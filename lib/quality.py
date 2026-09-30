"""Métricas técnicas de cada foto y su puntaje, medidas sobre la miniatura cacheada.

Tres criterios guían los umbrales, y valen para todo el módulo:

- La nitidez se mide en la zona más nítida, no en el promedio. Su estilo tiene mucho fondo
  desenfocado: un laplaciano global mandaría al fondo justo los mejores retratos.
- La exposición se juzga por dónde cae el grueso del histograma (mediana y percentil 95), no
  por cuántos píxeles quemados hay. Fotografía a contraluz con el sol en cuadro: el quemado
  localizado es su estilo, y lo que arruina una foto es que se corra la imagen entera.
- La exposición multiplica en vez de sumar. Una foto quemada no es "buena pero mal expuesta":
  no sirve, por nítida que esté.

Los umbrales están calibrados contra las 24 fotos con más "me gusta" de su perfil (raw/photos),
que son el piso de lo que él considera publicable:

                      sus 24 publicadas        tomas arruinadas
    mediana de luz    37 a 188                 233, 245, 255
    percentil 95      172 a 255                15, 16, 17
    quemado           hasta 0.198              0.395 a 0.699

Las rampas van por el medio de esos dos rangos, con margen para el material que no está en
esa muestra de 24.

Limitación conocida: el histograma es global. Una foto con la mitad quemada y la otra mitad
oscura promedia bien y pasa. Se probó medirlo por regiones y se descartó: el umbral que detecta
ese caso (0.22 de zonas quemadas) también marca sus propios collages sobre fondo blanco (0.34)
y sus fotos de cielo abierto (0.19). Prefiere dejar pasar una mala antes que voltear una buena.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# Grilla fina y un solo mosaico: en un retrato cerrado lo único nítido son los ojos, y con una
# grilla gruesa ese detalle se diluye en el resto del cuadro. Medido contra sus 24 publicadas y
# contra tomas movidas a propósito, 10x10 con el mejor mosaico separa 269x; la grilla de 6x6
# promediando tres mosaicos separaba 118x y además hundía sus retratos de poca profundidad.
TILES = 10
TOP_TILES = 1
BW_SATURATION = 0.06

# Rampa de nitidez, relativa a la mediana del álbum. Su publicada más suave queda en 0.31 de esa
# mediana, así que el cero va bastante más abajo. Arriba satura rápido a propósito: el puntaje
# técnico está para descartar lo inservible, no para ordenar lo bueno (de eso se ocupa el estilo).
SHARP_FLOOR, SHARP_FULL = 0.12, 0.45

BRIGHT_OK, BRIGHT_RUINED = 200.0, 245.0     # mediana de luz: de acá para arriba, sobreexpuesta
DARK_OK, DARK_RUINED = 110.0, 35.0          # percentil 95: si no hay ni un alto, está subexpuesta
CLIP_OK, CLIP_MUCH = 0.25, 0.60             # quemado tolerado antes de descontar, y tope


def _gray(rgb: np.ndarray) -> np.ndarray:
    return rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114


def _laplacian(gray: np.ndarray) -> np.ndarray:
    # Convolución 3x3 por rebanadas: más rápido que armar el kernel y no necesita scipy ni cv2
    return (4.0 * gray[1:-1, 1:-1] - gray[:-2, 1:-1] - gray[2:, 1:-1]
            - gray[1:-1, :-2] - gray[1:-1, 2:])


def _sharpness(gray: np.ndarray) -> tuple[float, float, float, float]:
    """Devuelve (nitidez de la mejor zona, nitidez global, foco x, foco y).

    El foco es el centro de las zonas más nítidas, en coordenadas 0–1. En una foto sin cara es
    lo más parecido a "el sujeto": el montaje recorta alrededor de ahí para no dejar afuera el
    anillo o el ramo que el fotógrafo enfocó.
    """
    lap = _laplacian(gray)
    overall = float(lap.var())
    h, w = lap.shape
    th, tw = max(1, h // TILES), max(1, w // TILES)
    tiles = []
    for row in range(TILES):
        for col in range(TILES):
            tile = lap[row * th:(row + 1) * th, col * tw:(col + 1) * tw]
            if tile.size > 64:
                tiles.append((float(tile.var()), (col + 0.5) / TILES, (row + 0.5) / TILES))
    if not tiles:
        return overall, overall, 0.5, 0.5
    tiles.sort(reverse=True)
    best = float(np.mean([t[0] for t in tiles[:TOP_TILES]]))
    # Centroide de las cinco zonas más nítidas, pesado por nitidez: una sola zona es inestable
    top = tiles[:5]
    peso = sum(t[0] for t in top) or 1.0
    fx = sum(t[0] * t[1] for t in top) / peso
    fy = sum(t[0] * t[2] for t in top) / peso
    return best, overall, fx, fy


def _colorfulness(rgb: np.ndarray) -> float:
    """Métrica de Hasler y Süsstrunk: cuánto color tiene la imagen."""
    rg = rgb[:, :, 0] - rgb[:, :, 1]
    yb = 0.5 * (rgb[:, :, 0] + rgb[:, :, 1]) - rgb[:, :, 2]
    std = np.sqrt(rg.var() + yb.var())
    mean = np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    return float(std + 0.3 * mean) / 255.0


def analyze(im: Image.Image) -> dict:
    """Métricas crudas de una miniatura. No decide nada: eso lo hace score_album()."""
    rgb = np.asarray(im.convert("RGB"), dtype=np.float32)
    gray = _gray(rgb)
    best_sharp, overall_sharp, focus_x, focus_y = _sharpness(gray)

    lum = gray / 255.0
    high = rgb.max(axis=2)
    low = rgb.min(axis=2)
    # Saturación estilo HSV, sin dividir por cero en los píxeles negros
    sat = np.where(high > 1e-3, (high - low) / np.maximum(high, 1e-3), 0.0)

    p05, p50, p95 = (float(v) for v in np.percentile(gray, (5, 50, 95)))

    return {
        "sharp": round(best_sharp, 2),
        "sharp_global": round(overall_sharp, 2),
        "focus": [round(focus_x, 3), round(focus_y, 3)],
        "lum": round(float(lum.mean()), 4),
        "contrast": round(float(lum.std()), 4),
        "p05": round(p05, 1),
        "p50": round(p50, 1),
        "p95": round(p95, 1),
        "clip_hi": round(float((gray > 250).mean()), 4),
        "clip_lo": round(float((gray < 6).mean()), 4),
        "sat": round(float(sat.mean()), 4),
        "colorfulness": round(_colorfulness(rgb), 4),
        # Cálido - frío: su paleta tira a dorado, sirve como rasgo de estilo en la fase 3
        "warmth": round(float((rgb[:, :, 0].mean() - rgb[:, :, 2].mean()) / 255.0), 4),
    }


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def score_album(metrics: list[dict]) -> list[dict]:
    """Convierte las métricas crudas en puntajes 0–1, normalizando dentro del álbum.

    La nitidez se compara contra la mediana del propio álbum: un umbral absoluto no se traslada
    entre cámaras, lentes ni condiciones de luz.
    """
    if not metrics:
        return []
    median_sharp = float(np.median([m["sharp"] for m in metrics])) or 1.0

    scored = []
    for m in metrics:
        rel = m["sharp"] / median_sharp
        sharp_score = _clamp((rel - SHARP_FLOOR) / (SHARP_FULL - SHARP_FLOOR))

        # Se corrió la imagen entera hacia el blanco: no es contraluz, está quemada
        expo = 1.0 - _clamp((m["p50"] - BRIGHT_OK) / (BRIGHT_RUINED - BRIGHT_OK))
        # No hay un solo alto en toda la foto: no es un clave baja, está subexpuesta
        expo *= 1.0 - _clamp((DARK_OK - m["p95"]) / (DARK_OK - DARK_RUINED))
        # Y aun con la mediana sana, si medio cuadro es blanco puro algo se perdió
        expo *= 1.0 - 0.5 * _clamp((m["clip_hi"] - CLIP_OK) / (CLIP_MUCH - CLIP_OK))

        # Una foto muy plana suele ser un disparo accidental: pared, techo, fuera de foco total
        tone = _clamp((m["contrast"] - 0.04) / 0.10)

        scored.append({
            **m,
            "sharp_rel": round(rel, 3),
            "bw": m["sat"] < BW_SATURATION,
            "score_sharp": round(sharp_score, 3),
            "score_expo": round(expo, 3),
            "score_tone": round(tone, 3),
            "score_tecnico": round((0.75 * sharp_score + 0.25 * tone) * expo, 3),
        })
    return scored
