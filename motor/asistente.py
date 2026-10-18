"""Asistente de chat (sin internet ni costo): entiende pedidos en español y responde con bloques
que la interfaz dibuja (texto, combinadas, partidos, reglas de Betano…).

No es un modelo de lenguaje: reconoce intenciones con reglas. Si no entiende, lo dice y sugiere frases.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

from . import analisis as A
from . import betano as B
from . import config as C
from . import datos
from . import fijas as F
from . import mercados as M

norm = B.normalizar

SUGERENCIAS = [
    "Dame las fijas de hoy",
    "Combinada de 3 para mañana con 20 soles",
    "Quiero cuota 3 con lo más seguro",
    "Bet builder del Arsenal",
    "Revisa: Leeds o empate a 1.40",
    "¿Qué es el Pago Anticipado?",
    "¿Cómo cuentan las tarjetas en Betano?",
    "¿Cómo voy con mis apuestas?",
]

PAL_FIJAS = ("fija", "fijas", "apuesta", "apuestas", "combinada", "combinadas", "combi", "pick", "picks",
             "pronostico", "pronosticos", "recomienda", "recomiendame", "sugiere", "parley", "parlay",
             "boleta", "ticket", "cupon", "seguras", "segura", "jugada", "jugadas", "dame", "quiero",
             "doble", "triple", "simple", "simples", "mas seguro", "cuota")
PAL_PREGUNTA = ("que es", "que son", "como funciona", "como funcionan", "que pasa", "que sucede", "cuenta",
                "cuentan", "como se", "regla", "reglas", "politica", "se anula", "minimo", "maximo", "puedo",
                "explica", "explicame", "significa", "aplica", "sirve", "cuanto es", "valen", "vale")
PAL_ANALIZAR = ("analiza", "analisis", "como ves", "que opinas", "opinion", "probabilidad", "pronostico de",
                "informe", "estadistica", "estadisticas", "que tal", "como viene", "previa", "para el partido",
                "bet builder", "betbuilder", "crear apuesta")
PAL_HISTORIAL = ("como voy", "historial", "mis apuestas", "mi balance", "balance", "roi", "cuanto llevo",
                 "cuanto he ganado", "cuanto he perdido", "mis boletas", "rendimiento")
PAL_AYUDA = ("ayuda", "como se usa", "como funciona el bot", "que puedes hacer", "que haces", "instrucciones",
             "como te uso", "tutorial", "guia")

LIGAS_ALIAS = {
    "premier": ["E0"], "inglesa": ["E0"], "inglaterra": ["E0"], "championship": ["E1"],
    "laliga": ["SP1"], "la liga": ["SP1"], "liga espanola": ["SP1"], "espana": ["SP1"], "espanola": ["SP1"],
    "segunda division": ["SP2"], "serie a": ["I1"], "italiana": ["I1"], "italia": ["I1"], "calcio": ["I1"],
    "bundesliga": ["D1"], "alemana": ["D1"], "alemania": ["D1"], "ligue 1": ["F1"], "francesa": ["F1"],
    "francia": ["F1"], "eredivisie": ["N1"], "holanda": ["N1"], "holandesa": ["N1"], "portugal": ["P1"],
    "portuguesa": ["P1"], "turquia": ["T1"], "turca": ["T1"], "escocia": ["SC0"], "grecia": ["G1"],
    "belgica": ["B1"], "top 5": ["E0", "SP1", "I1", "D1", "F1"], "grandes ligas": ["E0", "SP1", "I1", "D1", "F1"],
    "ligas top": ["E0", "SP1", "I1", "D1", "F1"], "5 grandes": ["E0", "SP1", "I1", "D1", "F1"],
}

ALIAS_EQUIPOS = {
    "barca": "Barcelona", "barcelona": "Barcelona", "real madrid": "Real Madrid", "madrid": "Real Madrid",
    "atletico de madrid": "Ath Madrid", "atletico madrid": "Ath Madrid", "atleti": "Ath Madrid",
    "atletico": "Ath Madrid", "athletic": "Ath Bilbao", "athletic bilbao": "Ath Bilbao", "bilbao": "Ath Bilbao",
    "real sociedad": "Sociedad", "rayo": "Vallecano", "rayo vallecano": "Vallecano", "espanyol": "Espanol",
    "deportivo": "La Coruna", "depor": "La Coruna", "la coruna": "La Coruna", "racing de santander": "Santander",
    "man city": "Man City", "manchester city": "Man City", "city": "Man City",
    "man united": "Man United", "manchester united": "Man United", "man utd": "Man United", "united": "Man United",
    "nottingham": "Nott'm Forest", "nottingham forest": "Nott'm Forest", "n forest": "Nott'm Forest",
    "forest": "Nott'm Forest", "spurs": "Tottenham", "villa": "Aston Villa", "palace": "Crystal Palace",
    "wolverhampton": "Wolves", "inter de milan": "Inter", "inter milan": "Inter", "internazionale": "Inter",
    "ac milan": "Milan", "juve": "Juventus", "napoles": "Napoli", "bayern munchen": "Bayern Munich",
    "bayern": "Bayern Munich", "borussia dortmund": "Dortmund", "bvb": "Dortmund", "leipzig": "RB Leipzig",
    "frankfurt": "Ein Frankfurt", "eintracht": "Ein Frankfurt", "gladbach": "M'gladbach",
    "monchengladbach": "M'gladbach", "koln": "FC Koln", "colonia": "FC Koln", "psg": "Paris SG",
    "paris saint germain": "Paris SG", "marsella": "Marseille", "niza": "Nice", "sporting lisboa": "Sp Lisbon",
    "sporting cp": "Sp Lisbon", "braga": "Sp Braga", "psv": "PSV Eindhoven", "az": "AZ Alkmaar",
    "flamengo": "Flamengo RJ", "botafogo": "Botafogo RJ", "atletico mineiro": "Atletico-MG",
    "athletico paranaense": "Athletico-PR", "boca": "Boca Juniors", "river": "River Plate", "velez": "Velez Sarsfield",
    "estudiantes": "Estudiantes L.P.", "newells": "Newells Old Boys", "america": "Club America",
    "chivas": "Guadalajara Chivas", "tigres": "Tigres UANL", "pumas": "UNAM Pumas", "inter miami": "Inter Miami",
    "miami": "Inter Miami", "galaxy": "Los Angeles Galaxy", "lafc": "Los Angeles FC",
}
# palabras comunes que coinciden con nombres de equipos: solo cuentan junto a "vs"/"contra"
AMBIGUAS = {"como", "real", "city", "united", "nacional", "racing", "union", "levante", "pisa", "santos",
            "estrela", "villa", "forest", "madrid", "america", "atletico", "deportivo", "river", "az", "miami"}

NUM = r"(\d+(?:[.,]\d+)?)"


def _num(s: str) -> float:
    return float(s.replace(",", "."))


@dataclass
class Peticion:
    cuando: str = "hoy_manana"
    n: int | None = None
    cuota_objetivo: float | None = None
    monto: float | None = None
    perfil: str = "segura"
    ligas: list | None = None
    corners: bool = False
    mercados: list | None = None


@dataclass
class Contexto:
    monto: float = 10.0
    ultima_peticion: Peticion | None = None
    ultima_combinada: F.Combinada | None = None
    ultima_super: tuple | None = None      # (líneas del combinador, índices marcados)
    historial: list = field(default_factory=list)


# --- índice de equipos ----------------------------------------------------------------

@lru_cache(maxsize=2)
def _indice_equipos(_firma) -> dict:
    df = datos.cargar_partidos()
    px = datos.cargar_proximos()
    reciente = df[df["fecha"] >= df["fecha"].max() - pd.Timedelta(days=400)]
    liga_de: dict = {}
    for _, f in px.iterrows():
        liga_de.setdefault(f.local, f.liga)
        liga_de.setdefault(f.visitante, f.liga)
    ult = pd.concat([reciente[["fecha", "liga", "local"]].rename(columns={"local": "eq"}),
                     reciente[["fecha", "liga", "visitante"]].rename(columns={"visitante": "eq"})])
    ult = ult.sort_values("fecha").groupby("eq").tail(1)
    for _, f in ult.iterrows():
        liga_de.setdefault(f.eq, f.liga)
    indice = {}
    for eq, liga in liga_de.items():
        n = norm(eq).replace("'", "").replace(".", " ").replace("-", " ")
        n = re.sub(r"\s+", " ", n).strip()
        indice.setdefault(n, (eq, liga))
    for alias, eq in ALIAS_EQUIPOS.items():
        if eq in liga_de:
            indice.setdefault(alias, (eq, liga_de[eq]))
    return indice


def indice_equipos() -> dict:
    return _indice_equipos(datos._firma())


def detectar_equipos(t: str) -> list[tuple[str, str]]:
    """Equipos mencionados (nombre exacto de los datos, liga), en orden de aparición."""
    t = " " + re.sub(r"[^\w\s]", " ", t) + " "
    t = re.sub(r"\s+", " ", t)
    idx = indice_equipos()
    ocupado = [False] * len(t)
    hallados = []
    for alias in sorted(idx, key=len, reverse=True):
        for m in re.finditer(r"(?<= )" + re.escape(alias) + r"(?= )", t):
            a, b = m.span()
            if any(ocupado[a:b]):
                continue
            if alias in AMBIGUAS:
                antes, despues = t[max(0, a - 8):a], t[b:b + 8]
                if not re.search(r"(vs|contra|v|x|ante|frente a)\s*$", antes) and not re.search(r"^\s*(vs|contra|v|x)\b", despues):
                    continue
            for i in range(a, b):
                ocupado[i] = True
            hallados.append((a, idx[alias]))
    hallados.sort()
    vistos, out = set(), []
    for _, (eq, liga) in hallados:
        if eq not in vistos:
            vistos.add(eq)
            out.append((eq, liga))
    return out


def partido_proximo(equipos: list[tuple[str, str]]) -> pd.Series | None:
    px = datos.cargar_proximos()
    if px.empty or not equipos:
        return None
    nombres = [e for e, _ in equipos]
    if len(nombres) >= 2:
        f = px[(px["local"].isin(nombres[:2])) & (px["visitante"].isin(nombres[:2]))]
    else:
        f = px[(px["local"] == nombres[0]) | (px["visitante"] == nombres[0])]
    f = f[f["inicio"] >= F.ahora_peru() - pd.Timedelta(hours=2)]
    return f.iloc[0] if len(f) else None


# --- interpretación ---------------------------------------------------------------------

def leer_peticion(t: str, base: Peticion | None = None) -> Peticion:
    p = Peticion(**(base.__dict__ if base else {}))
    if "pasado manana" in t:
        p.cuando = "pasado"
    elif re.search(r"\bhoy\b", t):
        p.cuando = "hoy"
    elif re.search(r"\bmanana\b", t):
        p.cuando = "manana"
    elif re.search(r"fin de semana|finde", t):
        p.cuando = "finde"
    elif re.search(r"\bsemana\b|proximos dias", t):
        p.cuando = "semana"
    else:
        for i, dia in enumerate(("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")):
            if re.search(rf"\b{dia}\b", t):
                hoy = F.ahora_peru().normalize()
                p.cuando = str((hoy + pd.Timedelta(days=(i - hoy.dayofweek) % 7)).date())
        m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", t)
        if m:
            p.cuando = f"{F.ahora_peru().year}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"

    m = (re.search(r"(?:s/\.?\s*|con\s+|monto\s+(?:de\s+)?|apuesto\s+|apostar\s+|invierto\s+|meter\s+)" + NUM + r"(?!\s*(?:fijas|selecciones|partidos|patas|picks|apuestas|equipos|lineas))", t)
         or re.search(NUM + r"\s*(?:soles|sol|lucas|luca|mangos)\b", t))
    if m:
        p.monto = _num(m.group(1))

    m = (re.search(r"(?:combinada|combi|parley|parlay|boleta|ticket)\s+de\s+(\d+)", t)
         or re.search(r"\b(\d+)\s+(?:fijas|selecciones|partidos|patas|picks|apuestas|equipos|lineas)\b", t))
    palabras_n = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8}
    if m:
        p.n = int(m.group(1))
    else:
        for w, k in palabras_n.items():
            if re.search(rf"\b{w}\s+(?:fijas|selecciones|partidos|patas|picks|apuestas|equipos)\b", t):
                p.n = k
        if re.search(r"\bdoble\b", t) and "oportunidad" not in t:
            p.n = 2
        elif re.search(r"\btriple\b", t):
            p.n = 3
        elif re.search(r"\bcuadruple\b", t):
            p.n = 4
        elif re.search(r"\b(simple|simples|una sola|individual)\b", t):
            p.n = 1

    m = (re.search(r"cuota\s+(?:total\s+)?(?:de\s+|minima\s+de\s+|minima\s+)?" + NUM, t)
         or re.search(r"(?:que\s+)?pague\s+(?:a\s+)?" + NUM, t))
    if m and _num(m.group(1)) > 1:
        p.cuota_objetivo = _num(m.group(1))
    elif re.search(r"cuota alta|mas cuota|que pague mas|algo mas alto", t):
        p.cuota_objetivo = max(3.0, (p.cuota_objetivo or 2.0) * 1.5)

    if re.search(r"ultra|muy segur|lo mas segur|segurisim|casi segur|sin riesgo", t):
        p.perfil = "ultra"
    elif re.search(r"arriesgad|riesgo alto|bomba|locura", t):
        p.perfil = "arriesgada"
    elif re.search(r"equilibrad|intermedi|normal", t):
        p.perfil = "equilibrada"
    elif re.search(r"\bsegur", t):
        p.perfil = "segura"
    if p.cuota_objetivo and p.cuota_objetivo >= 2.5 and p.perfil == "segura" and not re.search(r"\bsegur", t):
        p.perfil = "equilibrada"

    ligas = []
    for alias, cods in LIGAS_ALIAS.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            ligas += cods
    if ligas:
        p.ligas = sorted(set(ligas))
    if re.search(r"corner|esquina", t):
        p.corners = True
    if re.search(r"solo goles|de goles|mas de 1 5|over", t):
        p.mercados = ["goles", "btts", "goles_local", "goles_visitante", "1t_goles"]
    elif re.search(r"ambos anotan|ambos marcan|btts", t):
        p.mercados = ["btts"]
    elif re.search(r"doble oportunidad", t):
        p.mercados = ["doble"]
    elif re.search(r"ganador|1x2|que gane", t):
        p.mercados = ["1x2"]
    return p


def leer_selecciones(t: str, local: str, visitante: str) -> tuple[list[M.Seleccion], float | None]:
    """Mercados y cuota escritos en el texto (para verificar una fija)."""
    sels: list[M.Seleccion] = []
    nl, nv = norm(local), norm(visitante)
    al = {nl} | {a for a, e in ALIAS_EQUIPOS.items() if e == local}
    av = {nv} | {a for a, e in ALIAS_EQUIPOS.items() if e == visitante}
    patron_eq = lambda s: "(?:" + "|".join(re.escape(x) for x in sorted(s, key=len, reverse=True)) + ")"
    cuota = None
    m = re.search(r"(?:@|\ba\s+|cuota\s+(?:de\s+)?|paga\s+|pagan\s+)(\d+[.,]\d+)", t)
    if m:
        cuota = _num(m.group(1))
    for m in re.finditer(r"(mas|menos|over|under|\+|-)\s*(?:de\s*)?(\d+[.,]5)\s*(corner\w*|esquina\w*|tarjeta\w*|goles?)?\s*(primer tiempo|1t|1er tiempo|primera mitad|segundo tiempo|2t)?", t):
        op = "mas" if m.group(1) in ("mas", "over", "+") else "menos"
        linea = _num(m.group(2))
        cola = (m.group(3) or "") + " " + t[m.end():m.end() + 25]
        if re.search(r"corner|esquina", cola):
            sels.append(M.Seleccion("corners", op, linea))
        elif re.search(r"tarjeta", cola):
            sels.append(M.Seleccion("tarjetas", op, linea))
        elif m.group(4) and m.group(4).startswith(("primer", "1", "primera")):
            sels.append(M.Seleccion("1t_goles", op, linea))
        elif m.group(4):
            sels.append(M.Seleccion("2t_goles", op, linea))
        else:
            sels.append(M.Seleccion("goles", op, linea))
    if re.search(r"ambos (?:equipos )?(?:anotan|marcan)|btts", t):
        sels.append(M.Seleccion("btts", "no" if re.search(r"(no ambos|ambos (?:equipos )?(?:anotan|marcan)\s*:?\s*no|btts no)", t) else "si"))
    for equipo, mercado in ((al, "goles_local"), (av, "goles_visitante")):
        if re.search(patron_eq(equipo) + r"\s+(?:anota|marca|convierte|hace gol|le hace gol|mete gol)", t) \
                or re.search(r"(?:anota|marca|gol de)\s+(?:el\s+)?" + patron_eq(equipo) + r"\b", t):
            sels.append(M.Seleccion(mercado, "mas", 0.5))
    if re.search(patron_eq(al) + r"\s+o\s+empate", t):
        sels.append(M.Seleccion("doble", "1X"))
    elif re.search(patron_eq(av) + r"\s+o\s+empate", t):
        sels.append(M.Seleccion("doble", "X2"))
    elif re.search(r"(?:gana|ganador|victoria de|triunfo de)\s+" + patron_eq(al) + r"|" + patron_eq(al) + r"\s+(?:gana|ganador)", t):
        sels.append(M.Seleccion("1x2", "local"))
    elif re.search(r"(?:gana|ganador|victoria de|triunfo de)\s+" + patron_eq(av) + r"|" + patron_eq(av) + r"\s+(?:gana|ganador)", t):
        sels.append(M.Seleccion("1x2", "visitante"))
    elif re.search(r"\bempate\b", t):
        sels.append(M.Seleccion("1x2", "empate"))
    return sels, cuota


# --- respuestas ---------------------------------------------------------------------------

def _texto(md: str) -> dict:
    return {"tipo": "texto", "md": md}


def generar_fijas(p: Peticion, ctx: Contexto) -> list[dict]:
    """Súper boleta interactiva (Bet Builders seguros por partido) según el pedido."""
    import numpy as np
    from . import combinador as CB
    if p.cuando == "hoy_manana":
        ini = F.ahora_peru()
        fin, txt = ini.normalize() + pd.Timedelta(days=2), "hoy y mañana"
    else:
        ini, fin, txt = F.ventana(p.cuando)
    nivel = {"ultra": "ultra", "segura": "segura"}.get(p.perfil, "equilibrada")
    lineas = CB.generar(ini, fin, nivel, p.ligas, True, True if p.corners or not p.mercados else False)
    if not lineas:
        return generar_fijas_simple(p, ctx)
    marcadas = CB.preseleccion(lineas, p.n, p.cuota_objetivo)
    monto = p.monto if p.monto is not None else ctx.monto
    cfg = CB.NIVELES[nivel]
    ctx.ultima_peticion = p
    ctx.ultima_super = (lineas, marcadas)
    cuota = float(np.prod([lineas[i].cuota for i in marcadas]))
    prob = float(np.prod([lineas[i].p for i in marcadas]))
    return [{"tipo": "texto", "md": f"{cfg['emoji']} **{len(marcadas)} líneas {cfg['nombre'].lower()}s para {txt}** · cuota ≈ "
                                    f"{cuota:.2f} · acertar todo ≈ **{prob:.0%}**. Desmarca lo que no quieras o cambia el monto: "
                                    "la boleta se recalcula al instante. Abajo tienes más opciones sin marcar."},
            {"tipo": "super_boleta", "lineas": lineas, "marcadas": marcadas, "monto": monto,
             "titulo": f"{cfg['emoji']} {cfg['nombre']} · {txt}"}]


def generar_fijas_simple(p: Peticion, ctx: Contexto) -> list[dict]:
    if p.cuando == "hoy_manana":
        ini = F.ahora_peru()
        fin = ini.normalize() + pd.Timedelta(days=2)
        txt = "hoy y mañana"
    else:
        ini, fin, txt = F.ventana(p.cuando)
    monto = p.monto if p.monto is not None else ctx.monto
    cands = F.candidatas(ini, fin, p.ligas, p.corners, p.mercados)
    if not cands:
        ligas_txt = " de esas ligas" if p.ligas else ""
        return [_texto(f"No encontré partidos{ligas_txt} con cuotas de referencia para **{txt}**. "
                       "La fuente trae las ligas europeas de la semana (se actualiza los martes y viernes). "
                       "Prueba con *«fijas de mañana»* o *«fijas del fin de semana»*.")]
    perfil = p.perfil
    aptas = F.filtrar(cands, perfil)
    aviso_perfil = ""
    while len(F.mejores_simples(aptas, 99)) < max(p.n or 3, 1) and perfil != "arriesgada":
        perfil = {"ultra": "segura", "segura": "equilibrada", "equilibrada": "arriesgada"}[perfil]
        aptas = F.filtrar(cands, perfil)
        aviso_perfil = (f"No había suficientes selecciones con el nivel pedido; bajé a **{F.PERFILES[perfil]['nombre']}**.")
    bloques = []
    pf = F.PERFILES[perfil]
    n = p.n
    if p.cuota_objetivo:
        patas = F.armar_combinada(aptas, n=n, cuota_objetivo=p.cuota_objetivo)
        escalera = [x for x in ("segura", "equilibrada", "arriesgada")
                    if F.PERFILES[x]["p_min"] < F.PERFILES[perfil]["p_min"]]
        for nivel in escalera:  # baja el nivel de a uno hasta alcanzar la cuota pedida
            if patas:
                break
            patas = F.armar_combinada(F.filtrar(cands, nivel), n=n, cuota_objetivo=p.cuota_objetivo)
            perfil = nivel
            aviso_perfil = f"Para llegar a esa cuota usé selecciones de nivel **{F.PERFILES[nivel]['nombre']}**."
        pf = F.PERFILES[perfil]
        titulo = f"{pf['emoji']} Combinada buscando cuota {p.cuota_objetivo:.2f} para {txt}"
    else:
        patas = F.armar_combinada(aptas, n=n or 3)
        titulo = f"{pf['emoji']} {'Fija' if (n or 3) == 1 else 'Fijas'} para {txt} · perfil {pf['nombre']}"
    if not patas:
        return [_texto("No pude armar una combinada con esas condiciones. Prueba con menos selecciones o menos cuota.")]
    comb = F.Combinada(patas, monto, titulo)
    if aviso_perfil:
        comb.notas.append(aviso_perfil)
    ctx.ultima_peticion, ctx.ultima_combinada = p, comb
    bloques.append({"tipo": "combinada", "combinada": comb})
    otras = [c for c in F.mejores_simples(aptas, 8) if c not in patas][:5]
    if otras:
        bloques.append({"tipo": "simples", "titulo": "Otras opciones fuertes (por si quieres cambiar una)", "lista": otras})
    falla = 1 - comb.p_total
    bloques.append(_texto(
        f"📌 Probabilidad de acertar **todo**: **{comb.p_total:.0%}**: de cada 10 boletas así, unas "
        f"{falla * 10:.0f} se caen. Las cuotas con «≈» son estimadas: **cópialas de Betano** antes de apostar "
        "y, si son más bajas, la apuesta pierde valor."))
    return bloques


def analizar_partido(equipos, t: str, ctx: Contexto) -> list[dict]:
    f = partido_proximo(equipos)
    if f is None:
        nombres = " y ".join(e for e, _ in equipos)
        if len(equipos) >= 2 and equipos[0][1] == equipos[1][1]:
            return [{"tipo": "partido", "liga": equipos[0][1], "local": equipos[0][0], "visitante": equipos[1][0],
                     "inicio": None},
                    _texto("No está en la lista de próximos partidos de la fuente: uso solo el modelo (menos fiable). "
                           "Si me pasas las cuotas 1X2 de Betano, lo afino en **🔍 Verificar**.")]
        return [_texto(f"No encontré un partido próximo de **{nombres}** en la fuente (cubre ligas europeas). "
                       "Escribe los dos equipos, por ejemplo *«Barcelona vs Getafe»*.")]
    bloques = [{"tipo": "partido", "liga": f.liga, "local": f.local, "visitante": f.visitante, "inicio": f.inicio}]
    if re.search(r"bet ?builder|crear apuesta|mismo partido", t):
        bbs = F.bet_builders(f.liga, f.local, f.visitante)
        if bbs:
            bloques.append({"tipo": "bet_builders", "liga": f.liga, "local": f.local, "visitante": f.visitante,
                            "lista": bbs, "monto": ctx.monto})
    return bloques


def verificar(equipos, t: str) -> list[dict] | None:
    f = partido_proximo(equipos)
    if f is not None:
        liga, local, visitante = f.liga, f.local, f.visitante
    elif len(equipos) >= 2:
        liga, local, visitante = equipos[0][1], equipos[0][0], equipos[1][0]
    else:
        return None
    sels, cuota = leer_selecciones(t, local, visitante)
    if not sels:
        return None
    g = A.Grupo(liga, local, visitante, sels, cuota, str(f.inicio.date()) if f is not None else None, None, "chat")
    res = A.analizar_boleta([g], 0)
    return [{"tipo": "verificacion", "resultado": res, "grupo": g}]


def responder(texto: str, ctx: Contexto) -> list[dict]:
    t = norm(texto).strip()
    t = re.sub(r"\s+", " ", t)
    if not t:
        return []
    if re.fullmatch(r"(hola|buenas|buenos dias|buenas tardes|buenas noches|hey|que tal|ola)[!. ]*", t):
        return [_texto("¡Hola! 👋 Soy tu bot de fútbol para **Betano**. Pídeme fijas, combinadas con la cuota y el monto que quieras, "
                       "un análisis de un partido o cualquier duda de las reglas de Betano."),
                {"tipo": "sugerencias", "lista": SUGERENCIAS[:6]}]
    if any(w in t for w in PAL_AYUDA):
        return [{"tipo": "ayuda"}]

    if re.search(r"\b(agrega(?:la|lo)?|anade|añade|guarda(?:la)?|pasa(?:la)?|mandala)\b.*\b(boleta|cupon|ticket)\b|\ba mi boleta\b", t):
        if ctx.ultima_combinada or ctx.ultima_super:
            return [{"tipo": "accion", "accion": "agregar_ultima"}]
        return [_texto("Todavía no te propuse ninguna combinada. Pídeme, por ejemplo, *«dame las fijas de hoy»*.")]

    reglas = B.buscar_regla(t)
    es_pregunta = ("?" in texto or bool(re.match(r"(que|como|cual|cuales|cuanto|cuanta|cuando|donde|por que|porque|se puede|puedo|es cierto)\b", t))
                   or any(re.search(rf"\b{re.escape(w)}\b", t) for w in PAL_PREGUNTA))
    quiere_fijas = any(re.search(rf"\b{re.escape(w)}\b", t) for w in PAL_FIJAS)
    if reglas and es_pregunta and not re.search(r"\b(dame|recomienda|recomiendame|quiero|arma|armame)\b", t):
        return [{"tipo": "regla", "regla": r} for r in reglas]

    if re.search(r"champions|europa league|conference|libertadores|sudamericana|seleccion|eliminatoria|mundial|copa del rey|fa cup|liga 1|peru", t) and not detectar_equipos(t):
        return [_texto("La fuente de datos gratuita no trae **Champions, Europa/Conference League, copas, selecciones "
                       "ni la Liga 1 de Perú**, así que no puedo proponer fijas de esas competiciones por mi cuenta. "
                       "Sí puedo **revisarlas**: ve a **🔍 Verificar**, elige «Otra competición», escribe los equipos y "
                       "copia las cuotas 1X2 y Más/Menos 2.5 de Betano. Con eso calculo todos los mercados del partido.")]

    if any(w in t for w in PAL_HISTORIAL):
        return [{"tipo": "historial"}]

    equipos = detectar_equipos(t)
    if equipos:
        if re.search(r"revisa|verifica|es buena|vale la pena|conviene|la juego|\d[.,]\d", t):
            v = verificar(equipos, t)
            if v:
                return v
        if (any(w in t for w in PAL_ANALIZAR) or not quiere_fijas or len(equipos) >= 2
                or re.search(r"\b(del|de|para el|para)\b", t)):
            return analizar_partido(equipos, t, ctx)

    seguimiento = ctx.ultima_peticion is not None and re.fullmatch(
        r"(y )?(mas segur\w*|menos riesgo|mas arriesgad\w*|mas cuota|otra( opcion)?|otra mas|cambia\w*.*|con \d+.*|"
        r"s/ ?\d+.*|\d+ (soles|partidos|fijas|selecciones).*|de \d+.*|para manana|para hoy|y (para )?manana\??|y (para )?hoy\??|"
        r"solo .*|sin .*|que pague .*|cuota .*|ultra.*|equilibrad.*)", t)
    if seguimiento:
        base = ctx.ultima_peticion
        p = leer_peticion(t, base)
        if re.search(r"mas segur|menos riesgo", t):
            # más segura = menos cuota total o una selección menos
            p.perfil = {"arriesgada": "equilibrada", "equilibrada": "segura", "segura": "ultra", "ultra": "ultra"}[base.perfil]
            if base.cuota_objetivo:
                p.cuota_objetivo = round(base.cuota_objetivo * 0.7, 2) if base.cuota_objetivo * 0.7 >= 1.5 else None
            elif (base.n or 3) > 1:
                p.n = (base.n or 3) - 1
        if re.search(r"mas arriesgad|mas cuota", t):
            p.perfil = {"ultra": "segura", "segura": "equilibrada", "equilibrada": "arriesgada", "arriesgada": "arriesgada"}[base.perfil]
            if base.cuota_objetivo:
                p.cuota_objetivo = round(base.cuota_objetivo * 1.5, 2)
            else:
                p.n = (base.n or 3) + 1
        return generar_fijas(p, ctx)

    if quiere_fijas or re.search(r"\b(hoy|manana|finde|fin de semana|sabado|domingo)\b", t):
        return generar_fijas(leer_peticion(t), ctx)

    if reglas:
        return [{"tipo": "regla", "regla": r} for r in reglas]

    return [_texto("No te entendí del todo 🤔. Puedo darte fijas y combinadas, analizar un partido, revisar una fija "
                   "con su cuota o explicarte reglas de Betano. Prueba con alguna de estas:"),
            {"tipo": "sugerencias", "lista": SUGERENCIAS}]
