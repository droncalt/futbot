"""Datos de jugadores por partido (minutos, tiros, tiros al arco) para el mercado «<Jugador> Tiros al Arco».

Fuentes:
* API-Football (api-sports.io) con la clave PRIVADA del usuario en `.env` (APIFOOTBALL_KEY=...).
  El plan gratuito da 100 consultas al día: cada consulta se cuenta y la descarga se detiene antes
  del límite (sigue al día siguiente donde quedó). Un partido terminado no cambia, así que se baja una
  sola vez: con `/fixtures?ids=` entran 20 partidos (con estadísticas de jugadores) por consulta.
* Understat (gratis, sin clave): respaldo para las 5 grandes ligas cuando el plan de API-Football no
  incluye la temporada. Tiros al arco = tiros con resultado «Goal» o «SavedShot» (los goles en
  propia puerta no cuentan).

Las respuestas originales se guardan comprimidas en datos/raw/<fuente>/ (las listas de partidos con
versión fechada solo si cambiaron, igual que motor/datos.py) y cada consulta queda en
datos/registro_descargas.csv (sin la clave). Todo se normaliza a una tabla de «apariciones»:
una fila por jugador y partido en el que jugó al menos un minuto.
"""
from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
import os
import time
from collections import Counter
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
from . import datos

DIR_RAW_AF = C.DIR_RAW / "apifootball"
DIR_RAW_US = C.DIR_RAW / "understat"
ESTADO_AF = C.DIR_JUGADORES / "estado_apifootball.json"
CONSUMO_AF = C.DIR_JUGADORES / "consumo_apifootball.json"
TERMINADOS_AF = {"FT", "AET", "PEN"}
FUENTES = {"apifootball": "API-Football (api-sports.io)", "understat": "Understat"}

COLUMNAS = ["fuente", "liga", "temporada", "partido_id", "fecha", "equipo", "rival", "es_local",
            "goles_equipo", "goles_rival", "jugador_id", "jugador", "posicion", "grupo_pos",
            "titular", "minutos", "tiros", "tiros_arco", "goles"]

# Grupos de posición para el prior (la media de tiros al arco de su posición)
GRUPOS_US = {"GK": "POR", "DC": "DEF", "DL": "DEF", "DR": "DEF", "DMC": "MCD", "DML": "DEF", "DMR": "DEF",
             "MC": "MED", "ML": "MED", "MR": "MED", "AMC": "MPU", "AML": "MPU", "AMR": "MPU",
             "FW": "DEL", "FWL": "DEL", "FWR": "DEL"}
GRUPOS_AF = {"G": "POR", "D": "DEF", "M": "MED", "F": "DEL"}
NOMBRE_GRUPO = {"POR": "Portero", "DEF": "Defensa", "MCD": "Mediocentro defensivo", "MED": "Mediocampista",
                "MPU": "Extremo / mediapunta", "DEL": "Delantero"}


# --- utilidades -------------------------------------------------------------------

def _hash(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:16]


def _escribir_gz(ruta: Path, obj) -> bytes:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    b = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    tmp = ruta.with_name(f"{ruta.name}.{os.getpid()}.tmp")  # escritura atómica: si se corta, no queda a medias
    with gzip.open(tmp, "wb") as f:
        f.write(b)
    try:
        os.replace(tmp, ruta)
    except PermissionError:  # otro proceso guardó el mismo archivo a la vez (Windows bloquea el reemplazo)
        tmp.unlink(missing_ok=True)
        if not ruta.exists():
            raise
    return b


def _leer_gz(ruta: Path):
    with gzip.open(ruta, "rb") as f:
        return json.loads(f.read().decode("utf-8"))


