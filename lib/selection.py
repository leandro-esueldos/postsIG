"""Arma las slides del post: cuántas de cada tramo del día y cuáles, sin repetir la misma imagen.

El problema no es encontrar veinte fotos buenas —un álbum tiene cientos— sino que las veinte
cuenten el día y no se parezcan entre sí. Dos reglas:

**Cupo por tramo del día.** Sin cupo, las veinte mejores por puntaje salen casi todas del mismo
rato: el momento con mejor luz gana siempre. Con su primer casamiento etiquetado (MJ) se vio
además cómo reparte él: cubre el día entero, más o menos en proporción a cuántas fotos hay de cada
parte. Por eso el reparto por defecto es proporcional a los bloques del día (los cortes por pausas
reales), y no los cuatro cupos fijos por capítulo de la primera versión, que dejaban horas enteras
sin ninguna foto.

**Diversidad dentro del tramo.** Entre dos fotos igual de buenas pero parecidas entre sí, entra la
que aporta algo distinto. Es relevancia marginal: cada foto se juzga por su puntaje menos cuánto se
parece a las que ya entraron. El parecido se mide con CLIP cuando está, que describe el contenido;
si no, con los rasgos de estilo.
"""
from __future__ import annotations

import numpy as np

from . import style

DIVERSITY = 0.55            # cuánto pesa "no parecerse a lo ya elegido" contra el puntaje
SAME_KIND_PENALTY = 0.12    # castigo por repetir tipo de toma (retrato, pareja, detalle) seguido
MIN_HASH_DISTANCE = 12      # dos slides nunca pueden estar más cerca que esto
OVERFLOW = 1.5              # cuánto puede pasarse un tramo de su cupo al absorber sobrantes
CLIP_SAME = 0.80            # parecido CLIP a partir del cual dos fotos cuentan como "lo mismo"


def _feature_matrix(photos: list) -> np.ndarray:
    data = np.array([style.vector(p.metrics.get("estilo", {})) for p in photos], dtype=np.float64)
    if len(data) < 2:
        return data
    center = np.median(data, axis=0)
    mad = np.median(np.abs(data - center), axis=0) * 1.4826
    rango = (np.percentile(data, 95, axis=0) - np.percentile(data, 5, axis=0)) / 4.0
    scale = np.maximum(np.maximum(mad, rango), style.SCALE_FLOOR)
    return (data - center) / scale


def _similarity(photos: list, embeddings: dict | None):
    """Función (i, lista de j) -> parecido máximo de i con esas j, en 0–1."""
    if embeddings and all(p.key in embeddings for p in photos):
        E = np.stack([embeddings[p.key] for p in photos])

        def clip_sim(i: int, js: list[int]) -> float:
            # CLIP entre fotos de casamiento va de ~0.5 a 1: se reescala para que 0.5 sea "nada"
            # y CLIP_SAME ya cuente como parecidísimo
            raw = float(np.max(E[js] @ E[i]))
            return float(np.clip((raw - 0.5) / (CLIP_SAME - 0.5), 0.0, 1.0))
        return clip_sim

    features = _feature_matrix(photos)

    def style_sim(i: int, js: list[int]) -> float:
        d = np.sqrt((np.clip(features[js] - features[i], -5, 5) ** 2).mean(axis=1))
        return float(np.exp(-d.min()))
    return style_sim


def proportional(sizes: dict, slides: int) -> dict:
    """Reparte `slides` entre unidades en proporción a su tamaño (resto mayor)."""
    total = sum(sizes.values())
    if total == 0:
        return {k: 0 for k in sizes}
    exactos = {k: slides * v / total for k, v in sizes.items()}
    asignado = {k: int(v) for k, v in exactos.items()}
    sobran = slides - sum(asignado.values())
    for k in sorted(exactos, key=lambda k: -(exactos[k] - asignado[k]))[:sobran]:
        asignado[k] += 1
    return asignado


