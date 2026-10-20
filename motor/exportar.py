"""Paquete de datos para la app del celular (se genera cada día en la nube y la app lo descarga).

publicar/
  paquete.json   súper boletas por nivel, partidos con probabilidades, resultados recientes, reglas de Betano…
  escudos/*.png  escudos de los equipos que aparecen

La app no necesita la PC: solo descarga este paquete (y lo guarda para usarlo sin internet).
"""
from __future__ import annotations

import datetime as dt
import json
import shutil

import numpy as np
import pandas as pd
from scipy.stats import poisson

from . import analisis as A
from . import betano as B
from . import combinador as CB
from . import config as C
from . import datos
from . import equipos as EQ
from . import fijas as F
from . import mercados as M

DIR_PUBLICAR = C.RAIZ / "publicar"
VERSION_PAQUETE = 1


_LOGOS_ESPN: dict = {}


def _equipo(eq: str, escudos: set) -> dict:
    d = EQ.indice().get(eq, {})
    if d.get("archivo"):
        escudos.add(d["archivo"])
        return {"nombre": EQ.nombre(eq), "escudo": f"escudos/{d['archivo']}"}
    return {"nombre": EQ.nombre(eq), "escudo": _LOGOS_ESPN.get(eq)}  # URL del escudo en ESPN (copas)


def _lineas(nivel: str, escudos: set, jugadores: bool) -> list[dict]:
    ini, fin, _ = F.ventana("semana")
    lineas = CB.generar(ini, fin, nivel, None, jugadores, True, False, 3)
    out = []
    for l in lineas:
        s0 = l.patas[0].seleccion
        out.append({
            "id": l.id, "liga": l.liga, "liga_nombre": C.NOMBRES_LIGA.get(l.liga, l.liga), "inicio": l.inicio.isoformat(),
            "local": _equipo(l.local, escudos), "visitante": _equipo(l.visitante, escudos),
            "patas": [{"titulo": p.titulo, "mercado": p.mercado, "p": round(p.p, 4), "sel": p.seleccion.to_dict()}
                      | ({"alternativas": {k: round(v, 4) for k, v in p.alternativas.items()}} if p.alternativas else {})
                      for p in l.patas],
            "sub": {str(k): v for k, v in l.subconjuntos.items()},
            "cuota": round(l.cuota, 2), "estimada": l.cuota_tipo == "estimada", "p": round(l.p, 4),
            "multibono_ok": len(l.patas) == 1 and s0.mercado in B.MULTI_BONO_MERCADOS and l.liga in B.MULTI_BONO_LIGAS,
            "seguro_ok": len(l.patas) == 1 and s0.mercado in B.SEGURO_MERCADOS,
            "betano": EQ.enlace_liga(l.liga), "avisos": l.avisos[:3],
        })
    return out


def _partidos(escudos: set) -> list[dict]:
    tp = A.tabla_proximos()
    if tp.empty:
        return []
    cols = [n for n, _ in A.SELECCIONES_TABLA]
    w, _ = A.peso_modelo()
    hist = datos.cargar_partidos().sort_values("fecha")
    out = []
    for _, f in tp.iterrows():
        out.append({"liga": f.liga, "liga_nombre": C.NOMBRES_LIGA.get(f.liga, f.liga),
                    "inicio": f"{f.fecha:%Y-%m-%d} {f.hora or '00:00'}",
                    "local": _equipo(f.local, escudos), "visitante": _equipo(f.visitante, escudos),
                    "goles_esperados": None if pd.isna(f.goles_esperados) else float(f.goles_esperados),
                    "prob": {c: (None if pd.isna(f[c]) else round(float(f[c]), 4)) for c in cols},
                    "betano": EQ.enlace_liga(f.liga), "forma": _forma(f.local, f.visitante, hist)}
                   | _detalle(f.liga, f.local, f.visitante, w, hist))
    return out


# Líneas que la app puede evaluar de una captura (clave "mercado|opcion|linea", como Seleccion)
_GRILLA = ([("1x2", o, None) for o in ("local", "empate", "visitante")] + [("doble", o, None) for o in ("1X", "X2", "12")]
           + [("btts", o, None) for o in ("si", "no")]
           + [(m, o, l) for m, ls in (("goles", M.LINEAS_GOLES + [6.5]), ("goles_local", [0.5, 1.5, 2.5]),
                                      ("goles_visitante", [0.5, 1.5, 2.5]), ("1t_goles", [0.5, 1.5, 2.5]),
                                      ("2t_goles", [0.5, 1.5, 2.5]),
                                      ("corners", [5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5]),
                                      ("corners_local", [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]),
                                      ("corners_visitante", [1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]),
                                      ("tarjetas", [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]))
              for l in ls for o in ("mas", "menos")]
           + [("1t_1x2", o, None) for o in ("local", "empate", "visitante")])


def _clave(m, o, l) -> str:
    return f"{m}|{o}|{'' if l is None else l}"


