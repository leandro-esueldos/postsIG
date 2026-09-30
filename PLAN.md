# Armar post · plan

Herramienta local que convierte **la carpeta de un casamiento** (2.000–4.000 fotos) en
**un post de 15–20 slides al estilo de Diego**, con los collages ya armados, para que él lo
suba a mano desde el celular.

## Alcance

Adentro:

- Elegir las fotos: filtro técnico, descarte de repetidas, ranking por *su* estilo.
- Ordenarlas con criterio narrativo (preparativos → ceremonia → retratos → fiesta).
- Armar las slides: recorte 4:5 centrado en las caras y collages con su lenguaje visual.
- Dejarle una hoja de contacto para aprobar o cambiar en dos minutos.

Afuera por ahora (decisión del 17/09/2026):

- Publicación automática en Instagram — sube él, le lleva poco tiempo.
- Respuestas automáticas de mensajes y DMs.
- Reels y edición de video — le alcanza con subir el highlight.

Como sube a mano desde la app, **el límite de slides es 20** (el de 10 es de la API, no aplica).
Y como una slide puede ser un collage de 2 a 6 fotos, un post de 20 slides muestra 40–60 fotos
sin que se sienta largo.

## Qué deja cada corrida

```
salida/<boda>/
  slides/01.jpg …     las slides listas, 1080x1350, sRGB, en orden        ← lo que sube
  post.jpg            el carrusel completo de un vistazo                  ← lo que mira
  cambios.txt         donde escribe lo que quiere cambiar                 ← lo que edita
  seleccion.jpg       las fotos elegidas, numeradas por slide
  suplentes.jpg       las que quedaron afuera por poco, por capítulo
  contacto.jpg        todos los momentos del casamiento, con puntaje
  seleccion.json      qué entró, en qué slide, con qué plantilla y por qué
  analisis.json       todo lo medido, foto por foto
```

Pendiente: `caption.txt` con el borrador de texto y los proveedores (fase 6).

## El pipeline

| # | Etapa | Qué hace | Con qué | Estado |
|---|---|---|---|---|
| 1 | Ingesta | Recorre el álbum, lee EXIF, cachea miniaturas de 1024 px | PIL + numpy | **hecho** |
| 2 | Técnico | Nitidez, exposición, contraste, blanco y negro | numpy | **hecho** |
| 3 | Repetidas | Hash perceptual + agrupado de ráfagas por hora de captura | numpy | **hecho** |
| 4 | Caras | Detección, ojos cerrados, tamaño del sujeto, identidad de los novios | YuNet + MediaPipe + SFace | **hecho** |
| 5 | Preferencia | Parecido de contenido (CLIP) a lo que publicó en otros casamientos, y un modelo entrenado con los seis | CLIP + vecinos + regresión | **hecho, AUC 0.67–0.76 sin ver el casamiento** |
| 6 | Momentos | Corta el día en bloques por las pausas reales y les pone nombre | huecos + programación dinámica | **hecho** |
| 7 | Guion | Reparte las slides a lo largo del día, corregido por cuánto publica de cada parte | relevancia marginal | **hecho** |
| 8 | Montaje | Recorte 4:5 centrado en caras + plantillas medidas de sus posts | PIL | **hecho** |
| 9 | Texto | Borrador de caption y proveedores a etiquetar | Claude | fase 6 |

Cada etapa escribe su resultado en el caché, así que volver a correr con otros parámetros no
recalcula lo anterior. Sobre 3.000 fotos, las etapas 1–3 tardan pocos minutos la primera vez y
segundos las siguientes.

## Decisiones de diseño

1. **Todo el análisis corre sobre miniaturas de 1024 px cacheadas.** Los originales se abren una
   sola vez para hacer la miniatura, y otra vez al exportar la slide final. Sin esto, cada
   experimento con los parámetros costaría media hora.

2. **La nitidez se mide en la zona más nítida de la foto, no en el promedio.** Su estilo tiene
   mucho fondo desenfocado: un laplaciano global mandaría al fondo justo los mejores retratos.
   Se divide la foto en una grilla de 10×10 y se toma el mejor mosaico. Con una grilla más
   gruesa (6×6 promediando tres mosaicos) sus retratos cerrados quedaban en cero, porque lo
   único nítido son los ojos y se diluían en el resto del cuadro.

