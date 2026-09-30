"""Entrena el modelo de estilo con las fotos que él publicó.

Uso:
  python curator/train_estilo.py                          usa raw/photos como referencia
  python curator/train_estilo.py --mas "D:/mas-posts"     suma más publicadas
  python curator/train_estilo.py --descartadas "D:/boda/no-publicadas"
  python curator/train_estilo.py --evaluar                además mide cuánto discrimina

Deja el modelo en curator/modelo_estilo.json, que es lo que después usa curate.py.

Sobre los descartes: son las fotos del álbum que él NO eligió. Son el dato que más le falta al
modelo. Alcanza con una carpeta de un casamiento donde se hayan copiado las que quedaron afuera:
con eso el modelo deja de medir "parecido a lo suyo" y pasa a medir "de las de este álbum, cuál
elegiría él", que es la pregunta que importa.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import faces, quality, style

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent
PUBLICADAS = PROJECT / "raw" / "photos"
MODELO = ROOT / "modelo_estilo.json"
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def describe_folder(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in EXTENSIONS and p.is_file())


def extract(paths: list[Path], label: str) -> list[dict]:
    """Rasgos de estilo de cada foto. Es el mismo camino que corre curate.py."""
    out = []
    for i, path in enumerate(paths, start=1):
        try:
            with Image.open(path) as im:
                im.draft("RGB", (1024, 1024))
                rgb = np.asarray(im.convert("RGB"))
        except Exception as err:
            print(f"  no se pudo abrir {path.name}: {err}", flush=True)
            continue
        if max(rgb.shape[:2]) > 1024:
            scale = 1024 / max(rgb.shape[:2])
            im = Image.fromarray(rgb).resize(
                (round(rgb.shape[1] * scale), round(rgb.shape[0] * scale)), Image.LANCZOS)
            rgb = np.asarray(im)
        gray = (rgb[:, :, 0] * 0.299 + rgb[:, :, 1] * 0.587 + rgb[:, :, 2] * 0.114).astype(np.float32)
        metrics = quality.analyze(Image.fromarray(rgb))
        metrics.update(faces.analyze(rgb, gray))
        data = style.features(rgb, gray, metrics)
        data["_name"] = path.stem
        out.append(data)
        if i % 25 == 0:
            print(f"  {label}: {i}/{len(paths)}", flush=True)
    return out


def evaluate(positives: list[dict], model: style.StyleModel) -> None:
    """Cuánto puntúa cada foto suya cuando el modelo NO la vio: uno afuera por vez."""
    print("\n=== control: cada publicada contra las otras ===", flush=True)
    scores = []
    for i, feature_dict in enumerate(positives):
        resto = positives[:i] + positives[i + 1:]
        parcial = style.StyleModel.fit(resto)
        scores.append((parcial.score(feature_dict), feature_dict["_name"], parcial, feature_dict))
    values = np.array([s[0] for s in scores])
    print(f"  puntaje de las suyas: min={values.min():.3f} p25={np.percentile(values, 25):.3f} "
          f"mediana={np.median(values):.3f} max={values.max():.3f}", flush=True)
    print("  las tres que el modelo reconoce menos como suyas:", flush=True)
    for value, name, parcial, feature_dict in sorted(scores)[:3]:
        motivos = ", ".join(f"{k} {v:+.1f}" for k, v in parcial.explain(feature_dict, 3))
        print(f"    {name}: {value:.3f}   se aleja en {motivos}", flush=True)


def contrast_with(positives: list[dict], model: style.StyleModel, folder: Path) -> None:
    """Puntúa una carpeta de control y la compara contra las publicadas.

    Sirve para contestar la única pregunta que importa del modelo: ¿separa lo suyo de lo que no
    elegiría? Y además dice qué rasgo está haciendo la separación, que es la forma de darse
    cuenta si está separando por estilo o por algo tonto, como la resolución.
    """
    paths = describe_folder(folder)
    if not paths:
        print(f"  {folder} está vacía", flush=True)
        return
    control = extract(paths, folder.name)

    propios = np.array([
        style.StyleModel.fit(positives[:i] + positives[i + 1:]).score(f)
        for i, f in enumerate(positives)
    ])
    ajenos = np.array([model.score(f) for f in control])

    # Probabilidad de que una publicada al azar puntúe más alto que un control al azar
    auc = float((propios[:, None] > ajenos[None, :]).mean()
                + 0.5 * (propios[:, None] == ajenos[None, :]).mean())
    print(f"\n=== control: {folder.name} ({len(control)} fotos) ===", flush=True)
    print(f"  publicadas: mediana={np.median(propios):.3f}  rango {propios.min():.3f}–{propios.max():.3f}",
          flush=True)
    print(f"  control:    mediana={np.median(ajenos):.3f}  rango {ajenos.min():.3f}–{ajenos.max():.3f}",
          flush=True)
    print(f"  separación (AUC): {auc:.3f}   (0.5 = no distingue nada, 1.0 = perfecto)", flush=True)

    # Qué rasgo hace la separación: si es uno solo y es tonto, se ve acá
    pos = np.array([style.vector(f) for f in positives])
    neg = np.array([style.vector(f) for f in control])
    gap = np.abs(np.median(pos, axis=0) - np.median(neg, axis=0)) / model.scale
    order = np.argsort(-gap)[:5]
    print("  los rasgos que más separan a los dos grupos:", flush=True)
    for i in order:
        print(f"    {style.FEATURES[i]:14} publicadas={np.median(pos[:, i]):8.3f}  "
              f"control={np.median(neg[:, i]):8.3f}  ({gap[i]:.1f} desvíos)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Entrena el modelo de estilo")
    parser.add_argument("--mas", help="carpeta con más fotos publicadas por él")
    parser.add_argument("--descartadas", help="carpeta con fotos de un álbum que NO publicó")
    parser.add_argument("--evaluar", action="store_true", help="mide cuánto discrimina el modelo")
    parser.add_argument("--control", action="append", default=[],
                        help="carpeta de control para medir la separación (se puede repetir)")
    parser.add_argument("--out", default=str(MODELO))
    args = parser.parse_args()

    paths = describe_folder(PUBLICADAS) if PUBLICADAS.is_dir() else []
    if args.mas:
        extra = Path(args.mas).expanduser().resolve()
        if not extra.is_dir():
            sys.exit(f"No existe {extra}")
        paths += describe_folder(extra)
    if not paths:
        sys.exit(f"No hay fotos de referencia. Correr antes python scripts/download_raw.py")

    print(f"Referencia: {len(paths)} fotos publicadas", flush=True)
    positives = extract(paths, "publicadas")

    negatives = []
    if args.descartadas:
        folder = Path(args.descartadas).expanduser().resolve()
        if not folder.is_dir():
            sys.exit(f"No existe {folder}")
        descartes = describe_folder(folder)
        print(f"Descartes: {len(descartes)} fotos que no publicó", flush=True)
        negatives = extract(descartes, "descartadas")

    model = style.StyleModel.fit(positives, negatives or None)
    out = Path(args.out).expanduser().resolve()
    model.save(out)
    print(f"\nModelo en {out}", flush=True)
    print(f"  {model.meta['positivos']} positivos, {model.meta['negativos']} negativos, "
          f"{len(style.FEATURES)} rasgos, {style.NEIGHBOURS} vecinos", flush=True)
    if not negatives:
        print("  sin descartes todavía: el puntaje mide parecido a su material, no preferencia. "
              "Ver --descartadas.", flush=True)

    if args.evaluar:
        evaluate(positives, model)
    for folder in args.control:
        path = Path(folder).expanduser().resolve()
        if not path.is_dir():
            print(f"\nNo existe la carpeta de control {path}", flush=True)
            continue
        contrast_with(positives, model, path)


if __name__ == "__main__":
    main()
