"""Control de las slides armadas, sobre una salida ya generada.

Verifica lo que tiene que valer siempre, sea cual sea el álbum:

1. Hay un JPG por slide, y todos miden 1080x1350 (4:5, lo que Instagram usa en carrusel).
2. Todos llevan perfil sRGB embebido: sin eso, Instagram puede lavar los colores.
3. En las slides de una sola foto no quedó ninguna cara cortada por el recorte.
4. Dentro de un collage no se repite una foto, y ninguna foto aparece en dos slides.
5. Cada collage tiene tantas fotos como celdas su plantilla.

Uso:  python curator/test_montaje.py curator/salida/<boda>
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import montage

FALLAS: list[str] = []


def check(condition: bool, ok: str, bad: str) -> None:
    print(("  OK    " if condition else "  FALLA ") + (ok if condition else bad))
    if not condition:
        FALLAS.append(bad)


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("Uso: python curator/test_montaje.py <carpeta de salida>")
    out = Path(sys.argv[1]).expanduser().resolve()
    seleccion = json.loads((out / "seleccion.json").read_text(encoding="utf-8-sig"))
    slides = seleccion["slides"]
    print(f"{len(slides)} slides en {out / 'slides'}\n")

    # 1 y 2. archivos, tamaño y perfil de color
    faltan, mal_tamano, sin_srgb = [], [], []
    for s in slides:
        path = out / "slides" / f"{s['slide']:02d}.jpg"
        if not path.is_file():
            faltan.append(path.name)
            continue
        with Image.open(path) as im:
            if im.size != montage.CANVAS:
                mal_tamano.append(f"{path.name} {im.size}")
            icc = im.info.get("icc_profile")
        descripcion = ""
        if icc:
            try:
                descripcion = ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(icc)))
            except ImageCms.PyCMSError:
                pass
        if "srgb" not in (descripcion or "").lower():
            sin_srgb.append(path.name)
    check(not faltan, f"están los {len(slides)} JPG", f"faltan: {faltan}")
    check(not mal_tamano, f"todos miden {montage.CANVAS[0]}x{montage.CANVAS[1]}",
          f"tamaño equivocado: {mal_tamano}")
    check(not sin_srgb, "todos llevan perfil sRGB", f"sin perfil sRGB: {sin_srgb}")

    # 3. caras cortadas en las slides de una sola foto
    cortadas = [(s["slide"], c) for s in slides
                if s.get("plantilla") in ("sola", "entera")
                for c in s.get("sujeto_cortado", []) if c > montage.MAX_SUBJECT_CUT]
    check(not cortadas, "ninguna slide sola corta caras",
          f"slides solas con caras cortadas: {cortadas}")

    # 4. nada repetido
    vistas: dict[str, int] = {}
    repetidas_dentro, repetidas_entre = [], []
    for s in slides:
        fotos = s.get("fotos", [s["rel"]])
        if len(set(fotos)) != len(fotos):
            repetidas_dentro.append(s["slide"])
        for rel in fotos:
            if rel in vistas and vistas[rel] != s["slide"]:
                repetidas_entre.append((rel, vistas[rel], s["slide"]))
            vistas[rel] = s["slide"]
    check(not repetidas_dentro, "ningún collage repite una foto",
          f"collages con una foto repetida: {repetidas_dentro}")
    check(not repetidas_entre, f"ninguna foto aparece en dos slides ({len(vistas)} fotos distintas)",
          f"fotos en más de una slide: {repetidas_entre}")

    # 5. collages completos
    incompletos = [(s["slide"], s["plantilla"], len(s["fotos"])) for s in slides
                   if s.get("plantilla") in montage.TEMPLATES
                   and len(s["fotos"]) != len(montage.TEMPLATES[s["plantilla"]]["celdas"])]
    check(not incompletos, "cada collage tiene una foto por celda",
          f"collages incompletos: {incompletos}")

    tipos: dict[str, int] = {}
    for s in slides:
        tipos[s.get("plantilla", "?")] = tipos.get(s.get("plantilla", "?"), 0) + 1
    print(f"\n  reparto: {', '.join(f'{k} {v}' for k, v in sorted(tipos.items()))}")
    print()
    if FALLAS:
        print(f"{len(FALLAS)} propiedades no se cumplen")
        return 1
    print("Todas las propiedades del montaje se cumplen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
