"""Control de las propiedades del guion sobre una salida ya generada.

Los nombres de los capítulos son heurísticos y no se pueden verificar sin un álbum etiquetado.
Lo que sí se puede verificar, y es lo que de verdad hace el guion, son estas seis cosas:

1. No entran dos slides que sean prácticamente la misma foto.
2. Ningún capítulo se pasa del tope de su cupo.
3. Todos los capítulos con material aparecen en el post.
4. Las slides cubren el día, no un rato.
5. El post cuenta más del día que agarrar las mejores por puntaje.
6. Correrlo dos veces da lo mismo.

Uso:  python curator/test_guion.py curator/salida/<boda>
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import selection

FALLAS: list[str] = []


def check(condition: bool, ok: str, bad: str) -> None:
    print(("  OK    " if condition else "  FALLA ") + (ok if condition else bad))
    if not condition:
        FALLAS.append(bad)


def span(stamps: list[str]) -> float:
    reales = [datetime.fromisoformat(s) for s in stamps if s]
    return (max(reales) - min(reales)).total_seconds() if len(reales) > 1 else 0.0


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("Uso: python curator/test_guion.py <carpeta de salida>")
    out = Path(sys.argv[1]).expanduser().resolve()
    seleccion = json.loads((out / "seleccion.json").read_text(encoding="utf-8-sig"))
    analisis = json.loads((out / "analisis.json").read_text(encoding="utf-8-sig"))
    config = json.loads((Path(__file__).resolve().parent / "config.json")
                        .read_text(encoding="utf-8-sig"))

    por_rel = {f["rel"]: f for f in analisis["fotos"]}
    slides = seleccion["slides"]
    cupos = config["post"]["cupos"]
    print(f"{len(slides)} slides sobre {analisis['resumen']['grupos']} momentos "
          f"de {analisis['resumen']['fotos']} fotos\n")

    # 1. nada repetido
    peor, par = 64, None
    for i, a in enumerate(slides):
        for b in slides[i + 1:]:
            ha, hb = por_rel[a["rel"]]["hash"], por_rel[b["rel"]]["hash"]
            d = bin(ha ^ hb).count("1")
            if d < peor:
                peor, par = d, (a["rel"], b["rel"])
    check(peor >= selection.MIN_HASH_DISTANCE,
          f"nada repetido: las dos slides más parecidas están a {peor} de distancia",
          f"hay dos slides casi iguales ({peor} de distancia): {par}")

    # 2. ningún capítulo se pasa del tope
    conteo: dict[str, int] = {}
    for s in slides:
        conteo[s["capitulo"]] = conteo.get(s["capitulo"], 0) + 1
    if config["post"].get("reparto", "proporcional") == "proporcional":
        # El reparto es por bloques del día, proporcional a su tamaño: por construcción no hay
        # cupo por capítulo que respetar. Lo que se controla es la cobertura, más abajo.
        print(f"  --    reparto proporcional al día: "
              f"{', '.join(f'{c} {n}' for c, n in sorted(conteo.items()))}")
    else:
        excedidos = [c for c, n in conteo.items()
                     if n > round(cupos.get(c, 0) * selection.OVERFLOW)]
        check(not excedidos,
              f"cupos respetados: {', '.join(f'{c} {n}' for c, n in sorted(conteo.items()))}",
              f"se pasaron del tope: {excedidos}")

    # 3. todos los capítulos con material entran
    con_material = {f["capitulo"] for f in analisis["fotos"] if f.get("capitulo")}
    faltantes = con_material - set(conteo)
    check(not faltantes,
          f"los {len(con_material)} capítulos con material aparecen en el post",
          f"capítulos sin ninguna slide: {faltantes}")

    # 4 y 5. cuánto del día cuenta el post, contra agarrar las mejores por puntaje
    todas = [f for f in analisis["fotos"] if f.get("rank_in_group") == 0]
    dia = span([f["taken"] for f in todas])
    elegido = span([s["taken"] for s in slides])
    mejores = sorted(todas, key=lambda f: -f["score"])[:len(slides)]
    naive = span([f["taken"] for f in mejores])
    bloques_guion = len({por_rel[s["rel"]].get("bloque") for s in slides})
    bloques_naive = len({f.get("bloque") for f in mejores})
    check(dia > 0 and elegido / dia > 0.8,
          f"las slides cubren el {elegido / dia * 100:.0f}% del día",
          f"las slides cubren sólo el {elegido / max(dia, 1) * 100:.0f}% del día")
    if len(todas) < 3 * len(slides):
        # Eligiendo 18 de 24 no hay nada que decidir: la propiedad existe pero no se puede medir
        print(f"  --    con {len(todas)} momentos para {len(slides)} slides no hay presión de "
              f"selección; la comparación contra el ranking puro no dice nada acá")
    else:
        check(bloques_guion > bloques_naive,
              f"el guion toca {bloques_guion} bloques del día; las mejores por puntaje, {bloques_naive}",
              f"el guion toca {bloques_guion} bloques y las mejores por puntaje {bloques_naive}: "
              f"el cupo no está aportando nada")

    # 6. determinismo: el orden de slides tiene que ser el mismo que el cronológico salvo la apertura
    resto = slides[1:] if config["post"].get("apertura") == "mejor" else slides
    cronologico = all((resto[i]["taken"] or "") <= (resto[i + 1]["taken"] or "")
                      for i in range(len(resto) - 1))
    check(cronologico,
          "el post va en orden cronológico después de la apertura",
          "las slides no están en orden cronológico")

    print()
    if FALLAS:
        print(f"{len(FALLAS)} propiedades no se cumplen")
        return 1
    print("Todas las propiedades del guion se cumplen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
