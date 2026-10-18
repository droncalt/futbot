"""FútBot — analista de fútbol para Betano (aplicación web local con Streamlit).

Abrir con:  iniciar_bot.bat   (o: python -m streamlit run futbot.py)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

st.set_page_config(page_title="FútBot · Betano", page_icon="⚽", layout="wide", initial_sidebar_state="collapsed")

from motor import config as C
from ui import comun as U
from ui import estilos as E
from ui import paginas as P

E.inyectar()
U.iniciar()

from ui import acceso  # noqa: E402

if not acceso.puerta():  # desde el celular u otro equipo pide el PIN
    st.stop()

if not any(C.DIR_RAW.glob("*/*.csv")):
    E.hero("¡Bienvenido a FútBot! ⚽", "Primero descargo los datos de las ligas (tarda un par de minutos, solo la primera vez).")
    if st.button("⬇️ Descargar datos ahora", type="primary"):
        barra = st.progress(0.0)
        U.actualizar_todo(lambda p, m: barra.progress(min(p, 1.0), m))
        st.rerun()
    st.stop()

U.auto_actualizar()
try:  # nombres oficiales y escudos de los equipos que falten (en segundo plano, una sola vez)
    from motor import equipos as _EQ
    _EQ.resolver_en_fondo()
except Exception:
    pass

paginas = {
    "chat": st.Page(P.chat, title="Chat", icon="💬", url_path="chat", default=True),
    "fijas": st.Page(P.fijas, title="Súper boleta", icon="🎯", url_path="fijas"),
    "partidos": st.Page(P.partidos, title="Partidos", icon="📅", url_path="partidos"),
    "verificar": st.Page(P.verificar, title="Verificar", icon="🔍", url_path="verificar"),
    "boleta": st.Page(P.boleta, title="Mi boleta", icon="🧾", url_path="boleta"),
    "historial": st.Page(P.historial, title="Historial", icon="📒", url_path="historial"),
    "videos": st.Page(P.videos, title="Tipsters", icon="📹", url_path="tipsters"),
    "calidad": st.Page(P.calidad, title="Calidad", icon="📊", url_path="calidad"),
    "guia": st.Page(P.guia, title="Guía", icon="📘", url_path="guia"),
}
U.PAGINAS.update(paginas)
nav = st.navigation(list(paginas.values()), position="top")
U.barra_lateral()
nav.run()