3. **La exposición multiplica, no suma.** Una foto quemada no es "buena pero mal expuesta": no
   sirve, por nítida que esté. Y se juzga por dónde cae el grueso del histograma, no por cuántos
   píxeles quemados hay: el quemado localizado —el sol en cuadro— es su estilo.

4. **Los umbrales salen de sus fotos, no de un número lindo.** Están calibrados contra las 24
   con más "me gusta" de su perfil, y `test_calibracion.py` falla si alguna quedaría castigada.
   Son el piso de lo publicable: si una de esas cae, el umbral está mal, no la foto.

5. **El blanco y negro se detecta y no se penaliza.** Publica B&N a propósito (ceremonia,
   retratos clásicos), así que las métricas de color no pueden castigarlo.

6. **Nada se descarta, todo se ordena.** Las que no entran quedan en el banco de suplentes con su
   puntaje. Si él cambia una foto, esa corrección es dato de entrenamiento para la etapa 5.

7. **El ojo final es de él.** La herramienta llega hasta "estas 20, en este orden, así montadas".
   La aprobación es un paso humano de dos minutos, no un detalle a automatizar después.

8. **Álbum en JPEG.** Los RAW hay que exportarlos antes: además de lentos, las fotos que él
   publica ya están reveladas con su presét, y es ese revelado el que define su estilo.

## Su estilo, para el ranking

Sale de mirar los 385 posts ya revisados (los 24 con más "me gusta" están en `raw/photos`):

- Contraluz y hora dorada, con el sol entrando en cuadro.
- Planos abiertos de Mendoza —viñedos, montaña, lago— con la pareja chiquita en el encuadre.
- Blanco y negro de alto contraste para ceremonia y retratos clásicos.
- Movimiento: velo al viento, vestido girando, la pareja corriendo.
- Fiesta con energía: saltos, novio por el aire, bengalas de humo.
- Retrato cerrado con poca profundidad de campo.
- Detalles en macro: anillos, zapatos, maquillaje, ramo.
- Cielos azules saturados y contrastados; casi nada de tonos apagados.
- Formato: 4:5 la mayoría, algo de 1:1, muy poco apaisado.

## Su lenguaje de collage

Medido al píxel sobre sus cinco collages publicados (fase 5):

| plantilla | de dónde | fondo | margen | separación | celdas |
|---|---|---|---|---|---|
| grilla | `C6aDmJ1JyeC-0` | blanco 253 | 7 | 7 | 4, todas 4:5 |
| apilado | `DcmxP-iHGia-0` | **gris 209** | 77 lados, 29 arriba | 58 | 2 apaisadas 3:2 |
| mosaico | `DD0rOoyJJA_-1` | blanco | **0, a sangre** | 9 | columnas 2:1 |
| detalles | `DOe2CmnDITb-0` | blanco | 20 | 18–20 | 5, mezcladas |
| polaroid | `C6aDmJ1JyeC-1` | blanco 255 | — | — | 4 marcos de papel 247 |

- Los collages los usa sobre todo para preparativos y detalles; los retratos fuertes van solos.
- La polaroid no lleva sombra difusa: lleva una línea fina y oscura (172) en el borde de abajo, y
  el papel tiene grano. Sin esas dos cosas el marco desaparece contra el fondo blanco.

## Fases

| Fase | Entrega | Esfuerzo |
|---|---|---|
| **1** | **Base: ingesta, caché, filtro técnico, repetidas, hoja de contacto** | **hecha** |
| **2** | **Caras: ojos cerrados, tamaño del sujeto, identificar a los novios** | **hecha** |
| **3** | **Estilo: rasgos, modelo, entrenador y banco de pruebas** | **hecha; el modelo no discrimina** |
| **4** | **Momentos + guion de las slides** | **hecha** |
| **5** | **Montaje: recorte sobre el sujeto, plantillas medidas, cambios a mano** | **hecha** |
| 6 | Caption y proveedores | medio día |
| **—** | **Material real: verdad, evaluación, entrenamiento, recalibración** | **hecho con 6 casamientos** |
| **—** | **Interfaz local para mirar el post y cambiarlo** | **hecha** |
| **—** | **Pruebas funcionales de punta a punta (`probar.py`)** | **hechas, 34 de 34** |
| **—** | **Modo "con mis elegidas": él elige, la herramienta arma los collages con todas** | **hecho** |
| **—** | **Entrenar desde la interfaz, acumulativo, con lo publicado y lo elegido** | **hecho** |

