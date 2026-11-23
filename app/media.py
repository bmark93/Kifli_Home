from __future__ import annotations

import base64
import uuid
from pathlib import Path

import httpx

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB

MIME_TO_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def detect_extension(content: bytes, mime_type: str = "", filename: str = "") -> str:
    mt = (mime_type or "").split(";")[0].strip().lower()
    if mt in MIME_TO_EXT:
        return MIME_TO_EXT[mt]

    # Magic-byte ellenőrzés
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return ".webp"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"

    ext = Path(filename or "").suffix.lower()
    if ext in (".jpg", ".jpeg"):
        return ".jpg"
    if ext in (".png", ".webp", ".gif"):
        return ext
    raise ValueError("Nem támogatott képformátum! Használj JPG, PNG, WebP vagy GIF képet.")


def save_recipe_image_bytes(
    data_dir: Path,
    content: bytes,
    mime_type: str = "",
    filename: str = "",
) -> str:
    if not content:
        raise ValueError("Üres képfájl.")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("A kép túl nagy (maximum 8 MB engedélyezett).")

    ext = detect_extension(content, mime_type=mime_type, filename=filename)
    uploads_dir = data_dir / "uploads" / "recipes"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    out_name = f"{uuid.uuid4().hex}{ext}"
    (uploads_dir / out_name).write_bytes(content)
    return f"/uploads/recipes/{out_name}"


def save_recipe_image_base64(
    data_dir: Path, image_base64: str, mime_type: str = ""
) -> str:
    raw = image_base64.strip()
    if raw.startswith("data:") and "," in raw:
        header, raw = raw.split(",", 1)
        if not mime_type and ";" in header:
            mime_type = header[5:].split(";")[0]
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as exc:
        raise ValueError(f"Érvénytelen base64 kép adat: {exc}") from exc
    return save_recipe_image_bytes(data_dir, decoded, mime_type=mime_type)


async def download_and_save_recipe_image(data_dir: Path, url: str) -> str:
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        raise ValueError("Csak http:// vagy https:// kép URL támogatott.")
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        resp = await client.get(clean_url, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        content = resp.content
        mime = resp.headers.get("content-type", "")
    return save_recipe_image_bytes(data_dir, content, mime_type=mime, filename=clean_url.split("?")[0])
