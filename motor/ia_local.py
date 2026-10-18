"""IA conversacional LOCAL y GRATUITA (Ollama) que usa las herramientas del bot.

* Corre en la PC del usuario: no gasta tokens de Claude, no paga API y funciona sin internet.
* El modelo de lenguaje solo entiende y conversa; los números (probabilidades, cuotas, boletas) salen
  SIEMPRE de las herramientas del motor del bot. Así no inventa estadísticas.
* "Aprende": recuerda las preferencias que el usuario le pide guardar (datos/ia_memoria.json) y, como todo
  el bot, se re-estima con cada actualización de datos y mide su acierto real en el historial.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pandas as pd
import requests

from . import analisis as A
from . import asistente as AS
from . import betano as B
from . import combinador as CB
from . import config as C
from . import fijas as F
from . import registro as R

URL = "http://127.0.0.1:11434"
CONFIG = C.DIR_DATOS / "ia_config.json"
MEMORIA = C.DIR_DATOS / "ia_memoria.json"
MODELO_DEFECTO = "qwen3:4b-instruct"
MAX_RONDAS = 4
HISTORIAL_MAX = 8   # mensajes previos que se le pasan (más = más lento en CPU)


# --- configuración y estado --------------------------------------------------------------

def config() -> dict:
    try:
        return {"modelo": MODELO_DEFECTO, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except Exception:
        return {"modelo": MODELO_DEFECTO}


def guardar_config(**kw) -> None:
    CONFIG.write_text(json.dumps({**config(), **kw}, ensure_ascii=False, indent=1), encoding="utf-8")


def estado() -> dict:
    """{'servidor': bool, 'modelo': str, 'instalado': bool, 'modelos': [...]}"""
    m = config()["modelo"]
    try:
        r = requests.get(f"{URL}/api/tags", timeout=3)
        modelos = [x["name"] for x in r.json().get("models", [])]
        return {"servidor": True, "modelo": m, "modelos": modelos,
                "instalado": any(x == m or x.split(":")[0] == m.split(":")[0] and x.startswith(m) for x in modelos)}
    except Exception:
        return {"servidor": False, "modelo": m, "modelos": [], "instalado": False}


def memoria() -> list[str]:
    try:
        return json.loads(MEMORIA.read_text(encoding="utf-8"))
    except Exception:
        return []


def recordar(nota: str) -> None:
    notas = [n for n in memoria() if n.strip().lower() != nota.strip().lower()]
    notas.append(nota.strip())
    MEMORIA.write_text(json.dumps(notas[-30:], ensure_ascii=False, indent=1), encoding="utf-8")


def olvidar_todo() -> None:
    MEMORIA.write_text("[]", encoding="utf-8")


# --- herramientas ---------------------------------------------------------------------------

def _fn(nombre, descripcion, props, requeridos=()):
    return {"type": "function", "function": {"name": nombre, "description": descripcion, "parameters": {
        "type": "object", "properties": props, "required": list(requeridos)}}}


HERRAMIENTAS = [
    _fn("armar_boleta",
        "Arma una boleta de apuestas de fútbol para Betano con las selecciones más seguras (Bet Builders por partido). "
        "Úsala SIEMPRE que el usuario pida fijas, apuestas, combinadas, picks, una boleta o 'qué juego'.",
        {"cuando": {"type": "string", "enum": ["hoy", "manana", "hoy_manana", "finde", "semana"],
                    "description": "Día de los partidos. Por defecto hoy_manana."},
         "nivel": {"type": "string", "enum": ["ultra", "segura", "equilibrada"],
                   "description": "ultra = lo más seguro (cuotas ~1.15 por línea), segura (~1.25), equilibrada (~1.40)."},
         "selecciones": {"type": "integer", "description": "Cuántas líneas/partidos marcar. Opcional."},
         "cuota_objetivo": {"type": "number", "description": "Cuota total que quiere alcanzar. Opcional."},
         "monto": {"type": "number", "description": "Monto en soles. Opcional."},
         "ligas": {"type": "string", "description": "Ligas separadas por coma: premier, laliga, serie a, bundesliga, ligue 1, portugal, holanda, turquia. Opcional."},
         "jugadores": {"type": "boolean", "description": "Incluir tiros al arco de jugadores (por defecto sí)."},
         "corners": {"type": "boolean", "description": "Incluir córners (por defecto sí)."}}),
    _fn("analizar_partido", "Analiza un partido concreto: probabilidades de sus mercados, goles esperados y mejores opciones.",
        {"partido": {"type": "string", "description": "Equipos, por ejemplo 'Leeds vs Man United' o 'Arsenal'."}}, ["partido"]),
    _fn("evaluar_apuesta", "Evalúa una apuesta o fija concreta con su cuota: probabilidad real, cuota justa y si conviene.",
        {"texto": {"type": "string", "description": "La apuesta tal cual, ej. 'Leeds o empate a 1.40' o 'más de 1.5 Osasuna vs Santander 1.15'."}},
        ["texto"]),
    _fn("listar_partidos", "Lista los próximos partidos con probabilidades básicas.",
        {"cuando": {"type": "string", "enum": ["hoy", "manana", "hoy_manana", "finde", "semana"]},
         "liga": {"type": "string", "description": "Opcional: premier, laliga, serie a, bundesliga, ligue 1…"}}),
    _fn("regla_betano", "Explica una regla oficial de Betano Perú (pago anticipado, multi bono, cash out, tarjetas, córners, "
                        "partido suspendido, apuesta mínima, bet builder, seguro…).",
        {"tema": {"type": "string"}}, ["tema"]),
    _fn("mi_historial", "Balance real del usuario y acierto por fuente (bot, Telegram, tipsters).", {}),
    _fn("noticias", "Busca noticias recientes en internet (Google News): lesiones, bajas, alineaciones, previas, tendencias "
                    "de apuestas. Úsala antes de opinar sobre bajas o novedades de un partido o equipo.",
        {"consulta": {"type": "string", "description": "Equipos o tema, ej. 'Leeds Manchester United lesiones'."}}, ["consulta"]),
    _fn("recordar", "Guarda una preferencia del usuario para recordarla siempre (ej. 'mi monto habitual es 20 soles', "
                    "'no me gustan los córners'). Úsala cuando el usuario diga 'recuerda…' o exprese una preferencia estable.",
        {"nota": {"type": "string"}}, ["nota"]),
]


def _ligas(texto: str | None) -> list[str] | None:
    if not texto:
        return None
    t = AS.norm(texto)
    cods = []
    for alias, cs in AS.LIGAS_ALIAS.items():
        if alias in t:
            cods += cs
    for cod in C.LIGAS:
        if re.search(rf"\b{cod.lower()}\b", t):
            cods.append(cod)
    return sorted(set(cods)) or None


def _ventana(cuando: str | None):
    if not cuando or cuando == "hoy_manana":
        ini = F.ahora_peru()
        return ini, ini.normalize() + pd.Timedelta(days=2), "hoy y mañana"
    return F.ventana(cuando)


def h_armar_boleta(ctx, cuando=None, nivel="segura", selecciones=None, cuota_objetivo=None, monto=None,
                   ligas=None, jugadores=True, corners=True):
    nivel = nivel if nivel in CB.NIVELES else "segura"
    ini, fin, txt = _ventana(cuando)
    lineas = CB.generar(ini, fin, nivel, _ligas(ligas), bool(jugadores if jugadores is not None else True),
                        bool(corners if corners is not None else True))
    if not lineas and cuando in ("hoy", None, "hoy_manana"):
        ini, fin, txt = F.ventana("semana")
        lineas = CB.generar(ini, fin, nivel, _ligas(ligas), True, True)
    if not lineas:
        return {"error": f"No hay partidos con datos y cuotas para {txt}."}, []
    n = int(selecciones) if selecciones else None
    obj = float(cuota_objetivo) if cuota_objetivo else None
    marcadas = CB.preseleccion(lineas, n, obj)
    m = float(monto) if monto else ctx.monto
    cfg = CB.NIVELES[nivel]
    titulo = f"{cfg['emoji']} {cfg['nombre']} · {txt}"
    import numpy as np
    cuota = float(np.prod([lineas[i].cuota for i in marcadas]))
    p = float(np.prod([lineas[i].p for i in marcadas]))
    res = {"periodo": txt, "nivel": cfg["nombre"], "monto": m, "cuota_total": round(cuota, 2), "prob_acertar_todo": round(p, 3),
           "ganancia_potencial": round(m * cuota, 2), "otras_opciones_disponibles": max(0, len(lineas) - len(marcadas)),
           "lineas": [f"{lineas[i].partido}: " + " + ".join(pt.titulo for pt in lineas[i].patas)
                      + f" ({lineas[i].p:.0%})" for i in marcadas[:6]]}
    return res, [{"tipo": "super_boleta", "lineas": lineas, "marcadas": marcadas, "monto": m, "titulo": titulo}]


def h_analizar_partido(ctx, partido=""):
    eqs = AS.detectar_equipos(AS.norm(partido))
    if not eqs:
        return {"error": f"No reconocí equipos en '{partido}'."}, []
    f = AS.partido_proximo(eqs)
    if f is None:
        return {"error": "No encontré ese partido entre los próximos (la fuente cubre ligas europeas)."}, []
    from . import mercados as M
    ml = A.cargar_modelo(f.liga)
    mod = M.MotorPartido.desde_modelo(ml, f.local, f.visitante)
    ref = A.cuotas_proximo(f.liga, f.local, f.visitante)
    mer = M.motor_mercado(f.local, f.visitante, ref, ml) if ref else None
    w, _ = A.peso_modelo()
    filas = []
    for s in F.MERCADOS_FIJAS:
        pm = mod.prob([s])["conjunta"]
        pk = mer.prob([s])["conjunta"] if mer else None
        pc = F.calibrar(s, M.combinar(pm, pk, w))
        tit, sub = s.etiqueta(f.local, f.visitante)
        filas.append({"seleccion": f"{tit} ({sub})", "prob": round(pc, 3), "cuota_justa": round(1 / pc, 2)})
    filas.sort(key=lambda x: -x["prob"])
    res = {"partido": f"{f.local} vs {f.visitante}", "liga": C.LIGAS.get(f.liga), "inicio_peru": f"{f.inicio:%d/%m %H:%M}",
           "goles_esperados": [round(mod.lam, 2), round(mod.mu, 2)], "mercados": filas[:6], "avisos": mod.avisos[:1]}
    try:
        lineas = CB.generar(f.inicio - pd.Timedelta(minutes=1), f.inicio + pd.Timedelta(minutes=1), "segura", [f.liga])
        lineas = [l for l in lineas if l.local == f.local and l.visitante == f.visitante]
        if lineas:
            res["bet_builder_sugerido"] = {"seleccion": " + ".join(p.titulo + " (" + p.mercado + ")" for p in lineas[0].patas),
                                           "cuota": round(lineas[0].cuota, 2), "prob": round(lineas[0].p, 3)}
    except Exception:
        pass
    return res, [{"tipo": "partido", "liga": f.liga, "local": f.local, "visitante": f.visitante, "inicio": f.inicio}]


def h_evaluar_apuesta(ctx, texto=""):
    t = AS.norm(texto)
    eqs = AS.detectar_equipos(t)
    v = AS.verificar(eqs, t) if eqs else None
    if not v:
        return {"error": "No pude entender la apuesta: indica equipos, mercado y cuota."}, []
    l = v[0]["resultado"]["lineas"][0]
    res = {"apuesta": " + ".join(p["titulo"] + " (" + p["mercado"] + ")" for p in l["patas"]),
           "partido": f"{v[0]['grupo'].local} vs {v[0]['grupo'].visitante}", "cuota": l["cuota"],
           "prob_bot": l["p_final"] and round(l["p_final"], 3), "cuota_justa": l["cuota_justa"] and round(l["cuota_justa"], 2),
           "veredicto": l["veredicto"], "avisos": l["avisos"][:2]}
    return res, v


def h_listar_partidos(ctx, cuando=None, liga=None):
    tp = A.tabla_proximos()
    ini, fin, txt = _ventana(cuando)
    if tp.empty:
        return {"partidos": []}, []
    inicio = tp["fecha"] + pd.to_timedelta(tp["hora"].fillna("00:00") + ":00")
    tp = tp[(inicio >= ini) & (inicio < fin)]
    cods = _ligas(liga)
    if cods:
        tp = tp[tp["liga"].isin(cods)]
    out = [{"partido": f"{r.local} vs {r.visitante}", "liga": C.LIGAS.get(r.liga), "hora": f"{r.fecha:%d/%m} {r.hora}",
            "local_gana": round(r["1"], 2), "empate": round(r["X"], 2), "visita_gana": round(r["2"], 2),
            "mas_1_5": round(r["Más 1.5"], 2)} for _, r in tp.head(25).iterrows()]
    return {"periodo": txt, "partidos": out}, []


def h_regla_betano(ctx, tema=""):
    reglas = B.buscar_regla(tema, n=1)
    if not reglas:
        return {"error": "No encontré esa regla en la base oficial guardada."}, []
    return {"reglas": [{"titulo": r["titulo"], "texto": r["texto"], "fuente": r["url"]} for r in reglas]}, \
        [{"tipo": "regla", "regla": r} for r in reglas]


def h_mi_historial(ctx):
    met = R.metricas()
    out = {"resumen": met.get("resumen")}
    p = R.patas()
    p = p[p["resultado"].notna()]
    if len(p):
        g = p.groupby("fuente").agg(n=("id", "count"), aciertos=("resultado", "sum"), prob_bot=("p_final", "mean"))
        out["por_fuente"] = {k: {"selecciones": int(v.n), "acierto_real": round(v.aciertos / v.n, 3),
                                 "prob_esperada_bot": round(float(v.prob_bot), 3)} for k, v in g.iterrows()}
    return out, [{"tipo": "historial"}]


def h_recordar(ctx, nota=""):
    if nota.strip():
        recordar(nota)
    return {"guardado": True, "memoria": memoria()}, []


def buscar_noticias(consulta: str, n: int = 6) -> list[dict]:
    """Titulares recientes de Google News (RSS público) en español de Latinoamérica."""
    import urllib.parse
    import xml.etree.ElementTree as ET
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{consulta} when:4d", "hl": "es-419", "gl": "PE", "ceid": "PE:es-419"})
    r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        fuente = it.find("source")
        out.append({"titular": it.findtext("title"), "medio": fuente.text if fuente is not None else "",
                    "fecha": it.findtext("pubDate"), "enlace": it.findtext("link")})
        if len(out) >= n:
            break
    return out


def h_noticias(ctx, consulta=""):
    eqs = AS.detectar_equipos(AS.norm(consulta))
    q = " ".join(e for e, _ in eqs[:2]) + " lesiones alineación previa" if eqs else consulta
    notas = buscar_noticias(q)
    if not notas and eqs:
        notas = buscar_noticias(" ".join(e for e, _ in eqs[:2]))
    res = {"consulta": q, "noticias": [{k: v for k, v in x.items() if k != "enlace"} for x in notas],
           "aviso": "Son titulares de medios: resume lo relevante (bajas, dudas, contexto) sin inventar detalles que no estén."}
    return res, [{"tipo": "noticias", "consulta": q, "lista": notas}]


EJECUTORES = {"armar_boleta": h_armar_boleta, "analizar_partido": h_analizar_partido, "evaluar_apuesta": h_evaluar_apuesta,
              "listar_partidos": h_listar_partidos, "regla_betano": h_regla_betano, "mi_historial": h_mi_historial,
              "recordar": h_recordar, "noticias": h_noticias}


# --- conversación ----------------------------------------------------------------------------

def contexto_turno(ctx) -> str:
    """Datos que cambian (fecha, monto): van en el mensaje del usuario para no romper la caché del prefijo."""
    ahora = F.ahora_peru()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"[Contexto: hoy {dias[ahora.dayofweek]} {ahora:%d/%m/%Y %H:%M} hora de Perú; monto por defecto S/{ctx.monto:.2f}]"


def sistema(ctx=None) -> str:
    """Instrucciones FIJAS (idénticas en cada llamada: Ollama reutiliza su caché y responde mucho más rápido)."""
    notas = memoria()
    return (
        "Eres FútBot, analista de apuestas de fútbol para Betano Perú. Hablas en español peruano, cercano y claro, "
        "con respuestas cortas (máx. 6 líneas salvo que te pidan detalle). Nunca escribas tu razonamiento interno.\n"
        "REGLAS:\n"
        "1. Para fijas, apuestas, combinadas, boletas o 'qué juego' llama a armar_boleta. Para un partido, analizar_partido. "
        "Para revisar una fija con cuota, evaluar_apuesta. Para reglas de Betano, regla_betano. Para su balance, mi_historial. "
        "Si dice 'recuerda…' o una preferencia estable, recordar.\n"
        "2. Nunca inventes probabilidades, cuotas, estadísticas, lesiones ni alineaciones: usa solo lo que devuelven las herramientas. "
        "Si no sabes algo (lesiones, alineaciones), dilo.\n"
        "3. Nunca digas que algo es seguro o garantizado: di la probabilidad (ej. 'acierta ~8 de cada 10'). La probabilidad de acertar "
        "toda una combinada es mucho menor que la de cada línea: menciónala siempre.\n"
        "4. Las cuotas con '≈' son estimadas: recuerda copiar las reales de Betano. El usuario decide el monto.\n"
        "5. Tras armar_boleta, la boleta interactiva ya se ve en pantalla (el usuario desmarca líneas y cambia el monto ahí, "
        "en tiempo real): resume en 3 líneas cuota total, probabilidad de acertar todo y ganancia, más 1 advertencia; "
        "no copies las líneas.\n"
        "6. Si pide algo fuera de apuestas de fútbol, responde breve y vuelve al tema.\n"
        + ("PREFERENCIAS GUARDADAS DEL USUARIO:\n- " + "\n- ".join(notas) + "\n" if notas else "")
        + "/no_think"
    )


def _limpiar(texto: str) -> str:
    texto = re.sub(r"<think>.*?</think>", "", texto or "", flags=re.S)
    return texto.replace("/no_think", "").strip()


def _cuerpo(mensajes: list[dict], stream: bool, max_tokens: int = 320) -> dict:
    # Siempre las mismas herramientas e instrucciones: así Ollama reutiliza la caché del prefijo.
    return {"model": config()["modelo"], "messages": mensajes, "stream": stream, "think": False, "tools": HERRAMIENTAS,
            "options": {"temperature": 0.3, "num_ctx": 8192, "num_predict": max_tokens}, "keep_alive": "60m"}


def _chat(mensajes: list[dict]) -> dict:
    r = requests.post(f"{URL}/api/chat", json=_cuerpo(mensajes, False), timeout=600)
    r.raise_for_status()
    return r.json()["message"]


def precalentar() -> None:
    """Carga el modelo y deja en caché las instrucciones fijas (la primera respuesta real sale mucho más rápido)."""
    try:
        cuerpo = _cuerpo([{"role": "system", "content": sistema()}, {"role": "user", "content": "hola"}], False, 1)
        requests.post(f"{URL}/api/chat", json=cuerpo, timeout=600)
    except Exception:
        pass


def _ejecutar(ctx, nombre: str, args: dict) -> tuple[dict, list]:
    ejecutor = EJECUTORES.get(nombre)
    try:
        if ejecutor is None:
            raise ValueError(f"herramienta desconocida: {nombre}")
        return ejecutor(ctx, **{k: v for k, v in (args or {}).items() if v not in ("", None)})
    except TypeError as e:
        return {"error": f"argumentos inválidos: {e}"}, []
    except Exception as e:  # el error vuelve al modelo para que lo explique
        return {"error": f"{type(e).__name__}: {e}"}, []


def _preruta(texto: str) -> tuple[str, dict] | None:
    """Pedidos típicos que el bot entiende solo: va directo a la herramienta (más rápido y fiable en CPU)."""
    t = re.sub(r"\s+", " ", AS.norm(texto)).strip()
    if re.search(r"\b(recuerda|recuerdame|anota que|guarda que|ten en cuenta que)\b", t):
        return "recordar", {"nota": texto}
    if re.search(r"noticia|lesion|lesionad|\bbajas?\b|alineaci|tendencia|que se dice|rumor|novedad", t):
        return "noticias", {"consulta": texto}
    reglas = B.buscar_regla(t)
    pregunta = "?" in texto or bool(re.match(r"(que|como|cual|cuanto|cuando|donde|por que|se puede|puedo)\b", t))
    quiere = any(re.search(rf"\b{re.escape(w)}\b", t) for w in AS.PAL_FIJAS)
    if reglas and pregunta and not re.search(r"\b(dame|recomienda|arma|armame|quiero)\b", t):
        return "regla_betano", {"tema": texto}
    if any(w in t for w in AS.PAL_HISTORIAL):
        return "mi_historial", {}
    eqs = AS.detectar_equipos(t)
    if eqs and re.search(r"\d[.,]\d", t) and re.search(r"revisa|verifica|conviene|vale|es buena|la juego|\ba \d|@|cuota", t):
        return "evaluar_apuesta", {"texto": texto}
    if eqs and not re.search(r"\b(fijas|combinada|boleta|parley|parlay)\b", t):
        return "analizar_partido", {"partido": texto}
    if quiere or re.search(r"\b(hoy|manana|finde|fin de semana)\b", t):
        p = AS.leer_peticion(t)
        cuando = p.cuando if p.cuando in ("hoy", "manana", "finde", "semana") else (
            "hoy_manana" if p.cuando == "hoy_manana" else "semana")
        nivel = {"ultra": "ultra", "segura": "segura"}.get(p.perfil, "equilibrada")
        return "armar_boleta", {"cuando": cuando, "nivel": nivel, "selecciones": p.n, "cuota_objetivo": p.cuota_objetivo,
                                "monto": p.monto, "ligas": texto if p.ligas else None}
    return None


@dataclass
class Turno:
    mensajes: list
    bloques: list
    texto: str | None = None      # respuesta ya lista (si no, se escribe en vivo con escribir())


def iniciar_turno(texto: str, ctx, historial: list[dict]) -> Turno:
    """Ejecuta herramientas (atajo directo o elegidas por la IA). La respuesta final se escribe con escribir()."""
    mensajes = ([{"role": "system", "content": sistema()}] + historial[-HISTORIAL_MAX:]
                + [{"role": "user", "content": f"{texto}\n\n{contexto_turno(ctx)}"}])
    bloques: list[dict] = []
    ruta = _preruta(texto)
    if ruta:
        nombre, args = ruta
        res, bl = _ejecutar(ctx, nombre, args)
        bloques += bl
        mensajes += [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": nombre, "arguments": args}}]},
                     {"role": "tool", "content": json.dumps(res, ensure_ascii=False, default=str), "tool_name": nombre}]
        return Turno(mensajes, bloques)
    for _ in range(MAX_RONDAS):
        msg = _chat(mensajes)
        llamadas = msg.get("tool_calls") or []
        if not llamadas:
            return Turno(mensajes, bloques, _limpiar(msg.get("content", "")))
        mensajes.append({"role": "assistant", "content": msg.get("content", ""), "tool_calls": llamadas})
        for ll in llamadas:
            fn = ll.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            res, bl = _ejecutar(ctx, fn.get("name"), args)
            bloques += bl
            mensajes.append({"role": "tool", "content": json.dumps(res, ensure_ascii=False, default=str),
                             "tool_name": fn.get("name")})
    return Turno(mensajes, bloques)


def escribir(turno: Turno):
    """Generador: escribe la respuesta final de la IA en vivo (texto a medida que se genera)."""
    if turno.texto is not None:
        yield turno.texto
        return
    with requests.post(f"{URL}/api/chat", json=_cuerpo(turno.mensajes, True), stream=True, timeout=600) as r:
        r.raise_for_status()
        buf, dentro_think = "", False
        for linea in r.iter_lines():
            if not linea:
                continue
            d = json.loads(linea)
            trozo = d.get("message", {}).get("content", "")
            if trozo:
                buf += trozo
                if "<think>" in buf and "</think>" not in buf:
                    dentro_think = True
                    continue
                if dentro_think:
                    buf = buf.split("</think>", 1)[-1]
                    dentro_think = False
                    trozo = buf
                yield trozo.replace("/no_think", "")
            if d.get("done"):
                break


def responder(texto: str, ctx, historial: list[dict]) -> tuple[str, list[dict]]:
    """Versión sin streaming: (texto de la IA, bloques para la interfaz)."""
    turno = iniciar_turno(texto, ctx, historial)
    return _limpiar("".join(escribir(turno))), turno.bloques
