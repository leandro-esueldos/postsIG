# Armar post

De la carpeta de un casamiento a una selección para Instagram, sin publicar nada: Diego mira
una hoja de contacto, aprueba o cambia, y sube él desde el celular.

El plan completo y las fases que faltan están en [PLAN.md](PLAN.md). Para dejarlo instalado en
la Mac de Diego, [INSTALAR-MAC.md](INSTALAR-MAC.md).

## Uso

**La forma más cómoda: la interfaz.**

```bash
python curator/interfaz.py          # Windows y Linux
```

En macOS, doble clic en `curator/Armar post.command` (la primera vez, clic derecho → Abrir →
Abrir, porque no está firmado).

Abre una página en el navegador —sólo en esta máquina, las fotos no salen de acá—. Desde ahí:

- **Agregar casamiento…** abre el diálogo de carpetas del sistema (Finder o Explorador) y suma la
  carpeta a la lista. **La carpeta no se copia**: queda donde está y acá se guarda la ruta, porque
  un álbum pesa varios GB. La lista vive en `curator/casamientos.json`; *quitar de la lista* la
  saca de ahí y no borra ni una foto. Si el diálogo del sistema no abriera, la página ofrece un
  campo para pegar o arrastrar la carpeta.
- **Armar el post** corre el análisis mostrando la consola en vivo.
- Tocando una slide se ven sus fotos y las alternativas de ese momento del día, y se cambia lo que
  haga falta. Cada cambio se aplica y el post se rehace en segundos.
- **Abrir la carpeta de slides** deja los JPG numerados adelante, listos para subir en ese orden.

También se puede dejar una carpeta con todos los casamientos adentro y apuntarle `interfaz.albumes`
en `config.json`: los que estén ahí aparecen solos, sin agregarlos uno por uno. `interfaz.salida`
es dónde quedan los posts. Si el `config.json` viene de otra máquina y la ruta no existe en ésta
(por ejemplo `D:/...` abierto en una Mac), se usa la carpeta por omisión en vez de crear basura.

**Sin interfaz:** en Windows, arrastrar la carpeta del casamiento sobre `armar-post.bat`. En
cualquier sistema, `python curator/curate.py "<carpeta>" --out "<salida>"`.

Los pasos, del casamiento al post:

1. Exportar el álbum revelado a JPEG en una carpeta (lo mismo que se entrega).
2. Opcional: adentro, una carpeta `novios/` con 3 o 4 fotos de ellos. La herramienta la ignora como
   material y la usa para reconocerlos.
3. Arrastrar la carpeta sobre `armar-post.bat`. Tarda unos minutos la primera vez.
4. Mirar `post.jpg`. Si está bien, subir `slides/01.jpg`, `02.jpg`… en ese orden.
5. Si algo no gusta, escribir en `cambios.txt` y volver a arrastrar. Tarda segundos:

```
7 DSC_01234     la slide 7 pasa a ser esa foto
12 fuera        se saca la slide 12
3 sola          la slide 3 va sola, sin collage
```

Lo que no se tocó no se mueve: pedir "la 5 sola" no muda el collage a otra slide, y volver a armarlo
sin pedir nada devuelve el mismo post. Cada foto que se cambia queda registrada en
`correcciones.jsonl` como "sacó ésta, puso aquélla": es el dato más directo que existe sobre qué
elige él, y el que va a hacer que el modelo de preferencia mejore sin tener que esperar a que
publique otro casamiento.

**Desde la terminal:**

```bash
python curator/curate.py "D:/bodas/martina-y-juan"
```

Para que además reconozca a los novios, una carpeta con tres o cuatro fotos donde salgan ellos:

```bash
python curator/curate.py "D:/bodas/martina-y-juan" --novios "D:/bodas/martina-y-juan/novios"
```

No hace falta decir cuál es cuál ni recortar las caras: las agrupa solas. Con una sola foto de
referencia alcanza.

Opciones:

```
--out CARPETA     dónde dejar el resultado (por defecto curator/salida/<álbum>)
--novios CARPETA  fotos de referencia de los novios
--top N           cuántos momentos entran en la hoja de contacto (120)
--orden hora|tecnica   cómo se ordena la hoja (por defecto cronológico)
--workers N       hilos (8)
--modelos         baja los modelos de cara y sale
--sin-montaje     elige las slides pero no las arma (más rápido para probar parámetros)
```

El álbum tiene que estar **exportado a JPEG y ya revelado**. Los RAW se saltean con un aviso:
además de lentos, el revelado es justamente lo que define su estilo.

## Qué deja

En la carpeta de salida:

