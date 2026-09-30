"""Armar post: una página local para mirar el post y cambiarlo sin tocar archivos.

Uso:  python curator/interfaz.py            (abre el navegador solo)
      python curator/interfaz.py --puerto 8770 --no-abrir

Es un servidor que sólo escucha en esta máquina (127.0.0.1). Las fotos no salen de acá: la página
pide las miniaturas y las slides al servidor, que las lee del disco.

Por qué una página y no una ventana de escritorio: el navegador ya sabe mostrar cientos de fotos,
se ve igual en macOS y en Windows, y no agrega dependencias. Todo lo que hace la página es lo mismo
que se puede hacer a mano con curate.py y cambios.txt; la diferencia es que no hay que escribir
rutas ni acordarse de nombres de archivo.

Los casamientos se agregan desde la página con el botón "Agregar casamiento", que abre el diálogo
de carpetas del sistema (Finder en macOS, Explorador en Windows). La carpeta **no se copia**: queda
donde está y acá se guarda la ruta, porque un álbum pesa varios GB.

Cada casamiento tiene dos posts posibles, y pueden convivir:

- **El de la IA** (salida/<casamiento>/): la herramienta elige los momentos del álbum completo.
- **Con sus elegidas** (salida/<casamiento>/elegidas/): Diego ya eligió las fotos —marcándolas en
  la página, arrastrándolas o con una carpeta— y la herramienta arma los collages con todas.

El botón "Entrenar" corre entrenar_todo.py: lo que publicó y lo que eligió pasan a ser ejemplos.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import album as album_lib
from lib import elegidas as elegidas_lib

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"
PAGINA = ROOT / "interfaz.html"
REGISTRO = ROOT / "casamientos.json"        # los que se agregaron desde la página, por ruta
ENTRENAMIENTO = ROOT / "entrenamiento.json"  # cuándo y con qué se entrenó por última vez
MODELO_PREFERENCIA = ROOT / "modelo_preferencia.json"
MODOS = ("ia", "elegidas")
MINI_LADO = 320                              # las miniaturas del selector de fotos
UNIDAD_WINDOWS = re.compile(r"^[A-Za-z]:")

TIPOS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
         ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8"}


def config() -> dict:
    base = json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.is_file() else {}
    return base.get("interfaz", {})


def valido(nombre: str) -> bool:
    """El nombre del álbum viene por HTTP: tiene que ser una carpeta suelta, sin rutas."""
    return bool(nombre) and "/" not in nombre and "\\" not in nombre and not nombre.startswith(".")


def _carpeta(valor: str | None, por_defecto: Path) -> Path:
    """Resuelve una ruta de config.json, tolerando que sea de otra máquina.

    El config puede venir de una PC con Windows y abrirse en una Mac: ahí "D:/bodas" no es una
    ruta absoluta sino una carpeta llamada "D:" colgando de donde se corrió el comando, y se
    terminaría creando basura. En ese caso se usa el valor por omisión.
    """
    if not valor:
        return por_defecto
    ruta = Path(valor).expanduser()
    if os.name != "nt" and UNIDAD_WINDOWS.match(str(valor)):
        return por_defecto
    return ruta if ruta.is_absolute() else (ROOT / ruta)


def carpetas() -> tuple[Path, Path]:
    """(carpeta donde busca casamientos, carpeta donde deja los posts)."""
    c = config()
    return (_carpeta(c.get("albumes"), ROOT / "albumes"),
            _carpeta(c.get("salida"), ROOT / "salida"))


# --- casamientos agregados desde la página ------------------------------------------------

def registrados() -> list[Path]:
    if not REGISTRO.is_file():
        return []
    try:
        datos = json.loads(REGISTRO.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return []
    return [Path(r).expanduser() for r in datos.get("albumes", []) if r]


def guardar_registrados(rutas: list[Path]) -> None:
    REGISTRO.write_text(json.dumps({"albumes": [str(r) for r in rutas]},
                                   ensure_ascii=False, indent=1), encoding="utf-8")


def contar_fotos(carpeta: Path) -> int:
    """Cuántas fotos tiene el álbum, contando subcarpetas (los álbumes de Drive suelen venir en
    carpetas por parte del día) y salteando las que no son material: caché, novios, publicado."""
    # En Windows y en macOS el sistema de archivos no distingue mayúsculas: sumar *.jpg y *.JPG
    # contaba cada foto dos veces
    try:
        fotos, _ = album_lib.scan(carpeta)
    except OSError:
        return 0
    return len({p.relative_to(carpeta).as_posix().lower() for p in fotos})


def albumes_por_nombre() -> dict[str, Path]:
    """Nombre visible -> carpeta, juntando la carpeta de la config y los agregados a mano.

    El nombre es el de la carpeta. Si dos casamientos distintos se llaman igual, al segundo se le
    agrega un número: el nombre también es el de la carpeta de salida, así que no puede repetirse.
    """
    base, _ = carpetas()
    encontrados: dict[str, Path] = {}

    def sumar(carpeta: Path) -> None:
        carpeta = carpeta.resolve()
        if carpeta in encontrados.values():
            return
        nombre, n = carpeta.name, 2
        while nombre in encontrados:
            nombre, n = f"{carpeta.name}-{n}", n + 1
        encontrados[nombre] = carpeta

    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir()):
            if contar_fotos(d) or (d / album_lib.CACHE_DIRNAME).is_dir():
                sumar(d)
    for ruta in registrados():
        if ruta.is_dir():
            sumar(ruta)
    return encontrados


class Trabajo:
    """La corrida que está en curso, y lo que va imprimiendo."""

    def __init__(self) -> None:
        self.lineas: list[str] = []
        self.album = ""
        self.proceso: subprocess.Popen | None = None
        self.lock = threading.Lock()

    @property
    def corriendo(self) -> bool:
        return self.proceso is not None and self.proceso.poll() is None

    def arrancar(self, album: Path, salida: Path, novios: Path | None,
                 extra: list[str] | None = None, titulo: str | None = None) -> bool:
        cmd = [sys.executable, str(ROOT / "curate.py"), str(album), "--out", str(salida)]
        if novios and novios.is_dir():
            cmd += ["--novios", str(novios)]
        return self.correr(cmd + (extra or []), titulo or f"armar el post de {album.name}",
                           album.name)

    def correr(self, cmd: list[str], titulo: str, album: str = "") -> bool:
        """Arranca un proceso y va juntando lo que imprime. False si ya había otro corriendo."""
        with self.lock:
            if self.corriendo:
                return False
            self.lineas = [f"$ {titulo}"]
            self.album = album
            self.proceso = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._leer, daemon=True).start()
        return True

    def _leer(self) -> None:
        assert self.proceso and self.proceso.stdout
        for linea in self.proceso.stdout:
            linea = linea.rstrip()
            # Los avisos de las librerías no le dicen nada a nadie: se filtran
            if not linea or linea.startswith(("W0", "I0", "E0", "===", "INFO:", "[ WARN")):
                continue
            with self.lock:
                self.lineas.append(linea)
        self.proceso.wait()
        with self.lock:
            self.lineas.append("listo" if self.proceso.returncode == 0
                               else f"terminó con error ({self.proceso.returncode})")

    def estado(self) -> dict:
        with self.lock:
            return {"corriendo": self.corriendo, "album": self.album, "lineas": self.lineas[-60:]}


TRABAJO = Trabajo()


# --- diálogos del sistema -----------------------------------------------------------------

def elegir_carpeta() -> tuple[str | None, str | None]:
    """Abre el diálogo de carpetas del sistema. Devuelve (ruta, error); ambos None si canceló.

    Se usa el diálogo del sistema operativo y no uno del navegador porque el navegador, por
    seguridad, nunca le da a la página la ruta real de una carpeta del disco: daría los archivos,
    y copiar 5 GB para analizarlos no tiene sentido cuando el álbum ya está acá.
    """
    if sys.platform == "darwin":
        guion = 'POSIX path of (choose folder with prompt "Elegí la carpeta del casamiento")'
        cmd = ["osascript", "-e", "activate", "-e", guion]
    elif os.name == "nt":
        guion = ("Add-Type -AssemblyName System.Windows.Forms;"
                 "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
                 "$d.Description = 'Elegi la carpeta del casamiento';"
                 "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.SelectedPath }")
        cmd = ["powershell", "-NoProfile", "-STA", "-Command", guion]
    else:
        cmd = ["zenity", "--file-selection", "--directory",
               "--title=Elegí la carpeta del casamiento"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        return None, "no se pudo abrir el diálogo de carpetas en este sistema"
    except subprocess.TimeoutExpired:
        return None, "el diálogo quedó abierto demasiado tiempo"
    ruta = (r.stdout or "").strip()
    if not ruta:
        return None, None                   # canceló, que no es un error
    return ruta, None


def abrir_en_el_explorador(ruta: Path) -> None:
    """Deja la carpeta abierta adelante, en el Finder o en el Explorador."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    elif os.name == "nt":
        os.startfile(ruta)                  # noqa: S606 - carpeta propia, no viene del usuario
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


