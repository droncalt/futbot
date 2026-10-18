"""Tiros al arco de jugadores en la interfaz (FútBot y la app clásica app.py).

* seccion_jugadores: tabla de los jugadores de ambos equipos con escenarios de alineación y botón para agregar.
* elegir_jugador: selector para el formulario de Verificar (devuelve los campos de Seleccion del jugador).
* calidad_jugadores: backtest y calibración del mercado para la página Calidad.
"""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from motor import config as C
from motor import datos
from motor import mercados as M
from motor import modelo_jugadores as MJ

FUENTES = ["Bot", "Propia", "Telegram"]
AVISO_ALINEACION = (
    "⚠️ Depende de que el jugador sea titular. " + MJ.REGLA_BETANO + " «Titular» usa los minutos de sus últimas "
    "titularidades. El modelo no sabe de lesiones ni rotaciones: confirma la alineación oficial (≈1 h antes).")


def _nombre_liga(c: str) -> str:
    return C.LIGAS.get(c, "Otra competición")


def modelo() -> MJ.ModeloJugadores | None:
    with st.spinner("Preparando el modelo de jugadores…"):
        return MJ.modelo_vigente(datos.cargar_partidos())


def _estado_o_aviso() -> MJ.ModeloJugadores | None:
    """Modelo listo para mostrar, o None (después de explicar por qué)."""
    est = MJ.estado_calibracion()
    if not est["hay_backtest"]:
        st.info(est["texto"])
        return None
    mj = modelo()
    if mj is None:
        st.info("No hay datos de jugadores. Ejecuta `python -P bot.py jugadores --descargar`.")
        return None
    (st.success if est["calibrado"] else st.warning)(est["texto"])
    return mj


def seccion_jugadores(liga: str, local: str, visitante: str, cuotas_ref, fecha, clave: str, agregar) -> None:
    """agregar(liga, local, visitante, seleccion, fuente, cuotas_ref, fecha) -> mensaje (el de cada app)."""
    st.markdown("#### 🎯 Tiros al arco de jugadores")
    if liga not in C.LIGAS_JUGADORES:
        st.caption("Solo con datos para Premier League, LaLiga, Serie A, Bundesliga y Ligue 1. "
                   "Para otro partido, busca al jugador en *Verificar*.")
        return
    mj = _estado_o_aviso()
    if mj is None:
        return
    k = f"{clave}_{local}_{visitante}"
    esc = st.radio("Alineación", list(MJ.ESCENARIOS), format_func=MJ.ESCENARIOS.get, horizontal=True, key=f"jesc_{k}")
    st.caption(AVISO_ALINEACION)
    tablas = mj.tabla_partido(liga, local, visitante, esc)
    opciones = []
    for lado, eq in (("local", local), ("visitante", visitante)):
        t = tablas[lado]
        st.markdown(f"**{eq}**")
        if t.empty:
            st.caption("Sin jugadores de este equipo en los datos recientes.")
            continue
        vista = t.drop(columns=["jugador_id"])
        for c in ("1+", "2+", "3+", "Titular (últ. 10)"):
            vista[c] = vista[c] * 100
        vista["Cuota justa 1+"] = 1 / t["1+"]
        vista["Historial 1+"] = [MJ.evidencia(1, esc, p, corta=True) or "" for p in t["1+"]]
        st.dataframe(vista, hide_index=True, width="stretch", column_config={
            "1+": st.column_config.ProgressColumn("1+ %", format="%.0f%%", min_value=0, max_value=100),
            "2+": st.column_config.NumberColumn("2+ %", format="%.0f%%"),
            "3+": st.column_config.NumberColumn("3+ %", format="%.0f%%"),
            "Titular (últ. 10)": st.column_config.NumberColumn(format="%.0f%%"),
            "Min. si es titular": st.column_config.NumberColumn(format="%.0f'"),
            "Tiros al arco /90'": st.column_config.NumberColumn(format="%.2f"),
            "Cuota justa 1+": st.column_config.NumberColumn(format="%.2f"),
            "Historial 1+": st.column_config.TextColumn(
                help="Backtest: cuántas veces se cumplió «1+» cuando el bot dio una probabilidad parecida")})
        opciones += [(lado, jid, nom) for jid, nom in zip(t["jugador_id"], t["Jugador"])]
    if not opciones:
        return
    c1, c2, c3 = st.columns([3, 1, 2])
    i = c1.selectbox("Jugador", range(len(opciones)), key=f"jsel_{k}",
                     format_func=lambda i: f"{opciones[i][2]} ({local if opciones[i][0] == 'local' else visitante})")
    linea = c2.selectbox("Tiros al arco", M.MERCADOS["jug_arco"]["opciones"], key=f"jlin_{k}")
    fuente = c3.radio("Fuente", FUENTES, horizontal=True, key=f"jfue_{k}")
    if st.button("➕ Agregar tiros al arco a la boleta", key=f"jadd_{k}"):
        lado, jid, nombre = opciones[i]
        sel = M.Seleccion("jug_arco", linea, int(linea[:-1]) - 0.5, jugador=jid, jugador_nombre=nombre,
                          lado=lado, escenario=esc)
        st.toast(agregar(liga, local, visitante, sel, fuente, cuotas_ref,
                         str(pd.Timestamp(fecha).date()) if fecha is not None else None))


