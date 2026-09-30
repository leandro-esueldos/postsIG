"""Montaje: convierte la selección en las slides que él sube.

Tres decisiones, todas tomadas de sus propios posts:

**Las plantillas se midieron, no se inventaron.** Cada una sale de un collage que él publicó,
medido al píxel: color de fondo, margen, separación y celdas. Si mañana usa un collage nuevo, se
mide igual y se agrega a TEMPLATES.

**Se recorta alrededor del sujeto.** Con caras, el recorte abarca a todas las principales —no a
la más grande—, porque centrar en una sola le corta la cabeza al otro novio. Sin caras, se
centra en la zona más nítida, que es lo que el fotógrafo enfocó.

**Todo se renderiza desde los originales**, no desde las miniaturas del análisis, y se convierte
a sRGB. Si exporta en Adobe RGB e Instagram lo lee como sRGB, los colores se lavan: justo lo que
un fotógrafo nota primero.
"""
from __future__ import annotations

import io
import itertools
import math
import random
from pathlib import Path

from PIL import Image, ImageCms, ImageFilter, ImageOps

CANVAS = (1080, 1350)
JPEG_QUALITY = 95

# Coordenadas en píxeles sobre 1080x1350: (x, y, ancho, alto). Medidas de sus posts; las pocas
# que se derivaron y no se midieron lo dicen.
TEMPLATES = {
    # La que más usa: 27 de sus 101 slides publicadas (AF, AM, JJ, MN). Es adaptativa: el ancho
    # y los márgenes son fijos, pero el alto de cada foto cambia según la foto —602/692, 670/625,
    # 703/595— y siempre suma ~1294. Reparte el alto para recortar lo menos posible.
    "apilado_blanco": {
        "origen": "AF/AM/JJ/MN — dos apaisadas sobre blanco, alto repartido según las fotos",
        "fondo": (255, 255, 255),
        "caja": (18, 21, 1043, 1312),   # x, y, ancho, alto disponible para las dos y la separación
        "separacion": 18,
        "celdas": [(18, 21, 1043, 602), (18, 641, 1043, 692)],   # la variante más frecuente
    },
    # La fiesta de MJ (slides 18 y 19, idénticas): seis apaisadas 3:2 en dos columnas, sobre un
    # degradé lineal de 253 arriba a 137 abajo. Es la que le da energía al cierre: seis fotos de
    # pista en una slide. En sus otros posts la fiesta va en apilados, por eso no va primera.
    "grilla_6": {
        "origen": "MJ 18/19 — seis apaisadas en 2x3 sobre degradé",
        "fondo": (253, 253, 253),
        "degrade": (253, 137),
        "celdas": [(9, 108, 522, 347), (549, 108, 522, 347), (9, 502, 522, 347),
                   (549, 502, 522, 347), (9, 895, 522, 347), (549, 895, 522, 347)],
    },
    "grilla": {
        "origen": "C6aDmJ1JyeC-0 — cuatro retratos 4:5, separación fina",
        "fondo": (253, 252, 252),
        "celdas": [(7, 7, 529, 664), (544, 7, 529, 664), (7, 678, 529, 665), (544, 678, 529, 665)],
    },
    "apilado": {
        "origen": "DcmxP-iHGia-0 — dos apaisadas sobre gris",
        "fondo": (209, 209, 209),
        "celdas": [(77, 29, 926, 617), (77, 704, 926, 617)],
    },
    "mosaico": {
        "origen": "DD0rOoyJJA_-1 — a sangre, columnas 2:1",
        "fondo": (255, 255, 255),
        "celdas": [(0, 0, 714, 444), (0, 453, 714, 897), (723, 0, 357, 677), (723, 686, 357, 664)],
    },
    "detalles": {
        "origen": "DOe2CmnDITb-0 — cinco, detalles y un vertical alto",
        "fondo": (255, 255, 255),
        "celdas": [(20, 18, 388, 442), (425, 18, 635, 442), (20, 478, 485, 440),
                   (20, 938, 485, 394), (525, 478, 535, 854)],
    },
    "polaroid": {
        "origen": "C6aDmJ1JyeC-1 — cuatro polaroids con giro y sombra",
        # Medido al píxel: fondo blanco puro, marco en 247 con textura de papel, y en el borde de
        # abajo una línea fina y oscura (172) en vez de una sombra difusa grande
        "fondo": (255, 255, 255),
        "celdas": [(52, 74, 455, 470), (563, 71, 455, 470), (50, 706, 455, 470), (566, 708, 455, 470)],
        "marco": (22, 22, 112),          # lado, arriba, abajo
        "giro": 1.1,                     # grados, como máximo
    },
}