def destino(salida: Path, nombre: str, modo: str) -> Path:
    """Dónde queda cada post: el de la IA en la carpeta del casamiento, el otro en elegidas/."""
    return salida / nombre / "elegidas" if modo == "elegidas" else salida / nombre


def _cuando(archivo: Path) -> str | None:
    return (datetime.fromtimestamp(archivo.stat().st_mtime).strftime("%d/%m %H:%M")
            if archivo.is_file() else None)


def listar_albumes() -> list[dict]:
    _, salida = carpetas()
    fijos = {p.resolve() for p in registrados()}
    out = []
    for nombre, carpeta in albumes_por_nombre().items():
        ia = salida / nombre / "seleccion.json"
        eleg = salida / nombre / "elegidas" / "seleccion.json"
        lista = salida / nombre / "elegidas" / elegidas_lib.ARCHIVO
        out.append({
            "nombre": nombre, "ruta": str(carpeta), "fotos": contar_fotos(carpeta),
            "novios": (carpeta / "novios").is_dir(),
            "agregado": carpeta.resolve() in fijos,
            "curado": ia.is_file() or eleg.is_file(),
            "cuando": _cuando(ia) or _cuando(eleg),
            "curado_ia": ia.is_file(), "curado_elegidas": eleg.is_file(),
            "elegidas": len(elegidas_lib.leer(lista)),
            "carpeta_elegidas": (carpeta / "elegidas").is_dir(),
            "publicado": any((carpeta / d).is_dir() for d in ("publicado", "publicadas", "instagram")),
        })
    return out


