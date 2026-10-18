"""Backtest walk-forward del modelo de tiros al arco por jugador (mismo método que motor/evaluacion.py).

Cada semana se ajusta el modelo SOLO con apariciones y partidos anteriores (sin fuga de información)
y se predicen los jugadores que jugaron esa semana:
* «titular»: jugadores que fueron titulares, con los minutos de sus titularidades PASADAS (no los reales);
* «suplente»: jugadores que entraron desde el banco;
* «sin alineación confirmada»: todos los que jugaron, mezclando ambos escenarios.

Los parámetros (κ, ξ, β) se eligen con log-loss en ago–dic 2025 y la calibración se mide aparte en
ene–jun 2026 (y en la temporada en curso). No hay cuotas de mercado de jugadores en datos gratuitos:
se compara contra referencias simples (tasa cruda del jugador, media de su posición, sin defensa rival).
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

from . import config as C
from . import datos
from . import jugadores as J
from . import modelo_jugadores as MJ
from .evaluacion import BINS, _brier, _logloss

LINEAS_BT = (1, 2, 3)
GRID = [MJ.Params(k, x, b, s, po) for k in (3.0, 6.0, 12.0, 25.0) for x in (0.0, 0.002) for b in (0.0, 0.5, 1.0)
        for s in (True, False) for po in (False, True)]
SOLO_POSICION = MJ.Params(1e6, 0.002, 1.0)   # referencia: todos los jugadores de una posición iguales
CRITERIO = {"ece_max": 0.02, "desvio_max": 0.05, "n_min_bin": 200}
EVENTOS_CLAVE = [(k, e) for e in ("titular", "sin_confirmar") for k in LINEAS_BT]


def _ece(p: np.ndarray, y: np.ndarray) -> tuple[float, float, list[dict]]:
    """Error de calibración medio (ponderado), mayor desvío en rangos con muestra suficiente, y la tabla."""
    d = pd.DataFrame({"p": p, "y": y})
    filas, ece, desvio = [], 0.0, 0.0
    for intervalo, g in d.groupby(pd.cut(d["p"], BINS), observed=True):
        pe, fr = float(g["p"].mean()), float(g["y"].mean())
        filas.append({"lo": float(intervalo.left), "hi": float(intervalo.right), "n": int(len(g)),
                      "prob_estimada": pe, "frecuencia_real": fr})
        ece += len(g) / len(d) * abs(pe - fr)
        if len(g) >= CRITERIO["n_min_bin"]:
            desvio = max(desvio, abs(pe - fr))
    return ece, desvio, filas


def _platt(p: np.ndarray, y: np.ndarray) -> list[float]:
    """[a, b] de la corrección logística a + b·logit(p) que minimiza el log-loss."""
    z = MJ._logit(p)

    def perdida(t):
        return _logloss(1 / (1 + np.exp(-(t[0] + t[1] * z))), y)
    r = minimize(perdida, x0=[0.0, 1.0], method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-9, "maxiter": 2000})
    return [float(r.x[0]), float(r.x[1])]


def backtest_jugadores(inicio="2025-08-01", fin_ajuste="2025-12-31", fin_temporada="2026-06-30",
                       fin=None, fuente: str | None = None, progreso=None) -> dict:
    fuente = fuente or J.fuente_activa()
    partidos = datos.cargar_partidos()
    ap = J.cargar_apariciones(fuente)
    if ap.empty:
        raise RuntimeError("No hay datos de jugadores: ejecuta 'python -P bot.py jugadores --descargar'.")
    ap = J.con_nombres_fd(ap, partidos)
    fin = pd.Timestamp(fin or dt.date.today())
    semanas = list(pd.date_range(pd.Timestamp(inicio), fin, freq="7D"))
    combos = GRID + [SOLO_POSICION]
    preds = {c: {e: {k: [] for k in LINEAS_BT} for e in ("titular", "suplente", "sin_confirmar")} for c in combos}
    ingenuo = {k: [] for k in LINEAS_BT}
    meta = []
    for i, t in enumerate(semanas):
        if progreso:
            progreso(i / len(semanas), f"Backtest jugadores: semana del {t:%d/%m/%Y}")
        prueba = ap[(ap["fecha"] >= t) & (ap["fecha"] < t + pd.Timedelta(days=7)) & (ap["grupo_pos"] != "POR")]
        if prueba.empty:
            continue
        prep = MJ.Preparado(ap, t, MJ.modelos_arco(partidos, t))
        pos = {j: n for n, j in enumerate(prep.ids)}
        idx = prueba["jugador_id"].map(pos)
        prueba, idx = prueba[idx.notna()], idx[idx.notna()].to_numpy(int)  # como en la app: solo con historial
        if not len(idx):
            continue
        d_riv, s_h = np.zeros(len(prueba)), np.zeros(len(prueba))
        for liga, (dmap, h) in prep.defensas.items():
            m = (prueba["liga"] == liga).to_numpy()
            d_riv[m] = prueba.loc[m, "rival_fd"].map(dmap).fillna(0.0).to_numpy(float)
            s_h[m] = np.where(prueba.loc[m, "es_local"].to_numpy(bool), h / 2, -h / 2)
        for c in combos:
            a, b, _ = prep.posterior(c)
            pr = MJ.probabilidades(prep, idx, a, b, np.exp(c.beta * (d_riv + s_h)), LINEAS_BT)
            for e in pr:
                for k in LINEAS_BT:
                    preds[c][e][k].append(pr[e][k].astype(np.float32))
        # referencia ingenua: tasa cruda por 90' (sin encogimiento ni rival), Poisson, mismos minutos de titular
        mins90 = np.bincount(prep.code, prep.mins, prep.n) / 90.0
        crudo = np.bincount(prep.code, prep.y, prep.n) / np.maximum(mins90, 1e-9)
        _, _, mu = prep.posterior(MJ.Params(1.0, 0.0, 0.0))
        crudo = np.where(mins90 >= 1.0, crudo, mu)
        lam = crudo[idx, None] * prep.min_tit[idx] / 90.0
        msk = ~np.isnan(lam)
        for k in LINEAS_BT:
            sf = np.where(msk, poisson.sf(k - 1, np.where(msk, lam, 0.0)), 0.0)
            ingenuo[k].append((sf.sum(1) / msk.sum(1)).astype(np.float32))
        meta.append(pd.DataFrame({
            "liga": prueba["liga"].to_numpy(), "fecha": prueba["fecha"].to_numpy(),
            "jugador_id": prueba["jugador_id"].to_numpy(), "jugador": prueba["jugador"].to_numpy(),
            "equipo": prueba["equipo_fd"].to_numpy(), "rival": prueba["rival_fd"].to_numpy(),
            "grupo_pos": prueba["grupo_pos"].to_numpy(), "titular": prueba["titular"].to_numpy(bool),
            "minutos": prueba["minutos"].to_numpy(), "tiros_arco": prueba["tiros_arco"].to_numpy(),
            "minutos_previos": prep.info["minutos"].to_numpy()[idx], "p_tit_previa": prep.p_tit[idx],
        }))
    pr = pd.concat(meta, ignore_index=True)
    y = {k: (pr["tiros_arco"] >= k).to_numpy(float) for k in LINEAS_BT}
    tit = pr["titular"].to_numpy(bool)
    periodo = np.where(pr["fecha"] <= pd.Timestamp(fin_ajuste), "ajuste",
                       np.where(pr["fecha"] <= pd.Timestamp(fin_temporada), "validacion", "actual"))

    def cat(c, e, k):
        return np.concatenate(preds[c][e][k])

    def ll(c, per, version="modelo"):
        m = periodo == per
        vals = []
        for k in LINEAS_BT:
            if version == "ingenuo":
                vals.append(_logloss(np.concatenate(ingenuo[k])[m & tit], y[k][m & tit]))
                continue
            vals.append(_logloss(cat(c, "titular", k)[m & tit], y[k][m & tit]))
            vals.append(_logloss(cat(c, "sin_confirmar", k)[m], y[k][m]))
        return float(np.mean(vals))

    tabla = [{**c.to_dict(), "logloss_ajuste": ll(c, "ajuste"), "logloss_validacion": ll(c, "validacion")}
             for c in GRID]
    mejor = min(GRID, key=lambda c: ll(c, "ajuste"))
    variantes = {"sin_defensa_rival": replace(mejor, beta=0.0), "sin_factor_suplente": replace(mejor, suplente=not mejor.suplente)
                 if mejor.suplente else None, "otra_dispersion": replace(mejor, poisson=not mejor.poisson)}

    def ll_tit(c, per):  # solo titulares: comparable con la referencia ingenua
        m = (periodo == per) & tit
        return float(np.mean([_logloss(cat(c, "titular", k)[m], y[k][m]) for k in LINEAS_BT]))

    def ll_sin(c, per):  # todos los que jugaron, sin alineación confirmada
        m = periodo == per
        return float(np.mean([_logloss(cat(c, "sin_confirmar", k)[m], y[k][m]) for k in LINEAS_BT]))

    comparacion = {}
    for per in ("validacion", "actual"):
        if (periodo == per).sum() == 0:
            continue
        m_t = (periodo == per) & tit
        comparacion[per] = {
            "filas": int((periodo == per).sum()),
            "logloss_titular_modelo": ll_tit(mejor, per),
            "logloss_titular_sin_rival": ll_tit(variantes["sin_defensa_rival"], per),
            "logloss_titular_otra_dispersion": ll_tit(variantes["otra_dispersion"], per),
            "logloss_titular_solo_posicion": ll_tit(SOLO_POSICION, per),
            "logloss_titular_ingenuo": float(np.mean([_logloss(np.concatenate(ingenuo[k])[m_t], y[k][m_t])
                                                      for k in LINEAS_BT])),
            "logloss_sin_confirmar_modelo": ll_sin(mejor, per),
            "logloss_sin_confirmar_sin_factor_suplente": (ll_sin(variantes["sin_factor_suplente"], per)
                                                          if variantes["sin_factor_suplente"] else None),
        }

    # predicciones finales con los parámetros elegidos, y recalibración logística opcional: se estima SOLO con
    # el periodo de ajuste y se adopta solo si baja el log-loss de la validación (si no, se usan las crudas)
    filtros = {"titular": tit, "suplente": ~tit, "sin_confirmar": np.ones(len(pr), bool)}
    coef, ll_cr, ll_rc, ece_cr, ece_rc = {}, [], [], [], []
    for e, filtro in filtros.items():
        for k in LINEAS_BT:
            cruda = cat(mejor, e, k).astype(float)
            m = filtro & (periodo == "ajuste")
            coef[f"{e}|{k}"] = _platt(cruda[m], y[k][m]) if m.sum() >= 200 else [0.0, 1.0]
            rc = MJ.recalibrar(e, k, cruda, {"usar": True, "coeficientes": coef})
            pr[f"p_{e}_{k}_cruda"], pr[f"p_{e}_{k}_recal"] = cruda, rc
            mv = filtro & (periodo == "validacion")
            if (k, e) in EVENTOS_CLAVE and mv.sum():
                ll_cr.append(_logloss(cruda[mv], y[k][mv]))
                ll_rc.append(_logloss(rc[mv], y[k][mv]))
                ece_cr.append(_ece(cruda[mv], y[k][mv])[0])
                ece_rc.append(_ece(rc[mv], y[k][mv])[0])
    # se adopta solo si mejora a la vez el log-loss y el error de calibración de la validación
    usar = bool(ll_rc) and float(np.mean(ll_rc)) < float(np.mean(ll_cr)) and float(np.mean(ece_rc)) <= float(np.mean(ece_cr))
    for e in filtros:
        for k in LINEAS_BT:
            pr[f"p_{e}_{k}"] = pr[f"p_{e}_{k}_recal" if usar else f"p_{e}_{k}_cruda"]
    recalibracion = {"usar": usar, "coeficientes": coef,
                     "logloss_validacion_cruda": float(np.mean(ll_cr)) if ll_cr else None,
                     "logloss_validacion_recalibrada": float(np.mean(ll_rc)) if ll_rc else None,
                     "error_calibracion_validacion_cruda": float(np.mean(ece_cr)) if ece_cr else None,
                     "error_calibracion_validacion_recalibrada": float(np.mean(ece_rc)) if ece_rc else None}
    for k in LINEAS_BT:
        pr[f"p_ingenuo_{k}"] = np.concatenate(ingenuo[k])
    pr["periodo"] = periodo

    por_evento, calib, calib_actual, calibrado = [], {}, {}, {}
    for e, filtro in (("titular", tit), ("suplente", ~tit), ("sin_confirmar", np.ones(len(pr), bool))):
        for k in LINEAS_BT:
            nombre = MJ.evento(k, e)
            for per in ("ajuste", "validacion", "actual"):
                m = filtro & (periodo == per)
                if m.sum() < 30:
                    continue
                p, yy = pr[f"p_{e}_{k}"].to_numpy(float)[m], y[k][m]
                ece, desvio, filas = _ece(p, yy)
                por_evento.append({"evento": nombre, "periodo": per, "n": int(m.sum()), "prob_media": float(p.mean()),
                                   "frecuencia_real": float(yy.mean()), "logloss": _logloss(p, yy), "brier": _brier(p, yy),
                                   "error_calibracion": ece, "mayor_desvio": desvio})
                if per == "validacion":
                    calib[nombre] = filas
                    if (k, e) in EVENTOS_CLAVE:
                        calibrado[nombre] = {"ece": ece, "mayor_desvio": desvio,
                                             "calibrado": bool(ece <= CRITERIO["ece_max"] and desvio <= CRITERIO["desvio_max"])}
                if per == "actual":
                    calib_actual[nombre] = filas

    resumen = {
        "fecha": dt.date.today().isoformat(), "fuente": fuente, "fuente_nombre": J.FUENTES[fuente],
        "ligas": list(C.LIGAS_JUGADORES),
        "periodo_ajuste": f"{inicio} a {fin_ajuste}",
        "periodo_validacion": f"{pd.Timestamp(fin_ajuste) + pd.Timedelta(days=1):%Y-%m-%d} a {fin_temporada}",
        "periodo_actual": f"temporada {J.temporada_texto(max(C.TEMPORADAS_JUGADORES))} hasta {fin:%Y-%m-%d}",
        "filas": {per: int((periodo == per).sum()) for per in ("ajuste", "validacion", "actual")},
        "parametros": mejor.to_dict(), "tabla_parametros": tabla, "comparacion": comparacion,
        "recalibracion": recalibracion,
        "por_evento": por_evento, "calibracion_por_evento": calib, "calibracion_actual": calib_actual,
        "calibrado": calibrado, "criterio": CRITERIO,
        "contraste_definicion": J.contraste_arco(J.cargar_apariciones(fuente), partidos),
    }
    pr.to_csv(C.DIR_EVALUACION / f"predicciones_jugadores_{dt.date.today():%Y%m%d}.csv.gz", index=False)
    texto = json.dumps(resumen, ensure_ascii=False, indent=1, default=str)
    MJ.RUTA_RESUMEN.write_text(texto, encoding="utf-8")
    (C.DIR_EVALUACION / f"resumen_jugadores_{dt.datetime.now():%Y%m%d_%H%M%S}.json").write_text(texto, encoding="utf-8")
    if progreso:
        progreso(1.0, "Backtest de jugadores terminado")
    return resumen
