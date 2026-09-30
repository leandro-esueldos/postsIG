"""Descarga y caché de los modelos de cara.

Son cuatro, y cada uno hace una cosa distinta:

- **yunet** (OpenCV Zoo, 230 KB): encuentra las caras. Es el que corre sobre todas las fotos,
  así que tiene que ser rápido.
- **landmarker** (MediaPipe, 3,7 MB): sobre las caras que importan, devuelve los blendshapes,
  entre ellos cuánto está cerrado cada ojo. Es lo que contesta "¿parpadearon?".
- **sface** (OpenCV Zoo, 37 MB): convierte una cara en un vector comparable, para saber si los
  que están en la foto son los novios. Sólo se baja si se usa --novios.
- **clip** (CLIP ViT-B/32 de imagen, cuantizado, 85 MB): describe qué hay en cada foto. Es la
  base de la preferencia, que es lo que ordena (ver entrenar.py).

El landmarker sólo se usa si se prende el parpadeo en config.json (viene apagado).

Se guardan en curator/modelos/ y se bajan una sola vez.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "modelos"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) curator"

# Los modelos del OpenCV Zoo están en Git LFS: raw.githubusercontent.com devuelve el puntero de
# texto, no el archivo. El contenido real lo sirve media.githubusercontent.com.
SOURCES = {
    "yunet": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "face_detection_yunet_2023mar.onnx",
        200_000,
    ),
    "landmarker": (
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
        "face_landmarker/float16/1/face_landmarker.task",
        "face_landmarker.task",
        3_000_000,
    ),
    "sface": (
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "face_recognition_sface_2021dec.onnx",
        30_000_000,
    ),
    # CLIP ViT-B/32, sólo la parte de imagen, cuantizada a 8 bits (84 MB en vez de 335). Da un
    # vector de 512 que describe qué hay en la foto. Es lo que hizo falta: el álbum ya viene
    # curado por técnica y revelado parejo, así que lo que separa lo que él publica es el contenido.
    "clip": (
        "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/"
        "vision_model_quantized.onnx",
        "clip_vit_b32_vision_q8.onnx",
        80_000_000,
    ),
}


def path(name: str, download: bool = True) -> Path:
    """Ruta local del modelo, bajándolo la primera vez."""
    if name not in SOURCES:
        raise KeyError(f"modelo desconocido: {name}")
    url, filename, minimum = SOURCES[name]
    dest = MODELS / filename
    if dest.is_file() and dest.stat().st_size >= minimum:
        return dest
    if not download:
        sys.exit(f"Falta el modelo {name} en {dest}. Correr: python curator/curate.py --modelos")

    MODELS.mkdir(parents=True, exist_ok=True)
    print(f"  bajando {name} ({filename})...", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=180) as response, open(tmp, "wb") as fh:
            fh.write(response.read())
    except (urllib.error.URLError, TimeoutError) as err:
        tmp.unlink(missing_ok=True)
        sys.exit(f"No se pudo bajar {name} desde {url}\n  {err}")

    # Un servidor que devuelve un puntero de LFS, un HTML de error o una descarga cortada deja un
    # archivo que parece estar y no sirve. Mejor que falle acá que al cargar el modelo.
    head = tmp.read_bytes()[:64]
    if head.startswith(b"version https://git-lfs"):
        tmp.unlink(missing_ok=True)
        sys.exit(f"{url} devolvió el puntero de Git LFS en vez del modelo")
    if tmp.stat().st_size < minimum:
        actual = tmp.stat().st_size
        tmp.unlink(missing_ok=True)
        sys.exit(f"{name} vino incompleto: {actual} bytes, se esperaban al menos {minimum}")
    tmp.replace(dest)
    size = dest.stat().st_size / 1024 / 1024
    print(f"  {filename}: {size:.1f} MB", flush=True)
    return dest


def fetch_all(names: list[str] | None = None) -> None:
    for name in names or list(SOURCES):
        local = path(name)
        digest = hashlib.blake2b(local.read_bytes(), digest_size=8).hexdigest()
        print(f"  {name}: {local.name}  {local.stat().st_size / 1024 / 1024:.1f} MB  {digest}", flush=True)