def datos_post(nombre: str, modo: str = "ia") -> dict:
    _, salida = carpetas()
    carpeta = destino(salida, nombre, modo)
    archivo = carpeta / "seleccion.json"
    if not archivo.is_file():
        return {"slides": [], "suplentes": [], "capitulos": []}
    datos = json.loads(archivo.read_text(encoding="utf-8-sig"))
    cambios = carpeta / "cambios.txt"
    datos["cambios"] = [l for l in cambios.read_text(encoding="utf-8-sig").splitlines()
                        if l.strip() and not l.strip().startswith("#")] if cambios.is_file() else []
    return datos


def fotos_del_album(nombre: str) -> dict:
    """Todas las fotos del álbum, para el selector: nombre, miniatura, hora y lo que sepa la IA."""
    album = albumes_por_nombre().get(nombre)
    if album is None:
        return {"fotos": [], "preparado": False}
    cache = album / album_lib.CACHE_DIRNAME
    indice = album_lib.load_index(cache)
    archivos, _ = album_lib.scan(album)
    rels = {p.relative_to(album).as_posix() for p in archivos}
    listas = [p for rel, p in indice.items() if rel in rels
              and (cache / "thumbs" / f"{p.key}.jpg").is_file()]
    # Lo que sabe la IA, si el álbum ya se analizó: puntaje, capítulo, y si es la mejor toma
    # de su ráfaga (las otras tomas se pueden esconder en el selector)
    extra: dict[str, dict] = {}
    analisis = cache / "analisis.json"
    if analisis.is_file():
        try:
            for f in json.loads(analisis.read_text(encoding="utf-8-sig")).get("fotos", []):
                extra[f["rel"]] = {"score": f.get("score"), "capitulo": f.get("capitulo"),
                                   "rafaga": f.get("group_size", 1),
                                   "principal": f.get("rank_in_group", 0) == 0,
                                   "grupo": f.get("group")}
        except (json.JSONDecodeError, KeyError):
            extra = {}
    listas.sort(key=lambda p: (p.taken or "", p.rel))
    return {
        "preparado": len(listas) >= len(rels) and bool(rels),
        "total": len(rels),
        "analizado": bool(extra),
        "fotos": [{"name": p.name, "key": p.key, "taken": p.taken,
                   "v": p.height > p.width * 1.05, **extra.get(p.rel, {})} for p in listas],
    }