## Modo "con mis elegidas" (30/09/2026)

Pedido de Diego: además de que la IA elija del álbum completo, poder pasarle las fotos que ya
eligió él y que arme los collages.

- **Es otro problema.** No hay que elegir momentos sino empaquetar: que entren todas en 20
  slides como mucho. Se resuelve partiendo la secuencia del día en tramos contiguos por
  programación dinámica (`lib/elegidas.py`); cada tramo es una slide sola o un collage de 2, 4, 5 o
  6 (no hay plantilla de 3). El costo junta lo que ya se sabía: apaisada sola cuesta, recortar
  cuesta, abarcar más de 45 minutos o dos capítulos cuesta, meter una vertical fuerte en un collage
  cuesta. Con el tope de slides como restricción dura, sale el reparto de menor costo.
- **Dentro de cada bloque del día, las apaisadas se ordenan juntas** antes de partir: en el orden
  estricto por hora, una vertical en el medio separaba dos apaisadas que iban a un apilado.
- **Los cambios se guardan en la lista, no en el post.** "Sacar la slide 7" saca sus fotos de
  `elegidas.txt`; "la 3 sola" las marca. Así volver a armar no depende de números de slide viejos,
  y se aplican una sola vez (quedan en `cambios.txt` como `# aplicado:`).
- **Lo que elige es la mejor etiqueta que hay.** Elegir 40 fotos de un álbum de 1.500 es lo mismo
  que publicarlas, sin esperar a que las suba: queda en `elegidas.json` y el entrenamiento lo usa.
- Los dos posts conviven: el de la IA en `salida/<boda>/`, el suyo en `salida/<boda>/elegidas/`.

## Riesgo que apareció al entrenar desde la Mac

El modelo se entrenó con seis álbumes que viven en otra máquina. Reentrenar en la Mac de Diego con
lo que haya ahí lo habría hecho desaprender. Ahora el entrenamiento suma (`datos_preferencia.npz`
guarda los renglones de cada casamiento), y si el modelo actual sabe de casamientos que no se
pueden reconstruir, no se reemplaza. **Pendiente**: correr una vez `entrenar.py --modelo` en la
máquina con los seis álbumes y llevar `datos_preferencia.npz` a la Mac.

## Lo que se aprendió en la fase 3

El modelo de estilo está armado y medido, y **no alcanza para ordenar nada**. Entra al pipeline
con peso 0 en `config.json`: se calcula, se muestra en la hoja de contacto, y no toca el orden.

Se probó contra dos controles, con la foto madre sacada del conjunto de referencia para que la
comparación no tuviera fuga:

| control | qué es | AUC |
|---|---|---|
| recortes | trozos arbitrarios de sus propias fotos, devueltos al tamaño original | **0.549** |
| cuadros | fotogramas de sus reels a resolución completa | 0.887 |

El 0.549 es casi azar (0.5). Y el 0.887 está confundido: los cuadros son apaisados y sus fotos
son 4:5, así que buena parte de esa separación es el formato — sacando el rasgo `aspect` cae a
0.778. En la prueba pareada, la foto publicada le gana a su propio recorte en 66 de cada 100
casos, contra 50 de azar: hay señal, pero muy poca.

Se probaron siete subconjuntos de rasgos definidos de antemano (color, paleta, composición,
sujeto, y combinaciones). Ninguno pasa de 0.56 contra los recortes. No es un problema de elegir
mejor los rasgos.

Las dos causas, y sus arreglos:

1. **Faltan negativos.** 24 positivos y cero negativos no definen una frontera. Con las fotos
   descartadas de un solo casamiento, `train_estilo.py --descartadas` ya pasa a pesar cada rasgo
   por cuánto separa, sin tocar nada más.
2. **Los rasgos son los equivocados.** Histogramas de color y de bordes no capturan "buen
   encuadre": eso es semántico. Un modelo de embeddings (CLIP o similar) sobre las mismas 24
   fotos casi seguro discrimina mucho mejor. Cuesta instalar onnxruntime y bajar ~350 MB de
   modelo, o torch, que es bastante más.

## Lo que se aprendió en la fase 4

El corte del día y el nombre de los capítulos son dos cosas de confianza muy distinta, y el
módulo las trata distinto a propósito:

- **El corte es estructura medible.** Sale de las pausas reales entre fotos —el viaje al salón,
  la espera antes de la entrada, el corte antes del baile—. No es una conjetura.