# "Entera": una foto sola, completa, sin recortar. Medida sobre sus posts (MN 7, TH 13, TH 14):
# a todo el ancho, centrada, con franjas blancas arriba y abajo. TH 13 es exactamente una 3:2 de
# 1080x720 con 315 de franja. Evita recortar a 4:5 un plano abierto de viñedos y dejar gente
# afuera en una grupal: recortar agresivo es una decisión creativa, que la tome él.
ENTERA_FONDO = (255, 255, 255)
ENTERA_CAJA = (0, 0, 1080, 1350)    # dónde tiene que entrar la foto completa
LANDSCAPE_LETTERBOX = 1.15      # más apaisada que esto y sin sujeto compacto: va entera
MAX_SUBJECT_CUT = 0.05          # en una slide sola, cortar más que esto de las caras no se acepta
SRGB = ImageCms.createProfile("sRGB")
SRGB_BYTES = ImageCms.ImageCmsProfile(SRGB).tobytes()


# --- abrir originales ---------------------------------------------------------------------

def open_original(path: Path, longest: int) -> Image.Image:
    """Abre el original, lo endereza por EXIF, lo pasa a sRGB y lo baja a un tamaño útil."""
    with Image.open(path) as src:
        icc = src.info.get("icc_profile")
        # Decodificar escalado: pedir el doble de lo que se va a usar alcanza y ahorra memoria
        src.draft("RGB", (longest * 2, longest * 2))
        im = ImageOps.exif_transpose(src)
        im = im.convert("RGB")
    if icc:
        try:
            origen = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if "srgb" not in (ImageCms.getProfileDescription(origen) or "").lower():
                im = ImageCms.profileToProfile(im, origen, SRGB, outputMode="RGB")
        except (ImageCms.PyCMSError, OSError):
            pass                        # perfil roto: mejor la foto sin convertir que ninguna
    return im


# --- recorte ------------------------------------------------------------------------------

def crop_window(width: int, height: int, aspect: float, subject=None, focus=None) -> tuple:
    """Ventana (x0, y0, x1, y1) con el aspecto pedido, lo más grande posible, sobre el sujeto.

    `subject` es la caja de las caras en 0–1; `focus`, el punto más nítido en 0–1.
    """
    if width / height > aspect:
        ch, cw = float(height), height * aspect
    else:
        cw, ch = float(width), width / aspect

    if subject:
        sx0, sy0, sx1, sy1 = (subject[0] * width, subject[1] * height,
                              subject[2] * width, subject[3] * height)
        cx, cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
        # Las caras un poco arriba del centro: es donde las pone el que encuadra bien
        x0, y0 = cx - cw / 2, cy - ch * 0.42
        # Si el sujeto entra entero en la ventana, que entre entero
        if sx1 - sx0 <= cw:
            x0 = min(max(x0, sx1 - cw), sx0)
        if sy1 - sy0 <= ch:
            y0 = min(max(y0, sy1 - ch), sy0)
    elif focus:
        x0, y0 = focus[0] * width - cw / 2, focus[1] * height - ch / 2
    else:
        x0, y0 = (width - cw) / 2, (height - ch) / 2

    x0 = min(max(x0, 0.0), width - cw)
    y0 = min(max(y0, 0.0), height - ch)
    return (x0, y0, x0 + cw, y0 + ch)


