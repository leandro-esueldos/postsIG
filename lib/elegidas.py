"""Modo "con mis elegidas": Diego ya eligió las fotos, la herramienta arma el post con todas.

El problema cambia de naturaleza. En el modo normal hay miles de fotos y hay que elegir veinte
momentos; acá la elección ya está hecha y lo único que falta es **empaquetarlas**: que entren
todas, con collages que sigan su lenguaje.

**Cuántas slides.** Si él no lo dice, se decide por las fotos (`auto_slides`): una vertical vale
algo más de media slide —sus retratos fuertes van solos, el resto se agrupa de a 4 o 5— y una
apaisada vale media, porque él las pone de a dos en el apilado. Así 10 verticales dan 6 slides
(cinco solas y un collage), y 20 fotos mezcladas, unas 11. Siempre se puede pisar a mano.

**Cuáles juntas.** Se parte la secuencia del día en tramos contiguos, por programación dinámica.
Cada tramo es una slide: una foto sola, o un collage con una de sus plantillas. El costo de cada
tramo junta lo que ya se sabía de sus posts:

- una apaisada sola cuesta (él las pone en collage: en MJ, 51 de 51);
- un collage cuesta lo que obliga a recortar, más qué tan abajo está la plantilla en la lista
  del capítulo (config.json), más si junta fotos muy separadas en el día o de dos capítulos;
- una vertical fuerte en un collage cuesta un poco: sus retratos fuertes van solos.

Con el tope de slides como restricción dura, la programación dinámica da el reparto de menor costo.

**Lo que él decide manda.** Cada foto de la lista puede llevar marcas: `sola` (va sola), `grupo=`
(las de un mismo grupo van juntas en un collage, y con nada más) y `plantilla=` (con qué plantilla
se arma ese grupo). Los cambios que pide sobre el post —"la 3 sola", "juntar la 4 con la 5",
"la 7 con la grilla"— se traducen a esas marcas y se guardan en la lista, no en el post: así volver
a armar nunca depende de números de slide viejos.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import montage

ARCHIVO = "elegidas.txt"
MAX_SLIDES = 20                 # el tope de Instagram para un carrusel subido a mano
LANDSCAPE = 1.2                 # como montage.LANDSCAPE_COLLAGE
LANDSCAPE_SOLO = 0.35           # costo de dejar una apaisada sola
VERTICAL_IN_COLLAGE = 0.06      # costo por vertical metida en un collage
STRONG_IN_COLLAGE = 0.25        # extra si esa vertical es de las fuertes (novios, retrato)
SPAN_FREE = 45 * 60             # hasta acá, un collage no paga por abarcar tiempo
SPAN_COST = 0.30                # por cada tramo de 45 minutos de más
CROSS_CHAPTER = 0.8             # juntar dos capítulos en un collage
PREFERENCE_STEP = 0.08          # como montage.PREFERENCE_STEP
OUTSIDE_LIST = 0.30             # plantilla que la config no pone para ese capítulo
# Las que él usa menos, y las dos que no salen de sus posts (par y trío): entran cuando hacen
# falta, no por gusto
TEMPLATE_EXTRA = {"grilla_6": 0.10, "apilado": 0.12, "par": 0.15, "trio": 0.15}
ONLY_LANDSCAPE = {"apilado", "apilado_blanco", "grilla_6"}
# Cuánto vale cada foto en slides, para decidir cuántas slides por defecto (ver arriba)
SLIDE_POR_VERTICAL = 0.6
SLIDE_POR_APAISADA = 0.5
PREFIJO_APLICADO = "# aplicado: "

NOMBRES = {
    "apilado_blanco": "dos apaisadas, sobre blanco",
    "apilado": "dos apaisadas, sobre gris",
    "par": "dos verticales",
    "trio": "una arriba y dos abajo",
    "grilla": "grilla de 4",
    "mosaico": "mosaico de 4",
    "polaroid": "polaroids de 4",
    "detalles": "detalles, de 5",
    "grilla_6": "grilla de 6",
}

ENCABEZADO = """\
# Las fotos que eligió Diego, una por línea (el nombre, sin .jpg).
# Marcas opcionales después del nombre:
#   sola              esa foto va sola, sin collage
#   grupo=a           las del mismo grupo van juntas en un collage (de 2 a 6)
#   plantilla=grilla  con qué plantilla se arma su grupo
# "@slides 12" fija cuántas slides; sin esa línea se decide por las fotos.
# Esta lista la arma la interfaz; también se puede editar a mano.
"""


# --- la lista ---------------------------------------------------------------------------------

@dataclass
class Foto:
    name: str
    sola: bool = False
    grupo: str | None = None
    plantilla: str | None = None

    def linea(self) -> str:
        marcas = (["sola"] if self.sola else []) + \
            ([f"grupo={self.grupo}"] if self.grupo else []) + \
            ([f"plantilla={self.plantilla}"] if self.plantilla else [])
        return " ".join([self.name] + marcas)


@dataclass
class Lista:
    fotos: list[Foto] = field(default_factory=list)
    slides: int | None = None            # None: lo decide la herramienta

    def nombres(self) -> list[str]:
        return [f.name for f in self.fotos]

    def buscar(self, nombre: str) -> Foto | None:
        nombre = nombre.lower()
        return next((f for f in self.fotos if f.name.lower() == nombre), None)

    def grupo_nuevo(self) -> str:
        usados = {f.grupo for f in self.fotos if f.grupo}
        n = 1
        while f"g{n}" in usados:
            n += 1
        return f"g{n}"


def leer(path: Path) -> Lista:
    """La lista del archivo, en orden y sin repetidos. Vacía si no existe."""
    lista = Lista()
    if not path.is_file():
        return lista
    vistos = set()
    for linea in path.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        partes = linea.split()
        if partes[0].lower() == "@slides":
            valor = partes[1] if len(partes) > 1 else "auto"
            lista.slides = int(valor) if valor.isdigit() and 1 <= int(valor) <= MAX_SLIDES else None
            continue
        foto = Foto(_normalizar(partes[0]))
        for marca in partes[1:]:
            clave, _, valor = marca.partition("=")
            clave = clave.lower()
            if clave == "sola":
                foto.sola = True
            elif clave == "grupo" and valor:
                foto.grupo = valor
            elif clave == "plantilla" and valor in montage.TEMPLATES:
                foto.plantilla = valor
        if foto.name.lower() in vistos:
            continue
        vistos.add(foto.name.lower())
        lista.fotos.append(foto)
    return lista


def guardar(path: Path, lista: Lista) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cabeza = ENCABEZADO + (f"@slides {lista.slides}\n" if lista.slides else "")
    path.write_text(cabeza + "\n".join(f.linea() for f in lista.fotos) + "\n", encoding="utf-8")


def _normalizar(nombre: str) -> str:
    """El nombre de la foto sin carpeta ni extensión, que es como lo muestran las hojas."""
    nombre = nombre.replace("\\", "/").rsplit("/", 1)[-1]
    base, punto, ext = nombre.rpartition(".")
    return base if punto and ext.lower() in {"jpg", "jpeg", "png", "webp", "tif", "tiff"} else nombre


def desde_nombres(nombres: list[str]) -> list[str]:
    """Nombres normalizados, sin repetidos, en el orden en que llegaron."""
    vistos, out = set(), []
    for n in nombres:
        n = _normalizar(str(n).strip())
        if n and n.lower() not in vistos:
            vistos.add(n.lower())
            out.append(n)
    return out


def desde_carpeta(carpeta: Path) -> list[str]:
    """Las fotos de una carpeta (las que Diego copió aparte), por nombre."""
    from .album import EXTENSIONS
    return desde_nombres(sorted(p.name for p in carpeta.iterdir()
                                if p.is_file() and p.suffix.lower() in EXTENSIONS))


# --- cuántas slides, si él no lo dice -----------------------------------------------------------

def _aspect(photo) -> float:
    return photo.width / photo.height if photo.height else 1.0


def orientaciones(photos: list) -> tuple[int, int]:
    """(verticales, apaisadas). Las cuadradas cuentan como verticales: van solas igual."""
    apaisadas = sum(1 for p in photos if _aspect(p) > LANDSCAPE)
    return len(photos) - apaisadas, apaisadas


def auto_slides(photos: list) -> int:
    """Cuántas slides por defecto, según cuántas fotos son y de qué orientación."""
    if not photos:
        return 0
    verticales, apaisadas = orientaciones(photos)
    deseadas = math.ceil(SLIDE_POR_VERTICAL * verticales + SLIDE_POR_APAISADA * apaisadas)
    # Nunca menos de las que hacen falta para que entren todas (5 por slide con verticales, que
    # es la plantilla más grande que las acepta), ni más de una por foto o del tope de Instagram
    minimo = math.ceil(len(photos) / 5)
    return max(1, min(MAX_SLIDES, len(photos), max(deseadas, minimo)))


# --- cambios a mano, traducidos a la lista ----------------------------------------------------

def aplicar_cambios(archivo_cambios: Path, anterior: Path, lista: Lista,
                    photos_por_nombre: dict) -> tuple[Lista, list[str]]:
    """Pasa lo pedido en cambios.txt a la lista de elegidas, y lo marca como aplicado.

    Órdenes sobre una slide del último post armado (el número es el que se ve):

        7 fuera              saca sus fotos
        3 sola               sus fotos van solas (deshace un collage)
        4 juntar 5           las fotos de las dos slides van en un mismo collage
        6 plantilla grilla   arma esa slide con esa plantilla
        7 DSC_0123           cambia la foto principal de la slide por ésa

    Y sobre el post entero o una foto: "slides 12" / "slides auto", "- DSC_0123", "+ DSC_0123".
    """
    if not archivo_cambios.is_file():
        return lista, []
    slides: dict[int, list[str]] = {}
    if anterior.is_file():
        try:
            datos = json.loads(anterior.read_text(encoding="utf-8-sig"))
            slides = {s["slide"]: [d["name"] for d in s.get("detalle", [])]
                      for s in datos.get("slides", [])}
        except (json.JSONDecodeError, KeyError):
            slides = {}

    def de_la_slide(nombres: list[str]) -> list[Foto]:
        return [f for f in (lista.buscar(n) for n in nombres) if f is not None]

    hecho, lineas_out, tocado = [], [], False
    for linea in archivo_cambios.read_text(encoding="utf-8-sig").splitlines():
        limpia = linea.split("#", 1)[0].strip()
        if not limpia:
            lineas_out.append(linea)
            continue
        partes = limpia.split()
        tocado = True
        lineas_out.append(PREFIJO_APLICADO + limpia)

        if partes[0].lower() == "slides" and len(partes) == 2:
            valor = partes[1].lower()
            if valor == "auto":
                lista.slides = None
                hecho.append("cantidad de slides: la decide la herramienta")
            elif valor.isdigit() and 1 <= int(valor) <= MAX_SLIDES:
                lista.slides = int(valor)
                hecho.append(f"cantidad de slides: {valor}")
            else:
                hecho.append(f"«{limpia}»: las slides van de 1 a {MAX_SLIDES}, o «auto»")
            continue

        if len(partes) == 2 and partes[0] in ("+", "-"):
            nombre = _normalizar(partes[1])
            if nombre.lower() not in photos_por_nombre:
                hecho.append(f"no hay ninguna foto que se llame «{nombre}»")
                continue
            foto = lista.buscar(nombre)
            if partes[0] == "-" and foto is not None:
                lista.fotos.remove(foto)
                hecho.append(f"{nombre}: fuera del post")
            elif partes[0] == "+" and foto is None:
                lista.fotos.append(Foto(photos_por_nombre[nombre.lower()].name))
                hecho.append(f"{nombre}: entra al post")
            continue

        if not partes[0].isdigit() or len(partes) not in (2, 3):
            hecho.append(f"«{limpia}» no se entiende")
            continue
        numero = int(partes[0])
        if numero not in slides:
            hecho.append(f"slide {numero}: no existe")
            continue
        fotos = de_la_slide(slides[numero])
        accion = partes[1].lower()

        if accion == "fuera" and len(partes) == 2:
            for f in fotos:
                lista.fotos.remove(f)
            hecho.append(f"slide {numero}: fuera ({len(fotos)} foto{'s' if len(fotos) != 1 else ''})")
        elif accion in ("sola", "separar") and len(partes) == 2:
            for f in fotos:
                f.sola, f.grupo, f.plantilla = True, None, None
            hecho.append(f"slide {numero}: sus fotos van solas")
        elif accion == "juntar" and len(partes) == 3 and partes[2].isdigit():
            otra = int(partes[2])
            if otra not in slides or otra == numero:
                hecho.append(f"slide {numero}: no hay una slide {otra} para juntar")
                continue
            juntas = fotos + [f for f in de_la_slide(slides[otra]) if f not in fotos]
            if len(juntas) > 6:
                hecho.append(f"slides {numero} y {otra}: son {len(juntas)} fotos, y el collage "
                             f"más grande es de 6")
                continue
            grupo = lista.grupo_nuevo()
            for f in juntas:
                f.sola, f.grupo, f.plantilla = False, grupo, None
            hecho.append(f"slides {numero} y {otra}: juntas en un collage de {len(juntas)}")
        elif accion == "plantilla" and len(partes) == 3:
            nombre = partes[2]
            if nombre not in montage.TEMPLATES:
                hecho.append(f"slide {numero}: no hay una plantilla «{nombre}»")
                continue
            celdas = len(montage.TEMPLATES[nombre]["celdas"])
            if celdas != len(fotos):
                hecho.append(f"slide {numero}: «{nombre}» es para {celdas} fotos y la slide "
                             f"tiene {len(fotos)}")
                continue
            # La slide queda fija como está, con esa plantilla
            mismo = fotos[0].grupo and all(f.grupo == fotos[0].grupo for f in fotos)
            grupo = fotos[0].grupo if mismo else lista.grupo_nuevo()
            for f in fotos:
                f.sola, f.grupo, f.plantilla = False, grupo, nombre
            hecho.append(f"slide {numero}: con la plantilla {NOMBRES.get(nombre, nombre)}")
        elif len(partes) == 2:
            nombre = _normalizar(partes[1])
            if nombre.lower() not in photos_por_nombre:
                hecho.append(f"slide {numero}: no hay ninguna foto que se llame «{nombre}»")
                continue
            if lista.buscar(nombre) is not None:
                hecho.append(f"slide {numero}: {nombre} ya estaba en el post")
                continue
            nueva = Foto(photos_por_nombre[nombre.lower()].name)
            if not fotos:
                lista.fotos.append(nueva)
                hecho.append(f"slide {numero}: entra {nombre}")
                continue
            vieja = fotos[0]
            nueva.sola, nueva.grupo, nueva.plantilla = vieja.sola, vieja.grupo, vieja.plantilla
            lista.fotos[lista.fotos.index(vieja)] = nueva
            hecho.append(f"slide {numero}: {vieja.name} → {nombre}")
        else:
            hecho.append(f"«{limpia}» no se entiende")
    if tocado:
        archivo_cambios.write_text("\n".join(lineas_out) + "\n", encoding="utf-8")
    return lista, hecho


# --- el reparto en slides ---------------------------------------------------------------------

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


def plantillas_por_tamano() -> dict[int, list[dict]]:
    """Para la interfaz: qué plantillas hay para cada cantidad de fotos, con nombre legible."""
    return {k: [{"id": n, "nombre": NOMBRES.get(n, n)} for n in v]
            for k, v in sorted(_por_tamano().items())}


def _costo_collage(fotos: list, permitidas: list[str], nombres: list[str],
                   respetar_orientacion: bool = True):
    """(costo, plantilla, fotos en orden de celda) del mejor collage para estas fotos."""
    mejor = None
    apaisadas = all(_aspect(p) > LANDSCAPE for p in fotos)
    hero = max(fotos, key=lambda p: p.metrics.get("score", 0))
    for nombre in nombres:
        if respetar_orientacion and nombre in ONLY_LANDSCAPE and not apaisadas:
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


def pack(photos: list, solas: set, n_slides: int, config: dict,
         grupos: dict | None = None, plantillas: dict | None = None) -> tuple[list[dict], list, str]:
    """Reparte todas las elegidas en n_slides como mucho.

    `solas`: nombres que van solos. `grupos`: nombre -> grupo, las de un grupo van juntas en un
    collage. `plantillas`: grupo -> plantilla con que se arma. Devuelve (slides, las que no
    entraron, aviso).
    """
    montaje = config.get("montaje", {})
    permitidas_cfg = montaje.get("plantillas", {})
    por_tamano = _por_tamano()
    tamanos = sorted([1] + list(por_tamano))
    grupos = dict(grupos or {})
    plantillas = dict(plantillas or {})
    afuera: list = []
    avisos: list[str] = []

    # Un grupo que no tiene plantilla de su tamaño (editado a mano) se deshace
    tamano_grupo: dict[str, int] = {}
    for p in photos:
        if p.name in grupos:
            tamano_grupo[grupos[p.name]] = tamano_grupo.get(grupos[p.name], 0) + 1
    for g, n in tamano_grupo.items():
        if n == 1 or n not in por_tamano:
            if n > 1:
                avisos.append(f"un grupo de {n} fotos no tiene plantilla: van sueltas")
            grupos = {k: v for k, v in grupos.items() if v != g}
    solas = set(solas) - set(grupos)

    fotos = secuencia(photos)
    # Si no entran ni con los collages más grandes, afuera las de menor puntaje (y se avisa)
    capacidad = n_slides * max(tamanos)
    if len(fotos) > capacidad:
        sobran = sorted(fotos, key=lambda p: p.metrics.get("score", 0))[:len(fotos) - capacidad]
        afuera = sobran
        fotos = [p for p in fotos if p not in sobran]

    while True:
        unidades = _unidades(fotos, grupos)
        plan = _particion(unidades, solas, n_slides, tamanos, por_tamano, permitidas_cfg,
                          grupos, plantillas)
        if plan is not None or not fotos:
            break
        # No hay partición posible: primero se suelta lo que pidió él (de a una marca, la más
        # floja primero), y recién cuando no queda nada que soltar sale la foto más floja
        marcadas = [p for p in fotos if p.name in solas]
        if marcadas:
            solas = solas - {min(marcadas, key=lambda p: p.metrics.get("score", 0)).name}
            continue
        if grupos:
            g = sorted(set(grupos.values()))[0]
            grupos = {k: v for k, v in grupos.items() if v != g}
            avisos.append("se deshizo un collage pedido para que entre todo")
            continue
        peor = min(fotos, key=lambda p: p.metrics.get("score", 0))
        afuera.append(peor)
        fotos.remove(peor)
    if afuera:
        avisos.append(f"{len(afuera)} de las elegidas no entraron en {n_slides} slides: "
                      + ", ".join(p.name for p in afuera[:12]) + ("…" if len(afuera) > 12 else ""))

    slides = []
    for tramo, plantilla, orden, fijo in plan or []:
        hero = max(tramo, key=lambda p: p.metrics.get("score", 0))
        entry = {"photo": hero, "capitulo": hero.metrics.get("capitulo", "?"),
                 "unidad": hero.metrics.get("bloque"), "motivo": "la eligió él"}
        if plantilla:
            entry["plantilla"] = plantilla
            entry["fotos"] = orden
            entry["motivo"] += (f" · collage {plantilla}"
                                + (", armado a mano" if fijo else f" con {len(tramo) - 1} más"))
        else:
            entry["plantilla"] = None
            entry["fotos"] = [hero]
            if hero.name in solas:
                entry["forzar_sola"] = True
        slides.append(entry)
    slides.sort(key=lambda e: min((p.taken or "") for p in e["fotos"]))
    for numero, e in enumerate(slides, start=1):
        e["slide"] = numero
    return slides, afuera, " · ".join(avisos)


def _unidades(fotos: list, grupos: dict) -> list[list]:
    """La secuencia, con cada grupo pedido a mano convertido en una sola pieza.

    El grupo ocupa el lugar de su primera foto en la secuencia: así queda en su parte del día.
    """
    out: list[list] = []
    vistos: dict[str, list] = {}
    for p in fotos:
        g = grupos.get(p.name)
        if g is None:
            out.append([p])
        elif g in vistos:
            vistos[g].append(p)
        else:
            vistos[g] = [p]
            out.append(vistos[g])
    return out


def _particion(unidades: list[list], solas: set, n_slides: int, tamanos: list[int],
               por_tamano: dict, permitidas_cfg: dict, grupos: dict, plantillas: dict):
    """Programación dinámica: costo[i][s] = mejor forma de repartir las i primeras piezas en s slides.

    Una pieza es una foto suelta o un grupo pedido a mano. Un grupo va siempre solo en su slide.
    """
    n = len(unidades)
    if n == 0:
        return []
    inf = math.inf
    costo = [[inf] * (n_slides + 1) for _ in range(n + 1)]
    desde: list[list] = [[None] * (n_slides + 1) for _ in range(n + 1)]
    costo[0][0] = 0.0
    cache: dict[tuple[int, int], tuple] = {}
    max_k = max(tamanos)

    def tramo(i: int, k: int):
        """Costo y armado de la slide con las piezas i..i+k-1: (costo, plantilla, orden, fijo)."""
        if (i, k) in cache:
            return cache[(i, k)]
        piezas = unidades[i:i + k]
        grupo = [p for pieza in piezas for p in pieza]
        fijo = any(p.name in grupos for p in grupo)
        if fijo:
            if k > 1:
                valor = (inf, None, grupo, True)
            else:
                valor = _grupo_fijo(grupo, grupos, plantillas, por_tamano, permitidas_cfg)
        elif len(grupo) == 1:
            p = grupo[0]
            valor = (0.0 if p.name in solas or _aspect(p) <= LANDSCAPE else LANDSCAPE_SOLO,
                     None, grupo, False)
        elif any(p.name in solas for p in grupo) or len(grupo) not in por_tamano:
            valor = (inf, None, grupo, False)
        else:
            capitulos = {p.metrics.get("capitulo") for p in grupo}
            permitidas = permitidas_cfg.get(grupo[0].metrics.get("capitulo"), [])
            mejor = _costo_collage(grupo, permitidas, por_tamano[len(grupo)])
            if mejor is None:
                valor = (inf, None, grupo, False)
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
                valor = (mejor[0] * len(grupo) + extra, mejor[1], mejor[2], False)
        cache[(i, k)] = valor
        return valor

    for i in range(n):
        for s in range(n_slides):
            if costo[i][s] == inf:
                continue
            for k in range(1, max_k + 1):
                if i + k > n:
                    break
                c = tramo(i, k)[0]
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
        _, plantilla, orden, fijo = tramo(j, k)
        plan.append(([p for pieza in unidades[j:j + k] for p in pieza], plantilla, orden, fijo))
        i, s = j, s - 1
    plan.reverse()
    return plan


def _grupo_fijo(grupo: list, grupos: dict, plantillas: dict, por_tamano: dict,
                permitidas_cfg: dict) -> tuple:
    """Un collage que pidió él: con la plantilla que eligió, o la que mejor le quede.

    No paga costo: lo decidió él, y la partición se acomoda alrededor.
    """
    pedida = plantillas.get(grupos[grupo[0].name])
    if pedida in montage.TEMPLATES and len(montage.TEMPLATES[pedida]["celdas"]) == len(grupo):
        orden, _ = montage.assign(montage.TEMPLATES[pedida], grupo,
                                  max(grupo, key=lambda p: p.metrics.get("score", 0)))
        return (0.0, pedida, orden, True)
    permitidas = permitidas_cfg.get(grupo[0].metrics.get("capitulo"), [])
    nombres = por_tamano.get(len(grupo), [])
    # Si él juntó verticales, las plantillas de apaisadas también valen antes que nada
    mejor = (_costo_collage(grupo, permitidas, nombres)
             or _costo_collage(grupo, permitidas, nombres, respetar_orientacion=False))
    if mejor is None:
        return (math.inf, None, grupo, True)
    return (0.0, mejor[1], mejor[2], True)
