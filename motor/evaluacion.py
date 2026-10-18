"""Backtest walk-forward: así se mide si el bot sirve.

Para cada semana de la temporada de prueba se ajusta el modelo SOLO con partidos anteriores
(sin fuga de información) y se predicen los partidos de esa semana. Luego se compara con:
* lo que pasó (calibración, log-loss, Brier);
* el mercado sin margen (¿el modelo aporta algo que las casas no sepan ya?).

También se estima el peso óptimo modelo/mercado y se simulan las "combinadas de fijas".
"""
from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pandas as pd

from . import config as C
from . import mercados as M
from .modelo import ajustar_conteo, ajustar_goles, matriz_dc, puntos_tarjetas

EVENTOS = {  # evento binario -> función sobre (H, A)
    "Gana local": lambda H, A: H > A,
    "Gana visitante": lambda H, A: H < A,
    "Local o empate": lambda H, A: H >= A,
    "Visitante o empate": lambda H, A: H <= A,
    "Más de 0.5": lambda H, A: H + A > 0.5,
    "Más de 1.5": lambda H, A: H + A > 1.5,
    "Más de 2.5": lambda H, A: H + A > 2.5,
    "Menos de 3.5": lambda H, A: H + A < 3.5,
    "Menos de 4.5": lambda H, A: H + A < 4.5,
    "Ambos anotan": lambda H, A: (H > 0) & (A > 0),
}
K = np.arange(C.MAX_GOLES + 1)
HH, AA = np.meshgrid(K, K, indexing="ij")
MASCARAS = {e: f(HH, AA) for e, f in EVENTOS.items()}


def _probs_eventos(Mx: np.ndarray) -> dict:
    return {e: float(Mx[m].sum()) for e, m in MASCARAS.items()}


def _mercado(fila, pref: str) -> tuple[float, float, float | None] | None:
    c = [fila.get(pref + k) for k in ("1", "x", "2")]
    if any(v is None or pd.isna(v) or v <= 1 for v in c):
        return None
    p1, _, p2 = M.quitar_margen(c)
    o, u = fila.get(pref + "o25"), fila.get(pref + "u25")
    po = None
    if o is not None and u is not None and pd.notna(o) and pd.notna(u) and o > 1 and u > 1:
        po = float(M.quitar_margen([o, u])[0])
    return float(p1), float(p2), po


def walk_forward(df: pd.DataFrame, liga: str, inicio, fin, paso: int = 7,
                 peso_xg: float = C.PESO_XG, con_mercado: bool = True) -> pd.DataFrame:
    filas = []
    d_liga = df[df["liga"] == liga]
    for t in pd.date_range(pd.Timestamp(inicio), pd.Timestamp(fin), freq=f"{paso}D"):
        prueba = d_liga[(d_liga["fecha"] >= t) & (d_liga["fecha"] < t + pd.Timedelta(days=paso))]
        if prueba.empty:
            continue
        m = ajustar_goles(df, liga, t, "ft", peso_xg=peso_xg)
        if m is None:
            continue
        mc = ajustar_conteo(df, liga, t, "corners") if liga in C.LIGAS_EUROPA else None
        mt = ajustar_conteo(df, liga, t, "tarjetas") if liga in C.LIGAS_EUROPA else None
        for _, f in prueba.iterrows():
            if not (m.tiene(f.local) and m.tiene(f.visitante)):
                continue
            lam, mu = m.lambdas(f.local, f.visitante)
            pm = _probs_eventos(matriz_dc(lam, mu, m.rho))
            fila = {"liga": liga, "fecha": f.fecha, "local": f.local, "visitante": f.visitante,
                    "gl": f.gl, "gv": f.gv, "lam": lam, "mu": mu,
                    "n_local": m.partidos_por_equipo.get(f.local, 0),
                    "n_visit": m.partidos_por_equipo.get(f.visitante, 0)}
            for e in EVENTOS:
                fila["pm_" + e] = pm[e]
                fila["y_" + e] = bool(EVENTOS[e](np.array(f.gl), np.array(f.gv)))
            # mercado "al momento de apostar" (apertura) y al cierre
            for etiqueta, prefs in (("ap", ("s_", "c_")), ("ci", ("sc_", "cc_"))):
                if not con_mercado:
                    break
                mk = None
                for p in prefs:
                    mk = _mercado(f, p)
                    if mk:
                        break
                if mk:
                    lk, mk_mu = M.lambdas_desde_probs(mk[0], mk[1], mk[2])
                    pk = _probs_eventos(matriz_dc(lk, mk_mu, C.RHO_MERCADO))
                    for e in EVENTOS:
                        fila[f"pk{etiqueta}_" + e] = pk[e]
                    fila[f"tiene_ou_{etiqueta}"] = mk[2] is not None
            # cuota "tipo casa normal" para el laboratorio de combinadas
            for k in ("1", "x", "2"):
                fila["cuota_" + k] = f.get("c_" + k) if pd.notna(f.get("c_" + k)) else f.get("cc_" + k)
            if mc is not None and pd.notna(f.get("corn_l")):
                Mc = mc.conjunta(f.local, f.visitante)
                X, Y = np.meshgrid(np.arange(Mc.shape[0]), np.arange(Mc.shape[1]), indexing="ij")
                tot = f.corn_l + f.corn_v
                for L in (8.5, 9.5, 10.5):
                    fila[f"pm_Córners más de {L}"] = float(Mc[X + Y > L].sum())
                    fila[f"y_Córners más de {L}"] = bool(tot > L)
            if mt is not None and pd.notna(f.get("ama_l")):
                Mt = mt.conjunta(f.local, f.visitante)
                X, Y = np.meshgrid(np.arange(Mt.shape[0]), np.arange(Mt.shape[1]), indexing="ij")
                # Betano (regla 3.1.62): amarilla = 1, roja = 2
                tot = puntos_tarjetas(f.ama_l + f.ama_v, (f.roj_l if pd.notna(f.roj_l) else 0) + (f.roj_v if pd.notna(f.roj_v) else 0))
                for L in (3.5, 4.5):
                    fila[f"pm_Tarjetas más de {L}"] = float(Mt[X + Y > L].sum())
                    fila[f"y_Tarjetas más de {L}"] = bool(tot > L)
            filas.append(fila)
    return pd.DataFrame(filas)


