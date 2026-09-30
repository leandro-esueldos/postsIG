"""Parte el casamiento en capítulos y les pone nombre.

Son dos cosas de confianza muy distinta, y conviene no mezclarlas:

**El corte es estructura medible.** Un casamiento tiene pausas reales —el viaje del salón a la
iglesia, la espera antes de la entrada, el corte antes del baile— y esas pausas se ven en las
horas de captura. Cortar por los huecos más grandes no es una conjetura: es leer lo que pasó.

**El nombre es una conjetura.** "Este bloque es la ceremonia" sale de heurísticas sobre la luz,
la cantidad de caras y si están los novios solos. No hay con qué validarlo hasta que haya un
álbum real etiquetado, así que se pone el nombre, se dice en pantalla de dónde salió, y se puede
pisar a mano desde config.json.

Lo que de verdad importa del módulo es el corte, porque es lo que hace que el post cuente el día
entero en vez de veinte fotos de la misma media hora.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

CHAPTERS = ["preparativos", "ceremonia", "retratos", "fiesta"]
MIN_SHARE = 0.03            # ningún bloque puede quedarse con menos del 3% de las fotos
SWITCH_GAP = 60.0           # segundos: por debajo de esto, dos fotos son del mismo momento
BLOCKS_PER_CHAPTER = 4      # se corta en más bloques que capítulos, para que el nombrado decida


def _rank(values: list[float]) -> np.ndarray:
    """Posición relativa de cada valor dentro del álbum, de 0 a 1."""
    data = np.asarray(values, dtype=np.float64)
    order = data.argsort().argsort().astype(np.float64)
    return order / max(len(data) - 1, 1)


def cut(photos: list, blocks: int) -> list[int]:
    """Parte el álbum en bloques contiguos por los huecos de tiempo más grandes.

    Devuelve, por foto, el número de bloque. Las fotos vienen ordenadas por hora.
    """
    total = len(photos)
    if total == 0:
        return []
    blocks = max(1, min(blocks, total))
    stamps = [p.taken_dt() for p in photos]
    gaps = []
    for i in range(1, total):
        if stamps[i] and stamps[i - 1]:
            gaps.append(((stamps[i] - stamps[i - 1]).total_seconds(), i))
        else:
            gaps.append((0.0, i))

    minimum = max(1, int(total * MIN_SHARE))
    cuts: list[int] = []
    for seconds, index in sorted(gaps, reverse=True):
        if len(cuts) >= blocks - 1:
            break
        if seconds < SWITCH_GAP:
            break
        # Un corte no puede dejar un bloque más chico que el mínimo
        if all(abs(index - other) >= minimum for other in cuts) \
                and index >= minimum and total - index >= minimum:
            cuts.append(index)

    # Si los huecos no alcanzaron —álbum sin EXIF, o disparo continuo— se reparte parejo
    if len(cuts) < blocks - 1:
        faltan = blocks - 1 - len(cuts)
        for i in range(1, faltan + 1):
            index = round(total * i / (faltan + 1))
            if all(abs(index - other) >= minimum for other in cuts):
                cuts.append(index)

    cuts = sorted(set(cuts))
    result, block = [], 0
    borders = set(cuts)
    for i in range(total):
        if i in borders:
            block += 1
        result.append(block)
    return result


def _affinity(rows: dict, chapter: str) -> float:
    """Cuánto se parece un bloque al capítulo, según luz, caras, cielo y novios.

    Los pesos son heurísticos: no hay álbum etiquetado con qué ajustarlos.
    """
    oscuro, gente, afuera, pareja, detalle, momento = (
        rows["oscuro"], rows["gente"], rows["afuera"], rows["pareja"],
        rows["detalle"], rows["momento"])
    if chapter == "preparativos":
        return 1.2 * (1 - afuera) + 1.0 * detalle + 0.8 * (1 - gente) + 1.0 * (1 - momento)
    if chapter == "ceremonia":
        return 1.4 * gente + 0.6 * (1 - oscuro) + 0.5 * (1 - detalle)
    if chapter == "retratos":
        return 1.6 * pareja + 1.0 * afuera + 0.8 * (1 - gente) + 0.6 * (1 - oscuro)
    return 1.6 * oscuro + 0.9 * gente + 0.8 * momento          # fiesta


def label(photos: list, blocks: list[int], chapters: list[str] | None = None) -> dict[int, str]:
    """Nombra cada bloque, respetando que los capítulos van en orden en el día.

    Se resuelve por programación dinámica sobre los bloques, con tres reglas:

    - Se arranca en el primer capítulo y se termina en el último.
    - De un bloque al siguiente, el capítulo se queda igual o avanza exactamente uno.

    Juntas garantizan que **todos los capítulos se usen**. Sin eso, la suma de afinidades se
    maximiza metiendo casi todo en un solo capítulo, y el post termina siendo veinte fotos de
    los preparativos. Por eso también se corta en más bloques que capítulos: si hubiera uno por
    capítulo, no habría nada que decidir.
    """
    names = chapters or CHAPTERS
    if not photos or not blocks:
        return {}

    p50 = _rank([p.metrics.get("p50", 128) for p in photos])
    faces = _rank([p.metrics.get("faces", 0) or 0 for p in photos])
    sky = _rank([p.metrics.get("estilo", {}).get("sky", 0.0) for p in photos])
    total = len(photos)

    rasgos: dict[int, dict] = {}
    for block in sorted(set(blocks)):
        idx = [i for i, b in enumerate(blocks) if b == block]
        rasgos[block] = {
            "oscuro": float(1 - p50[idx].mean()),
            "gente": float(faces[idx].mean()),
            "afuera": float(sky[idx].mean()),
            "pareja": float(np.mean([
                1.0 if (photos[i].metrics.get("novios") or 0) >= 2
                and (photos[i].metrics.get("faces") or 0) <= 3 else 0.0 for i in idx])),
            "detalle": float(np.mean([
                1.0 if photos[i].metrics.get("kind") == "detalle" else 0.0 for i in idx])),
            "momento": float(np.mean(idx)) / max(total - 1, 1),
        }

    orden = sorted(rasgos)
    n, k = len(orden), len(names)
    if n < k:
        # Menos bloques que capítulos: no alcanza para contar el día entero, se reparte en orden
        return {orden[i]: names[min(i, k - 1)] for i in range(n)}

    score = np.full((n, k), -np.inf)
    back = np.zeros((n, k), dtype=int)
    score[0][0] = _affinity(rasgos[orden[0]], names[0])      # arranca en el primer capítulo
    for i in range(1, n):
        for c in range(k):
            # Quedarse en el capítulo, o avanzar exactamente uno: así ninguno se saltea
            opciones = [(score[i - 1][prev], prev) for prev in (c - 1, c) if prev >= 0]
            mejor, desde = max(opciones, default=(-np.inf, 0))
            if mejor == -np.inf:
                continue
            score[i][c] = mejor + _affinity(rasgos[orden[i]], names[c])
            back[i][c] = desde

    c = k - 1                                                # y termina en el último
    asignado = [0] * n
    for i in range(n - 1, -1, -1):
        asignado[i] = c
        c = back[i][c]
    return {orden[i]: names[asignado[i]] for i in range(n)}


def describe(photos: list, blocks: list[int], names: dict[int, str]) -> list[dict]:
    """Un resumen por capítulo —no por bloque— para imprimir y para el JSON de salida."""
    out: list[dict] = []
    for i, block in enumerate(blocks):
        capitulo = names.get(block, "?")
        stamp = photos[i].taken_dt()
        if out and out[-1]["capitulo"] == capitulo:
            fila = out[-1]
            fila["fotos"] += 1
            fila["bloques"] = len(set(fila["_blocks"] + [block]))
            fila["_blocks"].append(block)
        else:
            out.append({"capitulo": capitulo, "fotos": 1, "bloques": 1,
                        "desde": None, "hasta": None, "_blocks": [block]})
        if stamp:
            fila = out[-1]
            iso = stamp.isoformat()
            fila["desde"] = min(fila["desde"] or iso, iso)
            fila["hasta"] = max(fila["hasta"] or iso, iso)
    for fila in out:
        fila.pop("_blocks", None)
    return out


def gap_before(photos: list, index: int) -> float:
    """Segundos entre una foto y la anterior. Sirve para explicar por qué se cortó ahí."""
    if index <= 0:
        return 0.0
    a, b = photos[index - 1].taken_dt(), photos[index].taken_dt()
    return (b - a).total_seconds() if a and b else 0.0


def humanize(seconds: float) -> str:
    if seconds >= 3600:
        return f"{seconds / 3600:.1f} h"
    if seconds >= 60:
        return f"{seconds / 60:.0f} min"
    return f"{seconds:.0f} s"
