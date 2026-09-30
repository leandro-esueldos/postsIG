#!/bin/bash
# Doble clic para abrir Armar post. Deja una ventana de Terminal abierta: mientras esté abierta,
# la página funciona. Para cerrarlo, cerrar esa ventana (o Ctrl+C).
#
# La primera vez, macOS pide permiso para ejecutarlo. Si dice que no se puede abrir porque
# viene de un desarrollador no identificado: clic derecho sobre el archivo -> Abrir -> Abrir.

cd "$(dirname "$0")/.." || exit 1

# El python del entorno del proyecto si está, si no el del sistema
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  echo "No encontré Python. Instalalo con:  brew install python@3.12"
  echo "(o desde python.org). Después volvé a abrir este archivo."
  read -r -p "Enter para cerrar..." _
  exit 1
fi

echo "Abriendo Armar post…"
exec "$PY" curator/interfaz.py