- `slides/01.jpg …` — **las slides listas para subir**: 1080×1350, sRGB, calidad 95.
- `post.jpg` — el carrusel completo de un vistazo.
- `cambios.txt` — donde se escriben los cambios. Se crea solo, con las instrucciones.
- `seleccion.jpg` — las fotos elegidas, numeradas por slide, con su capítulo.
- `seleccion.json` — qué entró, en qué slide, de qué capítulo y por qué.
- `suplentes.jpg` — las que quedaron afuera por poco, por capítulo, para cambiar alguna.
- `contacto.jpg` — la mejor foto de cada momento, con su puntaje, paginado de a 36.
- `analisis.json` — todo lo medido, foto por foto.

En el álbum, una carpeta oculta `.curator/` con las miniaturas y el índice. Es el caché: borrarlo
sólo cuesta tiempo, no datos. Volver a correr sobre un álbum ya procesado tarda segundos.

## Cómo elige

1. **Miniaturas** de 1024 px, cacheadas. Todo el análisis corre sobre eso.
2. **Filtro técnico**: nitidez de la zona más nítida de la foto, y exposición juzgada por dónde
   cae el grueso del histograma. Los umbrales están calibrados contra las fotos que él ya
   publicó — ver `test_calibracion.py`.
3. **Agrupado de repetidas**: hora de captura + hash perceptual. Las 3 a 15 tomas de la misma
   escena quedan en un grupo y sale la mejor. Es el recorte más grande del pipeline.
4. **Caras**: cuántas hay y de qué tamaño (que clasifica la foto en retrato, pareja, grupo,
   lejos o detalle), cómo está expuesta la cara, y —si se pasó `--novios`— si están ellos.
5. **Preferencia**: cuánto se parece el *contenido* de la foto a lo que él publicó en otros
   casamientos (CLIP), más la señal de que publica fotos con menos gente. **Es lo que ordena.**
   El puntaje técnico y el de caras quedan como puerta: una foto rota no entra por mucho que se
   parezca a lo suyo.
6. **Capítulos**: corta el día en bloques por las pausas reales entre fotos y les pone nombre
   (preparativos, ceremonia, retratos, fiesta).
7. **Guion**: reparte las slides a lo largo del día, proporcional a cuántas fotos hay de cada
   parte, y dentro de cada tramo elige la que más aporta sin repetir imágenes parecidas.
8. **Montaje**: las verticales van solas a sangre, las apaisadas en collage, y lo que no se
   puede recortar sin cortar gente va entero sobre blanco. Todo se renderiza desde los
   originales y se pasa a sRGB.

Falta: el borrador de caption y los proveedores a etiquetar (fase 6).

## El montaje

Las plantillas no se inventaron: se midieron al píxel sobre los cinco collages que él publicó
—grilla, apilado, mosaico, detalles y polaroid—, con su color de fondo, margen y separación. Ver
`TEMPLATES` en `lib/montage.py` y la tabla en `PLAN.md`.

- **Recorte sobre el sujeto.** Con caras, abarca a todas las principales: centrar en la más grande
  le corta la cabeza al otro novio. Sin caras, se centra en la zona más nítida.
- **No corta gente por su cuenta.** Si el 4:5 deja afuera más del 5 % de las caras, la foto va
  entera sobre blanco, como hace él.
- **Verticales solas, apaisadas en collage.** Es lo que se ve en sus posts: en MJ las 3 fotos que
  publicó sueltas son verticales y las 51 apaisadas están todas en collages.
- **Collages del mismo tramo.** Las compañeras salen de los 45 minutos alrededor de la principal,
  por puntaje, y ninguna demasiado parecida a otra: sus collages cuentan una parte del día
  (mediana 28 minutos) con fotos que se parecen poco entre sí.
- **Colores.** Todo sale en sRGB con el perfil embebido: si exporta en Adobe RGB, se convierte.

```bash
python curator/test_montaje.py curator/salida/<boda>
```

Verifica sobre una salida real: un JPG por slide, todos 1080×1350, todos con perfil sRGB,
ninguna cara cortada en las slides solas, ninguna foto repetida, y collages completos.

## El guion

Sobre un álbum real de 1018 momentos, las veinte mejores por puntaje salen de **5 bloques** del
día; el guion toca **16** y cubre el 96 %. Ése es todo el punto: sin reparto, gana siempre el rato
con mejor luz.

El reparto es proporcional al día —cuántas slides por tramo según cuántas fotos hay de cada
parte—, que es lo que hace él: en MJ publicó a lo largo de todo el casamiento, con más peso al
principio y al final. Los cupos fijos por capítulo de la primera versión dejaban horas enteras sin
ninguna foto.

Dentro de cada tramo entra la que más aporta, no la que más puntaje tiene: cada candidata se juzga
por su puntaje menos cuánto se parece a las ya elegidas (con CLIP). Sin eso, los seis retratos son
seis veces el mismo retrato.

Todo se configura en `config.json` (`post.reparto`, `post.slides`, `post.apertura`). Los nombres de
los capítulos también: el corte del día no depende de cómo se llamen.

