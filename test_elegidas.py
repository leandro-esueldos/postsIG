"""Control del modo "con mis elegidas": que entren todas, bien repartidas, sin fotos reales.

Arma casamientos de mentira (sólo metadatos: tamaño, hora, capítulo) y verifica:

1. Entran todas las elegidas, cada una una sola vez, en 20 slides como mucho.
2. Cada collage tiene tantas fotos como celdas su plantilla, y las plantillas que sólo
   funcionan con apaisadas (apilados, grilla de 6) no llevan verticales.
3. Las marcadas "sola" van solas.
4. Con pocas fotos, las verticales van solas (sobra lugar) y las apaisadas se juntan.
5. Con más de las que entran, avisa y deja afuera las de menor puntaje, no cualquiera.
6. Correrlo dos veces da lo mismo, y los cambios a mano pasan a la lista.

Uso:  python curator/test_elegidas.py
"""
from __future__ import annotations

import json
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import elegidas, montage
from lib.album import Photo

FALLAS: list[str] = []
CONFIG = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8-sig"))


def check(condition: bool, ok: str, bad: str) -> None:
    print(("  OK    " if condition else "  FALLA ") + (ok if condition else bad))
    if not condition:
        FALLAS.append(bad)


def casamiento(n: int, semilla: int, verticales: float = 0.4) -> list[Photo]:
    rng = random.Random(semilla)
    t = datetime(2026, 3, 14, 15, 0)
    capitulos = ["preparativos", "ceremonia", "retratos", "fiesta"]
    fotos = []
    for i in range(n):
        t += timedelta(minutes=rng.choice([1, 2, 4, 9, 25]))
        vertical = rng.random() < verticales
        w, h = (4000, 6000) if vertical else (6000, 4000)
        parte = min(3, i * 4 // n)
        p = Photo(rel=f"DSC_{i:04d}.jpg", name=f"DSC_{i:04d}", key=f"{i:016x}", width=w, height=h,
                  mtime=0.0, size=0, taken=t.isoformat())
        p.metrics = {"score": round(rng.uniform(0.3, 1.0), 3), "capitulo": capitulos[parte],
                     "bloque": parte * 2 + (i % 2), "kind": rng.choice(["retrato", "pareja", "detalle", "grupo"]),
                     "hash": rng.getrandbits(64)}
        fotos.append(p)
    return fotos


def propiedades(slides: list[dict], fotos: list[Photo], afuera: list, solas: set, tope: int, cual: str) -> None:
    usadas = [p.name for s in slides for p in s["fotos"]]
    check(len(slides) <= tope, f"{cual}: {len(slides)} slides, dentro del tope de {tope}",
          f"{cual}: {len(slides)} slides, más que el tope de {tope}")
    check(len(usadas) == len(set(usadas)), f"{cual}: ninguna foto repetida",
          f"{cual}: hay fotos repetidas")
    check(set(usadas) | {p.name for p in afuera} == {p.name for p in fotos},
          f"{cual}: entran todas ({len(usadas)}{f', {len(afuera)} afuera con aviso' if afuera else ''})",
          f"{cual}: se perdieron fotos sin aviso")
    malas = []
    for s in slides:
        if s["plantilla"]:
            t = montage.TEMPLATES[s["plantilla"]]
            if len(s["fotos"]) != len(t["celdas"]):
                malas.append(f"slide {s['slide']}: {len(s['fotos'])} fotos en {s['plantilla']}")
            if s["plantilla"] in elegidas.ONLY_LANDSCAPE and any(p.height > p.width for p in s["fotos"]):
                malas.append(f"slide {s['slide']}: vertical en {s['plantilla']}")
            if solas & {p.name for p in s["fotos"]}:
                malas.append(f"slide {s['slide']}: una marcada 'sola' quedó en collage")
    check(not malas, f"{cual}: collages completos y con la orientación que piden",
          f"{cual}: " + "; ".join(malas[:4]))
    numeros = [s["slide"] for s in slides]
    check(numeros == list(range(1, len(slides) + 1)), f"{cual}: numeradas de corrido",
          f"{cual}: numeración rota {numeros}")


def main() -> int:
    print("1. Un post normal: 55 elegidas")
    fotos = casamiento(55, 1)
    slides, afuera, aviso = elegidas.pack(fotos, set(), 20, CONFIG)
    propiedades(slides, fotos, afuera, set(), 20, "55 fotos")
    otra, _, _ = elegidas.pack(fotos, set(), 20, CONFIG)
    check([[p.name for p in s["fotos"]] for s in slides] == [[p.name for p in s["fotos"]] for s in otra],
          "dos veces da lo mismo", "dos corridas iguales dieron posts distintos")
    horas = [min(p.taken for p in s["fotos"]) for s in slides]
    check(horas == sorted(horas), "las slides siguen el orden del día", "las slides no van en orden")

    print("2. Pocas fotos: 12 elegidas")
    fotos = casamiento(12, 2)
    slides, afuera, _ = elegidas.pack(fotos, set(), 20, CONFIG)
    propiedades(slides, fotos, afuera, set(), 20, "12 fotos")
    verticales_en_collage = [p.name for s in slides if s["plantilla"] for p in s["fotos"] if p.height > p.width]
    check(not verticales_en_collage, "con lugar de sobra, las verticales van solas",
          f"verticales metidas en collage sin necesidad: {verticales_en_collage}")

    print("3. Marcadas 'sola'")
    fotos = casamiento(50, 3)
    solas = {fotos[i].name for i in (3, 10, 22, 40)}
    slides, afuera, _ = elegidas.pack(fotos, solas, 20, CONFIG)
    propiedades(slides, fotos, afuera, solas, 20, "50 fotos, 4 solas")

    print("4. Más de las que entran: 140 elegidas, todas verticales")
    fotos = casamiento(140, 4, verticales=1.0)
    slides, afuera, aviso = elegidas.pack(fotos, set(), 20, CONFIG)
    propiedades(slides, fotos, afuera, set(), 20, "140 fotos")
    check(bool(aviso) and bool(afuera), f"avisa: {aviso[:70]}…", "no avisó que sobraban fotos")
    if afuera:
        peor_adentro = min(p.metrics["score"] for s in slides for p in s["fotos"])
        mejor_afuera = max(p.metrics["score"] for p in afuera)
        check(mejor_afuera <= peor_adentro + 1e-9, "las que quedan afuera son las de menor puntaje",
              "quedó afuera una foto mejor que otras que entraron")

    print("5. Tope más chico: 30 elegidas en 10 slides")
    fotos = casamiento(30, 5)
    slides, afuera, _ = elegidas.pack(fotos, set(), 10, CONFIG)
    propiedades(slides, fotos, afuera, set(), 10, "30 fotos en 10")

    print("6. Cambios a mano")
    fotos = casamiento(20, 6)
    por_nombre = {p.name.lower(): p for p in fotos}
    slides, _, _ = elegidas.pack(fotos, set(), 20, CONFIG)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "seleccion.json").write_text(json.dumps({"slides": [
            {"slide": s["slide"], "detalle": [{"name": p.name} for p in s["fotos"]]} for s in slides]}))
        collage = next(s for s in slides if len(s["fotos"]) > 1)
        (tmp / "cambios.txt").write_text(f"# comentario\n1 fuera\n{collage['slide']} sola\n- DSC_0005\n+ DSC_0005\n")
        items = [(p.name, False) for p in fotos]
        nuevos, hecho = elegidas.aplicar_cambios(tmp / "cambios.txt", tmp / "seleccion.json", items, por_nombre)
        nombres = {n for n, _ in nuevos}
        primera = {p.name for p in slides[0]["fotos"]}
        check(not (primera & nombres), "«1 fuera» saca las fotos de la slide 1", "«1 fuera» no sacó nada")
        marcadas = {n for n, s in nuevos if s}
        check({p.name for p in collage["fotos"]} - primera <= marcadas,
              "«N sola» marca las fotos del collage", "«N sola» no marcó las fotos")
        check("DSC_0005" in nombres or "DSC_0005" in primera, "«- foto» y «+ foto» se aplican en orden",
              "«+ foto» no volvió a sumar la foto")
        resto = (tmp / "cambios.txt").read_text()
        check(all(l.startswith("#") for l in resto.splitlines() if l.strip()),
              "los cambios quedan marcados como aplicados (no se repiten)", "quedaron cambios sin marcar")

    print()
    if FALLAS:
        print(f"{len(FALLAS)} fallas")
        return 1
    print("Todo bien")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