def _promedios(hist: pd.DataFrame, equipo: str, n: int = 10) -> dict:
    """Promedio de los últimos n partidos del equipo: a favor y en contra (tiros al arco, córners, tarjetas)."""
    h = hist[(hist["local"] == equipo) | (hist["visitante"] == equipo)].tail(n)
    if h.empty:
        return {}
    loc = h["local"] == equipo
    out = {}
    for k, cl, cv in (("arco", "arco_l", "arco_v"), ("corners", "corn_l", "corn_v"), ("amarillas", "ama_l", "ama_v")):
        if cl not in h or h[cl].isna().all():
            continue
        fav = np.where(loc, h[cl], h[cv])
        con = np.where(loc, h[cv], h[cl])
        out[k] = (float(np.nanmean(fav)), float(np.nanmean(con)))
    return out


def _detalle(liga, local, visitante, w, hist) -> dict:
    """Probabilidad del bot para muchas líneas del partido + valores esperados (córners, tarjetas, tiros al arco)."""
    try:
        pt = CB._Partido(liga, local, visitante, w)
    except Exception:
        return {}
    mer, esp = {}, {"goles": round(pt.mod.lam + pt.mod.mu, 2), "goles_local": round(pt.mod.lam, 2),
                    "goles_visitante": round(pt.mod.mu, 2)}
    for m, o, l in _GRILLA:
        fam = M.MERCADOS[m]["familia"]
        if (fam == "corners" and pt.mod.corners is None) or (fam == "tarjetas" and pt.mod.tarjetas is None):
            continue
        try:
            s = M.Seleccion(m, o, l)
            p = F.calibrar(s, M.combinar(*pt.bruta([s]), w))
        except Exception:
            p = None
        if p is not None:
            mer[_clave(m, o, l)] = round(float(p), 4)
    for nombre, Mx in (("corners", pt.mod.corners), ("tarjetas", pt.mod.tarjetas)):
        if Mx is not None:
            k = np.arange(Mx.shape[0])
            el, ev = float((Mx.sum(1) * k).sum()), float((Mx.sum(0) * np.arange(Mx.shape[1])).sum())
            esp[nombre] = round(el + ev, 2)
            esp[f"{nombre}_local"], esp[f"{nombre}_visitante"] = round(el, 2), round(ev, 2)
    # promedios de los últimos 10 partidos de cada equipo, con backtest (motor/estimaciones.py): tiros al arco y
    # atajadas siempre; córners y tarjetas solo si el partido no tiene modelo propio (copas)
    estimados = []
    try:
        from . import estimaciones as ES
        me, ee = ES.mercados_partido(local, visitante)
        for k, v in me.items():
            fam = k.split("|")[0].replace("_local", "").replace("_visitante", "")
            if fam in ("tiros_arco", "atajadas") or k not in mer:
                if k not in mer:
                    estimados.append(k)
                mer[k] = v
        for k, v in ee.items():
            esp.setdefault(k, v)
    except Exception:
        pass
    fams = sorted({k.split("|")[0] for k in estimados})
    return {"mercados": mer, "esperados": esp, "estimados": fams, "jugadores": _jugadores(liga, local, visitante)}


def _jugadores(liga, local, visitante, n: int = 8) -> list[dict]:
    """Los jugadores con más probabilidad de tiro al arco (modelo con backtest, 5 grandes ligas), si es titular."""
    try:
        from . import modelo_jugadores as MJ
        filas = MJ.eventos_partido(liga, local, visitante, n=6)
    except Exception:
        return []
    for f in filas:
        f["equipo"] = EQ.nombre(local if f["lado"] == "local" else visitante)
        f["linea_min"] = CB.linea_min_jugador(f["nombre"], {"1+": f.get("p1") or 0})
        f.pop("jugador_id", None)
    return sorted([f for f in filas if f.get("p1")], key=lambda x: -x["p1"])[:n]


def _resultados(dias: int = 10) -> list[dict]:
    """Resultados recientes: la app liquida sola las boletas que guardaste."""
    df = datos.cargar_partidos()
    df = df[df["fecha"] >= pd.Timestamp.now().normalize() - pd.Timedelta(days=dias)]
    cols = ["gl", "gv", "ht_gl", "ht_gv", "corn_l", "corn_v", "ama_l", "ama_v", "roj_l", "roj_v"]
    out = []
    for _, f in df.iterrows():
        r = {"liga": f.liga, "fecha": f"{f.fecha:%Y-%m-%d}", "local": EQ.nombre(f.local), "visitante": EQ.nombre(f.visitante)}
        for c in cols:
            v = f.get(c)
            r[c] = None if v is None or pd.isna(v) else int(v)
        out.append(r)
    return out


