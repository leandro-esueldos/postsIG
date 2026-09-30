"""Recorrido del álbum, lectura de EXIF y caché de miniaturas.

Todo el análisis posterior trabaja sobre las miniaturas: abrir 3.000 originales en cada corrida
costaría media hora y volvería imposible probar parámetros. El caché es incremental, se invalida
por (ruta, fecha de modificación, tamaño).
"""
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageFile, ImageOps

# Un JPG al que le faltan los últimos bytes —pasa con exportaciones y descargas de Drive— está
# entero en la práctica: PIL por defecto lo rechaza y la foto se perdería. Con esto se abre, y si
# lo que falta es mucho, la parte gris que queda la manda al fondo el filtro técnico.
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
# Los RAW no se abren: hay que exportarlos revelados, que es lo que define su estilo.
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".rw2", ".orf", ".dng", ".heic", ".heif"}
CACHE_DIRNAME = ".curator"
# Carpetas dentro del álbum que no son el casamiento: el caché, y las fotos de referencia de los
# novios, que conviene dejar adentro del álbum para que viajen juntas pero no son material del post
SKIP_DIRS = {CACHE_DIRNAME, "novios"}
THUMB_SIDE = 1024
INDEX_VERSION = 1

EXIF_IFD = 0x8769
TAG_TAKEN = 36867          # DateTimeOriginal
TAG_TAKEN_ALT = 36868      # DateTimeDigitized
TAG_SUBSEC = 37521         # SubsecTimeOriginal, ordena las ráfagas dentro del mismo segundo
TAG_ISO = 34855
TAG_FNUMBER = 33437
TAG_EXPOSURE = 33434
TAG_FOCAL = 37386
TAG_LENS = 42036
TAG_MODEL = 272


@dataclass
class Photo:
    """Una foto del álbum con sus metadatos y la ruta a su miniatura cacheada."""

    rel: str                    # ruta relativa al álbum, con barras normales
    name: str                   # nombre sin extensión, lo que se ve en la hoja de contacto
    key: str                    # identificador estable, y nombre del archivo de miniatura
    width: int
    height: int
    mtime: float
    size: int
    taken: str | None = None    # ISO 8601, de EXIF o (si no hay) de la fecha del archivo
    taken_from_exif: bool = False
    taken_original: str | None = None   # si la hora se corrigió por el orden de los archivos
    camera: str | None = None
    lens: str | None = None
    iso: int | None = None
    fnumber: float | None = None
    exposure: float | None = None
    focal: float | None = None
    metrics: dict = field(default_factory=dict)

    @property
    def aspect(self) -> float:
        return self.width / self.height if self.height else 1.0

    def taken_dt(self) -> datetime | None:
        return datetime.fromisoformat(self.taken) if self.taken else None


def _key(rel: str) -> str:
    return hashlib.blake2b(rel.encode("utf-8"), digest_size=8).hexdigest()


def _ratio(value) -> float | None:
    # PIL devuelve IFDRational; float() alcanza salvo división por cero
    try:
        return round(float(value), 4)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _read_exif(im: Image.Image) -> dict:
    out: dict = {}
    try:
        exif = im.getexif()
    except Exception:
        return out
    if not exif:
        return out
    ifd = exif.get_ifd(EXIF_IFD) or {}
    raw_taken = ifd.get(TAG_TAKEN) or ifd.get(TAG_TAKEN_ALT) or exif.get(306)
    if raw_taken:
        try:
            stamp = datetime.strptime(str(raw_taken).strip(), "%Y:%m:%d %H:%M:%S")
            subsec = str(ifd.get(TAG_SUBSEC) or "").strip()
            if subsec.isdigit():
                stamp = stamp.replace(microsecond=int(subsec[:6].ljust(6, "0")))
            out["taken"] = stamp.isoformat()
            out["taken_from_exif"] = True
        except ValueError:
            pass
    model = exif.get(TAG_MODEL)
    if model:
        out["camera"] = str(model).strip()
    lens = ifd.get(TAG_LENS)
    if lens:
        out["lens"] = str(lens).strip()
    iso = ifd.get(TAG_ISO)
    if isinstance(iso, (int, float)):
        out["iso"] = int(iso)
    elif isinstance(iso, tuple) and iso:
        out["iso"] = int(iso[0])
    for tag, name in ((TAG_FNUMBER, "fnumber"), (TAG_EXPOSURE, "exposure"), (TAG_FOCAL, "focal")):
        value = _ratio(ifd.get(tag))
        if value:
            out[name] = value
    return out