def _guardar_version(carpeta: Path, obj) -> tuple[Path, bool]:
    """Guarda una lista de partidos como nueva versión solo si su contenido cambió."""
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    previo = _ultima_version(carpeta)
    if previo is not None:
        try:
            antes = json.dumps(_leer_gz(previo), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if _hash(antes) == _hash(b):
                return previo, False
        except Exception:
            pass
    ruta = carpeta / f"{dt.datetime.now():%Y%m%d_%H%M%S}.json.gz"
    _escribir_gz(ruta, obj)
    return ruta, True


def _ultima_version(carpeta: Path) -> Path | None:
    archivos = sorted(carpeta.glob("*.json.gz")) if carpeta.exists() else []
    return archivos[-1] if archivos else None


def _edad_horas(ruta: Path | None) -> float:
    if ruta is None:
        return float("inf")
    return (time.time() - ruta.stat().st_mtime) / 3600


def _leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return defecto


def _escribir_json(ruta: Path, obj) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


def temporada_texto(t: int) -> str:
    return f"{t}/{str(t + 1)[2:]}"


def temporada_en_curso(t: int) -> bool:
    return t == max(C.TEMPORADAS_JUGADORES)


# --- clave privada ----------------------------------------------------------------

def leer_clave() -> str | None:
    """Lee APIFOOTBALL_KEY del archivo privado .env (o de la variable de entorno). Nunca se imprime."""
    if os.environ.get("APIFOOTBALL_KEY"):
        return os.environ["APIFOOTBALL_KEY"].strip()
    if not C.ENV_PATH.exists():
        return None
    for linea in C.ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
        linea = linea.strip()
        if linea.startswith("#") or "=" not in linea:
            continue
        k, v = linea.split("=", 1)
        if k.strip() == "APIFOOTBALL_KEY":
            v = v.strip().strip('"').strip("'")
            return v or None
    return None


# --- API-Football -----------------------------------------------------------------

class SinCuota(Exception):
    """No quedan consultas del día (se respeta la reserva)."""


def _hoy_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()  # la cuota de API-Football se reinicia a las 00:00 UTC


def consumo_api() -> dict:
    c = _leer_json(CONSUMO_AF, {})
    if c.get("fecha_utc") != _hoy_utc():
        c = {"fecha_utc": _hoy_utc(), "usadas": 0, "restantes_api": None, "limite_api": None}
    return c


def consultas_disponibles() -> int:
    c = consumo_api()
    limite = c.get("limite_api") or C.APIFOOTBALL_LIMITE_DIARIO
    restantes = c["restantes_api"] if c.get("restantes_api") is not None else limite - c["usadas"]
    return max(0, min(restantes, limite - c["usadas"]) - C.APIFOOTBALL_RESERVA)


def _anotar_consumo(cabeceras) -> None:
    c = consumo_api()
    c["usadas"] += 1
    for k, dst in (("x-ratelimit-requests-remaining", "restantes_api"), ("x-ratelimit-requests-limit", "limite_api")):
        v = cabeceras.get(k)
        if v is not None:
            try:
                c[dst] = int(v)
            except ValueError:
                pass
    _escribir_json(CONSUMO_AF, c)


_ultima_consulta = [0.0]


def _api_get(ruta: str, params: dict, clave: str, cuenta: bool = True) -> dict:
    """GET a API-Football. Lanza SinCuota si no quedan consultas. Devuelve el JSON (con 'errors')."""
    if cuenta and consultas_disponibles() <= 0:
        raise SinCuota()
    espera = C.APIFOOTBALL_PAUSA - (time.time() - _ultima_consulta[0])
    if espera > 0:
        time.sleep(espera)
    url = f"{C.APIFOOTBALL_URL}/{ruta}"
    url_log = url + ("?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else "")
    try:
        r = requests.get(url, params=params, headers={"x-apisports-key": clave}, timeout=45)
    except Exception as e:
        datos._registrar_descarga(url_log, f"error: {type(e).__name__}", "", 0, False)
        return {"errors": {"conexion": type(e).__name__}, "response": []}
    finally:
        _ultima_consulta[0] = time.time()
    if cuenta:
        _anotar_consumo(r.headers)
    try:
        js = r.json()
    except ValueError:
        js = {"errors": {"http": f"HTTP {r.status_code}"}, "response": []}
    err = js.get("errors") or {}
    estado = "ok" if r.status_code == 200 and not err else f"http {r.status_code} {json.dumps(err, ensure_ascii=False)[:120]}"
    datos._registrar_descarga(url_log, estado, _hash(r.content), len(r.content), False)
    return js


def estado_plan(clave: str | None = None) -> dict:
    """Plan y consumo de la cuenta (el endpoint /status no gasta cuota)."""
    clave = clave or leer_clave()
    if not clave:
        return {"error": "No hay clave en .env"}
    js = _api_get("status", {}, clave, cuenta=False)
    if js.get("errors"):
        return {"error": js["errors"]}
    r = js.get("response") or {}
    sub, req = r.get("subscription", {}), r.get("requests", {})
    return {"plan": sub.get("plan"), "activo": sub.get("active"), "vence": sub.get("end"),
            "consultas_hoy": req.get("current"), "limite_diario": req.get("limit_day")}


def _bloqueos() -> dict:
    """Temporadas que el plan rechazó en los últimos 7 días (no se gastan consultas en ellas)."""
    limite = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    return {k: v for k, v in _leer_json(ESTADO_AF, {}).get("bloqueadas", {}).items() if v.get("fecha", "") >= limite}


def _bloquear(clave_temp: str, motivo: str) -> None:
    e = _leer_json(ESTADO_AF, {})
    e.setdefault("bloqueadas", {})[clave_temp] = {"motivo": motivo, "fecha": dt.date.today().isoformat()}
    _escribir_json(ESTADO_AF, e)


def _error_plan(js: dict) -> str | None:
    err = js.get("errors") or {}
    if isinstance(err, dict):
        for k, v in err.items():
            if k in ("plan", "access", "season") or "plan" in str(v).lower():
                return str(v)
    return None


def _af_temporada(liga: str, temporada: int, clave: str, progreso=None) -> dict:
    nombre = f"{liga}_{temporada}"
    fila = {"fuente": "apifootball", "liga": liga, "temporada": temporada_texto(temporada),
            "estado": "", "nuevos": 0, "pendientes": None}
    if nombre in _bloqueos():
        fila["estado"] = "no incluida en tu plan: " + _bloqueos()[nombre]["motivo"]
        return fila
    carpeta_lista = DIR_RAW_AF / f"fixtures_{nombre}"
    carpeta_det = DIR_RAW_AF / f"partidos_{nombre}"
    lista = _ultima_version(carpeta_lista)
    if lista is None or (temporada_en_curso(temporada) and _edad_horas(lista) > 12):
        js = _api_get("fixtures", {"league": C.LIGAS_JUGADORES[liga]["apifootball"], "season": temporada}, clave)
        motivo = _error_plan(js)
        if motivo:
            _bloquear(nombre, motivo)
            fila["estado"] = "no incluida en tu plan: " + motivo
            return fila
        if js.get("errors"):
            fila["estado"] = f"error: {js['errors']}"
            return fila
        lista, _ = _guardar_version(carpeta_lista, js.get("response", []))
    partidos = _leer_gz(lista)
    terminados = [p["fixture"]["id"] for p in partidos
                  if p.get("fixture", {}).get("status", {}).get("short") in TERMINADOS_AF]
    faltan = [i for i in terminados if not (carpeta_det / f"{i}.json.gz").exists()]
    for k in range(0, len(faltan), 20):
        bloque = faltan[k:k + 20]
        if progreso:
            progreso(f"API-Football {nombre}: {len(terminados) - len(faltan) + k}/{len(terminados)} partidos")
        js = _api_get("fixtures", {"ids": "-".join(str(i) for i in bloque)}, clave)
        motivo = _error_plan(js)
        if motivo:
            _bloquear(nombre, motivo)
            fila["estado"] = "no incluida en tu plan: " + motivo
            return fila
        for det in js.get("response", []):
            fid = det.get("fixture", {}).get("id")
            if fid is not None and det.get("players"):
                _escribir_gz(carpeta_det / f"{fid}.json.gz", det)
                fila["nuevos"] += 1
    pend = [i for i in terminados if not (carpeta_det / f"{i}.json.gz").exists()]
    fila["pendientes"] = len(pend)
    fila["estado"] = "completa" if not pend else f"faltan {len(pend)} partidos (sin estadísticas de jugadores aún)"
    return fila


def _normalizar_af(det: dict, liga: str, temporada: int) -> list[dict]:
    fx, eq, gl = det["fixture"], det["teams"], det.get("goals", {})
    id_local = eq["home"]["id"]
    titulares = {p["player"]["id"] for l in det.get("lineups") or [] for p in l.get("startXI") or []
                 if p.get("player")}
    filas = []
    for bloque in det.get("players") or []:
        es_local = bloque["team"]["id"] == id_local
        propio, rival = (eq["home"], eq["away"]) if es_local else (eq["away"], eq["home"])
        g_p, g_r = (gl.get("home"), gl.get("away")) if es_local else (gl.get("away"), gl.get("home"))
        for p in bloque.get("players") or []:
            st = (p.get("statistics") or [{}])[0]
            juego = st.get("games") or {}
            minutos = juego.get("minutes") or 0
            if minutos <= 0:
                continue
            pid = p["player"]["id"]
            sup = juego.get("substitute")
            pos = juego.get("position") or ""
            tiros = st.get("shots") or {}
            filas.append({
                "fuente": "apifootball", "liga": liga, "temporada": temporada, "partido_id": f"af{fx['id']}",
                "fecha": fx["date"][:10], "equipo": propio["name"], "rival": rival["name"], "es_local": es_local,
                "goles_equipo": g_p, "goles_rival": g_r, "jugador_id": f"af{pid}", "jugador": p["player"]["name"],
                "posicion": pos, "grupo_pos": GRUPOS_AF.get(pos, "MED"),
                "titular": (not sup) if sup is not None else pid in titulares, "minutos": int(minutos),
                "tiros": int(tiros.get("total") or 0), "tiros_arco": int(tiros.get("on") or 0),
                "goles": int((st.get("goals") or {}).get("total") or 0),
            })
    return filas


# --- Understat --------------------------------------------------------------------

CABECERAS_US = {"User-Agent": "Mozilla/5.0 (bot-analitico-personal)", "X-Requested-With": "XMLHttpRequest"}
_sesion_us: list = []  # una sola conexión reutilizada (cada conexión nueva tarda ~1 s en esta PC)


def _us_get(ruta: str) -> dict | None:
    url = f"{C.UNDERSTAT_URL}/{ruta}"
    if not _sesion_us:
        _sesion_us.append(requests.Session())
    for intento in range(3):
        time.sleep(C.UNDERSTAT_PAUSA * (1 + 4 * intento))
        try:
            r = _sesion_us[0].get(url, headers=CABECERAS_US, timeout=45)
        except Exception as e:
            datos._registrar_descarga(url, f"error: {type(e).__name__}", "", 0, False)
            continue
        if r.status_code == 200:
            try:
                js = r.json()
            except ValueError:
                datos._registrar_descarga(url, "respuesta no es JSON", "", len(r.content), False)
                return None
            datos._registrar_descarga(url, "ok", _hash(r.content), len(r.content), True)
            return js
        datos._registrar_descarga(url, f"http {r.status_code}", "", len(r.content), False)
        if r.status_code not in (429, 500, 502, 503, 504):
            return None
    return None


def _us_temporada(liga: str, temporada: int, progreso=None, max_partidos: int | None = None) -> dict:
    nombre = f"{liga}_{temporada}"
    fila = {"fuente": "understat", "liga": liga, "temporada": temporada_texto(temporada),
            "estado": "", "nuevos": 0, "pendientes": None}
    carpeta_lista = DIR_RAW_US / f"liga_{nombre}"
    carpeta_det = DIR_RAW_US / f"partidos_{nombre}"
    lista = _ultima_version(carpeta_lista)
    if lista is None or (temporada_en_curso(temporada) and _edad_horas(lista) > 6):
        js = _us_get(f"getLeagueData/{C.LIGAS_JUGADORES[liga]['understat']}/{temporada}")
        if js and "dates" in js:
            lista, _ = _guardar_version(carpeta_lista, {"dates": js["dates"]})
        elif lista is None:
            fila["estado"] = "no disponible"
            return fila
    partidos = [p for p in _leer_gz(lista)["dates"] if p.get("isResult")]
    faltan = [p for p in partidos if not (carpeta_det / f"{p['id']}.json.gz").exists()]
    if max_partidos is not None:
        faltan = faltan[:max_partidos]
    for k, p in enumerate(faltan):
        if progreso and k % 10 == 0:
            progreso(f"Understat {nombre}: {len(partidos) - len(faltan) + k}/{len(partidos)} partidos")
        if (carpeta_det / f"{p['id']}.json.gz").exists():  # otro proceso ya lo bajó
            continue
        js = _us_get(f"getMatchData/{p['id']}")
        if js and "rosters" in js:
            _escribir_gz(carpeta_det / f"{p['id']}.json.gz", {"partido": p, "rosters": js["rosters"],
                                                              "shots": js.get("shots", {})})
            fila["nuevos"] += 1
    pend = [p for p in partidos if not (carpeta_det / f"{p['id']}.json.gz").exists()]
    fila["pendientes"] = len(pend)
    fila["estado"] = "completa" if not pend else f"faltan {len(pend)} partidos"
    return fila


def _normalizar_us(js: dict, liga: str, temporada: int) -> list[dict]:
    p = js["partido"]
    al_arco = Counter()
    for lado in ("h", "a"):
        for s in (js.get("shots") or {}).get(lado, []):
            if s.get("result") in ("Goal", "SavedShot"):
                al_arco[(str(s["player_id"]), lado)] += 1
    nombres = {"h": p["h"]["title"], "a": p["a"]["title"]}
    goles = {"h": int(p["goals"]["h"]), "a": int(p["goals"]["a"])}
    filas = []
    for lado, otro in (("h", "a"), ("a", "h")):
        for r in (js.get("rosters") or {}).get(lado, {}).values():
            minutos = int(r.get("time") or 0)
            if minutos <= 0:
                continue
            pos = r.get("position") or ""
            filas.append({
                "fuente": "understat", "liga": liga, "temporada": temporada, "partido_id": f"us{p['id']}",
                "fecha": p["datetime"][:10], "equipo": nombres[lado], "rival": nombres[otro], "es_local": lado == "h",
                "goles_equipo": goles[lado], "goles_rival": goles[otro], "jugador_id": f"us{r['player_id']}",
                "jugador": r["player"], "posicion": pos, "grupo_pos": GRUPOS_US.get(pos),  # "Sub": se completa luego
                "titular": pos != "Sub", "minutos": minutos, "tiros": int(r.get("shots") or 0),
                "tiros_arco": al_arco.get((str(r["player_id"]), lado), 0), "goles": int(r.get("goals") or 0),
            })
    return filas


# --- descarga -----------------------------------------------------------------------

def _necesita_understat() -> bool:
    if C.FUENTE_JUGADORES == "understat":
        return True
    if C.FUENTE_JUGADORES == "apifootball":
        return False
    return fuente_activa() != "apifootball"


def actualizar(progreso=None, fuentes: list[str] | None = None, max_partidos: int | None = None) -> pd.DataFrame:
    """Descarga lo que falta (incremental). progreso(texto) informa el avance."""
    filas = []
    clave = leer_clave()
    usar = fuentes or (["apifootball"] if clave and C.FUENTE_JUGADORES != "understat" else [])
    if "apifootball" in usar:
        if not clave:
            filas.append({"fuente": "apifootball", "estado": "sin clave: crea el archivo .env (ver README)"})
        else:
            sin_cuota = False
            actual = max(C.TEMPORADAS_JUGADORES)
            for temporada in sorted(C.TEMPORADAS_JUGADORES, reverse=True):  # primero lo más útil para apostar hoy
                if temporada != actual and all(f"{l}_{actual}" in _bloqueos() for l in C.LIGAS_JUGADORES):
                    filas.append({"fuente": "apifootball", "temporada": temporada_texto(temporada),
                                  "estado": "omitida: tu plan no incluye la temporada actual, así que se usa Understat"})
                    continue
                for liga in C.LIGAS_JUGADORES:
                    if sin_cuota:
                        filas.append({"fuente": "apifootball", "liga": liga, "temporada": temporada_texto(temporada),
                                      "estado": "esperando: se acabaron las consultas de hoy"})
                        continue
                    try:
                        filas.append(_af_temporada(liga, temporada, clave, progreso))
                    except SinCuota:
                        sin_cuota = True
                        filas.append({"fuente": "apifootball", "liga": liga, "temporada": temporada_texto(temporada),
                                      "estado": "pausada: se acabaron las consultas de hoy (sigue mañana)"})
    if (fuentes and "understat" in fuentes) or (not fuentes and _necesita_understat()):
        for temporada in C.TEMPORADAS_JUGADORES:
            for liga in C.LIGAS_JUGADORES:
                filas.append(_us_temporada(liga, temporada, progreso, max_partidos))
    _cache.clear()
    return pd.DataFrame(filas)


# --- tabla normalizada ------------------------------------------------------------

_cache: dict = {}


def _firma_raw(fuente: str) -> tuple:
    base = DIR_RAW_AF if fuente == "apifootball" else DIR_RAW_US
    archivos = list(base.glob("partidos_*/*.json.gz")) if base.exists() else []
    return (len(archivos), max((a.stat().st_mtime for a in archivos), default=0))


def cargar_apariciones(fuente: str | None = None) -> pd.DataFrame:
    """Una fila por jugador y partido jugado (todas las ligas y temporadas descargadas)."""
    fuente = fuente or fuente_activa()
    firma = _firma_raw(fuente)
    clave = ("ap", fuente)
    if _cache.get(clave, (None,))[0] == firma:
        return _cache[clave][1]
    ruta = C.DIR_JUGADORES / f"apariciones_{fuente}.csv.gz"
    meta = C.DIR_JUGADORES / f"apariciones_{fuente}.json"
    if ruta.exists() and _leer_json(meta, {}).get("firma") == list(firma):
        df = pd.read_csv(ruta, dtype={"jugador_id": str, "partido_id": str})
    else:
        df = _construir(fuente)
        if len(df):
            df.to_csv(ruta, index=False)
            _escribir_json(meta, {"firma": list(firma), "filas": len(df), "creada": dt.datetime.now().isoformat()})
    if len(df):
        df["fecha"] = pd.to_datetime(df["fecha"])
        df["titular"] = df["titular"].astype(bool)
        df["es_local"] = df["es_local"].astype(bool)
    _cache[clave] = (firma, df)
    return df


def _construir(fuente: str) -> pd.DataFrame:
    filas = []
    base = DIR_RAW_AF if fuente == "apifootball" else DIR_RAW_US
    for carpeta in sorted(base.glob("partidos_*")) if base.exists() else []:
        liga, temporada = carpeta.name.split("_")[1], int(carpeta.name.split("_")[2])
        for archivo in carpeta.glob("*.json.gz"):
            try:
                js = _leer_gz(archivo)
                filas += _normalizar_af(js, liga, temporada) if fuente == "apifootball" else _normalizar_us(js, liga, temporada)
            except Exception:
                continue
    df = pd.DataFrame(filas, columns=COLUMNAS)
    if df.empty:
        return df
    # Los suplentes de Understat no traen posición: se usa la posición más frecuente del jugador como titular
    falta = df["grupo_pos"].isna()
    if falta.any():
        habitual = (df[~falta].groupby("jugador_id")["grupo_pos"].agg(lambda s: s.value_counts().index[0]))
        df.loc[falta, "grupo_pos"] = df.loc[falta, "jugador_id"].map(habitual)
        df["grupo_pos"] = df["grupo_pos"].fillna("MED")
    return df.sort_values(["fecha", "partido_id", "es_local"], ascending=[True, True, False]).reset_index(drop=True)


def cobertura(fuente: str) -> pd.DataFrame:
    ap = cargar_apariciones(fuente)
    if ap.empty:
        return pd.DataFrame(columns=["liga", "temporada", "partidos", "jugadores", "hasta"])
    return (ap.groupby(["liga", "temporada"]).agg(partidos=("partido_id", "nunique"), jugadores=("jugador_id", "nunique"),
                                                   hasta=("fecha", "max")).reset_index())


def fuente_activa() -> str:
    """API-Football si sus datos cubren la temporada del backtest y la actual; si no, Understat."""
    if C.FUENTE_JUGADORES in FUENTES:
        return C.FUENTE_JUGADORES
    if leer_clave():
        cob = cobertura("apifootball")
        temps = set(cob.loc[cob["partidos"] >= 100, "temporada"]) if len(cob) else set()
        if {C.TEMPORADA_BACKTEST_JUGADORES, max(C.TEMPORADAS_JUGADORES)} <= temps:
            return "apifootball"
    return "understat"


# --- equipos: nombres de la fuente -> nombres de football-data ----------------------

def mapa_equipos(ap: pd.DataFrame, partidos: pd.DataFrame) -> dict:
    """Empareja equipos por (liga, fecha ±1 día, marcador) y elige el nombre por mayoría de votos."""
    clave = ("mapa", id(ap), len(ap), id(partidos), len(partidos))
    if clave in _cache:
        return _cache[clave]
    loc = ap[ap["es_local"]].drop_duplicates("partido_id")[["liga", "fecha", "equipo", "rival", "goles_equipo", "goles_rival"]]
    fd = partidos[partidos["liga"].isin(list(C.LIGAS_JUGADORES))][["liga", "fecha", "local", "visitante", "gl", "gv"]]
    m = loc.merge(fd, left_on=["liga", "goles_equipo", "goles_rival"], right_on=["liga", "gl", "gv"])
    m = m[(m["fecha_x"] - m["fecha_y"]).abs() <= pd.Timedelta(days=1)]
    votos = Counter()
    for f in m.itertuples(index=False):
        votos[(f.liga, f.equipo, f.local)] += 1
        votos[(f.liga, f.rival, f.visitante)] += 1
    mejor: dict = {}
    for (liga, src, dst), n in votos.items():
        if n > mejor.get((liga, src), ("", 0))[1]:
            mejor[(liga, src)] = (dst, n)
    out = {k: v[0] for k, v in mejor.items() if v[1] >= 3}
    _cache[clave] = out
    _escribir_json(C.DIR_JUGADORES / "mapa_equipos.json",
                   {f"{l}|{s}": d for (l, s), d in sorted(out.items())})
    return out


def con_nombres_fd(ap: pd.DataFrame, partidos: pd.DataFrame) -> pd.DataFrame:
    """Agrega equipo_fd y rival_fd (nombres de football-data) a la tabla de apariciones."""
    mapa = mapa_equipos(ap, partidos)
    ap = ap.copy()
    ap["equipo_fd"] = [mapa.get((l, e)) for l, e in zip(ap["liga"], ap["equipo"])]
    ap["rival_fd"] = [mapa.get((l, e)) for l, e in zip(ap["liga"], ap["rival"])]
    return ap


def contraste_arco(ap: pd.DataFrame, partidos: pd.DataFrame) -> dict:
    """Compara los tiros al arco por equipo de la fuente con los de football-data (otra definición posible)."""
    ap = con_nombres_fd(ap, partidos)
    eq = (ap.groupby(["liga", "fecha", "equipo_fd", "rival_fd", "es_local"], dropna=True)["tiros_arco"].sum()
          .reset_index())
    loc = eq[eq["es_local"]].merge(partidos, left_on=["liga", "equipo_fd", "rival_fd"], right_on=["liga", "local", "visitante"])
    loc = loc[(loc["fecha_x"] - loc["fecha_y"]).abs() <= pd.Timedelta(days=1)]
    vis = eq[~eq["es_local"]].merge(partidos, left_on=["liga", "rival_fd", "equipo_fd"], right_on=["liga", "local", "visitante"])
    vis = vis[(vis["fecha_x"] - vis["fecha_y"]).abs() <= pd.Timedelta(days=1)]
    a = np.concatenate([loc["tiros_arco"].to_numpy(float), vis["tiros_arco"].to_numpy(float)])
    b = np.concatenate([loc["arco_l"].to_numpy(float), vis["arco_v"].to_numpy(float)])
    ok = ~np.isnan(b)
    if ok.sum() == 0:
        return {}
    a, b = a[ok], b[ok]
    return {"equipos_partido": int(ok.sum()), "media_fuente": float(a.mean()), "media_football_data": float(b.mean()),
            "razon": float(a.sum() / b.sum()), "coinciden_%": float((a == b).mean() * 100),
            "difieren_en_1_%": float((np.abs(a - b) == 1).mean() * 100)}
