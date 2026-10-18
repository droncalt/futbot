"""Dibujo de las respuestas del bot (chat y páginas): boletas, fijas, partidos, reglas…"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from motor import analisis as A
from motor import asistente as AS
from motor import betano as B
from motor import fijas as F
from motor import mercados as M
from motor import registro as R
from motor import equipos as EQ
from ui import comun as U
from ui import estilos as E


def lineas_de_combinada(comb: F.Combinada) -> list[dict]:
    out = []
    for c in comb.patas:
        tit, sub = c.etiqueta()
        out.append({"titulo": tit, "mercado": sub, "local": c.local, "visitante": c.visitante, "cuota": c.cuota,
                    "estimada": c.cuota_tipo == "estimada", "p": c.p_cal,
                    "hora": f"{c.inicio:%a %d/%m %H:%M}".replace("Sun", "Dom").replace("Mon", "Lun").replace("Sat", "Sáb")
                    .replace("Tue", "Mar").replace("Wed", "Mié").replace("Thu", "Jue").replace("Fri", "Vie")})
    return out


def textos_promos(comb: F.Combinada) -> list[str]:
    pr = comb.promos()
    out = []
    mb = pr["multi_bono"]
    if mb["aplica"]:
        out.append(f"Multi Bono +{mb['porcentaje']} % sobre las ganancias si acierta.")
    if pr["seguro"]["aplica"]:
        out.append(pr["seguro"]["motivo"])
    return out


def combinada(comb: F.Combinada, clave: str) -> None:
    izq, der = st.columns([1.05, 1])
    with izq:
        st.markdown(f"**{comb.titulo}**")
        st.html(E.boleta_html(comb.tipo, lineas_de_combinada(comb), comb.monto, comb.cuota_total, comb.p_total,
                              textos_promos(comb)))
    with der:
        k1, k2 = st.columns(2)
        k1.metric("Ganancias potenciales", f"S/{comb.ganancia_potencial:.2f}", f"cuota {comb.cuota_total:.2f}")
        k2.metric("Prob. de acertar todo", U.pct(comb.p_total), f"falla ≈ {(1 - comb.p_total) * 10:.0f} de 10",
                  delta_color="off")
        for n in comb.notas:
            st.info(n)
        st.button("➕ Agregar a mi boleta", key=f"add_{clave}", type="primary", width="stretch",
                  on_click=U.cb_agregar_candidatas, args=(comb.patas,))
        mb = comb.promos()["multi_bono"]
        if not mb["aplica"]:
            st.caption(f"🎁 {mb['motivo']}")
        for c in comb.patas:
            tit, sub = c.etiqueta()
            with st.expander(f"¿Por qué «{tit}» en {c.partido}?"):
                st.write(F.razon(c))
                st.caption(f"Modelo {U.pct(c.p_modelo)} · mercado {U.pct(c.p_mercado)} · bot {U.pct(c.p_bot)} → "
                           f"calibrado {U.pct(c.p_cal)} · cuota justa {1 / c.p_cal:.2f}")
                if c.cuota_tipo == "estimada":
                    st.caption(f"Cuota ≈{c.cuota:.2f} estimada (promedio de casas + margen típico). Copia la real de Betano.")
                else:
                    st.caption(f"Cuota {c.cuota:.2f} = promedio de casas de apuestas (referencia).")
                if c.evidencia:
                    st.caption("📊 " + c.evidencia)
                if c.p_pago_anticipado:
                    st.caption(f"⚡ Si Betano le activa **Pago Anticipado** (2 goles de ventaja), la probabilidad de cobrar "
                               f"sube a ≈{c.p_pago_anticipado:.0%}.")
        with st.expander("📋 Texto para copiar"):
            st.code(F.combinada_desde_texto_cuota(comb), language=None)


def simples(lista, titulo: str, clave: str) -> None:
    st.markdown(f"**{titulo}**")
    cols = st.columns(2)
    for i, c in enumerate(lista):
        tit, sub = c.etiqueta()
        with cols[i % 2]:
            extra = E.chip("cuota ≈ estimada", E.COL["suave"]) if c.cuota_tipo == "estimada" else ""
            st.html(E.tarjeta_seleccion(tit, sub, c.partido, f"{c.inicio:%d/%m %H:%M} · {U.nombre_liga(c.liga)}",
                                        c.p_cal, c.cuota, c.cuota_tipo == "estimada"))
            st.button("➕ Agregar", key=f"adds_{clave}_{i}", on_click=U.cb_agregar_candidatas, args=([c],))


def partido(liga: str, local: str, visitante: str, inicio, clave: str, ficha_completa: bool = False) -> None:
    ml = A.cargar_modelo(liga)
    if not ml or not (ml.ft.tiene(local) and ml.ft.tiene(visitante)):
        st.warning("No tengo modelo para este partido.")
        return
    w, _ = A.peso_modelo()
    mod = M.MotorPartido.desde_modelo(ml, local, visitante)
    ref = A.cuotas_proximo(liga, local, visitante)
    mer = M.motor_mercado(local, visitante, ref, ml) if ref else None
    sels = [M.Seleccion("1x2", "local"), M.Seleccion("1x2", "empate"), M.Seleccion("1x2", "visitante")]
    p = []
    for s in sels:
        pm = mod.prob([s])["conjunta"]
        pk = mer.prob([s])["conjunta"] if mer else None
        p.append(M.combinar(pm, pk, w))
    lam, mu = (mer.lam * (1 - w) + mod.lam * w, mer.mu * (1 - w) + mod.mu * w) if mer else (mod.lam, mod.mu)
    hora = f"{pd.Timestamp(inicio):%d/%m %H:%M} (Perú)" if inicio is not None else "fecha por confirmar"
    marc = " · ".join(f"{s} {q:.0%}" for s, q in (mer or mod).marcadores_probables(4))
    st.html(f'<div class="fb-card"><div class="fb-muted">{E.e(U.nombre_liga(liga))} · 🕒 {E.e(hora)}</div>'
            f'<div style="font-size:1.3rem;font-weight:800;margin:6px 0;line-height:1.7">{E.equipo(local, 28)}<br>{E.equipo(visitante, 28)}</div>'
            f'{E.barra_1x2(p[0], p[1], p[2], EQ.nombre(local), EQ.nombre(visitante))}'
            f'<div style="margin-top:6px"><a href="{EQ.enlace_liga(liga)}" target="_blank" style="color:{E.COL["naranja"]};font-weight:800;text-decoration:none">Ver la liga en Betano ↗</a></div>'
            f'<div class="fb-muted" style="margin-top:8px">⚽ Goles esperados: <b>{lam:.2f}</b> – <b>{mu:.2f}</b> · '
            f'Marcadores más probables: {E.e(marc)}</div></div>')
    for a in mod.avisos:
        st.caption("⚠️ " + a)
    # mejores mercados del partido
    filas = []
    for s in F.MERCADOS_FIJAS:
        pm = mod.prob([s])["conjunta"]
        pk = mer.prob([s])["conjunta"] if mer else None
        pb = M.combinar(pm, pk, w)
        pc = F.calibrar(s, pb)
        if pc and 0.55 <= pc <= 0.97:
            filas.append((pc, s))
    filas.sort(key=lambda x: -x[0])
    cols = st.columns(3)
    for i, (pc, s) in enumerate(filas[:6]):
        tit, sub = s.etiqueta(local, visitante)
        nom, color = E.nivel(pc)
        with cols[i % 3]:
            st.html(f'<div class="fb-card" style="display:flex;gap:10px;align-items:center">{E.anillo(pc, 50, 5)}'
                    f'<div><div style="font-weight:800">{E.e(tit)}</div><div class="fb-muted" style="font-size:.8rem">{E.e(sub)}</div>'
                    f'<div class="fb-muted" style="font-size:.8rem">cuota justa {1 / pc:.2f}</div></div></div>')
    if not ficha_completa:
        if st.button("📊 Ver análisis completo", key=f"ver_{clave}"):
            st.session_state["partido_sel"] = {"liga": liga, "local": local, "visitante": visitante, "inicio": inicio}
            U.ir("partidos")


def bet_builders(liga, local, visitante, lista, monto, clave) -> None:
    st.markdown(f"**🧩 Bet Builders sugeridos · {local} vs {visitante}**")
    for i, bb in enumerate(lista):
        patas = [s.etiqueta(local, visitante) for s in bb["selecciones"]]
        c1, c2 = st.columns([3, 1])
        with c1:
            st.html(E.boleta_html("Simple · Bet Builder", [{"titulo": "Bet Builder", "mercado": "", "local": local,
                                                             "visitante": visitante, "cuota": bb["cuota"], "estimada": True,
                                                             "p": bb["p"], "patas": patas}],
                                  monto, bb["cuota"], bb["p"], encabezado="Bet Builder sugerido · cuota estimada"))
        with c2:
            st.button("➕ Agregar", key=f"addbb_{clave}_{i}", on_click=U.cb_agregar_grupo,
                      args=(liga, local, visitante, bb["selecciones"], bb["cuota"]))
    st.caption("En Betano el precio del Bet Builder no es el producto de las patas: la cuota aquí es una estimación. "
               "Si una pata se anula, se anula todo el Bet Builder.")


def verificacion(res: dict, g, clave: str) -> None:
    l = res["lineas"][0]
    pf = l["p_final"]
    nom, color = E.nivel(pf)
    titulo = "Bet Builder" if g.bet_builder else l["patas"][0]["titulo"]
    cuota = f"{l['cuota']:.2f}" if l["cuota"] else "sin cuota"
    st.html(f'<div class="fb-card" style="display:flex;gap:14px;align-items:center">{E.anillo(pf, 70, 7)}'
            f'<div style="flex:1"><div style="font-weight:800;font-size:1.1rem">{E.e(titulo)} · {E.e(g.local)} vs {E.e(g.visitante)}</div>'
            f'<div class="fb-muted">{" + ".join(E.e(p["titulo"]) for p in l["patas"])} · cuota {cuota}</div>'
            f'<div style="margin-top:6px;font-weight:800">{E.e(l["veredicto"])}</div>'
            f'<div class="fb-muted">Cuota justa {l["cuota_justa"]:.2f} · falla ≈ {(1 - pf) * 10:.1f} de cada 10</div></div></div>'
            if pf else '<div class="fb-card">No pude calcular esa selección.</div>')
    for p in l["patas"]:
        if p.get("evidencia"):
            st.caption("📊 " + p["evidencia"])
    for a in l["avisos"]:
        st.caption("⚠️ " + a)
    st.button("➕ Agregar a mi boleta", key=f"addv_{clave}", on_click=U.cb_agregar_grupo,
              args=(g.liga, g.local, g.visitante, g.selecciones, g.cuota, g.fuente))


def regla(r: dict) -> None:
    st.html(f'<div class="fb-card"><div style="font-weight:800;font-size:1.05rem">📘 {E.e(r["titulo"])}</div>'
            f'<div style="margin-top:6px;line-height:1.55">{E.e(r["texto"])}</div>'
            f'<div class="fb-muted" style="margin-top:8px">Fuente oficial: <a href="{E.e(r["url"])}" target="_blank" '
            f'style="color:{E.COL["naranja"]}">centro de ayuda de Betano Perú</a></div></div>')


def historial_resumen() -> None:
    met = R.metricas()
    if met["boletas"].empty:
        st.info("Aún no registraste boletas. Cuando apuestes, regístralas en **🧾 Mi boleta** y aquí verás tu balance real.")
        return
    s = met.get("resumen")
    if s:
        c1, c2, c3 = st.columns(3)
        c1.metric("Apostado", f"S/{s['apostado']:.2f}")
        c2.metric("Neto", f"S/{s['neto']:+.2f}")
        c3.metric("ROI", f"{s['roi']:+.1%}" if s["roi"] is not None else "—")
    st.button("Ver historial completo", key="ir_hist", on_click=U.ir, args=("historial",))


def ayuda() -> None:
    st.markdown(
        "**Así me puedes hablar:**\n"
        "- 🎯 *«Dame las fijas de hoy»*, *«fijas de mañana»*, *«fijas del fin de semana»*\n"
        "- 🧮 *«Combinada de 4 con cuota 3 con 20 soles»*, *«quiero cuota 2 lo más seguro»*\n"
        "- 🛡️ Ajustes: *«más segura»*, *«más cuota»*, *«con 50»*, *«solo goles»*, *«de la Premier»*, *«con córners»*\n"
        "- 🔍 *«Cómo ves el Leeds vs United»*, *«bet builder del Arsenal»*\n"
        "- ✅ *«Revisa: Leeds o empate a 1.40»*, *«Leeds anota a 1.30»*\n"
        "- 📘 *«¿Qué es el Pago Anticipado?»*, *«¿cómo cuentan las tarjetas?»*, *«¿qué pasa si se suspende?»*\n"
        "- 💾 *«Agrégala a mi boleta»* para guardar la última combinada\n\n"
        "La guía completa está en **📘 Guía**.")


def render(bloques: list[dict], clave: str) -> None:
    for j, b in enumerate(bloques):
        k = f"{clave}_{j}"
        t = b["tipo"]
        if t == "texto":
            st.markdown(b["md"])
        elif t == "combinada":
            combinada(b["combinada"], k)
        elif t == "noticias":
            filas = "".join(
                f'<div style="margin:6px 0"><a href="{E.e(n.get("enlace") or "#")}" target="_blank" '
                f'style="color:{E.COL["texto"]};font-weight:700;text-decoration:none">📰 {E.e(n["titular"])}</a>'
                f'<div class="fb-muted" style="font-size:.8rem">{E.e(n.get("medio", ""))} · {E.e((n.get("fecha") or "")[:16])}</div></div>'
                for n in b["lista"])
            st.html(f'<div class="fb-card"><div class="fb-muted">Noticias de internet · «{E.e(b["consulta"])}»</div>'
                    f'{filas or "<div class=fb-muted>Sin noticias recientes.</div>"}</div>')
        elif t == "super_boleta":
            U.mostrar_super_boleta(b["lineas"], b["marcadas"], b["monto"], b["titulo"], key=f"bv_{k}")
        elif t == "simples":
            simples(b["lista"], b.get("titulo", "Más opciones"), k)
        elif t == "partido":
            partido(b["liga"], b["local"], b["visitante"], b["inicio"], k)
        elif t == "bet_builders":
            bet_builders(b["liga"], b["local"], b["visitante"], b["lista"], b["monto"], k)
        elif t == "verificacion":
            verificacion(b["resultado"], b["grupo"], k)
        elif t == "regla":
            regla(b["regla"])
        elif t == "historial":
            historial_resumen()
        elif t == "ayuda":
            ayuda()
        elif t == "sugerencias":
            st.caption("Prueba con: " + " · ".join(f"«{s}»" for s in b["lista"]))
