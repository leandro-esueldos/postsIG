# Armar post

Herramienta local que arma posts de Instagram a partir del álbum de un casamiento. Qué hace y cómo
se usa: [README.md](README.md). El plan y las fases: [PLAN.md](PLAN.md).

- **Instalarla en una Mac:** seguir [INSTALAR-MAC-CON-CLAUDE.md](INSTALAR-MAC-CON-CLAUDE.md)
  (`bash instalar-mac.sh` hace casi todo).
- **La raíz del repo es la carpeta `curator/` del proyecto original.** Los `.md` y los mensajes de
  los scripts dicen `python curator/x.py`: acá es `.venv/bin/python x.py`.
- **Las fotos son de clientes.** Nada sale de la máquina. Los derivados (`referencias.npz`,
  `modelo_preferencia.json`, `datos_preferencia.npz`, `casamientos.json`, `correcciones.jsonl`)
  están en `.gitignore` a propósito: no agregarlos nunca a git.
- **`config.json`** está calibrado contra sus posts publicados; las `_nota` explican cada valor.
  Lo único que cambia de una máquina a otra es el bloque `interfaz`.
- Pruebas: `.venv/bin/python probar.py --rapido` (todo) y `.venv/bin/python test_elegidas.py`
  (no necesita fotos ni modelos).
