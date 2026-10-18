"""Boleta en tiempo real (componente Streamlit v2): marcar/desmarcar líneas y patas, cambiar cuotas y monto
recalcula cuota total, ganancias, probabilidad y Multi Bono AL INSTANTE en el navegador (sin recargar).

Solo cuando el usuario pulsa un botón (agregar, registrar…) se envía el estado a Python.
"""
from __future__ import annotations

import hashlib
import json

import streamlit as st

HTML = """
<div class="bv"></div>
"""

CSS = """
.bv { font-family: Nunito, "Segoe UI", Roboto, sans-serif; color: #1d2433; }
.tk { max-width: 560px; background: #fff; border-radius: 16px; overflow: hidden; box-shadow: 0 8px 28px rgba(0,0,0,.35); }
.hd { background: linear-gradient(90deg,#FF7A1A,#E8590C); color: #fff; padding: 9px 16px; font-weight: 800; font-size: 13px;
      display: flex; justify-content: space-between; gap: 8px; }
.sub { display: flex; justify-content: space-between; padding: 10px 16px; border-bottom: 1px solid #e6e9ef; font-weight: 800; }
.ln { padding: 11px 14px 11px 12px; border-bottom: 1px solid #e6e9ef; display: flex; gap: 10px; transition: opacity .15s; }
.ln.off { opacity: .42; }
.ck { appearance: none; width: 22px; height: 22px; border: 2px solid #c5ccd8; border-radius: 6px; cursor: pointer;
      flex: 0 0 22px; margin-top: 1px; display: grid; place-content: center; background: #fff; }
.ck:checked { background: #FF7A1A; border-color: #FF7A1A; }
.ck:checked::after { content: "✓"; color: #fff; font-weight: 900; font-size: 14px; }
.ck.sm { width: 17px; height: 17px; flex-basis: 17px; border-radius: 5px; }
.ck.sm:checked::after { font-size: 11px; }
.bd { flex: 1; min-width: 0; }
.top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.tt { font-weight: 800; font-size: 15px; }
.tt.bb { color: #c2410c; }
.cu { display: flex; align-items: center; gap: 4px; background: #f1f3f7; border-radius: 8px; padding: 2px 6px; }
.cu span { font-size: 11px; color: #8a94a8; font-weight: 800; }
.cu input { width: 52px; border: 0; background: transparent; font-weight: 800; font-size: 15px; text-align: right; color: #1d2433; }
.cu input:focus { outline: 2px solid #FF7A1A; border-radius: 4px; }
.mk { color: #5b6b8c; font-size: 13px; }
.eq { font-size: 14px; margin-top: 4px; }
.eqr { display: flex; align-items: center; gap: 7px; margin: 2px 0; }
.esc { width: 20px; height: 20px; object-fit: contain; flex: 0 0 20px; }
.esc.ini { display: inline-grid; place-content: center; border-radius: 50%; background: #e6e9ef; font-size: 11px;
           font-weight: 800; color: #56607a; }
.bt { color: #E8590C; font-weight: 800; text-decoration: none; margin-left: auto; }
.meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 5px; font-size: 12px; color: #56607a; }
.pr { border-radius: 999px; padding: 1px 8px; font-weight: 800; border: 1px solid; font-size: 12px; }
.pt { display: flex; gap: 8px; align-items: flex-start; margin: 6px 0 0 2px; padding-left: 10px; border-left: 2px solid #f0a37a; }
.pt.off { opacity: .45; }
.pt b { font-size: 14px; }
.ft { padding: 12px 16px; background: #fafbfc; }
.mrow { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mrow label { font-weight: 800; }
.monto { display: flex; align-items: center; border: 2px solid #FF7A1A; border-radius: 10px; padding: 2px 8px; background: #fff; }
.monto span { font-weight: 800; color: #56607a; }
.monto input { width: 90px; border: 0; font-size: 18px; font-weight: 800; color: #1d2433; background: transparent; }
.monto input:focus { outline: none; }
.qb { border: 1px solid #d5dbe5; background: #fff; border-radius: 999px; padding: 4px 10px; font-weight: 800; cursor: pointer; color: #1d2433; }
.qb:hover { border-color: #FF7A1A; color: #E8590C; }
.tot { margin-top: 10px; line-height: 1.8; }
.row { display: flex; justify-content: space-between; }
.big { font-size: 22px; font-weight: 900; }
.note { font-size: 12.5px; margin-top: 4px; }
.ok { color: #0f766e; } .warn { color: #b45309; } .bad { color: #be123c; }
.acts { display: flex; gap: 8px; flex-wrap: wrap; padding: 12px 16px; border-top: 1px solid #e6e9ef; }
.btn { border: 0; border-radius: 10px; padding: 9px 12px; font-weight: 800; cursor: pointer; font-size: 13.5px; }
.btn.pri { background: linear-gradient(135deg,#FF8A3D,#E8590C); color: #fff; }
.btn.sec { background: #eef1f6; color: #1d2433; }
.av { font-size: 11.5px; color: #8a6d1d; margin-top: 4px; }
.vacio { padding: 18px; text-align: center; color: #56607a; }
"""