def subject_cut(window: tuple, subject, width: int, height: int) -> float:
    """Qué fracción del sujeto quedó afuera del recorte. 0 = entero adentro."""
    if not subject:
        return 0.0
    sx0, sy0, sx1, sy1 = (subject[0] * width, subject[1] * height,
                          subject[2] * width, subject[3] * height)
    area = max((sx1 - sx0) * (sy1 - sy0), 1.0)
    ix = max(0.0, min(sx1, window[2]) - max(sx0, window[0]))
    iy = max(0.0, min(sy1, window[3]) - max(sy0, window[1]))
    return round(1.0 - (ix * iy) / area, 3)


def fit(photo, path: Path, size: tuple[int, int]) -> tuple[Image.Image, float]:
    """La foto recortada al tamaño de la celda. Devuelve (imagen, fracción de sujeto cortada)."""
    im = open_original(path, max(size))
    metrics = photo.metrics
    window = crop_window(im.width, im.height, size[0] / size[1],
                         metrics.get("subject_box"), metrics.get("focus"))
    cut = subject_cut(window, metrics.get("subject_box"), im.width, im.height)
    box = tuple(round(v) for v in window)
    return im.crop(box).resize(size, Image.LANCZOS), cut


# --- asignar fotos a celdas ---------------------------------------------------------------

def _aspect(photo) -> float:
    return photo.width / photo.height if photo.height else 1.0


ADAPT_SHARE = (0.40, 0.60)      # en el apilado adaptativo, ninguna se queda con menos del 40 %
                                # del alto; en los suyos va de 46 a 54 %


def cells_for(template: dict, photos: list) -> list[tuple[int, int, int, int]]:
    """Las celdas de la plantilla para estas fotos, en este orden.

    Las plantillas fijas devuelven siempre las mismas. Las adaptativas (las que tienen "caja")
    reparten el alto disponible según la proporción de cada foto, como hace él en el apilado
    blanco: a igual ancho, a cada una le toca el alto que la deja casi sin recortar.
    """
    if "caja" not in template:
        return template["celdas"]
    x, y, w, h = template["caja"]
    sep = template["separacion"]
    disponible = h - sep * (len(photos) - 1)
    naturales = [w / _aspect(p) for p in photos]
    shares = [n / sum(naturales) for n in naturales]
    shares = [min(max(s, ADAPT_SHARE[0]), ADAPT_SHARE[1]) for s in shares]
    shares = [s / sum(shares) for s in shares]
    alturas = [round(disponible * s) for s in shares]
    alturas[-1] = disponible - sum(alturas[:-1])      # que cierre justo, sin píxel de más
    cells, cy = [], y
    for alto in alturas:
        cells.append((x, cy, w, alto))
        cy += alto + sep
    return cells


def assign(template: dict, photos: list, hero=None) -> tuple[list, float]:
    """Qué foto va en qué celda, minimizando cuánto hay que recortar a cada una.

    Con cinco celdas como mucho, probar todas las permutaciones son 120 casos: no hace falta nada
    más inteligente. La foto principal va a la celda más grande.
    """
    if len(photos) != len(template["celdas"]):
        raise ValueError(f"la plantilla tiene {len(template['celdas'])} celdas y llegaron "
                         f"{len(photos)} fotos")
    best, best_cost = None, math.inf
    for order in itertools.permutations(range(len(photos))):
        cells = cells_for(template, [photos[i] for i in order])
        biggest = max(range(len(cells)), key=lambda i: cells[i][2] * cells[i][3])
        cost = 0.0
        for cell_index, photo_index in enumerate(order):
            cw, ch = cells[cell_index][2], cells[cell_index][3]
            cost += abs(math.log(_aspect(photos[photo_index]) / (cw / ch)))
        if hero is not None and photos[order[biggest]] is not hero:
            cost += 0.35                 # la principal pierde la celda grande: se puede, pero cuesta
        if cost < best_cost:
            best, best_cost = order, cost
    return [photos[i] for i in best], best_cost / len(cells)


# --- dibujar -------------------------------------------------------------------------------

PAPER = 247                     # gris del papel de la polaroid, medido sobre la suya
PAPER_GRAIN = 5.0               # desvío del grano del papel, en niveles de gris
EDGE_DARK = 172                 # la línea fina del borde inferior, medida sobre la suya


