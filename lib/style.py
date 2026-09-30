"""Rasgos de estilo y el modelo que puntúa cuánto se parece una foto a lo que él publica.

La técnica dice "esta foto no está rota". El estilo dice "esta es de las que él elegiría". Son
cosas distintas: un álbum tiene cientos de fotos correctas y él publica veinte.

**El modelo es de vecinos, no de promedio.** Lo que publica no es una sola cosa: hay drone sobre
viñedos, macro de anillos, blanco y negro de ceremonia y caos de fiesta. Un modelo que aprenda
"el centro" de eso puntuaría alto un promedio que no se parece a nada suyo. Midiendo contra las
fotos suyas *más parecidas* —las tres más cercanas— cada familia se compara con la suya.

**Con una sola clase, por ahora.** Un ranker entrenado necesita negativos, o sea las fotos que él
descartó, y ésas sólo existen en un álbum real. Hasta que haya uno, el modelo se arma sólo con
positivos y puntúa por cercanía. `train_estilo.py` ya acepta negativos y correcciones: el día que
lleguen, el modelo pasa solo a discriminativo sin tocar los rasgos.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np

TILES = 8
HUE_BINS = 6
BRIGHT_TILE, DARK_TILE = 235.0, 40.0
NEIGHBOURS = 3              # contra cuántas fotos suyas se compara cada foto nueva
MODEL_VERSION = 2

# Estandarizar con la desviación absoluta mediana sola no funciona acá: rasgos como "tejas
# quemadas" valen cero en casi todas sus fotos, la dispersión da cero y cualquier desvío se
# vuelve infinito. La escala de cada rasgo es la mayor entre esa desviación y un cuarto del
# rango observado, que es lo que le da sentido a un rasgo casi siempre nulo.
SCALE_FLOOR = 0.01          # último recurso, sólo si el rasgo vale exactamente lo mismo en todas
Z_CLIP = 5.0                # ningún rasgo solo puede dominar la distancia

# El orden importa: es el del vector que se guarda en el modelo
FEATURES = [
    "warmth", "sat", "colorfulness", "contrast", "lum", "p05n", "p50n", "p95n",
    "hue0", "hue1", "hue2", "hue3", "hue4", "hue5",
    "bokeh", "edges", "bright_tiles", "dark_tiles", "sky", "vgrad", "center_pop",
    "faces_n", "face_scale", "thirds", "aspect",
]


def _tile_medians(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape
    th, tw = max(1, h // TILES), max(1, w // TILES)
    return np.array([
        np.median(gray[r * th:(r + 1) * th, c * tw:(c + 1) * tw])
        for r in range(TILES) for c in range(TILES)
    ])


def features(rgb: np.ndarray, gray: np.ndarray, metrics: dict) -> dict:
    """Vector de estilo de una foto. Reusa lo que ya midieron quality.py y faces.py."""
    height, width = gray.shape
    out: dict[str, float] = {}

    # Tono y color, casi todo ya medido
    out["warmth"] = metrics.get("warmth", 0.0)
    out["sat"] = metrics.get("sat", 0.0)
    out["colorfulness"] = metrics.get("colorfulness", 0.0)
    out["contrast"] = metrics.get("contrast", 0.0)
    out["lum"] = metrics.get("lum", 0.0)
    for name, key in (("p05n", "p05"), ("p50n", "p50"), ("p95n", "p95")):
        out[name] = metrics.get(key, 0.0) / 255.0

    # Paleta: histograma de tono pesado por saturación, así el gris no vota
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, saturation = hsv[:, :, 0].astype(np.float32), hsv[:, :, 1].astype(np.float32) / 255.0
    weights = saturation.ravel()
    total = float(weights.sum()) or 1.0
    histogram, _ = np.histogram(hue.ravel(), bins=HUE_BINS, range=(0, 180), weights=weights)
    for i, value in enumerate(histogram / total):
        out[f"hue{i}"] = float(value)

    # Estructura
    sharp, sharp_global = metrics.get("sharp", 1.0), max(metrics.get("sharp_global", 1.0), 1.0)
    # Cuánto se despega la zona nítida del resto: alto = poca profundidad de campo, su retrato
    out["bokeh"] = math.log1p(sharp / sharp_global)
    lap = (4.0 * gray[1:-1, 1:-1] - gray[:-2, 1:-1] - gray[2:, 1:-1]
           - gray[1:-1, :-2] - gray[1:-1, 2:])
    out["edges"] = float(np.abs(lap).mean()) / 255.0

    medians = _tile_medians(gray)
    out["bright_tiles"] = float((medians > BRIGHT_TILE).mean())
    out["dark_tiles"] = float((medians < DARK_TILE).mean())

    # Cielo: azul y claro en la mitad de arriba. Sus planos abiertos de Mendoza viven de esto.
    top = rgb[: height // 2]
    blue = (top[:, :, 2] > top[:, :, 0] + 12) & (top[:, :, 2] > 90)
    out["sky"] = float(blue.mean())

    # Cómo cae la luz de arriba a abajo, y cuánto se despega el centro de los bordes
    rows = gray.mean(axis=1)
    index = np.arange(len(rows), dtype=np.float32)
    out["vgrad"] = float(np.corrcoef(index, rows)[0, 1]) if rows.std() > 1e-6 else 0.0
    y0, y1 = height // 3, 2 * height // 3
    x0, x1 = width // 3, 2 * width // 3
    center = float(gray[y0:y1, x0:x1].mean())
    mask = np.ones_like(gray, dtype=bool)
    mask[y0:y1, x0:x1] = False
    out["center_pop"] = center / max(float(gray[mask].mean()), 1.0)

    # Sujeto
    faces = metrics.get("faces", 0) or 0
    out["faces_n"] = min(faces, 6) / 6.0
    out["face_scale"] = math.sqrt(max(metrics.get("face_area", 0.0) or 0.0, 0.0))
    out["thirds"] = _thirds(metrics, width, height)
    out["aspect"] = width / height if height else 1.0
    return {k: round(float(v), 5) for k, v in out.items()}


def _thirds(metrics: dict, width: int, height: int) -> float:
    """Distancia del sujeto al punto de tercios más cercano, 0 = justo encima."""
    box = metrics.get("face_box")
    if not box:
        return 0.5                       # sin cara no hay sujeto claro; queda en el medio
    cx = (box[0] + box[2] / 2) / width
    cy = (box[1] + box[3] / 2) / height
    return min(math.hypot(cx - px, cy - py) for px in (1 / 3, 2 / 3) for py in (1 / 3, 2 / 3))


def vector(feature_dict: dict) -> np.ndarray:
    return np.array([feature_dict.get(name, 0.0) for name in FEATURES], dtype=np.float64)


class StyleModel:
    """Puntúa cuánto se parece una foto a las que él publicó.

    Guarda las fotos de referencia ya estandarizadas. Estandariza con mediana y desviación
    absoluta mediana, no con media y desvío: con 24 fotos, una sola rara corre el promedio.
    """

    def __init__(self, center: np.ndarray, scale: np.ndarray, points: np.ndarray,
                 escala_puntaje: float, negatives: np.ndarray | None = None,
                 weights: np.ndarray | None = None, meta: dict | None = None) -> None:
        self.center = center
        self.scale = scale
        self.points = points
        self.escala_puntaje = escala_puntaje
        self.negatives = negatives
        self.weights = weights if weights is not None else np.ones(len(FEATURES))
        self.meta = meta or {}

    # -- construcción ----------------------------------------------------------------

    @classmethod
    def fit(cls, positives: list[dict], negatives: list[dict] | None = None) -> "StyleModel":
        data = np.array([vector(f) for f in positives], dtype=np.float64)
        if len(data) < NEIGHBOURS + 1:
            raise ValueError(f"hacen falta al menos {NEIGHBOURS + 1} fotos de referencia")
        center = np.median(data, axis=0)
        mad = np.median(np.abs(data - center), axis=0) * 1.4826
        rango = (np.percentile(data, 95, axis=0) - np.percentile(data, 5, axis=0)) / 4.0
        scale = np.maximum(np.maximum(mad, rango), SCALE_FLOOR)

        weights = np.ones(len(FEATURES))
        negative_points = None
        if negatives:
            # Con negativos se pesa cada rasgo por cuánto separa: los que valen lo mismo en las
            # publicadas y en las descartadas dejan de opinar.
            neg = np.array([vector(f) for f in negatives], dtype=np.float64)
            negative_points = (neg - center) / scale
            separacion = np.abs(np.median(negative_points, axis=0))
            weights = np.clip(separacion, 0.15, 3.0)
            weights = weights / weights.mean()

        points = (data - center) / scale
        # La escala del puntaje sale de cuánto se parecen entre sí sus propias fotos: así un 1.0
        # significa "tan de su estilo como lo son sus fotos entre ellas", y no un número abstracto.
        propias = [cls._distance(points[i], np.delete(points, i, axis=0), weights)
                   for i in range(len(points))]
        escala = float(np.median(propias)) or 1.0
        return cls(center, scale, points, escala, negative_points, weights,
                   {"positivos": len(data), "negativos": len(negatives or [])})

    # -- uso -------------------------------------------------------------------------

    @staticmethod
    def _distance(point: np.ndarray, points: np.ndarray, weights: np.ndarray) -> float:
        """Distancia a las NEIGHBOURS fotos más parecidas, no al promedio de todas."""
        # Recortar en Z_CLIP evita que un solo rasgo raro —un formato apaisado, un cielo
        # quemado— tape todo lo demás y mande la foto al fondo por una sola cosa.
        diffs = np.clip((points - point), -Z_CLIP, Z_CLIP) * weights
        distances = np.sqrt((diffs ** 2).mean(axis=1))
        k = min(NEIGHBOURS, len(distances))
        return float(np.sort(distances)[:k].mean())

    def score(self, feature_dict: dict) -> float:
        """0 a 1: 1 es tan parecida a su material como lo son sus fotos entre sí."""
        point = (vector(feature_dict) - self.center) / self.scale
        distance = self._distance(point, self.points, self.weights)
        # Decae suave: al doble de la distancia típica entre sus fotos, el puntaje ya es ~0.37
        return round(float(math.exp(-distance / max(self.escala_puntaje, 1e-6))), 4)

    def explain(self, feature_dict: dict, top: int = 4) -> list[tuple[str, float]]:
        """Los rasgos que más la alejan de su material, para poder discutir el puntaje."""
        point = (vector(feature_dict) - self.center) / self.scale
        diffs = np.clip(self.points - point, -Z_CLIP, Z_CLIP) * self.weights
        closest = self.points[int(np.argmin(np.sqrt((diffs ** 2).mean(axis=1))))]
        gap = np.abs(np.clip(point - closest, -Z_CLIP, Z_CLIP) * self.weights)
        order = np.argsort(-gap)[:top]
        return [(FEATURES[i], round(float(gap[i]), 2)) for i in order]

    # -- persistencia ----------------------------------------------------------------

    def save(self, path: Path) -> None:
        payload = {
            "version": MODEL_VERSION,
            "features": FEATURES,
            "vecinos": NEIGHBOURS,
            "center": self.center.tolist(),
            "scale": self.scale.tolist(),
            "weights": self.weights.tolist(),
            "points": self.points.tolist(),
            "escala_puntaje": self.escala_puntaje,
            "meta": self.meta,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "StyleModel":
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if data.get("version") != MODEL_VERSION or data.get("features") != FEATURES:
            raise ValueError(f"{path.name} es de otra versión de rasgos: hay que reentrenarlo")
        return cls(
            np.array(data["center"]), np.array(data["scale"]), np.array(data["points"]),
            data["escala_puntaje"], None, np.array(data["weights"]), data.get("meta", {}),
        )