def quotas(candidates_by_unit: dict, wanted: dict, slides: int) -> tuple[dict, str]:
    """Reparte las slides entre unidades, moviendo las que una unidad no puede llenar.

    Si de la ceremonia hay tres fotos y el cupo pedía cinco, las dos que sobran van a la unidad con
    más material libre. Pero **con tope**: ninguna puede pasarse de OVERFLOW veces su cupo. Sin ese
    tope, un álbum desbalanceado termina en un post de veinte fotos de los preparativos, que es
    exactamente lo que el cupo venía a evitar.
    """
    asignado = {c: min(wanted.get(c, 0), len(candidates_by_unit.get(c, []))) for c in wanted}
    tope = {c: max(1, int(round(wanted.get(c, 0) * OVERFLOW))) for c in wanted}
    faltan = slides - sum(asignado.values())
    while faltan > 0:
        holgura = {c: min(len(candidates_by_unit.get(c, [])), tope[c]) - asignado[c] for c in wanted}
        mejor = max(holgura, key=lambda c: (holgura[c], -asignado[c]))
        if holgura[mejor] <= 0:
            break
        asignado[mejor] += 1
        faltan -= 1

    aviso = ""
    if faltan > 0:
        flojos = [str(c) for c in wanted if asignado[c] < wanted.get(c, 0)]
        aviso = (f"quedan {sum(asignado.values())} slides de las {slides} pedidas: falta material "
                 f"en {', '.join(flojos)}. Antes que llenar con más fotos de otra parte del día, "
                 f"el post queda más corto y mejor repartido")
    return asignado, aviso


def pick(photos: list, units: list, wanted: dict, slides: int, apertura: str = "mejor",
         embeddings: dict | None = None, unidad: str = "capitulo") -> tuple[list[dict], str]:
    """Elige las slides. `photos` son los representantes de cada momento, ya con capítulo y bloque.

    `unidad` es la clave de photo.metrics por la que se reparte: "bloque" (proporcional al día) o
    "capitulo". Devuelve (lista de {slide, photo, capitulo, motivo} en el orden del post, aviso).
    """
    if not photos:
        return [], ""

    parecido = _similarity(photos, embeddings)
    index_of = {id(p): i for i, p in enumerate(photos)}
    por_unidad: dict = {u: [] for u in units}
    for photo in photos:
        por_unidad.setdefault(photo.metrics[unidad], []).append(photo)

    cupos, aviso = quotas(por_unidad, wanted, slides)
    elegidas: list[dict] = []
    elegidos_idx: list[int] = []

    for u in units:
        cupo = cupos.get(u, 0)
        candidatos = sorted(por_unidad.get(u, []), key=lambda p: -p.metrics["score"])
        de_la_unidad: list = []
        for _ in range(cupo):
            mejor, mejor_valor, mejor_motivo = None, -np.inf, ""
            for photo in candidatos:
                if photo in de_la_unidad:
                    continue
                i = index_of[id(photo)]
                if any(bin(photo.metrics["hash"] ^ o.metrics["hash"]).count("1") < MIN_HASH_DISTANCE
                       for o in (e["photo"] for e in elegidas)):
                    continue                     # ya entró algo prácticamente igual
                similar = parecido(i, elegidos_idx) if elegidos_idx else 0.0
                repetido = sum(1 for e in de_la_unidad
                               if e.metrics.get("kind") == photo.metrics.get("kind"))
                valor = (photo.metrics["score"] - DIVERSITY * similar - SAME_KIND_PENALTY * repetido)
                if valor > mejor_valor:
                    mejor, mejor_valor = photo, valor
                    mejor_motivo = (f"puntaje {photo.metrics['score']:.2f}"
                                    + (f", parecido a otra {similar:.2f}" if similar > 0.3 else "")
                                    + (f", {repetido} del mismo tipo antes" if repetido else ""))
            if mejor is None:
                break
            de_la_unidad.append(mejor)
            elegidos_idx.append(index_of[id(mejor)])
            elegidas.append({"photo": mejor, "capitulo": mejor.metrics.get("capitulo", str(u)),
                             "unidad": u, "motivo": mejor_motivo})

    # Orden final: cronológico, y si se pidió, la más fuerte al frente como gancho
    elegidas.sort(key=lambda e: e["photo"].taken or "")
    if apertura == "mejor" and len(elegidas) > 1:
        hook = max(elegidas, key=lambda e: e["photo"].metrics["score"])
        elegidas.remove(hook)
        hook["motivo"] += " · abre el post"
        elegidas.insert(0, hook)
    for number, entry in enumerate(elegidas, start=1):
        entry["slide"] = number
    return elegidas, aviso


def spares(photos: list, chosen: list[dict], per_chapter: int = 4) -> list[dict]:
    """Las que quedaron afuera por poco, por capítulo, para poder cambiar una."""
    usadas = {id(e["photo"]) for e in chosen}
    por_capitulo: dict[str, list] = {}
    for photo in photos:
        if id(photo) in usadas:
            continue
        por_capitulo.setdefault(photo.metrics["capitulo"], []).append(photo)
    out = []
    for capitulo, candidatos in por_capitulo.items():
        for photo in sorted(candidatos, key=lambda p: -p.metrics["score"])[:per_chapter]:
            out.append({"photo": photo, "capitulo": capitulo})
    out.sort(key=lambda e: e["photo"].taken or "")
    return out
