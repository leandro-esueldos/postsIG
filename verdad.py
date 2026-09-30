"""Arma la verdad de un casamiento: qué fotos del álbum usó en cada slide que publicó.

Uso:
  python curator/verdad.py "D:/bodas/MJ" "D:/bodas/MJ_IG"
  python curator/verdad.py "D:/bodas/MJ" "D:/bodas/MJ_IG" --revisar     arma además una hoja para mirar

La carpeta del post son las slides tal como las subió (1.png, 2.png, 7b.png…). Deja
`publicadas.json` adentro del caché del álbum. Eso es lo que usan:

- evaluar.py, para medir cuántas de sus elegidas elige también la herramienta;
- train_estilo.py, para entrenar con positivos (lo que publicó) y negativos (el resto).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import album as album_lib
from lib import matcher

EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def slide_order(path: Path) -> tuple:
    m = re.match(r"(\d+)(.*)", path.stem)
    return (int(m.group(1)), m.group(2)) if m else (10_000, path.stem)


def review_sheet(slides: list[Path], found: dict, album: Path, dest: Path) -> None:
    """Cada slide al lado de las fotos del álbum que se encontraron adentro, para chequear."""
    fila_h, lado = 300, 240
    filas = []
    for slide in slides:
        fotos = found.get(slide.name, [])
        ancho = lado + 12 + max(len(fotos), 1) * (lado + 8)
        fila = Image.new("RGB", (ancho, fila_h + 24), (24, 22, 20))
        s = Image.open(slide).convert("RGB")
        s.thumbnail((lado, fila_h))
        fila.paste(s, (0, 0))
        d = ImageDraw.Draw(fila)
        d.text((4, fila_h + 6), f"slide {slide.stem}", fill=(240, 200, 120))
        for i, f in enumerate(fotos):
            with Image.open(album / f["foto"]) as src:
                src.draft("RGB", (lado * 2, lado * 2))
                t = src.convert("RGB")
            t.thumbnail((lado, fila_h))
            x = lado + 12 + i * (lado + 8)
            fila.paste(t, (x, 0))
            d.text((x + 2, fila_h + 6), f"{f['foto']} ({f['coherentes']})", fill=(230, 225, 215))
        if not fotos:
            d.text((lado + 16, fila_h // 2), "no se encontró en el álbum", fill=(230, 120, 110))
        filas.append(fila)
    ancho = max(f.width for f in filas)
    hoja = Image.new("RGB", (ancho, sum(f.height + 6 for f in filas)), (18, 16, 14))
    y = 0
    for f in filas:
        hoja.paste(f, (0, y))
        y += f.height + 6
    hoja.save(dest, "JPEG", quality=82)


def main() -> None:
    parser = argparse.ArgumentParser(description="Qué fotos del álbum publicó en cada slide")
    parser.add_argument("album", help="carpeta con las fotos del casamiento")
    parser.add_argument("post", help="carpeta con las slides que publicó")
    parser.add_argument("--revisar", action="store_true", help="arma revision.jpg para chequear a ojo")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    album = Path(args.album).expanduser().resolve()
    post = Path(args.post).expanduser().resolve()
    cache = album / album_lib.CACHE_DIRNAME
    cache.mkdir(parents=True, exist_ok=True)

    fotos, _ = album_lib.scan(album)
    slides = sorted((p for p in post.iterdir() if p.suffix.lower() in EXTENSIONS), key=slide_order)
    print(f"Álbum: {len(fotos)} fotos · post: {len(slides)} slides", flush=True)

    t = time.time()
    index = matcher.AlbumIndex(fotos, cache / "puntos.npz", workers=args.workers)
    print(f"  índice de puntos: {len(index.descriptors)} en {time.time() - t:.0f}s", flush=True)

    found: dict[str, list] = {}
    for slide in slides:
        found[slide.name] = index.find(slide)
        nombres = ", ".join(f["foto"] for f in found[slide.name]) or "—"
        print(f"  {slide.stem:>4}: {len(found[slide.name])} fotos  {nombres}", flush=True)

    publicadas = sorted({f["foto"] for fs in found.values() for f in fs})
    vacias = [s.stem for s in slides if not found[s.name]]
    print(f"En total: {len(publicadas)} fotos del álbum aparecen en el post "
          f"({len(publicadas) / max(len(fotos), 1):.1%} del álbum)", flush=True)
    if vacias:
        print(f"  ojo: en las slides {', '.join(vacias)} no se encontró ninguna foto del álbum", flush=True)

    rel = {p.name: p.relative_to(album).as_posix() for p in fotos}
    payload = {
        "album": str(album),
        "post": str(post),
        "generado": datetime.now().isoformat(timespec="seconds"),
        "slides": [{"slide": s.stem, "fotos": [{**f, "rel": rel.get(f["foto"], f["foto"])}
                                              for f in found[s.name]]} for s in slides],
        "publicadas": [rel.get(n, n) for n in publicadas],
    }
    (cache / "publicadas.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    print(f"Guardado en {cache / 'publicadas.json'}", flush=True)

    if args.revisar:
        review_sheet(slides, found, album, cache / "revision.jpg")
        print(f"Hoja para revisar: {cache / 'revision.jpg'}", flush=True)


if __name__ == "__main__":
    main()
