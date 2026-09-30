"""Embeddings CLIP: un vector de 512 que describe qué hay en cada foto.

Hizo falta con el primer álbum real. Sus rasgos de color y técnica valen lo mismo en lo que
publica y en lo que no (el álbum ya viene curado y revelado parejo): el modelo entrenado con ellos
dio AUC 0.53. Lo que cambia es el contenido —anillos, novia preparándose, iglesia, pista—, y eso
es justo lo que CLIP aprendió a describir.

Corre en CPU con onnxruntime, con el modelo cuantizado a 8 bits. Se calcula sobre la miniatura
del caché y se guarda por foto, así que el costo se paga una vez por álbum.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from . import models

SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
BATCH = 32

_session = None


def _model():
    global _session
    if _session is None:
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.log_severity_level = 3
        _session = ort.InferenceSession(str(models.path("clip")), options,
                                        providers=["CPUExecutionProvider"])
    return _session


def _prepare(path: Path) -> np.ndarray:
    """El preprocesado de CLIP: lado corto a 224, recorte central, normalización."""
    with Image.open(path) as src:
        im = src.convert("RGB")
    scale = SIZE / min(im.size)
    im = im.resize((max(SIZE, round(im.width * scale)), max(SIZE, round(im.height * scale))),
                   Image.BICUBIC)
    left, top = (im.width - SIZE) // 2, (im.height - SIZE) // 2
    im = im.crop((left, top, left + SIZE, top + SIZE))
    arr = (np.asarray(im, dtype=np.float32) / 255.0 - MEAN) / STD
    return arr.transpose(2, 0, 1)


def compute(paths: list[Path]) -> np.ndarray:
    """Embeddings normalizados (norma 1) de una lista de imágenes, en orden."""
    session = _model()
    out = []
    for start in range(0, len(paths), BATCH):
        lote = np.stack([_prepare(p) for p in paths[start:start + BATCH]])
        vec = session.run(["image_embeds"], {"pixel_values": lote})[0]
        out.append(vec / np.linalg.norm(vec, axis=1, keepdims=True))
    return np.concatenate(out) if out else np.zeros((0, 512), np.float32)


def for_album(album: Path, photos: list, thumb_path) -> dict[str, np.ndarray]:
    """Embedding de cada foto del álbum, por clave. Reusa el caché y calcula lo que falte."""
    cache = album / ".curator" / "clip.npz"
    guardados: dict[str, np.ndarray] = {}
    if cache.is_file():
        data = np.load(cache)
        guardados = dict(zip(data["keys"].tolist(), data["vectors"]))
    faltan = [p for p in photos if p.key not in guardados]
    if faltan:
        print(f"  contenido (CLIP): {len(faltan)} fotos a describir", flush=True)
        vectores = compute([thumb_path(album, p) for p in faltan])
        for photo, vector in zip(faltan, vectores):
            guardados[photo.key] = vector
        keys = list(guardados)
        np.savez_compressed(cache, keys=np.array(keys), vectors=np.stack([guardados[k] for k in keys]))
    return {p.key: guardados[p.key] for p in photos}
