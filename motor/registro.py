"""Registro de boletas y predicciones (SQLite) para medir resultados reales.

Todo lo que el bot propone o lo que llega del grupo de Telegram se puede registrar.
Cuando aparecen los resultados, se liquida solo y alimenta las métricas de calibración:
¿lo que el bot llama "80 %" ocurre de verdad 8 de cada 10 veces?
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3

import numpy as np
import pandas as pd

from . import config as C
from . import mercados as M
from .analisis import Grupo

ESQUEMA = """
CREATE TABLE IF NOT EXISTS boletas(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  creada TEXT, fuente TEXT, importe REAL, cuota_total REAL, p_total REAL,
  peso_modelo REAL, estado TEXT DEFAULT 'pendiente', retorno REAL, nota TEXT,
  solo_seguimiento INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS lineas(
  id INTEGER PRIMARY KEY AUTOINCREMENT, boleta_id INTEGER, liga TEXT, fecha TEXT,
  local TEXT, visitante TEXT, cuota REAL, p_modelo REAL, p_mercado REAL, p_final REAL,
  version_modelo TEXT, resultado INTEGER, liquidada TEXT, grupo_json TEXT);
CREATE TABLE IF NOT EXISTS patas(
  id INTEGER PRIMARY KEY AUTOINCREMENT, linea_id INTEGER, mercado TEXT, opcion TEXT, linea REAL,
  p_modelo REAL, p_mercado REAL, p_final REAL, resultado INTEGER);
"""


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(C.DB_PATH)
    con.executescript(ESQUEMA)
    return con


def registrar_boleta(res: dict, fuente: str, nota: str = "", solo_seguimiento: bool = False) -> int:
    con = conectar()
    with con:
        cur = con.execute(
            "INSERT INTO boletas(creada,fuente,importe,cuota_total,p_total,peso_modelo,nota,solo_seguimiento)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (dt.datetime.now().isoformat(timespec="seconds"), fuente, 0.0 if solo_seguimiento else res["importe"],
             res["cuota_total"], res["p_total"], res["peso_modelo"], nota, int(solo_seguimiento)))
        bid = cur.lastrowid
        for l in res["lineas"]:
            g: Grupo = l["grupo"]
            c2 = con.execute(
                "INSERT INTO lineas(boleta_id,liga,fecha,local,visitante,cuota,p_modelo,p_mercado,p_final,"
                "version_modelo,grupo_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (bid, g.liga, g.fecha, g.local, g.visitante, g.cuota, l["p_modelo"], l["p_mercado"],
                 l["p_final"], l["version_modelo"], json.dumps(g.to_dict(), ensure_ascii=False)))
            lid = c2.lastrowid
            for s, p in zip(g.selecciones, l["patas"]):
                con.execute(
                    "INSERT INTO patas(linea_id,mercado,opcion,linea,p_modelo,p_mercado,p_final) VALUES(?,?,?,?,?,?,?)",
                    (lid, s.mercado, s.opcion, s.linea, p["p_modelo"], p["p_mercado"], p["p_final"]))
    con.close()
    return bid


def boletas() -> pd.DataFrame:
    con = conectar()
    df = pd.read_sql_query("SELECT * FROM boletas ORDER BY id DESC", con)
    con.close()
    return df


def lineas(boleta_id: int | None = None) -> pd.DataFrame:
    con = conectar()
    q = "SELECT * FROM lineas" + (" WHERE boleta_id=?" if boleta_id else "")
    df = pd.read_sql_query(q, con, params=(boleta_id,) if boleta_id else None)
    con.close()
    return df


def patas() -> pd.DataFrame:
    con = conectar()
    df = pd.read_sql_query(
        "SELECT p.*, l.liga, l.local, l.visitante, b.fuente FROM patas p "
        "JOIN lineas l ON l.id=p.linea_id JOIN boletas b ON b.id=l.boleta_id", con)
    con.close()
    return df


def marcar(boleta_id: int, estado: str, retorno: float | None) -> None:
    con = conectar()
    with con:
        con.execute("UPDATE boletas SET estado=?, retorno=? WHERE id=?", (estado, retorno, boleta_id))
    con.close()


def borrar(boleta_id: int) -> None:
    con = conectar()
    with con:
        ids = [r[0] for r in con.execute("SELECT id FROM lineas WHERE boleta_id=?", (boleta_id,))]
        for lid in ids:
            con.execute("DELETE FROM patas WHERE linea_id=?", (lid,))
        con.execute("DELETE FROM lineas WHERE boleta_id=?", (boleta_id,))
        con.execute("DELETE FROM boletas WHERE id=?", (boleta_id,))
    con.close()


def _buscar_partido(partidos: pd.DataFrame, liga, local, visitante, fecha, creada) -> pd.Series | None:
    d = partidos[(partidos["local"] == local) & (partidos["visitante"] == visitante)]
    if liga in C.LIGAS:
        d = d[d["liga"] == liga]
    if fecha:
        f = pd.Timestamp(fecha)
        d = d[(d["fecha"] >= f - pd.Timedelta(days=3)) & (d["fecha"] <= f + pd.Timedelta(days=3))]
    else:
        d = d[d["fecha"] >= pd.Timestamp(creada).normalize() - pd.Timedelta(days=1)]
    return d.iloc[0] if len(d) else None


def liquidar_automatico(partidos: pd.DataFrame) -> int:
    """Busca resultados de las líneas pendientes y liquida patas, líneas y boletas."""
    con = conectar()
    pend = pd.read_sql_query(
        "SELECT l.*, b.creada FROM lineas l JOIN boletas b ON b.id=l.boleta_id WHERE l.resultado IS NULL", con)
    n = 0
    with con:
        for _, l in pend.iterrows():
            fila = _buscar_partido(partidos, l["liga"], l["local"], l["visitante"], l["fecha"], l["creada"])
            if fila is None:
                continue
            g = Grupo.from_dict(json.loads(l["grupo_json"]))
            res_patas = [M.cumple_real(s, fila) for s in g.selecciones]
            for j, s in enumerate(g.selecciones):
                if s.es_jugador and s.jugador:  # tiros al arco: datos de jugadores (None si no jugó o aún no hay datos)
                    from .modelo_jugadores import resultado_real
                    tiros = resultado_real(s.jugador, g.liga, str(pd.Timestamp(fila["fecha"]).date()), None, partidos)
                    res_patas[j] = None if tiros is None else tiros >= int(s.opcion.rstrip("+"))
            ids = [r[0] for r in con.execute("SELECT id FROM patas WHERE linea_id=? ORDER BY id", (int(l["id"]),))]
            for pid, r in zip(ids, res_patas):
                if r is not None:
                    con.execute("UPDATE patas SET resultado=? WHERE id=?", (int(r), pid))
            if any(r is False for r in res_patas):
                rl = 0
            elif all(r is True for r in res_patas):
                rl = 1
            else:
                continue
            con.execute("UPDATE lineas SET resultado=?, liquidada=? WHERE id=?",
                        (rl, dt.datetime.now().isoformat(timespec="seconds"), int(l["id"])))
            n += 1
        # boletas pendientes
        for bid, importe, cuota in con.execute(
                "SELECT id, importe, cuota_total FROM boletas WHERE estado='pendiente'").fetchall():
            res = [r[0] for r in con.execute("SELECT resultado FROM lineas WHERE boleta_id=?", (bid,))]
            if any(r == 0 for r in res):
                con.execute("UPDATE boletas SET estado='perdida', retorno=0 WHERE id=?", (bid,))
            elif res and all(r == 1 for r in res):
                con.execute("UPDATE boletas SET estado='ganada', retorno=? WHERE id=?",
                            ((importe or 0) * (cuota or 0), bid))
    con.close()
    return n


def metricas() -> dict:
    b = boletas()
    out: dict = {"boletas": b}
    if b.empty:
        return out
    cerradas = b[b["estado"].isin(["ganada", "perdida", "cashout"]) & (b["solo_seguimiento"] == 0)]
    apostado = float(cerradas["importe"].sum())
    retorno = float(cerradas["retorno"].fillna(0).sum())
    out["resumen"] = {
        "boletas_cerradas": int(len(cerradas)), "apostado": apostado, "retorno": retorno,
        "neto": retorno - apostado, "roi": (retorno - apostado) / apostado if apostado else None,
    }
    todas = b[b["estado"].isin(["ganada", "perdida"])]
    out["por_fuente"] = (
        todas.assign(acierto=(todas["estado"] == "ganada").astype(int))
        .groupby("fuente").agg(boletas=("id", "count"), aciertos=("acierto", "sum"),
                                prob_media_estimada=("p_total", "mean"))
        .assign(tasa_real=lambda x: x["aciertos"] / x["boletas"]).reset_index()
    )
    p = patas()
    p = p[p["resultado"].notna() & p["p_final"].notna()]
    if len(p):
        bins = [0, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0]
        p["rango"] = pd.cut(p["p_final"], bins)
        out["calibracion_patas"] = (
            p.groupby("rango", observed=True)
            .agg(patas=("id", "count"), prob_estimada=("p_final", "mean"), frecuencia_real=("resultado", "mean"))
            .reset_index())
        out["brier_patas"] = float(np.mean((p["p_final"] - p["resultado"]) ** 2))
    return out
