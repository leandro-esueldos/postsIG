"""Los cambios que Diego le pide al post, en un archivo de texto al lado de las slides.

Es la mitad que faltaba del flujo: la herramienta propone, él mira post.jpg, y si quiere cambiar
algo escribe una línea en cambios.txt y vuelve a correr. No hace falta tocar código ni JSON.

    7 DSC_01234     la slide 7 pasa a ser esa foto (va sola)
    12 fuera        se saca la slide 12
    3 sola          la slide 3 va sola, sin collage

Cada cambio de foto se guarda además en correcciones.jsonl: "sacó ésta, puso aquélla" es
exactamente el dato que le falta al modelo de estilo para dejar de adivinar (ver fase 3).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PLANTILLA = """\
# Cambios al post. Una línea por cambio; las que empiezan con # no cuentan.
# Después de escribirlos, volver a armar el post del mismo álbum.
#
#   7 DSC_01234     la slide 7 pasa a ser esa foto (el nombre, sin .jpg)
#   12 fuera        se saca la slide 12
#   3 sola          la slide 3 va sola, sin collage
#
# Los nombres de las fotos están en seleccion.jpg, suplentes.jpg y contacto.jpg.
"""


def ensure_template(path: Path) -> None:
    if not path.is_file():
        path.write_text(PLANTILLA, encoding="utf-8")


def read(path: Path) -> tuple[list[tuple[int, str]], list[str]]:
    """Devuelve (cambios válidos, errores legibles)."""
    if not path.is_file():
        return [], []
    cambios, errores = [], []
    for numero, linea in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        partes = linea.split()
        if len(partes) != 2 or not partes[0].isdigit():
            errores.append(f"línea {numero}: «{linea}» no se entiende (va: número de slide y "
                           f"una foto, «fuera» o «sola»)")
            continue
        cambios.append((int(partes[0]), partes[1]))
    return cambios, errores


def apply(slides: list[dict], cambios: list[tuple[int, str]], photos: list,
          album: Path, log: Path) -> list[str]:
    """Aplica los cambios sobre las slides elegidas. Devuelve lo que hizo, para mostrarlo."""
    por_nombre = {p.name.lower(): p for p in photos}
    por_slide = {s["slide"]: s for s in slides}
    hecho, fuera = [], set()

    for numero, accion in cambios:
        slide = por_slide.get(numero)
        if slide is None:
            hecho.append(f"slide {numero}: no existe, el post tiene {len(slides)}")
            continue
        clave = accion.lower()
        if clave == "fuera":
            fuera.add(numero)
            hecho.append(f"slide {numero}: fuera")
        elif clave == "sola":
            slide["forzar_sola"] = True
            hecho.append(f"slide {numero}: va sola")
        elif clave.removesuffix(".jpg") in por_nombre:
            nueva = por_nombre[clave.removesuffix(".jpg")]
            vieja = slide["photo"]
            if nueva is vieja:
                continue
            slide["photo"] = nueva
            slide["forzar_sola"] = True
            slide["motivo"] = "la eligió él"
            hecho.append(f"slide {numero}: {vieja.name} → {nueva.name}")
            _record(log, album, numero, slide["capitulo"], vieja, nueva)
        else:
            hecho.append(f"slide {numero}: no hay ninguna foto que se llame «{accion}»")

    if fuera:
        slides[:] = [s for s in slides if s["slide"] not in fuera]
        for nuevo, s in enumerate(slides, start=1):
            s["slide"] = nuevo
    return hecho


def _record(log: Path, album: Path, slide: int, capitulo: str, sale, entra) -> None:
    """Guarda la corrección como par de preferencia: entrenamiento para el modelo de estilo."""
    registro = {
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "album": str(album),
        "slide": slide,
        "capitulo": capitulo,
        "sale": sale.rel,
        "entra": entra.rel,
    }
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
