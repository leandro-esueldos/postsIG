"""Detección de fotos repetidas y agrupado de ráfagas.

En un casamiento la misma escena se dispara entre 3 y 15 veces. Agruparlas es lo que hace que
el álbum pase de 3.000 fotos a unos 600 momentos distintos, y es el recorte más grande de todo
el pipeline. Después, de cada grupo entra una sola.

Se usan dos señales juntas:

- La hora de captura, que separa momentos distintos aunque se parezcan.
- Un hash perceptual (dHash), que evita agrupar dos fotos seguidas en el tiempo pero de escenas
  distintas, por ejemplo cuando el fotógrafo se da vuelta.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
from PIL import Image

HASH_SIDE = 8               # dHash de 8x8 -> 64 bits
GAP_SECONDS = 4.0           # separación máxima para considerar dos fotos parte de la misma ráfaga
BURST_DISTANCE = 14         # distancia de Hamming tolerada dentro de una ráfaga
DUPLICATE_DISTANCE = 8      # casi idénticas: se agrupan aunque estén lejos en el tiempo
CHUNK = 512                 # filas por bloque en la comparación de todos contra todos
GRUPO_SOSPECHOSO = 25       # a partir de acá el grupo se avisa: una ráfaga real no llega

# Distancias medidas sobre un álbum de prueba de 3.444 fotos con escenas conocidas:
#
#   tomas de la misma ráfaga      mediana  3    el 91% cae en 8 o menos
#   fotos realmente distintas     mediana 32    la más parecida dio 10, en 57.557 pares
#
# Por eso el umbral de repetida va en 8: deja pasar la mayoría de las ráfagas y todavía queda a
# dos bits de la foto distinta más parecida que se haya visto.
#
# Lo que sí puede fallar es el encadenamiento: si A se parece a B y B a C, los tres terminan en
# el mismo grupo aunque A y C no se parezcan. Con material real es raro, pero cuando pasa el
# grupo queda enorme, así que se avisa por pantalla en vez de esconderlo.


def dhash(im: Image.Image) -> int:
    """Hash perceptual por gradiente horizontal: 64 bits que sobreviven al reencuadre leve."""
    small = im.convert("L").resize((HASH_SIDE + 1, HASH_SIDE), Image.LANCZOS)
    pixels = np.asarray(small, dtype=np.int16)
    bits = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


class _Union:
    """Union-find para encadenar las fotos de una misma ráfaga."""

    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def join(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _seconds(a: str | None, b: str | None) -> float:
    if not a or not b:
        return float("inf")
    return abs((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())


def _near_duplicates(hashes: np.ndarray, distance: int) -> list[tuple[int, int]]:
    """Pares casi idénticos en todo el álbum, comparando por bloques para no volar la memoria."""
    pairs = []
    total = len(hashes)
    for start in range(0, total, CHUNK):
        block = hashes[start:start + CHUNK, None]
        counts = np.bitwise_count(np.bitwise_xor(block, hashes[None, :]))
        rows, cols = np.nonzero(counts <= distance)
        for row, col in zip(rows, cols):
            i, j = start + int(row), int(col)
            if i < j:
                pairs.append((i, j))
    return pairs


def group(photos: list, hashes: list[int], scores: list[float], tiebreak: list[float] | None = None,
          gap: float = GAP_SECONDS, burst_distance: int = BURST_DISTANCE,
          duplicate_distance: int = DUPLICATE_DISTANCE) -> list[dict]:
    """Agrupa las fotos (que vienen ordenadas por hora) y ordena cada grupo por puntaje.

    Devuelve, por foto y en el mismo orden de entrada: número de grupo, tamaño del grupo y
    posición dentro del grupo (0 = la mejor, la que representa al momento).

    El puntaje técnico satura en 1 para todo lo que está bien, así que dentro de una ráfaga
    suele haber empate: `tiebreak` (la nitidez cruda) desempata, que es justo lo que cambia
    entre tomas de la misma escena.
    """
    total = len(photos)
    if total == 0:
        return []
    union = _Union(total)

    # Encadenado por vecindad temporal: A con B, B con C, y la ráfaga entera queda junta
    for i in range(total - 1):
        if _seconds(photos[i].taken, photos[i + 1].taken) <= gap:
            if bin(hashes[i] ^ hashes[i + 1]).count("1") <= burst_distance:
                union.join(i, i + 1)

    packed = np.array(hashes, dtype=np.uint64)
    for i, j in _near_duplicates(packed, duplicate_distance):
        union.join(i, j)

    members: dict[int, list[int]] = {}
    for i in range(total):
        members.setdefault(union.find(i), []).append(i)

    desempate = tiebreak or [0.0] * total
    result = [{} for _ in range(total)]
    for number, (_, indexes) in enumerate(sorted(members.items(), key=lambda kv: kv[1][0])):
        ordered = sorted(indexes, key=lambda i: (-scores[i], -desempate[i], photos[i].taken or ""))
        for rank, i in enumerate(ordered):
            result[i] = {"group": number, "group_size": len(indexes), "rank_in_group": rank}
    return result


def summary(groups: list[dict]) -> dict:
    sizes = [g["group_size"] for g in groups if g["rank_in_group"] == 0]
    if not sizes:
        return {"grupos": 0, "repetidas": 0, "grupo_mayor": 0, "sospechosos": 0}
    return {
        "grupos": len(sizes),
        "repetidas": sum(sizes) - len(sizes),
        "grupo_mayor": max(sizes),
        # Grupos tan grandes que probablemente sean un encadenamiento, no una ráfaga
        "sospechosos": sum(1 for s in sizes if s >= GRUPO_SOSPECHOSO),
    }
