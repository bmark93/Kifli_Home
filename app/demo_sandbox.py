from __future__ import annotations

import copy
from typing import Any

from app.db import Database

# Valósághű, 0 Ft-os szimulált Kifli.hu kosár a Demo Sandbox módhoz (valódi Kifli termékadatokkal)
INITIAL_DEMO_CART_ITEMS: list[dict[str, Any]] = [
    {
        "product_id": 16321,
        "name": "Magyar Tej ESL Tej 2,8%",
        "quantity": 2,
        "unit_price": 469,
        "original_unit_price": 469,
        "sale_percent": 0,
        "volume": "1",
        "unit": "l",
        "category": "Tejtermék és tojás",
        "image_url": "https://cdn.kifli.hu/images/grocery/products/16321/16321-1743115021084.jpeg",
        "kifli_url": "https://www.kifli.hu/16321-magyar-tej-esl-tej-2-8",
    },
    {
        "product_id": 59741,
        "name": "Magyar Tejföl 20% 330 g",
        "quantity": 2,
        "unit_price": 599,
        "original_unit_price": 649,
        "sale_percent": 8,
        "volume": "330",
        "unit": "g",
        "category": "Tejtermék és tojás",
        "image_url": "https://cdn.kifli.hu/images/grocery/products/59741/59741-1713265694542.jpeg",
        "kifli_url": "https://www.kifli.hu/59741-magyar-tejfol-20",
    },
    {
        "product_id": 82587,
        "name": "Pick Békebeli Gépsonka 100 g",
        "quantity": 2,
        "unit_price": 799,
        "original_unit_price": 899,
        "sale_percent": 11,
        "volume": "100",
        "unit": "g",
        "category": "Felvágott és Készétel",
        "image_url": "",
        "kifli_url": "https://www.kifli.hu/",
    },
    {
        "product_id": 92649,
        "name": "Barilla Spagetti n.5 tészta 500 g",
        "quantity": 2,
        "unit_price": 899,
        "original_unit_price": 899,
        "sale_percent": 0,
        "volume": "500",
        "unit": "g",
        "category": "Tartós élelmiszer",
        "image_url": "",
        "kifli_url": "https://www.kifli.hu/",
    },
    {
        "product_id": 97249,
        "name": "Zewa Deluxe Camomile 3 rétegű papírzsebkendő",
        "quantity": 1,
        "unit_price": 949,
        "original_unit_price": 1099,
        "sale_percent": 14,
        "volume": "90",
        "unit": "db",
        "category": "Vegyi- és papíráru",
        "image_url": "",
        "kifli_url": "https://www.kifli.hu/",
    },
    {
        "product_id": 70101,
        "name": "Friss csirkemell filé 500 g",
        "quantity": 2,
        "unit_price": 1490,
        "original_unit_price": 1690,
        "sale_percent": 12,
        "volume": "500",
        "unit": "g",
        "category": "Hús és hal",
        "image_url": "",
        "kifli_url": "https://www.kifli.hu/",
    },
]

DEMO_PRIVATE_LABEL_SWAPS: dict[int, dict[str, Any]] = {
    16321: {
        "new_product_id": 97506,
        "new_name": "Miil ESL Tej 2,8% (laktózmentes opcióval)",
        "new_brand": "Miil",
        "new_amount": "1 l",
        "new_unit_price": 349,
    },
    59741: {
        "new_product_id": 98102,
        "new_name": "Miil Tejföl 20% 330 g",
        "new_brand": "Miil",
        "new_amount": "330 g",
        "new_unit_price": 449,
    },
    82587: {
        "new_product_id": 98211,
        "new_name": "Dacello Prémium Gépsonka 100 g",
        "new_brand": "Dacello",
        "new_amount": "100 g",
        "new_unit_price": 549,
    },
    92649: {
        "new_product_id": 98305,
        "new_name": "Kitchin Olasz Spagetti 500 g",
        "new_brand": "Kitchin",
        "new_amount": "500 g",
        "new_unit_price": 549,
    },
    97249: {
        "new_product_id": 105944,
        "new_name": "Moddia 3 rétegű papírzsebkendő 100 db",
        "new_brand": "Moddia",
        "new_amount": "100 db",
        "new_unit_price": 599,
    },
}


