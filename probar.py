"""Pruebas funcionales de Armar post: un solo comando que verifica que todo anda.

Uso:  python curator/probar.py                 (usa las carpetas de config.json)
      python curator/probar.py --rapido        (no vuelve a armar: sólo revisa lo ya hecho)

Revisa, en este orden:

1. El entorno: versiones, modelos bajados y referencias entrenadas.
2. La calibración contra las fotos que él publicó (ninguna puede quedar castigada).
3. Cada casamiento: que corra de punta a punta, que el post cumpla sus propiedades y
   que volver a correrlo sin pedir cambios no le mueva nada.
4. Contra la verdad, donde la haya: cuánto se parece lo que elige la herramienta a lo que eligió
   él, y cuánto acierta dejando el casamiento entero afuera del entrenamiento.
5. La interfaz: que conteste.

Termina con un resumen y un código de salida: 0 si pasó todo.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import album as album_lib

ROOT = Path(__file__).resolve().parent
RESULTADOS: list[tuple[bool, str]] = []


def marca(ok: bool, texto: str) -> None:
    RESULTADOS.append((ok, texto))
    print(("   OK    " if ok else "   FALLA ") + texto, flush=True)


def dato(texto: str) -> None:
    print("   ·     " + texto, flush=True)


def correr(cmd: list[str], timeout: int = 3600) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def entorno() -> None:
    print("\n1. Entorno", flush=True)
    versiones = []
    for modulo, nombre in (("PIL", "Pillow"), ("numpy", "numpy"), ("cv2", "OpenCV"),
                           ("onnxruntime", "onnxruntime")):
        try:
            m = __import__(modulo)
            versiones.append(f"{nombre} {getattr(m, '__version__', '?')}")
        except ImportError:
            versiones.append(f"{nombre} FALTA")
    ok = all("FALTA" not in v for v in versiones)
    marca(ok, f"librerías: python {sys.version.split()[0]}, " + ", ".join(versiones))

    from lib import models
    faltan, pesan = [], 0
    for nombre in ("yunet", "sface", "clip"):
        p = models.MODELS / models.SOURCES[nombre][1]
        if p.is_file():
            pesan += p.stat().st_size
        else:
            faltan.append(nombre)
    marca(not faltan, f"modelos bajados ({pesan / 1e6:.0f} MB)" if not faltan
          else f"faltan modelos: {faltan} — correr python curator/curate.py --modelos")

    refs = ROOT / "referencias.npz"
    if refs.is_file():
        import numpy as np
        d = np.load(refs)
        bodas = sorted(set(d["origen"].tolist()))
        marca(True, f"entrenado con {len(d['vectors'])} fotos publicadas de "
                    f"{len(bodas)} casamientos ({', '.join(bodas)})")
    else:
        marca(False, "sin referencias.npz — correr python curator/entrenar.py")


def calibracion() -> None:
    print("\n2. Calibración contra lo que él publicó", flush=True)
    code, salida = correr([sys.executable, str(ROOT / "test_calibracion.py"), "--sin-caras"])
    ultima = [l for l in salida.splitlines() if l.strip()][-1] if salida.strip() else "sin salida"
    marca(code == 0, ultima.strip())


def plan_de(destino: Path) -> dict[int, tuple]:
    """El post como está en el disco: qué foto y qué montaje tiene cada slide."""
    archivo = destino / "seleccion.json"
    if not archivo.is_file():
        return {}
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return {s["slide"]: (s["rel"], s.get("plantilla"), tuple(s.get("fotos", [])))
            for s in datos.get("slides", [])}


def casamientos(albumes: Path, salida: Path, rapido: bool) -> None:
    print("\n3. Casamientos", flush=True)
    carpetas = [d for d in sorted(albumes.iterdir()) if d.is_dir()] if albumes.is_dir() else []
    if not carpetas:
        marca(False, f"no hay casamientos en {albumes}")
        return
    for album in carpetas:
        fotos, _ = album_lib.scan(album)
        if not fotos:
            continue
        destino = salida / album.name
        print(f"\n   {album.name} · {len(fotos)} fotos", flush=True)
        antes = plan_de(destino)
        if not rapido:
            cmd = [sys.executable, str(ROOT / "curate.py"), str(album), "--out", str(destino)]
            novios = album / "novios"
            if novios.is_dir():
                cmd += ["--novios", str(novios)]
            inicio = time.time()
            code, texto = correr(cmd)
            resumen = [l.strip() for l in texto.splitlines() if "slides," in l]
            marca(code == 0, f"{album.name} · corre de punta a punta en {time.time() - inicio:.0f} s"
                             + (f" · {resumen[0]}" if resumen else ""))
            if code != 0:
                dato(texto.strip().splitlines()[-1] if texto.strip() else "sin salida")
                continue
        if not (destino / "seleccion.json").is_file():
            dato("todavía sin post (sacá --rapido para armarlo)")
            continue
        if antes and not rapido:
            # Sin cambios pedidos, dos corridas tienen que dar el mismo post: si no, el post se
            # le mueve solo entre una corrida y la otra
            ahora = plan_de(destino)
            movidas = sorted(n for n in antes if antes.get(n) != ahora.get(n))
            marca(not movidas, f"{album.name} · volver a armarlo no mueve el post"
                               if not movidas
                               else f"{album.name} · volver a armarlo movió {len(movidas)} slides "
                                    f"sin que se lo pidieran: {movidas[:6]}")
        for prueba, nombre in (("test_montaje.py", "montaje"), ("test_guion.py", "guion")):
            code, texto = correr([sys.executable, str(ROOT / prueba), str(destino)])
            fallas = [l.strip() for l in texto.splitlines() if l.strip().startswith("FALLA")]
            marca(code == 0, f"{album.name} · {nombre}: "
                             + ("todas las propiedades se cumplen" if code == 0
                                else "; ".join(fallas) or "falló"))
        verdad = album / album_lib.CACHE_DIRNAME / "publicadas.json"
        if verdad.is_file():
            code, texto = correr([sys.executable, str(ROOT / "evaluar.py"), str(album), str(destino)])
            for linea in texto.splitlines():
                if "mismo momento" in linea or "puntaje final" in linea or "misma foto" in linea:
                    dato(linea.strip())


def validacion() -> None:
    """La prueba que importa: dejando el casamiento entero afuera, ¿acierta en él?"""
    print("\n4. Acierto en un casamiento que no vio", flush=True)
    code, texto = correr([sys.executable, str(ROOT / "validacion.py")])
    if code != 0:
        marca(False, "validacion.py falló")
        dato(texto.strip().splitlines()[-1] if texto.strip() else "sin salida")
        return
    lineas = texto.splitlines()
    for linea in lineas:
        if "promedio pesado" in linea or "regularización L2" in linea:
            dato(linea.strip().replace("**", ""))
    mejor = [l for l in lineas if "promedio pesado" in l]
    if not mejor:
        dato("todavía no hay dos casamientos con verdad para validar")
        return
    valores = re.findall(r"[*][*]([0-9.]+)[*][*]", mejor[0])
    valor = float(valores[0]) if valores else 0.0
    marca(valor > 0.55, f"AUC {valor:.3f} sobre un casamiento que no estaba en el entrenamiento "
                        f"(0.50 sería tirar la moneda)")


def interfaz(puerto: int) -> None:
    print("\n5. Interfaz", flush=True)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{puerto}/api/albumes", timeout=4) as r:
            datos = json.loads(r.read())
        marca(True, f"contesta en http://127.0.0.1:{puerto}/ con {len(datos)} casamientos")
    except (urllib.error.URLError, TimeoutError, OSError):
        dato(f"no está levantada (se levanta con: python curator/interfaz.py)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pruebas funcionales de Armar post")
    parser.add_argument("--rapido", action="store_true", help="no vuelve a armar los posts, sólo revisa")
    args = parser.parse_args()

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
    inter = config.get("interfaz", {})
    albumes = Path(inter.get("albumes", ROOT / "albumes")).expanduser()
    salida = Path(inter.get("salida", ROOT / "salida")).expanduser()

    print(f"Armar post · pruebas funcionales · {datetime.now():%d/%m/%Y %H:%M}")
    print(f"  casamientos en {albumes}")
    print(f"  salida en     {salida}")
    entorno()
    calibracion()
    casamientos(albumes, salida, args.rapido)
    validacion()
    interfaz(int(inter.get("puerto", 8770)))

    fallaron = [t for ok, t in RESULTADOS if not ok]
    print(f"\n{'=' * 70}")
    print(f"{len(RESULTADOS) - len(fallaron)} de {len(RESULTADOS)} pruebas pasaron")
    for t in fallaron:
        print(f"  FALLA  {t}")
    return 1 if fallaron else 0


if __name__ == "__main__":
    raise SystemExit(main())
