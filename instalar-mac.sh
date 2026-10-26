#!/bin/bash
# Deja Armar post listo en esta Mac: entorno de Python, librerías, modelos, carpetas y lanzador.
# Hace los pasos 2 a 8 de INSTALAR-MAC.md. Se puede correr las veces que haga falta: lo que ya
# está hecho lo saltea.
#
#   bash instalar-mac.sh
#   bash instalar-mac.sh --albumes ~/ArmarPost/casamientos --salida ~/ArmarPost/posts
#
# No toca fotos ni manda nada a ningún lado. Lo único que baja de internet son las librerías
# (~150 MB) y los modelos (126 MB) si no se copiaron a modelos/.
#
# Termina con 0 si quedó todo listo, 1 si falta algo (lo dice al final).

cd "$(dirname "$0")" || exit 1
DIR="$(pwd)"

ALBUMES="$HOME/ArmarPost/casamientos"
SALIDA="$HOME/ArmarPost/posts"
ELEGIDAS=""        # las que se pasaron a mano: ésas se escriben en config.json aunque ya tenga otra
USO="Uso: bash instalar-mac.sh [--albumes RUTA] [--salida RUTA]"
while [ $# -gt 0 ]; do
  [ $# -ge 2 ] || { echo "$USO"; exit 2; }     # las dos opciones llevan una ruta
  case "$1" in
    --albumes) ALBUMES="$2"; ELEGIDAS="$ELEGIDAS albumes"; shift 2 ;;
    --salida)  SALIDA="$2"; ELEGIDAS="$ELEGIDAS salida"; shift 2 ;;
    *) echo "$USO"; exit 2 ;;
  esac
done

FALTAN=()
ok()    { printf '   OK    %s\n' "$*"; }
falta() { printf '   FALTA %s\n' "$*"; FALTAN+=("$*"); }
dato()  { printf '   ·     %s\n' "$*"; }
paso()  { printf '\n%s\n' "$*"; }

echo "Armar post · instalación en $DIR"
if [ "$(uname -s)" != "Darwin" ]; then
  dato "esto no es una Mac ($(uname -s)): sigo igual, pero los permisos y el lanzador son de macOS"
else
  dato "macOS $(sw_vers -productVersion) · $(uname -m)"
fi


paso "1. Python"
# El /usr/bin/python3 de macOS es un señuelo: si no están las herramientas de Xcode, abre el cartel
# para instalarlas (más de 1 GB), y si están es un 3.9. No se usa.
PY=""
for c in python3.12 python3.13 python3.11 python3.10 python3; do
  ruta="$(command -v "$c" 2>/dev/null)" || continue
  [ "$ruta" = "/usr/bin/python3" ] && continue
  if "$ruta" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PY="$ruta"
    break
  fi
done
if [ -z "$PY" ]; then
  falta "Python 3.10 o mayor (mejor 3.12)"
  if command -v brew >/dev/null 2>&1; then
    dato "instalarlo con:  brew install python@3.12"
  else
    dato "bajar el instalador de https://www.python.org/downloads/macos/ (macOS 64-bit universal2, 3.12)"
  fi
  dato "después volver a correr: bash instalar-mac.sh"
  exit 1
fi
ok "$("$PY" --version 2>&1) en $PY"


paso "2. Entorno y librerías"
VPY="$DIR/.venv/bin/python"
# Un .venv copiado de otra máquina (o de Windows, que no tiene bin/) no sirve: se rehace
if [ -e .venv ] && ! "$VPY" -c 'import sys' >/dev/null 2>&1; then
  dato "el .venv que había no anda en esta máquina: lo rehago"
  rm -rf .venv
fi
if [ ! -x "$VPY" ]; then
  "$PY" -m venv .venv || { falta "no se pudo crear el entorno .venv"; exit 1; }
fi
"$VPY" -m pip install --upgrade pip --quiet --disable-pip-version-check
if ! "$VPY" -m pip install -r requirements.txt --progress-bar off --disable-pip-version-check; then
  falta "no se instalaron las librerías (el detalle está arriba)"
  exit 1
fi
if versiones="$("$VPY" -c 'import PIL, numpy, cv2, onnxruntime as o; print(f"Pillow {PIL.__version__}, numpy {numpy.__version__}, OpenCV {cv2.__version__}, onnxruntime {o.__version__}")' 2>&1)"; then
  ok "$versiones"
else
  falta "las librerías no cargan: $versiones"
  exit 1
fi


paso "3. Modelos (CLIP, YuNet, SFace)"
# Si se copió modelos/ de la otra máquina no baja nada: sólo los verifica
if "$VPY" curate.py --modelos; then
  ok "modelos en $DIR/modelos"
