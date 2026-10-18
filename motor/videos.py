"""Aprender de videos de tipsters (reels, TikToks) que el usuario descarga y le pasa al bot.

1. Transcribe el audio en la PC (faster-whisper, gratis, sin internet tras la 1.ª descarga del modelo).
2. Arma una hoja de fotogramas para ver lo que muestra en pantalla.
3. Busca la fija ("mi opción…", "mi apuesta…") y la traduce a un mercado de Betano.
4. El bot la evalúa con su propio cálculo y se puede registrar como "solo seguimiento" a nombre del
   tipster: así, con el tiempo, se mide cuánto acierta de verdad cada tipster.

No inicia sesión en redes sociales ni descarga nada de ellas: trabaja con los archivos que le das.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from . import analisis as A
from . import asistente as AS
from . import config as C

DIR_VIDEOS = C.DIR_DATOS / "videos"
DIR_ENTRADA = C.RAIZ / "videos_tipsters"   # carpeta donde el usuario deja los videos
MODELO_WHISPER = "small"                    # buen equilibrio velocidad/precisión en español
VOCABULARIO = ("Fijas de fútbol para Betano. Mi opción: gana, empate, anota, ambos anotan, más de 1.5 goles, "
               "menos de 3.5, doble oportunidad, córners, tarjetas, Premier League, LaLiga, Champions.")
# errores típicos de la transcripción -> forma correcta
CORRECCIONES = {r"\ba nota\b": "anota", r"\ba notar\b": "anota", r"\bmas de uno y medio\b": "mas de 1.5",
                r"\bmas de dos y medio\b": "mas de 2.5", r"\bmenos de tres y medio\b": "menos de 3.5",
                r"\bambos a notan\b": "ambos anotan", r"\bambos equipos a notan\b": "ambos anotan"}
FRASES_FIJA = r"(?:mi opcion|mi apuesta|mi fija|mi pick|mi pronostico|mi jugada|yo voy con|me quedo con|voy por|la fija es|apuesta del dia)"

for _d in (DIR_VIDEOS, DIR_ENTRADA):
    _d.mkdir(parents=True, exist_ok=True)

_modelo = None


def _id(ruta: Path) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        h.update(f.read(2_000_000))
    return h.hexdigest()[:14]


def transcribir(ruta: Path) -> dict:
    global _modelo
    try:
        import truststore
        truststore.inject_into_ssl()   # la 1.ª vez descarga el modelo (Avast intercepta HTTPS)
    except Exception:
        pass
    from faster_whisper import WhisperModel
    import numpy as np
    if _modelo is None:
        _modelo = WhisperModel(MODELO_WHISPER, device="cpu", compute_type="int8")
    # El audio se extrae con FFmpeg (16 kHz mono): evita la incompatibilidad de faster-whisper con av 19.
    crudo = subprocess.run(["ffmpeg", "-v", "error", "-i", str(ruta), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
                           capture_output=True, check=True, timeout=600).stdout
    audio = np.frombuffer(crudo, np.int16).astype(np.float32) / 32768.0
    segmentos, _ = _modelo.transcribe(audio, language="es", vad_filter=True, beam_size=5,
                                      initial_prompt=VOCABULARIO)
    segs = [{"ini": round(s.start, 1), "fin": round(s.end, 1), "texto": s.text.strip()} for s in segmentos]
    return {"texto": " ".join(s["texto"] for s in segs), "segmentos": segs}


def hoja_fotogramas(ruta: Path, destino: Path) -> Path | None:
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(ruta), "-vf",
                        "fps=1/2,scale=240:-1,tile=6x3:padding=4", "-frames:v", "1", str(destino)],
                       check=True, timeout=120)
        return destino
    except Exception:
        return None


def detectar_fijas(texto: str) -> list[dict]:
    """Fijas mencionadas: equipos + mercado. Prioriza la frase tras «mi opción», «mi apuesta», etc."""
    t = AS.norm(texto)
    for mal, bien in CORRECCIONES.items():
        t = re.sub(mal, bien, t)
    equipos = AS.detectar_equipos(t)
    if not equipos:
        return []
    f = AS.partido_proximo(equipos)
    if f is not None:
        liga, local, visitante, inicio = f.liga, f.local, f.visitante, f.inicio
    elif len(equipos) >= 2:
        liga, local, visitante, inicio = equipos[0][1], equipos[0][0], equipos[1][0], None
    else:
        return []
    frases = [m.group(1) for m in re.finditer(FRASES_FIJA + r"\s*:?\s*(.{0,90})", t)]
    confianza = "alta" if frases else "baja"
    sels = []
    for fr in frases or [t]:
        s, _ = AS.leer_selecciones(fr, local, visitante)
        sels += [x for x in s if x not in sels]
        if s and frases:
            break
    if not sels:
        return []
    return [{"liga": liga, "local": local, "visitante": visitante, "inicio": inicio,
             "selecciones": sels, "frase": frases[0] if frases else None, "confianza": confianza}]


def procesar(ruta: Path, tipster: str = "", forzar: bool = False) -> dict:
    ruta = Path(ruta)
    vid = _id(ruta)
    carpeta = DIR_VIDEOS / vid
    carpeta.mkdir(parents=True, exist_ok=True)
    cache = carpeta / "resultado.json"
    if cache.exists() and not forzar:
        res = json.loads(cache.read_text(encoding="utf-8"))
    else:
        tr = transcribir(ruta)
        hoja = hoja_fotogramas(ruta, carpeta / "hoja.jpg")
        res = {"id": vid, "archivo": ruta.name, "tipster": tipster, "transcripcion": tr["texto"],
               "segmentos": tr["segmentos"], "hoja": str(hoja) if hoja else None}
        cache.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if tipster:
        res["tipster"] = tipster
        cache.write_text(json.dumps({k: v for k, v in res.items() if k != "fijas"}, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    return completar(res)


def completar(res: dict) -> dict:
    """Agrega a un resultado (transcripción) sus fijas detectadas y el análisis del bot."""
    res["fijas"] = detectar_fijas(res["transcripcion"])
    for fj in res["fijas"]:
        g = A.Grupo(fj["liga"], fj["local"], fj["visitante"], fj["selecciones"], None,
                    str(fj["inicio"].date()) if fj["inicio"] is not None else None, None,
                    f"tipster:{res['tipster'] or 'sin nombre'}")
        fj["grupo"] = g
        fj["analisis"] = A.analizar_grupo(g)
    return res


def pendientes() -> list[Path]:
    return sorted([p for p in DIR_ENTRADA.glob("*") if p.suffix.lower() in (".mp4", ".mov", ".m4v", ".webm", ".mkv")])
