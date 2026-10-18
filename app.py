"""Bot analítico de fútbol — aplicación web local (Streamlit).

Abrir con:  iniciar_bot.bat   (o: python -m streamlit run app.py)
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import altair as alt
import pandas as pd
import streamlit as st

from motor import analisis as A
from motor import config as C
from motor import datos, ficha, modelo
from motor import evaluacion as E
from motor import jugadores as J
from motor import mercados as M
from motor import registro as R
from ui import jugadores_ui as JUI

st.set_page_config(page_title="Bot analítico de fútbol", page_icon="⚽", layout="wide")

OPC = {"local": "Local", "empate": "Empate", "visitante": "Visitante", "1X": "Local o Empate",
       "X2": "Visitante o Empate", "12": "Local o Visitante", "mas": "Más de", "menos": "Menos de",
       "si": "Sí", "no": "No"}
FUENTES = ["Propia", "Telegram", "Bot"]

if "boleta" not in st.session_state:
    st.session_state.boleta = []  # lista de Grupo.to_dict()


def nombre_liga(c: str) -> str:
    return C.LIGAS.get(c, "Otra competición (Champions, selecciones…)")


def pct(p) -> str:
    return "—" if p is None or pd.isna(p) else f"{p:.0%}"


def agregar(liga, local, visitante, sel: M.Seleccion, fuente: str, cuotas_ref=None, fecha=None) -> str:
    for g in st.session_state.boleta:
        if g["local"] == local and g["visitante"] == visitante:
            if sel.to_dict() in g["selecciones"]:
                return "Esa selección ya estaba en la boleta."
            g["selecciones"].append(sel.to_dict())
            g["cuota"] = None  # el precio del Bet Builder cambia: hay que volver a ingresarlo
            return f"Agregada al Bet Builder de {local} vs {visitante}. Vuelve a ingresar la cuota que muestre Betano."
    st.session_state.boleta.append(A.Grupo(liga, local, visitante, [sel], None, fecha, cuotas_ref,
                                           fuente.lower()).to_dict())
    return f"Agregada: {local} vs {visitante}."


def firma_cache() -> tuple:
    mods = tuple(sorted(p.name for p in C.DIR_MODELOS.glob("*/*.json")))
    return datos._firma(), mods


@st.cache_data(show_spinner="Calculando probabilidades de los próximos partidos…")
def tabla_proximos(_firma) -> pd.DataFrame:
    return A.tabla_proximos()


# --- barra lateral ----------------------------------------------------------------

with st.sidebar:
    st.title("⚽ Bot analítico")
    st.caption("Probabilidades, no certezas. Ningún resultado está garantizado.")
    ult = datos.ultima_descarga()
    st.write(f"**Última consulta de datos:** {ult.replace('T', ' ') if ult else 'nunca'}")
    st.caption(f"Fuente: {C.FUENTE_NOMBRE} (resultados, xG, córners, tarjetas y cuotas de referencia).")
    st.caption(f"Jugadores (tiros al arco): {J.FUENTES[J.fuente_activa()]}"
               + ("" if J.leer_clave() else " · sin clave de API-Football en .env"))
    w, origen_w = A.peso_modelo()
    st.write(f"**Peso del modelo vs. mercado:** {w:.0%}")
    st.caption(origen_w)
    if st.button("🔄 Actualizar datos y modelos", width="stretch"):
        barra = st.progress(0.0, "Iniciando…")
        datos.actualizar(progreso=lambda p, m: barra.progress(min(p, 1.0) * 0.8, m))
        df_all = datos.cargar_partidos()
        modelo.ajustar_todas(df_all, progreso=lambda p, m: barra.progress(0.8 + 0.15 * p, m))
        try:
            J.actualizar(progreso=lambda m: barra.progress(0.95, m))
        except Exception as e:
            st.warning(f"No se pudieron actualizar los datos de jugadores ({type(e).__name__}).")
        n = R.liquidar_automatico(df_all)
        barra.progress(1.0, "Listo")
        st.cache_data.clear()
        st.success(f"Datos y modelos actualizados. Líneas liquidadas: {n}.")
    st.divider()
    nb = len(st.session_state.boleta)
    st.write(f"🧾 **Boleta en armado:** {nb} línea(s)")
    if nb and st.button("Vaciar boleta", width="stretch"):
        st.session_state.boleta = []
        st.rerun()

if not any(C.DIR_RAW.glob("*/*.csv")):
    st.warning("Todavía no hay datos. Pulsa **🔄 Actualizar datos y modelos** en la barra lateral.")
    st.stop()

df = datos.cargar_partidos()
tabs = st.tabs(["📅 Partidos", "🔍 Verificar fijas", "🧾 Boleta guiada", "📒 Historial",
                "📊 Calidad del modelo", "ℹ️ Cómo funciona"])


# --- 1. partidos --------------------------------------------------------------------

def ficha_partido(liga: str, local: str, visitante: str, cuotas_ref: dict | None, fecha=None, clave="p"):
    ml = A.cargar_modelo(liga)
    w, _ = A.peso_modelo()
    mod = M.MotorPartido.desde_modelo(ml, local, visitante) if (ml and ml.ft.tiene(local) and ml.ft.tiene(visitante)) else None
    mer = M.motor_mercado(local, visitante, cuotas_ref, ml) if cuotas_ref else None
    if mod is None and mer is None:
        st.info("No hay modelo para este partido. Ingresa las cuotas 1X2 en *Verificar fijas* para usar el modelo de mercado.")
        return
    c1, c2, c3, c4 = st.columns(4)
    base = mod or mer
    c1.metric(f"Goles esperados {local}", f"{base.lam:.2f}")
    c2.metric(f"Goles esperados {visitante}", f"{base.mu:.2f}")
    medias = base.medias_conteo()
    if "corners" in medias:
        c3.metric("Córners esperados", f"{sum(medias['corners']):.1f}")
    if "tarjetas" in medias:
        c4.metric("Tarjetas esperadas", f"{sum(medias['tarjetas']):.1f}")
    st.caption("Marcadores más probables: " + " · ".join(f"{s} ({p:.0%})" for s, p in base.marcadores_probables(6)))
    if cuotas_ref:
        st.caption(f"Mercado de referencia: {cuotas_ref.get('fuente', 'cuotas ingresadas')} — "
                   f"1: {cuotas_ref['1']:.2f}  X: {cuotas_ref['x']:.2f}  2: {cuotas_ref['2']:.2f}"
                   + (f"  ·  Más 2.5: {cuotas_ref['o25']:.2f}" if cuotas_ref.get("o25") else ""))
    for a in (mod.avisos if mod else []):
        st.warning(a)

    filas_mod = mod.resumen_mercados() if mod else None
    filas_mer = mer.resumen_mercados() if mer else None
    ref = filas_mod or filas_mer
    filas = []
    for i, f in enumerate(ref):
        pm = filas_mod[i]["p"] if filas_mod else None
        pk = filas_mer[i]["p"] if filas_mer and i < len(filas_mer) and filas_mer[i]["opcion"] == f["opcion"] else None
        pf = M.combinar(pm, pk, w)
        filas.append({"Agregar": False, "Mercado": f["mercado"], "Selección": f["opcion"],
                      "Modelo %": None if pm is None else pm * 100, "Mercado %": None if pk is None else pk * 100,
                      "Bot %": None if pf is None else pf * 100,
                      "Falla 1 de cada": None if not pf or pf >= 0.999 else 1 / (1 - pf),
                      "Cuota justa": None if not pf else 1 / pf,
                      "Apostar solo si Betano paga ≥": None if not pf else (1 + C.UMBRAL_VALOR) / pf,
                      "Historial del bot": A.evidencia(f["seleccion"], pf, corta=True) or ""})
    tabla = pd.DataFrame(filas)
    editada = st.data_editor(
        tabla, hide_index=True, width="stretch", key=f"editor_{clave}_{local}_{visitante}",
        disabled=[c for c in tabla.columns if c != "Agregar"],
        column_config={
            "Agregar": st.column_config.CheckboxColumn("➕", help="Marca para agregar a la boleta"),
            "Modelo %": st.column_config.NumberColumn(format="%.0f%%"),
            "Mercado %": st.column_config.NumberColumn(format="%.0f%%"),
            "Bot %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
            "Falla 1 de cada": st.column_config.NumberColumn(format="%.1f partidos"),
            "Cuota justa": st.column_config.NumberColumn(format="%.2f"),
            "Apostar solo si Betano paga ≥": st.column_config.NumberColumn(format="%.2f"),
            "Historial del bot": st.column_config.TextColumn(
                help="En el backtest 2025/26, cuántas veces se cumplió este mercado cuando el bot dio una probabilidad parecida"),
        })
    fuente = st.radio("¿De dónde viene esta selección?", FUENTES, index=2, horizontal=True, key=f"fuente_{clave}")
    if st.button("➕ Agregar las marcadas a la boleta", key=f"add_{clave}"):
        marcadas = editada.index[editada["Agregar"]].tolist()
        if not marcadas:
            st.warning("No marcaste ninguna selección.")
        for i in marcadas:
            msg = agregar(liga, local, visitante, ref[i]["seleccion"], fuente, cuotas_ref,
                          str(pd.Timestamp(fecha).date()) if fecha is not None else None)
            st.toast(msg)
    st.caption("Si marcas varias del mismo partido, quedan juntas como **Bet Builder**. "
               "Probabilidades del bot = modelo estadístico + mercado, con el peso que justificó el backtest.")

    JUI.seccion_jugadores(liga, local, visitante, cuotas_ref, fecha, clave, agregar)

    with st.expander("📋 Ficha de los equipos (forma, local/visitante, enfrentamientos)"):
        temp = ficha.temporada_actual() if liga in C.LIGAS_EUROPA else None
        for eq in (local, visitante):
            st.markdown(f"**{eq}** — {'temporada ' + temp if temp else 'últimos datos'} en {nombre_liga(liga)}")
            res = ficha.resumen(df, eq, liga if liga in C.LIGAS else None, temp)
            st.dataframe(res, hide_index=True, width="stretch")
            st.dataframe(ficha.ultimos(df, eq, 8), hide_index=True, width="stretch")
        st.markdown("**Enfrentamientos directos en la base de datos**")
        h = ficha.h2h(df, local, visitante)
        st.dataframe(h, hide_index=True, width="stretch") if len(h) else st.caption("Sin enfrentamientos en los datos.")


with tabs[0]:
    st.subheader("Próximos partidos con probabilidades del bot")
    tp = tabla_proximos(firma_cache())
    if tp.empty:
        st.info("No hay partidos próximos en la fuente. Actualiza los datos.")
    else:
        ligas_disp = sorted(tp["liga"].unique(), key=lambda c: list(C.LIGAS).index(c) if c in C.LIGAS else 99)
        sel_ligas = st.multiselect("Ligas", ligas_disp, default=[l for l in ligas_disp if l in ("E0", "SP1", "I1", "D1", "F1", "P1", "N1")],
                                   format_func=nombre_liga)
        vista = tp[tp["liga"].isin(sel_ligas)] if sel_ligas else tp
        mostrar = vista.copy()
        mostrar["Partido"] = mostrar["local"] + " vs " + mostrar["visitante"]
        dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        mostrar["Fecha"] = (mostrar["fecha"].dt.dayofweek.map(lambda d: dias[int(d)]) + " "
                            + mostrar["fecha"].dt.strftime("%d/%m") + " " + mostrar["hora"].fillna(""))
        cols_p = [n for n, _ in A.SELECCIONES_TABLA]
        for c in cols_p:
            mostrar[c] = mostrar[c] * 100
        st.dataframe(
            mostrar[["Fecha", "liga", "Partido", "goles_esperados"] + cols_p], hide_index=True, width="stretch",
            column_config={c: st.column_config.NumberColumn(format="%.0f%%") for c in cols_p}
            | {"liga": "Liga", "goles_esperados": st.column_config.NumberColumn("Goles esp.", format="%.2f")})
        st.caption("Horas en hora de Perú (convertidas desde la hora del Reino Unido de la fuente). "
                   "Confirma siempre la hora en Betano.")

        st.markdown("#### Selecciones de mayor probabilidad esta semana")
        st.caption("Ojo: «más probable» no es «buena apuesta». Una selección al 85 % pierde 15 de cada 100 veces; "
                   "solo conviene si Betano paga más que la cuota justa.")
        largas = []
        for _, f in vista.iterrows():
            for c in cols_p:
                if pd.notna(f[c]):
                    largas.append({"Fecha": f.fecha.strftime("%d/%m"), "Partido": f"{f.local} vs {f.visitante}",
                                   "Selección": c, "Bot %": f[c] * 100, "Cuota justa": 1 / f[c],
                                   "Apostar solo si Betano paga ≥": (1 + C.UMBRAL_VALOR) / f[c]})
        if largas:
            top = pd.DataFrame(largas)
            top = top[(top["Bot %"] >= 70) & (top["Bot %"] < 97)].sort_values("Bot %", ascending=False).head(25)
            st.dataframe(top, hide_index=True, width="stretch", column_config={
                "Bot %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
                "Cuota justa": st.column_config.NumberColumn(format="%.2f"),
                "Apostar solo si Betano paga ≥": st.column_config.NumberColumn(format="%.2f")})

        st.markdown("#### Análisis de un partido")
        opciones = list(vista.index)
        elegido = st.selectbox("Partido", opciones, format_func=lambda i: (
            f"{vista.at[i, 'fecha']:%d/%m} {vista.at[i, 'hora'] or ''} · {nombre_liga(vista.at[i, 'liga'])} · "
            f"{vista.at[i, 'local']} vs {vista.at[i, 'visitante']}"))
        if elegido is not None:
            f = vista.loc[elegido]
            ficha_partido(f.liga, f.local, f.visitante, A.cuotas_proximo(f.liga, f.local, f.visitante), f.fecha, "prox")

    st.divider()
    with st.expander("🔎 Analizar otro partido (Brasil, Argentina, MLS… o cualquier liga con datos)"):
        lg = st.selectbox("Liga", list(C.LIGAS), format_func=nombre_liga, key="man_liga")
        eqs = datos.equipos_de_liga(lg)
        ca, cb = st.columns(2)
        lo = ca.selectbox("Local", eqs, key="man_local")
        vi = cb.selectbox("Visitante", [e for e in eqs if e != lo], key="man_visit")
        if lo and vi:
            ficha_partido(lg, lo, vi, A.cuotas_proximo(lg, lo, vi), None, "man")


# --- 2. verificar fijas -------------------------------------------------------------

def formulario_seleccion():
    st.markdown("##### Agregar una selección (por ejemplo, una «fija» del grupo de Telegram)")
    ligas = list(C.LIGAS) + [C.OTRA_COMPETICION]
    c1, c2, c3 = st.columns([2, 2, 2])
    liga = c1.selectbox("Competición", ligas, format_func=nombre_liga, key="v_liga")
    if liga in C.LIGAS:
        eqs = datos.equipos_de_liga(liga)
        local = c2.selectbox("Local", eqs, key="v_local")
        visitante = c3.selectbox("Visitante", [e for e in eqs if e != local], key="v_visit")
    else:
        local = c2.text_input("Local", key="v_local_txt").strip()
        visitante = c3.text_input("Visitante", key="v_visit_txt").strip()

    c4, c5, c6 = st.columns([3, 2, 1])
    mercado = c4.selectbox("Mercado", list(M.MERCADOS), key="v_mercado",
                           format_func=lambda k: M.MERCADOS[k]["nombre"].format(local=local or "Local",
                                                                                 visitante=visitante or "Visitante"))
    info = M.MERCADOS[mercado]

    def etiqueta_opcion(o):
        if mercado in ("1x2", "1t_1x2"):
            return {"local": local or "Local", "empate": "Empate", "visitante": visitante or "Visitante"}[o]
        if mercado == "doble":
            return {"1X": f"{local} o Empate", "X2": f"{visitante} o Empate", "12": f"{local} o {visitante}"}[o]
        return OPC.get(o, o)
    opcion = c5.selectbox("Opción", info["opciones"], format_func=etiqueta_opcion, key="v_opcion")
    linea = c6.selectbox("Línea", info["lineas"], index=min(1, len(info["lineas"]) - 1), key="v_linea") if "lineas" in info else None
    jugador_sel = JUI.elegir_jugador(liga, local, visitante) if mercado == "jug_arco" else None

    cuotas_ref = None
    with st.expander("Cuotas de referencia 1X2 y Más/Menos 2.5 (obligatorio en «Otra competición»; opcional en ligas)",
                     expanded=(liga == C.OTRA_COMPETICION)):
        st.caption("Cópialas de Betano. Sirven para estimar lo que «sabe» el mercado del partido.")
        k1, kx, k2, ko, ku = st.columns(5)
        q = [k.number_input(t, min_value=0.0, step=0.01, format="%.2f", key=f"v_ref_{t}")
             for k, t in ((k1, "1"), (kx, "X"), (k2, "2"), (ko, "Más 2.5"), (ku, "Menos 2.5"))]
        if all(v > 1 for v in q[:3]):
            cuotas_ref = {"1": q[0], "x": q[1], "2": q[2], "fuente": "cuotas de Betano ingresadas"}
            if q[3] > 1 and q[4] > 1:
                cuotas_ref.update({"o25": q[3], "u25": q[4]})
    fuente = st.radio("Fuente", FUENTES, horizontal=True, key="v_fuente")
    if st.button("➕ Agregar a la boleta", type="primary"):
        if not local or not visitante:
            st.error("Escribe los dos equipos.")
        elif liga == C.OTRA_COMPETICION and not cuotas_ref and mercado != "jug_arco":
            st.error("Para otras competiciones necesito las cuotas 1X2 de Betano (no hay datos propios).")
        elif M.MERCADOS[mercado]["familia"] in ("corners", "tarjetas") and liga not in C.LIGAS_EUROPA:
            st.error("Para córners y tarjetas solo hay datos de las ligas europeas.")
        elif mercado == "jug_arco" and not jugador_sel:
            st.error("Elige un jugador (y que exista el backtest de tiros al arco).")
        else:
            if mercado == "jug_arco":
                sel = M.Seleccion(mercado, opcion, int(opcion[:-1]) - 0.5, **jugador_sel)
            else:
                sel = M.Seleccion(mercado, opcion, linea)
            st.toast(agregar(liga, local, visitante, sel, fuente, cuotas_ref))
            st.rerun()
    st.caption(M.NO_SOPORTADOS)


def analisis_boleta(clave: str, importe: float = 0.0) -> dict | None:
    if not st.session_state.boleta:
        st.info("La boleta está vacía. Agrega selecciones desde **Partidos** o con el formulario.")
        return None
    grupos = [A.Grupo.from_dict(g) for g in st.session_state.boleta]
    res = A.analizar_boleta(grupos, importe)
    for i, (g, l) in enumerate(zip(grupos, res["lineas"])):
        with st.container(border=True):
            a, b, c = st.columns([5, 2, 1])
            titulo = "Bet Builder" if g.bet_builder else l["patas"][0]["titulo"]
            if not g.bet_builder and g.selecciones[0].es_jugador:
                titulo = f"{l['patas'][0]['mercado']} {titulo}"
            a.markdown(f"**{titulo}** — {g.local} vs {g.visitante}  \n"
                       f"<small>{nombre_liga(g.liga)} · fuente: {g.fuente}</small>", unsafe_allow_html=True)
            nueva = b.number_input("Cuota en Betano", min_value=0.0, step=0.01, format="%.2f",
                                   value=float(g.cuota or 0.0), key=f"{clave}_cuota_{i}_{len(g.selecciones)}")
            if (nueva or None) != g.cuota:
                st.session_state.boleta[i]["cuota"] = nueva if nueva > 1 else None
                st.rerun()
            if c.button("🗑️", key=f"{clave}_del_{i}", help="Quitar esta línea"):
                st.session_state.boleta.pop(i)
                st.rerun()
            patas = pd.DataFrame([{"Selección": p["titulo"], "Mercado": p["mercado"], "Modelo": pct(p["p_modelo"]),
                                   "Mercado (sin margen)": pct(p["p_mercado"]), "Bot": pct(p["p_final"]),
                                   "Historial del bot": p.get("evidencia") or "—"}
                                  for p in l["patas"]])
            st.dataframe(patas, hide_index=True, width="stretch")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Prob. del bot" + (" (conjunta)" if g.bet_builder else ""), pct(l["p_final"]))
            m2.metric("Prob. que paga Betano", pct(l["p_implicita"]))
            m3.metric("Cuota justa", f"{l['cuota_justa']:.2f}" if l["cuota_justa"] else "—")
            m4.metric("Valor esperado", f"{l['valor']:+.1%}" if l["valor"] is not None else "—")
            st.markdown(f"**{l['veredicto']}**" + (f" · falla aprox. {(1 - l['p_final']) * 10:.1f} de cada 10 veces"
                                                  if l["p_final"] else ""))
            for av in l["avisos"]:
                st.caption("⚠️ " + av)
    st.markdown("---")
    t1, t2, t3, t4 = st.columns(4)
    t1.metric("Líneas", len(grupos))
    t2.metric("Cuota total", f"{res['cuota_total']:.2f}" if res["cuota_total"] else "—")
    t3.metric("Prob. de acertar TODO", pct(res["p_total"]))
    t4.metric("Valor esperado de la boleta", f"{res['valor']:+.1%}" if res["valor"] is not None else "—")
    for av in res["avisos"]:
        st.warning(av)
    d = res["pata_mas_debil"]
    if d:
        g = grupos[d["indice"]]
        txt = (f"La línea más débil es **{g.local} vs {g.visitante}** ({d['p']:.0%}). "
               f"Sin ella, la probabilidad de acertar todo sube a **{d['p_sin_ella']:.0%}**")
        if d["cuota_sin_ella"]:
            txt += f" y la cuota baja a **{d['cuota_sin_ella']:.2f}**"
        st.info(txt + ".")
    return res


with tabs[1]:
    st.subheader("Verificador de fijas")
    st.caption("Pon aquí las fijas del grupo (o las tuyas) con la cuota que ves en Betano. El bot dice qué tan "
               "probable es cada una, cuál es su cuota justa y si Betano la está pagando bien o mal.")
    formulario_seleccion()
    st.divider()
    analisis_boleta("ver")


# --- 3. boleta guiada ---------------------------------------------------------------

def html_boleta(res: dict) -> str:
    e = html.escape
    n = len(res["lineas"])
    tipo = "Simple" if n == 1 else ("Doble" if n == 2 else f"Combinada de {n}")
    imp = res["importe"] or 0
    partes = [
        '<div style="max-width:430px;font-family:system-ui,Segoe UI,Roboto,sans-serif;background:#fff;color:#1d2433;'
        'border-radius:14px;border:1px solid #d9dde5;overflow:hidden">',
        f'<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;'
        f'border-bottom:1px solid #e6e9ef"><b>{tipo}</b> <span>S/{imp:.2f}</span>'
        '<span style="font-size:12px;border:1px solid #9aa3b2;border-radius:10px;padding:2px 8px;color:#56607a">'
        'Propuesta del bot</span></div>']
    for l in res["lineas"]:
        g = l["grupo"]
        cuota = f"{l['cuota']:.2f}" if l["cuota"] else "—"
        bb = g.bet_builder
        tit = "Bet Builder" if bb else l["patas"][0]["titulo"]
        color_tit = "#c2410c" if bb else "#1d2433"
        partes.append('<div style="padding:12px 16px;border-bottom:1px solid #e6e9ef">')
        partes.append(f'<div style="display:flex;justify-content:space-between;align-items:center">'
                      f'<span style="font-weight:700;color:{color_tit}">⚽ {e(tit)}</span>'
                      f'<span style="background:#f1f3f7;border-radius:6px;padding:3px 9px;font-weight:700">{cuota}</span></div>')
        if not bb:
            partes.append(f'<div style="color:#5b6b8c;font-size:14px;margin:2px 0 0 22px">{e(l["patas"][0]["mercado"])}</div>')
        partes.append(f'<div style="margin:4px 0 0 22px;font-size:15px">{e(g.local)}<br>{e(g.visitante)}</div>')
        if bb:
            for p in l["patas"]:
                partes.append(f'<div style="margin:6px 0 0 22px;padding-left:12px;border-left:2px solid #f0a37a">'
                              f'<b>{e(p["titulo"])}</b><br><span style="color:#5b6b8c;font-size:14px">{e(p["mercado"])}</span></div>')
        pf = l["p_final"]
        prob = f"Prob. estimada {pf:.0%} · cuota justa {1 / pf:.2f}" if pf else "Sin probabilidad calculada"
        partes.append(f'<div style="margin:6px 0 0 22px;font-size:12px;color:#56607a">{prob} · {e(l["veredicto"])}</div></div>')
    pie = f'<div style="padding:12px 16px;line-height:1.7"><div style="display:flex;justify-content:space-between">' \
          f'<span>Apuesta</span><b>S/{imp:.2f}</b></div>'
    if res["cuota_total"]:
        pie += f'<div style="display:flex;justify-content:space-between"><span>Cuota total</span><b>{res["cuota_total"]:.2f}</b></div>'
    if res["ganancia_potencial"] and imp:
        pie += f'<div style="display:flex;justify-content:space-between;font-size:18px"><span>Ganancias potenciales</span>' \
               f'<b>S/{res["ganancia_potencial"]:.2f}</b></div>'
    if res["p_total"] is not None:
        pie += f'<div style="display:flex;justify-content:space-between;color:#56607a"><span>Prob. de acertar todo</span>' \
               f'<b>{res["p_total"]:.0%}</b></div>'
    partes.append(pie + "</div></div>")
    return "".join(partes)


with tabs[2]:
    st.subheader("Boleta guiada para copiar en Betano")
    st.caption("Tú decides el importe. El bot no decide cuánto apostar: solo calcula probabilidades y retornos.")
    c1, c2 = st.columns([1, 2])
    importe = c1.number_input("Importe (S/)", min_value=0.0, step=5.0, value=0.0, format="%.2f")
    if st.session_state.boleta:
        grupos = [A.Grupo.from_dict(g) for g in st.session_state.boleta]
        res = A.analizar_boleta(grupos, importe)
        faltan = [g for g in grupos if not g.cuota]
        if faltan:
            st.warning("Falta la cuota de Betano en alguna línea (ingrésala en **Verificar fijas**).")
        izq, der = st.columns([1, 1])
        with izq:
            st.html(html_boleta(res))
        with der:
            st.markdown("**Texto para copiar**")
            st.code(A.texto_boleta(res), language=None)
            if res["valor"] is not None:
                st.metric("Retorno esperado según el bot", f"S/{res['retorno_esperado']:.2f}",
                          delta=f"{res['retorno_esperado'] - importe:+.2f} vs. lo apostado")
            fuente_b = st.radio("Fuente de la boleta", FUENTES, horizontal=True, key="b_fuente")
            nota = st.text_input("Nota (opcional)")
            r1, r2 = st.columns(2)
            if r1.button("✅ Registrar (la aposté)", type="primary", disabled=importe <= 0 or bool(faltan)):
                bid = R.registrar_boleta(res, fuente_b.lower(), nota)
                st.success(f"Boleta #{bid} registrada. Se liquidará sola cuando haya resultados.")
            if r2.button("👁️ Solo seguimiento (no aposté)"):
                bid = R.registrar_boleta(res, fuente_b.lower(), nota, solo_seguimiento=True)
                st.success(f"Boleta #{bid} guardada para medir su acierto, sin dinero.")
            st.caption("Registrar también las fijas del Telegram que NO juegas permite medir, con el tiempo, "
                       "cuánto aciertan de verdad.")
    else:
        st.info("La boleta está vacía.")


# --- 4. historial -------------------------------------------------------------------

with tabs[3]:
    st.subheader("Historial y resultados reales")
    if st.button("🔁 Liquidar con los resultados descargados"):
        n = R.liquidar_automatico(df)
        st.success(f"Líneas liquidadas: {n}. (Champions y otras competiciones sin datos se marcan a mano.)")
    met = R.metricas()
    b = met["boletas"]
    if b.empty:
        st.info("Aún no hay boletas registradas.")
    else:
        if "resumen" in met:
            s = met["resumen"]
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Boletas cerradas (con dinero)", s["boletas_cerradas"])
            k2.metric("Apostado", f"S/{s['apostado']:.2f}")
            k3.metric("Neto", f"S/{s['neto']:+.2f}")
            k4.metric("ROI", f"{s['roi']:+.1%}" if s["roi"] is not None else "—")
        if "por_fuente" in met and len(met["por_fuente"]):
            st.markdown("**Acierto real por fuente** (incluye las de solo seguimiento)")
            pf = met["por_fuente"].copy()
            pf["prob_media_estimada"] = (pf["prob_media_estimada"] * 100).round(1)
            pf["tasa_real"] = (pf["tasa_real"] * 100).round(1)
            st.dataframe(pf, hide_index=True, width="stretch")
        if "calibracion_patas" in met:
            st.markdown(f"**Calibración de tus selecciones** (Brier = {met['brier_patas']:.3f}; menor es mejor)")
            st.dataframe(met["calibracion_patas"].assign(rango=lambda x: x["rango"].astype(str)),
                         hide_index=True, width="stretch")
        cerr = b[b["estado"] != "pendiente"].sort_values("id")
        if len(cerr):
            cerr = cerr.assign(neto=lambda x: x["retorno"].fillna(0) - x["importe"].fillna(0))
            cerr["acumulado"] = cerr["neto"].cumsum()
            st.line_chart(cerr.set_index("id")["acumulado"], height=220)
        st.dataframe(b[["id", "creada", "fuente", "importe", "cuota_total", "p_total", "estado", "retorno",
                        "solo_seguimiento", "nota"]], hide_index=True, width="stretch")
        with st.expander("Ver líneas de una boleta / marcar resultado a mano"):
            bid = st.selectbox("Boleta", b["id"].tolist())
            st.dataframe(R.lineas(int(bid))[["liga", "local", "visitante", "cuota", "p_final", "resultado"]],
                         hide_index=True, width="stretch")
            e1, e2, e3 = st.columns(3)
            estado = e1.selectbox("Estado", ["ganada", "perdida", "cashout", "anulada", "pendiente"])
            retorno = e2.number_input("Retorno recibido (S/)", min_value=0.0, step=1.0)
            if e3.button("Guardar estado"):
                R.marcar(int(bid), estado, retorno)
                st.rerun()
            if st.button("Eliminar boleta", type="secondary"):
                R.borrar(int(bid))
                st.rerun()


# --- 5. calidad del modelo ----------------------------------------------------------

with tabs[4]:
    st.subheader("¿Qué tan bueno es el bot? (backtest sin trampa)")
    r = A.resumen_evaluacion()
    if not r:
        st.info("Todavía no se ejecutó el backtest.")
    else:
        st.caption(f"Backtest del {r['fecha']} · periodo {r['periodo']} · {r['partidos']:,} partidos predichos "
                   "semana a semana usando solo datos anteriores a cada partido.")
        cm = r.get("comparacion_mismo_partido", {})
        if cm:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Error del modelo solo", f"{cm['logloss_modelo']:.4f}")
            c2.metric("Error del mercado (apertura)", f"{cm['logloss_mercado_apertura']:.4f}")
            c3.metric("Error del bot (combinado)", f"{cm['logloss_bot_final']:.4f}")
            if "logloss_mercado_cierre" in cm:
                c4.metric("Error del mercado al cierre", f"{cm['logloss_mercado_cierre']:.4f}")
            st.caption("Log-loss medio en 10 mercados (1X2, doble oportunidad, Más/Menos, ambos anotan). "
                       f"Menor es mejor. Peso óptimo del modelo: {r['peso_modelo']:.0%}.")
        fg = r.get("fijas_global", {})
        if fg.get("n"):
            st.info(f"De **{fg['n']:,}** selecciones que el bot daba como «fija» (≥ 75 %), con una probabilidad media "
                    f"de **{fg['prob_media']:.1%}**, acertaron **{fg['acierto_real']:.1%}**. "
                    "Si esos dos números se parecen, el bot está bien calibrado; aun así, fallaron "
                    f"{1 - fg['acierto_real']:.0%} de las veces.")
        cal = pd.DataFrame(r["calibracion_bot"])
        if len(cal):
            st.markdown("**Calibración: lo que el bot dijo vs. lo que pasó**")
            base = alt.Chart(cal).encode(
                x=alt.X("prob_estimada:Q", title="Probabilidad que dio el bot", scale=alt.Scale(domain=[0, 1])),
                y=alt.Y("frecuencia_real:Q", title="Frecuencia real", scale=alt.Scale(domain=[0, 1])))
            diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(strokeDash=[4, 4], color="gray").encode(x="x", y="y")
            st.altair_chart(diag + base.mark_line(point=True) + base.mark_circle().encode(size="n:Q", tooltip=list(cal.columns)),
                            width="stretch")
        pe = pd.DataFrame(r.get("por_evento", []))
        if len(pe):
            st.markdown("**Por mercado: las «fijas» del bot (≥ 75 %) y cuánto acertaron**")
            for c in ("fijas_prob_media", "fijas_acierto_real"):
                pe[c] = (pe[c] * 100).round(1)
            st.dataframe(pe, hide_index=True, width="stretch")
        cc = pd.DataFrame(r.get("conteos_por_evento", []))
        if len(cc):
            st.markdown("**Córners y tarjetas (solo modelo, sin mercado de referencia)**")
            st.dataframe(cc.round(3), hide_index=True, width="stretch")
        lab = r.get("laboratorio", {})
        if lab:
            st.markdown(f"**Laboratorio de combinadas: favoritos a cuota ≤ {lab['cuota_max']:.2f}** "
                        "(cuotas promedio de casas, parecidas a las de Betano)")
            st.write(f"Simples: {lab['n_patas']:,} favoritos · acertaron **{lab['acierto_real_simples']:.1%}** · "
                     f"las cuotas prometían {lab['acierto_implicito_por_cuota']:.1%} · "
                     f"ROI apostando todos: **{lab['roi_simples']:+.1%}**.")
            sv = lab.get("simples_con_valor_segun_bot", {})
            if sv.get("n"):
                st.write(f"Solo los que el bot marcaba «con valor»: {sv['n']} · acierto {sv['acierto']:.1%} · "
                         f"ROI **{sv['roi']:+.1%}**.")
            st.dataframe(pd.DataFrame(lab["combinadas"]).round(3), hide_index=True, width="stretch")
            st.caption("acierto_azar / roi_azar: combinadas armadas al azar entre favoritos de la misma semana. "
                       "acierto_bot / roi_bot: las N más probables según el bot cada semana.")
        pl = pd.DataFrame(r["por_liga"])
        if len(pl):
            with st.expander("Detalle por liga"):
                pl["liga"] = pl["liga"].map(nombre_liga)
                st.dataframe(pl.round(4), hide_index=True, width="stretch")
    st.divider()
    JUI.calidad_jugadores()
    st.divider()
    with st.expander("Calidad de los datos"):
        q = datos.calidad_datos(df)
        st.write({k: v for k, v in q.items() if k != "problemas"})
        st.write(f"Problemas detectados: {len(q['problemas'])}")
        if q["problemas"]:
            st.dataframe(pd.DataFrame(q["problemas"]), hide_index=True)
    if st.button("▶️ Ejecutar backtest ahora (tarda unos minutos)"):
        barra = st.progress(0.0)
        E.ejecutar_backtest(df, progreso=lambda p, m: barra.progress(min(p, 1.0), m))
        st.cache_data.clear()
        st.rerun()


# --- 6. cómo funciona ---------------------------------------------------------------

with tabs[5]:
    st.markdown((Path(__file__).parent / "docs" / "como_funciona.md").read_text(encoding="utf-8")
                if (Path(__file__).parent / "docs" / "como_funciona.md").exists() else "Ver README.md")
