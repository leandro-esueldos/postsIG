"""Control del modo "con mis elegidas": que entren todas, bien repartidas, sin fotos reales.

Arma casamientos de mentira (sólo metadatos: tamaño, hora, capítulo) y verifica:

1. Entran todas las elegidas, cada una una sola vez, en 20 slides como mucho.
2. Cada collage tiene tantas fotos como celdas su plantilla, y las plantillas que sólo
   funcionan con apaisadas (apilados, grilla de 6) no llevan verticales.
3. Las marcadas "sola" van solas.
4. Con pocas fotos, las verticales van solas (sobra lugar) y las apaisadas se juntan.
5. Con más de las que entran, avisa y deja afuera las de menor puntaje, no cualquiera.
6. Correrlo dos veces da lo mismo, y los cambios a mano pasan a la lista.
7. Si él no dice cuántas slides, la cantidad sale de cuántas fotos son y de qué orientación.
8. Juntar dos slides las deja en un mismo collage, y elegir plantilla se respeta.

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


def escribir_post(carpeta: Path, slides: list[dict]) -> None:
    """Un seleccion.json mínimo, como el que deja curate.py, para que los cambios lo lean."""
    (carpeta / "seleccion.json").write_text(json.dumps({"slides": [
        {"slide": s["slide"], "detalle": [{"name": p.name} for p in s["fotos"]]} for s in slides]}))


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
        escribir_post(tmp, slides)
        collage = next(s for s in slides if len(s["fotos"]) > 1)
        (tmp / "cambios.txt").write_text(f"# comentario\n1 fuera\n{collage['slide']} sola\n"
                                         f"- DSC_0005\n+ DSC_0005\nslides 9\n")
        lista = elegidas.Lista([elegidas.Foto(p.name) for p in fotos])
        lista, hecho = elegidas.aplicar_cambios(tmp / "cambios.txt", tmp / "seleccion.json", lista, por_nombre)
        nombres = set(lista.nombres())
        primera = {p.name for p in slides[0]["fotos"]}
        check(not (primera & nombres), "«1 fuera» saca las fotos de la slide 1", "«1 fuera» no sacó nada")
        marcadas = {f.name for f in lista.fotos if f.sola}
        check({p.name for p in collage["fotos"]} - primera <= marcadas,
              "«N sola» marca las fotos del collage", "«N sola» no marcó las fotos")
        check("DSC_0005" in nombres or "DSC_0005" in primera, "«- foto» y «+ foto» se aplican en orden",
              "«+ foto» no volvió a sumar la foto")
        check(lista.slides == 9, "«slides 9» fija la cantidad", f"«slides 9» dejó {lista.slides}")
        resto = (tmp / "cambios.txt").read_text()
        check(all(l.startswith("#") for l in resto.splitlines() if l.strip()),
              "los cambios quedan marcados como aplicados (no se repiten)", "quedaron cambios sin marcar")
        # La lista ida y vuelta por el archivo no pierde nada
        elegidas.guardar(tmp / "elegidas.txt", lista)
        leida = elegidas.leer(tmp / "elegidas.txt")
        check([f.linea() for f in leida.fotos] == [f.linea() for f in lista.fotos] and leida.slides == 9,
              "la lista se guarda y se lee igual (marcas y cantidad de slides)",
              "la lista cambió al guardarla y leerla")

    print("7. Cuántas slides, si él no lo dice")
    for n, vert, esperado in ((10, 1.0, 6), (10, 0.0, 5), (20, 0.4, 11), (55, 0.4, 20), (3, 1.0, 2), (1, 1.0, 1)):
        fotos = casamiento(n, 70 + n, verticales=vert)
        v, h = elegidas.orientaciones(fotos)
        auto = elegidas.auto_slides(fotos)
        check(abs(auto - esperado) <= 1, f"{n} fotos ({v} verticales, {h} apaisadas) → {auto} slides",
              f"{n} fotos ({v} verticales, {h} apaisadas) → {auto} slides, se esperaban ~{esperado}")
    fotos = casamiento(14, 77)
    slides, afuera, _ = elegidas.pack(fotos, set(), elegidas.auto_slides(fotos), CONFIG)
    propiedades(slides, fotos, afuera, set(), elegidas.auto_slides(fotos), "14 fotos en automático")
    check(any(s["plantilla"] for s in slides), "en automático se arman collages",
          "en automático no se armó ningún collage")
    check(not afuera, "en automático entran todas", "en automático quedaron fotos afuera")

    print("8. Juntar y elegir plantilla")
    fotos = casamiento(16, 8, verticales=0.6)
    por_nombre = {p.name.lower(): p for p in fotos}
    tope = elegidas.auto_slides(fotos)
    slides, _, _ = elegidas.pack(fotos, set(), tope, CONFIG)
    sueltas = [s for s in slides if len(s["fotos"]) == 1]
    a, b = sueltas[0]["slide"], sueltas[1]["slide"]
    juntas = {p.name for s in (sueltas[0], sueltas[1]) for p in s["fotos"]}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        escribir_post(tmp, slides)
        (tmp / "cambios.txt").write_text(f"{a} juntar {b}\n")
        lista = elegidas.Lista([elegidas.Foto(p.name) for p in fotos])
        lista, _ = elegidas.aplicar_cambios(tmp / "cambios.txt", tmp / "seleccion.json", lista, por_nombre)
        grupos = {f.name: f.grupo for f in lista.fotos if f.grupo}
        nuevas, afuera, _ = elegidas.pack(fotos, set(), tope, CONFIG, grupos)
        propiedades(nuevas, fotos, afuera, set(), tope, "con dos slides juntadas")
        check(any({p.name for p in s["fotos"]} == juntas for s in nuevas),
              f"«{a} juntar {b}» las pone en un mismo collage, y con nada más",
              f"«{a} juntar {b}» no quedaron juntas")
        # Cambiarle la plantilla a un collage de 4
        cuatro = next((s for s in nuevas if len(s["fotos"]) == 4), None)
        if cuatro is None:
            check(True, "(no salió ningún collage de 4 para probar la plantilla)", "")
        else:
            otra = "polaroid" if cuatro["plantilla"] != "polaroid" else "grilla"
            escribir_post(tmp, nuevas)
            (tmp / "cambios.txt").write_text(f"{cuatro['slide']} plantilla {otra}\n")
            lista, _ = elegidas.aplicar_cambios(tmp / "cambios.txt", tmp / "seleccion.json", lista, por_nombre)
            grupos = {f.name: f.grupo for f in lista.fotos if f.grupo}
            plantillas = {f.grupo: f.plantilla for f in lista.fotos if f.grupo and f.plantilla}
            otra_vez, afuera, _ = elegidas.pack(fotos, set(), tope, CONFIG, grupos, plantillas)
            mismo = next((s for s in otra_vez if {p.name for p in s["fotos"]} == {p.name for p in cuatro["fotos"]}), None)
            check(mismo is not None and mismo["plantilla"] == otra,
                  f"«N plantilla {otra}» arma esa slide con esa plantilla",
                  f"«N plantilla {otra}» no se respetó")
        (tmp / "cambios.txt").write_text(f"{a} juntar {b}\n")
        escribir_post(tmp, [{"slide": 1, "fotos": fotos[:4]}, {"slide": 2, "fotos": fotos[4:7]}])
        (tmp / "cambios.txt").write_text("1 juntar 2\n")
        _, hecho = elegidas.aplicar_cambios(tmp / "cambios.txt", tmp / "seleccion.json", lista, por_nombre)
        check(any("más grande es de 6" in h for h in hecho), "no deja juntar más de 6 fotos",
              "dejó armar un collage de 7")

    print()
    if FALLAS:
        print(f"{len(FALLAS)} fallas")
        return 1
    print("Todo bien")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
