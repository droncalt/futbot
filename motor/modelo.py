"""Modelos estadísticos.

* ModeloGoles: Dixon-Coles (Poisson bivariado con corrección de marcadores bajos)
  con ponderación temporal y mezcla opcional con xG. Se ajusta para el partido completo,
  el 1.er tiempo y el 2.º tiempo.
* ModeloConteo: Poisson log-lineal con sobredispersión (binomial negativa) para córners
  y tarjetas.

Ajustar un modelo = estimar parámetros con datos anteriores a `fecha_ref`. Nada aquí
"aprende solo": se re-estima cuando llegan datos nuevos y se evalúa en el backtest.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import nbinom, poisson

from . import config as C


# --- utilidades -----------------------------------------------------------------

def _pesos(fechas: pd.Series, fecha_ref: pd.Timestamp, xi: float) -> np.ndarray:
    dias = (fecha_ref - fechas).dt.days.to_numpy(dtype=float)
    return np.exp(-xi * dias)


def _indices(df: pd.DataFrame) -> tuple[list[str], np.ndarray, np.ndarray]:
    equipos = sorted(set(df["local"]) | set(df["visitante"]))
    pos = {e: i for i, e in enumerate(equipos)}
    return equipos, df["local"].map(pos).to_numpy(), df["visitante"].map(pos).to_numpy()


def _nll(theta, hi, ai, x, y, xe, ye, w, n, ridge, usar_rho):
    """Log-verosimilitud negativa (penalizada) de Dixon-Coles y su gradiente analítico."""
    c, h, rho = theta[0], theta[1], theta[2]
    a, d = theta[3:3 + n], theta[3 + n:3 + 2 * n]
    ll = c + h + a[hi] + d[ai]
    lm = c + a[ai] + d[hi]
    lam, mu = np.exp(ll), np.exp(lm)

    tau = np.ones_like(lam)
    dt_dl = np.zeros_like(lam)
    dt_dm = np.zeros_like(lam)
    dt_dr = np.zeros_like(lam)
    if usar_rho:
        m00 = (x == 0) & (y == 0)
        m01 = (x == 0) & (y == 1)
        m10 = (x == 1) & (y == 0)
        m11 = (x == 1) & (y == 1)
        tau[m00] = 1 - lam[m00] * mu[m00] * rho
        tau[m01] = 1 + lam[m01] * rho
        tau[m10] = 1 + mu[m10] * rho
        tau[m11] = 1 - rho
        dt_dl[m00], dt_dm[m00], dt_dr[m00] = -mu[m00] * rho, -lam[m00] * rho, -lam[m00] * mu[m00]
        dt_dl[m01], dt_dr[m01] = rho, lam[m01]
        dt_dm[m10], dt_dr[m10] = rho, mu[m10]
        dt_dr[m11] = -1.0
        tau = np.clip(tau, 1e-9, None)

    loglik = w * (np.log(tau) + xe * ll - lam + ye * lm - mu)
    nll = -loglik.sum() + ridge * (a @ a + d @ d)

    g_ll = w * (xe - lam + dt_dl * lam / tau)
    g_lm = w * (ye - mu + dt_dm * mu / tau)
    grad = np.empty_like(theta)
    grad[0] = -(g_ll.sum() + g_lm.sum())
    grad[1] = -g_ll.sum()
    grad[2] = -(w * dt_dr / tau).sum() if usar_rho else 0.0
    grad[3:3 + n] = -(np.bincount(hi, g_ll, n) + np.bincount(ai, g_lm, n)) + 2 * ridge * a
    grad[3 + n:] = -(np.bincount(ai, g_ll, n) + np.bincount(hi, g_lm, n)) + 2 * ridge * d
    return nll, grad


def _ajustar(hi, ai, x, y, xe, ye, w, n, ridge, usar_rho, media):
    theta0 = np.zeros(3 + 2 * n)
    theta0[0] = np.log(max(media, 0.05))
    theta0[1] = 0.2
    theta0[2] = -0.05 if usar_rho else 0.0
    limites = [(None, None), (-1, 1), (-0.25, 0.25) if usar_rho else (0, 0)] + [(-3, 3)] * (2 * n)
    r = minimize(_nll, theta0, args=(hi, ai, x, y, xe, ye, w, n, ridge, usar_rho),
                 jac=True, method="L-BFGS-B", bounds=limites, options={"maxiter": 500})
    return r.x, bool(r.success)


# --- modelo de goles ------------------------------------------------------------

@dataclass
class ModeloGoles:
    liga: str
    tipo: str                 # "ft" (partido), "1t", "2t"
    equipos: list[str]
    ataque: list[float]
    defensa: list[float]
    intercepto: float
    ventaja_local: float
    rho: float
    fecha_ref: str
    n_partidos: int
    peso_efectivo: float
    partidos_por_equipo: dict = field(default_factory=dict)
    convergio: bool = True
    parametros: dict = field(default_factory=dict)

    def tiene(self, equipo: str) -> bool:
        return equipo in self.equipos

    def lambdas(self, local: str, visitante: str) -> tuple[float, float]:
        pos = {e: i for i, e in enumerate(self.equipos)}
        a = np.array(self.ataque)
        d = np.array(self.defensa)
        # Un equipo sin datos en esta liga se trata como un equipo promedio (0)
        al, dl = (a[pos[local]], d[pos[local]]) if local in pos else (0.0, 0.0)
        av, dv = (a[pos[visitante]], d[pos[visitante]]) if visitante in pos else (0.0, 0.0)
        lam = float(np.exp(self.intercepto + self.ventaja_local + al + dv))
        mu = float(np.exp(self.intercepto + av + dl))
        return lam, mu

    def matriz(self, local: str, visitante: str, max_goles: int | None = None) -> np.ndarray:
        if max_goles is None:
            max_goles = C.MAX_GOLES if self.tipo == "ft" else C.MAX_GOLES_MITAD
        lam, mu = self.lambdas(local, visitante)
        return matriz_dc(lam, mu, self.rho, max_goles)


def matriz_dc(lam: float, mu: float, rho: float, max_goles: int = C.MAX_GOLES) -> np.ndarray:
    """P(goles local = i, goles visitante = j) con la corrección Dixon-Coles."""
    k = np.arange(max_goles + 1)
    m = np.outer(poisson.pmf(k, lam), poisson.pmf(k, mu))
    m[0, 0] *= max(1 - lam * mu * rho, 0)
    m[0, 1] *= max(1 + lam * rho, 0)
    m[1, 0] *= max(1 + mu * rho, 0)
    m[1, 1] *= max(1 - rho, 0)
    return m / m.sum()


def _ventana(df: pd.DataFrame, fecha_ref: pd.Timestamp, liga: str) -> pd.DataFrame:
    d = df[(df["liga"] == liga) & (df["fecha"] < fecha_ref)
           & (df["fecha"] >= fecha_ref - pd.Timedelta(days=C.VENTANA_DIAS))]
    return d


def ajustar_goles(df: pd.DataFrame, liga: str, fecha_ref, tipo: str = "ft",
                  xi: float = C.XI, ridge: float = C.RIDGE, peso_xg: float = C.PESO_XG) -> ModeloGoles | None:
    fecha_ref = pd.Timestamp(fecha_ref)
    d = _ventana(df, fecha_ref, liga)
    if tipo == "ft":
        x, y = d["gl"], d["gv"]
    elif tipo == "1t":
        x, y = d.get("ht_gl"), d.get("ht_gv")
    else:
        x, y = d["gl"] - d.get("ht_gl"), d["gv"] - d.get("ht_gv")
    if x is None or y is None:
        return None
    ok = x.notna() & y.notna()
    d, x, y = d[ok], x[ok].to_numpy(float), y[ok].to_numpy(float)
    if len(d) < 60:
        return None
    equipos, hi, ai = _indices(d)
    w = _pesos(d["fecha"], fecha_ref, xi)
    xe, ye = x.copy(), y.copy()
    usa_xg = False
    if tipo == "ft" and peso_xg > 0 and "xg_l" in d.columns:
        tiene = d["xg_l"].notna().to_numpy() & d["xg_v"].notna().to_numpy()
        if tiene.any():
            usa_xg = True
            xe[tiene] = (1 - peso_xg) * x[tiene] + peso_xg * d["xg_l"].to_numpy(float)[tiene]
            ye[tiene] = (1 - peso_xg) * y[tiene] + peso_xg * d["xg_v"].to_numpy(float)[tiene]
    media = float(np.average((x + y) / 2, weights=w))
    theta, conv = _ajustar(hi, ai, x, y, xe, ye, w, len(equipos), ridge, True, media)
    n = len(equipos)
    conteo = pd.concat([d["local"], d["visitante"]]).value_counts().to_dict()
    return ModeloGoles(
        liga=liga, tipo=tipo, equipos=equipos,
        ataque=theta[3:3 + n].round(5).tolist(), defensa=theta[3 + n:].round(5).tolist(),
        intercepto=float(theta[0]), ventaja_local=float(theta[1]), rho=float(theta[2]),
        fecha_ref=str(fecha_ref.date()), n_partidos=int(len(d)), peso_efectivo=float(w.sum()),
        partidos_por_equipo={k: int(v) for k, v in conteo.items()}, convergio=conv,
        parametros={"xi": xi, "ridge": ridge, "peso_xg": peso_xg if usa_xg else 0.0},
    )


# --- modelo de conteos (córners, tarjetas) --------------------------------------

@dataclass
class ModeloConteo:
    liga: str
    tipo: str                 # "corners" o "tarjetas"
    equipos: list[str]
    ataque: list[float]       # tendencia propia (sacar córners / recibir tarjetas)
    defensa: list[float]      # lo que provoca en el rival
    intercepto: float
    ventaja_local: float
    phi_equipo: float         # varianza / media por equipo (>= 1)
    fecha_ref: str
    n_partidos: int

    def medias(self, local: str, visitante: str) -> tuple[float, float]:
        pos = {e: i for i, e in enumerate(self.equipos)}
        a, d = np.array(self.ataque), np.array(self.defensa)
        al, dl = (a[pos[local]], d[pos[local]]) if local in pos else (0.0, 0.0)
        av, dv = (a[pos[visitante]], d[pos[visitante]]) if visitante in pos else (0.0, 0.0)
        return (float(np.exp(self.intercepto + self.ventaja_local + al + dv)),
                float(np.exp(self.intercepto + av + dl)))

    def pmf_equipo(self, media: float, max_k: int = 30) -> np.ndarray:
        k = np.arange(max_k + 1)
        if self.phi_equipo <= 1.02:
            p = poisson.pmf(k, media)
        else:
            n = media / (self.phi_equipo - 1)
            p = nbinom.pmf(k, n, 1 / self.phi_equipo)
        return p / p.sum()

    def conjunta(self, local: str, visitante: str) -> np.ndarray:
        ml, mv = self.medias(local, visitante)
        return np.outer(self.pmf_equipo(ml), self.pmf_equipo(mv))


def puntos_tarjetas(amarillas, rojas):
    """Conteo de Betano (regla 3.1.62): amarilla = 1, roja = 2; la 2.ª amarilla no se cuenta aparte."""
    return amarillas + 2 * rojas


def ajustar_conteo(df: pd.DataFrame, liga: str, fecha_ref, tipo: str,
                   xi: float = C.XI, ridge: float = C.RIDGE_CONTEOS) -> ModeloConteo | None:
    fecha_ref = pd.Timestamp(fecha_ref)
    d = _ventana(df, fecha_ref, liga)
    if tipo == "corners":
        cl, cv = d.get("corn_l"), d.get("corn_v")
    elif tipo == "arco":  # tiros al arco por equipo (lo usa el modelo de jugadores para la defensa rival)
        cl, cv = d.get("arco_l"), d.get("arco_v")
    else:
        if "ama_l" not in d.columns:
            return None
        cl = puntos_tarjetas(d["ama_l"], d["roj_l"].fillna(0))
        cv = puntos_tarjetas(d["ama_v"], d["roj_v"].fillna(0))
    if cl is None:
        return None
    ok = cl.notna() & cv.notna()
    d, x, y = d[ok], cl[ok].to_numpy(float), cv[ok].to_numpy(float)
    if len(d) < 60:
        return None
    equipos, hi, ai = _indices(d)
    w = _pesos(d["fecha"], fecha_ref, xi)
    n = len(equipos)
    theta, _ = _ajustar(hi, ai, x, y, x, y, w, n, ridge, False, float(np.average((x + y) / 2, weights=w)))
    a, dd = theta[3:3 + n], theta[3 + n:]
    ml = np.exp(theta[0] + theta[1] + a[hi] + dd[ai])
    mv = np.exp(theta[0] + a[ai] + dd[hi])
    # sobredispersión: estadístico de Pearson ponderado
    pearson = (w * ((x - ml) ** 2 / ml + (y - mv) ** 2 / mv)).sum() / (2 * w.sum())
    return ModeloConteo(
        liga=liga, tipo=tipo, equipos=equipos, ataque=a.round(5).tolist(), defensa=dd.round(5).tolist(),
        intercepto=float(theta[0]), ventaja_local=float(theta[1]), phi_equipo=float(max(pearson, 1.0)),
        fecha_ref=str(fecha_ref.date()), n_partidos=int(len(d)),
    )


# --- conjunto de modelos por liga y persistencia --------------------------------

@dataclass
class ModeloLiga:
    liga: str
    fecha_ref: str
    version: str
    ft: ModeloGoles | None
    corners: ModeloConteo | None = None
    tarjetas: ModeloConteo | None = None
    fraccion_1t: float = C.FRACCION_1T

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @staticmethod
    def from_dict(d: dict) -> "ModeloLiga":
        def g(k):
            return ModeloGoles(**d[k]) if d.get(k) else None

        def c(k):
            return ModeloConteo(**d[k]) if d.get(k) else None
        return ModeloLiga(liga=d["liga"], fecha_ref=d["fecha_ref"], version=d["version"],
                          ft=g("ft"), corners=c("corners"),
                          tarjetas=c("tarjetas"), fraccion_1t=d.get("fraccion_1t", C.FRACCION_1T))


def ajustar_liga(df: pd.DataFrame, liga: str, fecha_ref=None, peso_xg: float = C.PESO_XG) -> ModeloLiga | None:
    fecha_ref = pd.Timestamp(fecha_ref or dt.date.today() + dt.timedelta(days=1))
    ft = ajustar_goles(df, liga, fecha_ref, "ft", peso_xg=peso_xg)
    if ft is None:
        return None
    # Las mitades se derivan del partido completo con la fracción de goles del 1.er tiempo
    # de la liga: así todas las patas de un Bet Builder salen de una sola distribución.
    d = _ventana(df, fecha_ref, liga)
    frac = C.FRACCION_1T
    if "ht_gl" in d.columns and d["ht_gl"].notna().sum() > 100:
        dd = d[d["ht_gl"].notna()]
        frac = float((dd["ht_gl"] + dd["ht_gv"]).sum() / max((dd["gl"] + dd["gv"]).sum(), 1))
    return ModeloLiga(
        liga=liga, fecha_ref=str(fecha_ref.date()),
        version=f"{C.VERSION_MODELO}-{liga}-{fecha_ref:%Y%m%d}",
        ft=ft,
        corners=ajustar_conteo(df, liga, fecha_ref, "corners"),
        tarjetas=ajustar_conteo(df, liga, fecha_ref, "tarjetas"),
        fraccion_1t=frac,
    )


def guardar(m: ModeloLiga) -> Path:
    carpeta = C.DIR_MODELOS / m.liga
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    ruta.write_text(m.to_json(), encoding="utf-8")
    return ruta


def cargar(liga: str) -> ModeloLiga | None:
    carpeta = C.DIR_MODELOS / liga
    archivos = sorted(carpeta.glob("*.json")) if carpeta.exists() else []
    if not archivos:
        return None
    return ModeloLiga.from_dict(json.loads(archivos[-1].read_text(encoding="utf-8")))


def ajustar_todas(df: pd.DataFrame, progreso=None) -> pd.DataFrame:
    filas = []
    ligas = list(C.LIGAS)
    for i, liga in enumerate(ligas):
        if progreso:
            progreso(i / len(ligas), f"Ajustando modelo {liga}…")
        m = ajustar_liga(df, liga)
        if m is None:
            filas.append({"liga": liga, "estado": "sin datos suficientes"})
            continue
        guardar(m)
        filas.append({
            "liga": liga, "estado": "ok" if m.ft.convergio else "no convergió",
            "partidos": m.ft.n_partidos, "equipos": len(m.ft.equipos),
            "ventaja_local": round(float(np.exp(m.ft.ventaja_local)), 3), "rho": round(m.ft.rho, 3),
            "goles_1T_%": round(m.fraccion_1t * 100, 1),
            "córners": m.corners is not None, "tarjetas": m.tarjetas is not None,
            "xG": m.ft.parametros.get("peso_xg", 0) > 0,
        })
    if progreso:
        progreso(1.0, "Modelos listos")
    return pd.DataFrame(filas)