else
  falta "no se pudieron bajar los modelos: copiar la carpeta modelos/ de la otra máquina a $DIR/modelos"
fi


paso "4. Lo que aprendió de sus casamientos (no está en git)"
for archivo in referencias.npz modelo_preferencia.json; do
  if [ -s "$archivo" ]; then
    ok "$archivo"
  else
    falta "$archivo: copiarlo de la máquina donde se entrenó a $DIR/ (no se puede regenerar sin los álbumes)"
  fi
done
if [ -s datos_preferencia.npz ]; then
  ok "datos_preferencia.npz"
else
  dato "sin datos_preferencia.npz: arma los posts igual, pero Entrenar no reemplaza el modelo hasta que esté"
fi


paso "5. Carpetas de casamientos y de posts"
# Sólo se toca config.json si su ruta no sirve en esta máquina (la D:/ de Windows) o si se pasó
# --albumes / --salida. El resto del archivo queda igual, byte a byte.
"$VPY" - "$ALBUMES" "$SALIDA" "$ELEGIDAS" <<'PY'
import json, os, re, sys
from pathlib import Path

albumes, salida = sys.argv[1], sys.argv[2]
config = Path("config.json")
datos = json.loads(config.read_text(encoding="utf-8-sig"))
inter = datos.setdefault("interfaz", {})

def sirve(valor):
    """Una ruta absoluta de esta máquina, que exista o se pueda crear (la de otro usuario no)."""
    if not valor or re.match(r"^[A-Za-z]:[\\/]", valor):
        return False
    ruta = Path(valor).expanduser()
    if not ruta.is_absolute():
        return False
    try:
        ruta.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    return True

elegidas = sys.argv[3].split()
cambio = False
for clave, nueva in (("albumes", albumes), ("salida", salida)):
    if clave in elegidas or not sirve(inter.get(clave)):
        nueva = str(Path(nueva).expanduser().resolve())
        if inter.get(clave) != nueva:
            print(f"   ·     config.json: interfaz.{clave} {inter.get(clave)!r} -> {nueva!r}")
            inter[clave] = nueva
            cambio = True
    Path(inter[clave]).expanduser().mkdir(parents=True, exist_ok=True)
    print(f"   OK    {clave}: {inter[clave]}")
if cambio:
    config.write_text(json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
[ $? -eq 0 ] || falta "no se pudo ajustar config.json"


paso "6. Lanzador"
chmod +x "Armar post.command" instalar-mac.sh
# Bajado como ZIP desde el navegador, macOS lo marca en cuarentena y pide permiso al abrirlo.
# Clonado con git no trae la marca; sacarla no hace nada en ese caso.
xattr -d com.apple.quarantine "Armar post.command" 2>/dev/null
ok "doble clic en: $DIR/Armar post.command"


paso "7. Pruebas"
LOG="${TMPDIR:-/tmp}/armar-post-probar.log"
"$VPY" probar.py --rapido > "$LOG" 2>&1
grep -E '^   (OK|FALLA|·) ' "$LOG" | sed 's/^/  /'
# En una instalación nueva no hay casamientos cargados: esa falla es la esperada. Los modelos y
# las referencias que falten ya se contaron arriba.
if grep -E '^   FALLA ' "$LOG" | grep -Evq 'no hay casamientos en|faltan modelos|sin referencias.npz'; then
  falta "probar.py encontró problemas (detalle completo en $LOG)"
else
  dato "\"no hay casamientos\" es lo esperado hasta que se agregue el primero desde la página"
  rm -f "$LOG"
fi

# Que la página conteste, en un puerto que no choque con una que ya esté abierta
PUERTO=8799
"$VPY" interfaz.py --no-abrir --puerto "$PUERTO" >/dev/null 2>&1 &
PID=$!
contesta=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 1
  if curl -fsS "http://127.0.0.1:$PUERTO/api/albumes" >/dev/null 2>&1; then contesta=1; break; fi
done
kill "$PID" 2>/dev/null
wait "$PID" 2>/dev/null
if [ "$contesta" = 1 ]; then
  ok "la interfaz levanta y contesta"
else
  falta "la interfaz no contestó en el puerto $PUERTO (probar a mano: .venv/bin/python interfaz.py)"
fi


echo
echo "======================================================================"
if [ ${#FALTAN[@]} -eq 0 ]; then
  echo "Listo. Para abrirlo: doble clic en \"Armar post.command\" o, desde la Terminal,"
  echo "  .venv/bin/python interfaz.py"
  exit 0
fi
echo "Falta:"
for f in "${FALTAN[@]}"; do echo "  - $f"; done
exit 1
