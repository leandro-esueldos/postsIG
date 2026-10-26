# Instalar Armar post en una Mac con Claude Code

Este archivo es para **Claude Code corriendo en la Mac** donde se va a usar la herramienta. La
versión para hacerlo a mano, con el porqué de cada paso, es [INSTALAR-MAC.md](INSTALAR-MAC.md).

**Para quien lo instala:** abrí Claude Code en la Terminal de la Mac y pegale esto:

```
Instalá Armar post en esta Mac. Cloná https://github.com/leandro-esueldos/postsIG en
~/armar-post y seguí al pie de la letra INSTALAR-MAC-CON-CLAUDE.md. Preguntame lo que
no puedas resolver solo; los archivos entrenados te los paso yo.
```

Tené a mano `referencias.npz`, `modelo_preferencia.json` y `datos_preferencia.npz` (ver paso 3):
no están en git y sin los dos primeros la herramienta no sabe lo que él elige.

---

## Para Claude: qué es esto

Una herramienta local que arma posts de Instagram a partir del álbum de un casamiento: una página
en `http://127.0.0.1:8770` servida por `interfaz.py`, más los scripts de línea de comandos.
Python 3.10+ con cuatro librerías (Pillow, numpy, opencv-python, onnxruntime); sin GPU, sin
cuentas ni servidores.

Reglas que no se negocian:

- **Las fotos son de clientes.** No subirlas, no copiarlas fuera de la Mac, no mandarlas a
  ningún servicio. Tampoco `referencias.npz`, `modelo_preferencia.json`, `datos_preferencia.npz`
  ni `casamientos.json`: son derivados de esas fotos y están en `.gitignore` por eso. Nunca los
  agregues a git.
- **No cambies `config.json` salvo el bloque `interfaz`.** Lo demás está calibrado contra sus
  posts publicados.
- **No instales `mediapipe`** aunque aparezca comentado en `requirements.txt`: trae telemetría y
  va apagado.
- **No uses `sudo pip` ni el Python del sistema.** Todo va en el `.venv` del proyecto.

Los otros `.md` del repo dicen `python curator/...`: en el proyecto original esto vivía en una
carpeta `curator/`. **Acá la raíz del repo es esa carpeta**, así que sacale el `curator/` a los
comandos (`python curator/probar.py` es `.venv/bin/python probar.py`).

---

## 1. Ver la máquina

```bash
uname -m && sw_vers -productVersion && xcode-select -p
```

- `arm64` (Apple Silicon) o `x86_64` (Intel): las dos andan igual.
- macOS 11 o mayor.
- Si `xcode-select -p` da error, **no están las herramientas de línea de comandos** y `git` es un
  señuelo que abre el cartel para instalarlas. Dos salidas, que elige la persona:
  - correr `xcode-select --install` y aceptar el cartel (unos minutos), o
  - bajar el ZIP del repo desde GitHub (*Code → Download ZIP*), descomprimirlo en `~/armar-post`
    y seguir desde el paso 3.

## 2. Clonar

```bash
git clone https://github.com/leandro-esueldos/postsIG.git ~/armar-post
cd ~/armar-post
ls instalar-mac.sh
```

Si el repo es privado y `git clone` pide usuario y contraseña o da 404, hace falta que la persona
se loguee en GitHub (`gh auth login` si está `gh`, o un token personal como contraseña). Pedíselo;
no inventes credenciales.

Si `ls instalar-mac.sh` dice que no existe, el cambio que lo agregó todavía no está en `main`:
`git checkout claude/sweet-edison-01cb1d`.

## 3. Traer lo que no está en git

Van **en la raíz del repo** (`~/armar-post/`, al lado de `curate.py`):

| archivo | ¿hace falta? | si falta |
|---|---|---|
| `referencias.npz` (~700 KB) | **sí** | no se puede regenerar sin los seis álbumes originales |
| `modelo_preferencia.json` (~40 KB) | **sí** | ídem |
| `datos_preferencia.npz` (~15 MB) | recomendado | arma igual, pero *Entrenar* no reemplaza el modelo (para no desaprender) |
| `modelos/` (126 MB) | no | `instalar-mac.sh` los baja solo |

Preguntale a la persona dónde los dejó. Lo habitual es un pendrive, AirDrop (cae en Descargas) o
Drive. Para encontrarlos:

```bash
find ~/Downloads ~/Desktop ~/Documents /Volumes -maxdepth 4 \
  \( -name referencias.npz -o -name modelo_preferencia.json -o -name datos_preferencia.npz \) 2>/dev/null
```

Copialos (no los muevas: que el original quede donde estaba) y verificá que pesen lo de la tabla:

```bash
cp "<carpeta donde están>"/{referencias.npz,modelo_preferencia.json,datos_preferencia.npz} ~/armar-post/
ls -lh ~/armar-post/*.npz ~/armar-post/modelo_preferencia.json
```

Si también trajeron una carpeta `modelos/` con tres o cuatro `.onnx`/`.task`, copiala entera a
`~/armar-post/modelos/` y te ahorrás la descarga. **No hace falta** traer `casamientos.json` ni
`correcciones.jsonl`: guardan rutas de la otra máquina y acá no sirven.

