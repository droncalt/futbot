"""Estilos y componentes visuales (HTML) de la app.

Paleta oscura y suave para no cansar la vista: fondo azul petróleo, texto gris claro (no blanco puro),
acento naranja y colores de probabilidad: verde (muy alta) → lima → ámbar → rosa (riesgo).
"""
from __future__ import annotations

import html

import streamlit as st

COL = {
    "fondo": "#0F1720", "panel": "#17212C", "tarjeta": "#1C2836", "borde": "#2A3A4D",
    "texto": "#E7EDF3", "suave": "#9DB0C4", "naranja": "#FF8A3D", "naranja_osc": "#E8590C",
    "verde": "#34D399", "lima": "#A3E635", "ambar": "#FBBF24", "rosa": "#FB7185", "azul": "#60A5FA",
}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input, textarea {{
  font-family: 'Nunito', 'Segoe UI', system-ui, sans-serif !important;
}}
.stApp {{ background: radial-gradient(1200px 600px at 10% -10%, #1A2B3D 0%, {COL['fondo']} 55%) fixed; }}
.block-container {{ padding-top: 4.2rem; max-width: 1180px; }}
.stDeployButton, [data-testid="stToolbarActionButton"] {{ display: none !important; }}
h1, h2, h3 {{ letter-spacing: -0.01em; }}
div[data-testid="stMetricValue"] {{ font-weight: 800; }}
.stButton > button, .stDownloadButton > button {{ border-radius: 12px; font-weight: 700; }}
.stButton > button[kind="primary"] {{ background: linear-gradient(135deg, {COL['naranja']}, {COL['naranja_osc']}); border: 0; }}
div[data-testid="stChatMessage"] {{ background: {COL['panel']}; border: 1px solid {COL['borde']}; border-radius: 16px; padding: 10px 14px; }}
div[data-testid="stChatInput"] textarea {{ font-size: 1.02rem; }}
div[data-testid="stExpander"] details {{ border-radius: 12px; border-color: {COL['borde']}; }}
.fb-hero {{ background: linear-gradient(135deg, #1E3247 0%, #1A2533 60%, #2B2219 100%); border: 1px solid {COL['borde']};
  border-radius: 20px; padding: 26px 28px; margin-bottom: 14px; }}
.fb-hero h1 {{ margin: 0 0 6px 0; font-size: 2.0rem; color: {COL['texto']}; }}
.fb-hero p {{ color: {COL['suave']}; margin: 0; font-size: 1.05rem; }}
.fb-card {{ background: {COL['tarjeta']}; border: 1px solid {COL['borde']}; border-radius: 16px; padding: 14px 16px; margin-bottom: 10px; }}
.fb-muted {{ color: {COL['suave']}; font-size: 0.92rem; }}
.fb-chip {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 700; margin: 2px 4px 2px 0; }}
.fb-feature {{ background: {COL['tarjeta']}; border: 1px solid {COL['borde']}; border-radius: 16px; padding: 16px; height: 100%; }}
.fb-feature b {{ font-size: 1.05rem; }}
.fb-step {{ display: flex; gap: 14px; align-items: flex-start; background: {COL['tarjeta']}; border: 1px solid {COL['borde']};
  border-radius: 16px; padding: 14px 16px; margin-bottom: 10px; }}
.fb-step .num {{ flex: 0 0 34px; height: 34px; border-radius: 50%; background: {COL['naranja']}; color: #1b1b1b;
  font-weight: 800; display: flex; align-items: center; justify-content: center; }}
@media (max-width: 640px) {{ .block-container {{ padding-left: 0.8rem; padding-right: 0.8rem; }} .fb-hero h1 {{ font-size: 1.5rem; }} }}
</style>
"""


def inyectar() -> None:
    st.html(CSS)


def e(t) -> str:
    return html.escape(str(t))


def nivel(p: float | None) -> tuple[str, str]:
    if p is None:
        return "Sin datos", COL["suave"]
    if p >= 0.85:
        return "Muy alta", COL["verde"]
    if p >= 0.75:
        return "Alta", COL["lima"]
    if p >= 0.65:
        return "Media", COL["ambar"]
    return "Riesgo", COL["rosa"]


def anillo(p: float | None, tam: int = 58, grosor: int = 6) -> str:
    """Anillo de probabilidad en SVG."""
    _, color = nivel(p)
    r = (tam - grosor) / 2
    circ = 2 * 3.14159 * r
    v = 0 if p is None else max(0.0, min(1.0, p))
    txt = "—" if p is None else f"{p * 100:.0f}%"
    return (f'<svg width="{tam}" height="{tam}" viewBox="0 0 {tam} {tam}" style="flex:0 0 {tam}px">'
            f'<circle cx="{tam/2}" cy="{tam/2}" r="{r}" stroke="#2A3A4D" stroke-width="{grosor}" fill="none"/>'
            f'<circle cx="{tam/2}" cy="{tam/2}" r="{r}" stroke="{color}" stroke-width="{grosor}" fill="none" '
            f'stroke-linecap="round" stroke-dasharray="{circ * v:.1f} {circ:.1f}" transform="rotate(-90 {tam/2} {tam/2})"/>'
            f'<text x="50%" y="54%" text-anchor="middle" dominant-baseline="middle" fill="{COL["texto"]}" '
            f'font-family="Nunito,Segoe UI,sans-serif" font-weight="800" font-size="{tam * 0.26:.0f}">{txt}</text></svg>')


def equipo(eq: str, tam: int = 22) -> str:
    """Escudo + nombre completo del equipo (o inicial si aún no hay escudo)."""
    from motor import equipos as EQ
    uri = EQ.escudo_uri(eq)
    img = (f'<img src="{uri}" style="width:{tam}px;height:{tam}px;object-fit:contain;vertical-align:middle;margin-right:6px">'
           if uri else f'<span style="display:inline-grid;place-content:center;width:{tam}px;height:{tam}px;border-radius:50%;'
                       f'background:#2A3A4D;font-size:{tam * 0.5:.0f}px;font-weight:800;margin-right:6px;vertical-align:middle">'
                       f'{e(EQ.nombre(eq)[:1])}</span>')
    return img + e(EQ.nombre(eq))


def chip(texto: str, color: str = COL["azul"], fondo: str | None = None) -> str:
    fondo = fondo or color + "22"
    return f'<span class="fb-chip" style="color:{color};background:{fondo};border:1px solid {color}55">{e(texto)}</span>'


def barra_1x2(p1, px, p2, local, visitante) -> str:
    a, b, c = (max(0.0, x or 0) for x in (p1, px, p2))
    s = a + b + c or 1
    a, b, c = a / s * 100, b / s * 100, c / s * 100
    return (f'<div style="display:flex;justify-content:space-between;font-size:.8rem;color:{COL["suave"]};margin-top:6px">'
            f'<span>{e(local)} {a:.0f}%</span><span>Empate {b:.0f}%</span><span>{e(visitante)} {c:.0f}%</span></div>'
            f'<div style="display:flex;height:8px;border-radius:6px;overflow:hidden;margin-top:3px">'
            f'<div style="width:{a}%;background:{COL["verde"]}"></div><div style="width:{b}%;background:#64748B"></div>'
            f'<div style="width:{c}%;background:{COL["azul"]}"></div></div>')


def tarjeta_seleccion(titulo, mercado, partido, info, p, cuota=None, cuota_estimada=False, extra="") -> str:
    """Tarjeta compacta de una selección con su anillo de probabilidad."""
    nom, color = nivel(p)
    cuota_html = ""
    if cuota:
        cuota_html = (f'<div style="text-align:right"><div class="fb-muted" style="font-size:.75rem">cuota{" ≈" if cuota_estimada else ""}</div>'
                      f'<div style="font-weight:800;font-size:1.15rem">{cuota:.2f}</div></div>')
    return (f'<div class="fb-card" style="display:flex;gap:12px;align-items:center">{anillo(p)}'
            f'<div style="flex:1;min-width:0"><div style="font-weight:800;font-size:1.02rem">{e(titulo)}</div>'
            f'<div class="fb-muted">{e(mercado)}</div><div style="font-size:.9rem;margin-top:2px">{e(partido)}</div>'
            f'<div class="fb-muted" style="font-size:.8rem">{e(info)} {chip(nom, color)}{extra}</div></div>{cuota_html}</div>')


def boleta_html(tipo: str, lineas: list[dict], monto: float, cuota_total: float | None, p_total: float | None,
                promos: list[str] | None = None, encabezado: str = "Boleta sugerida · para copiar en Betano") -> str:
    """Boleta clara con la estructura de Betano (selección, mercado, equipos, cuota, apuesta, ganancias).

    lineas: {titulo, mercado, local, visitante, cuota, estimada, p, patas: [(titulo, mercado)], hora}
    """
    from motor import equipos as EQ

    def eq_html(eq):
        uri = EQ.escudo_uri(eq)
        img = f'<img src="{uri}" style="width:18px;height:18px;object-fit:contain;vertical-align:middle;margin-right:6px">' if uri else ""
        return img + e(EQ.nombre(eq))
    filas = []
    for l in lineas:
        bb = bool(l.get("patas"))
        tit = "Bet Builder" if bb else l["titulo"]
        cuota = f"{'≈' if l.get('estimada') else ''}{l['cuota']:.2f}" if l.get("cuota") else "—"
        p = l.get("p")
        _, color = nivel(p)
        prob = (f'<span style="background:{color}22;color:#1d2433;border:1px solid {color};border-radius:999px;'
                f'padding:1px 8px;font-size:12px;font-weight:700">{p:.0%} prob.</span>') if p is not None else ""
        bloque = [f'<div style="padding:12px 16px;border-bottom:1px solid #e6e9ef">'
                  f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
                  f'<span style="font-weight:800;color:{"#c2410c" if bb else "#1d2433"}">⚽ {e(tit)}</span>'
                  f'<span style="background:#f1f3f7;border-radius:8px;padding:3px 10px;font-weight:800;color:#1d2433">{cuota}</span></div>']
        if not bb:
            bloque.append(f'<div style="color:#5b6b8c;font-size:14px;margin:2px 0 0 24px">{e(l["mercado"])}</div>')
        bloque.append(f'<div style="margin:4px 0 0 24px;font-size:15px;color:#1d2433;line-height:1.7">'
                      f'{eq_html(l["local"])}<br>{eq_html(l["visitante"])}</div>')
        for pt, pm in l.get("patas") or []:
            bloque.append(f'<div style="margin:6px 0 0 24px;padding-left:12px;border-left:2px solid #f0a37a;color:#1d2433">'
                          f'<b>{e(pt)}</b><br><span style="color:#5b6b8c;font-size:14px">{e(pm)}</span></div>')
        pie = f'<div style="margin:6px 0 0 24px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">{prob}'
        if l.get("hora"):
            pie += f'<span style="color:#56607a;font-size:12px">🕒 {e(l["hora"])}</span>'
        bloque.append(pie + "</div></div>")
        filas.append("".join(bloque))
    promos_html = "".join(f'<div style="color:#0f766e;font-size:13px;margin-top:4px">🎁 {e(x)}</div>' for x in (promos or []))
    gan = monto * cuota_total if (monto and cuota_total) else None
    pie = (f'<div style="padding:12px 16px;line-height:1.75;color:#1d2433">'
           f'<div style="display:flex;justify-content:space-between"><span>Apuesta</span><b>S/{monto:.2f}</b></div>')
    if cuota_total:
        pie += f'<div style="display:flex;justify-content:space-between"><span>Cuota total</span><b>{cuota_total:.2f}</b></div>'
    if gan:
        pie += (f'<div style="display:flex;justify-content:space-between;font-size:19px"><span>Ganancias potenciales</span>'
                f'<b>S/{gan:.2f}</b></div>')
    if p_total is not None:
        _, color = nivel(p_total)
        pie += (f'<div style="display:flex;justify-content:space-between;color:#56607a"><span>Prob. de acertar todo</span>'
                f'<b style="color:{color if p_total >= 0.65 else "#be123c"}">{p_total:.0%}</b></div>')
    pie += promos_html + "</div>"
    return ('<div style="max-width:460px;font-family:Nunito,Segoe UI,Roboto,sans-serif;background:#fff;border-radius:16px;'
            'overflow:hidden;box-shadow:0 8px 28px rgba(0,0,0,.35)">'
            f'<div style="background:linear-gradient(90deg,#FF7A1A,#E8590C);color:#fff;padding:8px 16px;font-weight:800;'
            f'font-size:13px;letter-spacing:.02em">{e(encabezado)}</div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #e6e9ef;color:#1d2433">'
            f'<b>{e(tipo)}</b><span>S/{monto:.2f}</span></div>' + "".join(filas) + pie + "</div>")


def hero(titulo: str, texto: str) -> None:
    st.html(f'<div class="fb-hero"><h1>{titulo}</h1><p>{texto}</p></div>')
