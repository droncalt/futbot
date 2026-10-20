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
                    "betano": EQ.enlace_liga(f.liga)} | _detalle(f.liga, f.local, f.visitante, w, hist))
    return out


# Líneas que la app puede evaluar de una captura (clave "mercado|opcion|linea", como Seleccion)
_GRILLA = ([("1x2", o, None) for o in ("local", "empate", "visitante")] + [("doble", o, None) for o in ("1X", "X2", "12")]
           + [("btts", o, None) for o in ("si", "no")]
           + [(m, o, l) for m, ls in (("goles", M.LINEAS_GOLES), ("goles_local", [0.5, 1.5, 2.5]),
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
    # tiros al arco: promedio simple de lo que cada uno genera y concede (no hay modelo con backtest: estimación)
    pl, pv = _promedios(hist, local), _promedios(hist, visitante)
    if "arco" in pl and "arco" in pv:
        al = (pl["arco"][0] + pv["arco"][1]) / 2
        av = (pv["arco"][0] + pl["arco"][1]) / 2
        esp.update(tiros_arco=round(al + av, 2), tiros_arco_local=round(al, 2), tiros_arco_visitante=round(av, 2))
        for m, lam, lineas in (("tiros_arco", al + av, [4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5]),
                               ("tiros_arco_local", al, [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]),
                               ("tiros_arco_visitante", av, [1.5, 2.5, 3.5, 4.5, 5.5, 6.5])):
            for l in lineas:
                pm = float(poisson.sf(int(l), lam))
                mer[_clave(m, "mas", l)] = round(pm, 4)
                mer[_clave(m, "menos", l)] = round(1 - pm, 4)
    return {"mercados": mer, "esperados": esp, "jugadores": _jugadores(liga, local, visitante)}


def _jugadores(liga, local, visitante, n: int = 5) -> list[dict]:
    """Los jugadores con más probabilidad de tiro al arco (modelo con backtest, 5 grandes ligas), si es titular."""
    if liga not in C.LIGAS_JUGADORES:
        return []
    try:
        from . import modelo_jugadores as MJ
        r = MJ.jugadores_partido(liga, local, visitante, MJ.ESCENARIO_DEFECTO, n=6)
    except Exception:
        return []
    if not r.get("disponible"):
        return []
    filas = [{"nombre": f["jugador"], "lado": lado, "equipo": EQ.nombre(local if lado == "local" else visitante),
              "p1": f["prob"].get("1+"), "p2": f["prob"].get("2+"), "p3": f["prob"].get("3+"),
              "titular": f.get("titular_en_ultimas_10"), "linea_min": CB.linea_min_jugador(f["jugador"], f["prob"])}
             for lado in ("local", "visitante") for f in r[lado] if f["prob"].get("1+")]
    return sorted(filas, key=lambda x: -x["p1"])[:n]


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
                    "peso_modelo": ev.get("peso_modelo")},
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
