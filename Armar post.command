#!/bin/bash
# Doble clic para abrir Armar post. Deja una ventana de Terminal abierta: mientras esté abierta,
# la página funciona. Para cerrarlo, cerrar esa ventana (o Ctrl+C).
#
# La primera vez, macOS pide permiso para ejecutarlo. Si dice que no se puede abrir porque
# viene de un desarrollador no identificado: clic derecho sobre el archivo -> Abrir -> Abrir.

# Este archivo vive al lado de interfaz.py. El entorno de Python puede estar en esta misma carpeta
# (el repo clonado, lo que deja instalar-mac.sh) o en la de arriba (la carpeta curator/ adentro
# del proyecto, como en INSTALAR-MAC.md).
cd "$(dirname "$0")" || exit 1

if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif [ -x "../.venv/bin/python" ]; then
  PY="../.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "No encontré Python. Instalalo con:  brew install python@3.12"
  echo "(o desde python.org). Después volvé a abrir este archivo."
  read -r -p "Enter para cerrar..." _
  exit 1
fi

echo "Abriendo Armar post…"
exec "$PY" interfaz.py
