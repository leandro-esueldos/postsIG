# Instalar Armar post en la Mac de Diego

Todo corre local: no hay cuenta, no hay servidor, no hay nada que pagar. Las fotos de sus clientes
no salen de su disco. La única vez que necesita internet es para bajar Python y las librerías.

Tiempo: **20–30 minutos**, casi todo esperando descargas.

---

## 0. Antes de salir de tu máquina

La carpeta `curator/` tiene archivos que **no están en git** y que hay que llevar sí o sí,
porque son lo que la herramienta aprendió de los seis casamientos:

| archivo | qué es |
|---|---|
| `referencias.npz` (708 KB) | las 377 fotos que publicó, descriptas por CLIP |
| `modelo_preferencia.json` (40 KB) | el modelo entrenado |
| `datos_preferencia.npz` (~15 MB) | los ejemplos con que se entrenó el modelo, para que el botón *Entrenar* de la Mac sume a lo aprendido en vez de empezar de cero |
| `modelos/` (126 MB) | CLIP, YuNet y SFace |

`datos_preferencia.npz` es nuevo: se genera corriendo una vez, en la máquina que tiene los seis
álbumes, `python curator/entrenar.py --modelo --albumes <los seis>` con esta versión. Sin él la Mac
arma los posts igual, pero *Entrenar* no reemplaza el modelo (para no desaprender) y lo avisa.

`modelos/` se puede bajar solo allá (paso 4), pero si lo copiás te ahorrás la descarga y el riesgo
de que alguna URL falle. Los otros **no se pueden regenerar sin los álbumes**, así que van sí o sí.

Llevá la carpeta del proyecto entera (con `modelos/` adentro son ~130 MB) en un pendrive, por
AirDrop o por Drive. No hace falta `curator/salida/` ni `__pycache__/`.

---

## 1. Ver qué Mac es

En la Terminal de la Mac (Spotlight con `⌘ + espacio`, escribir "Terminal"):

```bash
uname -m && sw_vers -productVersion
```

`arm64` es Apple Silicon (M1/M2/M3/M4), `x86_64` es Intel. **Las dos andan** y no hace falta
cambiar nada; anotalo por las dudas. Si la versión de macOS es 11 o mayor, estamos bien.

---

## 2. Instalar Python 3.12

macOS ya **no trae** Python: el `python3` que aparece es un señuelo que dispara la instalación de
las herramientas de Xcode (más de 1 GB). Mejor instalarlo derecho.

Bajá el instalador oficial: **https://www.python.org/downloads/macos/** → "macOS 64-bit universal2
installer" de la última 3.12. Doble clic al `.pkg` y Siguiente hasta el final.

Verificá:

```bash
python3 --version
```

Tiene que decir `Python 3.12.x`. Si dice 3.9 o menos, cerrá la Terminal, abrila de nuevo y probá
con `python3.12 --version`.

<details>
<summary>Alternativa con Homebrew, si ya lo tenés</summary>

```bash
brew install python@3.12
```
</details>

---

## 3. Copiar el proyecto e instalar las librerías

Dejá la carpeta en un lugar estable, por ejemplo `~/armar-post/`. Después:

```bash
cd ~/armar-post
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r curator/requirements.txt
```

Baja cuatro paquetes (Pillow, numpy, opencv-python, onnxruntime), unos 150 MB. Si `pip` tarda
mucho en "Building wheel", cortá con Ctrl+C y probá de nuevo: con Python 3.12 universal2 hay wheels
compilados para las dos arquitecturas y no debería compilar nada.

Comprobá que las cuatro cargan:

```bash
.venv/bin/python -c "import PIL, numpy, cv2, onnxruntime; print('todo ok')"
```

---

## 4. Los modelos

Si copiaste `curator/modelos/` ya está. Si no:

```bash
.venv/bin/python curator/curate.py --modelos
```

Baja 126 MB de GitHub y HuggingFace. Verificá que quedaron tres archivos:

```bash
ls -lh curator/modelos/
```

---

## 5. Decirle dónde dejar los posts

Abrí `curator/config.json` y cambiá **sólo** el bloque `interfaz`, que hoy apunta a un disco
`D:` de Windows:

```json
  "interfaz": {
    "albumes": "/Users/diego/ArmarPost/casamientos",
    "salida": "/Users/diego/ArmarPost/posts",
    "puerto": 8770
  }
```

Cambiá `diego` por el nombre de usuario real (lo dice `whoami`). Sin espacios en el nombre de
la carpeta: se lo agradecés después, cada vez que tengas que escribir la ruta. Creá las dos:

