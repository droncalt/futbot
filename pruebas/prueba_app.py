"""Prueba automática de la app (streamlit.testing AppTest) con una base SQLite TEMPORAL.

    python -P pruebas/prueba_app.py

No toca datos/registro.sqlite ni descarga nada. Recorre:
1. la app sin backtest de jugadores (debe avisar y no mostrar probabilidades de jugadores);
2. la app con el backtest real: agrega «Jugador · Tiros al arco N+» desde Verificar fijas y desde la ficha
   del partido, revisa probabilidad, cuota justa y evidencia en la boleta, la registra como «solo
   seguimiento» en la base temporal y comprueba la sección de calibración de la pestaña Calidad.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from streamlit.testing.v1 import AppTest  # noqa: E402

from motor import config as C  # noqa: E402
from motor import modelo_jugadores as MJ  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="prueba_bot_"))
C.DB_PATH = TMP / "registro_prueba.sqlite"
APP = str(RAIZ / "app.py")
fallos: list[str] = []


def revisar(at: AppTest, etapa: str) -> None:
    if at.exception:
        for e in at.exception:
            fallos.append(f"[{etapa}] excepción: {e.message}")
    print(f"{etapa}: {'OK' if not at.exception else 'CON EXCEPCIONES'}")


def textos(at: AppTest) -> str:
    partes = [m.value for m in at.markdown] + [m.value for m in at.caption] + [m.value for m in at.info]
    partes += [m.value for m in at.warning] + [m.value for m in at.success]
    return "\n".join(str(p) for p in partes)


def boton(at: AppTest, etiqueta: str):
    for b in at.button:
        if b.label == etiqueta:
            return b
    raise AssertionError(f"No encontré el botón «{etiqueta}»")


# 1. Sin backtest de jugadores ------------------------------------------------------------
ruta_real = MJ.RUTA_RESUMEN
MJ.RUTA_RESUMEN = TMP / "no_existe.json"
at = AppTest.from_file(APP, default_timeout=600)
at.run()
revisar(at, "1. carga sin backtest de jugadores")
at.selectbox(key="v_liga").set_value("E0").run()
at.selectbox(key="v_mercado").set_value("jug_arco").run()
revisar(at, "1. mercado de jugador sin backtest")
if "Sin backtest de tiros al arco" not in textos(at):
    fallos.append("[1] sin backtest debía avisar que no se muestran probabilidades de jugadores")
MJ.RUTA_RESUMEN = ruta_real

# 2. Con el backtest real --------------------------------------------------------------------
if not MJ.resumen_backtest():
    fallos.append("[2] no hay datos/evaluacion/resumen_jugadores.json: ejecuta 'python -P bot.py backtest-jugadores'")
else:
    at = AppTest.from_file(APP, default_timeout=600)
    at.run()
    revisar(at, "2. carga con backtest")
    at.selectbox(key="v_liga").set_value("E0").run()
    eqs = at.selectbox(key="v_local").options
    local = "Man City" if "Man City" in eqs else eqs[0]
    at.selectbox(key="v_local").set_value(local).run()
    visitante = next(e for e in at.selectbox(key="v_visit").options if e != local)
    at.selectbox(key="v_visit").set_value(visitante).run()
    at.selectbox(key="v_mercado").set_value("jug_arco").run()
    revisar(at, "2. elegir mercado de jugador")
    at.selectbox(key="v_opcion").set_value("1+").run()
    at.selectbox(key="v_jugador").set_value(0).run()
    at.radio(key="v_jesc").set_value("titular").run()
    boton(at, "➕ Agregar a la boleta").click().run()
    revisar(at, "2. agregar jugador desde Verificar fijas")
    boleta = at.session_state["boleta"]
    sel = [s for g in boleta for s in g["selecciones"] if s["mercado"] == "jug_arco"]
    if not sel:
        fallos.append("[2] la selección de jugador no llegó a la boleta")
    else:
        print("   en la boleta:", sel[0]["jugador_nombre"], sel[0]["opcion"], sel[0]["escenario"])
    t = textos(at)
    for esperado in ("Tiros al Arco", "depende de que sea titular"):
        if esperado not in t:
            fallos.append(f"[2] falta «{esperado}» en el análisis de la boleta")
    metricas = {m.label: m.value for m in at.metric}
    if metricas.get("Prob. del bot", "—") == "—" or metricas.get("Cuota justa", "—") == "—":
        fallos.append(f"[2] la línea de jugador no muestra probabilidad o cuota justa: {metricas}")
    else:
        print("   prob. del bot:", metricas["Prob. del bot"], "· cuota justa:", metricas["Cuota justa"])
    tablas = [d.value for d in at.dataframe]
    if not any("Historial del bot" in d.columns and d["Historial del bot"].astype(str).str.contains("casos").any()
               for d in tablas):
        fallos.append("[2] la pata de jugador no muestra la evidencia del backtest")

    # desde la ficha del partido (pestaña Partidos), si el partido elegido es de una liga con jugadores
    agregar_ficha = [b for b in at.button if b.label == "➕ Agregar tiros al arco a la boleta"]
    if agregar_ficha:
        antes = sum(len(g["selecciones"]) for g in at.session_state["boleta"])
        agregar_ficha[0].click().run()
        revisar(at, "2. agregar jugador desde la ficha del partido")
        if sum(len(g["selecciones"]) for g in at.session_state["boleta"]) <= antes:
            fallos.append("[2] el botón de la ficha no agregó la selección")
    else:
        print("   (el partido elegido en Partidos no es de las 5 grandes ligas: se omite esa parte)")

    # registrar como solo seguimiento en la base TEMPORAL
    boton(at, "👁️ Solo seguimiento (no aposté)").click().run()
    revisar(at, "2. registrar boleta (solo seguimiento)")
    con = sqlite3.connect(C.DB_PATH)
    n = con.execute("SELECT COUNT(*) FROM patas WHERE mercado='jug_arco'").fetchone()[0]
    con.close()
    if n == 0:
        fallos.append("[2] la pata de jugador no se guardó en la base temporal")
    else:
        print(f"   patas de jugador registradas en la base temporal: {n}")

    t = textos(at)
    if "Tiros al arco de jugadores (backtest propio)" not in t:
        fallos.append("[2] la pestaña Calidad no muestra la calibración de tiros al arco")
    if not any("Tiros al arco" in str(s.value) for s in at.selectbox if s.key == "cal_jug_ev"):
        fallos.append("[2] falta el selector del gráfico de calibración de jugadores")

# 3. FútBot (interfaz nueva, ui/): Verificar, detalle de partido y Calidad --------------------------
SCRIPT_FUTBOT = f'''
import sys
sys.path.insert(0, r"{RAIZ}")
import streamlit as st
from ui import comun as U, estilos as E, paginas as P
E.inyectar()
U.iniciar()
pagina = st.session_state.get("_pagina", "verificar")
if pagina == "verificar":
    P.verificar()
elif pagina == "detalle":
    P.detalle_partido(st.session_state["_sel"])
else:
    P.calidad()
'''
if (RAIZ / "ui" / "paginas.py").exists() and MJ.resumen_backtest():
    ft = AppTest.from_string(SCRIPT_FUTBOT, default_timeout=600)
    ft.session_state["_pagina"] = "verificar"
    ft.run()
    revisar(ft, "3. FútBot · Verificar")
    ft.selectbox(key="v_liga").set_value("E0").run()
    ft.selectbox(key="v_mercado").set_value("jug_arco").run()
    ft.selectbox(key="v_opcion_j").set_value("2+").run()
    ft.selectbox(key="v_jugador").set_value(0).run()
    boton(ft, "➕ Agregar a la boleta").click().run()
    revisar(ft, "3. FútBot · agregar jugador")
    if not any(s["mercado"] == "jug_arco" for g in ft.session_state["boleta"] for s in g["selecciones"]):
        fallos.append("[3] FútBot: la selección de jugador no llegó a la boleta")
    metricas = {m.label: m.value for m in ft.metric}
    if metricas.get("Prob. del bot", "—") == "—":
        fallos.append(f"[3] FútBot: la línea de jugador no muestra probabilidad: {metricas}")
    else:
        print("   FútBot prob. del bot:", metricas["Prob. del bot"], "· cuota justa:", metricas.get("Cuota justa"))
    ft.session_state["_pagina"] = "detalle"
    ft.session_state["_sel"] = {"liga": "E0", "local": local, "visitante": visitante, "inicio": None}
    ft.run()
    revisar(ft, "3. FútBot · detalle de partido")
    b = [x for x in ft.button if x.label == "➕ Agregar tiros al arco a la boleta"]
    if not b:
        fallos.append("[3] FútBot: falta la sección de tiros al arco en el detalle del partido")
    else:
        b[0].click().run()
        revisar(ft, "3. FútBot · agregar desde el detalle")
    ft.session_state["_pagina"] = "calidad"
    ft.run()
    revisar(ft, "3. FútBot · Calidad")
    if "Tiros al arco de jugadores (backtest propio)" not in textos(ft):
        fallos.append("[3] FútBot: la página Calidad no muestra la calibración de tiros al arco")

print("\nBase temporal:", C.DB_PATH)
if fallos:
    print("FALLÓ:\n- " + "\n- ".join(fallos))
    sys.exit(1)
print("PRUEBA SUPERADA: sin excepciones.")
