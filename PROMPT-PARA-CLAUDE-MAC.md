# Prompt para instalar Armar post en una Mac con Claude Code

1. En la Mac, abrí la **Terminal** (`⌘ + espacio`, escribir "Terminal") y arrancá Claude Code con
   `claude`.
2. Tené a mano los archivos entrenados, que **no están en el repo**: `referencias.npz`,
   `modelo_preferencia.json` y `datos_preferencia.npz` (en un pendrive, por AirDrop o en Drive).
   Sin los dos primeros se instala igual, pero la herramienta no sabe qué elige Diego.
3. Copiá el texto del recuadro de abajo, entero, y pegáselo a Claude.

Claude te va a ir pidiendo lo que no puede hacer solo: dónde dejaste los archivos, permisos, y
algunos clics en la pantalla.

---

```
Quiero instalar "Armar post" en esta Mac. Es una herramienta local en Python que arma
posts de Instagram a partir de álbumes de casamiento. Todo corre en esta máquina.

1. Cloná el repo en ~/armar-post, en la rama claude/sweet-edison-01cb1d:

     git clone -b claude/sweet-edison-01cb1d https://github.com/leandro-esueldos/postsIG.git ~/armar-post

   Si esa rama ya no existe, cloná main (sin el -b).
   Si git no está instalado (macOS ofrece instalar las herramientas de Xcode), o si el
   repo pide usuario y contraseña, frená y preguntame cómo seguir.

2. Leé ~/armar-post/INSTALAR-MAC-CON-CLAUDE.md y seguilo al pie de la letra. Ahí está
   todo: qué archivos traer y dónde van, el instalador (bash instalar-mac.sh), qué hacer
   si algo falla y qué tengo que hacer yo con clics.

3. Las fotos y los archivos entrenados (referencias.npz, modelo_preferencia.json,
   datos_preferencia.npz) son datos de clientes: no los subas a ningún lado ni los
   agregues a git. Cuando los necesites, preguntame dónde los dejé.

4. No hagas commits ni push desde esta Mac.

5. Al terminar, decime en pocas líneas qué quedó andando, cómo lo abro, dónde quedan los
   posts y si falta algo.
```