Si la persona todavía no los tiene, seguí igual con el paso 4: queda todo instalado y el script te
dice al final que faltan. Avisale que la herramienta no arma posts útiles hasta que estén.

## 4. Correr el instalador

```bash
cd ~/armar-post
bash instalar-mac.sh
```

Hace solo, y se puede correr las veces que haga falta (lo ya hecho lo saltea):

1. busca un Python 3.10+ (prefiere 3.12) que no sea el señuelo de `/usr/bin/python3`;
2. arma `.venv/` e instala `requirements.txt` (~150 MB);
3. baja los modelos a `modelos/` si no están (126 MB, de GitHub y HuggingFace);
4. revisa los archivos del paso 3;
5. si `config.json` apunta a la `D:/` de Windows, cambia **sólo** `interfaz.albumes` y
   `interfaz.salida` a `~/ArmarPost/casamientos` y `~/ArmarPost/posts`, y crea esas carpetas;
6. hace ejecutable `Armar post.command` y le saca la cuarentena de macOS;
7. corre `probar.py --rapido` y levanta la interfaz un momento para ver que conteste.

Termina en `0` si quedó todo listo, o en `1` con una lista de lo que falta.

Si la persona quiere otras carpetas (por ejemplo un disco externo para los álbumes, que pesan
varios GB cada uno), pasáselas:

```bash
bash instalar-mac.sh --albumes "/Volumes/Fotos/casamientos" --salida ~/ArmarPost/posts
```

### Qué hacer con cada falta

| lo que dice | qué hacer |
|---|---|
| `FALTA Python 3.10 o mayor` | si hay Homebrew: `brew install python@3.12` (pedí permiso antes). Si no, el instalador de python.org lo tiene que correr la persona (pide la contraseña de la Mac): **https://www.python.org/downloads/macos/** → *macOS 64-bit universal2 installer* de la última 3.12. Después cerrar y abrir la Terminal y volver a correr el script |
| `no se instalaron las librerías` | mirar el error de `pip` arriba. Si está compilando algo ("Building wheel"), el Python no es universal2 o es muy nuevo para `onnxruntime`: instalar 3.12 y borrar `.venv` |
| `no se pudieron bajar los modelos` | reintentar una vez (son descargas grandes); si sigue, pedirle a la persona la carpeta `modelos/` de la otra máquina |
| `referencias.npz` / `modelo_preferencia.json` | el paso 3 |
| `probar.py encontró problemas` | leer el log que nombra. *"no hay casamientos"* **no** es un problema: es lo esperado en una instalación nueva |
| `la interfaz no contestó` | correr `.venv/bin/python interfaz.py --no-abrir` a mano y leer el error. `Address already in use`: ya hay una abierta, o cambiar `interfaz.puerto` en `config.json` |

## 5. Lo que tiene que hacer la persona

Esto son clics en la pantalla y no los podés hacer vos. Explicáselos y esperá a que confirme:

1. **Abrir la herramienta**: doble clic en `~/armar-post/Armar post.command` (en el Finder,
   `open ~/armar-post`). Se abre una Terminal y el navegador en la página. Mientras esa Terminal
   esté abierta, la página anda; cerrarla la apaga. Si macOS dice que es de un desarrollador no
   identificado: clic derecho → Abrir → Abrir (una sola vez).
2. **Dejarlo a mano**: arrastrar `Armar post.command` al Dock, o clic derecho → *Crear alias* y
   llevar el alias al Escritorio. Un alias del Finder, no un enlace simbólico con `ln -s`.
3. **El diálogo de carpetas**: en la página, *Agregar casamiento…*. Tiene que aparecer el selector
   del Finder. La primera vez que lea fotos de Escritorio, Documentos, Descargas o un disco
   externo, macOS pregunta si la Terminal puede acceder: **hay que darle OK**. Si se le dio que no:
   *Ajustes del Sistema → Privacidad y seguridad → Archivos y carpetas*. Si el selector no abre,
   la página ofrece pegar o arrastrar la carpeta.

Si la persona tiene un álbum para probar (una carpeta de **JPEG ya revelados**, no RAW), que lo
agregue y toque *Armar el post*. La primera vez tarda unos minutos y muestra lo que va haciendo.

## 6. Cerrar

Pasale a la persona un resumen corto:

- dónde quedó instalado (`~/armar-post`) y cómo se abre (doble clic en **Armar post**);
- dónde busca casamientos y dónde deja los posts (las rutas que imprimió el paso 5 del script);
- qué faltó, si faltó algo, y qué tiene que hacer para completarlo;
- que el uso del día a día está en la sección 9 de [INSTALAR-MAC.md](INSTALAR-MAC.md).

No hagas commits desde la Mac: `config.json` queda con las rutas de esta máquina y eso es local.

## Actualizar más adelante

```bash
cd ~/armar-post
git stash          # guarda las rutas locales de config.json
git pull
git stash pop
bash instalar-mac.sh
```

Si `git stash pop` da conflicto en `config.json`, quedate con la versión nueva del repo
(`git checkout HEAD -- config.json && git stash drop`) y volvé a correr el instalador con las
mismas `--albumes` / `--salida` de antes: vuelve a poner las rutas.
