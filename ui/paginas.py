"""Páginas de la app."""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from motor import analisis as A
from motor import asistente as AS
from motor import betano as B
from motor import config as C
from motor import datos, ficha
from motor import evaluacion as EV
from motor import fijas as F
from motor import mercados as M
from motor import registro as R
from motor import equipos as EQ
from ui import bloques as BL
from ui import comun as U
from ui import estilos as E

try:  # tiros al arco de jugadores (módulo de la otra sesión de trabajo; opcional)
    from ui import jugadores_ui as JUI
except Exception:  # pragma: no cover
    JUI = None

OPC = {"local": "Local", "empate": "Empate", "visitante": "Visitante", "1X": "Local o Empate",
       "X2": "Visitante o Empate", "12": "Local o Visitante", "mas": "Más de", "menos": "Menos de",
       "si": "Sí", "no": "No"}


# =========================================================================== 💬 CHAT

def _cb_sugerencia():
    v = st.session_state.get("sug_chat")
    if v:
        st.session_state["pendiente"] = v
        st.session_state["sug_chat"] = None


def estado_ia() -> dict:
    """Estado de la IA local (se consulta como mucho cada 30 s)."""
    import time
    from motor import ia_local as IA
    ss = st.session_state
    if ss.get("_ia_est") is None or time.time() - ss.get("_ia_t", 0) > 30:
        ss["_ia_est"], ss["_ia_t"] = IA.estado(), time.time()
    return ss["_ia_est"]


def _responder_chat(msg: str) -> list[dict]:
    ss = st.session_state
    ss.setdefault("ia_hist", [])
    est = estado_ia()
    if est["servidor"] and est["instalado"] and ss.get("usar_ia", True):
        from motor import ia_local as IA
        try:
            texto, bloques = IA.responder(msg, ss.ctx, ss.ia_hist)
            ss.ia_hist += [{"role": "user", "content": msg}, {"role": "assistant", "content": texto}]
            return ([{"tipo": "texto", "md": texto}] if texto else []) + bloques
        except Exception as ex:
            aviso = [{"tipo": "texto", "md": f"⚠️ La IA local no respondió ({type(ex).__name__}); te respondo en modo básico."}]
            return aviso + AS.responder(msg, ss.ctx)
    bloques = AS.responder(msg, ss.ctx)
    if bloques and bloques[0]["tipo"] == "accion":
        if ss.ctx.ultima_super:
            lineas, marcadas = ss.ctx.ultima_super
            for i in marcadas:
                U.agregar_grupo(lineas[i].grupo())
        elif ss.ctx.ultima_combinada:
            U.agregar_candidatas(ss.ctx.ultima_combinada.patas)
        bloques = [{"tipo": "texto", "md": "✅ Listo: la agregué a **🧾 Mi boleta**. Ahí puedes cambiar cuotas, monto y registrarla."}]
    return bloques


def chat() -> None:
    ss = st.session_state
    est = estado_ia()
    ia_ok = est["servidor"] and est["instalado"]
    if ia_ok and not ss.get("_precalentado"):  # carga la IA en segundo plano: la 1.ª respuesta sale más rápido
        import threading
        from motor import ia_local as IA
        ss["_precalentado"] = True
        threading.Thread(target=IA.precalentar, daemon=True).start()
    if not ss.chat:
        E.hero("¡Hola! Soy FútBot ⚽",
               "Tu analista de fútbol para Betano. Pídeme <b>fijas</b> y <b>combinadas</b> con la cuota y el monto que quieras, "
               "pásame las fijas de tu grupo para revisarlas o pregúntame cualquier regla de Betano. "
               "Siempre te digo la probabilidad real: nada es 100 % seguro.")
        c1, c2, c3 = st.columns(3)
        for col, ico, tit, txt in (
                (c1, "🎯", "Fijas con probabilidad real", "Modelo estadístico + mercado + calibración con 9.842 partidos del pasado."),
                (c2, "🧾", "Boleta lista para Betano", "Selección, mercado, cuota, monto y ganancias. Solo copias."),
                (c3, "📘", "Sabe las reglas de Betano", "Pago Anticipado, Multi Bono, Bet Builder, tarjetas, Cash Out…")):
            col.html(f'<div class="fb-feature"><div style="font-size:1.6rem">{ico}</div><b>{tit}</b>'
                     f'<div class="fb-muted" style="margin-top:4px">{txt}</div></div>')
        st.write("")
    c1, c2 = st.columns([3, 1])
    if ia_ok:
        c1.html(f'<div class="fb-muted">🧠 <b>IA local activa</b> ({E.e(est["modelo"])}) · corre en tu PC: gratis, sin internet y '
                'sin gastar tokens de Claude. Conversa como quieras.</div>')
        ss["usar_ia"] = c2.toggle("Usar IA", value=ss.get("usar_ia", True), key="tg_ia")
    else:
        c1.html('<div class="fb-muted">⚙️ <b>Modo básico</b> (entiende frases típicas). Para conversar libremente activa la '
                '<b>IA local gratuita</b> en 📘 Guía → «IA local».</div>')
        if c2.button("Activar IA", key="ir_ia"):
            st.session_state["guia_tab"] = "ia"
            U.ir("guia")
    texto = st.chat_input("Escribe aquí… ej.: «dame fijas seguras para mañana con 20 soles, cuota 3»")
    msg = texto or ss.pop("pendiente", None)
    for i, m in enumerate(ss.chat):
        if m["rol"] == "user":
            with st.chat_message("user", avatar="🧑"):
                st.markdown(m["texto"])
        else:
            with st.chat_message("assistant", avatar="⚽"):
                BL.render(m["bloques"], f"m{i}")
    if not msg:
        st.pills("Prueba con:", AS.SUGERENCIAS, key="sug_chat", on_change=_cb_sugerencia)
    if msg:
        ss.chat.append({"rol": "user", "texto": msg})
        ss.ctx.monto = float(ss.monto)
        with st.chat_message("user", avatar="🧑"):
            st.markdown(msg)
        if ia_ok and ss.get("usar_ia", True):
            from motor import ia_local as IA
            ss.setdefault("ia_hist", [])
            with st.chat_message("assistant", avatar="⚽"):
                try:
                    with st.spinner("🔎 Buscando datos y armando la respuesta…"):
                        turno = IA.iniciar_turno(msg, ss.ctx, ss.ia_hist)
                    BL.render(turno.bloques, f"m{len(ss.chat)}")
                    with st.spinner("🧠 La IA está escribiendo (corre en tu PC)…"):
                        texto = st.write_stream(IA.escribir(turno))
                    texto = IA._limpiar(texto if isinstance(texto, str) else "".join(map(str, texto)))
                    ss.ia_hist += [{"role": "user", "content": msg}, {"role": "assistant", "content": texto}]
                    bloques = turno.bloques + ([{"tipo": "texto", "md": texto}] if texto else [])
                except Exception as ex:
                    bloques = [{"tipo": "texto", "md": f"⚠️ La IA local no respondió ({type(ex).__name__}); "
                                                       "te respondo en modo básico."}] + AS.responder(msg, ss.ctx)
        else:
            with st.chat_message("assistant", avatar="⚽"), st.spinner("Analizando partidos, cuotas y probabilidades…"):
                bloques = _responder_chat(msg)
        ss.chat.append({"rol": "bot", "bloques": bloques})
        st.rerun()
    if ss.chat and st.button("🧹 Nueva conversación"):
        ss.chat = []
        ss.ia_hist = []
        ss.ctx = AS.Contexto(monto=float(ss.monto))
        st.rerun()


