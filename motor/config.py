"""Configuración central del bot: rutas, ligas, fuentes y parámetros del modelo."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_DATOS = RAIZ / "datos"
DIR_RAW = DIR_DATOS / "raw"
DIR_MODELOS = DIR_DATOS / "modelos"
DIR_EVALUACION = DIR_DATOS / "evaluacion"
DIR_INFORMES = RAIZ / "informes"
DB_PATH = DIR_DATOS / "registro.sqlite"
LOG_DESCARGAS = DIR_DATOS / "registro_descargas.csv"

URL_BASE = "https://www.football-data.co.uk"
FUENTE_NOMBRE = "football-data.co.uk"
TEMPORADAS = ["2425", "2526", "2627"]
TEMPORADA_ACTUAL = "2627"
ZONA_HORARIA = "America/Lima"  # las horas de los partidos se muestran en hora de Perú

# Ligas con resultados, xG (desde 2026/27), remates, córners, tarjetas, árbitro y cuotas.
LIGAS_EUROPA = {
    "E0": "Inglaterra - Premier League",
    "E1": "Inglaterra - Championship",
    "E2": "Inglaterra - League One",
    "E3": "Inglaterra - League Two",
    "SP1": "España - LaLiga",
    "SP2": "España - LaLiga 2",
    "D1": "Alemania - Bundesliga",
    "D2": "Alemania - 2. Bundesliga",
    "I1": "Italia - Serie A",
    "I2": "Italia - Serie B",
    "F1": "Francia - Ligue 1",
    "F2": "Francia - Ligue 2",
    "N1": "Países Bajos - Eredivisie",
    "B1": "Bélgica - Pro League",
    "P1": "Portugal - Primeira Liga",
    "T1": "Turquía - Süper Lig",
    "G1": "Grecia - Super League",
    "SC0": "Escocia - Premiership",
    "SC1": "Escocia - Championship",
    "SC2": "Escocia - League One",
    "SC3": "Escocia - League Two",
}

# Ligas con solo resultados y cuotas de cierre (sin medio tiempo, córners ni tarjetas).
LIGAS_EXTRA = {
    "BRA": "Brasil - Série A",
    "ARG": "Argentina - Liga Profesional",
    "MEX": "México - Liga MX",
    "USA": "EE.UU. - MLS",
    "AUT": "Austria - Bundesliga",
    "SWZ": "Suiza - Super League",
    "DNK": "Dinamarca - Superliga",
    "POL": "Polonia - Ekstraklasa",
    "NOR": "Noruega - Eliteserien",
    "SWE": "Suecia - Allsvenskan",
}

LIGAS = {**LIGAS_EUROPA, **LIGAS_EXTRA}
OTRA_COMPETICION = "OTRA"  # Champions, Europa League, selecciones, etc.: solo modelo de mercado

# --- Parámetros del modelo (versión 1) ---
VERSION_MODELO = "dc-v1"
XI = 0.0019            # decaimiento temporal por día (vida media ≈ 1 año)
RIDGE = 2.0            # penalización que encoge a los equipos con pocos datos hacia la media
# Córners y tarjetas: con poco encogimiento (4) el modelo era demasiado seguro en los extremos
# (backtest 2025/26: decía 79 % y pasaba 69 %). 50 dio el mejor log-loss y calibración.
RIDGE_CONTEOS = 50.0
# Peso del xG frente a los goles reales. Prueba en 2026/27 (477 partidos, evidencia preliminar):
# log-loss 0.5736 (sin xG) / 0.5716 (0.3) / 0.5704 (0.6). Revalidar cuando haya más jornadas.
PESO_XG = 0.5
VENTANA_DIAS = 3 * 365
MAX_GOLES = 10
MAX_GOLES_MITAD = 7
RHO_MERCADO = -0.06    # corrección Dixon-Coles por defecto para el modelo de mercado
FRACCION_1T = 0.44     # parte de los goles que ocurre en el 1.er tiempo (se recalcula con datos)

# Peso del modelo estadístico frente al mercado al combinar probabilidades.
# Se sobrescribe con el valor estimado en el backtest (datos/evaluacion/resumen.json).
PESO_MODELO_DEFECTO = 0.3

UMBRAL_VALOR = 0.03       # ±3 % de valor esperado para decir "con valor" / "mal pagada"
UMBRAL_DISCREPANCIA = 0.08  # diferencia modelo vs mercado que obliga a revisar noticias

# --- Jugadores: tiros al arco (motor/jugadores.py y motor/modelo_jugadores.py) ---
DIR_JUGADORES = DIR_DATOS / "jugadores"
ENV_PATH = RAIZ / ".env"          # archivo PRIVADO con APIFOOTBALL_KEY=... (nunca se comparte)
APIFOOTBALL_URL = "https://v3.football.api-sports.io"
APIFOOTBALL_LIMITE_DIARIO = 100   # plan gratuito
APIFOOTBALL_RESERVA = 5           # consultas que se dejan libres cada día
APIFOOTBALL_PAUSA = 7.0           # segundos entre consultas (el plan gratuito limita por minuto)
UNDERSTAT_URL = "https://understat.com"
UNDERSTAT_PAUSA = 0.5            # ~1,3 consultas por segundo con conexión reutilizada
# Fuente de datos de jugadores: "auto" usa API-Football si la clave y el plan cubren las temporadas
# y si no Understat (gratis, sin clave, 5 grandes ligas). También "apifootball" o "understat".
FUENTE_JUGADORES = "auto"
# Betano no publica líneas de jugador que pagarían casi nada: el 18/10/2026 el usuario vio a Mbappé con
# "tiros al arco" solo desde 2+. Si la prob. de 1+ supera este valor y no hay captura que diga lo contrario,
# se propone 2+. No cambia ninguna probabilidad (es disponibilidad de mercado); lo aprendido de capturas manda.
JUG_ARCO_1_OCULTA = 0.80
RUTA_LINEAS_BETANO = RAIZ / "conocimiento" / "betano_lineas.json"  # líneas vistas en capturas del usuario

LIGAS_JUGADORES = {  # código football-data -> id en cada fuente
    "E0": {"apifootball": 39, "understat": "EPL"},
    "SP1": {"apifootball": 140, "understat": "La_liga"},
    "I1": {"apifootball": 135, "understat": "Serie_A"},
    "D1": {"apifootball": 78, "understat": "Bundesliga"},
    "F1": {"apifootball": 61, "understat": "Ligue_1"},
}
TEMPORADAS_JUGADORES = [2024, 2025, 2026]  # año de inicio: 2025 = 2025/26
TEMPORADA_BACKTEST_JUGADORES = 2025
VENTANA_DIAS_JUGADORES = 2 * 365
# Parámetros del modelo de jugadores. Se sobrescriben con los elegidos en el backtest
# (datos/evaluacion/resumen_jugadores.json); estos son solo el punto de partida.
# Backtest 18/10/2026 (Understat, 5 ligas; elegidos en ago–dic 2025, validados en ene–jun 2026 con 18.974
# titulares): κ=12, ξ=0.002, β=1, ritmo propio de suplente, binomial negativa. Log-loss titulares 0,2566 vs
# 0,2582 sin rival, 0,2662 solo posición y 0,2869 tasa cruda. «1+ titular»: 27,2 % estimado vs 26,8 % real.
JUG_KAPPA = 12.0       # fuerza del prior de su posición, en partidos de 90'
JUG_XI = 0.002         # decaimiento temporal por día de las apariciones pasadas
JUG_BETA_RIVAL = 1.0   # cuánto pesa la defensa rival (0 = nada, 1 = completo)

for _d in (DIR_DATOS, DIR_RAW, DIR_MODELOS, DIR_EVALUACION, DIR_INFORMES, DIR_JUGADORES):
    _d.mkdir(parents=True, exist_ok=True)