def elegir_jugador(liga: str, local: str, visitante: str) -> dict | None:
    """Jugador, su lado y el escenario de alineación, para M.Seleccion(..., **resultado)."""
    mj = _estado_o_aviso()
    if mj is None:
        return None
    c1, c2 = st.columns([3, 2])
    if liga in C.LIGAS_JUGADORES and local and visitante:
        cands = []
        for lado_eq, eq in (("local", local), ("visitante", visitante)):
            d = mj.jugadores_de(liga, eq)
            cands += [(lado_eq, j, n) for j, n in zip(d["jugador_id"], d["jugador"])]
        if not cands:
            st.warning("No hay jugadores de estos equipos en los datos.")
            return None
        k = c1.selectbox("Jugador", range(len(cands)), key="v_jugador",
                         format_func=lambda k: f"{cands[k][2]} ({local if cands[k][0] == 'local' else visitante})")
        lado, jid, nombre = cands[k]
    else:
        texto = c1.text_input("Buscar jugador (de las 5 grandes ligas)", key="v_jbuscar")
        res = mj.buscar(texto) if texto.strip() else mj.tabla.iloc[0:0]
        if res.empty:
            st.caption("Escribe parte del nombre, por ejemplo «Lautaro».")
            return None
        k = c1.selectbox("Resultados", range(len(res)), key="v_jres", format_func=lambda k: (
            f"{res.iloc[k]['jugador']} · {res.iloc[k]['equipo_fd'] or res.iloc[k]['equipo']}"))
        jid, nombre = res.iloc[k]["jugador_id"], res.iloc[k]["jugador"]
        lado = c2.radio("Su equipo es", ["local", "visitante"], horizontal=True, key="v_jlado",
                        format_func=lambda x: f"{local or 'Local'} (local)" if x == "local" else f"{visitante or 'Visitante'} (visitante)")
        st.caption("Rival fuera de las 5 grandes ligas: se usa una defensa promedio.")
    esc = c2.radio("Alineación", list(MJ.ESCENARIOS), format_func=MJ.ESCENARIOS.get, key="v_jesc")
    return {"jugador": jid, "jugador_nombre": nombre, "lado": lado, "escenario": esc}


