"""Modo "con mis elegidas": Diego ya eligió las fotos, la herramienta arma el post con todas.

El problema cambia de naturaleza. En el modo normal hay miles de fotos y hay que elegir veinte
momentos; acá la elección ya está hecha y lo único que falta es **empaquetarlas**: que entren
todas en veinte slides como mucho, con collages que sigan su lenguaje.

Se resuelve como una partición de la secuencia del día en tramos contiguos, por programación
dinámica. Cada tramo es una slide: una foto sola, o un collage con una de sus plantillas (2, 4, 5
o 6 fotos: no hay plantilla de 3). El costo de cada tramo junta lo que ya se sabía de sus posts:

- una apaisada sola cuesta (él las pone en collage: en MJ, 51 de 51);
- un collage cuesta lo que obliga a recortar, más qué tan abajo está la plantilla en la lista
  del capítulo (config.json), más si junta fotos muy separadas en el día o de dos capítulos;
- una vertical fuerte en un collage cuesta un poco: sus retratos fuertes van solos.

Con el tope de slides como restricción dura, la programación dinámica da el reparto de menor costo.
Si sobran lugares, las verticales quedan solas; si faltan, se agrupan las que menos pierden.

Los cambios a mano, en este modo, se guardan en la lista de elegidas y no en el post: "sacar la
slide 7" saca sus fotos de la lista, "la 3 sola" marca sus fotos para que vayan solas. Así volver a
armar nunca depende de números de slide viejos.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import montage

ARCHIVO = "elegidas.txt"
LANDSCAPE = 1.2                 # como montage.LANDSCAPE_COLLAGE
LANDSCAPE_SOLO = 0.35           # costo de dejar una apaisada sola
VERTICAL_IN_COLLAGE = 0.06      # costo por vertical metida en un collage
STRONG_IN_COLLAGE = 0.25        # extra si esa vertical es de las fuertes (novios, retrato)
SPAN_FREE = 45 * 60             # hasta acá, un collage no paga por abarcar tiempo
SPAN_COST = 0.30                # por cada tramo de 45 minutos de más
CROSS_CHAPTER = 0.8             # juntar dos capítulos en un collage
PREFERENCE_STEP = 0.08          # como montage.PREFERENCE_STEP
OUTSIDE_LIST = 0.30             # plantilla que la config no pone para ese capítulo
TEMPLATE_EXTRA = {"grilla_6": 0.10, "apilado": 0.12}   # las que él usa menos
ONLY_LANDSCAPE = {"apilado", "apilado_blanco", "grilla_6"}
PREFIJO_APLICADO = "# aplicado: "

ENCABEZADO = """\
# Las fotos que eligió Diego, una por línea (el nombre, sin .jpg).
# Agregar " sola" al final para que esa foto vaya sola, sin collage.
# Esta lista la arma la interfaz; también se puede editar a mano.
"""


# --- la lista ---------------------------------------------------------------------------------

def leer(path: Path) -> list[tuple[str, bool]]:
    """[(nombre, sola)] en el orden del archivo, sin repetidos."""
    if not path.is_file():
        return []
    vistos, out = set(), []
    for linea in path.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        partes = linea.split()
        nombre = _normalizar(partes[0])
        sola = len(partes) > 1 and partes[1].lower() == "sola"
        if nombre.lower() in vistos:
            continue
        vistos.add(nombre.lower())
        out.append((nombre, sola))
    return out


def guardar(path: Path, items: list[tuple[str, bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = "\n".join(f"{n} sola" if s else n for n, s in items)
    path.write_text(ENCABEZADO + cuerpo + "\n", encoding="utf-8")


def _normalizar(nombre: str) -> str:
    """El nombre de la foto sin carpeta ni extensión, que es como lo muestran las hojas."""
    nombre = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    base, punto, ext = nombre.rpartition(".")
    return base if punto and ext.lower() in {"jpg", "jpeg", "png", "webp", "tif", "tiff"} else nombre


def desde_nombres(nombres: list[str]) -> list[tuple[str, bool]]:
    vistos, out = set(), []
    for n in nombres:
        n = _normalizar(str(n).strip())
        if n and n.lower() not in vistos:
            vistos.add(n.lower())
            out.append((n, False))
    return out


def desde_carpeta(carpeta: Path) -> list[tuple[str, bool]]:
    """Las fotos de una carpeta (las que Diego copió aparte), por nombre."""
    from .album import EXTENSIONS
    return desde_nombres(sorted(p.name for p in carpeta.iterdir()
                                if p.is_file() and p.suffix.lower() in EXTENSIONS))


# --- cambios a mano, traducidos a la lista ----------------------------------------------------

def aplicar_cambios(archivo_cambios: Path, anterior: Path, items: list[tuple[str, bool]],
                    photos_por_nombre: dict) -> tuple[list[tuple[str, bool]], list[str]]:
    """Pasa lo pedido en cambios.txt a la lista de elegidas, y lo marca como aplicado.

    Entiende las mismas órdenes que el modo normal ("7 fuera", "3 sola", "7 DSC_0123") y dos
    más, por foto: "- DSC_0123" la saca del post y "+ DSC_0123" la suma.
    """
    if not archivo_cambios.is_file():
        return items, []
    slides = {}
    if anterior.is_file():
        try:
            datos = json.loads(anterior.read_text(encoding="utf-8-sig"))
            slides = {s["slide"]: [d["name"] for d in s.get("detalle", [])]
                      for s in datos.get("slides", [])}
        except (json.JSONDecodeError, KeyError):
            slides = {}

    lista = [list(i) for i in items]
    indice = lambda n: next((i for i, (m, _) in enumerate(lista) if m.lower() == n.lower()), None)  # noqa: E731
    hecho, lineas_out, tocado = [], [], False
    for linea in archivo_cambios.read_text(encoding="utf-8-sig").splitlines():
        limpia = linea.split("#", 1)[0].strip()
        if not limpia:
            lineas_out.append(linea)
            continue
        partes = limpia.split()
        tocado = True
        lineas_out.append(PREFIJO_APLICADO + limpia)
        if len(partes) == 2 and partes[0] in ("+", "-"):
            nombre = _normalizar(partes[1])
            if nombre.lower() not in photos_por_nombre:
                hecho.append(f"no hay ninguna foto que se llame «{nombre}»")
                continue
            i = indice(nombre)
            if partes[0] == "-" and i is not None:
                lista.pop(i)
                hecho.append(f"{nombre}: fuera del post")
            elif partes[0] == "+" and i is None:
                lista.append([photos_por_nombre[nombre.lower()].name, False])
                hecho.append(f"{nombre}: entra al post")
            continue
        if len(partes) != 2 or not partes[0].isdigit():
            hecho.append(f"«{limpia}» no se entiende")
            continue
        numero, accion = int(partes[0]), partes[1]
        fotos = slides.get(numero)
        if fotos is None:
            hecho.append(f"slide {numero}: no existe")
            continue
        clave = accion.lower()
        if clave == "fuera":
            lista = [x for x in lista if x[0].lower() not in {f.lower() for f in fotos}]
            hecho.append(f"slide {numero}: fuera ({len(fotos)} foto{'s' if len(fotos) > 1 else ''})")
        elif clave == "sola":
            for x in lista:
                if x[0].lower() in {f.lower() for f in fotos}:
                    x[1] = True
            hecho.append(f"slide {numero}: sus fotos van solas")
        else:
            nombre = _normalizar(accion)
            if nombre.lower() not in photos_por_nombre:
                hecho.append(f"slide {numero}: no hay ninguna foto que se llame «{nombre}»")
                continue
            vieja = fotos[0]
            i = indice(vieja)
            nueva = [photos_por_nombre[nombre.lower()].name, False]
            if indice(nombre) is not None:
                hecho.append(f"slide {numero}: {nombre} ya estaba en el post")
            elif i is None:
                lista.append(nueva)
                hecho.append(f"slide {numero}: entra {nombre}")
            else:
                lista[i] = nueva
                hecho.append(f"slide {numero}: {vieja} → {nombre}")
    if tocado:
        archivo_cambios.write_text("\n".join(lineas_out) + "\n", encoding="utf-8")
    return [(n, s) for n, s in lista], hecho


# --- el reparto en slides ---------------------------------------------------------------------

def _aspect(photo) -> float:
    return photo.width / photo.height if photo.height else 1.0


def _fuerte(photo) -> bool:
    m = photo.metrics
    return (m.get("novios") or 0) >= 2 or m.get("kind") in ("retrato", "pareja")


def _segundos(a, b) -> float:
    da, db = a.taken_dt(), b.taken_dt()
    return abs((db - da).total_seconds()) if da and db else 0.0


def _por_tamano() -> dict[int, list[str]]:
    tam: dict[int, list[str]] = {}
    for nombre, t in montage.TEMPLATES.items():
        tam.setdefault(len(t["celdas"]), []).append(nombre)
    return tam


def _costo_collage(fotos: list, permitidas: list[str], nombres: list[str]):
    """(costo, plantilla, fotos en orden de celda) del mejor collage para estas fotos."""
    mejor = None
    apaisadas = all(_aspect(p) > LANDSCAPE for p in fotos)
    hero = max(fotos, key=lambda p: p.metrics.get("score", 0))
    for nombre in nombres:
        if nombre in ONLY_LANDSCAPE and not apaisadas:
            continue
        lugar = permitidas.index(nombre) * PREFERENCE_STEP if nombre in permitidas else OUTSIDE_LIST
        orden, recorte = montage.assign(montage.TEMPLATES[nombre], fotos, hero)
        costo = recorte + lugar + TEMPLATE_EXTRA.get(nombre, 0.0)
        if mejor is None or costo < mejor[0]:
            mejor = (costo, nombre, orden)
    return mejor


def secuencia(photos: list) -> list:
    """El orden en que se parte: por tramo del día, y dentro del tramo las apaisadas juntas.

    Juntar las apaisadas de un mismo bloque deja armar apilados que en el orden estricto por hora
    quedarían separados por una vertical en el medio. El bloque sigue mandando: nunca se mezcla
    la ceremonia con la fiesta para ganar un collage.
    """
    def clave(p):
        return (p.metrics.get("bloque", 0), _aspect(p) > LANDSCAPE, p.taken or "", p.rel)
    return sorted(photos, key=clave)


def pack(photos: list, solas: set, n_slides: int, config: dict) -> tuple[list[dict], list, str]:
    """Reparte todas las elegidas en n_slides como mucho. Devuelve (slides, las que no entraron, aviso)."""
    montaje = config.get("montaje", {})
    permitidas_cfg = montaje.get("plantillas", {})
    por_tamano = _por_tamano()
    tamanos = sorted([1] + list(por_tamano))
    fotos = secuencia(photos)
    afuera: list = []
    aviso = ""

    # Si no entran ni con los collages más grandes, afuera las de menor puntaje (y se avisa)
    capacidad = n_slides * max(tamanos)
    if len(fotos) > capacidad:
        sobran = sorted(fotos, key=lambda p: p.metrics.get("score", 0))[:len(fotos) - capacidad]
        afuera = sobran
        fotos = [p for p in fotos if p not in sobran]

    while True:
        plan = _particion(fotos, solas, n_slides, tamanos, por_tamano, permitidas_cfg)
        if plan is not None or not fotos:
            break
        # No hay partición posible (por ejemplo, demasiadas marcadas "sola"): se suelta la
        # marca de la más floja, y si no queda ninguna, sale la foto más floja
        marcadas = [p for p in fotos if p.name in solas]
        if marcadas:
            solas = solas - {min(marcadas, key=lambda p: p.metrics.get("score", 0)).name}
        else:
            peor = min(fotos, key=lambda p: p.metrics.get("score", 0))
            afuera.append(peor)
            fotos.remove(peor)
    if afuera:
        aviso = (f"{len(afuera)} de las elegidas no entraron en {n_slides} slides: "
                 + ", ".join(p.name for p in afuera[:12]) + ("…" if len(afuera) > 12 else ""))

    slides = []
    for tramo, plantilla, orden in plan or []:
        hero = max(tramo, key=lambda p: p.metrics.get("score", 0))
        motivo = "la eligió él"
        entry = {"photo": hero, "capitulo": hero.metrics.get("capitulo", "?"),
                 "unidad": hero.metrics.get("bloque"), "motivo": motivo}
        if plantilla:
            entry["plantilla"] = plantilla
            entry["fotos"] = orden
            entry["motivo"] += f" · collage {plantilla} con {len(tramo) - 1} más"
        else:
            entry["plantilla"] = None
            entry["fotos"] = [hero]
            if hero.name in solas:
                entry["forzar_sola"] = True
        slides.append(entry)
    slides.sort(key=lambda e: min((p.taken or "") for p in e["fotos"]))
    for numero, e in enumerate(slides, start=1):
        e["slide"] = numero
    return slides, afuera, aviso


def _particion(fotos: list, solas: set, n_slides: int, tamanos: list[int],
               por_tamano: dict, permitidas_cfg: dict):
    """Programación dinámica: costo[i][s] = mejor forma de repartir las i primeras en s slides."""
    n = len(fotos)
    if n == 0:
        return []
    inf = math.inf
    costo = [[inf] * (n_slides + 1) for _ in range(n + 1)]
    desde: list[list] = [[None] * (n_slides + 1) for _ in range(n + 1)]
    costo[0][0] = 0.0
    cache: dict[tuple[int, int], tuple] = {}

    def tramo(i: int, k: int):
        """Costo y armado de la slide con las fotos i..i+k-1."""
        if (i, k) in cache:
            return cache[(i, k)]
        grupo = fotos[i:i + k]
        if k == 1:
            p = grupo[0]
            valor = (0.0 if p.name in solas or _aspect(p) <= LANDSCAPE else LANDSCAPE_SOLO, None, grupo)
        elif any(p.name in solas for p in grupo):
            valor = (inf, None, grupo)
        else:
            capitulos = {p.metrics.get("capitulo") for p in grupo}
            capitulo = grupo[0].metrics.get("capitulo")
            permitidas = permitidas_cfg.get(capitulo, [])
            mejor = _costo_collage(grupo, permitidas, por_tamano.get(k, []))
            if mejor is None:
                valor = (inf, None, grupo)
            else:
                extra = 0.0
                span = max(_segundos(a, b) for a in grupo for b in grupo)
                if span > SPAN_FREE:
                    extra += SPAN_COST * (span - SPAN_FREE) / SPAN_FREE
                if len(capitulos) > 1:
                    extra += CROSS_CHAPTER
                for p in grupo:
                    if _aspect(p) <= LANDSCAPE:
                        extra += VERTICAL_IN_COLLAGE + (STRONG_IN_COLLAGE if _fuerte(p) else 0.0)
                # El costo de recorte de assign() es un promedio por celda: se multiplica por
                # la cantidad, para que un collage de seis no salga más barato que tres pares
                valor = (mejor[0] * k + extra, mejor[1], mejor[2])
        cache[(i, k)] = valor
        return valor

    for i in range(n):
        for s in range(n_slides):
            if costo[i][s] == inf:
                continue
            for k in tamanos:
                if i + k > n:
                    break
                c, _, _ = tramo(i, k)
                if c == inf:
                    continue
                total = costo[i][s] + c
                if total < costo[i + k][s + 1]:
                    costo[i + k][s + 1] = total
                    desde[i + k][s + 1] = (i, k)

    mejor_s = min(range(n_slides + 1), key=lambda s: costo[n][s])
    if costo[n][mejor_s] == inf:
        return None
    plan, i, s = [], n, mejor_s
    while i > 0:
        j, k = desde[i][s]
        _, plantilla, orden = tramo(j, k)
        plan.append((fotos[j:j + k], plantilla, orden))
        i, s = j, s - 1
    plan.reverse()
    return plan