# --- métricas ---------------------------------------------------------------------

def _logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def _brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def _eventos_largos(pr: pd.DataFrame, col_p: str) -> pd.DataFrame:
    partes = []
    for e in EVENTOS:
        if col_p + e in pr.columns:
            partes.append(pd.DataFrame({"evento": e, "p": pr[col_p + e], "y": pr["y_" + e].astype(float),
                                        "liga": pr["liga"]}))
    return pd.concat(partes, ignore_index=True).dropna(subset=["p"]) if partes else pd.DataFrame()


def estimar_peso(pr: pd.DataFrame) -> tuple[float, pd.DataFrame]:
    """Peso del modelo (0 = solo mercado, 1 = solo modelo) que minimiza el log-loss."""
    d = pr[pr["pkap_Más de 2.5"].notna() & pr["tiene_ou_ap"].fillna(False).astype(bool)]
    filas = []
    for w in np.round(np.arange(0, 1.0001, 0.05), 2):
        ll = []
        for e in EVENTOS:
            p = M._logit(d["pm_" + e].to_numpy()) * w + M._logit(d["pkap_" + e].to_numpy()) * (1 - w)
            ll.append(_logloss(1 / (1 + np.exp(-p)), d["y_" + e]))
        filas.append({"peso_modelo": w, "logloss_medio": float(np.mean(ll))})
    tabla = pd.DataFrame(filas)
    return float(tabla.loc[tabla["logloss_medio"].idxmin(), "peso_modelo"]), tabla


BINS = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]


def calibracion_por_evento(largo: pd.DataFrame) -> dict:
    """{evento: [{lo, hi, n, prob_estimada, frecuencia_real}]} para mostrar evidencia por selección."""
    out = {}
    for ev, g in largo.groupby("evento"):
        cortes = pd.cut(g["p"], BINS)
        filas = []
        for intervalo, gg in g.groupby(cortes, observed=True):
            filas.append({"lo": float(intervalo.left), "hi": float(intervalo.right), "n": int(len(gg)),
                          "prob_estimada": float(gg["p"].mean()), "frecuencia_real": float(gg["y"].mean())})
        out[ev] = filas
    return out


def calibracion(largo: pd.DataFrame) -> pd.DataFrame:
    bins = BINS
    d = largo.assign(rango=pd.cut(largo["p"], bins))
    return (d.groupby("rango", observed=True)
            .agg(n=("y", "size"), prob_estimada=("p", "mean"), frecuencia_real=("y", "mean"))
            .reset_index().assign(rango=lambda x: x["rango"].astype(str)))