def calidad_jugadores() -> None:
    st.markdown("### 🎯 Tiros al arco de jugadores (backtest propio)")
    rj = MJ.resumen_backtest()
    if not rj:
        st.info("Todavía no se ejecutó el backtest de jugadores: hasta entonces no se muestran sus probabilidades.")
    else:
        est = MJ.estado_calibracion()
        (st.success if est["calibrado"] else st.warning)(est["texto"])
        p = rj["parametros"]
        st.caption(f"Backtest del {rj['fecha']} · fuente {rj['fuente_nombre']} · ligas: "
                   + ", ".join(_nombre_liga(l) for l in rj["ligas"])
                   + f". Parámetros elegidos con {rj['periodo_ajuste']} (κ = {p['kappa']:g} partidos de prior, "
                   f"ξ = {p['xi']:g}/día, defensa rival β = {p['beta']:g}, "
                   f"{'con' if p.get('suplente', True) else 'sin'} ritmo propio de suplente, "
                   f"{'Poisson' if p.get('poisson') else 'binomial negativa'}"
                   + (", con recalibración logística" if rj.get("recalibracion", {}).get("usar") else "")
                   + f"); calibración medida aparte en {rj['periodo_validacion']} "
                   f"({rj['filas']['validacion']:,} jugador-partido) y en la {rj['periodo_actual']} "
                   f"({rj['filas']['actual']:,}).")
        comp = rj.get("comparacion", {}).get("validacion")
        if comp:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Error del modelo", f"{comp['logloss_titular_modelo']:.4f}")
            c2.metric("Sin defensa rival", f"{comp['logloss_titular_sin_rival']:.4f}")
            c3.metric("Solo media de su posición", f"{comp['logloss_titular_solo_posicion']:.4f}")
            c4.metric("Tasa cruda del jugador", f"{comp['logloss_titular_ingenuo']:.4f}")
            st.caption("Log-loss medio de «1+», «2+» y «3+» en titulares (validación). Menor es mejor. No hay cuotas "
                       "de mercado de jugadores en datos gratuitos: se compara contra referencias simples.")
        cal = rj.get("calibracion_por_evento", {})
        if cal:
            ev = st.selectbox("Mercado y escenario", list(cal), key="cal_jug_ev")
            d = pd.DataFrame(cal[ev])
            base = alt.Chart(d).encode(
                x=alt.X("prob_estimada:Q", title="Probabilidad que dio el bot", scale=alt.Scale(domain=[0, 1])),
                y=alt.Y("frecuencia_real:Q", title="Frecuencia real", scale=alt.Scale(domain=[0, 1])))
            diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(strokeDash=[4, 4], color="gray").encode(x="x", y="y")
            st.altair_chart(diag + base.mark_line(point=True) + base.mark_circle().encode(size="n:Q", tooltip=list(d.columns)),
                            width="stretch")
        pe = pd.DataFrame(rj.get("por_evento", []))
        if len(pe):
            pe = pe[pe["periodo"].isin(["validacion", "actual"])].copy()
            for c in ("prob_media", "frecuencia_real", "error_calibracion", "mayor_desvio"):
                pe[c] = (pe[c] * 100).round(1)
            st.dataframe(pe.round(4), hide_index=True, width="stretch", column_config={
                "prob_media": "Prob. media %", "frecuencia_real": "Real %",
                "error_calibracion": "Error de calibración (pts %)", "mayor_desvio": "Mayor desvío (pts %)"})
            cr = rj.get("criterio", {})
            st.caption(f"«Calibrado» = error de calibración medio ≤ {cr.get('ece_max', 0.02):.0%} y ningún rango con "
                       f"≥ {cr.get('n_min_bin', 200)} casos desviado más de {cr.get('desvio_max', 0.05):.0%}.")
        cd = rj.get("contraste_definicion") or {}
        if cd:
            st.caption(f"Definición de «tiro al arco»: en {cd['equipos_partido']:,} equipo-partido la suma de la fuente "
                       f"coincide con football-data el {cd['coinciden_%']:.0f} % de las veces (razón {cd['razon']:.2f}). "
                       "Betano puede liquidar con otro proveedor de datos: pequeñas diferencias son posibles.")
    if st.button("▶️ Ejecutar backtest de jugadores (tarda unos minutos)", key="bt_jugadores"):
        barra = st.progress(0.0)
        from motor import evaluacion_jugadores as EJ
        EJ.backtest_jugadores(progreso=lambda p, m: barra.progress(min(p, 1.0), m))
        st.rerun()
