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
# Los renglones con que se entrenó el modelo, para que cada entrenamiento sume a los anteriores en
# vez de reemplazarlos: los álbumes viejos pueden no estar en esta máquina (35 GB), pero lo que se
# aprendió de ellos no se tiene que perder
DATOS = ROOT / "datos_preferencia.npz"
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
        from lib import preference as pref_lib
        publicadas = pref_lib.etiquetas(album)
        if not publicadas:
            print(f"  {album.name}: sin publicadas.json ni elegidas.json, correr antes verdad.py "
                  f"o elegir sus fotos desde la interfaz", flush=True)
            continue
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
    parser.add_argument("--desde-cero", action="store_true",
                        help="no suma lo aprendido antes: entrena sólo con lo que se pasa ahora")
    args = parser.parse_args()

    out = Path(args.out).expanduser().resolve()
    # Los recortes de las celdas son fotos de clientes y sólo sirven para calcular el embedding:
    # van a una carpeta temporal que se borra sola, no al repo
    with tempfile.TemporaryDirectory(prefix="curador-") as tmp:
        build(args, out, Path(tmp))
    if args.modelo:
        entrenar_modelo([Path(a).expanduser().resolve() for a in args.albumes], args.l2,
                        args.desde_cero)


def respaldar(path: Path) -> None:
    """Antes de pisar un archivo aprendido, deja una copia al lado (.anterior)."""
    if path.is_file():
        import shutil
        shutil.copy2(path, path.with_name(path.stem + ".anterior" + path.suffix))


def entrenar_modelo(albumes: list[Path], l2: float, desde_cero: bool = False) -> None:
    """Entrena el modelo de preferencia con todos los casamientos etiquetados que haya.

    Se entrena con todo a propósito: es el modelo que se usa en un casamiento nuevo. Para medir
    cuánto acierta hay que usar validacion.py, que lo reentrena dejando cada casamiento afuera.
    """
    import json as _json

    from lib import embed as _embed
    from lib import preference as pref_lib

    config = _json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    salidas = Path(config.get("interfaz", {}).get("salida", ROOT / "salida")).expanduser()
    if not salidas.is_dir():
        salidas = ROOT / "salida"

    def cargar(album: Path) -> dict:
        photos = list(album_lib.load_index(album / album_lib.CACHE_DIRNAME).values())
        return _embed.for_album(album, photos, album_lib.thumb_path)

    X, y, boda = pref_lib.dataset(albumes, salidas, cargar)
    nuevos = set(boda.tolist())
    if not desde_cero and DATOS.is_file():
        # Lo aprendido antes se conserva; un casamiento que se vuelve a pasar reemplaza al suyo
        previo = np.load(DATOS)
        quedan = ~np.isin(previo["boda"], list(nuevos))
        if quedan.any():
            print(f"  se suma lo aprendido antes: {int(quedan.sum())} momentos de "
                  f"{len(set(previo['boda'][quedan].tolist()))} casamientos", flush=True)
            X = np.concatenate([previo["X"][quedan].astype(np.float64), X]) if len(X) else \
                previo["X"][quedan].astype(np.float64)
            y = np.concatenate([previo["y"][quedan], y])
            boda = np.concatenate([previo["boda"][quedan], boda])
    if not len(X) or not y.any():
        print("", flush=True)
        print("Sin álbumes etiquetados con análisis: no se pudo entrenar el modelo", flush=True)
        return

    destino = ROOT / "modelo_preferencia.json"
    casamientos = sorted(set(boda.tolist()))
    if destino.is_file() and not desde_cero:
        try:
            antes = set(pref_lib.Preference.load(destino).meta.get("casamientos", []))
        except (ValueError, json.JSONDecodeError):
            antes = set()
        perdidos = sorted(antes - set(casamientos))
        if perdidos:
            # El modelo actual sabe de casamientos que no están acá ni en datos_preferencia.npz:
            # reemplazarlo sería desaprender. Se deja como está y se explica cómo seguir.
            print("", flush=True)
            print(f"El modelo actual se entrenó también con {', '.join(perdidos)}, que no están en "
                  f"esta máquina ni en {DATOS.name}.", flush=True)
            print("  Para no perder lo aprendido, el modelo NO se reemplazó (las referencias sí se "
                  "actualizaron y ya suman lo nuevo).", flush=True)
            print(f"  Solución: en la máquina que tiene esos álbumes correr una vez "
                  f"'python curator/entrenar.py --modelo --albumes ...' y copiar {DATOS.name} acá. "
                  f"O, si de verdad se quiere empezar de nuevo: --desde-cero.", flush=True)
            return

    modelo = pref_lib.Preference.fit(X, y, l2=l2)
    modelo.meta["casamientos"] = casamientos
    modelo.meta["l2"] = l2
    respaldar(destino)
    modelo.save(destino)
    respaldar(DATOS)
    np.savez_compressed(DATOS, X=X.astype(np.float32), y=y, boda=boda)
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
    nombres = [p.name for p in paths]
    if out.is_file() and not args.desde_cero:
        # Se conservan las referencias de casamientos que esta vez no se pasaron (pueden no estar
        # en esta máquina); los que sí se pasaron se reemplazan enteros
        previo = np.load(out)
        quedan = ~np.isin(previo["origen"], list(set(origen)))
        if quedan.any():
            print(f"  se conservan {int(quedan.sum())} referencias de antes, de "
                  f"{len(set(previo['origen'][quedan].tolist()))} casamientos", flush=True)
            vectores = np.concatenate([previo["vectors"][quedan], vectores])
            origen = previo["origen"][quedan].tolist() + origen
            nombres = previo["names"][quedan].tolist() + nombres
    respaldar(out)
    np.savez_compressed(out, vectors=vectores, origen=np.array(origen), names=np.array(nombres))
    por_boda = {b: origen.count(b) for b in dict.fromkeys(origen)}
    print(f"Referencias: {len(origen)} fotos de {len(por_boda)} casamientos -> {out}", flush=True)
    print("  " + ", ".join(f"{b} {n}" for b, n in por_boda.items()), flush=True)


if __name__ == "__main__":
    main()
