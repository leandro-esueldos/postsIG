"""Entrena con lo que él publicó: arma el conjunto de referencia de su criterio.

Uso:
  python curator/entrenar.py --posts "D:/datos/ig" --albumes "D:/datos/albumes/MJ" "D:/datos/albumes/XX"

- `--posts`: una carpeta con una subcarpeta por casamiento, cada una con las slides que subió
  (1.png, 2.png…). De cada slide se toman las fotos: la slide entera si va sola, y cada celda si
  es un collage armado con cortes rectos (los desordenados y las polaroid se saltean).
- `--albumes`: álbumes con `publicadas.json` (lo arma verdad.py). De ésos se toman las fotos
  originales que publicó, que son mejores referencias que las celdas recortadas.

Deja `curator/referencias.npz`: un embedding CLIP por foto publicada, con de qué casamiento es.
Cada foto de un álbum nuevo se puntúa por cuánto se parece a las tres más cercanas de
ese conjunto. Es la señal que mejor predijo lo que él elige en un casamiento que no vio: AUC 0.59
sobre MJ, contra 0.50 del puntaje técnico y 0.52 del modelo de estilo de la fase 3.

Cuantos más casamientos publicados se sumen, mejor: con cada uno se puede además medir, dejando
ese casamiento afuera, cuánto predice sobre uno que no vio.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import album as album_lib
from lib import embed, layouts

ROOT = Path(__file__).resolve().parent
REFERENCIAS = ROOT / "referencias.npz"
MIN_CELL = 200              # celdas más chicas que esto no describen bien la foto


def from_posts(folder: Path, work: Path) -> tuple[list[Path], list[str]]:
    """Fotos publicadas sacadas de las slides: la slide entera, o sus celdas."""
    paths, origen = [], []
    for boda in sorted(p for p in folder.iterdir() if p.is_dir()):
        for slide in sorted(boda.glob("*")):
            if slide.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            info = layouts.decompose(slide)
            if layouts.signature(info) == "desordenado/polaroid":
                continue
            with Image.open(slide) as src:
                im = src.convert("RGB")
            for i, (x, y, w, h) in enumerate(info["celdas"]):
                if w < MIN_CELL or h < MIN_CELL:
                    continue
                dest = work / f"{boda.name}_{slide.stem}_{i}.jpg"
                im.crop((x, y, x + w, y + h)).save(dest, "JPEG", quality=92)
                paths.append(dest)
                origen.append(boda.name)
    return paths, origen


def from_albums(albums: list[Path]) -> tuple[list[Path], list[str]]:
    """Las fotos originales que publicó de cada álbum etiquetado, en su miniatura del caché."""
    paths, origen = [], []
    for album in albums:
        verdad = album / album_lib.CACHE_DIRNAME / "publicadas.json"
        if not verdad.is_file():
            print(f"  {album.name}: sin publicadas.json, correr antes verdad.py", flush=True)
            continue
        publicadas = set(json.loads(verdad.read_text(encoding="utf-8-sig"))["publicadas"])
        indice = album_lib.load_index(album / album_lib.CACHE_DIRNAME)
        for rel in sorted(publicadas):
            photo = indice.get(rel)
            if photo is not None:
                paths.append(album_lib.thumb_path(album, photo))
                origen.append(album.name)
    return paths, origen


def main() -> None:
    parser = argparse.ArgumentParser(description="Arma el conjunto de referencia de su criterio")
    parser.add_argument("--posts", help="carpeta con una subcarpeta de slides por casamiento")
    parser.add_argument("--albumes", nargs="*", default=[], help="álbumes con publicadas.json")
    parser.add_argument("--out", default=str(REFERENCIAS))
    parser.add_argument("--modelo", action="store_true",
                        help="además entrena el modelo de preferencia con los álbumes etiquetados")
    parser.add_argument("--l2", type=float, default=10000.0,
                        help="regularización del modelo (10000 es lo que mejor midió)")
    args = parser.parse_args()

    out = Path(args.out).expanduser().resolve()
    # Los recortes de las celdas son fotos de clientes y sólo sirven para calcular el embedding:
    # van a una carpeta temporal que se borra sola, no al repo
    with tempfile.TemporaryDirectory(prefix="curador-") as tmp:
        build(args, out, Path(tmp))
    if args.modelo:
        entrenar_modelo([Path(a).expanduser().resolve() for a in args.albumes], args.l2)


def entrenar_modelo(albumes: list[Path], l2: float) -> None:
    """Entrena el modelo de preferencia con todos los casamientos etiquetados que haya.

    Se entrena con todo a propósito: es el modelo que se usa en un casamiento nuevo. Para medir
    cuánto acierta hay que usar validacion.py, que lo reentrena dejando cada casamiento afuera.
    """
    import json as _json

    from lib import embed as _embed
    from lib import preference as pref_lib

    config = _json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    salidas = Path(config.get("interfaz", {}).get("salida", ROOT / "salida")).expanduser()

    def cargar(album: Path) -> dict:
        photos = list(album_lib.load_index(album / album_lib.CACHE_DIRNAME).values())
        return _embed.for_album(album, photos, album_lib.thumb_path)

    X, y, boda = pref_lib.dataset(albumes, salidas, cargar)
    if not len(X) or not y.any():
        print("", flush=True)
        print("Sin álbumes etiquetados con análisis: no se pudo entrenar el modelo", flush=True)
        return
    modelo = pref_lib.Preference.fit(X, y, l2=l2)
    modelo.meta["casamientos"] = sorted(set(boda.tolist()))
    modelo.meta["l2"] = l2
    destino = ROOT / "modelo_preferencia.json"
    modelo.save(destino)
    print("", flush=True)
    print(f"Modelo de preferencia: {int(y.sum())} momentos publicados de {len(X)} en "
          f"{len(modelo.meta['casamientos'])} casamientos -> {destino}", flush=True)
    print(f"  {', '.join(modelo.meta['casamientos'])} · L2={l2}", flush=True)
    print("  para saber cuánto acierta: python curator/validacion.py", flush=True)


def build(args, out: Path, work: Path) -> None:
    paths: list[Path] = []
    origen: list[str] = []
    if args.posts:
        p, o = from_posts(Path(args.posts).expanduser().resolve(), work)
        print(f"De los posts: {len(p)} fotos publicadas ({len(set(o))} casamientos)", flush=True)
        paths += p
        origen += o
    albumes = [Path(a).expanduser().resolve() for a in args.albumes]
    p, o = from_albums(albumes)
    if albumes:
        print(f"De los álbumes etiquetados: {len(p)} fotos publicadas", flush=True)
    paths += p
    origen += o
    if not paths:
        sys.exit("No hay nada con qué entrenar: pasar --posts y/o --albumes")

    vectores = embed.compute(paths)
    np.savez_compressed(out, vectors=vectores, origen=np.array(origen),
                        names=np.array([p.name for p in paths]))
    por_boda = {b: origen.count(b) for b in dict.fromkeys(origen)}
    print(f"Referencias: {len(paths)} fotos de {len(por_boda)} casamientos -> {out}", flush=True)
    print("  " + ", ".join(f"{b} {n}" for b, n in por_boda.items()), flush=True)


if __name__ == "__main__":
    main()