# =========================================================================== 🎯 FIJAS

def fijas() -> None:
    from motor import combinador as CB
    E.hero("🎯 Súper boleta segura",
           "Un <b>Bet Builder por partido</b> con lo más probable (goles, doble oportunidad, «equipo anota», córners, "
           "tiros al arco 1+). Marca y desmarca líneas o patas y cambia el monto: la cuota, la ganancia y la probabilidad "
           "se actualizan <b>al instante</b>, como en Betano.")
    ahora = F.ahora_peru()
    px = datos.cargar_proximos()
    quedan_hoy = (not px.empty) and ((px["inicio"] >= ahora) & (px["inicio"] < ahora.normalize() + pd.Timedelta(days=1))).any()
    opciones = {"Hoy": "hoy", "Mañana": "manana", "Fin de semana": "finde", "Próximos días": "semana"}
    c1, c2 = st.columns([1.3, 1.6])
    cuando = c1.segmented_control("📅 ¿Cuándo?", list(opciones), default="Hoy" if quedan_hoy else "Mañana", key="sb_cuando") or "Mañana"
    niveles = {f"{v['emoji']} {v['nombre']} (~{v['cuota_min']:.2f})": k for k, v in CB.NIVELES.items()}
    nivel_txt = c2.segmented_control("🎚️ Seguridad de cada línea", list(niveles), default=list(niveles)[1], key="sb_nivel") or list(niveles)[1]
    c3, c4, c5 = st.columns([1.6, 1.1, 1.3])
    n = c3.pills("🔢 Líneas marcadas", ["Auto", 2, 3, 4, 5, 6, 8, 10], default="Auto", key="sb_n") or "Auto"
    usar_obj = c4.toggle("🎯 Cuota objetivo", key="sb_obj_on")
    objetivo = c4.number_input("Cuota total", 1.2, 100.0, 3.0, 0.5, key="sb_obj", label_visibility="collapsed") if usar_obj else None
    patas = c5.pills("🧩 Patas por partido", [1, 2, 3], default=3, key="sb_patas") or 3
    with st.expander("⚙️ Mercados y ligas"):
        k1, k2, k3 = st.columns(3)
        jug = k1.toggle("Tiros al arco de jugadores", True, key="sb_jug")
        corn = k2.toggle("Córners", True, key="sb_corn")
        tarj = k3.toggle("Tarjetas", False, key="sb_tarj")
        ligas_disp = sorted(px["liga"].unique(), key=lambda c: list(C.LIGAS).index(c) if c in C.LIGAS else 99) if not px.empty else []
        ligas = st.multiselect("Ligas", ligas_disp, format_func=U.nombre_liga, key="sb_ligas", placeholder="Todas las ligas con datos")
    ini, fin, txt = F.ventana(opciones[cuando])
    nivel = niveles[nivel_txt]
    with st.spinner("Armando los Bet Builders más seguros de cada partido…"):
        lineas = CB.generar(ini, fin, nivel, ligas or None, jug, corn, tarj, int(patas))
    if not lineas:
        st.info(f"No hay partidos con datos y cuotas para **{txt}**. Prueba con otro día o baja el nivel de seguridad.")
        return
    marcadas = CB.preseleccion(lineas, None if n == "Auto" else int(n), objetivo)
    izq, der = st.columns([1.25, 1])
    with izq:
        cfg = CB.NIVELES[nivel]
        U.mostrar_super_boleta(lineas, marcadas, float(st.session_state.monto),
                               f"{cfg['emoji']} {cfg['nombre']} · {txt}", key="bv_fijas", extras=12)
    with der:
        st.markdown("#### Cómo usarla")
        st.markdown(
            "- ✅ **Casilla grande**: incluye o quita la línea (partido).\n"
            "- ☑️ **Casillas chicas**: quita una pata del Bet Builder; su cuota se recalcula.\n"
            "- ✏️ **Cuota**: escribe la cuota real que te muestra Betano (las «≈» son estimadas).\n"
            "- 💰 **Monto**: escríbelo o usa +5 / +10 / +20 / +50.\n"
            "- Abajo de las marcadas hay **más opciones** sin marcar: márcalas para subir la cuota.\n"
            "- **➕ A mi boleta** la pasa a 🧾 Mi boleta · **✅ La aposté** la registra · **📋 Copiar** copia el texto.")
        st.info("Cada línea suelta es muy probable, pero **la combinada entera no**: mira «Prob. de acertar todo». "
                "Más líneas = más cuota y más riesgo.")
        st.caption(f"{len(lineas)} partidos cumplen el nivel. Probabilidad = modelo + mercado + calibración del backtest. "
                   "Tiros al arco suponen titularidad (si no es titular, Betano anula todo el Bet Builder y devuelve lo apostado).")
    return


def fijas_simples() -> None:
    """Versión anterior (selecciones simples), sin uso en la navegación."""
    ahora = F.ahora_peru()
    px = datos.cargar_proximos()
    quedan_hoy = (not px.empty) and ((px["inicio"] >= ahora) & (px["inicio"] < ahora.normalize() + pd.Timedelta(days=1))).any()
    opciones = {"Hoy": "hoy", "Mañana": "manana", "Fin de semana": "finde", "Próximos días": "semana"}
    c1, c2 = st.columns([1.3, 1.6])
    cuando = c1.segmented_control("📅 ¿Cuándo?", list(opciones), default="Hoy" if quedan_hoy else "Mañana", key="fj_cuando") or "Mañana"
    niveles = {f"{v['emoji']} {v['nombre']}": k for k, v in F.PERFILES.items()}
    nivel_txt = c2.segmented_control("🎚️ Nivel de riesgo", list(niveles), default="✅ Segura", key="fj_nivel") or "✅ Segura"
    c3, c4, c5 = st.columns([1.3, 1, 1.3])
    n = c3.pills("🔢 Selecciones", [1, 2, 3, 4, 5, 6], default=3, key="fj_n") or 3
    usar_obj = c4.toggle("🎯 Cuota objetivo", key="fj_obj_on")
    objetivo = c4.number_input("Cuota total mínima", 1.2, 50.0, 2.0, 0.1, key="fj_obj", label_visibility="collapsed") if usar_obj else None
    monto = c5.number_input("💰 Monto (S/)", 0.5, 100000.0, float(st.session_state.monto), 5.0, key="fj_monto")
    with st.expander("⚙️ Más filtros (ligas, córners)"):
        ligas_disp = sorted(px["liga"].unique(), key=lambda c: list(C.LIGAS).index(c) if c in C.LIGAS else 99) if not px.empty else []
        ligas = st.multiselect("Ligas", ligas_disp, format_func=U.nombre_liga, key="fj_ligas",
                               placeholder="Todas las ligas con datos")
        corners = st.toggle("Incluir córners (solo modelo, sin cuota de mercado: más incierto)", key="fj_corn")

    ini, fin, txt = F.ventana(opciones[cuando])
    with st.spinner("Buscando las selecciones más probables…"):
        cands = F.candidatas(ini, fin, ligas or None, corners)
    if not cands:
        st.info(f"No hay partidos con cuotas de referencia para **{txt}**. Prueba con otro día "
                "(la fuente trae las ligas europeas de la semana).")
        return
    perfil = niveles[nivel_txt]
    aptas = F.filtrar(cands, perfil)
    patas = F.armar_combinada(aptas, n=n, cuota_objetivo=objetivo)
    if not patas:
        st.warning("Con ese nivel de riesgo no alcanza para armar la combinada. Baja el nivel, usa menos selecciones o menos cuota.")
    else:
        titulo = f"{F.PERFILES[perfil]['emoji']} {'Fija' if n == 1 else 'Combinada'} para {txt} · nivel {F.PERFILES[perfil]['nombre']}"
        BL.combinada(F.Combinada(patas, monto, titulo), "fijas")
    st.divider()
    st.subheader("🔝 Ranking de fijas")
    st.caption("La mejor selección de cada partido, de mayor a menor probabilidad. «≈» = cuota estimada: confírmala en Betano.")
    BL.simples(F.mejores_simples(aptas, 12), f"{len(aptas)} selecciones cumplen el nivel {F.PERFILES[perfil]['nombre']}", "rank")
    with st.expander("ℹ️ ¿Cómo elige el bot?"):
        st.markdown(
            "1. Calcula cada mercado con un **modelo estadístico** (Dixon-Coles con xG, 3 temporadas) y con las **cuotas del mercado** "
            "sin margen; los mezcla con el peso que mejor funcionó en el backtest.\n"
            "2. **Calibra**: si en el pasado, cuando dijo 80 %, pasó 78 %, usa 78 %.\n"
            "3. Para combinadas elige **un partido por línea** (para no repetir riesgo) y la combinación con mayor "
            "probabilidad de acertar todo; con cuota objetivo busca la más probable que llegue a esa cuota.\n"
            "4. Nunca es 100 %: una combinada de 3 selecciones al 85 % acierta ≈ 61 % de las veces.")


