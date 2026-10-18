"""Todo lo específico de Betano Perú: reglas oficiales, promociones y cuotas estimadas.

Las reglas salen del centro de ayuda oficial (conocimiento/betano_reglas.json, con URL y fecha).
Las cuotas de Betano NO se descargan (su reglamento lo prohíbe y no hay API pública):
* para 1X2 y Más/Menos 2.5 se usa el promedio de casas como referencia;
* para el resto se ESTIMA con la probabilidad del mercado más un margen típico.
El usuario siempre puede reemplazarlas por la cuota real que ve en la app.
"""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache

import numpy as np
import pandas as pd

from . import config as C

RUTA_KB = C.RAIZ / "conocimiento" / "betano_reglas.json"
APUESTA_MINIMA = 0.50          # S/ (centro de ayuda, «¿Existe un monto mínimo?»)
BET_BUILDER_MAX_PATAS = 13     # fútbol: de 2 a 13 mercados del mismo partido

# Multi Bono (fútbol): % sobre las ganancias según n.º de selecciones (cuota mínima 1.50 c/u)
MULTI_BONO_FUTBOL = {2: 0, 3: 5, 4: 10, 5: 15, 6: 20, 7: 25, 8: 30, 9: 35, 10: 40, 11: 45, 12: 50,
                     13: 60, 14: 70, 15: 75, 16: 80, 17: 85, 18: 90, 19: 95, 20: 100, 21: 115, 22: 130,
                     23: 150, 24: 175}
MULTI_BONO_CUOTA_MIN = 1.50
MULTI_BONO_LIGAS = {"E0", "E1", "E2", "E3", "SP1", "SP2", "I1", "I2", "D1", "D2", "F1", "F2", "P1", "N1",
                    "BRA", "MEX", "USA", C.OTRA_COMPETICION}  # OTRA: Champions/Europa/Conference sí; verificar
MULTI_BONO_MERCADOS = {"1x2", "goles", "btts", "btts_o25", "marcador", "1t_1x2", "1t_goles"}
SEGURO_MIN_SEL, SEGURO_MAX_SEL, SEGURO_CUOTA_MIN = 5, 20, 1.65
SEGURO_MERCADOS = {"1x2", "goles", "btts"}