- **El nombre es heurístico.** "Este bloque es la ceremonia" sale de la luz, la cantidad de caras
  y si están los novios solos. No hay con qué validarlo hasta que haya un álbum real etiquetado.
  Se puede pisar desde `config.json`, y el corte no depende de cómo se llamen.

Lo que sí quedó medido, sobre un álbum de 859 momentos:

| | guion | agarrar las mejores por puntaje |
|---|---|---|
| bloques del día que toca | **8** | 1 |
| porción del día que cubre | 92 % | — |

Las veinte mejores por puntaje salen **todas del mismo bloque**: el rato con mejor luz gana
siempre. Ése es el problema que resuelve el cupo, y es toda la razón de ser de esta fase.

Dos cosas que hubo que corregir en el camino:

1. La primera versión metía tres bloques en "preparativos" y dejaba capítulos sin usar, porque
   la programación dinámica maximizaba la suma sin obligación de recorrerlos todos. Ahora arranca
   en el primero, termina en el último y avanza de a uno, así ninguno se saltea.
2. Cuando a un capítulo le falta material, sus slides sobrantes se reparten —pero con tope—.
   Sin tope, un álbum desbalanceado terminaba en un post de veinte fotos de los preparativos, que
   es exactamente lo que el cupo venía a evitar. Hoy prefiere un post más corto y avisa por qué.

## Lo que se aprendió en la fase 5

- **Sus collages se midieron en vez de estimarse**, y hubo sorpresas: el apilado va sobre gris, no
  sobre blanco; el mosaico va a sangre, sin margen; la polaroid se distingue del fondo por una
  línea oscura de un píxel, no por una sombra.
- **Recortar gente es una decisión creativa.** Si en 4:5 se corta más del 5 % de las caras, la
  foto va entera sobre el gris. Si quiere el recorte agresivo, lo pide.
- **Sin castigo por repetir, gana siempre la grilla**: sus celdas 4:5 casi no obligan a recortar.
  El orden de preferencia de la config y un costo por repetir plantilla lo corrigen sin forzar
  recortes malos.
- **Lo que él no tocó no se mueve.** La primera versión, al pedir "la 5 sola", mudaba el collage a
  la 6. Ahora cada corrida reusa el plan anterior para las slides intactas, y un collage que él
  deshizo no reaparece en otro lado.

## Lo que enseñó el material real (22/09/2026)

Seis carruseles publicados (AF, AM, JJ, MJ, MN, TH: 101 slides) y dos álbumes completos (MJ, 1155
fotos, y CT, 1224). Sólo MJ tiene las dos cosas, así que es el único casamiento etiquetado:
`verdad.py` encontró, slide por slide, las 68 fotos del álbum que usó (verificado a ojo, y la
cantidad por slide coincide con las celdas de cada collage).

**Varias cosas que se habían supuesto eran falsas.**

- **La técnica no separa nada en un álbum entregado.** Técnica 0.499, caras 0.502, estilo (fase 3)
  0.522 de AUC sobre lo que él publicó. El álbum ya viene elegido por él y revelado con el mismo
  presét: todas las fotos están bien expuestas y enfocadas, y el color es parejo. El filtro técnico
  sigue sirviendo de puerta, pero no ordena.
- **Lo que separa es el contenido.** Publica el doble de detalles (19 % contra 9 % del álbum) y
  fotos con menos gente (mediana de 2 caras contra 4). Los rasgos de color, aun entrenados con
  etiquetas reales, dieron 0.53.
- **La apertura no es la foto más fuerte**: 5 de sus 6 posts arrancan cronológicos, y con collage.
- **Cubre el día entero.** Los cupos fijos por capítulo dejaban horas enteras sin ninguna foto.
- **Las verticales van solas, las apaisadas en collage.** En MJ las 3 fotos sueltas son verticales
  y las 51 apaisadas están en collages. Explica por qué su proporción de collages cambia tanto (de
  18 a 80 %): depende de cuántas apaisadas trae el álbum.
- **Su plantilla más usada no estaba medida**: el apilado blanco (27 de 101 slides), adaptativo —el
  alto de cada foto cambia, pero siempre suman 1294—. También la grilla de 6 de fiesta sobre
  degradé, y la "entera" va a todo el ancho sobre blanco, no sobre gris.