def laboratorio_combinadas(pr: pd.DataFrame, cuota_max: float = 1.40, seed: int = 7) -> dict:
    """¿Qué habría pasado jugando 'fijas' (favoritos a cuota baja) en combinadas?"""
    rng = np.random.default_rng(seed)
    filas = []
    for _, f in pr.iterrows():
        for lado, ev, k in (("local", "Gana local", "1"), ("visitante", "Gana visitante", "2")):
            c = f.get("cuota_" + k)
            if c is None or pd.isna(c) or c > cuota_max or c <= 1:
                continue
            pf = f.get("pf_" + ev)
            filas.append({"semana": f.fecha.to_period("W"), "cuota": float(c), "gano": bool(f["y_" + ev]),
                          "p_bot": None if pd.isna(pf) else float(pf),
                          "equipo": f.local if lado == "local" else f.visitante})
    patas = pd.DataFrame(filas)
    if patas.empty:
        return {}
    out = {"cuota_max": cuota_max, "n_patas": int(len(patas)),
           "acierto_real_simples": float(patas["gano"].mean()),
           "acierto_implicito_por_cuota": float((1 / patas["cuota"]).mean()),
           "roi_simples": float((patas["gano"] * patas["cuota"]).mean() - 1)}
    con_p = patas[patas["p_bot"].notna()]
    valor = con_p[con_p["p_bot"] * con_p["cuota"] > 1 + C.UMBRAL_VALOR]
    out["simples_con_valor_segun_bot"] = {
        "n": int(len(valor)),
        "acierto": float(valor["gano"].mean()) if len(valor) else None,
        "roi": float((valor["gano"] * valor["cuota"]).mean() - 1) if len(valor) else None,
    }
    combos = []
    semanas = [g for _, g in patas.groupby("semana")]
    for n in (2, 3, 4, 5, 6, 8):
        res_azar, res_bot = [], []
        for g in semanas:
            if len(g) < n:
                continue
            for _ in range(30):  # 30 combinadas al azar por semana
                s = g.sample(n, random_state=int(rng.integers(1e9)))
                res_azar.append((s["gano"].all(), float(s["cuota"].prod())))
            gb = g[g["p_bot"].notna()]
            if len(gb) >= n:
                s = gb.nlargest(n, "p_bot")
                res_bot.append((s["gano"].all(), float(s["cuota"].prod())))
        if res_azar:
            a = np.array(res_azar)
            fila = {"patas": n, "combinadas": len(a), "acierto_azar": float(a[:, 0].mean()),
                    "cuota_media": float(a[:, 1].mean()),
                    "roi_azar": float((a[:, 0] * a[:, 1]).mean() - 1)}
            if res_bot:
                b = np.array(res_bot)
                fila.update({"semanas_bot": len(b), "acierto_bot": float(b[:, 0].mean()),
                             "roi_bot": float((b[:, 0] * b[:, 1]).mean() - 1)})
            combos.append(fila)
    out["combinadas"] = combos
    return out


