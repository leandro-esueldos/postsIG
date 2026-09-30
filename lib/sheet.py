"""Hojas de contacto con puntaje, para aprobar o corregir la selección a ojo.

Sigue el mismo lenguaje que scripts/contact_sheet.py del sitio —fondo oscuro, etiqueta abajo—
pero agrega el puntaje, el tamaño del grupo de ráfaga y las marcas de cada foto. La corrección
que haga Diego sobre estas hojas es, además, el dato de entrenamiento de la fase 3.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (18, 16, 14)
PANEL = (30, 27, 24)
TEXT = (232, 228, 222)
MUTED = (150, 143, 134)
BAR_BG = (58, 53, 48)
BAR = (212, 168, 92)
CELL_W = 260
CELL_H = 325
LABEL_H = 34
HEADER_H = 46


def _font(size: int) -> ImageFont.ImageFont:
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:       # Pillow viejo: la fuente por defecto no acepta tamaño
        return ImageFont.load_default()


def _fit(path: Path, box: tuple[int, int]) -> Image.Image:
    with Image.open(path) as src:
        im = src.convert("RGB")
    scale = min(box[0] / im.width, box[1] / im.height)
    return im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)


def _cell(path: Path, caption: str, score: float | None, badge: str | None,
          small: ImageFont.ImageFont, tiny: ImageFont.ImageFont) -> Image.Image:
    cell = Image.new("RGB", (CELL_W, CELL_H + LABEL_H), PANEL)
    tile = _fit(path, (CELL_W, CELL_H))
    cell.paste(tile, ((CELL_W - tile.width) // 2, (CELL_H - tile.height) // 2))
    draw = ImageDraw.Draw(cell)

    if badge:
        width = draw.textlength(badge, font=tiny) + 10
        draw.rectangle([CELL_W - width - 6, 6, CELL_W - 6, 24], fill=(0, 0, 0))
        draw.text((CELL_W - width - 1, 9), badge, font=tiny, fill=TEXT)

    draw.rectangle([0, CELL_H, CELL_W, CELL_H + LABEL_H], fill=BACKGROUND)
    draw.text((6, CELL_H + 4), caption[:34], font=small, fill=TEXT)
    if score is not None:
        draw.rectangle([6, CELL_H + 24, CELL_W - 42, CELL_H + 28], fill=BAR_BG)
        width = int((CELL_W - 48) * max(0.0, min(1.0, score)))
        if width:
            draw.rectangle([6, CELL_H + 24, 6 + width, CELL_H + 28], fill=BAR)
        draw.text((CELL_W - 36, CELL_H + 19), f"{score:.2f}", font=tiny, fill=MUTED)
    return cell


def write(cells: list[dict], dest_dir: Path, prefix: str, title: str,
          cols: int = 6, rows: int = 6) -> list[Path]:
    """Arma las hojas paginadas. Cada celda es {path, caption, score, badge}."""
    if not cells:
        return []
    dest_dir.mkdir(parents=True, exist_ok=True)
    small, tiny = _font(15), _font(13)
    per_page = cols * rows
    pages = (len(cells) + per_page - 1) // per_page
    written = []

    for page in range(pages):
        chunk = cells[page * per_page:(page + 1) * per_page]
        used_rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * CELL_W, HEADER_H + used_rows * (CELL_H + LABEL_H)), BACKGROUND)
        draw = ImageDraw.Draw(sheet)
        heading = title if pages == 1 else f"{title}  ·  hoja {page + 1} de {pages}"
        draw.text((10, 14), heading, font=_font(19), fill=TEXT)
        for i, cell in enumerate(chunk):
            image = _cell(cell["path"], cell["caption"], cell.get("score"), cell.get("badge"), small, tiny)
            sheet.paste(image, ((i % cols) * CELL_W, HEADER_H + (i // cols) * (CELL_H + LABEL_H)))
        name = f"{prefix}.jpg" if pages == 1 else f"{prefix}-{page + 1:02d}.jpg"
        dest = dest_dir / name
        sheet.save(dest, "JPEG", quality=82)
        written.append(dest)
        print(f"  {dest.name}  {sheet.width}x{sheet.height}", flush=True)
    return written
