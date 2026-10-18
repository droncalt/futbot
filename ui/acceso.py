"""Acceso desde el celular: direcciones de la PC, códigos QR y PIN para conexiones que no son de la misma PC."""
from __future__ import annotations

import hashlib
import io
import json
import os
import socket

import streamlit as st

from motor import config as C

RUTA_PIN = C.DIR_DATOS / "acceso.json"
PUERTO = 8501


def es_local() -> bool:
    ip = getattr(st.context, "ip_address", None)
    return ip in (None, "", "127.0.0.1", "::1", "localhost")


def _hash(pin: str, sal: str) -> str:
    return hashlib.sha256((sal + pin).encode()).hexdigest()


def hay_pin() -> bool:
    return RUTA_PIN.exists()


def guardar_pin(pin: str) -> None:
    sal = os.urandom(8).hex()
    RUTA_PIN.write_text(json.dumps({"sal": sal, "hash": _hash(pin, sal)}), encoding="utf-8")


def pin_correcto(pin: str) -> bool:
    try:
        d = json.loads(RUTA_PIN.read_text(encoding="utf-8"))
        return _hash(pin, d["sal"]) == d["hash"]
    except Exception:
        return False


def puerta() -> bool:
    """True si puede entrar. Desde la misma PC no pide nada; desde otro equipo pide el PIN."""
    if es_local() or st.session_state.get("_pin_ok"):
        return True
    st.html('<div class="fb-hero"><h1>⚽ FútBot</h1><p>Acceso desde otro dispositivo</p></div>')
    if not hay_pin():
        st.warning("Por seguridad, primero crea un PIN en la PC: 📘 Guía → «📱 Celular».")
        return False
    pin = st.text_input("PIN", type="password", max_chars=12)
    if st.button("Entrar", type="primary"):
        if pin_correcto(pin):
            st.session_state["_pin_ok"] = True
            st.rerun()
        else:
            st.error("PIN incorrecto.")
    return False


def direcciones() -> dict:
    """{'wifi': [ip,...], 'tailscale': [ip,...]} de esta PC."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    principal = None
    try:  # IP de la interfaz que sale a la red real (no envía datos)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        principal = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    privadas = sorted(ip for ip in ips if ip.startswith(("192.168.", "10.")) or ip.startswith("172.") and 16 <= int(ip.split(".")[1]) <= 31)
    # la de la WiFi/red real primero; se ocultan adaptadores virtuales (VirtualBox, VPN) si se conoce la principal
    wifi = [principal] if principal in privadas or (principal and principal.startswith("192.168.")) else privadas
    tail = sorted(ip for ip in ips if ip.startswith("100.") and 64 <= int(ip.split(".")[1]) <= 127)
    return {"wifi": wifi, "tailscale": tail}


def qr_png(texto: str) -> bytes:
    import qrcode
    img = qrcode.make(texto, box_size=7, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def panel_celular() -> None:
    st.markdown("#### 📱 App Android independiente (recomendado)")
    st.markdown("Instala **`FutBot.apk`** (está en la carpeta del bot) y conecta la nube gratis de GitHub: funciona **sin la PC**, "
                "con datos que se calculan solos 2 veces al día. Pasos completos en **`APP_CELULAR.md`**.")
    st.markdown("#### 🖥️ O abrir esta app de la PC desde el celular")
    st.markdown(
        "FútBot corre en tu PC (ahí están los datos, los modelos y la IA). El celular lo abre por el navegador y lo puedes "
        "**instalar como app** en la pantalla de inicio. La PC debe estar encendida con FútBot abierto (`iniciar_bot.bat`).")
    if not es_local():
        st.info("Estas opciones se configuran desde la PC.")
        return
    st.markdown("**1️⃣ Crea tu PIN** (te lo pedirá el celular; en la PC no hace falta)")
    c1, c2 = st.columns([2, 1])
    nuevo = c1.text_input("Nuevo PIN (4 a 12 caracteres)", type="password", key="pin_nuevo")
    if c2.button("Guardar PIN"):
        if 4 <= len(nuevo) <= 12:
            guardar_pin(nuevo)
            st.success("PIN guardado.")
        else:
            st.error("Usa entre 4 y 12 caracteres.")
    if hay_pin():
        st.caption("✅ Ya tienes un PIN configurado (puedes cambiarlo arriba).")
    d = direcciones()
    st.markdown("**2️⃣ En la misma WiFi de tu casa:** escanea el QR con la cámara del celular")
    if d["wifi"]:
        cols = st.columns(min(len(d["wifi"]), 3))
        for col, ip in zip(cols, d["wifi"]):
            url = f"http://{ip}:{PUERTO}"
            col.image(qr_png(url), caption=url, width=190)
        st.caption("La primera vez, Windows te preguntará si permites que Python use la red: elige **Redes privadas → Permitir**. "
                   "Si el celular no carga, revisa que esté en la misma WiFi que la PC.")
    else:
        st.caption("No detecté una red WiFi/local en esta PC.")
    st.markdown("**3️⃣ Desde cualquier lugar (datos móviles, fuera de casa):** usa **Tailscale** (gratis y privado)")
    st.markdown(
        "1. Instala **Tailscale** en la PC (tailscale.com/download) y en el celular (Play Store / App Store).\n"
        "2. Inicia sesión **con la misma cuenta** en los dos (tú mismo; FútBot no toca tus cuentas).\n"
        "3. Vuelve a esta página: aparecerá aquí un QR con la dirección privada de tu PC.\n"
        "Solo tus dispositivos pueden entrar; no queda expuesto a internet.")
    if d["tailscale"]:
        cols = st.columns(min(len(d["tailscale"]), 3))
        for col, ip in zip(cols, d["tailscale"]):
            url = f"http://{ip}:{PUERTO}"
            col.image(qr_png(url), caption=f"Tailscale: {url}", width=190)
    st.markdown("**4️⃣ Instalarlo como app**")
    st.markdown(
        "- **Android (Chrome):** abre la dirección → menú ⋮ → **Agregar a la pantalla principal** / **Instalar app**.\n"
        "- **iPhone (Safari):** abre la dirección → botón Compartir → **Agregar a inicio**.\n"
        "Te queda el ícono de FútBot como una app más. En el celular el menú está en el botón **»** de arriba.")