JS = """
const ESTADOS = new Map()

function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])) }
function color(p) { return p >= 0.85 ? "#16a34a" : p >= 0.75 ? "#65a30d" : p >= 0.65 ? "#d97706" : "#e11d48" }
function fmt(x) { return (Math.round(x * 100) / 100).toFixed(2) }

function estadoInicial(data) {
  const lineas = {}
  for (const l of data.lineas) {
    lineas[l.id] = { on: !!l.marcada, mask: (1 << l.patas.length) - 1, manual: null }
  }
  return { monto: Number(data.monto) || 10, lineas }
}

function calcular(data, st) {
  let cuota = 1, p = 1, n = 0, mbOk = true, seguroOk = true, minCuota = 99
  const det = {}
  for (const l of data.lineas) {
    const e = st.lineas[l.id]
    if (!e || !e.on || e.mask === 0) { det[l.id] = null; continue }
    const s = l.sub[String(e.mask)] || { p: l.p, cuota: l.cuota, estimada: l.estimada }
    const c = e.manual ?? s.cuota
    det[l.id] = { p: s.p, cuota: c, estimada: e.manual == null && s.estimada, patasOn: e.mask }
    cuota *= c; p *= s.p; n += 1
    const completa = e.mask === (1 << l.patas.length) - 1
    if (!(l.multibono_ok && completa && l.patas.length === 1)) mbOk = false
    if (!(l.seguro_ok && completa && l.patas.length === 1)) seguroOk = false
    minCuota = Math.min(minCuota, c)
  }
  const monto = Math.max(0, Number(st.monto) || 0)
  const gan = monto * cuota
  let mb = 0, mbTxt = ""
  if (n >= 3 && mbOk && minCuota >= 1.5) {
    mb = data.multibono[String(Math.min(n, 24))] ?? (n >= 25 ? 200 : 0)
    mbTxt = mb ? `🎁 Multi Bono +${mb} %: ≈ +S/${fmt((gan - monto) * mb / 100)} extra si acierta (verifícalo en el cupón)` : ""
  } else if (n >= 3) {
    mbTxt = "Sin Multi Bono: pide 3+ selecciones simples de mercados válidos a cuota ≥ 1.50 cada una."
  }
  const seguro = n >= 5 && n <= 20 && seguroOk && minCuota >= 1.65
  return { cuota: n ? cuota : 0, p: n ? p : 0, n, gan: n ? gan : 0, monto, det, mbTxt, mb, seguro }
}

function texto(data, st, r) {
  const t = [`${tipo(r.n)} · propuesta de FútBot (verifica cuotas en Betano)`, ""]
  for (const l of data.lineas) {
    const d = r.det[l.id]; if (!d) continue
    const patas = l.patas.filter((_, i) => d.patasOn >> i & 1)
    if (patas.length > 1) {
      t.push(`⚽ Bet Builder [${d.estimada ? "≈" : ""}${fmt(d.cuota)}] · ${l.local} vs ${l.visitante} · ${l.hora}`)
      for (const p of patas) t.push(`   • ${p.titulo} — ${p.mercado}`)
    } else {
      t.push(`⚽ ${patas[0].titulo} — ${patas[0].mercado} [${d.estimada ? "≈" : ""}${fmt(d.cuota)}]`)
      t.push(`   ${l.local} vs ${l.visitante} · ${l.hora}`)
    }
  }
  t.push("", `Cuota total: ${fmt(r.cuota)}`, `Apuesta: S/${fmt(r.monto)}`, `Ganancias potenciales: S/${fmt(r.gan)}`,
         `Probabilidad de acertar todo: ${Math.round(r.p * 100)}%`)
  return t.join("\\n")
}

function escudo(uri, nombre) {
  return uri ? `<img class="esc" src="${uri}" alt="">` : `<span class="esc ini">${esc(String(nombre || "?").charAt(0))}</span>`
}

function tipo(n) { return n === 1 ? "Simple" : n === 2 ? "Doble" : n === 3 ? "Triple" : `Combinada de ${n}` }

export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const raiz = parentElement.querySelector(".bv")
  if (!raiz || !data) return
  if (!ESTADOS.has(data.id)) ESTADOS.set(data.id, estadoInicial(data))
  const st = ESTADOS.get(data.id)

  function enviar(tipoAccion) {
    const r = calcular(data, st)
    const lineas = data.lineas.filter(l => r.det[l.id]).map(l => ({ id: l.id, mask: st.lineas[l.id].mask, cuota: r.det[l.id].cuota }))
    setTriggerValue("accion", { tipo: tipoAccion, slip: data.id, monto: r.monto, lineas, t: Date.now() })
  }

  function resumen() {
    const r = calcular(data, st)
    const q = s => raiz.querySelector(s)
    q("#n").textContent = r.n ? `${tipo(r.n)} · ${r.n} ${r.n > 1 ? "selecciones" : "selección"}` : "Sin selecciones"
    q("#ct").textContent = r.n ? fmt(r.cuota) : "—"
    q("#gan").textContent = `S/${fmt(r.gan)}`
    q("#neto").textContent = r.n ? `ganancia neta S/${fmt(r.gan - r.monto)}` : ""
    const pp = q("#pp"); pp.textContent = r.n ? `${Math.round(r.p * 100)}%` : "—"; pp.style.color = color(r.p)
    q("#falla").textContent = r.n ? `De cada 10 boletas así, ≈ ${Math.round((1 - r.p) * 10)} se caen.` : ""
    const mb = q("#mb"); mb.textContent = r.mbTxt; mb.className = "note " + (r.mb ? "ok" : "warn")
    q("#seg").textContent = r.seguro ? "🛟 Podría tener Seguro Betano: si falla solo una, te devuelven lo apostado." : ""
    q("#min").textContent = r.monto > 0 && r.monto < data.minimo ? `La apuesta mínima en Betano es S/${fmt(data.minimo)}.` : ""
    q("#sm").textContent = `S/${fmt(r.monto)}`
    for (const l of data.lineas) {
      // las líneas sin marcar también muestran su cuota y probabilidad (para decidir si sumarlas)
      const e = st.lineas[l.id]
      const s = l.sub[String(e.mask)] || { p: l.p, cuota: l.cuota, estimada: l.estimada }
      const d = r.det[l.id] || { p: s.p, cuota: e.manual ?? s.cuota, estimada: e.manual == null && s.estimada }
      const inp = raiz.querySelector(`input.cuota[data-id="${CSS.escape(l.id)}"]`)
      const pr = raiz.querySelector(`.pr[data-id="${CSS.escape(l.id)}"]`)
      const aprox = raiz.querySelector(`.aprox[data-id="${CSS.escape(l.id)}"]`)
      if (inp && inp.getRootNode().activeElement !== inp) inp.value = fmt(d.cuota)
      if (aprox) aprox.textContent = d.estimada ? "≈" : ""
      if (pr) { pr.textContent = `${Math.round(d.p * 100)}% prob.`; pr.style.color = color(d.p); pr.style.borderColor = color(d.p) }
    }
  }

  function render() {
    if (!data.lineas.length) { raiz.innerHTML = `<div class="tk"><div class="vacio">No hay selecciones que cumplan el nivel pedido.</div></div>`; return }
    let h = `<div class="tk"><div class="hd"><span>${esc(data.titulo || "Boleta sugerida")}</span><span>para copiar en Betano</span></div>
      <div class="sub"><span id="n"></span><span id="sm"></span></div>`
    for (const l of data.lineas) {
      const e = st.lineas[l.id]
      const activas = l.patas.filter((_, i) => e.mask >> i & 1)
      const bb = activas.length > 1
      const tit = bb ? "Bet Builder" : esc((activas[0] || l.patas[0]).titulo)
      h += `<div class="ln ${e.on && e.mask ? "" : "off"}">
        <input type="checkbox" class="ck lin" data-id="${esc(l.id)}" ${e.on ? "checked" : ""} title="Incluir en la boleta">
        <div class="bd"><div class="top"><span class="tt ${bb ? "bb" : ""}">⚽ ${tit}</span>
          <label class="cu"><span class="aprox" data-id="${esc(l.id)}"></span><input class="cuota" data-id="${esc(l.id)}" inputmode="decimal" title="Escribe aquí la cuota real de Betano"></label></div>`
      if (!bb) h += `<div class="mk">${esc((activas[0] || l.patas[0]).mercado)}</div>`
      h += `<div class="eq"><div class="eqr">${escudo(l.escudo_local, l.local)}${esc(l.local)}</div>
              <div class="eqr">${escudo(l.escudo_visitante, l.visitante)}${esc(l.visitante)}</div></div>`
      if (l.patas.length > 1) {
        l.patas.forEach((p, i) => {
          const on = e.mask >> i & 1
          h += `<div class="pt ${on ? "" : "off"}"><input type="checkbox" class="ck sm pat" data-id="${esc(l.id)}" data-i="${i}" ${on ? "checked" : ""}>
            <div><b>${esc(p.titulo)}</b> <span class="mk">${esc(p.mercado)} · ${Math.round(p.p * 100)}%</span></div></div>`
        })
      }
      h += `<div class="meta"><span class="pr" data-id="${esc(l.id)}"></span><span>🕒 ${esc(l.hora)}</span><span>${esc(l.liga_nombre)}</span>
            ${l.betano ? `<a class="bt" href="${esc(l.betano)}" target="_blank" rel="noopener">Ver en Betano ↗</a>` : ""}</div>`
      for (const a of (l.avisos || [])) h += `<div class="av">⚠️ ${esc(a)}</div>`
      h += `</div></div>`
    }
    h += `<div class="ft"><div class="mrow"><label>Monto</label><div class="monto"><span>S/</span><input id="monto" inputmode="decimal"></div>
        <button class="qb" data-add="5">+5</button><button class="qb" data-add="10">+10</button><button class="qb" data-add="20">+20</button>
        <button class="qb" data-add="50">+50</button><button class="qb" data-add="0">Borrar</button></div>
      <div class="tot"><div class="row"><span>Cuota total</span><b id="ct"></b></div>
        <div class="row"><span>Ganancias potenciales</span><span class="big" id="gan"></span></div>
        <div class="row mk"><span></span><span id="neto"></span></div>
        <div class="row"><span>Prob. de acertar todo</span><b id="pp"></b></div>
        <div class="note mk" id="falla"></div><div class="note" id="mb"></div><div class="note ok" id="seg"></div><div class="note bad" id="min"></div></div></div>
      <div class="acts"><button class="btn pri" data-act="agregar">➕ A mi boleta</button><button class="btn sec" data-act="registrar">✅ La aposté</button>
        <button class="btn sec" data-act="seguimiento">👁️ Solo seguimiento</button><button class="btn sec" data-act="copiar">📋 Copiar texto</button>
        <a class="btn sec" href="https://www.betano.pe/sport/futbol/" target="_blank" rel="noopener" style="text-decoration:none">🟠 Abrir Betano</a></div></div>`
    raiz.innerHTML = h
    const monto = raiz.querySelector("#monto"); monto.value = fmt(st.monto)
    monto.oninput = () => { st.monto = parseFloat(monto.value.replace(",", ".")) || 0; resumen() }
    raiz.querySelectorAll(".qb").forEach(b => b.onclick = () => {
      const add = Number(b.dataset.add); st.monto = add === 0 ? 0 : (Number(st.monto) || 0) + add
      monto.value = fmt(st.monto); resumen()
    })
    raiz.querySelectorAll("input.lin").forEach(c => c.onchange = () => { st.lineas[c.dataset.id].on = c.checked; render() })
    raiz.querySelectorAll("input.pat").forEach(c => c.onchange = () => {
      const e = st.lineas[c.dataset.id]; e.mask = e.mask ^ (1 << Number(c.dataset.i)); e.manual = null
      if (e.mask === 0) e.on = false; else e.on = true
      render()
    })
    raiz.querySelectorAll("input.cuota").forEach(inp => {
      inp.oninput = () => { const v = parseFloat(inp.value.replace(",", ".")); st.lineas[inp.dataset.id].manual = v > 1 ? v : null; resumen() }
      inp.onblur = () => resumen()
    })
    raiz.querySelectorAll(".btn").forEach(b => b.onclick = () => {
      if (b.dataset.act === "copiar") {
        const r = calcular(data, st)
        navigator.clipboard?.writeText(texto(data, st, r)).then(() => { b.textContent = "✅ Copiado" }, () => { b.textContent = "No se pudo copiar" })
        return
      }
      const original = b.textContent
      enviar(b.dataset.act)
      b.textContent = "✅ Listo"
      setTimeout(() => { b.textContent = original }, 1800)
    })
    resumen()
  }
  render()
}
"""

_COMPONENTE = st.components.v2.component("futbot_boleta_vivo", html=HTML, css=CSS, js=JS)


def id_boleta(datos: dict) -> str:
    base = json.dumps([datos.get("titulo"), [l["id"] for l in datos.get("lineas", [])]], ensure_ascii=False)
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def mostrar(datos: dict, key: str, on_accion=None):
    """Dibuja la boleta. on_accion() se llama cuando el usuario pulsa un botón; el detalle está en
    st.session_state[key].accion = {"tipo", "slip", "monto", "lineas": [{"id", "mask", "cuota"}]}."""
    datos = {**datos, "id": datos.get("id") or id_boleta(datos)}
    return _COMPONENTE(key=key, data=datos, on_accion_change=on_accion or (lambda: None))