# =========================================================================== 📅 PARTIDOS

def _ficha_mercados(liga, local, visitante, cuotas_ref, fecha, clave) -> None:
    """Tabla de todos los mercados del partido con casillas para agregar a la boleta."""
    ml = A.cargar_modelo(liga)
    w, _ = A.peso_modelo()
    mod = M.MotorPartido.desde_modelo(ml, local, visitante) if (ml and ml.ft.tiene(local) and ml.ft.tiene(visitante)) else None
    mer = M.motor_mercado(local, visitante, cuotas_ref, ml) if cuotas_ref else None
    if mod is None and mer is None:
        st.info("No hay modelo para este partido. Ingresa las cuotas 1X2 en **🔍 Verificar**.")
        return
    fm = mod.resumen_mercados() if mod else None
    fk = mer.resumen_mercados() if mer else None
    ref = fm or fk
    filas = []
    for i, f in enumerate(ref):
        pm = fm[i]["p"] if fm else None
        pk = fk[i]["p"] if fk and i < len(fk) and fk[i]["opcion"] == f["opcion"] else None
        pf = F.calibrar(f["seleccion"], M.combinar(pm, pk, w))
        filas.append({"➕": False, "Mercado": f["mercado"], "Selección": f["opcion"],
                      "Bot %": None if pf is None else pf * 100, "Modelo %": None if pm is None else pm * 100,
                      "Mercado %": None if pk is None else pk * 100,
                      "Cuota justa": None if not pf else 1 / pf,
                      "Apuesta si Betano paga ≥": None if not pf else (1 + C.UMBRAL_VALOR) / pf,
                      "Historial del bot": A.evidencia(f["seleccion"], pf, corta=True) or ""})
    tabla = pd.DataFrame(filas)
    editada = st.data_editor(
        tabla, hide_index=True, width="stretch", key=f"ed_{clave}_{local}_{visitante}",
        disabled=[c for c in tabla.columns if c != "➕"],
        column_config={
            "➕": st.column_config.CheckboxColumn("➕", help="Marca para agregar a tu boleta"),
            "Bot %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
            "Modelo %": st.column_config.NumberColumn(format="%.0f%%"),
            "Mercado %": st.column_config.NumberColumn(format="%.0f%%"),
            "Cuota justa": st.column_config.NumberColumn(format="%.2f"),
            "Apuesta si Betano paga ≥": st.column_config.NumberColumn(format="%.2f"),
        })
    fuente = U.elegir_fuente(f"pm_{clave}", "Bot")
    if st.button("➕ Agregar las marcadas a mi boleta", key=f"addm_{clave}", type="primary"):
        marcadas = editada.index[editada["➕"]].tolist()
        if not marcadas:
            st.warning("No marcaste ninguna selección.")
        for i in marcadas:
            st.toast(U.agregar(liga, local, visitante, ref[i]["seleccion"], fuente, cuotas_ref,
                               str(pd.Timestamp(fecha).date()) if fecha is not None else None))
    st.caption("Varias del mismo partido = **Bet Builder** (Betano le pone una cuota propia).")


def _ficha_equipos(liga, local, visitante) -> None:
    df = datos.cargar_partidos()
    temp = ficha.temporada_actual() if liga in C.LIGAS_EUROPA else None
    c1, c2 = st.columns(2)
    for col, eq in ((c1, local), (c2, visitante)):
        with col:
            st.markdown(f"**{eq}** · {'temporada ' + temp if temp else 'últimos datos'}")
            st.dataframe(ficha.resumen(df, eq, liga if liga in C.LIGAS else None, temp), hide_index=True, width="stretch")
            st.dataframe(ficha.ultimos(df, eq, 8), hide_index=True, width="stretch")
    h = ficha.h2h(df, local, visitante)
    st.markdown("**Enfrentamientos directos**")
    st.dataframe(h, hide_index=True, width="stretch") if len(h) else st.caption("Sin enfrentamientos en los datos.")


def detalle_partido(sel: dict) -> None:
    liga, local, visitante, inicio = sel["liga"], sel["local"], sel["visitante"], sel.get("inicio")
    if st.button("← Volver a la lista"):
        st.session_state.pop("partido_sel", None)
        st.rerun()
    BL.partido(liga, local, visitante, inicio, "det", ficha_completa=True)
    ref = A.cuotas_proximo(liga, local, visitante)
    if ref:
        st.caption(f"Mercado de referencia ({ref['fuente']}): 1 {ref['1']:.2f} · X {ref['x']:.2f} · 2 {ref['2']:.2f}"
                   + (f" · Más 2.5 {ref['o25']:.2f}" if ref.get("o25") else ""))
    t1, t2, t3, t4 = st.tabs(["📊 Todos los mercados", "🧩 Bet Builders", "📋 Equipos", "🎯 Jugadores"])
    with t1:
        _ficha_mercados(liga, local, visitante, ref, inicio, "det")
    with t2:
        bbs = F.bet_builders(liga, local, visitante, n=5)
        BL.bet_builders(liga, local, visitante, bbs, st.session_state.monto, "det") if bbs else st.info("Sin sugerencias.")
    with t3:
        _ficha_equipos(liga, local, visitante)
    with t4:
        if JUI is not None and hasattr(JUI, "seccion_jugadores"):
            JUI.seccion_jugadores(liga, local, visitante, ref, inicio, "det", U.agregar)
        else:
            st.info("La sección de tiros al arco de jugadores se está terminando de integrar.")