def _paper(w: int, h: int, rng: random.Random) -> Image.Image:
    """Papel de polaroid: base 247 con grano y alguna mota, como el de las suyas."""
    import numpy as np
    base = np.full((h, w), float(PAPER))
    gen = np.random.default_rng(rng.randrange(1 << 30))
    base += gen.normal(0, PAPER_GRAIN, (h, w))
    # Motas y fibras sueltas: son las que hacen que se lea como papel y no como un rectángulo
    for _ in range(max(6, (w * h) // 9000)):
        x, y = gen.integers(0, w), gen.integers(0, h)
        r = gen.integers(1, 3)
        base[max(0, y - r):y + r, max(0, x - r):x + r] -= gen.uniform(8, 28)
    gray = Image.fromarray(np.clip(base, 0, 255).astype("uint8"), "L")
    return Image.merge("RGB", (gray, gray, gray))


def _polaroid(photo_img: Image.Image, frame: tuple, angle: float, seed: int) -> Image.Image:
    """Una polaroid: papel texturado, línea fina oscura abajo, apenas girada."""
    side, top, bottom = frame
    w, h = photo_img.width + 2 * side, photo_img.height + top + bottom
    rng = random.Random(seed)
    paper = _paper(w, h, rng)
    paper.paste(photo_img, (side, top))
    rgba = paper.convert("RGBA")

    # Lienzo con aire para la sombra: una línea nítida y oscura pegada al borde inferior y al
    # derecho, y un velo muy leve alrededor. Así es la suya: no una sombra difusa grande.
    pad = 8
    pieza = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    velo = Image.new("RGBA", pieza.size, (0, 0, 0, 0))
    velo.paste((0, 0, 0, 30), (pad + 1, pad + 2, pad + w + 1, pad + h + 2))
    velo = velo.filter(ImageFilter.GaussianBlur(3))
    pieza.alpha_composite(velo)
    borde = Image.new("RGBA", pieza.size, (0, 0, 0, 0))
    oscuro = (EDGE_DARK, EDGE_DARK, EDGE_DARK, 255)
    borde.paste(oscuro, (pad + 1, pad + h, pad + w + 1, pad + h + 2))        # abajo
    borde.paste((205, 205, 205, 255), (pad + w, pad + 1, pad + w + 1, pad + h + 1))   # derecha
    pieza.alpha_composite(borde)
    pieza.alpha_composite(rgba, (pad, pad))
    return pieza.rotate(angle, resample=Image.BICUBIC, expand=True)


def _background(template: dict) -> Image.Image:
    """Fondo liso, o degradé vertical si la plantilla lo pide (la grilla de fiesta de MJ)."""
    if "degrade" not in template:
        return Image.new("RGB", CANVAS, template["fondo"])
    arriba, abajo = template["degrade"]
    columna = Image.linear_gradient("L").resize((1, CANVAS[1]))
    columna = columna.point(lambda v: round(arriba + (abajo - arriba) * v / 255))
    return Image.merge("RGB", [columna.resize(CANVAS)] * 3)


def render(template_name: str, photos: list, paths: list[Path], seed: int = 0) -> tuple[Image.Image, list]:
    """Arma una slide. Devuelve (imagen 1080x1350, qué fracción de sujeto se cortó en cada foto)."""
    template = TEMPLATES[template_name]
    canvas = _background(template)
    cuts = []
    rng = random.Random(seed)
    for (x, y, w, h), photo, path in zip(cells_for(template, photos), photos, paths):
        img, cut = fit(photo, path, (w, h))
        cuts.append(cut)
        if template_name == "polaroid":
            giro = template["giro"]
            angle = rng.uniform(-giro, giro)
            pieza = _polaroid(img, template["marco"], angle, seed * 7 + len(cuts))
            side, top, _ = template["marco"]
            # Centrar la polaroid girada sobre donde iría sin girar
            cx = x - side + (w + 2 * side) / 2
            cy = y - top + (h + top + template["marco"][2]) / 2
            base = canvas.convert("RGBA")
            base.alpha_composite(pieza, (round(cx - pieza.width / 2), round(cy - pieza.height / 2)))
            canvas = base.convert("RGB")
        else:
            canvas.paste(img, (x, y))
    return canvas, cuts


def render_entera(path: Path) -> Image.Image:
    """La foto completa, sin recortar, centrada sobre el gris."""
    x, y, w, h = ENTERA_CAJA
    im = open_original(path, max(w, h))
    scale = min(w / im.width, h / im.height)
    size = (round(im.width * scale), round(im.height * scale))
    canvas = Image.new("RGB", CANVAS, ENTERA_FONDO)
    canvas.paste(im.resize(size, Image.LANCZOS),
                 (x + (w - size[0]) // 2, y + (h - size[1]) // 2))
    return canvas


def render_single(photo, path: Path) -> tuple[Image.Image, str, float]:
    """Slide de una sola foto: a sangre en 4:5 si se puede sin cortar a nadie; si no, entera.

    La decisión se toma antes de abrir el original: el recorte se calcula con el tamaño que
    ya está en el índice y la caja de caras, que están en coordenadas 0–1.
    """
    metrics = photo.metrics
    subject = metrics.get("subject_box")
    window = crop_window(photo.width, photo.height, CANVAS[0] / CANVAS[1],
                         subject, metrics.get("focus"))
    corte = subject_cut(window, subject, photo.width, photo.height)
    compacto = subject and (subject[2] - subject[0]) < 0.5
    muy_ancha = _aspect(photo) > LANDSCAPE_LETTERBOX and not compacto
    if corte > MAX_SUBJECT_CUT or muy_ancha:
        return render_entera(path), "entera", 0.0
    img, cut = fit(photo, path, CANVAS)
    return img, "sola", cut


# --- qué slides son collage, y con qué -------------------------------------------------------

# Qué tipo de toma le queda bien a cada plantilla, sacado de lo que él pone en cada una
PREFIERE = {
    "detalles": {"detalle", "retrato"},
    "polaroid": {"retrato", "pareja", "detalle"},
    "grilla": {"retrato", "pareja"},
    "mosaico": set(),
    "apilado": set(),
    "apilado_blanco": set(),
    "grilla_6": set(),
}
MIN_COMPANION_SCORE = 0.5
MIN_COMPANION_HASH = 12
# Medido sobre sus collages de MJ (17 slides con más de una foto): cada collage abarca un tramo
# del día —mediana 28 minutos—, no un instante, y las fotos que junta se parecen poco entre sí
# (parecido CLIP mediano 0.69, nunca más de 0.87). La primera versión elegía la toma siguiente
# y armaba collages de dos fotos casi iguales.
COMPANION_WINDOW = 45 * 60      # segundos alrededor de la principal
COMPANION_MAX_SIM = 0.85        # parecido CLIP máximo entre dos fotos del mismo collage
# Sin estos dos, gana siempre la grilla: sus cuatro celdas 4:5 casi no obligan a recortar. Pero
# él mezcla plantillas, y en preparativos usa detalles y polaroid, no grilla.
# Cambiar esto invalida los planes guardados de corridas anteriores: si cambió cómo se arma, no
# tiene sentido "no mover lo que él no tocó" sobre un plan hecho con otras reglas
PLAN_VERSION = 2
# En MJ, las 3 fotos que publicó solas son verticales y las apaisadas (51 de 65) van todas en
# collage. Explica también por qué su proporción de collages cambia tanto entre casamientos (de
# 18 a 80 %): depende de cuántas apaisadas tiene el álbum.
LANDSCAPE_COLLAGE = 1.2
PREFERENCE_STEP = 0.08      # cuánto cuesta cada lugar que se baja en la lista de la config
# Leve a propósito: en sus posts la plantilla principal se repite mucho (el apilado blanco va 14
# veces en JJ). El castigo sólo desempata a favor de variar cuando dos plantillas cuestan parecido.
REPEAT_PENALTY = 0.04


def _fuerza(photo) -> float:
    """Qué tanto merece una foto ir sola. Sus retratos fuertes van solos; lo demás se agrupa."""
    m = photo.metrics
    return (m.get("score", 0)
            + 0.30 * ((m.get("novios") or 0) >= 2)
            + 0.15 * (m.get("kind") in ("retrato", "pareja")))


def _minutes(a, b) -> float:
    da, db = a.taken_dt(), b.taken_dt()
    return abs((da - db).total_seconds()) / 60 if da and db else 999.0


def _companions(hero, pool: list, template_name: str, need: int,
                embeddings: dict | None = None) -> list | None:
    """Fotos para acompañar a la principal: del mismo tramo, buenas, y distintas entre sí.

    Del mismo tramo del día (COMPANION_WINDOW) porque así son sus collages: cuentan una parte
    —los preparativos, la fiesta—, no una mezcla del día entero. Dentro de eso, las mejores por
    puntaje, y ninguna demasiado parecida a otra ya elegida.
    """
    prefiere = PREFIERE.get(template_name, set())
    apilado = template_name in ("apilado", "apilado_blanco", "grilla_6")

    def key(photo):
        castigo = 0.0 if not prefiere or photo.metrics.get("kind") in prefiere else 0.15
        return -(photo.metrics.get("score", 0) - castigo)

    candidatas = [p for p in pool if _minutes(p, hero) * 60 <= COMPANION_WINDOW]
    elegidas = [hero]
    for photo in sorted(candidatas, key=key):
        if len(elegidas) - 1 >= need:
            break
        if photo.metrics.get("score", 0) < MIN_COMPANION_SCORE:
            continue
        if apilado and _aspect(photo) < 1.2:
            continue                     # los apilados sólo funcionan con apaisadas
        if any(bin(photo.metrics["hash"] ^ e.metrics["hash"]).count("1") < MIN_COMPANION_HASH
               for e in elegidas):
            continue
        if embeddings and photo.key in embeddings and any(
                e.key in embeddings
                and float(embeddings[photo.key] @ embeddings[e.key]) > COMPANION_MAX_SIM
                for e in elegidas):
            continue                     # casi la misma foto que una que ya está
        elegidas.append(photo)
    return elegidas[1:] if len(elegidas) - 1 == need else None


def plan(slides: list[dict], pool_by_chapter: dict[str, list], config: dict,
         previous: dict[str, dict] | None = None, photos_by_rel: dict | None = None,
         embeddings: dict | None = None) -> list[dict]:
    """Decide, slide por slide, si va sola o en collage, y con qué plantilla y fotos.

    En cada capítulo se vuelven collage las slides más flojas —las más fuertes quedan solas— y
    nunca la de apertura. Para cada una se prueban las plantillas permitidas y se queda la de
    menor costo, sumando tres cosas: cuánto recorte obliga, qué tan abajo está en la lista de
    preferencias del capítulo, y si ya se usó antes en el post.

    **Lo que él no tocó no se mueve.** `previous` es el plan de la corrida anterior, por foto
    principal. Un collage de una slide intacta se reusa tal cual; uno que él deshizo —pidiendo que
    vaya sola— no reaparece en otra slide. Sin esto, pedir "la 5 sola" terminaba en un collage
    nuevo en la 6, que es lo contrario de lo que pidió.

    Volver a armarlo sin tocar nada tiene que dar el mismo post: el cupo del capítulo se gasta con
    las mismas slides en la primera corrida y en la décima.
    """
    montaje = config.get("montaje", {})
    cuantos = montaje.get("collages", {})
    permitidas = montaje.get("plantillas", {})
    # Cuántas veces puede aparecer cada plantilla en un post. Sin tope, la grilla de 6 se comía la
    # fiesta: 8 slides de 6 fotos, y la fiesta pasaba a ser el 65 % del post contra su 43 %
    maximos = montaje.get("maximo", {})
    previous = previous or {}
    photos_by_rel = photos_by_rel or {}
    heroes = {id(s["photo"]) for s in slides}
    usadas: set[int] = set(heroes)
    ya_usadas: dict[str, int] = {}
    heroes_ahora = {s["photo"].rel: s for s in slides}

    por_capitulo: dict[str, list[dict]] = {}
    for s in slides:
        por_capitulo.setdefault(s["capitulo"], []).append(s)

    for capitulo, del_capitulo in por_capitulo.items():
        cupo = cuantos.get(capitulo, 0)

        # Primero, lo que ya estaba armado y él no tocó. El cupo del capítulo cuenta sólo las
        # verticales: las apaisadas van en collage siempre, así que no gastan cupo ni acá ni
        # abajo. Contarlas hacía que la segunda corrida perdiera collages sin que él tocara nada.
        reusados = 0
        deshechos = 0
        for rel, antes in previous.items():
            if antes.get("capitulo") != capitulo or antes.get("plantilla") not in TEMPLATES:
                continue
            s = heroes_ahora.get(rel)
            if s is None:
                continue                 # esa foto ya no está en el post: no es algo que él deshizo
            vertical = _aspect(s["photo"]) <= LANDSCAPE_COLLAGE
            if s.get("forzar_sola"):
                deshechos += 1           # lo deshizo él: no vuelve a aparecer en otro lado
                continue
            fotos = [photos_by_rel.get(r) for r in antes.get("fotos", [])]
            libres = all(f is not None and (f is s["photo"] or id(f) not in usadas) for f in fotos)
            if libres and len(fotos) == len(TEMPLATES[antes["plantilla"]]["celdas"]):
                s["plantilla"], s["fotos"] = antes["plantilla"], fotos
                s["motivo"] += f" · collage {antes['plantilla']}, igual que antes"
                usadas.update(id(f) for f in fotos)
                ya_usadas[antes["plantilla"]] = ya_usadas.get(antes["plantilla"], 0) + 1
                reusados += vertical

        # Después, las que todavía no tienen plan. Las apaisadas van en collage siempre (así lo
        # hace él); de las verticales, sólo las más flojas hasta llenar el cupo del capítulo, y las
        # fuertes quedan solas. Las que él pidió que vayan solas no se tocan. La de apertura sí
        # puede ser collage: en 5 de sus 6 posts lo es (config: montaje.apertura_collage).
        apertura_ok = montaje.get("apertura_collage", True)
        libres = [s for s in del_capitulo
                  if (apertura_ok or s["slide"] != 1)
                  and not s.get("forzar_sola") and not s.get("plantilla")]
        apaisadas = [s for s in libres if _aspect(s["photo"]) > LANDSCAPE_COLLAGE]
        verticales = sorted((s for s in libres if _aspect(s["photo"]) <= LANDSCAPE_COLLAGE),
                            key=lambda s: _fuerza(s["photo"]))
        for s in apaisadas + verticales[:max(0, cupo - reusados - deshechos)]:
            pool = [p for p in pool_by_chapter.get(capitulo, []) if id(p) not in usadas]
            mejor = None
            for lugar, nombre in enumerate(permitidas.get(capitulo, ["grilla"])):
                if nombre in maximos and ya_usadas.get(nombre, 0) >= maximos[nombre]:
                    continue
                need = len(TEMPLATES[nombre]["celdas"]) - 1
                companeras = _companions(s["photo"], pool, nombre, need, embeddings)
                if not companeras:
                    continue
                fotos, recorte = assign(TEMPLATES[nombre], [s["photo"]] + companeras, s["photo"])
                costo = (recorte + PREFERENCE_STEP * lugar
                         + REPEAT_PENALTY * ya_usadas.get(nombre, 0))
                if mejor is None or costo < mejor[2]:
                    mejor = (nombre, fotos, costo, companeras)
            if mejor:
                nombre, fotos, costo, companeras = mejor
                s["plantilla"], s["fotos"] = nombre, fotos
                s["motivo"] += f" · collage {nombre} con {len(companeras)} más"
                usadas.update(id(p) for p in companeras)
                ya_usadas[nombre] = ya_usadas.get(nombre, 0) + 1

    for s in slides:
        s.setdefault("plantilla", None)
        s.setdefault("fotos", [s["photo"]])
    return slides


def save(img: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # 4:4:4 y calidad 95: Instagram recomprime igual, pero partir de algo limpio se nota
    img.save(dest, "JPEG", quality=JPEG_QUALITY, subsampling=0, icc_profile=SRGB_BYTES,
             optimize=True)
