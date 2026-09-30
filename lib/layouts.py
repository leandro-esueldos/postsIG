"""Descompone una slide publicada en sus celdas, para aprender las plantillas de sus posts.

Casi todos sus collages se arman con cortes de lado a lado: un apilado es un corte horizontal,
una grilla son dos, un mosaico son cortes dentro de cortes. Eso es una partición "de guillotina",
y se deshace al revés: se busca una línea de fondo que cruce la región entera, se parte, y se
repite en cada mitad. Lo que queda sin poder partirse es una celda.

No resuelve los collages desordenados (fotos giradas encima de otras) ni las polaroids: esos se
reconocen porque dejan una celda enorme con mucho fondo adentro, y se marcan aparte.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

BG_TOLERANCE = 14          # cuánto puede desviarse un píxel del fondo y seguir siendo fondo
GUTTER_FILL = 0.985        # qué fracción de una fila tiene que ser fondo para contar como separación
MIN_CELL = 60              # lado mínimo de una celda, en píxeles de la slide de 1080x1350
MIN_GUTTER = 2             # separación más fina que se acepta


def background(rgb: np.ndarray) -> tuple[int, int, int] | None:
    """Color de fondo, si las cuatro esquinas coinciden. None si la foto va a sangre."""
    h, w = rgb.shape[:2]
    corners = [rgb[:4, :4], rgb[:4, -4:], rgb[-4:, :4], rgb[-4:, -4:]]
    medians = [np.median(c.reshape(-1, 3), axis=0) for c in corners]
    spread = np.ptp(np.array(medians), axis=0).max()
    if spread > BG_TOLERANCE:
        return None
    color = np.median(np.array(medians), axis=0)
    # Un fondo de collage es neutro y claro u oscuro liso; una esquina de cielo o pasto, no
    if np.ptp(color) > 12:
        return None
    return tuple(int(v) for v in color)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs, start = [], None
    for i, value in enumerate(mask):
        if value and start is None:
            start = i
        elif not value and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


def _split(is_bg: np.ndarray, x0: int, y0: int, x1: int, y1: int, depth: int, out: list) -> None:
    region = is_bg[y0:y1, x0:x1]
    if region.size == 0:
        return
    rows = region.mean(axis=1) >= GUTTER_FILL
    cols = region.mean(axis=0) >= GUTTER_FILL

    # Recortar el fondo de los bordes: márgenes, no separaciones
    ys = np.where(~rows)[0]
    xs = np.where(~cols)[0]
    if len(ys) == 0 or len(xs) == 0:
        return
    ny0, ny1 = y0 + ys[0], y0 + ys[-1] + 1
    nx0, nx1 = x0 + xs[0], x0 + xs[-1] + 1
    if (ny0, ny1, nx0, nx1) != (y0, y1, x0, x1):
        _split(is_bg, nx0, ny0, nx1, ny1, depth, out)
        return

    # Buscar la separación interior más ancha, horizontal o vertical
    best = None
    for axis, mask, length in (("h", rows, y1 - y0), ("v", cols, x1 - x0)):
        for a, b in _runs(mask):
            if a < MIN_CELL or length - b < MIN_CELL or b - a < MIN_GUTTER:
                continue
            if best is None or (b - a) > best[2] - best[1]:
                best = (axis, a, b)
    if best is None or depth > 6:
        out.append((x0, y0, x1 - x0, y1 - y0))
        return
    axis, a, b = best
    if axis == "h":
        _split(is_bg, x0, y0, x1, y0 + a, depth + 1, out)
        _split(is_bg, x0, y0 + b, x1, y1, depth + 1, out)
    else:
        _split(is_bg, x0, y0, x0 + a, y1, depth + 1, out)
        _split(is_bg, x0 + b, y0, x1, y1, depth + 1, out)


def _white_lines(rgb: np.ndarray) -> np.ndarray:
    """Para los collages a sangre: las separaciones son líneas blancas aunque no haya margen."""
    gray = rgb.astype(np.int16).mean(axis=2)
    return gray >= 236


def decompose(path) -> dict:
    """Celdas de una slide publicada, con su fondo, margen y separación."""
    with Image.open(path) as src:
        rgb = np.asarray(src.convert("RGB"), dtype=np.int16)
    h, w = rgb.shape[:2]
    bg = background(rgb)
    if bg is not None:
        is_bg = (np.abs(rgb - np.array(bg)).max(axis=2) <= BG_TOLERANCE)
    else:
        is_bg = _white_lines(rgb)
    cells: list[tuple[int, int, int, int]] = []
    _split(is_bg, 0, 0, w, h, 0, cells)
    cells.sort(key=lambda c: (c[1] // 40, c[0]))

    # Una celda que tiene mucho fondo adentro no es una foto: es un collage desordenado o
    # una polaroid, que la guillotina no sabe partir
    irregular = False
    for x, y, cw, ch in cells:
        inside = is_bg[y:y + ch, x:x + cw].mean() if cw and ch else 0
        if bg is not None and inside > 0.12 and len(cells) <= 2:
            irregular = True

    margin = None
    if cells and bg is not None:
        left = min(c[0] for c in cells)
        top = min(c[1] for c in cells)
        right = w - max(c[0] + c[2] for c in cells)
        bottom = h - max(c[1] + c[3] for c in cells)
        margin = (left, top, right, bottom)
    return {"size": (w, h), "fondo": bg, "celdas": cells, "margen": margin, "irregular": irregular}


def signature(info: dict) -> str:
    """Nombre corto del tipo de armado, para agrupar slides iguales."""
    cells = info["celdas"]
    n = len(cells)
    if info["irregular"]:
        return "desordenado/polaroid"
    if n == 1:
        x, y, cw, ch = cells[0]
        w, h = info["size"]
        if cw * ch > 0.93 * w * h:
            return "sola"
        return "entera"
    if n == 2:
        a, b = cells
        return "apilado-2" if abs(a[0] - b[0]) < 30 else "lado-a-lado-2"
    rows = len({round(c[1] / 40) for c in cells})
    cols = len({round(c[0] / 40) for c in cells})
    if rows * cols == n:
        return f"grilla-{cols}x{rows}"
    return f"mosaico-{n}"
