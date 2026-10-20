"""Partidos próximos y cuotas de referencia desde la API pública de ESPN (cuotas de DraftKings).

football-data.co.uk solo publica la jornada de las ligas nacionales europeas; entre semana (Champions, Europa
League, Libertadores, Liga 1 de Perú, partidos de BRA/ARG/MEX/MLS…) la Súper boleta quedaba vacía. ESPN publica
el calendario de los próximos días con 1X2 y una línea de goles Más/Menos; con eso el modelo de mercado del bot
(mercados.motor_mercado) calcula las probabilidades. Si el equipo es de una liga con modelo propio, se usa también.
Copias versionadas en datos/raw/espn_proximos/ como el resto de descargas.
"""
from __future__ import annotations

import datetime as dt
import json
import unicodedata

import numpy as np
import pandas as pd
from scipy.stats import poisson

from . import config as C
from . import datos

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
DIR = C.DIR_RAW / "espn_proximos"

# código del bot → liga de ESPN (verificadas el 18/10/2026; Polonia no está en ESPN)
SLUGS = {
    "E0": "eng.1", "E1": "eng.2", "SP1": "esp.1", "SP2": "esp.2", "D1": "ger.1", "D2": "ger.2", "I1": "ita.1",
    "I2": "ita.2", "F1": "fra.1", "F2": "fra.2", "N1": "ned.1", "B1": "bel.1", "P1": "por.1", "T1": "tur.1",
    "G1": "gre.1", "SC0": "sco.1", "BRA": "bra.1", "ARG": "arg.1", "MEX": "mex.1", "USA": "usa.1", "AUT": "aut.1",
    "SWZ": "sui.1", "DNK": "den.1", "NOR": "nor.1", "SWE": "swe.1",
    "UCL": "uefa.champions", "UEL": "uefa.europa", "UECL": "uefa.europa.conf",
    "LIB": "conmebol.libertadores", "SUD": "conmebol.sudamericana", "PER": "per.1",
}


def _get(url: str, **params) -> dict:
    import requests
    import truststore
    truststore.inject_into_ssl()
    r = requests.get(url, params=params, timeout=30)
    datos._registrar_descarga(r.url, f"http {r.status_code}", "", len(r.content), r.ok)
    r.raise_for_status()
    return r.json()


def _decimal(ml) -> float | None:
    """Cuota americana (+150 / -200) → decimal."""
    try:
        v = float(ml)
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return round(1 + v / 100, 3) if v > 0 else round(1 + 100 / abs(v), 3)


def _o25_equivalente(linea: float, c_over: float, c_under: float) -> tuple[float, float] | None:
    """La línea de ESPN no siempre es 2.5: se busca el total de goles (Poisson) que reproduce su Más/Menos y se
    traduce a cuotas justas de Más/Menos 2.5 para el modelo de mercado."""
    try:
        po, pu = 1 / c_over, 1 / c_under
    except (TypeError, ZeroDivisionError):
        return None
    p = po / (po + pu)
    k = int(np.floor(linea))
    lo, hi = 0.05, 10.0
    for _ in range(60):
        m = (lo + hi) / 2
        if poisson.sf(k, m) < p:
            lo = m
        else:
            hi = m
    p25 = float(poisson.sf(2, (lo + hi) / 2))
    p25 = min(max(p25, 0.03), 0.97)
    return round(1 / p25, 3), round(1 / (1 - p25), 3)