def exportar(jugadores: bool = True) -> dict:
    try:
        from . import espn
        _LOGOS_ESPN.update(espn.logos())
    except Exception:
        pass
    DIR_PUBLICAR.mkdir(exist_ok=True)
    (DIR_PUBLICAR / "escudos").mkdir(exist_ok=True)
    px = datos.cargar_proximos()
    if not px.empty:  # los equipos de copas traen el escudo de ESPN: no se buscan en TheSportsDB
        px = px[px["liga"].isin(list(C.LIGAS))]
        EQ.resolver(list(px.get("local", [])) + list(px.get("visitante", [])))
    escudos: set = set()
    ev = A.resumen_evaluacion()
    paquete = {
        "version": VERSION_PAQUETE,
        "generado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "generado_peru": F.ahora_peru().strftime("%d/%m/%Y %H:%M"),
        "niveles": {k: {"nombre": v["nombre"], "emoji": v["emoji"], "cuota_min": v["cuota_min"]} for k, v in CB.NIVELES.items()},
        "lineas": {k: _lineas(k, escudos, jugadores) for k in CB.NIVELES},
        "partidos": _partidos(escudos),
        "resultados": _resultados(),
        "multibono": B.MULTI_BONO_FUTBOL, "apuesta_minima": B.APUESTA_MINIMA,
        "reglas": B.base_conocimiento()["reglas"],
        "calidad": {"fijas_global": ev.get("fijas_global"), "periodo": ev.get("periodo"), "partidos": ev.get("partidos"),
                    "peso_modelo": ev.get("peso_modelo"), **_calidad_extra()},
    }
    for archivo in escudos:
        origen = EQ.DIR_ESCUDOS / archivo
        if origen.exists():
            shutil.copy2(origen, DIR_PUBLICAR / "escudos" / archivo)
    (DIR_PUBLICAR / "paquete.json").write_text(json.dumps(paquete, ensure_ascii=False, default=str), encoding="utf-8")
    (DIR_PUBLICAR / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>FútBot datos</title>"
        f"<p>Paquete de datos de FútBot · generado {paquete['generado_peru']} (hora de Perú).</p>", encoding="utf-8")
    return {"lineas": {k: len(v) for k, v in paquete["lineas"].items()}, "partidos": len(paquete["partidos"]),
            "resultados": len(paquete["resultados"]), "escudos": len(escudos),
            "kb": round((DIR_PUBLICAR / "paquete.json").stat().st_size / 1024)}


def _calidad_extra() -> dict:
    """Resumen de los backtests de jugadores y de las estimaciones por promedios (para «Aprendizaje»)."""
    out = {}
    try:
        from . import estimaciones as ES
        r = ES.resumen()
        ev = [x for x in r.get("evaluacion", []) if x["periodo"] == "validacion"]
        if ev:
            out["estimaciones"] = {"partidos": r.get("partidos"), "periodo": r.get("periodo_validacion"),
                                   "mercados": {x["mercado"]: {"n": x["n"], "prob": round(x["prob_media"], 3),
                                                               "real": round(x["frecuencia_real"], 3),
                                                               "error": round(x["error_calibracion"], 4)} for x in ev}}
    except Exception:
        pass
    try:
        from . import modelo_jugadores as MJ
        jug = {}
        for col in ("tiros_arco", "goles", "asistencias", "ga"):
            r = MJ.resumen_backtest() if col == "tiros_arco" else MJ.resumen_evento(col)
            for x in r.get("por_evento", []):
                if x["periodo"] == "validacion" and ("Titular" in x["evento"] or "titular" in x["evento"]):
                    jug.setdefault(col, []).append({"evento": x["evento"], "n": x["n"], "prob": round(x["prob_media"], 3),
                                                    "real": round(x["frecuencia_real"], 3), "error": round(x["error_calibracion"], 4)})
        if jug:
            out["jugadores"] = jug
    except Exception:
        pass
    return out


def _forma(local: str, visitante: str, hist: pd.DataFrame, n: int = 5) -> dict:
    """Últimos partidos de cada equipo (cualquier competición con datos) y enfrentamientos directos."""
    h = hist.dropna(subset=["gl", "gv"])

    def ultimos(eq: str) -> list[dict]:
        d = h[(h["local"] == eq) | (h["visitante"] == eq)].tail(n)
        out = []
        for f in d.itertuples():
            casa = f.local == eq
            gf, gc = (f.gl, f.gv) if casa else (f.gv, f.gl)
            fila = {"fecha": f"{f.fecha:%d/%m}", "rival": EQ.nombre(f.visitante if casa else f.local), "casa": bool(casa),
                    "gf": int(gf), "gc": int(gc), "res": "G" if gf > gc else "E" if gf == gc else "P"}
            for k, (cl, cv) in (("corners", ("corn_l", "corn_v")), ("tarjetas", ("ama_l", "ama_v")), ("arco", ("arco_l", "arco_v"))):
                a, b = getattr(f, cl, None), getattr(f, cv, None)
                if a is not None and b is not None and not (pd.isna(a) or pd.isna(b)):
                    fila[k] = [int(a if casa else b), int(b if casa else a)]
            out.append(fila)
        return out[::-1]  # el más reciente primero

    d = h[((h["local"] == local) & (h["visitante"] == visitante)) | ((h["local"] == visitante) & (h["visitante"] == local))].tail(5)
    h2h = [{"fecha": f"{f.fecha:%d/%m/%Y}", "local": EQ.nombre(f.local), "visitante": EQ.nombre(f.visitante),
            "gl": int(f.gl), "gv": int(f.gv)} for f in d.itertuples()][::-1]
    return {"local": ultimos(local), "visitante": ultimos(visitante), "h2h": h2h}
