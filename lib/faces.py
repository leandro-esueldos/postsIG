"""Caras: cuántas hay, qué tamaño tienen, si parpadearon y cómo están expuestas.

Es la etapa que más recorta después del agrupado de repetidas, porque contesta las dos preguntas
que descartan una foto de casamiento sin discusión: ¿alguien cerró los ojos? ¿la cara está
quemada o en sombra? Y de paso clasifica la foto —detalle, retrato, pareja, grupo—, que es lo
que después usa el guion para repartir las slides.

Dos modelos, por razones distintas:

- **YuNet** (OpenCV) encuentra las caras. Corre sobre todas las fotos, así que pesa 230 KB y
  tarda ~50 ms. Devuelve la caja, cinco puntos y una confianza.
- **FaceLandmarker** (MediaPipe) mide el parpadeo, y sólo corre sobre las caras que importan.
  Sobre el cuadro completo no ve las caras chicas, así que se le pasa la cara ya recortada y
  escalada: así lee caras de hasta ~50 px, contra las ~150 px que necesita en el cuadro entero.

Calibración, otra vez contra sus 24 publicadas (107 caras detectadas, 50 con parpadeo legible):

    confianza de cara     mediana 0.88; los falsos positivos de la foto de los anillos, 0.57-0.62
    parpadeo              mediana 0.28, p90 0.52, máximo 0.71, ninguna por encima de 0.85

Por eso el umbral de ojos cerrados va en 0.85: arriba de todo lo que él publicó. El valor tiene
margen del lado de los ojos abiertos, que es el que se pudo medir; del lado del parpadeo real
hace falta confirmarlo con un álbum de verdad, donde los haya.
"""
from __future__ import annotations

import os
import threading

# MediaPipe arrastra la telemetría de Google: intenta reportar uso a "clearcut", falla, y llena
# la pantalla con el error una vez por hilo y por minuto. Se silencia antes de importarlo.
os.environ.setdefault("GLOG_minloglevel", "3")
os.environ.setdefault("GLOG_logtostderr", "0")

import cv2
import numpy as np
from PIL import Image

from . import models

# OpenCV avisa por cada modelo ONNX que carga que el motor nuevo no soporta elegir target. No
# cambia nada del resultado y aparece en cada corrida; los errores de verdad siguen saliendo.
cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)

FACE_CONFIDENCE = 0.75      # abajo de esto son casi todos falsos positivos (anillos, flores, telas)

# El parpadeo usa MediaPipe, que trae compilada la telemetría de Google sin forma de apagarla. Y
# medido sobre un álbum real (MJ) no aporta: el álbum que él entrega ya viene sin ojos cerrados
# (5 de 1155), y la toma que queda de cada ráfaga coincide con la suya igual que al azar con o sin
# esto. Por eso va apagado; se prende con "caras.parpadeo" en config.json.
BLINK_ENABLED = False
BLINK_PX = 60               # cara más chica, en la miniatura, a la que el landmarker le ve los ojos
BLINK_FACES = 4             # a cuántas caras por foto se les mide el parpadeo, de mayor a menor
BLINK_OK, BLINK_SHUT = 0.85, 1.00
BLINK_WEIGHT_AREA = 0.02    # una cara que ocupa 2% del cuadro o más pesa completo al penalizar
CROP_MARGIN = 1.6           # cuánto se agranda la caja de la cara antes de recortarla
CROP_SIDE = 256             # a qué tamaño se escala el recorte para el landmarker

# Exposición sobre la cara: los mismos criterios que lib/quality.py, pero medidos donde importa.
# Esto es lo que resuelve el punto flojo de la fase 1: una foto con la mitad quemada y la mitad
# oscura promediaba bien en el histograma global; sobre la cara no.
#
# Medido sobre las 21 publicadas que tienen cara: la mediana de luz de la cara va de 91 a 142, y
# el percentil 95 de 150 a 255. Las rampas quedan bien afuera de eso: acá conviene dejar pasar
# una mala antes que voltear una buena, que para eso está el ojo de él al final.
FACE_BRIGHT_OK, FACE_BRIGHT_RUINED = 190.0, 245.0
FACE_DARK_OK, FACE_DARK_RUINED = 70.0, 20.0

# Identificar a los novios. Validado contra verdad conocida: fotos del mismo post son la misma
# pareja, de posts distintos son parejas distintas.
#
#     misma boda (4 pares)        similitud coseno 0.685 a 0.795
#     bodas distintas (101 pares) mediana 0.199, máximo 0.364
#
# OpenCV recomienda 0.363, que con estos datos deja pasar un falso. El umbral va en 0.50, en el
# medio del hueco. La muestra del lado positivo es chica (4 pares), así que conviene volver a
# mirarlo con el primer álbum real.
MATCH = 0.50
REFERENCE_PX = 70           # cara mínima, en la miniatura, para servir de referencia

