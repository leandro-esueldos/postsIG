"""Encuentra qué fotos del álbum usó en cada slide que publicó.

Es lo que convierte sus posts en datos de entrenamiento: para cada casamiento, cuáles de las
mil y pico fotos eligió (positivos) y cuáles no (negativos). Sin esto el modelo de estilo sólo
podía medir parecido; con esto puede aprender preferencia.

Se usan puntos característicos (SIFT) y no hashes o embeddings globales, por tres razones que
vienen de cómo arma él los posts:

- Un collage mezcla varias fotos en una slide. Un descriptor global de la slide no se parece a
  ninguna de ellas; los puntos de cada foto, en cambio, siguen estando en su celda.
- Las celdas están recortadas y escaladas (de 6000 px a 500). SIFT aguanta escala y recorte.
- A veces publica en blanco y negro una foto que en el álbum está en color. SIFT trabaja en
  escala de grises, así que no le importa.

El proceso es el de recuperación de imágenes clásico: cada punto de la slide vota por la foto
del álbum de la que más se parece, y las fotos con más votos se confirman con una homografía
(RANSAC). La homografía además dice en qué parte de la slide cayó cada foto.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFile, ImageOps

ImageFile.LOAD_TRUNCATED_IMAGES = True      # ver lib/album.py

SIDE = 1000                 # lado largo al que se analiza cada foto del álbum
FEATURES = 600              # puntos por foto del álbum
SLIDE_FEATURES = 4000       # la slide trae hasta seis fotos: necesita más puntos
RATIO = 0.75                # prueba de Lowe: el mejor vecino tiene que ganarle claro al segundo
MIN_VOTES = 12              # votos para que una foto pase a la verificación geométrica
MIN_INLIERS = 20            # puntos coherentes con una homografía para darla por encontrada


def _gray(path: Path, side: int) -> np.ndarray:
    with Image.open(path) as src:
        src.draft("L", (side * 2, side * 2))
        im = ImageOps.exif_transpose(src).convert("L")
    im.thumbnail((side, side), Image.LANCZOS)
    return np.asarray(im)


def describe(path: Path, side: int = SIDE, features: int = FEATURES):
    """Puntos y descriptores de una imagen. Devuelve (coordenadas Nx2, descriptores Nx128)."""
    sift = cv2.SIFT_create(nfeatures=features)
    gray = _gray(path, side)
    keypoints, descriptors = sift.detectAndCompute(gray, None)
    if descriptors is None:
        return np.zeros((0, 2), np.float32), np.zeros((0, 128), np.float32), gray.shape
    points = np.array([k.pt for k in keypoints], dtype=np.float32)
    # RootSIFT: normalizar así mejora bastante el emparejamiento, a costo casi nulo
    descriptors = descriptors / (descriptors.sum(axis=1, keepdims=True) + 1e-7)
    descriptors = np.sqrt(descriptors).astype(np.float32)
    return points, descriptors, gray.shape


class AlbumIndex:
    """Todos los puntos del álbum en un índice, cada uno con la foto a la que pertenece."""

    def __init__(self, paths: list[Path], cache: Path | None = None, workers: int = 8) -> None:
        self.paths = paths
        data = None
        if cache and cache.is_file():
            data = np.load(cache, allow_pickle=True)
            if list(data["names"]) != [p.name for p in paths]:
                data = None                       # cambió el álbum: se rehace
        if data is None:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(describe, paths))
            points = [r[0] for r in results]
            descs = [r[1] for r in results]
            owners = [np.full(len(d), i, dtype=np.int32) for i, d in enumerate(descs)]
            self.points = np.concatenate(points) if points else np.zeros((0, 2), np.float32)
            self.descriptors = np.concatenate(descs) if descs else np.zeros((0, 128), np.float32)
            self.owner = np.concatenate(owners) if owners else np.zeros(0, np.int32)
            if cache:
                np.savez_compressed(cache, names=np.array([p.name for p in paths]),
                                    points=self.points, descriptors=self.descriptors,
                                    owner=self.owner)
        else:
            self.points = data["points"]
            self.descriptors = data["descriptors"]
            self.owner = data["owner"]
        self.flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
        self.flann.add([self.descriptors])
        self.flann.train()

    def find(self, slide: Path) -> list[dict]:
        """Las fotos del álbum que aparecen en la slide, con dónde caen y cuánta evidencia hay."""
        points, descriptors, shape = describe(slide, side=1350, features=SLIDE_FEATURES)
        if len(descriptors) < 10:
            return []
        matches = self.flann.knnMatch(descriptors, k=2)
        votes: dict[int, list[tuple[int, int]]] = {}
        for pair in matches:
            if len(pair) < 2:
                continue
            best, second = pair
            if best.distance < RATIO * second.distance:
                owner = int(self.owner[best.trainIdx])
                votes.setdefault(owner, []).append((best.queryIdx, best.trainIdx))

        found = []
        for owner, pairs in sorted(votes.items(), key=lambda kv: -len(kv[1]))[:12]:
            if len(pairs) < MIN_VOTES:
                break
            src = np.float32([self.points[t] for _, t in pairs])       # en la foto del álbum
            dst = np.float32([points[q] for q, _ in pairs])            # en la slide
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 6.0)
            inliers = int(mask.sum()) if mask is not None else 0
            if H is None or inliers < MIN_INLIERS:
                continue
            # Dónde cae en la slide: la caja de los puntos que la confirmaron
            ok = dst[mask.ravel().astype(bool)]
            x0, y0 = ok.min(axis=0)
            x1, y1 = ok.max(axis=0)
            found.append({
                "foto": self.paths[owner].name,
                "votos": len(pairs),
                "coherentes": inliers,
                "zona": [round(float(v)) for v in (x0, y0, x1, y1)],
            })
        return _drop_overlaps(found)


def _drop_overlaps(found: list[dict]) -> list[dict]:
    """Si dos fotos del álbum caen en la misma zona, es la misma escena de una ráfaga: gana la
    que tiene más puntos coherentes, que es la que de verdad está en la slide."""
    kept: list[dict] = []
    for item in sorted(found, key=lambda f: -f["coherentes"]):
        x0, y0, x1, y1 = item["zona"]
        area = max((x1 - x0) * (y1 - y0), 1)
        solapa = False
        for other in kept:
            a0, b0, a1, b1 = other["zona"]
            ix = max(0, min(x1, a1) - max(x0, a0))
            iy = max(0, min(y1, b1) - max(y0, b0))
            if ix * iy > 0.5 * area:
                solapa = True
                break
        if not solapa:
            kept.append(item)
    return sorted(kept, key=lambda f: (f["zona"][1], f["zona"][0]))
