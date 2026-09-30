"""Compara lo que elige la herramienta contra lo que él publicó de verdad.

Uso:  python curator/evaluar.py "D:/bodas/MJ" curator/salida/MJ

Necesita `publicadas.json` en el caché del álbum (lo arma verdad.py) y un post ya armado.
Mide cuatro cosas, porque cada una apunta a una parte distinta:

1. **Puntajes.** ¿Las que él publicó puntúan alto? Es un AUC por cada señal: técnica, caras,
   estilo. Dice qué señales están alineadas con él y cuáles no, sin depender del guion.
2. **Ráfagas.** De cada ráfaga queda una sola toma. ¿Es la misma que eligió él?
3. **Selección.** De sus fotos publicadas, ¿cuántas eligió también la herramienta? Contado por foto
   exacta, por ráfaga y por momento (misma escena en ±2 minutos), porque elegir otra toma del
   mismo momento no es un error.
4. **Reparto.** ¿Cuánto de su post cae en cada capítulo, y cuánto del armado?

Cada número viene con su azar al lado: sin eso no se sabe si 12 % es bueno o malo.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

MOMENTO = 120.0             # segundos: dos fotos a menos de esto son "el mismo momento"


def auc(scores: list[float], labels: list[bool]) -> float | None:
    """Probabilidad de que una publicada al azar puntúe más que una no publicada al azar."""
    s, y = np.asarray(scores, dtype=float), np.asarray(labels, dtype=bool)
    pos, neg = s[y], s[~y]
    if len(pos) == 0 or len(neg) == 0:
        return None
    # Por rangos, que es exacto y aguanta empates: los puntajes técnicos saturan mucho en 1.0
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    valores = np.concatenate([pos, neg])[order]
    i = 0
    while i < len(valores):
        j = i
        while j + 1 < len(valores) and valores[j + 1] == valores[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    rank_pos = ranks[:len(pos)].sum()
    return float((rank_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def main() -> int:
    if len(sys.argv) < 3:
        sys.exit("Uso: python curator/evaluar.py <álbum> <carpeta del post armado>")
    album = Path(sys.argv[1]).expanduser().resolve()
    out = Path(sys.argv[2]).expanduser().resolve()
    verdad = json.loads((album / ".curator" / "publicadas.json").read_text(encoding="utf-8-sig"))
    analisis = json.loads((out / "analisis.json").read_text(encoding="utf-8-sig"))
    seleccion = json.loads((out / "seleccion.json").read_text(encoding="utf-8-sig"))

    fotos = analisis["fotos"]
    por_rel = {f["rel"]: f for f in fotos}
    # El capítulo sólo queda anotado en la representante de cada ráfaga; las otras tomas lo heredan
    cap_grupo = {f["group"]: f["capitulo"] for f in fotos if f.get("capitulo")}
    for f in fotos:
        f.setdefault("capitulo", cap_grupo.get(f["group"], "?"))
    suyas = {r for r in verdad["publicadas"] if r in por_rel}
    faltan = set(verdad["publicadas"]) - suyas
    elegidas = {r for s in seleccion["slides"] for r in s.get("fotos", [s["rel"]])}
    total = len(fotos)
    print(f"Álbum: {total} fotos. Él publicó {len(suyas)}; la herramienta eligió {len(elegidas)}.")
    if faltan:
        print(f"  ojo: {len(faltan)} publicadas no están en el análisis")

    # 1. Puntajes
    print("\n1. ¿Sus publicadas puntúan alto? (AUC: 0.5 = azar, 1.0 = perfecto)")
    labels = [f["rel"] in suyas for f in fotos]
    for clave, nombre in (("score_tecnico", "técnica"), ("score_caras", "caras"),
                          ("score_toma", "técnica × caras"), ("score_estilo", "estilo (fase 3)"),
                          ("score_pref", "preferencia (CLIP)"), ("score", "puntaje final"),
                          ("sharp", "nitidez cruda"), ("face_area", "tamaño de cara")):
        valores = [f.get(clave) for f in fotos]
        if any(v is None for v in valores):
            continue
        valor = auc(valores, labels)
        if valor is not None:
            print(f"   {nombre:18} {valor:.3f}")

    # 2. Ráfagas
    print("\n2. De cada ráfaga, ¿la toma que queda es la que eligió él?")
    en_rafaga = [por_rel[r] for r in suyas if por_rel[r]["group_size"] > 1]
    representantes = sum(1 for f in en_rafaga if f["rank_in_group"] == 0)
    if en_rafaga:
        azar = np.mean([1 / f["group_size"] for f in en_rafaga])
        print(f"   {len(en_rafaga)} de sus publicadas venían en una ráfaga. En {representantes} "
              f"({representantes / len(en_rafaga):.0%}) la herramienta eligió la misma toma "
              f"(al azar: {azar:.0%})")

    # 3. Selección
    print("\n3. De sus publicadas, ¿cuántas eligió la herramienta?")
    exactas = suyas & elegidas
    grupos_curador = {por_rel[r]["group"] for r in elegidas if r in por_rel}
    misma_rafaga = {r for r in suyas if por_rel[r]["group"] in grupos_curador}
    horas_curador = [datetime.fromisoformat(por_rel[r]["taken"]) for r in elegidas
                     if r in por_rel and por_rel[r]["taken"]]
    mismo_momento = set()
    for r in suyas:
        t = por_rel[r]["taken"]
        if t and any(abs((datetime.fromisoformat(t) - h).total_seconds()) <= MOMENTO
                     for h in horas_curador):
            mismo_momento.add(r)
    k = len(elegidas)
    azar_exacta = k / total
    # Azar de "mismo momento": qué fracción del álbum cae a ±2 min de k fotos al azar
    rng = np.random.default_rng(0)
    todas_horas = np.array([datetime.fromisoformat(f["taken"]).timestamp() for f in fotos])
    suyas_horas = np.array([datetime.fromisoformat(por_rel[r]["taken"]).timestamp() for r in suyas])
    azar_mom = []
    for _ in range(200):
        muestra = rng.choice(todas_horas, size=k, replace=False)
        azar_mom.append(np.mean([np.min(np.abs(muestra - h)) <= MOMENTO for h in suyas_horas]))
    n = max(len(suyas), 1)
    print(f"   misma foto exacta:        {len(exactas):3} de {len(suyas)} ({len(exactas) / n:.0%})   "
          f"al azar: {azar_exacta:.0%}")
    print(f"   misma ráfaga:             {len(misma_rafaga):3} de {len(suyas)} "
          f"({len(misma_rafaga) / n:.0%})")
    print(f"   mismo momento (±2 min):   {len(mismo_momento):3} de {len(suyas)} "
          f"({len(mismo_momento) / n:.0%})   al azar: {np.mean(azar_mom):.0%}")

    # 4. Reparto
    print("\n4. ¿Cómo se reparte cada post en los capítulos detectados?")
    suyas_cap = Counter(por_rel[r].get("capitulo", "?") for r in suyas)
    cur_cap = Counter(por_rel[r].get("capitulo", "?") for r in elegidas if r in por_rel)
    caps = [c["capitulo"] for c in seleccion.get("capitulos", [])] or sorted(set(suyas_cap) | set(cur_cap))
    for c in dict.fromkeys(caps):
        print(f"   {c:14} él {suyas_cap.get(c, 0):3} ({suyas_cap.get(c, 0) / n:4.0%})   "
              f"armado {cur_cap.get(c, 0):3} ({cur_cap.get(c, 0) / max(k, 1):4.0%})")

    # Resumen para comparar corridas
    resumen = {
        "album": str(album), "fotos": total, "publicadas": len(suyas), "elegidas": k,
        "exactas": len(exactas), "misma_rafaga": len(misma_rafaga),
        "mismo_momento": len(mismo_momento), "azar_momento": round(float(np.mean(azar_mom)), 3),
        "auc": {clave: auc([f.get(clave) for f in fotos], labels)
                for clave in ("score_tecnico", "score_caras", "score_toma", "score_estilo",
                              "score_pref", "score")
                if all(f.get(clave) is not None for f in fotos)},
    }
    (out / "evaluacion.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