def normalizar(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


# --- base de conocimiento -------------------------------------------------------------

@lru_cache(maxsize=1)
def base_conocimiento() -> dict:
    return json.loads(RUTA_KB.read_text(encoding="utf-8"))


def buscar_regla(texto: str, n: int = 2) -> list[dict]:
    """Reglas cuyo tema aparece en el texto (ordenadas por coincidencia)."""
    t = normalizar(texto)
    puntajes = []
    for r in base_conocimiento()["reglas"]:
        p = 0
        for k in r["claves"]:
            k = normalizar(k)
            if re.search(r"(?<!\w)" + re.escape(k), t):
                p += len(k)
        if p:
            puntajes.append((p, r))
    puntajes.sort(key=lambda x: -x[0])
    return [r for _, r in puntajes[:n]]


# --- promociones ------------------------------------------------------------------------

def multi_bono(grupos, cuotas: list[float | None]) -> dict:
    """¿La combinada califica para Multi Bono? Devuelve % y motivo."""
    n = len(grupos)
    if n < 3:
        return {"aplica": False, "porcentaje": 0, "motivo": "El Multi Bono en fútbol empieza en triples."}
    if any(len(g.selecciones) > 1 for g in grupos):
        return {"aplica": False, "porcentaje": 0, "motivo": "Lleva Bet Builder: no está entre los mercados del Multi Bono."}
    bajas = [c for c in cuotas if not c or c < MULTI_BONO_CUOTA_MIN]
    if bajas:
        return {"aplica": False, "porcentaje": 0,
                "motivo": f"Para el Multi Bono cada selección debe pagar 1.50 o más ({len(bajas)} no llegan)."}
    if any(g.selecciones[0].mercado not in MULTI_BONO_MERCADOS for g in grupos):
        return {"aplica": False, "porcentaje": 0, "motivo": "Algún mercado no participa (p. ej. Doble oportunidad o córners)."}
    if any(g.liga not in MULTI_BONO_LIGAS for g in grupos):
        return {"aplica": False, "porcentaje": 0, "motivo": "Alguna liga no está en la lista del Multi Bono."}
    pct = MULTI_BONO_FUTBOL.get(n, 200 if n >= 25 else 0)
    return {"aplica": True, "porcentaje": pct,
            "motivo": f"Califica para Multi Bono: +{pct} % sobre las ganancias si acierta (verifica el banner del cupón)."}


def seguro_betano(grupos, cuotas: list[float | None]) -> dict:
    n = len(grupos)
    ok = (SEGURO_MIN_SEL <= n <= SEGURO_MAX_SEL and all(c and c >= SEGURO_CUOTA_MIN for c in cuotas)
          and all(len(g.selecciones) == 1 and g.selecciones[0].mercado in SEGURO_MERCADOS for g in grupos))
    return {"aplica": ok, "motivo": ("Podría tener Seguro Betano: si falla una sola, te devuelven lo apostado."
                                     if ok else "Sin Seguro Betano (pide 5–20 selecciones de 1X2/goles/ambos anotan a cuota ≥ 1.65).")}


def prob_pago_anticipado(lam: float, mu: float, lado: str = "local", pasos: int = 180) -> tuple[float, float]:
    """(P(ganar), P(ganar o ir 2 goles arriba en algún momento)) con goles como procesos de Poisson."""
    K = 12
    d = np.zeros(2 * K + 1)
    d[K] = 1.0
    ph, pa = lam / pasos, mu / pasos
    pagado = 0.0
    signo = 1 if lado == "local" else -1
    meta = K + 2 * signo
    for _ in range(pasos):
        nuevo = d * (1 - ph - pa)
        nuevo[1:] += d[:-1] * ph   # gol local: diferencia +1
        nuevo[:-1] += d[1:] * pa   # gol visitante: diferencia −1
        pagado += nuevo[meta]
        nuevo[meta] = 0.0
        d = nuevo
    idx = np.arange(2 * K + 1) - K
    gana = d[idx * signo > 0].sum()
    # P(ganar) sin oferta: los que ya cobraron por la oferta pueden terminar ganando, empatando o perdiendo;
    # se calcula aparte con la distribución final de Poisson.
    k = np.arange(15)
    from scipy.stats import poisson
    M = np.outer(poisson.pmf(k, lam), poisson.pmf(k, mu))
    H, A = np.meshgrid(k, k, indexing="ij")
    p_gana = float(M[(H > A) if lado == "local" else (H < A)].sum())
    return p_gana, float(pagado + gana)


# --- cuotas estimadas -----------------------------------------------------------------

@lru_cache(maxsize=4)
def _margenes(_firma: str) -> dict:
    from . import datos
    px = datos.cargar_proximos()
    m3 = m2 = None
    if not px.empty:
        s3 = (1 / px["c_1"] + 1 / px["c_x"] + 1 / px["c_2"]).dropna()
        s2 = (1 / px["c_o25"] + 1 / px["c_u25"]).dropna()
        m3 = float(s3.median() - 1) if len(s3) else None
        m2 = float(s2.median() - 1) if len(s2) else None
    return {"tres_vias": m3 if m3 and 0 < m3 < 0.15 else 0.055, "dos_vias": m2 if m2 and 0 < m2 < 0.15 else 0.06}


def margenes() -> dict:
    from . import datos
    ruta = datos.ultimo_snapshot("proximos")
    return _margenes(ruta.name if ruta else "")


def cuota_estimada(p_justa: float | None, mercado: str, n_patas: int = 1) -> float | None:
    """Cuota parecida a la de una casa: probabilidad justa + margen típico (más alto en Bet Builder)."""
    if not p_justa or p_justa <= 0:
        return None
    m = margenes()
    base = m["tres_vias"] if mercado in ("1x2", "marcador", "1t_1x2") else m["dos_vias"]
    if n_patas > 1:  # los Bet Builder llevan más margen: se suma uno por pata extra (estimación)
        base = base + 0.03 * (n_patas - 1)
    return max(1.01, round(1 / (p_justa * (1 + base)), 2))


def cuota_referencia(fila_proximo, s) -> float | None:
    """Cuota promedio de casas para 1X2 y Más/Menos 2.5 (si la fuente la trae)."""
    if fila_proximo is None:
        return None
    col = None
    if s.mercado == "1x2":
        col = {"local": "c_1", "empate": "c_x", "visitante": "c_2"}[s.opcion]
    elif s.mercado == "goles" and s.linea == 2.5:
        col = "c_o25" if s.opcion == "mas" else "c_u25"
    if col is None:
        return None
    v = fila_proximo.get(col)
    return float(v) if v is not None and pd.notna(v) else None