def scan(album: Path) -> tuple[list[Path], list[Path]]:
    """Devuelve (fotos que se pueden abrir, archivos RAW encontrados)."""
    usable, raws = [], []
    for path in sorted(album.rglob("*")):
        relativas = {p.lower() for p in path.relative_to(album).parts[:-1]}
        if not path.is_file() or relativas & SKIP_DIRS:
            continue
        suffix = path.suffix.lower()
        if suffix in EXTENSIONS:
            usable.append(path)
        elif suffix in RAW_EXTENSIONS:
            raws.append(path)
    return usable, raws


def _make_thumb(path: Path, album: Path, thumbs: Path) -> Photo | None:
    rel = path.relative_to(album).as_posix()
    key = _key(rel)
    stat = path.stat()
    try:
        with Image.open(path) as src:
            width, height = src.size
            data = _read_exif(src)
            # draft() decodifica el JPEG ya escalado: es lo que hace que 3.000 fotos tarden
            # minutos y no horas. Después se ajusta al tamaño exacto.
            src.draft("RGB", (THUMB_SIDE, THUMB_SIDE))
            im = ImageOps.exif_transpose(src).convert("RGB")
    except Exception as err:
        print(f"  no se pudo abrir {rel}: {err}", flush=True)
        return None
    if max(im.size) > THUMB_SIDE:
        scale = THUMB_SIDE / max(im.size)
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.LANCZOS)
    im.save(thumbs / f"{key}.jpg", "JPEG", quality=88)
    # El ancho y alto que valen son los de la foto ya rotada según EXIF
    if (im.width > im.height) != (width > height):
        width, height = height, width
    photo = Photo(
        rel=rel, name=path.stem, key=key, width=width, height=height,
        mtime=stat.st_mtime, size=stat.st_size,
    )
    for field_name, value in data.items():
        setattr(photo, field_name, value)
    if not photo.taken:
        photo.taken = datetime.fromtimestamp(stat.st_mtime).isoformat()
    return photo


REPAIR_JUMP = 1800.0        # segundos: una foto que se sale de sus vecinas por más que esto se corrige
REPAIR_MAX_SHARE = 0.03     # si más del 3 % salta hacia atrás, la numeración no es cronológica


def _number(name: str) -> int | None:
    match = re.search(r"(\d+)(?!.*\d)", name)
    return int(match.group(1)) if match else None


