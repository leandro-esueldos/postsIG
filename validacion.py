"""Valida el criterio dejando un casamiento afuera: ¿acierta en uno que no vio?

Uso:  python curator/validacion.py                       (todos los que tengan verdad)
      python curator/validacion.py --albumes D:/datos/albumes/MJ D:/datos/albumes/MN

Es la prueba que importa. Cada foto se puntúa por cuánto se parece a lo que él publicó,
y si entre esas referencias estuvieran las del mismo casamiento estaría copiándose la respuesta.
Acá se saca el casamiento entero del entrenamiento y se mide sobre él, uno por uno.

Reporta el AUC: la probabilidad de que una foto que él publicó puntúe más alto que una que no.
0.5 es tirar la moneda. Se mide por foto y por momento (agrupando las ráfagas), porque elegir
otra toma de la misma ráfaga no es un error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import curate
from evaluar import auc
from lib import album as album_lib
from lib import embed


def datos(album: Path) -> tuple[list, dict, set, list] | None:
    cache = album / album_lib.CACHE_DIRNAME
    verdad = cache / "publicadas.json"
    if not verdad.is_file():
        return None
    photos = list(album_lib.load_index(cache).values())
    if not photos or not photos[0].metrics:
        return None
    publicadas = set(json.loads(verdad.read_text(encoding="utf-8-sig"))["publicadas"])
    embeddings = embed.for_album(album, photos, album_lib.thumb_path)
    return photos, embeddings, publicadas, []


def por_momento(photos: list, valores: dict, publicadas: set, grupos: dict) -> tuple[list, list]:
    """Una fila por ráfaga: su mejor puntaje, y si él publicó alguna de sus tomas."""
    mejor: dict[int, float] = {}
    label: dict[int, bool] = {}
    for p in photos:
        g = grupos.get(p.rel)
        if g is None:
            continue
        mejor[g] = max(mejor.get(g, -1.0), valores[p.key])
        label[g] = label.get(g, False) or (p.rel in publicadas)
    claves = sorted(mejor)
    return [mejor[g] for g in claves], [label[g] for g in claves]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validación dejando un casamiento afuera")
    parser.add_argument("--albumes", nargs="*", default=[])
    parser.add_argument("--salida", default=None, help="carpeta de salidas, para agrupar por ráfaga")
    args = parser.parse_args()

    config = json.loads((curate.ROOT / "config.json").read_text(encoding="utf-8-sig"))
    inter = config.get("interfaz", {})
    base = Path(inter.get("albumes", curate.ROOT / "albumes")).expanduser()
    salidas = Path(args.salida or inter.get("salida", curate.ROOT / "salida")).expanduser()
    albumes = ([Path(a).expanduser().resolve() for a in args.albumes] or
               [d for d in sorted(base.iterdir()) if d.is_dir()] if base.is_dir() else [])

    print("Validación dejando un casamiento afuera")
    print(f"{'casamiento':12} {'fotos':>6} {'publicó':>8} {'AUC foto':>9} {'AUC momento':>12} "
          f"{'AUC técnica':>12}")
    filas = []
    for album in albumes:
        d = datos(album)
        if d is None:
            continue
        photos, embeddings, publicadas, _ = d
        pref = curate.preference_scores(album, photos, embeddings)
        if pref is None:
            print(f"{album.name:12} sin referencias para comparar")
            continue
        etiquetas = [p.rel in publicadas for p in photos]
        if not any(etiquetas):
            continue
        auc_foto = auc([pref[p.key] for p in photos], etiquetas)
        tecnica = [p.metrics.get("score_tecnico", p.metrics.get("sharp", 0)) for p in photos]
        auc_tec = auc(tecnica, etiquetas)

        auc_mom = None
        analisis = salidas / album.name / "analisis.json"
        if analisis.is_file():
            grupos = {f["rel"]: f["group"]
                      for f in json.loads(analisis.read_text(encoding="utf-8-sig"))["fotos"]}
            v, y = por_momento(photos, pref, publicadas, grupos)
            auc_mom = auc(v, y)
        filas.append((album.name, len(photos), sum(etiquetas), auc_foto, auc_mom, auc_tec))
        print(f"{album.name:12} {len(photos):6} {sum(etiquetas):8} {auc_foto:9.3f} "
              f"{(f'{auc_mom:.3f}' if auc_mom else '—'):>12} {auc_tec:12.3f}")

    # --- modelo entrenado, también dejando cada casamiento afuera ------------------------
    from lib import preference as modelo_pref

    def cargar(album: Path) -> dict:
        photos = list(album_lib.load_index(album / album_lib.CACHE_DIRNAME).values())
        return embed.for_album(album, photos, album_lib.thumb_path)

    X, y, boda = modelo_pref.dataset(albumes, salidas, cargar)
    if len(X) and len(set(boda.tolist())) > 1:
        print(f"\nModelo entrenado sobre el contenido ({len(X)} momentos, "
              f"{int(y.sum())} publicados, {len(set(boda.tolist()))} casamientos)")
        print(f"{'casamiento':12} {'momentos':>9} {'publicó':>8} {'AUC':>7}   entrenado con")
        for l2 in (1000.0, 3000.0, 10000.0, 30000.0):
            aucs, pesos_b = [], []
            detalle = []
            for b in sorted(set(boda.tolist())):
                fuera = boda == b
                if not y[fuera].any() or not y[~fuera].any():
                    continue
                modelo = modelo_pref.Preference.fit(X[~fuera], y[~fuera], l2=l2)
                valor = auc(list(modelo.score(X[fuera])), list(y[fuera]))
                aucs.append(valor)
                pesos_b.append(int(y[fuera].sum()))
                detalle.append((b, int(fuera.sum()), int(y[fuera].sum()), valor))
            if not aucs:
                continue
            media = float(np.average(aucs, weights=pesos_b))
            if l2 == 10000.0:
                for b, n, p_, v in detalle:
                    print(f"{b:12} {n:9} {p_:8} {v:7.3f}   los otros {len(detalle) - 1}")
            print(f"  regularización L2={l2:<6} promedio: {media:.3f}")

    if filas:
        pesos = np.array([f[2] for f in filas], dtype=float)
        media = float(np.average([f[3] for f in filas], weights=pesos))
        media_t = float(np.average([f[5] for f in filas], weights=pesos))
        print(f"\n{len(filas)} casamientos · AUC por foto, promedio pesado por publicadas: "
              f"**{media:.3f}**  (técnica sola: {media_t:.3f})")
        print("0.5 sería tirar la moneda. Cada casamiento se puntuó sin sus propias referencias.")
    else:
        print("\nNo hay casamientos con verdad: correr antes curator/verdad.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