def partidos() -> None:
    sel = st.session_state.get("partido_sel")
    if sel:
        detalle_partido(sel)
        return
    E.hero("📅 Partidos", "Los próximos partidos con la probabilidad del bot. Toca <b>Analizar</b> para ver todos los mercados, "
                         "Bet Builders y la ficha de cada equipo.")
    tp = U.tabla_proximos(U.firma_cache())
    if tp.empty:
        st.info("No hay partidos próximos en la fuente. Actualiza los datos.")
    else:
        ligas_disp = sorted(tp["liga"].unique(), key=lambda c: list(C.LIGAS).index(c) if c in C.LIGAS else 99)
        elegidas = st.multiselect("Ligas", ligas_disp, default=[l for l in ligas_disp if l in ("E0", "SP1", "I1", "D1", "F1")] or ligas_disp,
                                  format_func=U.nombre_liga, key="pt_ligas")
        vista = tp[tp["liga"].isin(elegidas)] if elegidas else tp
        vista = vista[vista["fecha"] + pd.to_timedelta(vista["hora"].fillna("00:00") + ":00") >= F.ahora_peru() - pd.Timedelta(hours=2)]
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        for fecha, grupo in vista.groupby(vista["fecha"].dt.date):
            st.markdown(f"### {dias[pd.Timestamp(fecha).dayofweek]} {pd.Timestamp(fecha):%d/%m}")
            cols = st.columns(2)
            for i, (_, f) in enumerate(grupo.iterrows()):
                with cols[i % 2]:
                    mejor = max(((n, f[n]) for n, _ in A.SELECCIONES_TABLA if pd.notna(f[n]) and f[n] < 0.97),
                                key=lambda x: x[1], default=(None, None))
                    chip = E.chip(f"⭐ {mejor[0]} {mejor[1]:.0%}", E.nivel(mejor[1])[1]) if mejor[0] else ""
                    st.html(f'<div class="fb-card"><div class="fb-muted">🕒 {E.e(f.hora or "")} · {E.e(U.nombre_liga(f.liga))}</div>'
                            f'<div style="font-weight:800;font-size:1.08rem;margin:4px 0;line-height:1.8">{E.equipo(f.local)}<br>{E.equipo(f.visitante)}</div>'
                            f'{E.barra_1x2(f["1"], f["X"], f["2"], EQ.nombre(f.local), EQ.nombre(f.visitante))}'
                            f'<div style="margin-top:8px">{chip}{E.chip(f"Más 1.5 {f["Más 1.5"]:.0%}", E.COL["azul"]) if pd.notna(f["Más 1.5"]) and mejor[0] != "Más 1.5" else ""}'
                            f'{E.chip(f"Ambos anotan {f["Ambos anotan"]:.0%}", E.COL["azul"]) if pd.notna(f["Ambos anotan"]) and mejor[0] != "Ambos anotan" else ""}'
                            f'<span class="fb-muted" style="font-size:.8rem"> · goles esp. {f.goles_esperados if pd.notna(f.goles_esperados) else "—"}</span></div></div>')
                    if st.button("📊 Analizar", key=f"an_{f.liga}_{f.local}_{f.visitante}"):
                        hora = f.hora if isinstance(f.hora, str) else "00:00"
                        st.session_state["partido_sel"] = {"liga": f.liga, "local": f.local, "visitante": f.visitante,
                                                           "inicio": pd.Timestamp(f"{f.fecha:%Y-%m-%d} {hora}")}
                        st.rerun()
    with st.expander("🔎 Analizar otro partido (Brasil, Argentina, MLS… o cualquier liga con datos)"):
        lg = st.selectbox("Liga", list(C.LIGAS), format_func=U.nombre_liga, key="man_liga")
        eqs = datos.equipos_de_liga(lg)
        ca, cb = st.columns(2)
        lo = ca.selectbox("Local", eqs, key="man_local")
        vi = cb.selectbox("Visitante", [e for e in eqs if e != lo], key="man_visit")
        if st.button("Analizar este partido", key="man_btn"):
            st.session_state["partido_sel"] = {"liga": lg, "local": lo, "visitante": vi, "inicio": None}
            st.rerun()


# =========================================================================== 🔍 VERIFICAR

def _formulario() -> None:
    ligas = list(C.LIGAS) + [C.OTRA_COMPETICION]
    c1, c2, c3 = st.columns(3)
    liga = c1.selectbox("Competición", ligas, format_func=U.nombre_liga, key="v_liga")
    if liga in C.LIGAS:
        eqs = datos.equipos_de_liga(liga)
        local = c2.selectbox("Local", eqs, key="v_local")
        visitante = c3.selectbox("Visitante", [e for e in eqs if e != local], key="v_visit")
    else:
        local = c2.text_input("Local", key="v_local_txt").strip()
        visitante = c3.text_input("Visitante", key="v_visit_txt").strip()
    mercados = list(M.MERCADOS)
    c4, c5, c6 = st.columns([3, 2, 1])
    mercado = c4.selectbox("Mercado", mercados, key="v_mercado",
                           format_func=lambda k: M.MERCADOS[k]["nombre"].format(local=local or "Local", visitante=visitante or "Visitante"))
    info = M.MERCADOS[mercado]
    sel_jugador = None
    if info.get("familia") == "jugadores":
        opcion = c5.selectbox("Tiros al arco", info["opciones"], key="v_opcion_j")
        linea = int(opcion[:-1]) - 0.5
        if JUI is not None and hasattr(JUI, "elegir_jugador"):
            sel_jugador = JUI.elegir_jugador(liga, local, visitante)
        else:
            st.info("Mercado de jugadores todavía en integración.")
    else:
        def etiqueta_opcion(o):
            if mercado in ("1x2", "1t_1x2"):
                return {"local": local or "Local", "empate": "Empate", "visitante": visitante or "Visitante"}[o]
            if mercado == "doble":
                return {"1X": f"{local} o Empate", "X2": f"{visitante} o Empate", "12": f"{local} o {visitante}"}[o]
            return OPC.get(o, o)
        opcion = c5.selectbox("Opción", info["opciones"], format_func=etiqueta_opcion, key="v_opcion")
        linea = c6.selectbox("Línea", info["lineas"], index=min(1, len(info["lineas"]) - 1), key="v_linea") if "lineas" in info else None
    cuotas_ref = None
    with st.expander("Cuotas 1X2 y Más/Menos 2.5 de Betano (obligatorio en «Otra competición»)", expanded=(liga == C.OTRA_COMPETICION)):
        k = st.columns(5)
        q = [k[i].number_input(t, min_value=0.0, step=0.01, format="%.2f", key=f"v_ref_{t}")
             for i, t in enumerate(("1", "X", "2", "Más 2.5", "Menos 2.5"))]
        if all(v > 1 for v in q[:3]):
            cuotas_ref = {"1": q[0], "x": q[1], "2": q[2], "fuente": "cuotas de Betano ingresadas"}
            if q[3] > 1 and q[4] > 1:
                cuotas_ref.update({"o25": q[3], "u25": q[4]})
    fuente = U.elegir_fuente("ver", "Telegram")
    if st.button("➕ Agregar a la boleta", type="primary"):
        if not local or not visitante:
            st.error("Escribe los dos equipos.")
        elif liga == C.OTRA_COMPETICION and not cuotas_ref:
            st.error("Para otras competiciones necesito las cuotas 1X2 de Betano.")
        elif info.get("familia") in ("corners", "tarjetas") and liga not in C.LIGAS_EUROPA:
            st.error("Córners y tarjetas solo tienen datos en las ligas europeas.")
        elif info.get("familia") == "jugadores":
            if not sel_jugador:
                st.error("Elige el jugador.")
            else:
                st.toast(U.agregar(liga, local, visitante, M.Seleccion(mercado, opcion, linea, **sel_jugador),
                                   fuente, cuotas_ref))
                st.rerun()
        else:
            st.toast(U.agregar(liga, local, visitante, M.Seleccion(mercado, opcion, linea), fuente, cuotas_ref))
            st.rerun()


