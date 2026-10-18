"""Estado compartido de la interfaz: boleta, chat, monto, actualización automática y barra lateral."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from motor import analisis as A
from motor import asistente as AS
from motor import config as C
from motor import datos, modelo
from motor import mercados as M
from motor import registro as R
from ui import estilos as E

PAGINAS: dict = {}          # nombre -> st.Page (lo llena app.py para poder saltar entre páginas)
FUENTES = ["Bot", "Propia", "Telegram", "Tipster"]
HORAS_AUTO = 6              # cada cuántas horas se actualizan los datos solos al abrir la app


def iniciar() -> None:
    ss = st.session_state
    ss.setdefault("boleta", [])          # lista de Grupo.to_dict()
    ss.setdefault("chat", [])            # [{"rol": "user"|"bot", "texto": str, "bloques": list}]
    ss.setdefault("ctx", AS.Contexto())
    ss.setdefault("monto", 10.0)


def nombre_liga(c: str) -> str:
    return C.LIGAS.get(c, "Otra competición (Champions, selecciones…)")


def pct(p) -> str:
    return "—" if p is None or (isinstance(p, float) and pd.isna(p)) else f"{p:.0%}"


def ir(pagina: str) -> None:
    if pagina in PAGINAS:
        st.switch_page(PAGINAS[pagina])


# --- boleta --------------------------------------------------------------------------

def agregar(liga, local, visitante, sel: M.Seleccion, fuente: str, cuotas_ref=None, fecha=None,
            cuota: float | None = None) -> str:
    """Agrega una selección; si ya hay una línea del mismo partido, la convierte en Bet Builder."""
    for g in st.session_state.boleta:
        if g["local"] == local and g["visitante"] == visitante:
            if sel.to_dict() in g["selecciones"]:
                return "Esa selección ya estaba en tu boleta."
            g["selecciones"].append(sel.to_dict())
            g["cuota"] = None  # el precio del Bet Builder cambia: hay que copiarlo de Betano
            return f"➕ Sumada al Bet Builder de {local} vs {visitante}. Copia la nueva cuota de Betano."
    st.session_state.boleta.append(A.Grupo(liga, local, visitante, [sel], cuota, fecha, cuotas_ref,
                                           fuente.lower()).to_dict())
    return f"➕ Agregada: {local} vs {visitante}."


def agregar_candidatas(cands, fuente: str = "bot") -> str:
    msgs = [agregar(c.liga, c.local, c.visitante, c.seleccion, fuente, None, str(c.inicio.date()), c.cuota)
            for c in cands]
    return msgs[-1] if len(msgs) == 1 else f"➕ {len(msgs)} selecciones agregadas a tu boleta."


def cb_agregar_candidatas(cands, fuente="bot"):
    st.toast(agregar_candidatas(cands, fuente))


def cb_agregar_grupo(liga, local, visitante, sels, cuota, fuente="bot"):
    for s in sels:
        agregar(liga, local, visitante, s, fuente)
    for g in st.session_state.boleta:
        if g["local"] == local and g["visitante"] == visitante and cuota:
            g["cuota"] = cuota
    st.toast(f"➕ Bet Builder de {local} vs {visitante} agregado (cuota estimada: verifícala en Betano).")


def agregar_grupo(g: A.Grupo) -> None:
    """Agrega una línea completa (simple o Bet Builder) con su cuota; reemplaza la del mismo partido."""
    ss = st.session_state
    ss.boleta = [x for x in ss.boleta if not (x["local"] == g.local and x["visitante"] == g.visitante)]
    ss.boleta.append(g.to_dict())


def mostrar_super_boleta(lineas, marcadas: list[int], monto: float, titulo: str, key: str, extras: int = 8) -> None:
    """Boleta en tiempo real con las líneas del combinador (marcadas por defecto + más opciones)."""
    from motor import combinador as CB
    from ui import boleta_vivo as BV
    datos_bv = CB.a_boleta_vivo(lineas, marcadas, monto, titulo, extras)
    datos_bv["id"] = BV.id_boleta(datos_bv)
    st.session_state.setdefault("_slips", {})[datos_bv["id"]] = {l.id: l for l in lineas}
    BV.mostrar(datos_bv, key, on_accion=lambda: _accion_boleta(key))


def _accion_boleta(key: str) -> None:
    acc = getattr(st.session_state.get(key), "accion", None)
    if not acc:
        return
    reg = st.session_state.get("_slips", {}).get(acc.get("slip"), {})
    grupos = []
    for x in acc.get("lineas", []):
        l = reg.get(x["id"])
        if l is not None:
            grupos.append(l.grupo(int(x["mask"]), float(x["cuota"])))
    if not grupos:
        st.toast("No hay selecciones marcadas.")
        return
    tipo = acc.get("tipo")
    if tipo == "agregar":
        for g in grupos:
            agregar_grupo(g)
        st.toast(f"➕ {len(grupos)} línea(s) en 🧾 Mi boleta.")
    elif tipo in ("registrar", "seguimiento"):
        res = A.analizar_boleta(grupos, float(acc.get("monto") or 0))
        bid = R.registrar_boleta(res, "bot", "súper boleta", solo_seguimiento=(tipo == "seguimiento"))
        st.toast(f"✅ Boleta #{bid} {'registrada' if tipo == 'registrar' else 'en seguimiento'}. Se liquidará sola.")


def elegir_fuente(clave: str, defecto: str = "Bot") -> str:
    c1, c2 = st.columns([3, 2])
    f = c1.radio("¿De dónde viene?", FUENTES, index=FUENTES.index(defecto), horizontal=True, key=f"fuente_{clave}")
    if f == "Tipster":
        nombre = c2.text_input("Nombre del tipster", placeholder="ej. lasfijas.latam", key=f"tip_{clave}").strip()
        return f"tipster:{nombre or 'sin nombre'}"
    return f.lower()


# --- datos -----------------------------------------------------------------------------

def actualizar_todo(progreso=None) -> int:
    datos.actualizar(progreso=(lambda p, m: progreso(p * 0.85, m)) if progreso else None)
    df = datos.cargar_partidos()
    modelo.ajustar_todas(df, progreso=(lambda p, m: progreso(0.85 + 0.1 * p, m)) if progreso else None)
    try:  # tiros al arco de jugadores: solo los partidos nuevos (también liquida esas patas)
        from motor import jugadores as J
        J.actualizar(progreso=(lambda m: progreso(0.96, m)) if progreso else None)
    except Exception:  # sin internet o cambios en la fuente: se sigue con lo guardado
        pass
    n = R.liquidar_automatico(df)
    st.cache_data.clear()
    if progreso:
        progreso(1.0, "Listo")
    return n


def datos_viejos() -> bool:
    ult = datos.ultima_descarga()
    return ult is None or (pd.Timestamp.now() - pd.Timestamp(ult)) > pd.Timedelta(hours=HORAS_AUTO)


_ACTUALIZACION = {"corriendo": False, "mensaje": "", "fin": None}


def _actualizar_fondo() -> None:
    """Hilo en segundo plano: no usa Streamlit (la app sigue funcionando con los datos guardados)."""
    try:
        def prog(p, m):
            _ACTUALIZACION["mensaje"] = m
        datos.actualizar(progreso=lambda p, m: prog(p, m))
        df = datos.cargar_partidos()
        modelo.ajustar_todas(df)
        try:
            from motor import jugadores as J
            J.actualizar()
        except Exception:
            pass
        n = R.liquidar_automatico(df)
        _ACTUALIZACION["mensaje"] = f"✅ Datos al día · {n} línea(s) de tu historial liquidadas"
    except Exception as ex:  # sin internet: se sigue con lo guardado
        _ACTUALIZACION["mensaje"] = f"⚠️ No se pudo actualizar ({type(ex).__name__}); uso los datos guardados."
    finally:
        _ACTUALIZACION["corriendo"] = False
        _ACTUALIZACION["fin"] = pd.Timestamp.now()


def auto_actualizar() -> None:
    """Al abrir la app baja resultados y cuotas nuevas si tienen más de 6 h, EN SEGUNDO PLANO (no bloquea)."""
    import threading
    if _ACTUALIZACION["corriendo"]:
        st.caption(f"🔄 Actualizando datos en segundo plano… {_ACTUALIZACION['mensaje']}")
        return
    if _ACTUALIZACION["fin"] is not None and not st.session_state.get("_aviso_act"):
        st.session_state["_aviso_act"] = True
        st.toast(_ACTUALIZACION["mensaje"])
    if st.session_state.get("_auto_hecho"):
        return
    st.session_state["_auto_hecho"] = True
    if datos_viejos():
        _ACTUALIZACION.update(corriendo=True, mensaje="iniciando…", fin=None)
        threading.Thread(target=_actualizar_fondo, daemon=True).start()
        st.toast("🔄 Actualizando resultados y cuotas en segundo plano; puedes seguir usando la app.")


def firma_cache() -> tuple:
    mods = tuple(sorted(p.name for p in C.DIR_MODELOS.glob("*/*.json")))
    return datos._firma(), mods


@st.cache_data(show_spinner="Calculando probabilidades de los próximos partidos…")
def tabla_proximos(_firma) -> pd.DataFrame:
    return A.tabla_proximos()


# --- barra lateral ---------------------------------------------------------------------

def barra_lateral() -> None:
    ss = st.session_state
    with st.sidebar:
        st.html('<div style="font-size:1.5rem;font-weight:800">⚽ FútBot</div>'
                '<div class="fb-muted">Tu analista de fútbol para Betano</div>')
        ss.monto = st.number_input("💰 Monto por defecto (S/)", min_value=0.5, step=5.0, value=float(ss.monto),
                                   help="Lo que usa el chat y las fijas si no dices otro monto. Mínimo de Betano: S/0.50.")
        nb = len(ss.boleta)
        st.html(f'<div class="fb-card">🧾 <b>Mi boleta:</b> {nb} línea(s)</div>')
        if nb and st.button("Ver mi boleta", width="stretch"):
            ir("boleta")
        st.divider()
        ult = datos.ultima_descarga()
        st.caption(f"📡 Datos: {ult.replace('T', ' ')[:16] if ult else 'sin descargar'} · se actualizan solos cada {HORAS_AUTO} h")
        w, origen = A.peso_modelo()
        st.caption(f"📐 Mezcla: {w:.0%} modelo propio + {1 - w:.0%} mercado ({origen}).")
        est = ss.get("_ia_est")
        if est:
            st.caption("🧠 IA local: " + ("activa · " + est["modelo"] if est["servidor"] and est["instalado"]
                                         else "no activa (📘 Guía → IA local)"))
        if st.button("🔄 Actualizar ahora", width="stretch"):
            barra = st.progress(0.0, "Iniciando…")
            n = actualizar_todo(lambda p, m: barra.progress(min(p, 1.0), m))
            st.success(f"Datos al día. Líneas liquidadas: {n}.")
        st.divider()
        st.caption("Probabilidades, no certezas: ninguna apuesta es segura. Juega con montos que puedas perder. "
                   "Mayores de 18.")
