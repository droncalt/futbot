"""Modelo de tiros al arco por jugador (mercado de Betano «<Jugador> Tiros al Arco»).

Tiros al arco esperados en un partido:

    λ = tasa por 90' del jugador × (minutos / 90) × factor de la defensa rival × factor de localía

* Tasa por 90': Gamma-Poisson. El prior es la media de su grupo de posición en su liga, con una fuerza
  de κ partidos de 90'; el posterior suma sus apariciones (las recientes pesan más, decaimiento ξ) y
  corrige por la defensa de los rivales que ya enfrentó. La incertidumbre de la tasa hace que la
  distribución final sea binomial negativa (más ancha que una Poisson para jugadores con pocos datos).
* Defensa rival: modelo de conteo de motor/modelo.py sobre los tiros al arco por equipo de
  football-data (arco_l / arco_v). factor = exp(β · (defensa_rival ± ventaja_local / 2)).
* Minutos: dependen de la alineación, que el modelo NO conoce. Por eso hay escenarios:
  - «titular»: minutos de sus últimas titularidades;
  - «suplente»: minutos de sus últimas entradas desde el banco;
  - «juega (titular o suplente)»: mezcla de ambos con su frecuencia reciente de titular.
  En Betano, por defecto, la selección de un jugador que no es titular se anula: la probabilidad relevante
  es la de «titular» (ver REGLA_BETANO). Betano liquida con Opta, que cuenta como tiro al arco también los
  bloqueos del último defensor; Understat no, así que con esa fuente el bot queda apenas conservador.

κ, ξ y β se eligen en el backtest walk-forward (motor/evaluacion.py: backtest_jugadores).
"""
from __future__ import annotations

import datetime as dt
import json
import unicodedata
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from . import config as C
from . import datos
from . import jugadores as J
from .modelo import ModeloConteo, ajustar_conteo

N_MINUTOS = 10            # últimas titularidades / suplencias que definen los minutos de cada escenario
MIN_MUESTRA_MINUTOS = 4   # si tiene menos, se completa con lo típico de su posición
LINEAS = (1, 2, 3)        # líneas con backtest
# En Betano, «Anular jugadores no titulares» viene activo por defecto: si el jugador no es titular, su
# selección se anula (support.betano.pe, artículo 38361766676765). Por eso el escenario que importa es «titular».
ESCENARIOS = {"titular": "Titular", "sin_confirmar": "Juega (titular o suplente)", "suplente": "Entra desde el banco"}
ESCENARIO_DEFECTO = "titular"
REGLA_BETANO = ("En Betano, con «Anular jugadores no titulares» (activo por defecto), si el jugador no sale de titular "
                "su selección se anula; en un Bet Builder, una selección anulada anula todo el Bet Builder. Por eso la "
                "probabilidad que importa es la de «Titular». Si desactivaste esa opción, usa «Juega (titular o suplente)».")
RUTA_RESUMEN = C.DIR_EVALUACION / "resumen_jugadores.json"
COLUMNAS = ("tiros_arco", "goles", "asistencias")
# Otras estadísticas del jugador con el mismo modelo (Gamma-Poisson + defensa rival + minutos de titular);
# cada una tiene su propio backtest (evaluacion_jugadores.backtest_eventos) en resumen_jugadores_<columna>.json.
EVENTOS = {"goles": "Marca gol", "asistencias": "Da asistencia", "ga": "Marca o asiste"}


def ruta_resumen(columna: str) -> "C.Path":
    return RUTA_RESUMEN if columna == "tiros_arco" else C.DIR_EVALUACION / f"resumen_jugadores_{columna}.json"