_local = threading.local()


def _detector() -> cv2.FaceDetectorYN:
    if not hasattr(_local, "detector"):
        _local.detector = cv2.FaceDetectorYN.create(
            str(models.path("yunet")), "", (320, 320), FACE_CONFIDENCE, 0.3, 5000)
    return _local.detector


def _recognizer() -> cv2.FaceRecognizerSF:
    if not hasattr(_local, "recognizer"):
        _local.recognizer = cv2.FaceRecognizerSF.create(str(models.path("sface")), "")
    return _local.recognizer


def _landmarker():
    if not hasattr(_local, "landmarker"):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision
        _local.mp = mp
        _local.landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(models.path("landmarker"))),
                num_faces=1, output_face_blendshapes=True))
    return _local.landmarker


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def detect(rgb: np.ndarray) -> list[np.ndarray]:
    """Caras de la foto, de mayor a menor. Cada una es la fila de 15 valores de YuNet."""
    height, width = rgb.shape[:2]
    detector = _detector()
    detector.setInputSize((width, height))
    _, faces = detector.detect(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if faces is None:
        return []
    return sorted(faces, key=lambda f: -f[2] * f[3])


def _crop(rgb: np.ndarray, box) -> np.ndarray | None:
    x, y, w, h = box[:4]
    cx, cy = x + w / 2, y + h / 2
    side = max(w, h) * CROP_MARGIN
    x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
    x1, y1 = int(min(rgb.shape[1], cx + side / 2)), int(min(rgb.shape[0], cy + side / 2))
    crop = rgb[y0:y1, x0:x1]
    return crop if crop.size else None


def blink(rgb: np.ndarray, box) -> float | None:
    """Cuánto está cerrado el ojo más cerrado de esa cara, de 0 a 1. None si no se pudo leer."""
    crop = _crop(rgb, box)
    if crop is None:
        return None
    small = np.asarray(Image.fromarray(crop).resize((CROP_SIDE, CROP_SIDE), Image.LANCZOS))
    landmarker = _landmarker()
    result = landmarker.detect(_local.mp.Image(image_format=_local.mp.ImageFormat.SRGB, data=small))
    if not result.face_blendshapes:
        return None
    shapes = {c.category_name: c.score for c in result.face_blendshapes[0]}
    return max(shapes.get("eyeBlinkLeft", 0.0), shapes.get("eyeBlinkRight", 0.0))


SUBJECT_SHARE = 0.25        # una cara entra en el sujeto si tiene al menos 1/4 del área de la mayor


def _subject_box(faces: list, width: int, height: int) -> list[float] | None:
    """Unión de las caras que importan, con aire alrededor, en coordenadas 0-1."""
    if not faces:
        return None
    mayor = float(faces[0][2] * faces[0][3])
    principales = [f for f in faces if f[2] * f[3] >= SUBJECT_SHARE * mayor][:6]
    x0 = min(f[0] for f in principales)
    y0 = min(f[1] for f in principales)
    x1 = max(f[0] + f[2] for f in principales)
    y1 = max(f[1] + f[3] for f in principales)
    # La caja de YuNet es la cara justa: se agranda para incluir pelo arriba y mentón abajo
    ancho, alto = x1 - x0, y1 - y0
    x0, x1 = x0 - 0.25 * ancho / max(len(principales), 1), x1 + 0.25 * ancho / max(len(principales), 1)
    y0, y1 = y0 - 0.45 * alto, y1 + 0.25 * alto
    # float() explícito: los valores vienen de numpy (float32) y el JSON del caché no los acepta
    return [round(float(max(0.0, x0 / width)), 4), round(float(max(0.0, y0 / height)), 4),
            round(float(min(1.0, x1 / width)), 4), round(float(min(1.0, y1 / height)), 4)]


def _kind(faces: list, area_max: float) -> str:
    if not faces:
        return "detalle"
    if area_max < 0.004:            # caras diminutas: la foto es del lugar, no de la gente
        return "lejos"
    if len(faces) == 1:
        return "retrato"
    if len(faces) == 2:
        return "pareja"
    return "grupo"


def analyze(rgb: np.ndarray, gray: np.ndarray, couple=None) -> dict:
    """Métricas de cara de una foto, sobre la miniatura ya cargada."""
    height, width = rgb.shape[:2]
    frame = float(width * height)
    faces = detect(rgb)
    areas = [float(f[2] * f[3]) / frame for f in faces]
    area_max = max(areas, default=0.0)

    out = {
        "faces": len(faces),
        "face_area": round(area_max, 5),
        "face_px": round(float(max((max(f[2], f[3]) for f in faces), default=0.0)), 1),
        # Caja de la cara principal, que lib/style.py usa para ver dónde cae el sujeto
        "face_box": [round(float(v), 1) for v in faces[0][:4]] if faces else None,
        # Caja que abarca a todas las caras principales, en coordenadas 0-1. Es la que usa el
        # montaje para recortar: centrar en una sola cara le corta la cabeza al otro novio.
        "subject_box": _subject_box(faces, width, height),
        "kind": _kind(faces, area_max),
        "blink": None,
        "blink_leidas": 0,
        "face_p50": None,
        "face_p95": None,
        "novios": None,
        "score_caras": 1.0,
    }
    if not faces:
        if couple is not None:
            out["novios"] = 0
        return out
    if couple is not None:
        out["novios"] = couple.present(rgb, faces)

    # Parpadeo: sólo en las caras grandes. En una cara de 30 px nadie ve si parpadeó, y el
    # landmarker tampoco.
    peor, leidas = 0.0, 0
    for face, area in (list(zip(faces, areas))[:BLINK_FACES] if BLINK_ENABLED else []):
        if max(face[2], face[3]) < BLINK_PX:
            break                                   # vienen ordenadas, las que siguen son menores
        value = blink(rgb, face)
        if value is None:
            continue
        leidas += 1
        castigo = _clamp((value - BLINK_OK) / (BLINK_SHUT - BLINK_OK))
        peso = _clamp(area / BLINK_WEIGHT_AREA)     # una cara chica que parpadea no arruina la foto
        peor = max(peor, castigo * peso)
        out["blink"] = max(out["blink"] or 0.0, round(value, 3))
    out["blink_leidas"] = leidas

    # Exposición sobre las caras principales, que es donde el ojo mira primero
    recortes = []
    for face in faces[:BLINK_FACES]:
        x, y, w, h = (int(v) for v in face[:4])
        piece = gray[max(0, y):y + h, max(0, x):x + w]
        if piece.size:
            recortes.append(piece.ravel())
    expo = 1.0
    if recortes:
        pixels = np.concatenate(recortes)
        p50, p95 = (float(v) for v in np.percentile(pixels, (50, 95)))
        out["face_p50"], out["face_p95"] = round(p50, 1), round(p95, 1)
        expo = 1.0 - _clamp((p50 - FACE_BRIGHT_OK) / (FACE_BRIGHT_RUINED - FACE_BRIGHT_OK))
        expo *= 1.0 - _clamp((FACE_DARK_OK - p95) / (FACE_DARK_OK - FACE_DARK_RUINED))

    out["score_caras"] = round((1.0 - 0.75 * peor) * expo, 3)
    return out


def embed(rgb: np.ndarray, face) -> np.ndarray | None:
    """Vector comparable de una cara. None si no se pudo alinear."""
    try:
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return _recognizer().feature(_recognizer().alignCrop(bgr, face))
    except cv2.error:
        return None


class Couple:
    """Los novios, aprendidos de unas pocas fotos de referencia.

    Las caras de las fotos de referencia se agrupan solas por parecido, así que alcanza con una
    carpeta con tres o cuatro fotos donde salgan los dos: no hace falta decir cuál es cuál.
    """

    def __init__(self, folder) -> None:
        from pathlib import Path
        self.identities: list[list[np.ndarray]] = []
        self.sources: list[str] = []
        for path in sorted(Path(folder).iterdir()):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
                continue
            with Image.open(path) as src:
                im = src.convert("RGB")
            im.thumbnail((1024, 1024))
            rgb = np.asarray(im)
            found = 0
            for face in detect(rgb):
                if max(face[2], face[3]) < REFERENCE_PX:
                    break
                vector = embed(rgb, face)
                if vector is not None:
                    self._add(vector)
                    found += 1
            self.sources.append(f"{path.name}: {found} caras")

    def _add(self, vector: np.ndarray) -> None:
        """Suma la cara a la identidad que más se le parece, o abre una nueva."""
        recognizer = _recognizer()
        for group in self.identities:
            if max(recognizer.match(vector, other, cv2.FaceRecognizerSF_FR_COSINE)
                   for other in group) >= MATCH:
                group.append(vector)
                return
        self.identities.append([vector])

    def present(self, rgb: np.ndarray, found: list) -> int:
        """Cuántos de los novios están en esta foto."""
        if not self.identities:
            return 0
        recognizer = _recognizer()
        vectors = []
        for face in found[:BLINK_FACES]:
            if max(face[2], face[3]) < REFERENCE_PX:
                break
            vector = embed(rgb, face)
            if vector is not None:
                vectors.append(vector)
        if not vectors:
            return 0
        return sum(
            1 for group in self.identities
            if any(recognizer.match(v, other, cv2.FaceRecognizerSF_FR_COSINE) >= MATCH
                   for v in vectors for other in group)
        )
