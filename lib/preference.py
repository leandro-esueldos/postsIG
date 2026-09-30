"""Modelo de preferencia: aprende, de lo que él publicó, qué fotos de un álbum elegiría.

Reemplaza al modelo de estilo de la fase 3 en lo que importa. Aquel medía parecido a sus fotos
publicadas y no discriminaba (AUC 0.52 sobre un casamiento real). La causa quedó clara con el
primer álbum etiquetado: el álbum que entrega ya está curado por técnica y revelado con el mismo
presét, así que el color y la nitidez son iguales en lo que publica y en lo que no. Lo que cambia
es qué hay en la foto: publica el doble de detalles, y fotos con menos gente.

Este modelo se entrena con positivos y negativos del mismo casamiento (verdad.py) y aprende qué
rasgos separan. Es una regresión logística con regularización muy fuerte (L2=10000): con 205
positivos contra 512 rasgos de CLIP, cualquier cosa más flexible memoriza. El valor no se eligió a
ojo: dejando cada casamiento afuera, el acierto sube de 0.668 (L2=10) a 0.764 (L2=10000) y después
baja. Con tanta regularización los pesos quedan casi en cero y lo que ordena es la dirección que
separa el promedio de lo que publicó del promedio de lo que no; esa dirección sola da 0.751.

La unidad es el momento (la ráfaga), no la foto: si él eligió la tercera toma de una ráfaga, las
otras tres no son "fotos que no eligió", son la misma foto. Contarlas como negativas ensucia.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np

from . import style

KINDS = ["detalle", "lejos", "grupo", "pareja", "retrato"]
L2 = 10000.0                # ver la nota de abajo: medido, no elegido a ojo
ITERATIONS = 3000
LEARNING_RATE = 0.05
MODEL_VERSION = 1


def names(extra: int = 0) -> list[str]:
    base = list(style.FEATURES) + ["log_caras", "raiz_area_cara"] + [f"tipo_{k}" for k in KINDS]
    base += ["bn", "apaisada", "novios", "momento", "momento2"]
    return base + [f"extra_{i}" for i in range(extra)]


def vector(m: dict, momento: float, extra: np.ndarray | None = None) -> np.ndarray:
    """Rasgos de una foto. `momento` es la posición en el día, de 0 a 1."""
    estilo = style.vector(m.get("estilo", {}))
    caras = [math.log1p(m.get("faces") or 0), math.sqrt(max(m.get("face_area") or 0.0, 0.0))]
    tipo = [1.0 if m.get("kind") == k else 0.0 for k in KINDS]
    otros = [float(bool(m.get("bw"))), float((m.get("aspect") or 1.0) > 1.0),
             float(m.get("novios") or 0), momento, momento ** 2]
    partes = [estilo, caras, tipo, otros]
    if extra is not None:
        partes.append(np.asarray(extra, dtype=np.float64))
    return np.concatenate([np.asarray(p, dtype=np.float64) for p in partes])


def day_positions(fotos: list[dict]) -> dict[str, float]:
    """Posición de cada foto en el día, de 0 (primera) a 1 (última)."""
    horas = {f["rel"]: datetime.fromisoformat(f["taken"]).timestamp() for f in fotos if f.get("taken")}
    if not horas:
        return {}
    t0, t1 = min(horas.values()), max(horas.values())
    span = max(t1 - t0, 1.0)
    return {rel: (t - t0) / span for rel, t in horas.items()}


def moments(fotos: list[dict], publicadas: set[str]) -> list[dict]:
    """Una fila por ráfaga: la toma que eligió él si eligió alguna, si no la representante."""
    por_grupo: dict[int, list[dict]] = {}
    for f in fotos:
        por_grupo.setdefault(f["group"], []).append(f)
    filas = []
    for grupo, miembros in por_grupo.items():
        elegida = [f for f in miembros if f["rel"] in publicadas]
        foto = elegida[0] if elegida else min(miembros, key=lambda f: f["rank_in_group"])
        filas.append({"foto": foto, "label": bool(elegida), "grupo": grupo})
    filas.sort(key=lambda r: r["foto"].get("taken") or "")
    return filas


class Preference:
    def __init__(self, mean: np.ndarray, scale: np.ndarray, weights: np.ndarray, bias: float,
                 meta: dict | None = None) -> None:
        self.mean, self.scale, self.weights, self.bias = mean, scale, weights, bias
        self.meta = meta or {}

    @classmethod
    def fit(cls, X: np.ndarray, y: np.ndarray, l2: float = L2) -> "Preference":
        mean = X.mean(axis=0)
        scale = X.std(axis=0)
        scale[scale < 1e-6] = 1.0
        Z = (X - mean) / scale
        # Pesos por clase: sin esto, con 6 % de positivos, el modelo aprende a decir que no a todo
        pos = max(y.sum(), 1)
        neg = max(len(y) - y.sum(), 1)
        sample_w = np.where(y, len(y) / (2 * pos), len(y) / (2 * neg))
        w = np.zeros(Z.shape[1])
        b = 0.0
        # Con L2 muy grande el paso de la regularización se pasa de largo y el descenso explota
        # (sale AUC 0.000). El paso se achica para que nunca invierta el signo del peso.
        lr = min(LEARNING_RATE, 0.5 * len(y) / l2) if l2 > 0 else LEARNING_RATE
        for _ in range(ITERATIONS):
            p = 1 / (1 + np.exp(-(Z @ w + b)))
            error = (p - y) * sample_w
            grad_w = Z.T @ error / len(y) + l2 * w / len(y)
            grad_b = error.mean()
            w -= lr * grad_w
            b -= lr * grad_b
        return cls(mean, scale, w, b, {"positivos": int(y.sum()), "negativos": int(len(y) - y.sum())})

    def score(self, X: np.ndarray) -> np.ndarray:
        Z = (np.atleast_2d(X) - self.mean) / self.scale
        return 1 / (1 + np.exp(-(Z @ self.weights + self.bias)))

    def top_features(self, labels: list[str], n: int = 8) -> list[tuple[str, float]]:
        order = np.argsort(-np.abs(self.weights))[:n]
        return [(labels[i], round(float(self.weights[i]), 3)) for i in order]

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({
            "version": MODEL_VERSION, "mean": self.mean.tolist(), "scale": self.scale.tolist(),
            "weights": self.weights.tolist(), "bias": self.bias, "meta": self.meta,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Preference":
        d = json.loads(path.read_text(encoding="utf-8-sig"))
        if d.get("version") != MODEL_VERSION:
            raise ValueError(f"{path.name} es de otra versión: hay que reentrenarlo")
        return cls(np.array(d["mean"]), np.array(d["scale"]), np.array(d["weights"]),
                   float(d["bias"]), d.get("meta", {}))

# --- datos para entrenar con varios casamientos ------------------------------------------

def vector_clip(embedding, m: dict, momento: float) -> np.ndarray:
    """Rasgos de una foto para el modelo entrenado: el contenido (CLIP) y unos pocos extras.

    El embedding manda; los extras agregan lo que CLIP no mira: cuánta gente hay, qué tan grande
    está la cara, en qué parte del día cae. La estandarización de fit() los pone en la misma escala.
    """
    extras = [math.log1p(m.get("faces") or 0), math.sqrt(max(m.get("face_area") or 0.0, 0.0))]
    extras += [1.0 if m.get("kind") == k else 0.0 for k in KINDS]
    extras += [float(bool(m.get("bw"))), float((m.get("aspect") or 1.0) > 1.0),
               momento, momento ** 2]
    return np.concatenate([np.asarray(embedding, dtype=np.float64), np.asarray(extras)])


def names_clip(dim: int = 512) -> list[str]:
    return ([f"clip{i}" for i in range(dim)] + ["log_caras", "raiz_area_cara"]
            + [f"tipo_{k}" for k in KINDS] + ["bn", "apaisada", "momento", "momento2"])


def etiquetas(album: Path) -> set[str] | None:
    """Las fotos que él eligió de este álbum, juntando las dos fuentes que hay.

    - publicadas.json (verdad.py): lo que publicó en Instagram, ubicado en el álbum.
    - elegidas.json (modo "con mis elegidas"): lo que eligió para el post desde la interfaz.
    - correcciones.jsonl: cada foto que puso a mano en lugar de la que había propuesto la
      herramienta (sólo suman a alguna de las otras dos).

    Las dos son la misma señal —"de todo el álbum, él se quedó con éstas"—, y la segunda llega
    sin esperar a que publique. None si el álbum no tiene ninguna.
    """
    from . import album as album_lib

    cache = Path(album) / album_lib.CACHE_DIRNAME
    encontradas: set[str] | None = None
    for archivo, clave in (("publicadas.json", "publicadas"), ("elegidas.json", "elegidas")):
        ruta = cache / archivo
        if ruta.is_file():
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError:
                continue
            encontradas = (encontradas or set()) | set(datos.get(clave, []))
    # Las correcciones solas no alcanzan para etiquetar un álbum: si cambió una slide de veinte,
    # las otras diecinueve no son "fotos que no eligió". Sólo suman a una etiqueta que ya existe.
    correcciones = Path(__file__).resolve().parents[1] / "correcciones.jsonl"
    if encontradas is not None and correcciones.is_file():
        propio = str(Path(album).resolve())
        for linea in correcciones.read_text(encoding="utf-8-sig").splitlines():
            try:
                registro = json.loads(linea)
            except json.JSONDecodeError:
                continue
            if registro.get("entra") and str(Path(registro.get("album", "")).resolve()) == propio:
                encontradas = (encontradas or set()) | {registro["entra"]}
    return encontradas


def analisis(album: Path, salidas: Path | None = None) -> Path | None:
    """Dónde está el analisis.json del álbum: en su caché, o en la carpeta de salida."""
    from . import album as album_lib

    for ruta in (Path(album) / album_lib.CACHE_DIRNAME / "analisis.json",
                 (Path(salidas) / Path(album).name / "analisis.json") if salidas else None):
        if ruta is not None and ruta.is_file():
            return ruta
    return None


def dataset(albumes: list, salidas, cargar_embeddings) -> tuple:
    """Arma (X, y, casamiento) con un renglón por momento de cada casamiento etiquetado.

    La unidad es el momento y no la foto: si él eligió la tercera toma de una ráfaga, las otras
    no son "fotos que descartó", son la misma foto.
    """
    from . import album as album_lib

    X, y, boda = [], [], []
    for album in albumes:
        cache = album / album_lib.CACHE_DIRNAME
        publicadas = etiquetas(album)
        archivo = analisis(album, salidas)
        if not publicadas or archivo is None:
            continue
        fotos = json.loads(archivo.read_text(encoding="utf-8-sig"))["fotos"]
        photos = album_lib.load_index(cache)
        embeddings = cargar_embeddings(album)
        posiciones = day_positions(fotos)
        for fila in moments(fotos, publicadas):
            m = fila["foto"]
            photo = photos.get(m["rel"])
            if photo is None or photo.key not in embeddings:
                continue
            X.append(vector_clip(embeddings[photo.key], m, posiciones.get(m["rel"], 0.5)))
            y.append(fila["label"])
            boda.append(album.name)
    return np.array(X), np.array(y, dtype=bool), np.array(boda)
