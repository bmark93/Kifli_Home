from __future__ import annotations

import datetime as dt
import json
import logging
from collections import defaultdict
from typing import Any

from app.db import Database, normalize_key
from app.kifli_mcp import KifliMCPManager

log = logging.getLogger("kifli_otthon.restock")


def _parse_iso_date(val: Any) -> dt.datetime | None:
    if not val:
        return None
    txt = str(val).strip()
    if not txt:
        return None
    for candidate in (txt, txt.replace("Z", "+00:00")):
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed
        except ValueError:
            continue
    return None


def compute_restock_predictions_from_events(
    events: list[dict[str, Any]],
    active_general_keys: set[str],
    now: dt.datetime | None = None,
    min_occurrences: int = 2,
) -> list[dict[str, Any]]:
    """
    Tisztán determinisztikus (0 AI token!) fogyás-előrejelző motor.
    Bemenet: [{name, ordered_at, kifli_product_id, brand_hint, source}]
    Kiszámolja minden ismétlődő termék átlagos újrarendelési ciklusát és sürgősségét.
    """
    ref_now = now or dt.datetime.now(dt.timezone.utc)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for ev in events:
        name = str(ev.get("name", "")).strip()
        ts = _parse_iso_date(ev.get("ordered_at"))
        if not name or not ts:
            continue
        key = str(ev.get("kifli_product_id") or normalize_key(name))
        grouped[key].append(
            {
                "name": name,
                "ts": ts,
                "kifli_product_id": str(ev.get("kifli_product_id") or ""),
                "brand_hint": str(ev.get("brand_hint") or ""),
                "source": str(ev.get("source") or "kifli"),
            }
        )

    suggestions: list[dict[str, Any]] = []
    for _key, rows in grouped.items():
        rows.sort(key=lambda x: x["ts"])
        # Ugyanazon a napon belüli duplikátumok összevonása
        dedup: list[dict[str, Any]] = []
        for r in rows:
            if dedup and abs((r["ts"] - dedup[-1]["ts"]).total_seconds()) < 3600 * 12:
                continue
            dedup.append(r)

        if len(dedup) < min_occurrences:
            continue

        latest = dedup[-1]
        if normalize_key(latest["name"]) in active_general_keys:
            continue

        intervals = [
            max(1.0, (dedup[i]["ts"] - dedup[i - 1]["ts"]).total_seconds() / 86400.0)
            for i in range(1, len(dedup))
        ]
        avg_days = round(sum(intervals) / len(intervals), 1)
        days_since = round(max(0.0, (ref_now - latest["ts"]).total_seconds() / 86400.0), 1)
        ratio = round(days_since / max(avg_days, 1.0), 2)

        if ratio >= 0.75:
            status = "overdue" if ratio >= 1.0 else "soon"
            suggestions.append(
                {
                    "name": latest["name"],
                    "kifli_product_id": latest["kifli_product_id"],
                    "brand_hint": latest["brand_hint"],
                    "source": latest["source"],
                    "order_count": len(dedup),
                    "avg_interval_days": avg_days,
                    "days_since_last": days_since,
                    "due_ratio": ratio,
                    "urgency": status,
                    "reason": (
                        f"Átlagosan {int(round(avg_days))} naponta veszed · "
                        f"{int(round(days_since))} napja vetted utoljára"
                    ),
                }
            )

    suggestions.sort(key=lambda x: x["due_ratio"], reverse=True)
    return suggestions[:15]


async def analyze_smart_restock(
    db: Database, kifli: KifliMCPManager
) -> dict[str, Any]:
    """
    0 AI-tokenes elemzés: összefésüli a Kifli.hu korábbi rendeléseit (`fetch_orders`)
    és a helyi `general_items` (`ORDERED`) előzményeket.
    """
    active_keys = {
        normalize_key(g["name"]) for g in db.list_general_items(include_ordered=False)
    }
    events: list[dict[str, Any]] = []
    kifli_orders_analyzed = 0

    # 1. Helyi ORDERED háztartási előzmények
    for g in db.list_general_items(include_ordered=True):
        if g.get("status") == "ORDERED" and g.get("ordered_at"):
            events.append(
                {
                    "name": g.get("kifli_product_name") or g["name"],
                    "ordered_at": g["ordered_at"],
                    "kifli_product_id": g.get("kifli_product_id", ""),
                    "brand_hint": g.get("brand_hint", ""),
                    "source": "local_history",
                }
            )

    # 2. Kifli.hu MCP korábbi rendelések (ha be van jelentkezve)
    st = await kifli.get_status()
    if st.get("authenticated"):
        try:
            raw = await kifli.call_tool_untruncated(
                "fetch_orders",
                {
                    "limit": 15,
                    "context": "Analyze past grocery orders to predict household restock needs",
                },
            )
            payload = json.loads(raw)
            data = payload.get("data")
            orders: list[dict[str, Any]] = []
            if isinstance(data, list):
                orders = data
            elif isinstance(data, dict):
                orders = data.get("orders") or data.get("items") or []

            kifli_orders_analyzed = len(orders)
            for order in orders:
                order_ts = (
                    order.get("deliveredAt")
                    or order.get("orderTime")
                    or order.get("createdAt")
                    or order.get("date")
                )
                items = order.get("items") or order.get("products") or []
                if isinstance(items, dict):
                    items = list(items.values())
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    pname = it.get("productName") or it.get("name") or ""
                    pid = it.get("productId") or it.get("id") or ""
                    if pname:
                        events.append(
                            {
                                "name": pname,
                                "ordered_at": order_ts,
                                "kifli_product_id": str(pid),
                                "brand_hint": "",
                                "source": "kifli_orders",
                            }
                        )
        except Exception as exc:
            log.warning("Smart Restock Kifli fetch_orders hiba (folytatás helyi adatokkal): %s", exc)

    predictions = compute_restock_predictions_from_events(events, active_general_keys=active_keys)
    return {
        "kifli_connected": bool(st.get("authenticated")),
        "kifli_orders_analyzed": kifli_orders_analyzed,
        "local_events_analyzed": sum(1 for e in events if e["source"] == "local_history"),
        "suggestions": predictions,
    }