- **Sus collages no juntan la toma siguiente**: abarcan un tramo del día (mediana 28 minutos) con
  fotos que se parecen poco (CLIP 0.69). La herramienta armaba collages de dos cuadros casi iguales.

**Lo que se cambió, en consecuencia:**

- Preferencia por **contenido** con CLIP: cada foto se compara con lo que él publicó en *otros*
  casamientos (`entrenar.py` arma esas referencias), más la señal de "menos gente".
- Reparto **proporcional al día** por bloques, apertura cronológica, collage en la apertura.
- Regla de orientación, apilado blanco adaptativo, grilla de 6 con tope por post, entera blanca.
- Compañeras de collage del mismo tramo (45 min), por puntaje, con parecido CLIP ≤ 0.85.
- **Horas corregidas por el orden de los archivos**: las fotos retocadas aparte (MJ_20, los anillos
  de su slide 4) tenían en el EXIF la fecha del retoque, tres días después.
- El parpadeo quedó apagado: usa MediaPipe, que trae telemetría de Google sin forma de apagarla, y
  en un álbum entregado no aporta (5 fotos de 1155).

**Cómo quedó, medido sobre MJ con `evaluar.py`** (la preferencia no usa ninguna referencia de MJ):

| | primera versión | ahora | azar |
|---|---|---|---|
| AUC del puntaje | 0.501 | **0.581** | 0.5 |
| mismo momento (±2 min) | 19 % | **60 %** | 50 % |
| reparto prep/cer/ret/fiesta | 22/28/25/25 | 31/12/4/52 | él: 47/10/0/43 |
| collages | 7 de 20 | 17 de 20 | él: 16 de 20 |

**Lo que faltaba para ir más lejos** eran más casamientos etiquetados: con uno solo, cada número
tiene mucho ruido y no se puede medir si lo aprendido en MJ vale para otro. Llegaron los otros
cinco esa misma noche, y lo que salió de ahí está en la sección siguiente.

## Lo que enseñó el material real (23/09/2026): seis casamientos etiquetados

Ya son **siete álbumes completos** (AF, AM, CT, JJ, MJ, MN, TH: 8.432 fotos, 35 GB) y **seis con su
post publicado al lado**. `verdad.py` ubicó, slide por slide, las **205 fotos del álbum que él
publicó**, contra 6.658 momentos. CT queda como el casamiento de control: tiene álbum y no tiene
post, así que es el único donde la herramienta elige sin que exista la respuesta.

### Lo que más cambió el resultado: no publica el día en la proporción en que lo fotografía

Es lo más claro que salió de los seis, y no se parece a nada que se hubiera supuesto antes:

| capítulo | del álbum | de lo que publicó | sesgo | en cuántos de los 6 |
|---|---|---|---|---|
| preparativos | 36 % | **58 %** | **1.6×** | 6 de 6 por encima de 1.2 |
| ceremonia | 10 % | 12 % | 1.2× | 4 de 6 por encima de 1 |
| retratos | 6 % | 9 % | 1.5× | va de 0.0 a 3.8: no es estable |
| fiesta | 47 % | **22 %** | **0.45×** | 6 de 6 por debajo de 1 |

En la fiesta la cámara dispara muchísimo —es la mitad del álbum— y él publica poco; de los
preparativos pasa lo contrario. El reparto proporcional puro copiaba la proporción del álbum, que
es la de la cámara, no la de él. Ahora el reparto se multiplica por `post.sesgo` (config.json).
Preparativos y fiesta van con lo medido; ceremonia y retratos varían demasiado entre casamientos,
así que se dejan cerca de 1: con seis casamientos no hay con qué justificar más.

**Qué ganó**, sobre los cinco casamientos que ya estaban armados antes del cambio (163 publicadas):

| | antes | ahora | al azar |
|---|---|---|---|
| eligió exactamente la misma foto | 10 % | **15 %** | 5 % |
| eligió del mismo momento (±2 min) | 58 % | **65 %** | ~50 % |

Y el reparto del post se le parece: en MN él publicó 54/15/8/23 y la herramienta armó 58/12/9/21.

### Cuánto acierta en un casamiento que no vio

La única medición que vale: se saca el casamiento entero del entrenamiento y se mide sobre él.

| qué ordena | AUC (0.5 = moneda) |
|---|---|
| el puntaje técnico solo | 0.53 |
| parecido de contenido con lo que publicó en los otros 5 (CLIP + vecinos) | **0.67** |
| modelo entrenado sobre CLIP, por momento | **0.76** |