def analisis_boleta(clave: str, importe: float = 0.0) -> dict | None:
    ss = st.session_state
    if not ss.boleta:
        st.info("Tu boleta está vacía. Agrega selecciones desde el **chat**, **🎯 Fijas**, **📅 Partidos** o el formulario.")
        return None
    grupos = [A.Grupo.from_dict(g) for g in ss.boleta]
    res = A.analizar_boleta(grupos, importe)
    for i, (g, l) in enumerate(zip(grupos, res["lineas"])):
        pf = l["p_final"]
        with st.container(border=True):
            a, b, c = st.columns([5, 2, 1])
            titulo = "Bet Builder" if g.bet_builder else l["patas"][0]["titulo"]
            patas = " + ".join(f"{p['titulo']} ({p['mercado']})" for p in l["patas"]) if g.bet_builder else l["patas"][0]["mercado"]
            a.html(f'<div style="display:flex;gap:12px;align-items:center">{E.anillo(pf, 56, 6)}<div>'
                   f'<div style="font-weight:800">{E.e(titulo)} · {E.e(g.local)} vs {E.e(g.visitante)}</div>'
                   f'<div class="fb-muted" style="font-size:.85rem">{E.e(patas)}</div>'
                   f'<div style="margin-top:2px;font-weight:700">{E.e(l["veredicto"])}</div></div></div>')
            nueva = b.number_input("Cuota en Betano", min_value=0.0, step=0.01, format="%.2f",
                                   value=float(g.cuota or 0.0), key=f"{clave}_cuota_{i}_{len(g.selecciones)}")
            if (nueva or None) != g.cuota:
                ss.boleta[i]["cuota"] = nueva if nueva > 1 else None
                st.rerun()
            if c.button("🗑️", key=f"{clave}_del_{i}", help="Quitar"):
                ss.boleta.pop(i)
                st.rerun()
            m = st.columns(4)
            m[0].metric("Prob. del bot", U.pct(pf))
            m[1].metric("Prob. que paga Betano", U.pct(l["p_implicita"]))
            m[2].metric("Cuota justa", f"{l['cuota_justa']:.2f}" if l["cuota_justa"] else "—")
            m[3].metric("Valor esperado", f"{l['valor']:+.1%}" if l["valor"] is not None else "—")
            with st.expander("Detalle y avisos"):
                st.dataframe(pd.DataFrame([{"Selección": p["titulo"], "Mercado": p["mercado"], "Modelo": U.pct(p["p_modelo"]),
                                            "Mercado sin margen": U.pct(p["p_mercado"]), "Bot": U.pct(p["p_final"]),
                                            "Historial del bot": p.get("evidencia") or "—"} for p in l["patas"]]),
                             hide_index=True, width="stretch")
                for av in l["avisos"]:
                    st.caption("⚠️ " + av)
    t = st.columns(4)
    t[0].metric("Líneas", len(grupos))
    t[1].metric("Cuota total", f"{res['cuota_total']:.2f}" if res["cuota_total"] else "—")
    t[2].metric("Prob. de acertar TODO", U.pct(res["p_total"]))
    t[3].metric("Valor esperado", f"{res['valor']:+.1%}" if res["valor"] is not None else "—")
    for av in res["avisos"]:
        st.warning(av)
    d = res["pata_mas_debil"]
    if d:
        g = grupos[d["indice"]]
        txt = (f"🔻 La línea más débil es **{g.local} vs {g.visitante}** ({d['p']:.0%}). Sin ella, acertar todo sube a "
               f"**{d['p_sin_ella']:.0%}**")
        st.info(txt + (f" y la cuota baja a **{d['cuota_sin_ella']:.2f}**." if d["cuota_sin_ella"] else "."))
    return res


def verificar() -> None:
    E.hero("🔍 Verificar fijas", "Pon aquí las fijas del grupo o de un tipster con la cuota que ves en Betano. El bot te dice qué tan "
                                "probable es cada una, su cuota justa y si Betano la paga bien o mal. También puedes escribirlas en el chat: "
                                "<i>«revisa: Leeds o empate a 1.40»</i>.")
    with st.container(border=True):
        _formulario()
    st.caption(M.NO_SOPORTADOS if hasattr(M, "NO_SOPORTADOS") else "")
    analisis_boleta("ver")


# =========================================================================== 🧾 MI BOLETA

def boleta() -> None:
    ss = st.session_state
    E.hero("🧾 Mi boleta", "Copia esta boleta en Betano. Cambia las cuotas por las reales que te muestre la app y elige el monto: "
                          "el bot recalcula todo.")
    if not ss.boleta:
        st.info("Tu boleta está vacía. Pídele fijas al **💬 chat** o agrégalas desde **🎯 Fijas** o **📅 Partidos**.")
        return
    c1, c2 = st.columns([1, 2])
    importe = c1.number_input("💰 Monto (S/)", min_value=0.5, step=5.0, value=float(ss.monto), key="b_monto")
    rapidos = c2.pills("Montos rápidos", [5, 10, 20, 50, 100], key="b_rap")
    if rapidos:
        importe = float(rapidos)
    grupos = [A.Grupo.from_dict(g) for g in ss.boleta]
    res = A.analizar_boleta(grupos, importe)
    n = len(grupos)
    tipo = "Simple" if n == 1 else ("Doble" if n == 2 else ("Triple" if n == 3 else f"Combinada de {n}"))
    lineas = []
    for g, l in zip(grupos, res["lineas"]):
        lineas.append({"titulo": l["patas"][0]["titulo"], "mercado": l["patas"][0]["mercado"], "local": g.local,
                       "visitante": g.visitante, "cuota": l["cuota"], "p": l["p_final"],
                       "patas": [(p["titulo"], p["mercado"]) for p in l["patas"]] if g.bet_builder else None})
    cuotas = [g.cuota for g in grupos]
    mb, seg = B.multi_bono(grupos, cuotas), B.seguro_betano(grupos, cuotas)
    promos = ([f"Multi Bono +{mb['porcentaje']} % sobre las ganancias si acierta"] if mb["aplica"] else []) + \
             ([seg["motivo"]] if seg["aplica"] else [])
    izq, der = st.columns([1.05, 1])
    with izq:
        st.html(E.boleta_html(tipo, lineas, importe, res["cuota_total"], res["p_total"], promos, "Mi boleta · para copiar en Betano"))
        if not mb["aplica"]:
            st.caption("🎁 " + mb["motivo"])
        if importe < B.APUESTA_MINIMA:
            st.error("La apuesta mínima en Betano es S/0.50.")
    with der:
        faltan = [g for g in grupos if not g.cuota]
        if faltan:
            st.warning("Falta la cuota de Betano en alguna línea: ingrésala abajo.")
        if res["valor"] is not None:
            st.metric("Retorno esperado según el bot", f"S/{res['retorno_esperado']:.2f}",
                      f"{res['retorno_esperado'] - importe:+.2f} vs. lo apostado")
        with st.expander("📋 Texto para copiar"):
            st.code(A.texto_boleta(res), language=None)
        fuente = U.elegir_fuente("bol", "Bot")
        nota = st.text_input("Nota (opcional)", key="b_nota")
        r1, r2 = st.columns(2)
        if r1.button("✅ La aposté: registrar", type="primary", disabled=bool(faltan)):
            bid = R.registrar_boleta(res, fuente, nota)
            st.success(f"Boleta #{bid} registrada. Se liquidará sola con los resultados.")
        if r2.button("👁️ Solo seguimiento"):
            bid = R.registrar_boleta(res, fuente, nota, solo_seguimiento=True)
            st.success(f"Boleta #{bid} guardada para medir su acierto, sin dinero.")
        if st.button("🗑️ Vaciar boleta"):
            ss.boleta = []
            st.rerun()
    st.divider()
    st.subheader("Editar cuotas y líneas")
    analisis_boleta("bol", importe)