```bash
python curator/test_guion.py curator/salida/<boda>
```

Verifica las propiedades del guion sobre una salida ya generada: nada repetido, todos los
capítulos presentes, cobertura del día, ventaja contra el ranking puro, y orden cronológico.

## Probar que todo anda

```bash
python curator/probar.py            # cura todos los casamientos y revisa todo
python curator/probar.py --rapido   # sólo revisa lo ya armado
```

Verifica el entorno (librerías, modelos, entrenamiento), la calibración contra sus publicadas,
que cada casamiento corra de punta a punta, que volver a armarlo sin pedir cambios no le mueva
nada, las propiedades del guion y del montaje de cada post, la comparación contra lo que él
publicó donde haya verdad, y cuánto acierta en un casamiento que no vio. Termina con un resumen y
devuelve 0 si pasó todo. Con los siete casamientos de prueba son **34 verificaciones** y tarda unos
cuatro minutos, porque el análisis de los siete ya está cacheado. Un álbum nuevo de 1.300 fotos
tarda unos 6 minutos la primera vez (medido en una laptop Intel de 8 hilos, sin GPU) y 25
segundos cada vez que se vuelve a correr.

## Entrenar y medir con casamientos reales

```bash
python curator/verdad.py "D:/bodas/MJ" "D:/bodas/MJ_IG" --revisar     # qué fotos usó en cada slide
python curator/entrenar.py --posts "D:/bodas/posts" --albumes "D:/bodas/MJ" ... --modelo
python curator/evaluar.py "D:/bodas/MJ" curator/salida/MJ              # cuánto se parece a lo suyo
```

- **`verdad.py`** encuentra, en el álbum, las fotos de cada slide que él publicó —también las de
  los collages, recortadas o en blanco y negro— por coincidencia de puntos (SIFT). Deja
  `publicadas.json` en el caché del álbum y, con `--revisar`, una hoja para chequear a ojo.
- **`entrenar.py`** arma `referencias.npz`: un embedding CLIP por cada foto que publicó, sacada de
  sus posts (celda por celda) y de los álbumes etiquetados. La herramienta puntúa cada foto de un
  casamiento nuevo por cuánto se parece a eso. Las referencias del mismo casamiento se excluyen.
  Con `--modelo` entrena además `modelo_preferencia.json`, una regresión sobre esos embeddings con
  los positivos y negativos de cada casamiento etiquetado: es lo que ordena en un casamiento nuevo.
  Si el álbum que se está armando participó del entrenamiento, **no** usa el modelo y
  cae al parecido por vecinos, para no copiarse la respuesta.
- **`evaluar.py`** compara un post armado contra lo que él publicó: AUC de cada puntaje,
  toma dentro de cada ráfaga, coincidencia por foto/ráfaga/momento, y reparto por capítulo.
  Cada número lleva su azar al lado.
- **`validacion.py`** es la prueba que importa: saca un casamiento entero del entrenamiento y mide
  sobre él, uno por uno. Sin eso, la herramienta se estaría copiando la respuesta.

```bash
python curator/validacion.py
```

Con seis casamientos etiquetados (205 fotos publicadas sobre 6.658 momentos), dejando cada uno
afuera del entrenamiento:

| qué ordena | AUC (0.5 = tirar la moneda) |
|---|---|
| el puntaje técnico solo | 0.53 |
| parecido de contenido con los otros cinco | **0.67** |
| modelo entrenado sobre CLIP, por momento | **0.76** |

Con dos casamientos esto daba 0.61 y 0.66: **cada casamiento etiquetado que se sume mejora el
resultado**, y es lo más barato que se puede hacer para que elija mejor.

El resto de lo que salió del material real está en `PLAN.md`. Lo más importante: la técnica no
separa nada en un álbum entregado —ya viene elegido por él y revelado parejo—, lo que separa es el
contenido, y él no publica el día en la proporción en que lo fotografía (58 % de los preparativos
contra 36 % del álbum; 22 % de la fiesta contra 47 %). Eso último se corrige con `post.sesgo`.

## El modelo de estilo (fase 3, reemplazado)

Quedó reemplazado por la preferencia con CLIP: sobre un álbum real dio AUC 0.52. Se sigue
calculando con peso 0 por si sirve de comparación.

```bash
python curator/train_estilo.py --evaluar
python curator/train_estilo.py --descartadas "D:/boda/no-publicadas"
```

Se arma con las fotos que él publicó (`raw/photos`) y puntúa por cercanía a las tres más
parecidas, no al promedio de todas: lo que publica no es una sola cosa —drone sobre viñedos,
macro de anillos, blanco y negro de ceremonia, caos de fiesta— y un modelo del "centro" premiaría
un promedio que no se parece a nada suyo.