Con dos casamientos esto daba 0.61 y 0.66. Con seis, 0.67 y 0.76: **cada casamiento etiquetado
sigue sumando**, y es la vía más barata para mejorar.

La regularización del modelo se barrió en vez de elegirse: el acierto sube de 0.668 (L2=10) a
**0.764 (L2=10000)** y baja después. Con tanta regularización los pesos quedan casi en cero y lo
que ordena es la dirección que separa el promedio de lo publicado del promedio de lo demás; esa
dirección sola da 0.751. Con 205 positivos contra 512 rasgos de CLIP, era de esperar: cualquier
cosa más flexible memoriza.

### Dos errores que encontró el material

1. **Un casamiento etiquetado se puntuaba a sí mismo.** El modelo entrenado se usaba también sobre
   los casamientos con los que se entrenó, así que todo lo medido sobre ellos salía inflado. Ahora,
   si el álbum está en `meta.casamientos` del modelo, la herramienta cae al parecido por vecinos, que
   sí sabe excluir las referencias propias. Todos los números de arriba son sin fuga.
2. **Volver a armarlo movía el post.** La segunda corrida sobre el mismo álbum, sin pedir ningún
   cambio, devolvía 49 fotos donde la primera había puesto 64: el cupo de collages por capítulo
   contaba también las apaisadas —que van en collage siempre— y al reusar el plan anterior las
   clampeaba. Ahora el cupo cuenta sólo las verticales, y `probar.py` verifica en cada casamiento
   que volver a armarlo no mueva nada.

### Dónde sigue flojo

- **MJ es el peor de los seis** (AUC 0.59 contra 0.73–0.78 de AF y JJ), y es justo el que más
  publicó (68 fotos) y el único donde publicó tanta fiesta como preparativos. El sesgo le juega en
  contra: le baja la fiesta al 25 % cuando él publicó 43 %.
- **TH publicó 33 % de retratos** y la herramienta le puso 7 %. Es el caso que hace inestable el sesgo
  de retratos.
- **La coincidencia exacta sigue siendo baja** (15 %). Es esperable —de una ráfaga de cuatro tomas
  casi iguales elegir otra no es un error— pero el número que importa para él es cuántas de las 20
  slides le sirven tal cual, y eso todavía no está medido con él mirando.


## Riesgos conocidos

- **Consentimiento.** Hace falta una lista de "no publicar" (invitados, o parejas que no quieren
  aparecer) que la herramienta respete antes de que esto procese álbumes reales.
- **Fotos sin EXIF.** Si el álbum viene de una exportación que borró los metadatos, el agrupado
  por ráfaga cae al horario del archivo, que es peor. Se avisa en pantalla cuando pasa.
- **Exposición mixta dentro del cuadro.** Resuelto en la fase 2 para lo que importa: además del
  histograma global, ahora se mide la exposición sobre las caras. Una foto con la cara quemada o
  en sombra cae aunque el promedio del cuadro dé bien. En fotos sin cara sigue valiendo el
  promedio global, con la limitación conocida.
- **El umbral de ojos cerrados está calibrado de un solo lado.** Se sabe que ninguna de sus
  publicadas pasa de 0.74, y el umbral está en 0.85. Falta confirmar con un álbum real, donde
  haya parpadeos de verdad, que el valor no se queda corto.
- **La muestra de reconocimiento es chica.** El umbral de 0.50 separa limpio, pero se validó
  con 4 pares de la misma boda contra 101 de bodas distintas. Conviene revisarlo con el primer
  álbum real.
- **El sesgo por capítulo está medido con seis casamientos, no con sesenta.** Preparativos y
  fiesta apuntan en la misma dirección en los seis, así que ésos son firmes. Ceremonia y retratos
  no: retratos va de 0.0 (MJ, JJ) a 3.8 (TH). Están puestos cerca de 1 justamente por eso, y
  conviene volver a medirlos con cada casamiento nuevo (`sesgo` en `config.json`).
- **Los seis casamientos son del mismo fotógrafo y del mismo año.** Si cambia de estilo, el modelo
  queda viejo y no hay nada que lo avise: hay que reentrenar con los posts nuevos.
- **Sobreajuste al pasado. Entrenar con lo que más "me gusta" tuvo lo empuja a repetir lo que
  ya funcionó. Por eso el guion reserva cupo por momento en vez de tomar el top 20 a secas.
