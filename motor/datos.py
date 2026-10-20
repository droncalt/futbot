"""Descarga, versionado, normalización y control de calidad de los datos.

Cada archivo descargado se guarda como una copia con fecha en datos/raw/<nombre>/ solo
si su contenido cambió (hash distinto). Nunca se borra una versión anterior.
Cada consulta queda registrada en datos/registro_descargas.csv.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:  # Avast intercepta HTTPS en esta PC: usar los certificados de Windows
    import truststore

    truststore.inject_into_ssl()
except Exception:  # pragma: no cover
    pass
import requests

from . import config as C

CABECERAS = {"User-Agent": "Mozilla/5.0 (bot-analitico-personal)"}

# --- columnas -------------------------------------------------------------------

MAPA_EUROPA = {
    "Div": "liga", "Date": "fecha", "Time": "hora", "HomeTeam": "local", "AwayTeam": "visitante",
    "FTHG": "gl", "FTAG": "gv", "FTR": "res", "HTHG": "ht_gl", "HTAG": "ht_gv",
    "HxG": "xg_l", "AxG": "xg_v", "HS": "rem_l", "AS": "rem_v", "HST": "arco_l", "AST": "arco_v",
    "HF": "faltas_l", "AF": "faltas_v", "HC": "corn_l", "AC": "corn_v",
    "HY": "ama_l", "AY": "ama_v", "HR": "roj_l", "AR": "roj_v", "Referee": "arbitro",
}

# (destino, [columnas candidatas en orden de preferencia])
CUOTAS = [
    # apertura / del momento: promedio del mercado
    ("c_1", ["AvgH"]), ("c_x", ["AvgD"]), ("c_2", ["AvgA"]),
    ("c_o25", ["Avg>2.5"]), ("c_u25", ["Avg<2.5"]),
    # apertura: casa "afilada" (Pinnacle si existe, si no Betfair Exchange)
    ("s_1", ["PSH", "BFEH"]), ("s_x", ["PSD", "BFED"]), ("s_2", ["PSA", "BFEA"]),
    ("s_o25", ["P>2.5", "BFE>2.5"]), ("s_u25", ["P<2.5", "BFE<2.5"]),
    # cierre: promedio
    ("cc_1", ["AvgCH"]), ("cc_x", ["AvgCD"]), ("cc_2", ["AvgCA"]),
    ("cc_o25", ["AvgC>2.5"]), ("cc_u25", ["AvgC<2.5"]),
    # cierre: afilada
    ("sc_1", ["PSCH", "BFECH"]), ("sc_x", ["PSCD", "BFECD"]), ("sc_2", ["PSCA", "BFECA"]),
    ("sc_o25", ["PC>2.5", "BFEC>2.5"]), ("sc_u25", ["PC<2.5", "BFEC<2.5"]),
]

COLUMNAS_NUM = [
    "gl", "gv", "ht_gl", "ht_gv", "xg_l", "xg_v", "rem_l", "rem_v", "arco_l", "arco_v",
    "faltas_l", "faltas_v", "corn_l", "corn_v", "ama_l", "ama_v", "roj_l", "roj_v",
] + [c for c, _ in CUOTAS]


# --- descarga y versionado -------------------------------------------------------

def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def ultimo_snapshot(nombre: str) -> Path | None:
    carpeta = C.DIR_RAW / nombre
    if not carpeta.exists():
        return None
    archivos = sorted(carpeta.glob("*.csv"))
    return archivos[-1] if archivos else None


def _registrar_descarga(url: str, estado: str, h: str, n: int, cambio: bool) -> None:
    nuevo = not C.LOG_DESCARGAS.exists()
    with open(C.LOG_DESCARGAS, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["fecha_consulta", "url", "estado", "hash", "bytes", "contenido_nuevo"])
        w.writerow([dt.datetime.now().isoformat(timespec="seconds"), url, estado, h, n, cambio])


def descargar(nombre: str, url: str) -> tuple[Path | None, bool, str]:
    """Descarga url y la guarda como nueva versión si cambió. Devuelve (ruta, cambió, estado)."""
    try:
        r = requests.get(url, headers=CABECERAS, timeout=45)
    except Exception as e:  # sin internet, etc.
        _registrar_descarga(url, f"error: {type(e).__name__}", "", 0, False)
        return ultimo_snapshot(nombre), False, f"error de conexión ({type(e).__name__})"
    if r.status_code != 200 or r.content.lstrip()[:15].lower().startswith(b"<!doctype"):
        _registrar_descarga(url, f"http {r.status_code}", "", len(r.content), False)
        return ultimo_snapshot(nombre), False, f"no disponible (HTTP {r.status_code})"
    h = _hash(r.content)
    previo = ultimo_snapshot(nombre)
    if previo is not None and _hash(previo.read_bytes()) == h:
        _registrar_descarga(url, "ok", h, len(r.content), False)
        return previo, False, "sin cambios"
    carpeta = C.DIR_RAW / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{dt.datetime.now():%Y%m%d_%H%M%S}.csv"
    ruta.write_bytes(r.content)
    _registrar_descarga(url, "ok", h, len(r.content), True)
    return ruta, True, "actualizado"


def actualizar(forzar: bool = False, progreso=None) -> pd.DataFrame:
    """Descarga todo lo necesario. Las temporadas cerradas solo se bajan una vez."""
    tareas = []
    for liga in C.LIGAS_EUROPA:
        for temp in C.TEMPORADAS:
            nombre = f"{liga}_{temp}"
            if temp != C.TEMPORADA_ACTUAL and not forzar and ultimo_snapshot(nombre):
                continue
            tareas.append((nombre, f"{C.URL_BASE}/mmz4281/{temp}/{liga}.csv"))
    for liga in C.LIGAS_EXTRA:
        tareas.append((f"{liga}_todas", f"{C.URL_BASE}/new/{liga}.csv"))
    tareas.append(("proximos", f"{C.URL_BASE}/fixtures.csv"))

    filas = []
    for i, (nombre, url) in enumerate(tareas):
        if progreso:
            progreso(i / len(tareas), f"Descargando {nombre}…")
        _, cambio, estado = descargar(nombre, url)
        filas.append({"archivo": nombre, "estado": estado, "cambio": cambio})
        time.sleep(0.4)  # ser respetuosos con el servidor gratuito
    try:  # calendario y cuotas de ESPN: Champions, Libertadores, Liga 1 y partidos entre semana
        from . import espn
        if progreso:
            progreso(0.99, "Calendario y cuotas de ESPN…")
        n = len(espn.descargar())
        filas.append({"archivo": "espn_proximos", "estado": f"{n} partidos", "cambio": n > 0})
    except Exception as e:
        filas.append({"archivo": "espn_proximos", "estado": f"error {type(e).__name__}", "cambio": False})
    if progreso:
        progreso(1.0, "Descarga terminada")
    cargar_partidos.cache_clear()
    return pd.DataFrame(filas)


# --- normalización ---------------------------------------------------------------

def _fechas(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    f = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    falta = f.isna()
    if falta.any():
        f[falta] = pd.to_datetime(s[falta], format="%d/%m/%y", errors="coerce")
    return f


def _leer_csv(ruta: Path) -> pd.DataFrame:
    return pd.read_csv(ruta, encoding="utf-8-sig", on_bad_lines="skip", low_memory=False)


def _agregar_cuotas(df_raw: pd.DataFrame, out: pd.DataFrame) -> None:
    for destino, candidatas in CUOTAS:
        out[destino] = np.nan
        for col in candidatas:
            if col in df_raw.columns:
                v = pd.to_numeric(df_raw[col], errors="coerce")
                out[destino] = out[destino].fillna(v)


def _normalizar_europa(df_raw: pd.DataFrame, temporada: str) -> pd.DataFrame:
    out = pd.DataFrame({dst: df_raw[src] if src in df_raw.columns else np.nan
                        for src, dst in MAPA_EUROPA.items()})
    _agregar_cuotas(df_raw, out)
    out["temporada"] = f"20{temporada[:2]}/{temporada[2:]}"
    return out


def _normalizar_extra(df_raw: pd.DataFrame, liga: str) -> pd.DataFrame:
    out = pd.DataFrame({
        "liga": liga,
        "fecha": df_raw["Date"], "hora": df_raw.get("Time"),
        "local": df_raw["Home"].astype(str).str.strip(),
        "visitante": df_raw["Away"].astype(str).str.strip(),
        "gl": df_raw["HG"], "gv": df_raw["AG"], "res": df_raw["Res"],
        "temporada": df_raw["Season"].astype(str),
        "competicion": df_raw["League"].astype(str).str.strip(),
    })
    _agregar_cuotas(df_raw, out)
    return out


_cache: dict = {}


def _firma() -> tuple:
    return tuple(sorted((p.parent.name, p.name) for p in C.DIR_RAW.glob("*/*.csv")))


def cargar_partidos() -> pd.DataFrame:
    """Todos los partidos jugados de todas las ligas, en un esquema común."""
    firma = _firma()
    if _cache.get("firma") == firma and "partidos" in _cache:
        return _cache["partidos"]
    partes = []
    for liga in C.LIGAS_EUROPA:
        for temp in C.TEMPORADAS:
            ruta = ultimo_snapshot(f"{liga}_{temp}")
            if ruta is None:
                continue
            raw = _leer_csv(ruta)
            if "HomeTeam" not in raw.columns:
                continue
            partes.append(_normalizar_europa(raw, temp))
    for liga in C.LIGAS_EXTRA:
        ruta = ultimo_snapshot(f"{liga}_todas")
        if ruta is None:
            continue
        raw = _leer_csv(ruta)
        if "Home" not in raw.columns:
            continue
        partes.append(_normalizar_extra(raw, liga))
    if not partes:
        return pd.DataFrame(columns=["liga", "fecha", "local", "visitante", "gl", "gv"])
    df = pd.concat(partes, ignore_index=True)
    df = df[df["local"].notna() & df["visitante"].notna()].copy()
    df["local"] = df["local"].astype(str).str.strip()
    df["visitante"] = df["visitante"].astype(str).str.strip()
    df["fecha"] = _fechas(df["fecha"])
    for c in COLUMNAS_NUM:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["fecha"].notna() & df["gl"].notna() & df["gv"].notna()]
    df = df.sort_values(["fecha", "liga", "local"]).reset_index(drop=True)
    _cache.update(firma=firma, partidos=df)
    return df


cargar_partidos.cache_clear = lambda: _cache.clear()  # type: ignore[attr-defined]


def cargar_proximos() -> pd.DataFrame:
    """Partidos próximos (ligas europeas) con cuotas del momento."""
    ruta = ultimo_snapshot("proximos")
    if ruta is None:
        return _con_espn(pd.DataFrame())
    raw = _leer_csv(ruta)
    if "HomeTeam" not in raw.columns:
        return _con_espn(pd.DataFrame())
    out = pd.DataFrame({
        "liga": raw["Div"], "fecha": _fechas(raw["Date"]), "hora": raw.get("Time"),
        "local": raw["HomeTeam"].astype(str).str.strip(),
        "visitante": raw["AwayTeam"].astype(str).str.strip(),
        "arbitro": raw.get("Referee"),
    })
    _agregar_cuotas(raw, out)
    # La fuente publica la hora del Reino Unido; se convierte a la hora de Perú.
    inicio_uk = pd.to_datetime(out["fecha"].dt.strftime("%Y-%m-%d") + " " + out["hora"].fillna("12:00").astype(str),
                               errors="coerce")
    inicio_pe = (inicio_uk.dt.tz_localize("Europe/London", ambiguous="NaT", nonexistent="NaT")
                 .dt.tz_convert(C.ZONA_HORARIA).dt.tz_localize(None))
    out["inicio"] = inicio_pe
    out["fecha"] = inicio_pe.dt.normalize().fillna(out["fecha"])
    out["hora"] = inicio_pe.dt.strftime("%H:%M").fillna(out["hora"])
    ahora = pd.Timestamp.now(tz=C.ZONA_HORARIA).tz_localize(None)
    out = out[out["inicio"].isna() | (out["inicio"] >= ahora - pd.Timedelta(hours=2))]
    out["fuente_consulta"] = ruta.stem
    return _con_espn(out).sort_values(["inicio", "liga"]).reset_index(drop=True)


def _con_espn(out: pd.DataFrame) -> pd.DataFrame:
    """Suma los partidos de ESPN que football-data no trae (mismo partido = misma liga, equipos y día)."""
    try:
        from . import espn
        e = espn.cargar()
    except Exception:
        return out
    if e.empty:
        return out
    ya = set(zip(out["liga"], out["local"], out["visitante"], out["fecha"].dt.date)) if not out.empty else set()
    e = e[[(f.liga, f.local, f.visitante, f.fecha.date()) not in ya for f in e.itertuples()]]
    return pd.concat([out, e], ignore_index=True) if not out.empty else e


def cuotas_sanas(*cuotas, minimo: float = 0.97, maximo: float = 1.20) -> bool:
    """Descarta precios absurdos (p. ej. Betfair a 1.01 en un mercado sin liquidez): la suma de
    probabilidades implícitas debe parecerse a la de una casa normal."""
    try:
        v = [float(c) for c in cuotas]
    except (TypeError, ValueError):
        return False
    if any(not np.isfinite(c) or c <= 1.0 for c in v):
        return False
    s = sum(1 / c for c in v)
    return minimo <= s <= maximo


def cuotas_coherentes(a: list[float], b: list[float], tolerancia: float = 0.10) -> bool:
    """Dos fuentes de cuotas del mismo mercado no deben diferir más de 10 puntos de probabilidad."""
    pa = np.array([1 / x for x in a]); pa /= pa.sum()
    pb = np.array([1 / x for x in b]); pb /= pb.sum()
    return bool(np.max(np.abs(pa - pb)) <= tolerancia)


def equipos_de_liga(liga: str, solo_recientes: bool = True) -> list[str]:
    df = cargar_partidos()
    d = df[df["liga"] == liga]
    if solo_recientes and len(d):
        d = d[d["fecha"] >= d["fecha"].max() - pd.Timedelta(days=200)]
    return sorted(set(d["local"]) | set(d["visitante"]))


# --- calidad de datos ------------------------------------------------------------

def calidad_datos(df: pd.DataFrame | None = None) -> dict:
    """Detecta duplicados, contradicciones y faltantes. No modifica nada."""
    if df is None:
        df = cargar_partidos()
    problemas = []
    dup = df[df.duplicated(["liga", "fecha", "local", "visitante"], keep=False)]
    for _, f in dup.iterrows():
        problemas.append({"tipo": "duplicado", "liga": f.liga, "fecha": f.fecha.date(),
                          "partido": f"{f.local} vs {f.visitante}"})
    if "ht_gl" in df.columns:
        mal_ht = df[(df["ht_gl"] > df["gl"]) | (df["ht_gv"] > df["gv"])]
        for _, f in mal_ht.iterrows():
            problemas.append({"tipo": "goles 1T > goles finales", "liga": f.liga,
                              "fecha": f.fecha.date(), "partido": f"{f.local} vs {f.visitante}"})
    res_calc = np.where(df["gl"] > df["gv"], "H", np.where(df["gl"] < df["gv"], "A", "D"))
    mal_res = df[df["res"].notna() & (df["res"].astype(str).str.strip() != res_calc)]
    for _, f in mal_res.iterrows():
        problemas.append({"tipo": "resultado no coincide con goles", "liga": f.liga,
                          "fecha": f.fecha.date(), "partido": f"{f.local} vs {f.visitante}"})
    faltantes = {}
    europa = df[df["liga"].isin(list(C.LIGAS_EUROPA))]
    for c in ["ht_gl", "corn_l", "ama_l", "rem_l", "arco_l", "xg_l", "c_1", "s_1"]:
        if c in europa.columns and len(europa):
            faltantes[c] = round(float(europa[c].isna().mean()) * 100, 1)
    actual = europa[europa["temporada"] == f"20{C.TEMPORADA_ACTUAL[:2]}/{C.TEMPORADA_ACTUAL[2:]}"]
    return {
        "partidos": int(len(df)),
        "ligas": int(df["liga"].nunique()),
        "desde": str(df["fecha"].min().date()) if len(df) else None,
        "hasta": str(df["fecha"].max().date()) if len(df) else None,
        "con_xg_temporada_actual_%": round(float(actual["xg_l"].notna().mean()) * 100, 1) if len(actual) else 0.0,
        "faltantes_%_europa": faltantes,
        "problemas": problemas,
    }


def ultima_descarga() -> str | None:
    if not C.LOG_DESCARGAS.exists():
        return None
    try:
        log = pd.read_csv(C.LOG_DESCARGAS)
        ok = log[log["estado"] == "ok"]
        return str(ok["fecha_consulta"].iloc[-1]) if len(ok) else None
    except Exception:
        return None