**Todavía no sirve para ordenar, y está medido.** Con dos controles y sacando la foto madre del
conjunto de referencia para que no haya fuga:

| control | qué es | AUC |
|---|---|---|
| recortes de sus propias fotos | mismo contenido y revelado, otro encuadre | **0.549** |
| cuadros de sus reels | su material, momentos que no eligió | 0.887 |

0.5 es azar. El 0.887 está confundido por el formato: los cuadros son apaisados y sus fotos 4:5,
y sacando ese rasgo cae a 0.778. Se probaron siete grupos de rasgos definidos de antemano y
ninguno pasa de 0.56 contra los recortes, así que no es cuestión de elegirlos mejor.

Por eso `config.json` lo deja en `"peso": 0`. Para que empiece a servir hacen falta **descartes**:
las fotos de un casamiento que él no eligió. Con eso `--descartadas` pesa cada rasgo por cuánto
separa y el modelo pasa de medir "parecido a lo suyo" a medir "cuál de éstas elegiría".

## Las marcas de la hoja de contacto

```
RET PAR GRU LEJ DET   retrato · pareja · grupo · gente lejos · detalle sin caras
♥ ♥♥                  cuántos de los novios están en la foto
OJOS                  alguien cerró los ojos
BN                    blanco y negro
x4                    la ráfaga tenía 4 tomas; ésta es la que quedó
```

## Control de calibración

```bash
python curator/test_calibracion.py
```

Corre el puntaje sobre `raw/photos` (sus fotos con más "me gusta", las baja
`scripts/download_raw.py`) y falla si alguna quedaría castigada. Son el piso de lo publicable:
si una de esas cae, el umbral está mal, no la foto.

## Cuánto tarda

Medido sobre un álbum de prueba de 3.444 fotos, 8 hilos:

| | |
|---|---|
| primera corrida, sin caras | 2 min 30 s |
| primera corrida, con caras | 5 min 20 s |
| corridas siguientes (todo cacheado) | **5,8 s** |
| espacio del caché | ~1,5 % del álbum |

Por eso conviene probar parámetros: cambiar un umbral y volver a mirar cuesta segundos.

## Lo que se midió, y no se inventó

Los números del filtro técnico salieron de comparar sus 24 publicadas contra tomas arruinadas
a propósito:

| | sus publicadas | arruinadas |
|---|---|---|
| mediana de luz | 37 a 188 | 233, 245, 255 |
| percentil 95 | 172 a 255 | 15, 16, 17 |
| nitidez (mejor mosaico, 10×10) | desde 1147 | hasta 4 |

De ahí salen las rampas de `lib/quality.py`. La grilla de nitidez pasó de 6×6 a 10×10 porque con
la gruesa sus retratos cerrados —lo único nítido son los ojos— quedaban en cero.

El umbral de foto repetida salió de medir distancias de Hamming sobre el álbum de prueba, donde
se sabe qué toma pertenece a qué escena:

| | mediana | la más parecida |
|---|---|---|
| tomas de la misma ráfaga | 3 | — (el 91 % cae en 8 o menos) |
| fotos realmente distintas | 32 | 10, sobre 57.557 pares |

El umbral va en 8: queda a dos bits de la foto distinta más parecida que se haya visto.

El umbral de ojos cerrados y el de reconocimiento salieron igual, de medir sobre material suyo:

| | |
|---|---|
| parpadeo en sus publicadas | mediana 0.28, máximo 0.74 → umbral en **0.85** |
| misma boda, similitud de cara | 0.685 a 0.795 |
| bodas distintas | mediana 0.199, máximo 0.364 → umbral en **0.50** |

El de reconocimiento quedó bastante arriba del 0.363 que recomienda OpenCV, que con estos datos
deja pasar un falso. Probado con una sola foto de referencia contra un álbum de 24 parejas:
encontró las 5 fotos de esa pareja y ninguna ajena.

**Limitación conocida:** el agrupado encadena. Si A se parece a B y B a C, los tres caen en el
mismo grupo aunque A y C no se parezcan, y se puede perder un momento. Con material real es
raro; cuando pasa, el grupo queda enorme y la herramienta lo avisa por pantalla.

**Limitación conocida:** en las fotos **sin cara**, la exposición se mide sobre el histograma
global, así que una con la mitad quemada y la otra mitad oscura promedia bien y pasa. Medirlo por
regiones se probó y se descartó: el umbral que la detectaba también marcaba sus propios collages
sobre fondo blanco. En las fotos con cara ya no pasa: ahí se mide sobre la cara.

**El umbral de ojos cerrados está calibrado de un solo lado.** Se sabe que ninguna de sus
publicadas pasa de 0.74 y el umbral quedó en 0.85, pero falta un álbum real con parpadeos de
verdad para confirmar que no se queda corto.
