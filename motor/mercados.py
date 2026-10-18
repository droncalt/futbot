"""Mercados con los nombres que usa Betano y cálculo de probabilidades.

Un partido se representa con distribuciones conjuntas:
* goles: matriz (local, visitante) del partido completo y, si una pata lo pide,
  una distribución 4D (1T local, 1T visitante, 2T local, 2T visitante);
* córners y tarjetas: matriz (local, visitante) independiente de los goles.

Las patas de un mismo Bet Builder se evalúan sobre la MISMA distribución: así se
respeta la correlación entre, por ejemplo, "Barcelona gana" y "Más de 2.5".
Entre familias distintas (goles × córners × tarjetas) se asume independencia y se avisa.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
from scipy.optimize import least_squares
from scipy.stats import poisson

from . import config as C
from .modelo import ModeloLiga, matriz_dc, puntos_tarjetas

LINEAS_GOLES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]

MERCADOS: dict[str, dict] = {
    "1x2": {"nombre": "Resultado del partido", "opciones": ["local", "empate", "visitante"], "familia": "goles"},
    "doble": {"nombre": "Doble oportunidad", "opciones": ["1X", "X2", "12"], "familia": "goles"},
    "goles": {"nombre": "Goles totales Más/Menos", "opciones": ["mas", "menos"], "lineas": LINEAS_GOLES, "familia": "goles"},
    "btts": {"nombre": "Ambos equipos anotan", "opciones": ["si", "no"], "familia": "goles"},
    "btts_o25": {"nombre": "Ambos equipos anotan o Más de 2.5", "opciones": ["si", "no"], "familia": "goles"},
    "goles_local": {"nombre": "{local} - Goles totales Más/Menos", "opciones": ["mas", "menos"], "lineas": [0.5, 1.5, 2.5, 3.5], "familia": "goles"},
    "goles_visitante": {"nombre": "{visitante} - Goles totales Más/Menos", "opciones": ["mas", "menos"], "lineas": [0.5, 1.5, 2.5, 3.5], "familia": "goles"},
    "marcador": {"nombre": "Marcador correcto", "opciones": [f"{i}-{j}" for i in range(6) for j in range(6)], "familia": "goles"},
    "1t_1x2": {"nombre": "Resultado Primer Tiempo", "opciones": ["local", "empate", "visitante"], "familia": "mitades"},
    "1t_goles": {"nombre": "Más/Menos Goles en Primer Tiempo", "opciones": ["mas", "menos"], "lineas": [0.5, 1.5, 2.5], "familia": "mitades"},
    "2t_goles": {"nombre": "Más/Menos Goles en Segundo Tiempo", "opciones": ["mas", "menos"], "lineas": [0.5, 1.5, 2.5], "familia": "mitades"},
    "corners": {"nombre": "Más/Menos Córners", "opciones": ["mas", "menos"], "lineas": [6.5, 7.5, 8.5, 9.5, 10.5, 11.5, 12.5], "familia": "corners"},
    "corners_local": {"nombre": "{local} Más/Menos Córners", "opciones": ["mas", "menos"], "lineas": [2.5, 3.5, 4.5, 5.5, 6.5, 7.5], "familia": "corners"},
    "corners_visitante": {"nombre": "{visitante} Más/Menos Córners", "opciones": ["mas", "menos"], "lineas": [2.5, 3.5, 4.5, 5.5, 6.5, 7.5], "familia": "corners"},
    "tarjetas": {"nombre": "Tarjetas Totales Más/Menos", "opciones": ["mas", "menos"], "lineas": [1.5, 2.5, 3.5, 4.5, 5.5, 6.5], "familia": "tarjetas"},
    # Mercado de jugador: en la boleta sale «1+» y debajo «<Jugador> Tiros al Arco» (motor/modelo_jugadores.py)
    # solo las líneas con backtest (1+, 2+, 3+)
    "jug_arco": {"nombre": "Jugador - Tiros al Arco", "opciones": ["1+", "2+", "3+"], "familia": "jugadores"},
}

NO_SOPORTADOS = (
    "Goleadores, córners del 1.er tiempo y hándicaps todavía no tienen datos fiables gratuitos: el bot no los "
    "calcula. Tiros al arco de jugadores: solo 5 grandes ligas y siempre según la alineación."
)


@dataclass
class Seleccion:
    mercado: str
    opcion: str
    linea: float | None = None
    # solo para mercados de jugador (jug_arco)
    jugador: str | None = None          # id en la fuente de datos, ej. "us8260"
    jugador_nombre: str | None = None
    lado: str | None = None             # "local" o "visitante": equipo del jugador en este partido
    escenario: str | None = None        # "sin_confirmar", "titular" o "suplente"

    @property
    def es_jugador(self) -> bool:
        return MERCADOS[self.mercado]["familia"] == "jugadores"

    def etiqueta(self, local: str, visitante: str) -> tuple[str, str]:
        """(texto en negrita, texto gris) tal como aparecen en la boleta de Betano."""
        m = MERCADOS[self.mercado]
        if self.es_jugador:
            return self.opcion, f"{self.jugador_nombre or 'Jugador'} Tiros al Arco"
        from .equipos import nombre  # nombres completos (no las abreviaturas de la fuente)
        local, visitante = nombre(local), nombre(visitante)
        sub = m["nombre"].format(local=local, visitante=visitante)
        o = self.opcion
        if self.mercado in ("1x2", "1t_1x2"):
            tit = {"local": local, "visitante": visitante, "empate": "Empate"}[o]
        elif self.mercado == "doble":
            tit = {"1X": f"{local} o Empate", "X2": f"{visitante} o Empate", "12": f"{local} o {visitante}"}[o]
        elif self.mercado in ("btts", "btts_o25"):
            tit = "Sí" if o == "si" else "No"
        elif self.mercado == "marcador":
            tit = o
        else:
            tit = f"{'Más' if o == 'mas' else 'Menos'} de {self.linea}"
        return tit, sub

    def to_dict(self) -> dict:
        return asdict(self)


# --- predicados -----------------------------------------------------------------

def _cumple_goles(s: Seleccion, H, A, H1=None, A1=None, H2=None, A2=None) -> np.ndarray:
    o, L = s.opcion, s.linea
    if s.mercado == "1x2":
        return {"local": H > A, "empate": H == A, "visitante": H < A}[o]
    if s.mercado == "doble":
        return {"1X": H >= A, "X2": H <= A, "12": H != A}[o]
    if s.mercado == "goles":
        return (H + A > L) if o == "mas" else (H + A < L)
    if s.mercado == "btts":
        b = (H > 0) & (A > 0)
        return b if o == "si" else ~b
    if s.mercado == "btts_o25":
        b = ((H > 0) & (A > 0)) | (H + A > 2.5)
        return b if o == "si" else ~b
    if s.mercado == "goles_local":
        return (H > L) if o == "mas" else (H < L)
    if s.mercado == "goles_visitante":
        return (A > L) if o == "mas" else (A < L)
    if s.mercado == "marcador":
        i, j = (int(v) for v in o.split("-"))
        return (H == i) & (A == j)
    if s.mercado == "1t_1x2":
        return {"local": H1 > A1, "empate": H1 == A1, "visitante": H1 < A1}[o]
    if s.mercado == "1t_goles":
        return (H1 + A1 > L) if o == "mas" else (H1 + A1 < L)
    if s.mercado == "2t_goles":
        return (H2 + A2 > L) if o == "mas" else (H2 + A2 < L)
    raise ValueError(s.mercado)


def _cumple_conteo(s: Seleccion, X, Y) -> np.ndarray:
    L = s.linea
    v = {"corners": X + Y, "tarjetas": X + Y, "corners_local": X, "corners_visitante": Y}[s.mercado]
    return (v > L) if s.opcion == "mas" else (v < L)


def cumple_real(s: Seleccion, fila) -> bool | None:
    """Evalúa una selección contra el resultado real de un partido (fila de datos)."""
    def num(c):
        v = fila.get(c)
        return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
    fam = MERCADOS[s.mercado]["familia"]
    if fam == "jugadores":  # se liquida con los datos de jugadores (registro.liquidar_automatico)
        return None
    if fam in ("goles", "mitades"):
        H, A = num("gl"), num("gv")
        if H is None or A is None:
            return None
        H1, A1 = num("ht_gl"), num("ht_gv")
        if fam == "mitades":
            if H1 is None or A1 is None:
                return None
            return bool(_cumple_goles(s, np.array(H), np.array(A), np.array(H1), np.array(A1),
                                      np.array(H - H1), np.array(A - A1)))
        return bool(_cumple_goles(s, np.array(H), np.array(A)))
    if fam == "corners":
        X, Y = num("corn_l"), num("corn_v")
    else:
        # Betano (regla 3.1.62): amarilla = 1, roja = 2
        X = None if num("ama_l") is None else puntos_tarjetas(num("ama_l"), num("roj_l") or 0)
        Y = None if num("ama_v") is None else puntos_tarjetas(num("ama_v"), num("roj_v") or 0)
    if X is None or Y is None:
        return None
    return bool(_cumple_conteo(s, np.array(X), np.array(Y)))


# --- motor de un partido --------------------------------------------------------

@dataclass
class MotorPartido:
    local: str
    visitante: str
    lam: float
    mu: float
    rho: float
    fraccion_1t: float = C.FRACCION_1T
    corners: np.ndarray | None = None      # matriz conjunta (córners local, visitante)
    tarjetas: np.ndarray | None = None
    origen: str = "modelo"
    avisos: list = field(default_factory=list)

    @staticmethod
    def desde_modelo(ml: ModeloLiga, local: str, visitante: str) -> "MotorPartido":
        lam, mu = ml.ft.lambdas(local, visitante)
        avisos = []
        for e in (local, visitante):
            n = ml.ft.partidos_por_equipo.get(e, 0)
            if n == 0:
                avisos.append(f"{e} no tiene partidos en esta liga dentro de la ventana de datos: se trató como equipo promedio.")
            elif n < 12:
                avisos.append(f"{e} tiene solo {n} partidos en la muestra (recién ascendido o pocos datos): estimación poco fiable.")
        return MotorPartido(
            local, visitante, lam, mu, ml.ft.rho, ml.fraccion_1t,
            corners=ml.corners.conjunta(local, visitante) if ml.corners else None,
            tarjetas=ml.tarjetas.conjunta(local, visitante) if ml.tarjetas else None,
            origen="modelo", avisos=avisos,
        )

    def matriz_ft(self) -> np.ndarray:
        return matriz_dc(self.lam, self.mu, self.rho, C.MAX_GOLES)

    def _rejilla_mitades(self):
        k = np.arange(C.MAX_GOLES_MITAD + 1)
        f = self.fraccion_1t
        p1l, p1v = poisson.pmf(k, self.lam * f), poisson.pmf(k, self.mu * f)
        p2l, p2v = poisson.pmf(k, self.lam * (1 - f)), poisson.pmf(k, self.mu * (1 - f))
        P = np.einsum("a,b,c,d->abcd", p1l, p1v, p2l, p2v)
        P /= P.sum()
        H1, A1, H2, A2 = np.meshgrid(k, k, k, k, indexing="ij")
        return P, H1 + H2, A1 + A2, H1, A1, H2, A2

    def prob(self, selecciones: list[Seleccion]) -> dict:
        """Probabilidad conjunta de todas las selecciones y de cada una por separado."""
        avisos = list(self.avisos)
        goles = [s for s in selecciones if MERCADOS[s.mercado]["familia"] in ("goles", "mitades")]
        corn = [s for s in selecciones if MERCADOS[s.mercado]["familia"] == "corners"]
        tarj = [s for s in selecciones if MERCADOS[s.mercado]["familia"] == "tarjetas"]
        individuales: list[float | None] = []
        conjunta = 1.0

        if goles:
            usa_mitades = any(MERCADOS[s.mercado]["familia"] == "mitades" for s in goles)
            if usa_mitades:
                P, H, A, H1, A1, H2, A2 = self._rejilla_mitades()
                mascaras = [_cumple_goles(s, H, A, H1, A1, H2, A2) for s in goles]
                avisos.append("Mercados por tiempos: se asume que los goles de cada mitad siguen Poisson con la fracción de goles del 1.er tiempo de la liga.")
            else:
                P = self.matriz_ft()
                k = np.arange(P.shape[0])
                H, A = np.meshgrid(k, k, indexing="ij")
                mascaras = [_cumple_goles(s, H, A) for s in goles]
            conjunta *= float(P[np.logical_and.reduce(mascaras)].sum())
            ind_goles = {id(s): float(P[m].sum()) for s, m in zip(goles, mascaras)}
        else:
            ind_goles = {}

        ind_conteo = {}
        for lista, M, nombre in ((corn, self.corners, "córners"), (tarj, self.tarjetas, "tarjetas")):
            if not lista:
                continue
            if M is None:
                avisos.append(f"No hay datos de {nombre} para esta liga/partido: esas patas no se pueden calcular.")
                for s in lista:
                    ind_conteo[id(s)] = None
                conjunta = None
                continue
            k = np.arange(M.shape[0])
            X, Y = np.meshgrid(k, k, indexing="ij")
            mascaras = [_cumple_conteo(s, X, Y) for s in lista]
            for s, m in zip(lista, mascaras):
                ind_conteo[id(s)] = float(M[m].sum())
            if conjunta is not None:
                conjunta *= float(M[np.logical_and.reduce(mascaras)].sum())
        if (corn or tarj) and goles:
            avisos.append("Se asume independencia entre goles y córners/tarjetas (aproximación).")

        for s in selecciones:
            individuales.append(ind_goles.get(id(s), ind_conteo.get(id(s))))
        return {"conjunta": conjunta, "individuales": individuales, "avisos": avisos}

    def resumen_mercados(self) -> list[dict]:
        """Tabla de los mercados principales para la ficha del partido."""
        filas = []
        sels = [Seleccion("1x2", o) for o in ("local", "empate", "visitante")]
        sels += [Seleccion("doble", o) for o in ("1X", "X2", "12")]
        for L in LINEAS_GOLES[:5]:
            sels += [Seleccion("goles", "mas", L), Seleccion("goles", "menos", L)]
        sels += [Seleccion("btts", "si"), Seleccion("btts", "no"), Seleccion("btts_o25", "si")]
        sels += [Seleccion("goles_local", "mas", 0.5), Seleccion("goles_local", "mas", 1.5),
                 Seleccion("goles_visitante", "mas", 0.5), Seleccion("goles_visitante", "mas", 1.5)]
        sels += [Seleccion("1t_goles", "mas", 0.5), Seleccion("1t_goles", "mas", 1.5),
                 Seleccion("2t_goles", "mas", 0.5), Seleccion("1t_1x2", "local"),
                 Seleccion("1t_1x2", "empate"), Seleccion("1t_1x2", "visitante")]
        if self.corners is not None:
            for L in (7.5, 8.5, 9.5, 10.5):
                sels += [Seleccion("corners", "mas", L), Seleccion("corners", "menos", L)]
        if self.tarjetas is not None:
            for L in (2.5, 3.5, 4.5, 5.5):
                sels += [Seleccion("tarjetas", "mas", L), Seleccion("tarjetas", "menos", L)]
        for s in sels:
            p = self.prob([s])["conjunta"]
            tit, sub = s.etiqueta(self.local, self.visitante)
            filas.append({"seleccion": s, "mercado": sub, "opcion": tit, "p": p})
        return filas

    def marcadores_probables(self, n: int = 8) -> list[tuple[str, float]]:
        M = self.matriz_ft()
        idx = np.dstack(np.unravel_index(np.argsort(M.ravel())[::-1], M.shape))[0][:n]
        return [(f"{i}-{j}", float(M[i, j])) for i, j in idx]

    def medias_conteo(self) -> dict:
        out = {}
        for nombre, M in (("corners", self.corners), ("tarjetas", self.tarjetas)):
            if M is not None:
                k = np.arange(M.shape[0])
                out[nombre] = (float((M.sum(1) * k).sum()), float((M.sum(0) * k).sum()))
        return out


# --- modelo de mercado (a partir de cuotas) -------------------------------------

def quitar_margen(cuotas: list[float]) -> np.ndarray:
    """Probabilidades sin margen (método de potencia: corrige el sesgo hacia el favorito)."""
    q = 1 / np.asarray(cuotas, dtype=float)
    if q.sum() <= 1:
        return q / q.sum()
    lo, hi = 1.0, 10.0
    for _ in range(80):
        k = (lo + hi) / 2
        if (q ** k).sum() > 1:
            lo = k
        else:
            hi = k
    p = q ** ((lo + hi) / 2)
    return p / p.sum()


def lambdas_desde_probs(p1: float, p2: float, po25: float | None = None,
                        rho: float = C.RHO_MERCADO) -> tuple[float, float]:
    """Busca los goles esperados (local, visitante) que reproducen las probabilidades del mercado."""
    k = np.arange(C.MAX_GOLES + 1)
    H, A = np.meshgrid(k, k, indexing="ij")

    def residuos(t):
        M = matriz_dc(np.exp(t[0]), np.exp(t[1]), rho)
        r = [M[H > A].sum() - p1, M[H < A].sum() - p2]
        if po25 is not None:
            r.append(M[H + A > 2.5].sum() - po25)
        return r
    sol = least_squares(residuos, x0=np.log([1.4, 1.1]), bounds=([-3, -3], [1.8, 1.8]))
    return float(np.exp(sol.x[0])), float(np.exp(sol.x[1]))


def motor_mercado(local: str, visitante: str, cuotas: dict, ml: ModeloLiga | None = None) -> MotorPartido | None:
    """cuotas: {"1":..,"x":..,"2":.., opcional "o25":..,"u25":..}."""
    try:
        c1, cx, c2 = float(cuotas["1"]), float(cuotas["x"]), float(cuotas["2"])
    except (KeyError, TypeError, ValueError):
        return None
    if min(c1, cx, c2) <= 1.0:
        return None
    p1, _, p2 = quitar_margen([c1, cx, c2])
    po = None
    if cuotas.get("o25") and cuotas.get("u25"):
        try:
            po = float(quitar_margen([float(cuotas["o25"]), float(cuotas["u25"])])[0])
        except (TypeError, ValueError):
            po = None
    lam, mu = lambdas_desde_probs(p1, p2, po)
    m = MotorPartido(local, visitante, lam, mu, C.RHO_MERCADO, origen="mercado")
    if ml is not None:
        m.fraccion_1t = ml.fraccion_1t
        if ml.corners:
            m.corners = ml.corners.conjunta(local, visitante)
        if ml.tarjetas:
            m.tarjetas = ml.tarjetas.conjunta(local, visitante)
    if po is None:
        m.avisos.append("Sin cuotas de Más/Menos 2.5: el total de goles del mercado se dedujo solo del 1X2 (menos preciso).")
    return m


# --- combinación modelo + mercado -----------------------------------------------

def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def combinar(p_modelo: float | None, p_mercado: float | None, peso_modelo: float) -> float | None:
    """Promedio en escala logit. peso_modelo sale del backtest."""
    if p_modelo is None:
        return p_mercado
    if p_mercado is None:
        return p_modelo
    z = peso_modelo * _logit(p_modelo) + (1 - peso_modelo) * _logit(p_mercado)
    return float(1 / (1 + np.exp(-z)))
