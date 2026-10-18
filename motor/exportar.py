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

import pandas as pd

from . import analisis as A
from . import betano as B
from . import combinador as CB
from . import config as C
from . import datos
from . import equipos as EQ
from . import fijas as F

DIR_PUBLICAR = C.RAIZ / "publicar"
VERSION_PAQUETE = 1


def _equipo(eq: str, escudos: set) -> dict:
    d = EQ.indice().get(eq, {})
    if d.get("archivo"):
        escudos.add(d["archivo"])
    return {"nombre": EQ.nombre(eq), "escudo": f"escudos/{d['archivo']}" if d.get("archivo") else None}


def _lineas(nivel: str, escudos: set, jugadores: bool) -> list[dict]:
    ini, fin, _ = F.ventana("semana")
    lineas = CB.generar(ini, fin, nivel, None, jugadores, True, False, 3)
    out = []
    for l in lineas:
        s0 = l.patas[0].seleccion
        out.append({
            "id": l.id, "liga": l.liga, "liga_nombre": C.LIGAS.get(l.liga, l.liga), "inicio": l.inicio.isoformat(),
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
    out = []
    for _, f in tp.iterrows():
        out.append({"liga": f.liga, "liga_nombre": C.LIGAS.get(f.liga, f.liga),
                    "inicio": f"{f.fecha:%Y-%m-%d} {f.hora or '00:00'}",
                    "local": _equipo(f.local, escudos), "visitante": _equipo(f.visitante, escudos),
                    "goles_esperados": None if pd.isna(f.goles_esperados) else float(f.goles_esperados),
                    "prob": {c: (None if pd.isna(f[c]) else round(float(f[c]), 4)) for c in cols},
                    "betano": EQ.enlace_liga(f.liga)})
    return out


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
    DIR_PUBLICAR.mkdir(exist_ok=True)
    (DIR_PUBLICAR / "escudos").mkdir(exist_ok=True)
    EQ.resolver(list(datos.cargar_proximos().get("local", [])) + list(datos.cargar_proximos().get("visitante", [])))
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
