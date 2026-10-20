"""Estimaciones por promedios para mercados sin modelo propio en el partido: córners, tarjetas y tiros al arco en
copas (Champions, Libertadores…), y tiros al arco y ATAJADAS del portero en cualquier partido.

Para cada equipo se toman sus últimos N partidos (de cualquier liga europea con datos) ANTES del partido:
lo que genera y lo que concede. Valor esperado del local = (lo que genera el local + lo que concede el visitante) / 2
× ventaja de localía de esa estadística; igual para el visitante. La distribución es binomial negativa con la
dispersión estimada en el backtest. Atajadas del portero de un equipo = tiros al arco del rival − goles del rival.

Backtest (`backtest()`): todos los partidos de las ligas europeas desde ago-2025, cada uno predicho solo con los
partidos anteriores (promedios móviles desplazados: sin fuga de información). Dispersión y recalibración logística
se estiman en ago–dic 2025 y se validan en ene–jun 2026; la recalibración se adopta solo si mejora log-loss y
calibración. Resultado en datos/evaluacion/resumen_estimaciones.json.
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import nbinom

from . import config as C
from . import datos

N_ULTIMOS = 10
RUTA = C.DIR_EVALUACION / "resumen_estimaciones.json"
# estadística: (columna local, columna visitante) por partido
ESTADISTICAS = {
    "corners": ("corn_l", "corn_v"),
    "tarjetas": ("tarj_l", "tarj_v"),
    "tiros_arco": ("arco_l", "arco_v"),
    "atajadas": ("ataj_l", "ataj_v"),  # atajadas del portero del local / del visitante
}
LINEAS = {
    "corners": {"total": [5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5], "equipo": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]},
    "tarjetas": {"total": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5], "equipo": [0.5, 1.5, 2.5, 3.5]},
    "tiros_arco": {"total": [4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5], "equipo": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]},
    "atajadas": {"total": [3.5, 4.5, 5.5, 6.5, 7.5], "equipo": [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]},
}
CRITERIO = {"ece_max": 0.02, "desvio_max": 0.05, "n_min_bin": 200}


def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    d = df[df["liga"].isin(list(C.LIGAS_EUROPA))].copy()
    d = d.dropna(subset=["arco_l", "arco_v", "corn_l", "corn_v", "ama_l", "ama_v", "gl", "gv"])
    d["tarj_l"] = d["ama_l"] + 2 * d["roj_l"].fillna(0)
    d["tarj_v"] = d["ama_v"] + 2 * d["roj_v"].fillna(0)
    d["ataj_l"] = (d["arco_v"] - d["gv"]).clip(lower=0)  # paradas del portero local
    d["ataj_v"] = (d["arco_l"] - d["gl"]).clip(lower=0)
    return d.sort_values("fecha").reset_index(drop=True)


def _largo(d: pd.DataFrame) -> pd.DataFrame:
    """Una fila por equipo y partido: lo que hizo (a favor) y lo que le hicieron (en contra)."""
    filas = []
    for lado, otro, es_local in (("l", "v", True), ("v", "l", False)):
        x = pd.DataFrame({"idx": d.index, "fecha": d["fecha"], "equipo": d["local" if es_local else "visitante"],
                          "es_local": es_local})
        for est, (cl, cv) in ESTADISTICAS.items():
            mio, suyo = (cl, cv) if es_local else (cv, cl)
            x[f"{est}_f"] = d[mio].to_numpy(float)
            x[f"{est}_c"] = d[suyo].to_numpy(float)
        filas.append(x)
    return pd.concat(filas, ignore_index=True).sort_values(["equipo", "fecha"])


def _promedios_previos(largo: pd.DataFrame) -> pd.DataFrame:
    """Promedio de los N partidos ANTERIORES de cada equipo (desplazado una fila: sin mirar el partido)."""
    cols = [c for c in largo.columns if c.endswith("_f") or c.endswith("_c")]
    g = largo.groupby("equipo")[cols]
    prev = g.transform(lambda s: s.shift(1).rolling(N_ULTIMOS, min_periods=4).mean())
    out = largo[["idx", "equipo", "es_local"]].join(prev)
    out["n_prev"] = largo.groupby("equipo").cumcount()
    return out


def _lambdas(d: pd.DataFrame, prev: pd.DataFrame, ventaja: dict) -> pd.DataFrame:
    loc = prev[prev["es_local"]].set_index("idx")
    vis = prev[~prev["es_local"]].set_index("idx")
    out = pd.DataFrame(index=d.index)
    for est in ESTADISTICAS:
        hl, hv = ventaja.get(est, (1.0, 1.0))
        out[f"{est}_l"] = (loc[f"{est}_f"] + vis[f"{est}_c"]).reindex(d.index) / 2 * hl
        out[f"{est}_v"] = (vis[f"{est}_f"] + loc[f"{est}_c"]).reindex(d.index) / 2 * hv
    return out


def _ventaja(d: pd.DataFrame) -> dict:
    """Cuánto más (o menos) hace el local que el promedio, por estadística."""
    out = {}
    for est, (cl, cv) in ESTADISTICAS.items():
        m = (d[cl].mean() + d[cv].mean()) / 2
        out[est] = (float(d[cl].mean() / m), float(d[cv].mean() / m)) if m > 0 else (1.0, 1.0)
    return out


def _sf(linea: float, mu, r):
    """P(Y > linea) con Y ~ binomial negativa de media mu y tamaño r."""
    mu = np.maximum(np.asarray(mu, float), 1e-6)
    return nbinom.sf(np.floor(linea), r, r / (r + mu))


def _ajustar_r(y, mu) -> float:
    y, mu = np.asarray(y, float), np.maximum(np.asarray(mu, float), 1e-6)

    def nll(log_r):
        r = np.exp(log_r)
        return -np.mean(nbinom.logpmf(y, r, r / (r + mu)))
    return float(np.exp(minimize_scalar(nll, bounds=(np.log(0.5), np.log(500.0)), method="bounded").x))


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _platt(p, y) -> list[float]:
    z = _logit(p)

    def ll(t):
        q = np.clip(1 / (1 + np.exp(-(t[0] + t[1] * z))), 1e-6, 1 - 1e-6)
        return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))
    r = minimize(ll, x0=[0.0, 1.0], method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-9, "maxiter": 2000})
    return [float(r.x[0]), float(r.x[1])]


def _ece(p, y, bins=(0, .1, .2, .3, .4, .5, .6, .7, .75, .8, .85, .9, .95, 1)):
    d = pd.DataFrame({"p": p, "y": y})
    ece, desvio, filas = 0.0, 0.0, []
    for iv, g in d.groupby(pd.cut(d["p"], list(bins)), observed=True):
        pe, fr = float(g["p"].mean()), float(g["y"].mean())
        filas.append({"lo": float(iv.left), "hi": float(iv.right), "n": int(len(g)), "prob_estimada": pe, "frecuencia_real": fr})
        ece += len(g) / len(d) * abs(pe - fr)
        if len(g) >= CRITERIO["n_min_bin"]:
            desvio = max(desvio, abs(pe - fr))
    return ece, desvio, filas


def backtest(inicio="2025-08-01", fin_ajuste="2025-12-31", fin_validacion="2026-06-30") -> dict:
    d = _preparar(datos.cargar_partidos())
    prev = _promedios_previos(_largo(d))
    ajuste_hist = d[d["fecha"] < pd.Timestamp(inicio)]
    ventaja = _ventaja(ajuste_hist)
    lam = _lambdas(d, prev, ventaja)
    ok = (d["fecha"] >= pd.Timestamp(inicio))
    loc_n = prev[prev["es_local"]].set_index("idx")["n_prev"].reindex(d.index)
    vis_n = prev[~prev["es_local"]].set_index("idx")["n_prev"].reindex(d.index)
    ok &= (loc_n >= 4) & (vis_n >= 4) & lam.notna().all(axis=1)
    d, lam = d[ok], lam[ok]
    per = np.where(d["fecha"] <= pd.Timestamp(fin_ajuste), "ajuste",
                   np.where(d["fecha"] <= pd.Timestamp(fin_validacion), "validacion", "actual"))
    resumen = {"fecha": dt.date.today().isoformat(), "n_ultimos": N_ULTIMOS, "ventaja_local": ventaja,
               "periodo_ajuste": f"{inicio} a {fin_ajuste}", "periodo_validacion": f"2026-01-01 a {fin_validacion}",
               "partidos": {p: int((per == p).sum()) for p in ("ajuste", "validacion", "actual")},
               "dispersion": {}, "recalibracion": {}, "evaluacion": [], "calibrado": {}, "criterio": CRITERIO}
    aj = per == "ajuste"
    for est, (cl, cv) in ESTADISTICAS.items():
        objetivos = {"total": (d[cl] + d[cv], lam[f"{est}_l"] + lam[f"{est}_v"]),
                     "local": (d[cl], lam[f"{est}_l"]), "visitante": (d[cv], lam[f"{est}_v"])}
        for alcance, (y, mu) in objetivos.items():
            y, mu = y.to_numpy(float), mu.to_numpy(float)
            r = _ajustar_r(y[aj], mu[aj])
            resumen["dispersion"][f"{est}|{alcance}"] = r
            lineas = LINEAS[est]["total" if alcance == "total" else "equipo"]
            p_all, y_all, per_all = [], [], []
            for ln in lineas:
                p_all.append(_sf(ln, mu, r))
                y_all.append((y > ln).astype(float))
                per_all.append(per)
            p_all, y_all, per_all = np.concatenate(p_all), np.concatenate(y_all), np.concatenate(per_all)
            # recalibración logística conjunta para todas las líneas de este mercado
            ma, mv = per_all == "ajuste", per_all == "validacion"
            coef = _platt(p_all[ma], y_all[ma])
            rc = 1 / (1 + np.exp(-(coef[0] + coef[1] * _logit(p_all))))

            def ll(p, m):
                q = np.clip(p[m], 1e-6, 1 - 1e-6)
                return float(-np.mean(y_all[m] * np.log(q) + (1 - y_all[m]) * np.log(1 - q)))
            usar = ll(rc, mv) < ll(p_all, mv) and _ece(rc[mv], y_all[mv])[0] <= _ece(p_all[mv], y_all[mv])[0]
            clave = f"{est}|{alcance}"
            resumen["recalibracion"][clave] = {"usar": bool(usar), "coeficientes": coef}
            final = rc if usar else p_all
            for periodo in ("ajuste", "validacion", "actual"):
                m = per_all == periodo
                if m.sum() < 50:
                    continue
                ece, desvio, filas = _ece(final[m], y_all[m])
                resumen["evaluacion"].append({"mercado": clave, "periodo": periodo, "n": int(m.sum()),
                                              "prob_media": float(final[m].mean()), "frecuencia_real": float(y_all[m].mean()),
                                              "logloss": ll(final, m), "error_calibracion": ece, "mayor_desvio": desvio})
                if periodo == "validacion":
                    resumen["calibrado"][clave] = {"ece": ece, "mayor_desvio": desvio, "tabla": filas,
                                                   "calibrado": bool(ece <= CRITERIO["ece_max"] and desvio <= CRITERIO["desvio_max"])}
    RUTA.write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return resumen


# --- uso en el paquete del día ----------------------------------------------------------------

_cache: dict = {}


def resumen() -> dict:
    try:
        return json.loads(RUTA.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _base() -> tuple[pd.DataFrame, dict]:
    clave = datos._firma()
    if _cache.get("clave") != clave:
        d = _preparar(datos.cargar_partidos())
        ult = _largo(d)
        cols = [c for c in ult.columns if c.endswith("_f") or c.endswith("_c")]
        prom = ult.groupby("equipo").tail(N_ULTIMOS).groupby("equipo")[cols].mean()
        prom["n"] = ult.groupby("equipo").size()
        prom["ultima"] = ult.groupby("equipo")["fecha"].max()
        _cache.update(clave=clave, prom=prom)
    return _cache["prom"], resumen()


def equipo_conocido(equipo: str) -> bool:
    prom, _ = _base()
    return equipo in prom.index and prom.loc[equipo, "n"] >= 4


def mercados_partido(local: str, visitante: str, solo: tuple[str, ...] | None = None) -> tuple[dict, dict]:
    """(probabilidades "mercado|opcion|linea", esperados) para el partido; vacío si falta historial o backtest."""
    prom, res = _base()
    if not res.get("dispersion") or local not in prom.index or visitante not in prom.index:
        return {}, {}
    if min(prom.loc[local, "n"], prom.loc[visitante, "n"]) < 4:
        return {}, {}
    pl, pv = prom.loc[local], prom.loc[visitante]
    mer, esp = {}, {}
    for est in ESTADISTICAS:
        if solo and est not in solo:
            continue
        hl, hv = res.get("ventaja_local", {}).get(est, (1.0, 1.0))
        ml = (pl[f"{est}_f"] + pv[f"{est}_c"]) / 2 * hl
        mv = (pv[f"{est}_f"] + pl[f"{est}_c"]) / 2 * hv
        esp[est], esp[f"{est}_local"], esp[f"{est}_visitante"] = round(ml + mv, 2), round(ml, 2), round(mv, 2)
        for alcance, mu, sufijo in (("total", ml + mv, ""), ("local", ml, "_local"), ("visitante", mv, "_visitante")):
            r = res["dispersion"].get(f"{est}|{alcance}")
            rc = res["recalibracion"].get(f"{est}|{alcance}", {})
            if not r:
                continue
            for ln in LINEAS[est]["total" if alcance == "total" else "equipo"]:
                p = float(_sf(ln, mu, r))
                if rc.get("usar"):
                    a, b = rc["coeficientes"]
                    p = float(1 / (1 + np.exp(-(a + b * _logit(p)))))
                mer[f"{est}{sufijo}|mas|{ln}"] = round(p, 4)
                mer[f"{est}{sufijo}|menos|{ln}"] = round(1 - p, 4)
    return mer, esp
