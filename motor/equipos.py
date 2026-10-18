"""Nombres completos, escudos y enlaces de Betano.

* football-data.co.uk abrevia los nombres ("Nott'm Forest", "Ath Madrid", "M'gladbach"…): aquí se traducen al
  nombre completo, usando una tabla propia y el nombre oficial de TheSportsDB.
* Los escudos se bajan UNA vez de TheSportsDB (API gratuita) y se guardan en datos/escudos/ (funcionan sin internet).
* Betano no permite enlaces que carguen una apuesta (no hay API pública y sus códigos de evento son internos);
  se enlaza a la página PÚBLICA de la liga en Betano, donde está el partido.
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import unicodedata

from . import config as C

DIR_ESCUDOS = C.DIR_DATOS / "escudos"
DIR_ESCUDOS.mkdir(parents=True, exist_ok=True)
INDICE = DIR_ESCUDOS / "equipos.json"
TSDB = "https://www.thesportsdb.com/api/v1/json/123/searchteams.php"

BETANO = "https://www.betano.pe"
BETANO_LIGAS = {  # páginas públicas de cada liga (menú de https://www.betano.pe/sport/futbol/, 18/10/2026)
    "E0": "/sport/futbol/inglaterra/premier-league/1/", "E1": "/sport/futbol/inglaterra/championship/2/",
    "E2": "/sport/futbol/inglaterra/league-one/527/", "E3": "/sport/futbol/inglaterra/league-two/4/",
    "SP1": "/sport/futbol/espana/laliga/5/", "SP2": "/sport/futbol/espana/segunda-division/10000/",
    "D1": "/sport/futbol/alemania/bundesliga/216/", "D2": "/sport/futbol/alemania/2-bundesliga/217/",
    "I1": "/sport/futbol/italia/serie-a/1635/", "I2": "/sport/futbol/italia/serie-b/10210/",
    "F1": "/sport/futbol/francia/ligue-1/215/", "F2": "/sport/futbol/francia/ligue-2/10467/",
    "N1": "/sport/futbol/paises-bajos/eredivisie/17067/", "B1": "/sport/futbol/belgica/1a-pro-league/16849/",
    "P1": "/sport/futbol/portugal/primeira-liga/17083/", "T1": "/sport/futbol/turquia/super-lig/17093/",
    "G1": "/sport/futbol/grecia/super-league-1/1636/", "SC0": "/sport/futbol/escocia/premiership/1647/",
    "SC1": "/sport/futbol/escocia/championship/1630/", "SC2": "/sport/futbol/escocia/league-one/1672/",
    "SC3": "/sport/futbol/escocia/league-two/1673/", "BRA": "/sport/futbol/brasil/brasileirao-serie-a/10016/",
    "ARG": "/sport/futbol/argentina/liga-profesional/195785/", "MEX": "/sport/futbol/mexico/liga-mx/17264/",
    "USA": "/sport/futbol/ee-uu/mls/17103/", "AUT": "/sport/futbol/austria/bundesliga/16823/",
    "SWZ": "/sport/futbol/suiza/superliga/17122/", "DNK": "/sport/futbol/dinamarca/superligaen/16955/",
    "POL": "/sport/futbol/polonia/ekstraklasa/17080/", "NOR": "/sport/futbol/noruega/eliteserien/17074/",
    "SWE": "/sport/futbol/suecia/allsvenskan/17118/",
}

# Abreviaturas de football-data -> nombre completo (lo que se ve en Betano)
COMPLETO = {
    "Man City": "Manchester City", "Man United": "Manchester United", "Nott'm Forest": "Nottingham Forest",
    "Wolves": "Wolverhampton", "West Brom": "West Bromwich Albion", "Sheffield Weds": "Sheffield Wednesday",
    "Sheffield United": "Sheffield United", "QPR": "Queens Park Rangers", "Hull": "Hull City", "Ipswich": "Ipswich Town",
    "Leicester": "Leicester City", "Leeds": "Leeds United", "Norwich": "Norwich City", "Stoke": "Stoke City",
    "Swansea": "Swansea City", "Cardiff": "Cardiff City", "Coventry": "Coventry City", "Derby": "Derby County",
    "Luton": "Luton Town", "Newcastle": "Newcastle United", "Tottenham": "Tottenham Hotspur", "West Ham": "West Ham United",
    "Brighton": "Brighton & Hove Albion", "Bournemouth": "AFC Bournemouth", "Oxford": "Oxford United",
    "Plymouth": "Plymouth Argyle", "Preston": "Preston North End", "Blackburn": "Blackburn Rovers", "Bristol City": "Bristol City",
    "Ath Madrid": "Atlético Madrid", "Ath Bilbao": "Athletic Club", "Sociedad": "Real Sociedad", "Vallecano": "Rayo Vallecano",
    "Espanol": "Espanyol", "La Coruna": "Deportivo La Coruña", "Santander": "Racing Santander", "Betis": "Real Betis",
    "Celta": "Celta de Vigo", "Alaves": "Alavés", "Malaga": "Málaga", "Leganes": "Leganés", "Almeria": "Almería",
    "Cadiz": "Cádiz", "Sp Gijon": "Sporting Gijón", "Valladolid": "Real Valladolid", "Oviedo": "Real Oviedo",
    "Zaragoza": "Real Zaragoza", "Cordoba": "Córdoba", "Mirandes": "Mirandés", "Castellon": "Castellón",
    "M'gladbach": "Borussia Mönchengladbach", "Ein Frankfurt": "Eintracht Frankfurt", "FC Koln": "1. FC Köln",
    "Bayern Munich": "Bayern Múnich", "Dortmund": "Borussia Dortmund", "Leverkusen": "Bayer Leverkusen",
    "RB Leipzig": "RB Leipzig", "Werder Bremen": "Werder Bremen", "Mainz": "Mainz 05", "Hoffenheim": "Hoffenheim",
    "Hamburg": "Hamburgo", "St Pauli": "St. Pauli", "Schalke 04": "Schalke 04", "Fortuna Dusseldorf": "Fortuna Düsseldorf",
    "Nurnberg": "Núremberg", "Greuther Furth": "Greuther Fürth", "Paderborn": "Paderborn 07",
    "Inter": "Inter de Milán", "Milan": "AC Milan", "Roma": "AS Roma", "Napoli": "Nápoles", "Verona": "Hellas Verona",
    "Paris SG": "Paris Saint-Germain", "Marseille": "Olympique de Marsella", "Lyon": "Olympique de Lyon", "Monaco": "AS Mónaco",
    "Nice": "Niza", "St Etienne": "Saint-Étienne", "Paris FC": "Paris FC",
    "Sp Lisbon": "Sporting CP", "Sp Braga": "Sporting Braga", "Guimaraes": "Vitória Guimarães", "Famalicao": "Famalicão",
    "Academico Viseu": "Académico de Viseu", "Maritimo": "Marítimo",
    "PSV Eindhoven": "PSV", "AZ Alkmaar": "AZ Alkmaar", "For Sittard": "Fortuna Sittard", "Nijmegen": "NEC Nijmegen",
    "Den Haag": "ADO Den Haag", "Sparta Rotterdam": "Sparta Rotterdam", "Go Ahead Eagles": "Go Ahead Eagles",
    "Buyuksehyr": "İstanbul Başakşehir", "Goztep": "Göztepe", "Karagumruk": "Fatih Karagümrük", "Fenerbahce": "Fenerbahçe",
    "Besiktas": "Beşiktaş", "Kasimpasa": "Kasımpaşa", "Eyupspor": "Eyüpspor", "Genclerbirligi": "Gençlerbirliği",
    "Corum": "Çorum FK", "Amedspor": "Amed SK",
    "Flamengo RJ": "Flamengo", "Botafogo RJ": "Botafogo", "Atletico-MG": "Atlético Mineiro",
    "Athletico-PR": "Athletico Paranaense", "Chapecoense-SC": "Chapecoense", "Sao Paulo": "São Paulo", "Gremio": "Grêmio",
    "Vitoria": "Vitória", "Vasco": "Vasco da Gama", "Bragantino": "Red Bull Bragantino",
    "Estudiantes L.P.": "Estudiantes de La Plata", "Gimnasia L.P.": "Gimnasia La Plata", "Newells Old Boys": "Newell's Old Boys",
    "Atl. Tucuman": "Atlético Tucumán", "Dep. Riestra": "Deportivo Riestra", "Ind. Rivadavia": "Independiente Rivadavia",
    "Velez Sarsfield": "Vélez Sarsfield", "Talleres Cordoba": "Talleres de Córdoba", "Huracan": "Huracán", "Lanus": "Lanús",
    "Club America": "América", "Guadalajara Chivas": "Chivas", "UNAM Pumas": "Pumas UNAM", "Atl. San Luis": "Atlético San Luis",
    "Club Leon": "León", "Club Tijuana": "Tijuana", "Queretaro": "Querétaro", "Mazatlan FC": "Mazatlán", "Juarez": "FC Juárez",
    "Los Angeles FC": "LAFC", "Los Angeles Galaxy": "LA Galaxy", "New York City": "New York City FC",
}

_lock = threading.Lock()
_indice: dict | None = None


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t).lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in t if not unicodedata.combining(c))).strip()


def indice() -> dict:
    global _indice
    if _indice is None:
        try:
            _indice = json.loads(INDICE.read_text(encoding="utf-8"))
        except Exception:
            _indice = {}
    return _indice


def nombre(equipo: str) -> str:
    """Nombre completo para mostrar (lo que verás en Betano)."""
    if not equipo:
        return equipo
    return COMPLETO.get(equipo) or indice().get(equipo, {}).get("nombre") or equipo


def enlace_liga(liga: str) -> str:
    return BETANO + BETANO_LIGAS.get(liga, "/sport/futbol/proximos-partidos-hoy/")


def escudo_uri(equipo: str) -> str | None:
    """Escudo como data URI (sirve sin internet y dentro de cualquier HTML)."""
    d = indice().get(equipo)
    if not d or not d.get("archivo"):
        return None
    ruta = DIR_ESCUDOS / d["archivo"]
    if not ruta.exists():
        return None
    return "data:image/png;base64," + base64.b64encode(ruta.read_bytes()).decode()


def _buscar(equipo: str) -> dict | None:
    import requests
    completo = COMPLETO.get(equipo, equipo)
    candidatos = []
    for q in dict.fromkeys([completo, equipo, re.sub(r"\b(FC|CF|AFC|SC|CD)\b", "", completo).strip()]):
        try:
            r = requests.get(TSDB, params={"t": q}, timeout=20)
            candidatos += [t for t in (r.json().get("teams") or []) if t.get("strSport") == "Soccer"]
        except Exception:
            pass
        time.sleep(2.5)  # la API gratuita limita las consultas por minuto
        if candidatos:
            break
    if not candidatos:
        return None
    objetivo = {_norm(completo), _norm(equipo)}

    def puntaje(t):
        nombres = {_norm(t.get("strTeam", ""))} | {_norm(x) for x in (t.get("strTeamAlternate") or "").split(",") if x.strip()}
        return (len(objetivo & nombres) > 0, -abs(len(_norm(t.get("strTeam", ""))) - len(_norm(completo))))
    return max(candidatos, key=puntaje)


def _wiki_escudo(nombre_completo: str) -> bytes | None:
    """Escudo desde Wikipedia (imagen principal del artículo del club), sin clave."""
    import requests
    cab = {"User-Agent": "FutBot/1.0 (bot personal de analisis; uso privado)"}
    for consulta in (f"{nombre_completo} football club", f"{nombre_completo} fútbol club"):
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php", headers=cab, timeout=20, params={
                "action": "query", "format": "json", "generator": "search", "gsrsearch": consulta, "gsrlimit": 1,
                "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 64, "pilicense": "any"})
            paginas = (r.json().get("query") or {}).get("pages") or {}
            for p in paginas.values():
                url = (p.get("thumbnail") or {}).get("source")
                if url:
                    img = requests.get(url, headers=cab, timeout=20)
                    if img.ok and img.content[:4] == b"\x89PNG":
                        return img.content
        except Exception:
            pass
        time.sleep(0.5)
    return None


def resolver(equipos: list[str], progreso=None) -> int:
    """Busca nombre oficial y escudo de los equipos que falten (queda guardado; los fallidos se reintentan al día)."""
    import requests
    try:
        import truststore
        truststore.inject_into_ssl()
    except Exception:
        pass
    idx = indice()
    nuevos = 0
    ahora = time.time()
    pendientes = [e for e in dict.fromkeys(equipos) if e and (e not in idx or (
        not idx[e].get("archivo") and ahora - idx[e].get("intento", 0) > 86400))]
    for i, eq in enumerate(pendientes):
        if progreso:
            progreso(i / max(len(pendientes), 1), eq)
        t = _buscar(eq)
        dato = {"nombre": COMPLETO.get(eq) or (t or {}).get("strTeam") or eq, "intento": ahora}
        contenido = None
        if t and t.get("strBadge"):
            try:
                img = requests.get(t["strBadge"] + "/tiny", timeout=20)
                if img.ok and img.content[:4] == b"\x89PNG":
                    contenido = img.content
            except Exception:
                pass
        if contenido is None:  # TheSportsDB no lo tenía (o limitó las consultas): Wikipedia
            contenido = _wiki_escudo(dato["nombre"])
        if contenido:
            archivo = re.sub(r"[^a-z0-9]+", "_", _norm(eq)) + ".png"
            (DIR_ESCUDOS / archivo).write_bytes(contenido)
            dato["archivo"] = archivo
        with _lock:
            idx[eq] = dato
            INDICE.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
        nuevos += 1
    return nuevos


_hilo = {"corriendo": False}


def resolver_en_fondo() -> None:
    """Resuelve en segundo plano los equipos de los próximos partidos."""
    if _hilo["corriendo"]:
        return
    from . import datos
    px = datos.cargar_proximos()
    faltan = [e for e in list(px.get("local", [])) + list(px.get("visitante", [])) if e not in indice()]
    if not faltan:
        return
    _hilo["corriendo"] = True

    def tarea():
        try:
            resolver(faltan)
        finally:
            _hilo["corriendo"] = False
    threading.Thread(target=tarea, daemon=True).start()