class DemoCartSandbox:
    """Izolált, 0 AI-tokenes Kifli.hu kosár szimulátor a Demo módhoz."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = copy.deepcopy(INITIAL_DEMO_CART_ITEMS)

    def reset(self) -> dict[str, Any]:
        self._items = copy.deepcopy(INITIAL_DEMO_CART_ITEMS)
        return self.get_cart()

    def get_cart(self) -> dict[str, Any]:
        items_out: list[dict[str, Any]] = []
        total_price = 0
        total_savings = 0
        for it in self._items:
            qty = int(it["quantity"])
            up = int(it["unit_price"])
            op = int(it.get("original_unit_price") or up)
            line_total = qty * up
            total_price += line_total
            total_savings += max(0, (op - up) * qty)
            items_out.append({**it, "line_total": line_total})
        return {
            "connected": True,
            "is_demo_sandbox": True,
            "cart_id": 999999,
            "total_price": total_price,
            "total_savings": total_savings,
            "min_order_price": 12000,
            "can_checkout": total_price >= 12000,
            "item_count": len(items_out),
            "total_units": sum(int(i["quantity"]) for i in items_out),
            "items": items_out,
        }

    def update_item(self, product_id: int, quantity: int) -> dict[str, Any]:
        if quantity <= 0:
            self._items = [i for i in self._items if int(i["product_id"]) != int(product_id)]
        else:
            for it in self._items:
                if int(it["product_id"]) == int(product_id):
                    it["quantity"] = int(quantity)
                    break
        return self.get_cart()

    def clear(self) -> dict[str, Any]:
        self._items = []
        return self.get_cart()

    def apply_swaps(self, swaps: list[dict[str, Any]]) -> dict[str, Any]:
        applied = 0
        for sw in swaps:
            old_id = int(sw["old_product_id"])
            new_id = int(sw["new_product_id"])
            new_qty = max(1, int(sw.get("new_quantity", 1)))
            meta = DEMO_PRIVATE_LABEL_SWAPS.get(old_id)
            for idx, it in enumerate(self._items):
                if int(it["product_id"]) == old_id:
                    new_unit = meta["new_unit_price"] if meta else max(199, int(it["unit_price"]) - 150)
                    new_name = meta["new_name"] if meta else f"Kifli Sajátmárkás {it['name']}"
                    self._items[idx] = {
                        **it,
                        "product_id": new_id,
                        "name": new_name,
                        "quantity": new_qty,
                        "unit_price": new_unit,
                        "original_unit_price": new_unit,
                        "sale_percent": 0,
                    }
                    applied += 1
                    break
        return {"applied_count": applied, "cart": self.get_cart()}

    def optimize_private_label(self, db: Database, user_id: int) -> dict[str, Any]:
        prefs = db.list_product_preferences(user_id=user_id)
        fav_ids = {
            int(p["kifli_product_id"])
            for p in prefs
            if str(p.get("kifli_product_id", "")).isdigit()
        }

        auto_swaps: list[dict[str, Any]] = []
        fav_proposals: list[dict[str, Any]] = []

        for it in list(self._items):
            old_id = int(it["product_id"])
            meta = DEMO_PRIVATE_LABEL_SWAPS.get(old_id)
            if not meta:
                continue
            qty = int(it["quantity"])
            old_total = int(it["unit_price"]) * qty
            new_total = int(meta["new_unit_price"]) * qty
            savings = old_total - new_total
            if savings < 20:
                continue
            entry = {
                "old_product_id": old_id,
                "old_name": it["name"],
                "old_quantity": qty,
                "old_price_ft": old_total,
                "old_image_url": it.get("image_url", ""),
                "new_product_id": int(meta["new_product_id"]),
                "new_name": meta["new_name"],
                "new_brand": meta["new_brand"],
                "new_amount": meta["new_amount"],
                "new_quantity": qty,
                "new_unit_price_ft": int(meta["new_unit_price"]),
                "new_price_ft": new_total,
                "savings_ft": savings,
            }
            if old_id in fav_ids:
                fav_proposals.append(entry)
            else:
                auto_swaps.append(entry)

        if auto_swaps:
            self.apply_swaps(auto_swaps)
        auto_savings = sum(int(s["savings_ft"]) for s in auto_swaps)
        return {
            "cart": self.get_cart(),
            "auto_swapped": auto_swaps,
            "auto_savings_ft": auto_savings,
            "favorite_proposals": fav_proposals,
            "message": (
                f"Demo kosár: {len(auto_swaps)} terméket azonnal Kifli saját márkára cseréltünk (-{auto_savings} Ft)!"
                if auto_swaps
                else (
                    "Csak a kedvelt márkáidhoz találtunk olcsóbb Kifli saját márkát — dönts róluk a felugró ablakban!"
                    if fav_proposals
                    else "A demo kosárban már minden termék Kifli saját márkás! 🎉"
                )
            ),
        }