def _normal(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    fuera = {"fc", "cf", "ac", "sc", "afc", "cd", "ud", "club", "de", "fk", "sk", "if", "bk", "ss", "us", "as", "rc", "sd",
             "ca", "cr", "se", "ec", "calcio", "the"}
    return " ".join(w for w in "".join(ch if ch.isalnum() else " " for ch in t).split() if w not in fuera)


def _parecido(a: str, b: str) -> float:
    x, y = _normal(a), _normal(b)
    if not x or not y:
        return 0.0
    if x == y:
        return 1.0
    if x in y or y in x:
        return 0.9
    tx, ty = x.split(), y.split()
    comunes = sum(1 for t in tx if t in ty or any(len(t) >= 4 and u.startswith(t[:4]) for u in ty))
    return comunes / max(len(tx), len(ty))


def _equipos_liga(partidos: pd.DataFrame, liga: str) -> list[str]:
    h = partidos[partidos["liga"] == liga]
    if h.empty:
        return []
    h = h[h["fecha"] >= h["fecha"].max() - pd.Timedelta(days=400)]
    return sorted(set(h["local"]) | set(h["visitante"]))


def _mapear(nombre: str, candidatos: list[str]) -> str:
    """Nombre de ESPN → nombre del modelo (football-data) si se reconoce con confianza."""
    mejor, puntos = nombre, 0.0
    for c in candidatos:
        s = _parecido(nombre, c)
        if s > puntos:
            mejor, puntos = c, s
    return mejor if puntos >= 0.6 else nombre


def descargar(dias: int = 3) -> pd.DataFrame:
    """Calendario + cuotas de hoy y los próximos días; guarda una copia versionada."""
    hoy = dt.datetime.now(dt.timezone.utc).date()
    try:
        partidos = datos.cargar_partidos()
    except Exception:
        partidos = pd.DataFrame(columns=["liga", "fecha", "local", "visitante"])
    filas, vistos = [], set()
    for liga, slug in SLUGS.items():
        cand = _equipos_liga(partidos, liga) if liga in C.LIGAS else []
        for d in range(dias + 1):
            fecha = (hoy + dt.timedelta(days=d)).strftime("%Y%m%d")
            try:
                js = _get(BASE + f"{slug}/scoreboard", dates=fecha)
            except Exception:
                continue
            for e in js.get("events", []):
                if e["id"] in vistos or e.get("status", {}).get("type", {}).get("state") != "pre":
                    continue
                c = e["competitions"][0]
                eq = {x["homeAway"]: x for x in c.get("competitors", [])}
                if "home" not in eq or "away" not in eq:
                    continue
                odds = (c.get("odds") or [{}])[0] or {}
                ml = odds.get("moneyline") or {}

                def cierre(d):  # {"close": {"odds": "-160"}} o, en el detalle, {"moneyLine": -160}
                    d = d or {}
                    return _decimal((d.get("close") or d.get("open") or {}).get("odds", d.get("moneyLine")))
                c1 = cierre(ml.get("home")) or _decimal((odds.get("homeTeamOdds") or {}).get("moneyLine"))
                c2 = cierre(ml.get("away")) or _decimal((odds.get("awayTeamOdds") or {}).get("moneyLine"))
                cx = _decimal((odds.get("drawOdds") or {}).get("moneyLine"))
                if not (c1 and c2 and cx):
                    continue
                o25 = None
                tot = odds.get("total") or {}
                ov, un = (tot.get("over") or {}).get("close") or {}, (tot.get("under") or {}).get("close") or {}
                try:
                    linea = float(str(ov.get("line", "")).lstrip("ou") or odds.get("overUnder"))
                    co, cu = _decimal(ov.get("odds")), _decimal(un.get("odds"))
                    if co and cu:
                        o25 = _o25_equivalente(linea, co, cu)
                except (TypeError, ValueError):
                    o25 = None
                vistos.add(e["id"])
                inicio = pd.Timestamp(c.get("date") or e["date"]).tz_convert(C.ZONA_HORARIA).tz_localize(None)
                h, a = eq["home"]["team"], eq["away"]["team"]
                filas.append({
                    "liga": liga, "local": _mapear(h["displayName"], cand), "visitante": _mapear(a["displayName"], cand),
                    "inicio": inicio, "c_1": c1, "c_x": cx, "c_2": c2,
                    "c_o25": o25[0] if o25 else np.nan, "c_u25": o25[1] if o25 else np.nan,
                    "espn_id": e["id"], "escudo_l": h.get("logo"), "escudo_v": a.get("logo"),
                    "nombre_espn_l": h["displayName"], "nombre_espn_v": a["displayName"],
                })
    df = pd.DataFrame(filas)
    if not df.empty:
        DIR.mkdir(parents=True, exist_ok=True)
        df.to_csv(DIR / f"{dt.datetime.now():%Y%m%d_%H%M%S}.csv", index=False, encoding="utf-8")
    return df


def cargar() -> pd.DataFrame:
    """Última copia descargada (solo partidos que aún no empiezan)."""
    if not DIR.exists():
        return pd.DataFrame()
    archivos = sorted(DIR.glob("*.csv"))
    if not archivos:
        return pd.DataFrame()
    df = pd.read_csv(archivos[-1], encoding="utf-8")
    df["inicio"] = pd.to_datetime(df["inicio"], errors="coerce")
    ahora = pd.Timestamp.now(tz=C.ZONA_HORARIA).tz_localize(None)
    df = df[df["inicio"] >= ahora - pd.Timedelta(hours=2)]
    df["fecha"] = df["inicio"].dt.normalize()
    df["hora"] = df["inicio"].dt.strftime("%H:%M")
    df["fuente_consulta"] = archivos[-1].stem
    return df.reset_index(drop=True)


def logos() -> dict[str, str]:
    """Nombre del equipo (como lo usa el bot) → escudo de ESPN, para equipos sin escudo propio."""
    df = cargar()
    out = {}
    for _, f in df.iterrows():
        for n, u in ((f["local"], f.get("escudo_l")), (f["visitante"], f.get("escudo_v"))):
            if isinstance(u, str) and u.startswith("http"):
                out[n] = u
    return out
