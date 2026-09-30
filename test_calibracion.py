"""Control de que no se descarte material que él sí publicaría.

Corre el puntaje completo —técnica y caras— sobre las fotos con más "me gusta" de su perfil
(raw/photos, las baja scripts/download_raw.py) y verifica que ninguna quede penalizada. Son el
piso de lo que considera publicable: si una de estas cae, el umbral está mal, no la foto.

Uso:  python curator/test_calibracion.py
      python curator/test_calibracion.py --sin-caras     (no necesita los modelos)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import quality

ROOT = Path(__file__).resolve().parents[1]
PUBLICADAS = ROOT / "raw" / "photos"
MIN_EXPO = 0.95         # ninguna publicada debería perder más de un 5% por exposición
MIN_TECNICO = 0.50      # ni caer en la mitad inferior del puntaje técnico
MIN_CARAS = 0.95        # ni quedar marcada por ojos cerrados o cara mal expuesta


def main() -> int:
    con_caras = "--sin-caras" not in sys.argv
    if not PUBLICADAS.is_dir():
        print(f"No está {PUBLICADAS}: correr antes python scripts/download_raw.py")
        return 0

    files = sorted(PUBLICADAS.glob("*.jpg"))
    if not files:
        print(f"No hay fotos en {PUBLICADAS}")
        return 0

    if con_caras:
        from lib import faces

    metrics, face_metrics = [], []
    for path in files:
        with Image.open(path) as im:
            im.draft("RGB", (1024, 1024))
            metrics.append(quality.analyze(im))
            if con_caras:
                rgb = np.asarray(im.convert("RGB"))
                gray = (rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587
                        + rgb[:, :, 2] * 0.114).astype(np.float32)
                face_metrics.append(faces.analyze(rgb, gray))
    scored = quality.score_album(metrics)
    if not con_caras:
        face_metrics = [{"score_caras": 1.0, "blink": None, "kind": "?"} for _ in scored]

    fallas = []
    for path, m, f in zip(files, scored, face_metrics):
        if m["score_expo"] < MIN_EXPO or m["score_tecnico"] < MIN_TECNICO \
                or f["score_caras"] < MIN_CARAS:
            fallas.append((path.stem, m, f))

    print(f"{len(files)} fotos publicadas evaluadas" + ("" if con_caras else " (sin caras)"))
    print(f"  puntaje técnico: peor {min(m['score_tecnico'] for m in scored):.3f}, "
          f"mejor {max(m['score_tecnico'] for m in scored):.3f}")
    print(f"  exposición: peor {min(m['score_expo'] for m in scored):.3f}")
    print(f"  blanco y negro detectadas: {sum(1 for m in scored if m['bw'])}")
    if con_caras:
        blinks = [f["blink"] for f in face_metrics if f["blink"] is not None]
        print(f"  caras: peor puntaje {min(f['score_caras'] for f in face_metrics):.3f}; "
              f"parpadeo máximo {max(blinks, default=0):.3f} "
              f"(el umbral de ojos cerrados está en {faces.BLINK_OK})")
    if fallas:
        print(f"\nFALLA: {len(fallas)} fotos que él publicó quedarían castigadas")
        for name, m, f in fallas:
            print(f"  {name}: tecnico={m['score_tecnico']:.3f} expo={m['score_expo']:.3f} "
                  f"nitidez={m['score_sharp']:.3f} caras={f['score_caras']:.3f} "
                  f"parpadeo={f['blink']} p50={m['p50']:.0f} p95={m['p95']:.0f}")
        return 1
    print("\nOK: ninguna foto publicada queda penalizada")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
