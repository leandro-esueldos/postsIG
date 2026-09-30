"""Reentrena con todo lo que hay: un solo comando (o el botón "Entrenar" de la interfaz).

Uso:  python curator/entrenar_todo.py
      python curator/entrenar_todo.py --albumes "/ruta/boda1" "/ruta/boda2"

Recorre los casamientos de la interfaz (los de la carpeta de config.json y los agregados a mano) y,
de cada uno, junta lo que diga qué eligió él:

- **Lo que publicó.** Si adentro del álbum hay una carpeta `publicado/` con las slides tal como
  las subió a Instagram (1.jpg, 2.jpg…), corre verdad.py para ubicar cada foto en el álbum.
- **Lo que eligió desde la interfaz.** El modo "con mis elegidas" deja `elegidas.json` en el caché
  del álbum: es la misma señal, sin esperar a que lo publique.

Después arma las referencias y el modelo de preferencia con todos (entrenar.py --modelo) y, si hay
dos casamientos o más, mide cuánto acierta dejando cada uno afuera (validacion.py). Cada casamiento
nuevo con etiqueta suma: con dos daba AUC 0.66, con seis 0.76 (ver PLAN.md).

Los álbumes que todavía no se analizaron se analizan antes (tarda unos minutos la primera vez).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import album as album_lib
from lib import preference as pref_lib

ROOT = Path(__file__).resolve().parent
RESUMEN = ROOT / "entrenamiento.json"
CARPETAS_POST = ("publicado", "publicadas", "instagram")
EXT_SLIDES = {".png", ".jpg", ".jpeg", ".webp"}


def correr(cmd: list[str]) -> int:
    """Corre un paso mostrando lo que imprime, línea por línea."""
    proceso = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                               encoding="utf-8", errors="replace", bufsize=1)
    assert proceso.stdout
    for linea in proceso.stdout:
        linea = linea.rstrip()
        if linea:
            print(f"    {linea}", flush=True)
    return proceso.wait()


def carpeta_post(album: Path) -> Path | None:
    for nombre in CARPETAS_POST:
        for d in (album / nombre, album / nombre.capitalize(), album / nombre.upper()):
            if d.is_dir() and any(p.suffix.lower() in EXT_SLIDES for p in d.iterdir()):
                return d
    return None


def al_dia(post: Path, verdad: Path) -> bool:
    """publicadas.json ya está y es más nuevo que todas las slides."""
    if not verdad.is_file():
        return False
    ultima = max((p.stat().st_mtime for p in post.iterdir()), default=0)
    return verdad.stat().st_mtime >= ultima


def albumes_de_la_interfaz() -> list[Path]:
    import interfaz
    return list(interfaz.albumes_por_nombre().values())


def main() -> int:
    parser = argparse.ArgumentParser(description="Reentrena la preferencia con todo lo que hay")
    parser.add_argument("--albumes", nargs="*", help="por defecto, los de la interfaz")
    parser.add_argument("--posts", help="carpeta con una subcarpeta de slides por casamiento, "
                        "sin álbum (por defecto entrenamiento.posts de config.json)")
    args = parser.parse_args()

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    albumes = ([Path(a).expanduser().resolve() for a in args.albumes] if args.albumes
               else albumes_de_la_interfaz())
    posts = args.posts or config.get("entrenamiento", {}).get("posts")
    posts_dir = Path(posts).expanduser() if posts else None
    if posts_dir is not None and not posts_dir.is_dir():
        posts_dir = None

    print(f"Entrenar con todo: {len(albumes)} casamientos en la lista", flush=True)
    etiquetados: list[Path] = []
    for album in albumes:
        cache = album / album_lib.CACHE_DIRNAME
        post = carpeta_post(album)
        if post is not None and not al_dia(post, cache / "publicadas.json"):
            print(f"  {album.name}: ubicando en el álbum las fotos de lo que publicó ({post.name}/)",
                  flush=True)
            if correr([sys.executable, str(ROOT / "verdad.py"), str(album), str(post)]) != 0:
                print(f"  {album.name}: verdad.py falló, se sigue con los demás", flush=True)
        etiquetas = pref_lib.etiquetas(album)
        if not etiquetas:
            print(f"  {album.name}: sin etiqueta todavía (ni publicado/ ni fotos elegidas)", flush=True)
            continue
        if pref_lib.analisis(album) is None or not (cache / "clip.npz").is_file():
            print(f"  {album.name}: analizando el álbum (la primera vez tarda unos minutos)",
                  flush=True)
            cmd = [sys.executable, str(ROOT / "curate.py"), str(album), "--sin-montaje",
                   "--out", str(cache / "entrenamiento")]
            if correr(cmd) != 0:
                print(f"  {album.name}: el análisis falló, se sigue con los demás", flush=True)
                continue
        print(f"  {album.name}: {len(etiquetas)} fotos elegidas por él", flush=True)
        etiquetados.append(album)

    if not etiquetados and posts_dir is None:
        print("", flush=True)
        print("No hay con qué entrenar todavía. Dos formas de sumar un casamiento:", flush=True)
        print("  1. Poner adentro del álbum una carpeta 'publicado' con las slides que subió.", flush=True)
        print("  2. Armar su post en modo 'con mis elegidas' desde la interfaz.", flush=True)
        return 1

    print("", flush=True)
    print(f"Entrenando con {len(etiquetados)} casamientos etiquetados"
          f"{' y los posts de ' + str(posts_dir) if posts_dir else ''}", flush=True)
    cmd = [sys.executable, str(ROOT / "entrenar.py"), "--modelo", "--albumes",
           *[str(a) for a in etiquetados]]
    if posts_dir:
        cmd += ["--posts", str(posts_dir)]
    if correr(cmd) != 0:
        print("El entrenamiento falló", flush=True)
        return 1

    if len(etiquetados) >= 2:
        print("", flush=True)
        print("Cuánto acierta en un casamiento que no vio (dejando cada uno afuera):", flush=True)
        correr([sys.executable, str(ROOT / "validacion.py"), "--albumes",
                *[str(a) for a in etiquetados]])
    else:
        print("Con un solo casamiento etiquetado no se puede medir cuánto acierta: hace falta otro.",
              flush=True)

    RESUMEN.write_text(json.dumps({
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "casamientos": [a.name for a in etiquetados],
        "posts": str(posts_dir) if posts_dir else None,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("", flush=True)
    print("Listo: los próximos posts ya usan el modelo nuevo.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