def repair_times(photos: list[Photo]) -> int:
    """Corrige la hora de las fotos retocadas aparte, usando el orden de los archivos.

    Cuando se retoca una foto en Photoshop, la fecha del EXIF pasa a ser la del retoque: en MJ,
    cuatro fotos quedaron fechadas tres días después del casamiento, y el curador las mandaba al
    final del día. Pero él exporta numerado por hora de captura, así que el número del archivo
    sabe dónde va cada foto aunque el EXIF mienta.

    Sólo se corrige si la numeración es de verdad cronológica (casi ningún salto hacia atrás), y
    sólo las fotos que se salen de sus dos vecinas por más de media hora. Devuelve cuántas corrigió.
    """
    numeradas = [(n, p) for p in photos if (n := _number(p.name)) is not None and p.taken]
    if len(numeradas) < 0.8 * len(photos) or len(numeradas) < 3:
        return 0
    numeradas.sort(key=lambda np_: np_[0])
    ordenadas = [p for _, p in numeradas]
    horas = [datetime.fromisoformat(p.taken).timestamp() for p in ordenadas]
    atras = sum(1 for a, b in zip(horas, horas[1:]) if b < a)
    if atras > REPAIR_MAX_SHARE * len(horas):
        return 0

    corregidas = 0
    for i, photo in enumerate(ordenadas):
        antes = horas[i - 1] if i > 0 else None
        despues = horas[i + 1] if i + 1 < len(horas) else None
        vecinas = [h for h in (antes, despues) if h is not None]
        if not vecinas:
            continue
        # Se sale de TODAS sus vecinas, y las vecinas entre sí son coherentes
        if all(abs(horas[i] - h) > REPAIR_JUMP for h in vecinas):
            if antes is not None and despues is not None and abs(despues - antes) > REPAIR_JUMP:
                continue                 # las vecinas tampoco coinciden: no hay con qué corregir
            nueva = sum(vecinas) / len(vecinas)
            photo.taken_original = photo.taken_original or photo.taken
            photo.taken = datetime.fromtimestamp(nueva).isoformat()
            horas[i] = nueva
            corregidas += 1
    return corregidas


def load_index(cache: Path) -> dict[str, Photo]:
    index = cache / "index.json"
    if not index.is_file():
        return {}
    try:
        data = json.loads(index.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    if data.get("version") != INDEX_VERSION:
        return {}
    return {item["rel"]: Photo(**item) for item in data.get("photos", [])}


def save_index(cache: Path, photos: list[Photo]) -> None:
    payload = {"version": INDEX_VERSION, "photos": [asdict(p) for p in photos]}
    (cache / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def build(album: Path, workers: int = 8) -> list[Photo]:
    """Deja el caché al día y devuelve las fotos del álbum ordenadas por hora de captura."""
    cache = album / CACHE_DIRNAME
    thumbs = cache / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    files, raws = scan(album)
    if raws:
        print(f"  {len(raws)} archivos RAW ignorados: hay que exportarlos a JPEG revelados", flush=True)
    if not files:
        return []

    known = load_index(cache)
    photos: list[Photo] = []
    pending: list[Path] = []
    for path in files:
        rel = path.relative_to(album).as_posix()
        stat = path.stat()
        cached = known.get(rel)
        if cached and cached.mtime == stat.st_mtime and cached.size == stat.st_size \
                and (thumbs / f"{cached.key}.jpg").is_file():
            photos.append(cached)
        else:
            pending.append(path)

    if pending:
        print(f"  miniaturas: {len(pending)} nuevas, {len(photos)} ya estaban", flush=True)
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for photo in pool.map(lambda p: _make_thumb(p, album, thumbs), pending):
                done += 1
                if photo:
                    photos.append(photo)
                if done % 100 == 0:
                    print(f"    {done}/{len(pending)}", flush=True)
    else:
        print(f"  miniaturas: {len(photos)} en caché", flush=True)

    corregidas = repair_times(photos)
    if corregidas:
        nombres = ", ".join(p.name for p in photos if p.taken_original)[:120]
        print(f"  {corregidas} fotos con la hora corregida por el orden de los archivos "
              f"(retocadas aparte, el EXIF tenía la fecha del retoque): {nombres}", flush=True)

    sin_exif = sum(1 for p in photos if not p.taken_from_exif)
    if sin_exif:
        print(f"  ojo: {sin_exif} fotos sin fecha en EXIF, se usa la del archivo "
              f"(el agrupado por ráfaga va a ser peor)", flush=True)
    photos.sort(key=lambda p: (p.taken or "", p.rel))
    save_index(cache, photos)
    return photos


def thumb_path(album: Path, photo: Photo) -> Path:
    return album / CACHE_DIRNAME / "thumbs" / f"{photo.key}.jpg"