def ejecutar_backtest(df: pd.DataFrame, ligas: list[str] | None = None, inicio="2025-08-01",
                      fin="2026-06-30", progreso=None) -> dict:
    ligas = ligas or list(C.LIGAS)
    partes = []
    for i, liga in enumerate(ligas):
        if progreso:
            progreso(i / (len(ligas) + 1), f"Backtest {liga}…")
        p = walk_forward(df, liga, inicio, fin)
        if len(p):
            partes.append(p)
    pr = pd.concat(partes, ignore_index=True)

    w, tabla_w = estimar_peso(pr)
    for e in EVENTOS:  # probabilidad final del bot (modelo + mercado de apertura)
        pm, pk = pr["pm_" + e].to_numpy(), pr.get("pkap_" + e)
        if pk is None:
            pr["pf_" + e] = pm
            continue
        pk = pk.to_numpy(dtype=float)
        z = w * M._logit(pm) + (1 - w) * M._logit(np.where(np.isnan(pk), pm, pk))
        pr["pf_" + e] = 1 / (1 + np.exp(-z))

    # métricas globales y por liga
    por_liga = []
    for liga, g in pr.groupby("liga"):
        fila = {"liga": liga, "partidos": int(len(g))}
        for col, nombre in (("pm_", "modelo"), ("pkap_", "mercado_apertura"), ("pkci_", "mercado_cierre"),
                            ("pf_", "bot_final")):
            ll = [_logloss(g[col + e], g["y_" + e]) for e in EVENTOS
                  if col + e in g and g[col + e].notna().all()]
            fila[f"logloss_{nombre}"] = float(np.mean(ll)) if ll else None
        por_liga.append(fila)
    por_liga = pd.DataFrame(por_liga)

    largo_bot = _eventos_largos(pr, "pf_")
    largo_mod = _eventos_largos(pr, "pm_")
    extra = [c[3:] for c in pr.columns if c.startswith("pm_") and c[3:] not in EVENTOS]
    largo_conteos = pd.concat([pd.DataFrame({"evento": e, "p": pr["pm_" + e], "y": pr["y_" + e]})
                               for e in extra], ignore_index=True).dropna() if extra else pd.DataFrame()
    if len(largo_conteos):
        largo_conteos["y"] = largo_conteos["y"].astype(float)

    fijas = largo_bot[largo_bot["p"] >= 0.75]
    por_evento = (largo_bot.groupby("evento")
                  .apply(lambda g: pd.Series({
                      "n": len(g), "brier_bot": _brier(g["p"], g["y"]),
                      "fijas_n(p>=75%)": int((g["p"] >= 0.75).sum()),
                      "fijas_prob_media": float(g.loc[g["p"] >= 0.75, "p"].mean()) if (g["p"] >= 0.75).any() else None,
                      "fijas_acierto_real": float(g.loc[g["p"] >= 0.75, "y"].mean()) if (g["p"] >= 0.75).any() else None,
                  }), include_groups=False).reset_index())

    lab = laboratorio_combinadas(pr)
    resumen = {
        "fecha": dt.date.today().isoformat(),
        "periodo": f"{inicio} a {fin}",
        "partidos": int(len(pr)),
        "ligas": ligas,
        "peso_modelo": w,
        "tabla_peso": tabla_w.to_dict("records"),
        "logloss_global": {
            "modelo": float(np.mean([_logloss(pr["pm_" + e], pr["y_" + e]) for e in EVENTOS])),
            "bot_final": float(np.mean([_logloss(pr["pf_" + e], pr["y_" + e]) for e in EVENTOS])),
        },
        "por_liga": por_liga.to_dict("records"),
        "calibracion_bot": calibracion(largo_bot).to_dict("records"),
        "calibracion_modelo": calibracion(largo_mod).to_dict("records"),
        "calibracion_conteos": calibracion(largo_conteos).to_dict("records") if len(largo_conteos) else [],
        "calibracion_por_evento": {**calibracion_por_evento(largo_bot),
                                   **(calibracion_por_evento(largo_conteos) if len(largo_conteos) else {})},
        "peso_xg": C.PESO_XG, "ridge_conteos": C.RIDGE_CONTEOS,
        "conteos_por_evento": (largo_conteos.groupby("evento").agg(n=("y", "size"), prob_media=("p", "mean"),
                               frecuencia_real=("y", "mean")).reset_index().to_dict("records")
                               if len(largo_conteos) else []),
        "por_evento": por_evento.to_dict("records"),
        "fijas_global": {"n": int(len(fijas)), "prob_media": float(fijas["p"].mean()) if len(fijas) else None,
                         "acierto_real": float(fijas["y"].mean()) if len(fijas) else None},
        "laboratorio": lab,
    }
    con_mk = pr[pr["pkap_Más de 2.5"].notna()]
    if len(con_mk):
        resumen["comparacion_mismo_partido"] = {
            "partidos": int(len(con_mk)),
            **{f"logloss_{n}": float(np.mean([_logloss(con_mk[c + e], con_mk["y_" + e]) for e in EVENTOS]))
               for c, n in (("pm_", "modelo"), ("pkap_", "mercado_apertura"), ("pf_", "bot_final"))},
        }
        cierre = con_mk[con_mk["pkci_Más de 2.5"].notna()]
        if len(cierre):
            resumen["comparacion_mismo_partido"]["logloss_mercado_cierre"] = float(
                np.mean([_logloss(cierre["pkci_" + e], cierre["y_" + e]) for e in EVENTOS]))
    if progreso:
        progreso(1.0, "Backtest terminado")
    pr.to_csv(C.DIR_EVALUACION / f"predicciones_{dt.date.today():%Y%m%d}.csv", index=False)
    (C.DIR_EVALUACION / "resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=1, default=str),
                                                   encoding="utf-8")
    historial = C.DIR_EVALUACION / f"resumen_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    historial.write_text(json.dumps(resumen, ensure_ascii=False, default=str), encoding="utf-8")
    return resumen


def prueba_xg(df: pd.DataFrame, inicio="2026-09-14", pesos=(0.0, 0.3, 0.6)) -> pd.DataFrame:
    """Compara pesos de xG en la temporada actual (única con xG). Muestra pequeña: orientativo."""
    fin = dt.date.today()
    filas = []
    for w in pesos:
        partes = [walk_forward(df, l, inicio, fin, peso_xg=w, con_mercado=False) for l in C.LIGAS_EUROPA]
        pr = pd.concat([p for p in partes if len(p)], ignore_index=True)
        filas.append({"peso_xg": w, "partidos": len(pr),
                      "logloss": float(np.mean([_logloss(pr["pm_" + e], pr["y_" + e]) for e in EVENTOS]))})
    return pd.DataFrame(filas)