@dataclass(frozen=True)
class Params:
    kappa: float = C.JUG_KAPPA
    xi: float = C.JUG_XI
    beta: float = C.JUG_BETA_RIVAL
    # El que entra desde el banco tira más por minuto (partido abierto, piernas frescas): factor γ estimado
    # comparando a cada jugador consigo mismo como titular. False = mismo ritmo que de titular.
    suplente: bool = True
    # True = Poisson con la tasa estimada (sin sumar la incertidumbre de la tasa: colas más finas)
    poisson: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def resumen_backtest() -> dict:
    try:
        return json.loads(RUTA_RESUMEN.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def recalibrar(escenario: str, k: int, p, recal: dict | None):
    """Corrección logística a + b·logit(p) estimada en el backtest; solo si el backtest la aprobó."""
    if not recal or not recal.get("usar"):
        return p
    c = recal.get("coeficientes", {}).get(f"{escenario}|{k}")
    if not c:
        return p
    return 1 / (1 + np.exp(-(c[0] + c[1] * _logit(p))))


def params_vigentes() -> tuple[Params, str]:
    r = resumen_backtest()
    if r.get("parametros"):
        return Params(**r["parametros"]), f"elegidos en el backtest del {r.get('fecha', '?')}"
    return Params(), "valores por defecto (aún no hay backtest de jugadores)"


def modelos_arco(partidos: pd.DataFrame, fecha_ref) -> dict:
    """Modelo de tiros al arco por equipo de cada liga con datos de jugadores (solo datos < fecha_ref)."""
    return {liga: ajustar_conteo(partidos, liga, fecha_ref, "arco") for liga in C.LIGAS_JUGADORES}


def _defensa(m: ModeloConteo | None) -> tuple[dict, float]:
    if m is None:
        return {}, 0.0
    return dict(zip(m.equipos, m.defensa)), float(m.ventaja_local)


def _moda(s: pd.Series):
    return s.value_counts().index[0]


# --- historial en arreglos ----------------------------------------------------------

class Preparado:
    """Historial de apariciones anterior a fecha_ref, en arreglos numpy (rápido para el backtest).

    `ap` debe traer equipo_fd y rival_fd (jugadores.con_nombres_fd).
    """

    def __init__(self, ap: pd.DataFrame, fecha_ref, arco: dict, columna: str = "tiros_arco"):
        self.fecha_ref = pd.Timestamp(fecha_ref)
        tr = ap[(ap["fecha"] < self.fecha_ref)
                & (ap["fecha"] >= self.fecha_ref - pd.Timedelta(days=C.VENTANA_DIAS_JUGADORES))]
        tr = tr.sort_values("fecha", kind="stable")
        self.ids, self.code = np.unique(tr["jugador_id"].to_numpy(str), return_inverse=True)
        n = len(self.ids)
        self.n = n
        self.dias = (self.fecha_ref - tr["fecha"]).dt.days.to_numpy(float)
        # columnas disponibles para el mismo historial (se elige una con usar())
        self._cols = {c: tr[c].to_numpy(float) for c in COLUMNAS if c in tr.columns}
        if "goles" in self._cols and "asistencias" in self._cols:
            self._cols["ga"] = self._cols["goles"] + self._cols["asistencias"]
        self.y = self._cols.get(columna, tr["tiros_arco"].to_numpy(float))
        self.mins = tr["minutos"].to_numpy(float)
        self.es_tit = tr["titular"].to_numpy(bool)
        self.defensas = {liga: _defensa(m) for liga, m in arco.items()}
        d_riv, s_h = np.zeros(len(tr)), np.zeros(len(tr))
        for liga, (dmap, h) in self.defensas.items():
            m = (tr["liga"] == liga).to_numpy()
            if m.any():
                d_riv[m] = tr.loc[m, "rival_fd"].map(dmap).fillna(0.0).to_numpy(float)
                s_h[m] = np.where(tr.loc[m, "es_local"].to_numpy(bool), h / 2, -h / 2)
        self.d_rival, self.s_h = d_riv, s_h

        # una fila por jugador: su última aparición y su posición habitual
        tr = tr.assign(_c=self.code)
        ult = tr.drop_duplicates("_c", keep="last").set_index("_c").sort_index()
        recientes = tr.groupby("_c").tail(20)
        grupo = recientes.groupby("_c")["grupo_pos"].agg(_moda).reindex(range(n)).fillna("MED")
        self.info = pd.DataFrame({
            "jugador_id": self.ids, "jugador": ult["jugador"].to_numpy(), "liga": ult["liga"].to_numpy(),
            "equipo": ult["equipo"].to_numpy(), "equipo_fd": ult["equipo_fd"].to_numpy(),
            "grupo_pos": grupo.to_numpy(), "ultima_fecha": ult["fecha"].to_numpy(),
            "partidos": np.bincount(self.code, minlength=n), "minutos": np.bincount(self.code, self.mins, n).astype(int),
            "titularidades": np.bincount(self.code, tr["titular"].to_numpy(float), n).astype(int),
            "tiros_arco": np.bincount(self.code, self.y, n).astype(int),
        })
        # prior: media del grupo de posición en la liga de su última aparición
        claves = self.info["liga"].astype(str) + "|" + self.info["grupo_pos"].astype(str)
        self.claves, self.key_j = np.unique(claves.to_numpy(str), return_inverse=True)
        self.key_row = self.key_j[self.code]

        # minutos por escenario (últimas N, completadas con lo típico de la posición)
        tit = tr["titular"].to_numpy(bool)
        tipico_tit = tr[tit].groupby("grupo_pos")["minutos"].median()
        tipico_sup = tr[~tit].groupby("grupo_pos")["minutos"].median()
        self.min_tit = self._lista_minutos(tr[tit], n, self.info["grupo_pos"].map(tipico_tit).fillna(80.0).to_numpy())
        self.min_sup = self._lista_minutos(tr[~tit], n, self.info["grupo_pos"].map(tipico_sup).fillna(20.0).to_numpy())
        ult10 = tr.groupby("_c").tail(N_MINUTOS)
        nt = ult10.groupby("_c")["titular"].sum().reindex(range(n)).fillna(0).to_numpy(float)
        na = ult10.groupby("_c").size().reindex(range(n)).fillna(0).to_numpy(float)
        self.p_tit = (nt + 0.5) / (na + 1.0)   # P(titular | juega), con un leve encogimiento a 50 %

    def usar(self, columna: str) -> "Preparado":
        """Cambia la estadística que se modela (tiros_arco, goles, asistencias o ga = gol o asistencia)."""
        self.y = self._cols[columna]
        return self

    @staticmethod
    def _lista_minutos(d: pd.DataFrame, n: int, tipico: np.ndarray) -> np.ndarray:
        out = np.full((n, N_MINUTOS), np.nan)
        if len(d):
            ult = d.groupby("_c").tail(N_MINUTOS)
            orden = ult.groupby("_c").cumcount().to_numpy()
            out[ult["_c"].to_numpy(), orden] = ult["minutos"].to_numpy(float)
        cuenta = (~np.isnan(out)).sum(1)
        for i in np.where(cuenta < MIN_MUESTRA_MINUTOS)[0]:
            out[i, cuenta[i]:MIN_MUESTRA_MINUTOS] = tipico[i]
        return out

    def _gamma(self, p: Params, w: np.ndarray, e0: np.ndarray) -> float:
        """Ritmo como suplente / ritmo del MISMO jugador como titular (no se compara entre jugadores)."""
        if not p.suplente:
            return 1.0
        t = self.es_tit
        k = len(self.claves)
        mu = np.bincount(self.key_row[t], (w * self.y)[t], k) / np.maximum(np.bincount(self.key_row[t], (w * e0)[t], k), 1e-9)
        tasa_tit = (p.kappa * np.maximum(mu[self.key_j], 1e-3) + np.bincount(self.code[t], (w * self.y)[t], self.n)) / (
            p.kappa + np.bincount(self.code[t], (w * e0)[t], self.n))
        esperado = (w * e0 * tasa_tit[self.code])[~t].sum()
        return float(np.clip((w * self.y)[~t].sum() / esperado, 0.5, 2.5)) if esperado > 0 else 1.0

    def posterior(self, p: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(a, b, media_prior) de la tasa de tiros al arco por 90' de titular de cada jugador (Gamma(a, b))."""
        w = np.exp(-p.xi * self.dias)
        e0 = self.mins / 90.0 * np.exp(p.beta * (self.d_rival + self.s_h))
        self.gamma = self._gamma(p, w, e0)
        e = np.where(self.es_tit, e0, e0 * self.gamma)
        sy = np.bincount(self.code, w * self.y, self.n)
        se = np.bincount(self.code, w * e, self.n)
        k = len(self.claves)
        mu_k = np.bincount(self.key_row, w * self.y, k) / np.maximum(np.bincount(self.key_row, w * e, k), 1e-9)
        mu = np.maximum(mu_k[self.key_j], 1e-3)
        a, b = p.kappa * mu + sy, p.kappa + se
        if p.poisson:  # misma media, varianza de la tasa ≈ 0  ->  binomial negativa ≈ Poisson
            a, b = a * 1e4, b * 1e4
        return a, b, mu

    def factor(self, liga: str, rival_fd: str | None, es_local: bool | None, beta: float) -> float:
        dmap, h = self.defensas.get(liga, ({}, 0.0))
        d = dmap.get(rival_fd, 0.0) if rival_fd else 0.0
        s = 0.0 if es_local is None else (h / 2 if es_local else -h / 2)
        return float(np.exp(beta * (d + s)))


def prob_al_menos(a: np.ndarray, b: np.ndarray, t: np.ndarray, lineas=LINEAS) -> dict[int, np.ndarray]:
    """P(tiros al arco ≥ k) promediando sobre la lista de exposiciones t (n × m, con NaN de relleno)."""
    a, b = np.asarray(a, float)[:, None], np.asarray(b, float)[:, None]
    mascara = ~np.isnan(t)
    q = b / (b + np.where(mascara, t, 0.0))
    out = {}
    for k in lineas:
        sf = nbinom.sf(k - 1, a, q)
        out[k] = np.where(mascara, sf, 0.0).sum(1) / np.maximum(mascara.sum(1), 1)
    return out


def probabilidades(prep: Preparado, idx: np.ndarray, a: np.ndarray, b: np.ndarray, fac: np.ndarray,
                   lineas=LINEAS) -> dict[str, dict[int, np.ndarray]]:
    """Las tres versiones (titular / suplente / sin confirmar) para los jugadores idx con factor fac.

    Usa el γ de suplente del último prep.posterior() (llamarlo antes con los mismos parámetros)."""
    fac = np.asarray(fac, float)[:, None]
    tit = prob_al_menos(a[idx], b[idx], prep.min_tit[idx] / 90.0 * fac, lineas)
    sup = prob_al_menos(a[idx], b[idx], prep.min_sup[idx] / 90.0 * fac * getattr(prep, "gamma", 1.0), lineas)
    pt = prep.p_tit[idx]
    sin = {k: pt * tit[k] + (1 - pt) * sup[k] for k in lineas}
    return {"titular": tit, "suplente": sup, "sin_confirmar": sin}


# --- modelo listo para usar en la app -------------------------------------------------

def _norm(s) -> str:
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


class ModeloJugadores:
    def __init__(self, prep: Preparado, params: Params, fuente: str, origen_params: str = "", recal: dict | None = None):
        self.prep, self.params, self.fuente, self.origen_params = prep, params, fuente, origen_params
        self.a, self.b, mu = prep.posterior(params)
        self.gamma = prep.gamma
        self.recal = resumen_backtest().get("recalibracion", {}) if recal is None else recal
        t = prep.info.copy()
        t["tasa90"] = self.a / self.b
        t["prior90"] = mu
        t["p_titular"] = prep.p_tit
        t["min_titular"] = np.nanmean(prep.min_tit, 1)
        t["min_suplente"] = np.nanmean(prep.min_sup, 1)
        t["posicion"] = t["grupo_pos"].map(J.NOMBRE_GRUPO)
        t["_nombre"] = t["jugador"].map(_norm)
        self.tabla = t
        self.pos = {j: i for i, j in enumerate(prep.ids)}

    @property
    def fecha_ref(self) -> pd.Timestamp:
        return self.prep.fecha_ref

    def jugadores_de(self, liga: str, equipo_fd: str, dias: int = 150) -> pd.DataFrame:
        """Plantilla según los datos: su última aparición fue con ese equipo, hace menos de `dias` días."""
        t = self.tabla
        d = t[(t["equipo_fd"] == equipo_fd) & (t["grupo_pos"] != "POR")
              & (t["ultima_fecha"] >= self.fecha_ref - pd.Timedelta(days=dias))]
        if liga in C.LIGAS_JUGADORES:
            d = d[d["liga"] == liga]
        return d.sort_values("tasa90", ascending=False)

    def buscar(self, texto: str, n: int = 30) -> pd.DataFrame:
        q = _norm(texto)
        t = self.tabla[self.tabla["grupo_pos"] != "POR"]
        d = t[t["_nombre"].str.contains(q, regex=False)] if q else t
        return d.sort_values(["ultima_fecha", "minutos"], ascending=False).head(n)

    def predecir(self, jugador_id: str, liga: str | None, rival_fd: str | None, es_local: bool | None) -> dict | None:
        i = self.pos.get(jugador_id)
        if i is None:
            return None
        info = self.tabla.iloc[i]
        liga_f = liga if liga in C.LIGAS_JUGADORES else info["liga"]
        conocido = bool(rival_fd) and rival_fd in self.prep.defensas.get(liga_f, ({}, 0))[0]
        fac = self.prep.factor(liga_f, rival_fd if conocido else None, es_local, self.params.beta)
        idx = np.array([i])
        self.prep.gamma = self.gamma  # por si otro ajuste usó el mismo historial
        pr = probabilidades(self.prep, idx, self.a, self.b, np.array([fac]))
        out = {e: {k: float(recalibrar(e, k, v[0], self.recal)) for k, v in pr[e].items()} for e in pr}
        avisos = []
        if not conocido:
            avisos.append("Rival sin datos de tiros al arco en esta liga: se usó una defensa promedio.")
        if info["minutos"] < 450:
            avisos.append(f"{info['jugador']} tiene solo {int(info['minutos'])}' en la muestra: la estimación "
                          "se apoya mucho en la media de su posición.")
        dias = (self.fecha_ref - pd.Timestamp(info["ultima_fecha"])).days
        if dias > 21:
            avisos.append(f"Su última aparición en los datos fue hace {dias} días (¿lesión, sanción o suplencia?).")
        return {
            "jugador_id": jugador_id, "jugador": info["jugador"], "equipo": info["equipo_fd"] or info["equipo"],
            "posicion": info["posicion"], "probs": out, "factor_rival": fac, "rival_conocido": conocido,
            "tasa90": float(info["tasa90"]), "prior90": float(info["prior90"]),
            "lam_titular": float(info["tasa90"] * np.nanmean(self.prep.min_tit[i]) / 90 * fac),
            "min_titular": float(info["min_titular"]), "min_suplente": float(info["min_suplente"]),
            "p_titular": float(info["p_titular"]), "partidos": int(info["partidos"]),
            "minutos": int(info["minutos"]), "tiros_arco": int(info["tiros_arco"]),
            "ultima_fecha": str(pd.Timestamp(info["ultima_fecha"]).date()), "avisos": avisos,
        }

    def tabla_partido(self, liga: str, local: str, visitante: str, escenario: str = ESCENARIO_DEFECTO,
                      n: int = 12) -> dict[str, pd.DataFrame]:
        out = {}
        for lado, eq, rival, es_local in (("local", local, visitante, True), ("visitante", visitante, local, False)):
            filas = []
            for jid in self.jugadores_de(liga, eq)["jugador_id"].head(n):
                r = self.predecir(jid, liga, rival, es_local)
                if r is None:
                    continue
                p = r["probs"][escenario]
                filas.append({"jugador_id": jid, "Jugador": r["jugador"], "Posición": r["posicion"],
                              "Titular (últ. 10)": r["p_titular"], "Min. si es titular": r["min_titular"],
                              "Tiros al arco /90'": r["tasa90"], "1+": p[1], "2+": p[2], "3+": p[3],
                              "Partidos en la muestra": r["partidos"], "Última aparición": r["ultima_fecha"]})
            out[lado] = pd.DataFrame(filas)
        return out


_cache: dict = {}


def modelo_vigente(partidos: pd.DataFrame | None = None, fuente: str | None = None) -> ModeloJugadores | None:
    """Modelo ajustado con todos los datos hasta hoy y los parámetros del backtest (con caché)."""
    fuente = fuente or J.fuente_activa()
    ap = J.cargar_apariciones(fuente)
    if ap.empty:
        return None
    if partidos is None:
        partidos = datos.cargar_partidos()
    params, origen = params_vigentes()
    fecha_ref = pd.Timestamp(dt.date.today() + dt.timedelta(days=1))
    resumen_mtime = RUTA_RESUMEN.stat().st_mtime if RUTA_RESUMEN.exists() else 0
    clave = (fuente, J._firma_raw(fuente), datos._firma(), params, fecha_ref, resumen_mtime)
    if _cache.get("clave") == clave:
        return _cache["modelo"]
    ap = J.con_nombres_fd(ap, partidos)
    prep = Preparado(ap, fecha_ref, modelos_arco(partidos, fecha_ref))
    m = ModeloJugadores(prep, params, fuente, origen)
    _cache.update(clave=clave, modelo=m)
    return m


# --- API para el chat, la interfaz y bot.py ----------------------------------------------------

def jugadores_partido(liga: str, local: str, visitante: str, escenario: str = ESCENARIO_DEFECTO,
                      n: int = 8, jugador: str | None = None) -> dict:
    """Jugadores de ambos equipos con P(tiros al arco ≥ 1, 2, 3), cuota justa y evidencia del backtest.

    Devuelve {"disponible", "motivo"?, "calibrado", "calibracion", "regla_betano", "escenario", "fuente",
    "local": [fila, ...], "visitante": [...], "busqueda"?: [...]}. Cada fila trae "seleccion": los argumentos
    de mercados.Seleccion (sin la opción): M.Seleccion("jug_arco", "2+", 1.5, **fila["seleccion"]).
    `jugador` filtra por nombre (sin tildes); si no está en estos equipos, se busca en todas las ligas.
    """
    est = estado_calibracion()
    out = {"disponible": False, "calibrado": est["calibrado"], "calibracion": est["texto"],
           "regla_betano": REGLA_BETANO, "escenario": escenario, "local": [], "visitante": []}
    if not est["hay_backtest"]:
        out["motivo"] = est["texto"]
        return out
    mj = modelo_vigente()
    if mj is None:
        out["motivo"] = "No hay datos de jugadores: ejecuta 'python -P bot.py jugadores --descargar'."
        return out
    out.update(disponible=True, fuente=J.FUENTES[mj.fuente], datos_hasta=str(mj.tabla["ultima_fecha"].max())[:10],
               parametros=mj.params.to_dict(), origen_parametros=mj.origen_params)

    def fila(r, lado):
        p = r["probs"][escenario]
        return {"jugador_id": r["jugador_id"], "jugador": r["jugador"], "equipo": r["equipo"], "posicion": r["posicion"],
                "seleccion": {"jugador": r["jugador_id"], "jugador_nombre": r["jugador"], "lado": lado, "escenario": escenario},
                "prob": {f"{k}+": round(v, 4) for k, v in p.items()},
                "cuota_justa": {f"{k}+": round(1 / v, 2) for k, v in p.items() if v > 0},
                "evidencia": {f"{k}+": evidencia(k, escenario, v) for k, v in p.items()},
                "escenarios": {ESCENARIOS[e]: {f"{k}+": round(v, 4) for k, v in r["probs"][e].items()} for e in ESCENARIOS},
                "tiros_al_arco_por_90": round(r["tasa90"], 3), "media_de_su_posicion_por_90": round(r["prior90"], 3),
                "titular_en_ultimas_10": round(r["p_titular"], 3), "minutos_si_es_titular": round(r["min_titular"], 1),
                "factor_defensa_rival": round(r["factor_rival"], 3), "partidos_muestra": r["partidos"],
                "ultima_aparicion": r["ultima_fecha"], "avisos": r["avisos"]}
    for lado, eq, rival, es_local in (("local", local, visitante, True), ("visitante", visitante, local, False)):
        plantel = mj.jugadores_de(liga, eq)  # copas: su plantel según su liga (rival de otra liga = defensa promedio)
        if jugador:
            plantel = plantel[plantel["_nombre"].str.contains(_norm(jugador), regex=False)]
        for jid in plantel["jugador_id"].head(n):
            r = mj.predecir(jid, liga, rival, es_local)
            if r:
                out[lado].append(fila(r, lado))
    if jugador and not (out["local"] or out["visitante"]):  # otra competición o de otro equipo: sin rival conocido
        out["busqueda"] = [fila(r, None) for r in (mj.predecir(j, None, None, None) for j in mj.buscar(jugador, 5)["jugador_id"]) if r]
        out["aviso_busqueda"] = ("Jugador fuera de los equipos del partido (o competición sin datos): se usó una defensa "
                                 "rival promedio. Indica en la selección si su equipo juega de local o de visitante.")
    return out


# --- evidencia y calibración (para la app) ----------------------------------------------

def estado_calibracion() -> dict:
    """{'hay_backtest', 'calibrado', 'texto'} para mostrar junto a cada probabilidad de jugador."""
    r = resumen_backtest()
    if not r:
        return {"hay_backtest": False, "calibrado": False,
                "texto": "Sin backtest de tiros al arco todavía: no se muestran probabilidades de jugadores."}
    if r.get("fuente") != J.fuente_activa():
        return {"hay_backtest": True, "calibrado": False, "fuente": r.get("fuente"),
                "texto": (f"El backtest de jugadores se hizo con {J.FUENTES.get(r.get('fuente'), '?')} pero ahora la fuente es "
                          f"{J.FUENTES[J.fuente_activa()]}: vuelve a ejecutarlo antes de confiar en estas probabilidades.")}
    cal = r.get("calibrado", {})
    ok = all(v.get("calibrado") for v in cal.values()) if cal else False
    malos = [k for k, v in cal.items() if not v.get("calibrado")]
    texto = (f"Backtest {r.get('periodo_validacion', '')}: calibrado (error medio ≤ {r.get('criterio', {}).get('ece_max', 0.02):.0%})."
             if ok else "Backtest: NO bien calibrado en " + ", ".join(malos) + ". Usa estas probabilidades con cautela.")
    return {"hay_backtest": True, "calibrado": ok, "texto": texto, "fuente": r.get("fuente")}


def evento(k: int, escenario: str) -> str:
    return f"Tiros al arco {k}+ · {ESCENARIOS.get(escenario, escenario)}"


def evidencia(k: int, escenario: str, p: float | None, corta: bool = False) -> str | None:
    if p is None:
        return None
    tabla = resumen_backtest().get("calibracion_por_evento", {}).get(evento(k, escenario))
    if not tabla:
        return None
    for b in tabla:
        if b["lo"] < p <= b["hi"] and b["n"] >= 30:
            dif = b["prob_estimada"] - b["frecuencia_real"]
            nota = (" ⚠️ el bot fue demasiado optimista en este rango" if dif > 0.05 else
                    " (en este rango pasó más seguido de lo que dijo el bot)" if dif < -0.05 else "")
            if corta:
                return f"{b['frecuencia_real']:.0%} real en {b['n']:,} casos" + (" ⚠️" if dif > 0.05 else "")
            return (f"Backtest: cuando el bot dio ~{b['prob_estimada']:.0%} a «{k}+» ({ESCENARIOS.get(escenario)}), "
                    f"se cumplió el {b['frecuencia_real']:.0%} ({b['n']:,} casos).{nota}")
    return None


# --- liquidación ---------------------------------------------------------------------

def resultado_real(jugador_id: str, liga: str, fecha: str | None, equipo_fd: str | None,
                   partidos: pd.DataFrame, creada: str | None = None) -> int | None:
    """Tiros al arco del jugador en ese partido, o None si aún no hay datos o si no fue titular
    (Betano anula por defecto la selección de un jugador no titular: queda para marcarla a mano)."""
    fuente = "apifootball" if jugador_id.startswith("af") else "understat"
    ap = J.cargar_apariciones(fuente)
    if ap.empty:
        return None
    ref = pd.Timestamp(fecha) if fecha else pd.Timestamp(creada).normalize()
    lo = ref - pd.Timedelta(days=3)
    hi = ref + pd.Timedelta(days=3) if fecha else ref + pd.Timedelta(days=10)
    d = ap[(ap["jugador_id"] == jugador_id) & (ap["fecha"] >= lo) & (ap["fecha"] <= hi)]
    if len(d):
        f = d.sort_values("fecha").iloc[0]
        return int(f["tiros_arco"]) if bool(f["titular"]) else None
    return None


# --- otras estadísticas del jugador: gol, asistencia, gol o asistencia --------------------

_cache_eventos: dict = {}


def resumen_evento(columna: str) -> dict:
    try:
        return json.loads(ruta_resumen(columna).read_text(encoding="utf-8"))
    except Exception:
        return {}


def modelo_evento(columna: str, partidos: pd.DataFrame | None = None) -> ModeloJugadores | None:
    """Modelo de goles / asistencias / gol o asistencia, con los parámetros y la recalibración de SU backtest."""
    r = resumen_evento(columna)
    if not r.get("parametros"):
        return None
    fuente = J.fuente_activa()
    ap = J.cargar_apariciones(fuente)
    if ap.empty or ("asistencias" not in ap.columns and columna != "goles"):
        return None
    if partidos is None:
        partidos = datos.cargar_partidos()
    fecha_ref = pd.Timestamp(dt.date.today() + dt.timedelta(days=1))
    clave = (columna, fuente, J._firma_raw(fuente), datos._firma(), fecha_ref, ruta_resumen(columna).stat().st_mtime)
    if _cache_eventos.get(columna, (None,))[0] == clave:
        return _cache_eventos[columna][1]
    ap = J.con_nombres_fd(ap, partidos)
    prep = Preparado(ap, fecha_ref, modelos_arco(partidos, fecha_ref), columna)
    m = ModeloJugadores(prep, Params(**r["parametros"]), fuente, f"backtest del {r.get('fecha', '?')}", r.get("recalibracion", {}))
    _cache_eventos[columna] = (clave, m)
    return m


def eventos_partido(liga: str, local: str, visitante: str, n: int = 6) -> list[dict]:
    """Jugadores de ambos equipos con P(tiro al arco 1+/2+/3+) y, si su backtest existe, P(gol), P(asistencia)
    y P(gol o asistencia), todo en el escenario «titular» (Betano anula al jugador que no es titular)."""
    r = jugadores_partido(liga, local, visitante, ESCENARIO_DEFECTO, n=n)
    if not r.get("disponible"):
        return []
    otros = {c: modelo_evento(c) for c in EVENTOS}
    out = []
    for lado, eq, rival, es_local in (("local", local, visitante, True), ("visitante", visitante, local, False)):
        for f in r[lado]:
            fila = {"jugador_id": f["jugador_id"], "nombre": f["jugador"], "lado": lado,
                    "p1": f["prob"].get("1+"), "p2": f["prob"].get("2+"), "p3": f["prob"].get("3+"),
                    "titular": f.get("titular_en_ultimas_10"), "ultima": f.get("ultima_aparicion"),
                    "arco90": f.get("tiros_al_arco_por_90"), "avisos": (f.get("avisos") or [])[:2]}
            for c, m in otros.items():
                pr = m.predecir(f["jugador_id"], liga, rival, es_local) if m else None
                if pr:
                    fila[c] = round(float(pr["probs"]["titular"][1]), 4)
            out.append(fila)
    return out