def nombres_del_album(album: Path) -> dict[str, str]:
    """nombre en minúsculas -> nombre tal cual, para cruzar lo que eligió con lo que hay."""
    archivos, _ = album_lib.scan(album)
    out: dict[str, str] = {}
    for p in archivos:
        out.setdefault(p.stem.lower(), p.stem)
    return out


def guardar_elegidas(nombre: str, album: Path, nombres: list[str], sumar: bool) -> dict:
    """Cruza los nombres con el álbum y guarda la lista. Devuelve cuántas quedaron y cuáles no están."""
    _, salida = carpetas()
    lista = destino(salida, nombre, "elegidas") / elegidas_lib.ARCHIVO
    hay = nombres_del_album(album)
    pedidas = elegidas_lib.desde_nombres(nombres)
    faltan = [n for n, _ in pedidas if n.lower() not in hay]
    nuevas = [(hay[n.lower()], False) for n, _ in pedidas if n.lower() in hay]
    if sumar:
        previas = elegidas_lib.leer(lista)
        ya = {n.lower() for n, _ in previas}
        nuevas = previas + [x for x in nuevas if x[0].lower() not in ya]
    else:
        # Reemplazar la lista conserva las marcas de "sola" de las que siguen
        solas = {n.lower() for n, s in elegidas_lib.leer(lista) if s}
        nuevas = [(n, n.lower() in solas) for n, _ in nuevas]
    elegidas_lib.guardar(lista, nuevas)
    return {"ok": True, "elegidas": len(nuevas), "faltan": faltan[:30], "cuantas_faltan": len(faltan)}


def mini(album: Path, clave: str) -> Path | None:
    """Miniatura chica para el selector: 3.000 fotos de 1024 px no las aguanta ningún navegador."""
    origen = album / album_lib.CACHE_DIRNAME / "thumbs" / f"{clave}.jpg"
    if not origen.is_file():
        return None
    dest = album / album_lib.CACHE_DIRNAME / "mini" / f"{clave}.jpg"
    if not dest.is_file() or dest.stat().st_mtime < origen.stat().st_mtime:
        from PIL import Image
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(origen) as im:
            im = im.convert("RGB")
            im.thumbnail((MINI_LADO, MINI_LADO))
            tmp = dest.with_suffix(".part")
            im.save(tmp, "JPEG", quality=80)
            tmp.replace(dest)
    return dest


