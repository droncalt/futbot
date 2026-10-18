"""Fichas de equipo: forma reciente, rendimiento local/visitante y enfrentamientos directos."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def _vista_equipo(df: pd.DataFrame, equipo: str) -> pd.DataFrame:
    """Partidos del equipo desde su punto de vista (a favor / en contra)."""
    loc = df[df["local"] == equipo]
    vis = df[df["visitante"] == equipo]

    def armar(d, es_local):
        s, o = ("_l", "_v") if es_local else ("_v", "_l")
        out = pd.DataFrame({
            "fecha": d["fecha"], "liga": d["liga"], "temporada": d["temporada"],
            "condicion": "Local" if es_local else "Visitante",
            "rival": d["visitante"] if es_local else d["local"],
            "gf": d["gl"] if es_local else d["gv"], "gc": d["gv"] if es_local else d["gl"],
        })
        for col in ("xg", "rem", "arco", "corn", "ama", "roj"):
            if col + s in d.columns:
                out[col + "_f"] = d[col + s]
                out[col + "_c"] = d[col + o]
        ht_f, ht_c = ("ht_gl", "ht_gv") if es_local else ("ht_gv", "ht_gl")
        out["ht_gf"], out["ht_gc"] = d.get(ht_f), d.get(ht_c)
        return out
    v = pd.concat([armar(loc, True), armar(vis, False)]).sort_values("fecha")
    v["res"] = np.where(v["gf"] > v["gc"], "G", np.where(v["gf"] < v["gc"], "P", "E"))
    return v


def ultimos(df: pd.DataFrame, equipo: str, n: int = 8) -> pd.DataFrame:
    v = _vista_equipo(df, equipo).tail(n).iloc[::-1]
    out = pd.DataFrame({
        "Fecha": v["fecha"].dt.strftime("%d/%m/%y"), "Liga": v["liga"], "Cond.": v["condicion"].str[0],
        "Rival": v["rival"], "Marcador": v["gf"].astype(int).astype(str) + "-" + v["gc"].astype(int).astype(str),
        "Res.": v["res"],
    })
    if "xg_f" in v and v["xg_f"].notna().any():
        out["xG"] = v["xg_f"].round(2).astype(str) + " - " + v["xg_c"].round(2).astype(str)
    if "corn_f" in v and v["corn_f"].notna().any():
        out["Córners"] = v["corn_f"].fillna(-1).astype(int).astype(str) + "-" + v["corn_c"].fillna(-1).astype(int).astype(str)
        out["Córners"] = out["Córners"].str.replace("-1", "?")
    return out.reset_index(drop=True)


def resumen(df: pd.DataFrame, equipo: str, liga: str | None = None, temporada: str | None = None) -> pd.DataFrame:
    v = _vista_equipo(df, equipo)
    if liga:
        v = v[v["liga"] == liga]
    if temporada:
        v = v[v["temporada"] == temporada]
    filas = []
    for nombre, d in (("Total", v), ("Local", v[v["condicion"] == "Local"]), ("Visitante", v[v["condicion"] == "Visitante"])):
        if d.empty:
            continue
        tot = d["gf"] + d["gc"]
        fila = {
            "": nombre, "PJ": len(d), "G-E-P": f"{(d.res == 'G').sum()}-{(d.res == 'E').sum()}-{(d.res == 'P').sum()}",
            "GF/p": d["gf"].mean(), "GC/p": d["gc"].mean(),
            "Más 1.5 %": (tot > 1.5).mean() * 100, "Más 2.5 %": (tot > 2.5).mean() * 100,
            "Ambos anotan %": ((d["gf"] > 0) & (d["gc"] > 0)).mean() * 100,
            "Valla invicta %": (d["gc"] == 0).mean() * 100, "Sin marcar %": (d["gf"] == 0).mean() * 100,
        }
        if "xg_f" in d and d["xg_f"].notna().any():
            fila["xG/p"] = d["xg_f"].mean()
            fila["xGA/p"] = d["xg_c"].mean()
        if "arco_f" in d and d["arco_f"].notna().any():
            fila["Tiros al arco/p"] = d["arco_f"].mean()
        if "corn_f" in d and d["corn_f"].notna().any():
            fila["Córners a favor/p"] = d["corn_f"].mean()
            fila["Córners en contra/p"] = d["corn_c"].mean()
        if "ama_f" in d and d["ama_f"].notna().any():
            fila["Amarillas/p"] = d["ama_f"].mean()
        filas.append(fila)
    return pd.DataFrame(filas).round(2)


def h2h(df: pd.DataFrame, a: str, b: str, n: int = 8) -> pd.DataFrame:
    d = df[((df["local"] == a) & (df["visitante"] == b)) | ((df["local"] == b) & (df["visitante"] == a))]
    d = d.sort_values("fecha", ascending=False).head(n)
    return pd.DataFrame({
        "Fecha": d["fecha"].dt.strftime("%d/%m/%y"), "Liga": d["liga"], "Local": d["local"],
        "Marcador": d["gl"].astype(int).astype(str) + "-" + d["gv"].astype(int).astype(str),
        "Visitante": d["visitante"],
    }).reset_index(drop=True)


def temporada_actual() -> str:
    return f"20{C.TEMPORADA_ACTUAL[:2]}/{C.TEMPORADA_ACTUAL[2:]}"