# =========================================================================== 📒 HISTORIAL

def historial() -> None:
    E.hero("📒 Historial", "Tu balance real y, sobre todo, <b>quién acierta de verdad</b>: el bot, tus propias apuestas, "
                          "el grupo de Telegram o cada tipster. Las boletas se liquidan solas cuando llegan los resultados.")
    df = datos.cargar_partidos()
    if st.button("🔁 Liquidar con los resultados descargados"):
        st.success(f"Líneas liquidadas: {R.liquidar_automatico(df)}. (Champions y competiciones sin datos se marcan a mano.)")
    met = R.metricas()
    b = met["boletas"]
    if b.empty:
        st.info("Aún no hay boletas registradas.")
        return
    if "resumen" in met:
        s = met["resumen"]
        k = st.columns(4)
        k[0].metric("Boletas cerradas (con dinero)", s["boletas_cerradas"])
        k[1].metric("Apostado", f"S/{s['apostado']:.2f}")
        k[2].metric("Neto", f"S/{s['neto']:+.2f}")
        k[3].metric("ROI", f"{s['roi']:+.1%}" if s["roi"] is not None else "—")
    st.subheader("🏆 ¿A quién creerle?")
    p = R.patas()
    p = p[p["resultado"].notna()]
    if len(p):
        tabla = (p.groupby("fuente").agg(selecciones=("id", "count"), acertadas=("resultado", "sum"),
                                         prob_bot=("p_final", "mean"))
                 .assign(acierto_real=lambda x: x["acertadas"] / x["selecciones"]).reset_index())
        tabla["fuente"] = tabla["fuente"].str.replace("tipster:", "📹 ")
        tabla["acierto_real"] = (tabla["acierto_real"] * 100).round(1)
        tabla["prob_bot"] = (tabla["prob_bot"] * 100).round(1)
        st.dataframe(tabla.rename(columns={"prob_bot": "lo que esperaba el bot %", "acierto_real": "acierto real %"}),
                     hide_index=True, width="stretch")
        st.caption("Si una fuente acierta mucho más de lo que el bot esperaba durante muchas selecciones (50+), sabe algo útil. "
                   "Con pocas selecciones, la suerte pesa más que el talento.")
    else:
        st.caption("Todavía no hay selecciones liquidadas para comparar fuentes.")
    if "calibracion_patas" in met:
        st.markdown(f"**Calibración de tus selecciones** (Brier {met['brier_patas']:.3f}; menor es mejor)")
        st.dataframe(met["calibracion_patas"].assign(rango=lambda x: x["rango"].astype(str)), hide_index=True, width="stretch")
    cerr = b[(b["estado"] != "pendiente") & (b["solo_seguimiento"] == 0)].sort_values("id")
    if len(cerr):
        cerr = cerr.assign(neto=lambda x: x["retorno"].fillna(0) - x["importe"].fillna(0))
        cerr["acumulado"] = cerr["neto"].cumsum()
        st.markdown("**Balance acumulado**")
        st.area_chart(cerr.set_index("id")["acumulado"], height=220, color=E.COL["naranja"])
    st.dataframe(b[["id", "creada", "fuente", "importe", "cuota_total", "p_total", "estado", "retorno", "solo_seguimiento", "nota"]],
                 hide_index=True, width="stretch")
    with st.expander("Ver líneas de una boleta / marcar resultado a mano"):
        bid = st.selectbox("Boleta", b["id"].tolist())
        st.dataframe(R.lineas(int(bid))[["liga", "local", "visitante", "cuota", "p_final", "resultado"]], hide_index=True, width="stretch")
        e1, e2, e3 = st.columns(3)
        estado = e1.selectbox("Estado", ["ganada", "perdida", "cashout", "anulada", "pendiente"])
        retorno = e2.number_input("Retorno recibido (S/)", min_value=0.0, step=1.0)
        if e3.button("Guardar estado"):
            R.marcar(int(bid), estado, retorno)
            st.rerun()
        if st.button("Eliminar boleta"):
            R.borrar(int(bid))
            st.rerun()


# =========================================================================== 📹 VIDEOS DE TIPSTERS

def _registrar_fija_video(fj, tipster):
    res = A.analizar_boleta([fj["grupo"]], 0)
    bid = R.registrar_boleta(res, f"tipster:{tipster or 'sin nombre'}", "desde video", solo_seguimiento=True)
    st.toast(f"📹 Fija de {tipster} registrada (#{bid}). Se medirá sola cuando termine el partido.")