def estado_modelo() -> dict:
    """Con qué se entrenó la preferencia, para mostrarlo en la página."""
    out: dict = {"entrenado": MODELO_PREFERENCIA.is_file()}
    if MODELO_PREFERENCIA.is_file():
        try:
            meta = json.loads(MODELO_PREFERENCIA.read_text(encoding="utf-8-sig")).get("meta", {})
            out["casamientos"] = len(meta.get("casamientos", []))
            out["positivos"] = meta.get("positivos")
        except json.JSONDecodeError:
            pass
        out["cuando"] = _cuando(MODELO_PREFERENCIA)
    if ENTRENAMIENTO.is_file():
        try:
            out["ultimo"] = json.loads(ENTRENAMIENTO.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError:
            pass
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:       # sin ruido en la consola
        pass

    def _send(self, code: int, body: bytes, tipo: str, cache: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(body)))
        # Las miniaturas no cambian (la clave depende del archivo): que el navegador las guarde,
        # así el selector de 3.000 fotos no las vuelve a pedir en cada vuelta
        self.send_header("Cache-Control", "max-age=86400" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), TIPOS[".json"])

    def _archivo(self, path: Path, cache: bool = False) -> None:
        if not path.is_file():
            self._json({"error": "no existe"}, 404)
            return
        self._send(200, path.read_bytes(), TIPOS.get(path.suffix.lower(), "application/octet-stream"),
                   cache)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        _, salida = carpetas()
        modo = q.get("modo") if q.get("modo") in MODOS else "ia"
        nombre = q.get("album", "")

        if url.path in ("/", "/index.html"):
            self._archivo(PAGINA)
        elif url.path == "/api/albumes":
            self._json(listar_albumes())
        elif url.path == "/api/estado":
            self._json(TRABAJO.estado())
        elif url.path == "/api/modelo":
            self._json(estado_modelo())
        elif url.path == "/api/post":
            self._json(datos_post(nombre, modo) if valido(nombre) else {"slides": []})
        elif url.path == "/api/fotos":
            self._json(fotos_del_album(nombre) if valido(nombre) else {"fotos": []})
        elif url.path == "/api/elegidas":
            if not valido(nombre):
                self._json({"elegidas": []})
                return
            lista = destino(salida, nombre, "elegidas") / elegidas_lib.ARCHIVO
            self._json({"elegidas": [{"name": n, "sola": s} for n, s in elegidas_lib.leer(lista)]})
        elif url.path == "/slide":
            if not valido(nombre):
                self._json({"error": "nombre raro"}, 400)
                return
            self._archivo(destino(salida, nombre, modo) / "slides" / f"{int(q.get('n', 0)):02d}.jpg")
        elif url.path in ("/thumb", "/mini"):
            album = albumes_por_nombre().get(nombre) if valido(nombre) else None
            if album is None:
                self._json({"error": "nombre raro"}, 400)
                return
            # La clave es hexadecimal: sirve de protección contra rutas raras
            clave = "".join(c for c in q.get("key", "") if c in "0123456789abcdef")
            if url.path == "/mini":
                archivo = mini(album, clave)
                if archivo is None:
                    self._json({"error": "no existe"}, 404)
                    return
                self._archivo(archivo, cache=True)
            else:
                self._archivo(album / album_lib.CACHE_DIRNAME / "thumbs" / f"{clave}.jpg", cache=True)
        else:
            self._json({"error": "no existe"}, 404)

    # --- agregar y quitar casamientos ------------------------------------------------------

    def _elegir(self) -> None:
        ruta, error = elegir_carpeta()
        if error:
            self._json({"error": error}, 500)
        else:
            self._json({"ruta": ruta})      # ruta None = canceló

    def _agregar(self, cuerpo: dict) -> None:
        crudo = str(cuerpo.get("ruta", "")).strip().strip('"').strip("'")
        if not crudo:
            self._json({"error": "no llegó ninguna carpeta"}, 400)
            return
        carpeta = Path(crudo).expanduser()
        if not carpeta.is_dir():
            self._json({"error": f"no existe la carpeta {carpeta}"}, 400)
            return
        carpeta = carpeta.resolve()
        fotos = contar_fotos(carpeta)
        if not fotos:
            self._json({"error": "esa carpeta no tiene fotos JPEG adentro, ni en sus subcarpetas. "
                                 "Si son RAW, hay que exportarlas reveladas a JPEG"}, 400)
            return
        ya = albumes_por_nombre()
        for nombre, otra in ya.items():
            if otra == carpeta:
                self._json({"ok": True, "nombre": nombre, "fotos": fotos, "repetido": True})
                return
        rutas = registrados()
        rutas.append(carpeta)
        guardar_registrados(rutas)
        nombre = next((n for n, c in albumes_por_nombre().items() if c == carpeta), carpeta.name)
        self._json({"ok": True, "nombre": nombre, "fotos": fotos})

    def _quitar(self, nombre: str, album: Path) -> None:
        """Lo saca de la lista. No borra nada del disco: ni el álbum ni el post."""
        quedan = [r for r in registrados() if r.resolve() != album]
        if len(quedan) == len(registrados()):
            self._json({"error": "ése no se agregó desde acá: está en la carpeta de la config"}, 400)
            return
        guardar_registrados(quedan)
        self._json({"ok": True, "nombre": nombre})

    def do_POST(self) -> None:
        url = urlparse(self.path)
        largo = int(self.headers.get("Content-Length", 0))
        try:
            cuerpo = json.loads(self.rfile.read(largo) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "pedido mal formado"}, 400)
            return
        _, salida = carpetas()

        # Estos no hablan de un álbum que ya exista
        if url.path == "/api/elegir":
            self._elegir()
            return
        if url.path == "/api/agregar":
            self._agregar(cuerpo)
            return
        if url.path == "/api/entrenar":
            ok = TRABAJO.correr([sys.executable, str(ROOT / "entrenar_todo.py")],
                                "entrenar con todo lo que eligió y publicó")
            self._json({"ok": ok} if ok else {"error": "ya hay algo corriendo, esperá que termine"})
            return

        nombre = cuerpo.get("album", "")
        album = albumes_por_nombre().get(nombre) if valido(nombre) else None
        if album is None:
            self._json({"error": "ese álbum no está"}, 400)
            return
        modo = cuerpo.get("modo") if cuerpo.get("modo") in MODOS else "ia"
        carpeta = destino(salida, nombre, modo)

        if url.path == "/api/curar":
            carpeta.mkdir(parents=True, exist_ok=True)
            extra = []
            if modo == "elegidas":
                lista = carpeta / elegidas_lib.ARCHIVO
                if not elegidas_lib.leer(lista):
                    self._json({"error": "todavía no hay fotos elegidas"}, 400)
                    return
                extra = ["--elegidas", str(lista)]
            slides = cuerpo.get("slides")
            if isinstance(slides, int) and 1 <= slides <= 20:
                extra += ["--slides", str(slides)]
            titulo = (f"armar el post de {nombre} con sus elegidas" if modo == "elegidas"
                      else f"armar el post de {nombre}")
            ok = TRABAJO.arrancar(album, carpeta, album / "novios", extra, titulo)
            self._json({"ok": ok} if ok else {"error": "ya hay algo corriendo, esperá que termine"})
        elif url.path == "/api/preparar":
            ok = TRABAJO.arrancar(album, destino(salida, nombre, "ia"), None, ["--preparar"],
                                  f"preparar las miniaturas de {nombre}")
            self._json({"ok": ok} if ok else {"error": "ya hay algo corriendo, esperá que termine"})
        elif url.path == "/api/cambios":
            lineas = [str(l).strip() for l in cuerpo.get("lineas", []) if str(l).strip()]
            archivo = carpeta / "cambios.txt"
            previo = archivo.read_text(encoding="utf-8-sig") if archivo.is_file() else ""
            archivo.write_text(previo.rstrip() + "\n" + "\n".join(lineas) + "\n", encoding="utf-8")
            extra = ["--elegidas", str(carpeta / elegidas_lib.ARCHIVO)] if modo == "elegidas" else []
            ok = TRABAJO.arrancar(album, carpeta, album / "novios", extra)
            self._json({"ok": ok, "lineas": lineas} if ok
                       else {"error": "ya hay algo corriendo: los cambios quedaron guardados, "
                                      "se aplican la próxima vez que se arme"})
        elif url.path == "/api/elegidas":
            nombres = [str(n) for n in cuerpo.get("nombres", []) if str(n).strip()]
            self._json(guardar_elegidas(nombre, album, nombres, bool(cuerpo.get("sumar"))))
        elif url.path == "/api/elegidas-carpeta":
            # Una carpeta con copias de las que eligió: sólo importan los nombres
            if cuerpo.get("interna"):
                ruta = album / "elegidas"
            else:
                elegida, error = elegir_carpeta()
                if error:
                    self._json({"error": error}, 500)
                    return
                if not elegida:
                    self._json({"ok": False})
                    return
                ruta = Path(elegida)
            if not ruta.is_dir():
                self._json({"error": f"no existe la carpeta {ruta}"}, 400)
                return
            nombres = [n for n, _ in elegidas_lib.desde_carpeta(ruta)]
            if not nombres:
                self._json({"error": "esa carpeta no tiene fotos"}, 400)
                return
            r = guardar_elegidas(nombre, album, nombres, bool(cuerpo.get("sumar")))
            if r["elegidas"] == 0:
                r = {"error": f"ninguna de las {len(nombres)} fotos de esa carpeta está en el álbum "
                              f"{nombre} (se cruzan por nombre de archivo). Si esa carpeta es todo "
                              f"lo que hay, agregala como casamiento y usá «todas las fotos»"}
            self._json(r)
        elif url.path == "/api/elegidas-todas":
            nombres = list(nombres_del_album(album).values())
            self._json(guardar_elegidas(nombre, album, nombres, False))
        elif url.path == "/api/abrir":
            # Él sube las slides a mano: que el botón le deje la carpeta abierta adelante
            slides = carpeta / "slides"
            if not slides.is_dir():
                self._json({"error": "todavía no hay slides"}, 404)
                return
            abrir_en_el_explorador(slides)
            self._json({"ok": True, "carpeta": str(slides)})
        elif url.path == "/api/quitar":
            self._quitar(nombre, album)
        elif url.path == "/api/limpiar-cambios":
            archivo = carpeta / "cambios.txt"
            if archivo.is_file():
                quedan = [l for l in archivo.read_text(encoding="utf-8-sig").splitlines()
                          if l.strip().startswith("#")]
                archivo.write_text("\n".join(quedan) + "\n", encoding="utf-8")
            self._json({"ok": True})
        else:
            self._json({"error": "no existe"}, 404)


def main() -> None:
    parser = argparse.ArgumentParser(description="Armar post: la interfaz local")
    parser.add_argument("--puerto", type=int, default=config().get("puerto", 8770))
    parser.add_argument("--no-abrir", action="store_true")
    args = parser.parse_args()

    albumes, salida = carpetas()
    salida.mkdir(parents=True, exist_ok=True)
    servidor = ThreadingHTTPServer(("127.0.0.1", args.puerto), Handler)
    url = f"http://127.0.0.1:{args.puerto}/"
    cuantos = len(albumes_por_nombre())
    print(f"Armar post en {url}", flush=True)
    print(f"  casamientos: {cuantos} · carpeta {albumes}"
          f"{' (todavía no existe)' if not albumes.is_dir() else ''}", flush=True)
    print(f"  los posts van a: {salida}", flush=True)
    print("  para sumar un casamiento, el botón 'Agregar casamiento' de la página", flush=True)
    print("  (Ctrl+C para cortar)", flush=True)
    if not args.no_abrir:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nlisto", flush=True)


if __name__ == "__main__":
    main()
