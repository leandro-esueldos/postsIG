"""Armar post: de la carpeta de un casamiento a una selección para Instagram.

Uso:
  python curator/curate.py "D:/bodas/martina-y-juan"
  python curator/curate.py "D:/bodas/martina-y-juan" --top 150 --out salida/martina

Fases 1 y 2 (ver curator/PLAN.md): ingesta, filtro técnico, agrupado de repetidas y caras
—cuántas hay, si parpadearon, cómo están expuestas y si están los novios—. Deja en la carpeta
de salida las hojas de contacto para mirar y el analisis.json que consumen las fases siguientes
(estilo, guion y montaje).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import album as album_lib
from lib import changes, dedup, embed, models, moments, quality, selection, sheet, style
from lib import elegidas as elegidas_lib

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
MODELO_ESTILO = ROOT / "modelo_estilo.json"
REFERENCIAS = ROOT / "referencias.npz"
MODELO_PREFERENCIA = ROOT / "modelo_preferencia.json"
PREF_NEIGHBOURS = 3         # contra cuántas de sus publicadas se compara cada foto
PREF_FLOOR = 0.4            # piso del factor de preferencia: la técnica sigue pesando
# Él publica fotos con menos gente que el promedio del álbum (mediana de 2 caras contra 4 en MJ):
# las de invitados son para el álbum de los novios, y su Instagram vende su trabajo —la pareja,
# los detalles—. Sola, esa señal predice casi tanto como CLIP (AUC 0.571 contra 0.575 en MJ), y
# juntas llegan a 0.59. El peso sale de un solo casamiento: se deja por debajo del mejor valor
# medido (0.35) para no sobreajustar.
PREF_FEWER_PEOPLE = 0.25
CORRECCIONES = ROOT / "correcciones.jsonl"
METRICS_VERSION = 6


def load_config() -> dict:
    # utf-8-sig: si el JSON se editó desde PowerShell puede venir con BOM
    base = json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.is_file() else {}
    return base


def analyze(photos: list, album: Path, workers: int, couple=None) -> None:
    """Completa photo.metrics: técnica, hash perceptual y caras. Reusa lo ya calculado."""
    from lib import faces

    # El caché de caras depende de a quién se declaró como novios, así que cambiar --novios
    # obliga a recalcular
    version = str(METRICS_VERSION) + ("p" if faces.BLINK_ENABLED else "")
    if couple:
        version += f"n{len(couple.identities)}"
    pending = [p for p in photos if p.metrics.get("v") != version]
    if not pending:
        print(f"  métricas: {len(photos)} en caché", flush=True)
        return
    print(f"  métricas y caras: {len(pending)} a calcular", flush=True)
    # Los modelos se piden acá, con un solo hilo. Si se dejara para adentro del pool, los ocho
    # hilos intentarían bajar el mismo archivo a la vez la primera vez que se corre.
    models.path("yunet")
    if faces.BLINK_ENABLED:
        models.path("landmarker")

    def one(photo) -> None:
        with Image.open(album_lib.thumb_path(album, photo)) as im:
            im.load()
            data = quality.analyze(im)
            data["hash"] = dedup.dhash(im)
            rgb = np.asarray(im.convert("RGB"))
        gray = (rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114).astype(np.float32)
        data.update(faces.analyze(rgb, gray, couple))
        data["estilo"] = style.features(rgb, gray, data)
        data["v"] = version
        photo.metrics = data

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for _ in pool.map(one, pending):
            done += 1
            if done % 200 == 0:
                print(f"    {done}/{len(pending)}", flush=True)


TIPO_CORTO = {"retrato": "RET", "pareja": "PAR", "grupo": "GRU", "lejos": "LEJ", "detalle": "DET"}


def _slide_cell(album: Path, entry: dict) -> dict:
    """Celda de la hoja de slides: el número de slide adelante y el capítulo como marca."""
    photo = entry["photo"]
    hora = photo.taken_dt()
    prefijo = f"{entry['slide']:02d}  " if "slide" in entry else ""
    return {
        "path": album_lib.thumb_path(album, photo),
        "caption": f"{prefijo}{hora:%H:%M}  {photo.name}" if hora else f"{prefijo}{photo.name}",
        "score": photo.metrics["score"],
        "badge": entry["capitulo"][:4].upper(),
    }


def _cells(album: Path, pairs: list[tuple]) -> list[dict]:
    """Traduce (foto, grupo) a las celdas que dibuja lib/sheet.py."""
    from lib import faces as faces_lib

    cells = []
    for photo, group in pairs:
        metrics = photo.metrics
        marks = []
        if metrics.get("kind"):
            marks.append(TIPO_CORTO.get(metrics["kind"], ""))
        if metrics.get("novios"):
            marks.append("♥" * metrics["novios"])
        if (metrics.get("blink") or 0) > faces_lib.BLINK_OK:
            marks.append("OJOS")
        if "score_estilo" in metrics:
            marks.append(f"e{metrics['score_estilo']:.2f}")
        if metrics["bw"]:
            marks.append("BN")
        if group["group_size"] > 1:
            marks.append(f"x{group['group_size']}")
        hora = photo.taken_dt()
        cells.append({
            "path": album_lib.thumb_path(album, photo),
            "caption": f"{hora:%H:%M}  {photo.name}" if hora else photo.name,
            "score": metrics["score"],
            "badge": " ".join(m for m in marks if m) or None,
        })
    return cells


def preference_scores(album: Path, photos: list, embeddings: dict) -> dict[str, float] | None:
    """Cuánto le gustaría a él cada foto, en percentil 0–1 dentro del álbum.

    Con modelo entrenado (entrenar.py --modelo) usa el modelo, que aprendió de lo que publicó en
    varios casamientos. Si no hay —o si este casamiento entró al entrenamiento— cae en comparar
    contra sus fotos publicadas más parecidas.

    En los dos casos el casamiento se puntúa sin sus propias respuestas: si no, uno ya etiquetado
    se copiaría, y cualquier medición sobre él saldría inflada. Se devuelve el percentil dentro
    del álbum y no el valor crudo, porque el parecido entre fotos de casamiento vive en un rango
    angosto.
    """
    if not embeddings:
        return None
    if MODELO_PREFERENCIA.is_file():
        puntajes = _preference_model(album, photos, embeddings)
        if puntajes is not None:
            return puntajes
    if not REFERENCIAS.is_file():
        return None
    data = np.load(REFERENCIAS)
    otros = data["origen"] != album.name
    refs = data["vectors"][otros]
    if len(refs) < PREF_NEIGHBOURS:
        return None
    keys = [p.key for p in photos]
    X = np.stack([embeddings[k] for k in keys])
    parecido = np.sort(X @ refs.T, axis=1)[:, -PREF_NEIGHBOURS:].mean(axis=1)

    def percentil(valores: np.ndarray) -> np.ndarray:
        return valores.argsort().argsort() / max(len(valores) - 1, 1)

    poca_gente = -np.log1p([p.metrics.get("faces") or 0 for p in photos])
    mezcla = ((1 - PREF_FEWER_PEOPLE) * percentil(parecido)
              + PREF_FEWER_PEOPLE * percentil(np.asarray(poca_gente)))
    rangos = percentil(mezcla)
    print(f"  preferencia: parecido con {len(refs)} fotos que publicó en "
          f"{len(set(data['origen'][otros]))} casamientos", flush=True)
    return {k: float(r) for k, r in zip(keys, rangos)}


def _preference_model(album: Path, photos: list, embeddings: dict) -> dict[str, float] | None:
    """Puntaje del modelo entrenado, en percentil dentro del álbum."""
    from lib import preference as pref_lib
    try:
        modelo = pref_lib.Preference.load(MODELO_PREFERENCIA)
    except (ValueError, json.JSONDecodeError) as err:
        print(f"  modelo de preferencia ignorado: {err}", flush=True)
        return None
    entrenado = modelo.meta.get("casamientos", [])
    if album.name in entrenado:
        # Este casamiento esta adentro del modelo: puntuarlo con el es copiarse la respuesta, y
        # todo lo que se mida sobre el sale inflado. Se cae al parecido, que si sabe excluirlo.
        print(f"  el modelo se entrenó con {album.name}: para no copiarse la respuesta, acá se "
              f"usa el parecido sin sus propias fotos", flush=True)
        return None
    horas = [p.taken for p in photos]
    t0 = min(h for h in horas if h) if any(horas) else None
    t1 = max(h for h in horas if h) if any(horas) else None
    span = 1.0
    if t0 and t1:
        span = max((datetime.fromisoformat(t1) - datetime.fromisoformat(t0)).total_seconds(), 1.0)
    X = []
    for p in photos:
        momento = 0.5
        if p.taken and t0:
            momento = (datetime.fromisoformat(p.taken)
                       - datetime.fromisoformat(t0)).total_seconds() / span
        X.append(pref_lib.vector_clip(embeddings[p.key], p.metrics, momento))
    valores = modelo.score(np.array(X))
    rangos = valores.argsort().argsort() / max(len(valores) - 1, 1)
    print(f"  preferencia: modelo entrenado con {modelo.meta.get('positivos', '?')} fotos que "
          f"publicó en {len(entrenado)} casamientos", flush=True)
    return {p.key: float(r) for p, r in zip(photos, rangos)}


def load_style(config: dict) -> tuple:
    """Carga el modelo de estilo, si está, y con cuánto peso entra en el puntaje final."""
    peso = float(config.get("estilo", {}).get("peso", 0.0))
    if not MODELO_ESTILO.is_file():
        return None, 0.0
    try:
        modelo = style.StyleModel.load(MODELO_ESTILO)
    except ValueError as err:
        print(f"  modelo de estilo ignorado: {err}", flush=True)
        return None, 0.0
    meta = modelo.meta
    estado = (f"{meta.get('positivos', 0)} publicadas de referencia, "
              f"{meta.get('negativos', 0)} descartes")
    if peso:
        print(f"  estilo: {estado}, pesa {peso:.0%} en el puntaje", flush=True)
    else:
        print(f"  estilo: {estado}. Se calcula y se muestra pero NO ordena "
              f"(peso 0 en config.json: sin descartes todavía no discrimina)", flush=True)
    return modelo, peso


def report_faces(photos: list, best: list, couple) -> None:
    """Qué encontró la etapa de caras, en una línea por cosa que le sirva a Diego."""
    from collections import Counter
    from lib import faces as faces_lib

    kinds = Counter(p.metrics.get("kind", "?") for p in photos)
    orden = ["retrato", "pareja", "grupo", "lejos", "detalle"]
    resumen = ", ".join(f"{kinds[k]} {k}" for k in orden if kinds.get(k))
    print(f"  qué hay en el álbum: {resumen}", flush=True)

    cerrados = [p for p in photos if (p.metrics.get("blink") or 0) > faces_lib.BLINK_OK]
    rescatadas = sum(
        1 for p, g in best
        if g["group_size"] > 1 and (p.metrics.get("blink") or 0) <= faces_lib.BLINK_OK
    )
    print(f"  ojos cerrados: {len(cerrados)} fotos. En {rescatadas} ráfagas se pudo elegir "
          f"una toma con todos mirando", flush=True)

    if couple is not None:
        con_los_dos = sum(1 for p in photos if (p.metrics.get("novios") or 0) >= 2)
        con_uno = sum(1 for p in photos if p.metrics.get("novios") == 1)
        print(f"  novios: {con_los_dos} fotos con los dos, {con_uno} con uno solo", flush=True)


def plan_signature(config: dict) -> str:
    """Huella de las reglas con que se arma el post: versión del montaje y config que lo afecta."""
    import hashlib
    from lib import montage
    partes = json.dumps({"post": config.get("post"), "montaje": config.get("montaje")},
                        sort_keys=True, ensure_ascii=False)
    return f"{montage.PLAN_VERSION}-{hashlib.blake2b(partes.encode(), digest_size=6).hexdigest()}"


def build_post(album: Path, out: Path, slides: list, representantes: list, config: dict,
               photos: list, embeddings: dict | None = None, planear: bool = True) -> None:
    """Arma las slides desde los originales: sola a sangre, entera sobre gris, o collage."""
    from lib import montage

    pool: dict[str, list] = {}
    for photo in representantes:
        pool.setdefault(photo.metrics.get("capitulo"), []).append(photo)

    # El plan de la corrida anterior, para no mover lo que él no tocó
    previo = {}
    anterior = out / "seleccion.json"
    if anterior.is_file():
        try:
            datos = json.loads(anterior.read_text(encoding="utf-8-sig"))
            # Sólo se reusa un plan armado con las mismas reglas y la misma config: si no, cosas
            # que cambió el algoritmo se leerían como cambios que pidió él
            if datos.get("firma") == plan_signature(config):
                previo = {s["rel"]: s for s in datos.get("slides", [])}
        except (json.JSONDecodeError, KeyError):
            previo = {}
    if planear:
        montage.plan(slides, pool, config, previo, {p.rel: p for p in photos}, embeddings)

    destino = out / "slides"
    if destino.is_dir():
        for viejo in destino.glob("*.jpg"):
            viejo.unlink()
    print("Montaje (desde los originales):", flush=True)
    armado = datetime.now().replace(microsecond=0)
    previas, fotos_totales, cortadas = [], 0, []
    for entry in slides:
        fotos = entry["fotos"]
        paths = [album / p.rel for p in fotos]
        if entry["plantilla"]:
            img, cortes = montage.render(entry["plantilla"], fotos, paths, seed=entry["slide"])
            tipo = entry["plantilla"]
        else:
            img, tipo, corte = montage.render_single(entry["photo"], paths[0])
            cortes = [corte]
            entry["render"] = tipo
        entry["cortes"] = cortes
        dest = destino / f"{entry['slide']:02d}.jpg"
        montage.save(img, dest, orden=entry["slide"], base=armado)
        fotos_totales += len(fotos)
        for photo, corte in zip(fotos, cortes):
            if corte > 0.15:
                cortadas.append((entry["slide"], photo.name, corte))
        print(f"  {entry['slide']:02d}  {tipo:9} {len(fotos)} foto{'s' if len(fotos) > 1 else ' '}  "
              f"{', '.join(p.name for p in fotos)}", flush=True)
        previa = img.copy()
        previa.thumbnail((270, 338))
        previas.append(previa)

    print(f"  {len(slides)} slides, {fotos_totales} fotos en total", flush=True)
    if cortadas:
        for slide, nombre, corte in cortadas:
            print(f"  ojo: en la slide {slide:02d}, a {nombre} le quedó afuera el "
                  f"{corte:.0%} de las caras", flush=True)
    else:
        print("  ninguna cara quedó cortada por el recorte", flush=True)

    # Vista del post como carrusel: todas las slides juntas, para mirarlo de un vistazo
    cols = 5
    rows = (len(previas) + cols - 1) // cols
    hoja = Image.new("RGB", (cols * 278 + 8, rows * 346 + 8), (18, 16, 14))
    for i, previa in enumerate(previas):
        hoja.paste(previa, (8 + (i % cols) * 278, 8 + (i // cols) * 346))
    hoja.save(out / "post.jpg", "JPEG", quality=88)
    print(f"  post.jpg  {hoja.width}x{hoja.height}  (el carrusel completo de un vistazo)", flush=True)


def armar_con_elegidas(args, album: Path, out: Path, photos: list, representantes: list,
                       config: dict, n_slides: int, archivo_cambios: Path) -> tuple[list, str, int]:
    """Modo 'con mis elegidas': entran todas las fotos que eligió él, repartidas en collages.

    La lista vive en out/elegidas.txt, que es la fuente de verdad: la primera vez se arma desde lo
    que se pasó (una carpeta, un archivo o --todas), y después los cambios a mano se guardan ahí.
    """
    import bisect

    lista_path = out / elegidas_lib.ARCHIVO
    por_nombre: dict = {}
    for p in photos:
        por_nombre.setdefault(p.name.lower(), p)

    # Una lista que ya existe manda sobre lo que se pase: tiene los cambios a mano de corridas
    # anteriores, y volver a copiarla desde la carpeta o el archivo original los desharía
    fuente = Path(args.elegidas).expanduser().resolve() if args.elegidas else None
    if fuente is not None and not fuente.exists():
        sys.exit(f"No existe {fuente}")
    if fuente is not None and fuente.is_file() and fuente == lista_path.resolve():
        pass                                     # la interfaz pasa la lista misma
    elif lista_path.is_file():
        if fuente is not None or args.todas:
            print(f"  se usa la lista que ya estaba en {lista_path} (borrarla para empezar de "
                  f"nuevo desde lo que se pasó)", flush=True)
    elif args.todas:
        elegidas_lib.guardar(lista_path, [(p.name, False) for p in photos])
    elif fuente is not None and fuente.is_dir():
        elegidas_lib.guardar(lista_path, elegidas_lib.desde_carpeta(fuente))
    elif fuente is not None:
        elegidas_lib.guardar(lista_path, elegidas_lib.leer(fuente))
    items = elegidas_lib.leer(lista_path)

    items, hechos = elegidas_lib.aplicar_cambios(archivo_cambios, out / "seleccion.json",
                                                 items, por_nombre)
    if hechos:
        print(f"Cambios pedidos ({len(hechos)}):", flush=True)
        for linea in hechos:
            print(f"  {linea}", flush=True)
        elegidas_lib.guardar(lista_path, items)

    faltan = [n for n, _ in items if n.lower() not in por_nombre]
    elegidas = [por_nombre[n.lower()] for n, _ in items if n.lower() in por_nombre]
    solas = {por_nombre[n.lower()].name for n, s in items if s and n.lower() in por_nombre}
    print(f"Con sus elegidas: {len(elegidas)} fotos", flush=True)
    if faltan:
        print(f"  ojo: {len(faltan)} de la lista no están en el álbum: "
              f"{', '.join(faltan[:10])}{'…' if len(faltan) > 10 else ''}", flush=True)
    if not elegidas:
        sys.exit("Ninguna de las elegidas está en el álbum: revisar que los nombres coincidan")

    # Las elegidas que no son la representante de su ráfaga no tienen tramo del día: se les da
    # el de la representante más cercana en la hora
    marcas = [(p.taken or "", p) for p in representantes]
    horas = [m[0] for m in marcas]
    for p in elegidas:
        if "bloque" in p.metrics or not marcas:
            continue
        i = min(bisect.bisect_left(horas, p.taken or ""), len(marcas) - 1)
        vecinas = [marcas[j][1] for j in (i - 1, i) if 0 <= j < len(marcas)]
        cerca = min(vecinas, key=lambda r: abs(
            (r.taken_dt() - p.taken_dt()).total_seconds()) if r.taken_dt() and p.taken_dt() else 0)
        p.metrics["bloque"] = cerca.metrics.get("bloque", 0)
        p.metrics["capitulo"] = cerca.metrics.get("capitulo", "?")

    # Lo que eligió él de un álbum completo es la mejor etiqueta que existe: se guarda para
    # entrenar (entrenar_todo.py la usa igual que lo que publicó)
    if not args.todas and len(elegidas) <= 0.5 * len(photos):
        cache = album / album_lib.CACHE_DIRNAME
        (cache / "elegidas.json").write_text(json.dumps({
            "album": str(album), "generado": datetime.now().isoformat(timespec="seconds"),
            "elegidas": sorted(p.rel for p in elegidas),
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    slides, afuera, aviso = elegidas_lib.pack(elegidas, solas, n_slides, config)
    return slides, aviso, len(elegidas)


def describe(photos: list) -> None:
    stamps = [p.taken for p in photos if p.taken]
    if stamps:
        first, last = datetime.fromisoformat(min(stamps)), datetime.fromisoformat(max(stamps))
        hours = (last - first).total_seconds() / 3600
        # Si cruza la medianoche hay que mostrar la fecha del final, si no "16:00 a 19:20" con
        # 27 horas al lado no se entiende
        cierre = f"{last:%H:%M}" if first.date() == last.date() else f"{last:%d/%m %H:%M}"
        print(f"  cubre {first:%d/%m/%Y %H:%M} a {cierre} ({hours:.1f} h)", flush=True)
        if hours > 18:
            print(f"  ojo: {hours:.0f} horas es mucho para un casamiento, "
                  f"¿la carpeta tiene material de más de un evento?", flush=True)
    cameras = sorted({p.camera for p in photos if p.camera})
    if cameras:
        print(f"  cámaras: {', '.join(cameras)}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Armar post: de un álbum de casamiento a las slides")
    parser.add_argument("album", nargs="?", help="carpeta con las fotos ya reveladas y exportadas a JPEG")
    parser.add_argument("--out", help="carpeta de salida (por defecto curator/salida/<álbum>)")
    parser.add_argument("--top", type=int, default=120, help="cuántos momentos entran en la hoja de contacto")
    parser.add_argument("--orden", choices=("hora", "tecnica"), default="hora",
                        help="cómo se ordena la hoja: por hora de captura (se lee como el casamiento) o por puntaje")
    parser.add_argument("--novios", help="carpeta con 3 o 4 fotos donde salgan los novios, para reconocerlos")
    parser.add_argument("--modelos", action="store_true", help="baja los modelos de cara y sale")
    parser.add_argument("--sin-montaje", action="store_true",
                        help="elige las slides pero no las arma (más rápido para probar parámetros)")
    parser.add_argument("--elegidas", help="modo 'con mis elegidas': un elegidas.txt con los nombres, "
                        "o una carpeta con copias de las fotos que eligió. Entran todas al post")
    parser.add_argument("--todas", action="store_true",
                        help="modo 'con mis elegidas' usando todas las fotos de la carpeta")
    parser.add_argument("--slides", type=int, help="tope de slides (por defecto post.slides de config.json)")
    parser.add_argument("--preparar", action="store_true",
                        help="sólo arma las miniaturas (para elegir fotos desde la interfaz) y sale")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    if args.modelos:
        models.fetch_all()
        return

    if not args.album:
        sys.exit("Falta la carpeta del álbum")
    album = Path(args.album).expanduser().resolve()
    if not album.is_dir():
        sys.exit(f"No existe la carpeta {album}")
    out = Path(args.out).expanduser().resolve() if args.out else ROOT / "salida" / album.name
    config = load_config()
    grouping = config.get("agrupado", {})
    from lib import faces as faces_lib
    faces_lib.BLINK_ENABLED = bool(config.get("caras", {}).get("parpadeo", False))

    couple = None
    if args.novios:
        from lib import faces
        reference = Path(args.novios).expanduser().resolve()
        if not reference.is_dir():
            sys.exit(f"No existe la carpeta de referencia {reference}")
        print(f"Novios: {reference}", flush=True)
        couple = faces.Couple(reference)
        for line in couple.sources:
            print(f"  {line}", flush=True)
        if not couple.identities:
            sys.exit("No se encontró ninguna cara en las fotos de referencia")
        print(f"  {len(couple.identities)} personas distintas reconocidas", flush=True)
        if len(couple.identities) > 2:
            print("  ojo: salieron más de dos personas. Conviene dejar sólo fotos donde estén "
                  "ellos dos, o recortarlas", flush=True)

    print(f"Álbum: {album}", flush=True)
    photos = album_lib.build(album, workers=args.workers)
    if not photos:
        sys.exit("No se encontraron fotos que se puedan abrir (los RAW hay que exportarlos antes)")
    describe(photos)
    if args.preparar:
        print(f"Miniaturas listas: {len(photos)} fotos", flush=True)
        return

    analyze(photos, album, args.workers, couple)
    album_lib.save_index(album / album_lib.CACHE_DIRNAME, photos)

    modelo, peso_estilo = load_style(config)
    try:
        embeddings = embed.for_album(album, photos, album_lib.thumb_path)
    except (SystemExit, Exception) as err:        # noqa: BLE001 - sin CLIP se sigue igual
        # Sin CLIP (no se pudo bajar el modelo, o no hay onnxruntime) el post se arma igual,
        # ordenado por técnica y caras: peor, pero mejor que no tener nada
        print(f"  ojo: sin el modelo de contenido (CLIP), la preferencia no ordena: {err}", flush=True)
        embeddings = None
    preferencia = preference_scores(album, photos, embeddings)
    scored = quality.score_album([p.metrics for p in photos])
    for photo, data in zip(photos, scored):
        photo.metrics = {**photo.metrics, **data}
        if modelo and photo.metrics.get("estilo"):
            photo.metrics["score_estilo"] = modelo.score(photo.metrics["estilo"])
        # Técnica y caras multiplican: una foto donde parpadearon no se salva por estar nítida.
        # El estilo entra con el peso de config.json, que hoy es 0 mientras no discrimine.
        final = photo.metrics["score_tecnico"] * photo.metrics.get("score_caras", 1.0)
        if peso_estilo and "score_estilo" in photo.metrics:
            final *= (1 - peso_estilo) + peso_estilo * photo.metrics["score_estilo"]
        # La preferencia (parecido con lo que publica) ordena; la técnica y las caras son la
        # puerta: una foto movida o con ojos cerrados no entra por mucho que se parezca a lo suyo.
        # Dentro de una ráfaga las tomas son casi iguales en contenido, así que ahí sigue mandando
        # la técnica, que es lo que corresponde para elegir la toma.
        # La toma dentro de una ráfaga se elige sólo por técnica: entre cuadros casi idénticos
        # la preferencia es ruido, y pasada a percentil ese ruido alcanzaba para cambiar la toma
        photo.metrics["score_toma"] = round(final, 3)
        if preferencia is not None:
            photo.metrics["score_pref"] = round(preferencia[photo.key], 3)
            final *= PREF_FLOOR + (1 - PREF_FLOOR) * preferencia[photo.key]
        photo.metrics["score"] = round(final, 3)

    groups = dedup.group(
        photos,
        [p.metrics["hash"] for p in photos],
        [p.metrics["score_toma"] for p in photos],
        tiebreak=[p.metrics["sharp"] for p in photos],
        gap=grouping.get("gap_segundos", dedup.GAP_SECONDS),
        burst_distance=grouping.get("distancia_rafaga", dedup.BURST_DISTANCE),
        duplicate_distance=grouping.get("distancia_repetida", dedup.DUPLICATE_DISTANCE),
    )
    stats = dedup.summary(groups)
    print(f"  {len(photos)} fotos -> {stats['grupos']} momentos distintos "
          f"({stats['repetidas']} repetidas, la ráfaga más larga fue de {stats['grupo_mayor']})", flush=True)
    if stats["sospechosos"]:
        print(f"  ojo: {stats['sospechosos']} grupos de {dedup.GRUPO_SOSPECHOSO} fotos o más. "
              f"Una ráfaga real no llega a eso: puede ser que se hayan encadenado escenas "
              f"parecidas y se pierda alguna. Mirar descartadas.jpg", flush=True)

    best = [(p, g) for p, g in zip(photos, groups) if g["rank_in_group"] == 0]
    best.sort(key=lambda pair: -pair[0].metrics["score"])
    flojas = sum(1 for p, _ in best if p.metrics["score"] < 0.35)
    print(f"  de esos momentos, {flojas} quedan flojos "
          f"(nitidez, exposición o gente con los ojos cerrados)", flush=True)
    report_faces(photos, best, couple)

    out.mkdir(parents=True, exist_ok=True)

    # --- el post: capítulos del día y las slides que entran --------------------------------
    post = config.get("post", {})
    capitulos = post.get("capitulos", moments.CHAPTERS)
    representantes = [p for p, _ in sorted(best, key=lambda pair: pair[0].taken or "")]
    bloques = moments.cut(representantes, len(capitulos) * moments.BLOCKS_PER_CHAPTER)
    nombres = moments.label(representantes, bloques, capitulos)
    for photo, bloque in zip(representantes, bloques):
        photo.metrics["bloque"] = bloque
        photo.metrics["capitulo"] = nombres.get(bloque, capitulos[0])

    print("Capítulos del día:", flush=True)
    for fila in moments.describe(representantes, bloques, nombres):
        desde = datetime.fromisoformat(fila["desde"]) if fila["desde"] else None
        hasta = datetime.fromisoformat(fila["hasta"]) if fila["hasta"] else None
        rango = f"{desde:%H:%M} a {hasta:%H:%M}" if desde and hasta else "sin hora"
        print(f"  {fila['capitulo']:14} {rango}   {fila['fotos']} momentos "
              f"en {fila['bloques']} bloque{'s' if fila['bloques'] > 1 else ''}", flush=True)
    print("  (el corte sale de las pausas reales del día; el nombre es una heurística "
          "y se puede cambiar en config.json)", flush=True)

    n_slides = min(args.slides or post.get("slides", 20), 20)
    if post.get("reparto", "proporcional") == "proporcional":
        # Proporcional a cuántos momentos tiene cada bloque del día, corregido por el sesgo de
        # cada capítulo: la cámara dispara muchísimo en la fiesta y él no la publica en esa
        # proporción. Medido sobre sus casamientos etiquetados (ver post.sesgo en config.json).
        sesgo = post.get("sesgo", {})
        tamanos = {b: bloques.count(b) * float(sesgo.get(nombres.get(b, ""), 1.0))
                   for b in sorted(set(bloques))}
        unidades, cupos, unidad = list(tamanos), selection.proportional(tamanos, n_slides), "bloque"
    else:
        unidades, cupos, unidad = capitulos, post.get("cupos", {}), "capitulo"
    archivo_cambios = out / "cambios.txt"
    modo_elegidas = bool(args.elegidas or args.todas)
    if modo_elegidas:
        slides, aviso, n_elegidas = armar_con_elegidas(
            args, album, out, photos, representantes, config, n_slides, archivo_cambios)
        usadas = [{"photo": p} for e in slides for p in e["fotos"]]
        suplentes = selection.spares(representantes, usadas, per_chapter=24)
    else:
        n_elegidas = None
        slides, aviso = selection.pick(
            representantes, unidades, cupos, n_slides, post.get("apertura", "mejor"),
            embeddings, unidad)

        # Lo que él pidió cambiar en una corrida anterior, si escribió algo en cambios.txt
        pedidos, errores = changes.read(archivo_cambios)
        for error in errores:
            print(f"  cambios.txt, {error}", flush=True)
        if pedidos:
            print(f"Cambios pedidos en cambios.txt ({len(pedidos)}):", flush=True)
            for linea in changes.apply(slides, pedidos, photos, album, CORRECCIONES):
                print(f"  {linea}", flush=True)
        suplentes = selection.spares(representantes, slides, per_chapter=24)
    changes.ensure_template(archivo_cambios)
    print(f"Post: {len(slides)} slides", flush=True)
    if aviso:
        print(f"  ojo: {aviso}", flush=True)
    for entry in slides:
        hora = entry["photo"].taken_dt()
        print(f"  {entry['slide']:02d}  {entry['capitulo']:14} "
              f"{hora:%H:%M}  {entry['photo'].name:16} {entry['motivo']}", flush=True)

    sheet.write([_slide_cell(album, e) for e in slides], out, "seleccion",
                f"{album.name} · las {len(slides)} slides del post, en orden")

    if not args.sin_montaje:
        build_post(album, out, slides, representantes, config, photos, embeddings,
                   planear=not modo_elegidas)
    if suplentes:
        sheet.write([_slide_cell(album, e) for e in suplentes], out, "suplentes",
                    f"{album.name} · suplentes por capítulo, para cambiar alguna")

    # El corte es siempre por puntaje, pero la hoja se mira mejor en orden cronológico: así se
    # lee como el casamiento y se nota si falta un momento.
    elegidas = best[:args.top]
    if args.orden == "hora":
        elegidas = sorted(elegidas, key=lambda pair: pair[0].taken or "")
    print("Hojas de contacto:", flush=True)
    criterio = "en orden cronológico" if args.orden == "hora" else "ordenados por puntaje"
    sheet.write(_cells(album, elegidas), out, "contacto",
                f"{album.name} · {len(elegidas)} mejores momentos, {criterio}")

    # Las peores, para revisar que el filtro no se haya llevado puesto nada bueno
    descartadas = best[args.top:][-min(72, len(best) - args.top):] if len(best) > args.top else []
    if descartadas:
        sheet.write(_cells(album, descartadas), out, "descartadas",
                    f"{album.name} · las {len(descartadas)} peores, para controlar el filtro")

    (out / "seleccion.json").write_text(json.dumps({
        "album": str(album),
        "generado": datetime.now().isoformat(timespec="seconds"),
        "firma": plan_signature(config),
        "modo": "elegidas" if modo_elegidas else "ia",
        "elegidas": n_elegidas,
        "capitulos": moments.describe(representantes, bloques, nombres),
        "slides": [
            {"slide": e["slide"], "capitulo": e["capitulo"], "rel": e["photo"].rel,
             "taken": e["photo"].taken, "score": e["photo"].metrics["score"],
             "kind": e["photo"].metrics.get("kind"), "motivo": e["motivo"],
             "plantilla": e.get("plantilla") or e.get("render", "sola"),
             "fotos": [p.rel for p in e.get("fotos", [e["photo"]])],
             # La interfaz necesita nombre y miniatura de cada foto, no sólo su ruta
             "detalle": [{"rel": p.rel, "name": p.name, "key": p.key}
                         for p in e.get("fotos", [e["photo"]])],
             "bloque": e["photo"].metrics.get("bloque"),
             "sujeto_cortado": e.get("cortes", [])}
            for e in slides
        ],
        "suplentes": [
            {"capitulo": e["capitulo"], "rel": e["photo"].rel, "name": e["photo"].name,
             "key": e["photo"].key, "taken": e["photo"].taken,
             "bloque": e["photo"].metrics.get("bloque"),
             "kind": e["photo"].metrics.get("kind"),
             "score": e["photo"].metrics["score"]} for e in suplentes
        ],
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    payload = {
        "album": str(album),
        "generado": datetime.now().isoformat(timespec="seconds"),
        "fase": 4,
        "novios": len(couple.identities) if couple else None,
        "resumen": {"fotos": len(photos), **stats, "flojas": flojas},
        "fotos": [
            {"rel": p.rel, "name": p.name, "key": p.key, "taken": p.taken,
             "aspect": round(p.aspect, 3), **g, **p.metrics}
            for p, g in zip(photos, groups)
        ],
    }
    texto = json.dumps(payload, ensure_ascii=False, indent=1)
    (out / "analisis.json").write_text(texto, encoding="utf-8")
    # Una copia en el caché del álbum: el entrenamiento la necesita, y así no depende de dónde
    # quedó la salida ni de qué modo se usó para armar el post
    (album / album_lib.CACHE_DIRNAME / "analisis.json").write_text(texto, encoding="utf-8")
    print(f"Salida en {out}", flush=True)


if __name__ == "__main__":
    main()