def videos() -> None:
    from motor import videos as V
    E.hero("📹 Aprender de tipsters", "Descarga el reel o TikTok del tipster y súbelo aquí. El bot lo <b>transcribe</b>, detecta "
                                     "su fija («mi opción…»), la compara con su propio cálculo y la anota a su nombre para "
                                     "medir con el tiempo cuánto acierta de verdad.")
    c1, c2 = st.columns([2, 1])
    archivo = c1.file_uploader("Video (mp4, mov, webm)", type=["mp4", "mov", "m4v", "webm", "mkv"])
    tipster = c2.text_input("Nombre del tipster", value=st.session_state.get("ult_tipster", ""), placeholder="ej. lasfijas.latam")
    pend = V.pendientes()
    if pend:
        st.caption(f"📂 Hay {len(pend)} video(s) en la carpeta `videos_tipsters`: {', '.join(p.name for p in pend[:5])}")
    rutas = []
    if archivo is not None:
        destino = V.DIR_ENTRADA / archivo.name
        destino.write_bytes(archivo.getvalue())
        rutas = [destino]
    elif pend and st.button(f"Procesar los {len(pend)} video(s) de la carpeta"):
        rutas = pend
    for ruta in rutas:
        st.session_state["ult_tipster"] = tipster
        with st.spinner(f"Transcribiendo {ruta.name}… (la 1.ª vez descarga el modelo de voz, ≈480 MB)"):
            r = V.procesar(ruta, tipster)
        st.session_state.setdefault("videos_hechos", {})[r["id"]] = r
    hechos = st.session_state.get("videos_hechos", {})
    if not hechos:
        for p in sorted(V.DIR_VIDEOS.glob("*/resultado.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:6]:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                hechos[d["id"]] = V.completar(d)
            except Exception:
                continue
    for vid, r in hechos.items():
        with st.container(border=True):
            st.markdown(f"**🎬 {r['archivo']}** · tipster: **{r.get('tipster') or 'sin nombre'}**")
            c1, c2 = st.columns([1, 1.4])
            if r.get("hoja") and Path(r["hoja"]).exists():
                c1.image(r["hoja"], caption="Fotogramas del video")
            with c2:
                st.markdown("**Lo que dice:**")
                st.caption(r["transcripcion"])
                if not r["fijas"]:
                    st.warning("No encontré una fija clara (equipos + mercado). Escríbela en **🔍 Verificar** con fuente «Tipster».")
                for j, fj in enumerate(r["fijas"]):
                    a = fj.get("analisis")
                    sels = " + ".join("{1}: {0}".format(*s.etiqueta(fj["local"], fj["visitante"])) for s in fj["selecciones"])
                    st.markdown(f"🎯 **Su fija:** {sels} · {fj['local']} vs {fj['visitante']}"
                                + (f" · {pd.Timestamp(fj['inicio']):%d/%m %H:%M}" if fj.get("inicio") is not None else ""))
                    if a and a["p_final"]:
                        nom, color = E.nivel(a["p_final"])
                        st.html(f'<div class="fb-card" style="display:flex;gap:12px;align-items:center">{E.anillo(a["p_final"], 56, 6)}'
                                f'<div><b>Según el bot: {a["p_final"]:.0%}</b> · cuota justa {a["cuota_justa"]:.2f}<br>'
                                f'<span class="fb-muted">Si Betano paga menos de {(1 + C.UMBRAL_VALOR) * a["cuota_justa"]:.2f}, no tiene valor.</span></div></div>')
                        for av in a["avisos"][:2]:
                            st.caption("⚠️ " + av)
                    if "grupo" in fj:
                        b1, b2 = st.columns(2)
                        b1.button("📌 Anotar a su nombre (seguimiento)", key=f"vreg_{vid}_{j}", on_click=_registrar_fija_video,
                                  args=(fj, r.get("tipster") or tipster))
                        b2.button("➕ A mi boleta", key=f"vadd_{vid}_{j}", on_click=U.cb_agregar_grupo,
                                  args=(fj["liga"], fj["local"], fj["visitante"], fj["selecciones"], None,
                                        f"tipster:{r.get('tipster') or tipster}"))
    with st.expander("ℹ️ Cómo bajar los videos y por qué así"):
        st.markdown(
            "- Guarda el video desde la app (o con tu herramienta de descarga) y súbelo aquí, o déjalo en la carpeta "
            "`videos_tipsters` del bot.\n"
            "- El bot **no inicia sesión** en Instagram/TikTok ni las revisa solo: sus reglas lo prohíben y la fija va dicha en el video.\n"
            "- Todo se procesa en tu PC (el audio no se envía a ningún lado).\n"
            "- Después de 50+ fijas anotadas, la pestaña **📒 Historial → ¿A quién creerle?** te dirá si ese tipster sabe algo que el bot no.")


# =========================================================================== 📊 CALIDAD

def calidad() -> None:
    E.hero("📊 ¿Qué tan bueno es el bot?", "Backtest sin trampa: la temporada pasada, semana a semana, usando solo los datos que existían antes de cada partido.")
    r = A.resumen_evaluacion()
    if not r:
        st.info("Todavía no se ejecutó el backtest.")
    else:
        st.caption(f"Backtest del {r['fecha']} · {r['periodo']} · {r['partidos']:,} partidos.")
        fg = r.get("fijas_global", {})
        if fg.get("n"):
            k = st.columns(3)
            k[0].metric("Fijas del bot (≥ 75 %)", f"{fg['n']:,}")
            k[1].metric("Probabilidad que dio", f"{fg['prob_media']:.1%}")
            k[2].metric("Acierto real", f"{fg['acierto_real']:.1%}", f"fallaron {1 - fg['acierto_real']:.0%}", delta_color="off")
        cm = r.get("comparacion_mismo_partido", {})
        if cm:
            k = st.columns(4)
            k[0].metric("Error modelo solo", f"{cm['logloss_modelo']:.4f}")
            k[1].metric("Error mercado (apertura)", f"{cm['logloss_mercado_apertura']:.4f}")
            k[2].metric("Error del bot", f"{cm['logloss_bot_final']:.4f}")
            if "logloss_mercado_cierre" in cm:
                k[3].metric("Error mercado al cierre", f"{cm['logloss_mercado_cierre']:.4f}")
            st.caption(f"Log-loss (menor es mejor). Peso óptimo del modelo frente al mercado: {r['peso_modelo']:.0%}.")
        cal = pd.DataFrame(r["calibracion_bot"])
        if len(cal):
            st.markdown("**Lo que el bot dijo vs. lo que pasó** (sobre la línea gris = bien calibrado)")
            base = alt.Chart(cal).encode(x=alt.X("prob_estimada:Q", title="Probabilidad que dio el bot", scale=alt.Scale(domain=[0, 1])),
                                         y=alt.Y("frecuencia_real:Q", title="Frecuencia real", scale=alt.Scale(domain=[0, 1])))
            diag = alt.Chart(pd.DataFrame({"x": [0, 1], "y": [0, 1]})).mark_line(strokeDash=[4, 4], color="gray").encode(x="x", y="y")
            st.altair_chart(diag + base.mark_line(point=True, color=E.COL["naranja"]) +
                            base.mark_circle(color=E.COL["naranja"]).encode(size="n:Q", tooltip=list(cal.columns)), width="stretch")
        pe = pd.DataFrame(r.get("por_evento", []))
        if len(pe):
            st.markdown("**Por mercado: fijas del bot (≥ 75 %) y cuánto acertaron**")
            for c in ("fijas_prob_media", "fijas_acierto_real"):
                pe[c] = (pe[c] * 100).round(1)
            st.dataframe(pe, hide_index=True, width="stretch")
        lab = r.get("laboratorio", {})
        if lab:
            st.markdown(f"**Laboratorio: combinadas de favoritos a cuota ≤ {lab['cuota_max']:.2f}**")
            st.write(f"{lab['n_patas']:,} favoritos · acertaron **{lab['acierto_real_simples']:.1%}** · las cuotas prometían "
                     f"{lab['acierto_implicito_por_cuota']:.1%} · ROI apostando todos: **{lab['roi_simples']:+.1%}**.")
            st.dataframe(pd.DataFrame(lab["combinadas"]).round(3), hide_index=True, width="stretch")
    if JUI is not None and hasattr(JUI, "calidad_jugadores"):  # backtest de tiros al arco de jugadores
        st.divider()
        JUI.calidad_jugadores()
        st.divider()
    with st.expander("Calidad de los datos"):
        q = datos.calidad_datos()
        st.write({k: v for k, v in q.items() if k != "problemas"})
        st.write(f"Problemas detectados: {len(q['problemas'])}")
    if st.button("▶️ Ejecutar backtest ahora (tarda unos minutos)"):
        barra = st.progress(0.0)
        EV.ejecutar_backtest(datos.cargar_partidos(), progreso=lambda p, m: barra.progress(min(p, 1.0), m))
        st.cache_data.clear()
        st.rerun()


# =========================================================================== 📘 GUÍA

def panel_ia() -> None:
    """Estado, instalación del modelo y memoria de la IA local."""
    import requests
    from motor import ia_local as IA
    est = IA.estado()
    st.markdown("#### 🧠 IA local (gratis, en tu PC)")
    st.markdown(
        "La IA de FútBot corre **en tu computadora** con [Ollama](https://ollama.com): no usa tus tokens de Claude, no paga "
        "ninguna API y funciona sin internet. Entiende lo que escribes y usa las herramientas del bot (boletas, partidos, "
        "reglas de Betano, tu historial). Los números siempre salen del motor del bot, no de la IA.")
    k = st.columns(3)
    k[0].metric("Servidor Ollama", "Encendido" if est["servidor"] else "Apagado")
    k[1].metric("Modelo", est["modelo"])
    k[2].metric("Estado", "Lista ✅" if est["servidor"] and est["instalado"] else "Falta descargar")
    if not est["servidor"]:
        st.warning("Ollama no está encendido. Ábrelo desde el menú Inicio (busca «Ollama») y recarga esta página. "
                   "Si no está instalado, instálalo desde ollama.com (gratis).")
        return
    modelos = {"qwen3:4b-instruct": "Recomendado: responde directo, buen español y usa bien las herramientas (~2,5 GB)",
               "qwen2.5:7b": "Más inteligente pero ~2× más lento en tu PC (~4,7 GB)",
               "llama3.2:3b": "El más rápido, algo menos preciso en español (~2 GB)"}
    actual = est["modelo"] if est["modelo"] in modelos else IA.MODELO_DEFECTO

    def _cambiar():
        IA.guardar_config(modelo=st.session_state["ia_modelo"])
        st.session_state["_ia_est"] = None

    elegido = st.radio("Modelo", list(modelos), index=list(modelos).index(actual), on_change=_cambiar,
                       format_func=lambda m: f"{m} — {modelos[m]}", key="ia_modelo")
    if not est["instalado"]:
        if st.button(f"⬇️ Descargar {elegido}", type="primary"):
            barra = st.progress(0.0, "Conectando…")
            with requests.post(f"{IA.URL}/api/pull", json={"model": elegido}, stream=True, timeout=3600) as r:
                for linea in r.iter_lines():
                    if not linea:
                        continue
                    d = json.loads(linea)
                    if d.get("total"):
                        barra.progress(min(d.get("completed", 0) / d["total"], 1.0), d.get("status", ""))
            st.session_state["_ia_est"] = None
            st.success("Modelo listo. Ya puedes conversar en 💬 Chat.")
    notas = IA.memoria()
    st.markdown("**Lo que la IA recuerda de ti** (dile «recuerda que…» en el chat para agregar)")
    if notas:
        for n in notas:
            st.caption("• " + n)
        if st.button("🗑️ Borrar memoria"):
            IA.olvidar_todo()
            st.rerun()
    else:
        st.caption("Todavía nada.")


def guia() -> None:
    E.hero("📘 Guía", "Cómo se usa FútBot, cómo calcula y las reglas de Betano que más importan.")
    if st.session_state.pop("guia_tab", None) == "ia":
        with st.container(border=True):
            panel_ia()
    t1, t0, tc, t2, t3, t4 = st.tabs(["🚀 Cómo se usa", "🧠 IA local", "📱 Celular", "⚙️ Cómo funciona",
                                      "📘 Reglas de Betano", "🛟 Juego responsable"])
    with t0:
        panel_ia()
    with tc:
        from ui import acceso
        acceso.panel_celular()
    with t1:
        pasos = [
            ("Abre la app", "Doble clic en <b>iniciar_bot.bat</b>. Los datos se actualizan solos cada 6 horas al abrirla."),
            ("Pide tus fijas", "En <b>💬 Chat</b> escribe lo que quieres: <i>«fijas de mañana»</i>, <i>«combinada de 4 con cuota 3 con 20 soles»</i>, "
                               "<i>«más segura»</i>, <i>«solo goles de la Premier»</i>. O usa <b>🎯 Fijas</b> con botones."),
            ("Revisa el porqué", "Cada selección trae su probabilidad (anillo de color), su cuota justa y por qué la eligió."),
            ("Copia en Betano", "Agrega a <b>🧾 Mi boleta</b>, cambia las cuotas por las reales de Betano (las «≈» son estimadas) "
                                "y elige el monto. Si la cuota de Betano es menor que la cuota justa, no conviene."),
            ("Registra", "Pulsa <b>✅ La aposté</b> (o <b>👁️ Solo seguimiento</b> para las fijas que no juegas). Se liquida solo."),
            ("Aprende quién acierta", "En <b>📒 Historial → ¿A quién creerle?</b> ves el acierto real del bot, del grupo y de cada tipster. "
                                      "Sube videos de tipsters en <b>📹 Tipsters</b>."),
        ]
        for i, (tit, txt) in enumerate(pasos, 1):
            st.html(f'<div class="fb-step"><div class="num">{i}</div><div><b>{tit}</b><div class="fb-muted">{txt}</div></div></div>')
        st.markdown("#### Colores de probabilidad")
        st.html(" ".join(E.chip(f"{n}: {r}", c) for n, r, c in (("Muy alta", "≥ 85 %", E.COL["verde"]), ("Alta", "75–85 %", E.COL["lima"]),
                                                                    ("Media", "65–75 %", E.COL["ambar"]), ("Riesgo", "< 65 %", E.COL["rosa"]))))
        BL.ayuda()
    with t2:
        ruta = C.RAIZ / "docs" / "como_funciona.md"
        st.markdown(ruta.read_text(encoding="utf-8") if ruta.exists() else "Ver README.md")
    with t3:
        kb = B.base_conocimiento()
        st.caption(f"{kb['fuente']} · consultado {kb['consultado']}. {kb['aviso']}")
        q = st.text_input("🔎 Buscar regla", placeholder="ej. tarjetas, pago anticipado, suspendido")
        reglas = B.buscar_regla(q, n=20) if q else kb["reglas"]
        for r in reglas:
            BL.regla(r)
    with t4:
        st.markdown(
            "- **Ninguna apuesta es segura.** Ni la del bot, ni la del grupo, ni la del tipster con más seguidores.\n"
            "- Usa un **monto fijo pequeño** por boleta y no subas el monto para recuperar lo perdido.\n"
            "- Más selecciones = más cuota, pero **mucho más riesgo**: 5 fijas al 85 % aciertan juntas solo ≈ 44 % de las veces.\n"
            "- Betano tiene herramientas de **límites de depósito, de apuesta y de sesión** en tu cuenta (sección de juego responsable).\n"
            "- Si sientes que el juego te controla, para y busca ayuda. Mayores de 18 años.")