```bash
mkdir -p ~/ArmarPost/casamientos ~/ArmarPost/posts
```

- `albumes` es opcional: lo que haya ahí adentro aparece solo en la lista. Igual Diego va a sumar
  los casamientos desde la página, y ésos pueden estar en cualquier disco.
- `salida` es donde quedan los posts listos para subir. Que sea una carpeta que él encuentre.

Si te olvidás de este paso no se rompe nada: al no existir `D:` en macOS, la herramienta usa carpetas
por omisión adentro del proyecto y lo avisa al arrancar.

---

## 6. Probar que anda

```bash
.venv/bin/python curator/probar.py --rapido
```

Tiene que decir que las librerías están, los modelos están y que hay **377 fotos publicadas de 6
casamientos**. Esa última línea es la que confirma que `referencias.npz` viajó bien. Como todavía
no hay casamientos cargados, va a avisar que no hay nada que armar: es lo esperado.

---

## 7. Dejarlo listo para él

Hacé ejecutable el lanzador (copiarlo desde Windows le saca el permiso):

```bash
chmod +x "curator/Armar post.command"
```

Y arrastralo al Dock, o hacele un alias en el Escritorio (clic derecho → Crear alias).

**Doble clic y listo**: abre una ventana de Terminal y el navegador en la página.
Mientras esa ventana esté abierta, la página funciona; cerrarla la apaga.

La **primera vez** macOS va a decir que no puede abrirlo porque viene de un desarrollador no
identificado. **Clic derecho sobre el archivo → Abrir → Abrir.** Se pregunta una sola vez.

---

## 8. Los permisos de macOS (importante)

La primera vez que la herramienta lea fotos que estén en Escritorio, Documentos, Descargas o un disco
externo, macOS muestra un cartel del tipo *"Terminal quiere acceder a archivos de tu carpeta
Documentos"*. Hay que darle **OK**. Si por error se le da que no, se arregla en
**Ajustes del Sistema → Privacidad y seguridad → Archivos y carpetas**.

Probá antes de irte que el diálogo de elegir carpeta abre bien:

```bash
osascript -e 'activate' -e 'POSIX path of (choose folder with prompt "prueba")'
```

Tiene que aparecer el selector del Finder. Si no aparece, no es grave: la página tiene un plan B
para pegar o arrastrar la carpeta a mano.

---

## 9. Cómo lo usa Diego (esto es lo que hay que explicarle)

1. Doble clic en **Armar post**.
2. **Agregar casamiento…** → elegir la carpeta con los JPG ya revelados. *No se copia nada*: las
   fotos se quedan donde están.
3. **Armar el post**. La primera vez tarda unos minutos y va mostrando qué está haciendo.
4. Mirar las 20 slides. Tocar cualquiera para ver sus fotos, cambiarla por otra de ese momento del
   día, dejarla sola o sacarla del post.
5. **Aplicar y rehacer el post** (segundos).
6. **Abrir la carpeta de slides** → subir `01.jpg`, `02.jpg`… en ese orden.

Requisito del álbum: **JPEG ya revelados**, la misma exportación que le entrega a los novios. RAW
no, y con los metadatos de fecha intactos (si se los borró la exportación, la herramienta avisa).

---

## Cuánto va a tardar en su máquina

En una laptop Intel de 8 hilos, un álbum de 1.300 fotos tarda **~6 minutos** la primera vez y **25
segundos** cada vez que se vuelve a correr. En una Mac de edición de video (M-series con 10+
núcleos) debería andar bastante más rápido: el grueso del tiempo es leer los JPEG y generar las
miniaturas, o sea CPU y disco, que es justo lo que esas máquinas tienen de sobra. No usa GPU.

Lo que ocupa: ~200 MB de caché por álbum (miniaturas y descriptores, adentro de una carpeta oculta
`.curator/` en el mismo álbum) y ~22 MB por post. Se puede borrar y se regenera.

---

## Si algo falla

| síntoma | qué pasa |
|---|---|
| `command not found: python3` | Python no se instaló o falta reabrir la Terminal |
| el navegador dice que no puede conectar | no está abierto: doble clic en `Armar post.command` |
| `Address already in use` | ya hay uno abierto, o cambiá `puerto` en `config.json` |
| la lista de casamientos sale vacía | normal si todavía no agregó ninguno: **Agregar casamiento…** |
| "esa carpeta no tiene fotos JPEG adentro" | eligió la carpeta madre; hay que elegir la que tiene los JPG directamente |
| el post sale con menos de 20 slides | el álbum tiene poco material en alguna parte del día; la herramienta lo dice en pantalla y prefiere un post más corto |
