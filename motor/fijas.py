"""Generador de fijas y combinadas.

1. Para cada partido próximo calcula la probabilidad del bot (modelo + mercado) en los mercados
   que más se juegan en Betano.
2. La corrige con la calibración del backtest: si en el pasado, cuando el bot dijo 80 %, pasó 78 %,
   se usa 78 %. Así las "fijas" no se inflan.
3. Asigna una cuota: promedio de casas (1X2 y Más/Menos 2.5) o estimada (resto). El usuario debe
   confirmar la cuota real en Betano.
4. Arma combinadas que maximizan la probabilidad de acertar todo, con un partido por línea
   (y opcionalmente una cuota total objetivo).
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import analisis as A
from . import betano as B
from . import config as C
from . import datos
from . import mercados as M

MERCADOS_FIJAS = [
    M.Seleccion("1x2", "local"), M.Seleccion("1x2", "visitante"),
    M.Seleccion("doble", "1X"), M.Seleccion("doble", "X2"),
    M.Seleccion("goles", "mas", 1.5), M.Seleccion("goles", "mas", 2.5),
    M.Seleccion("goles", "menos", 2.5), M.Seleccion("goles", "menos", 3.5), M.Seleccion("goles", "menos", 4.5),
    M.Seleccion("btts", "si"), M.Seleccion("btts", "no"),
    M.Seleccion("goles_local", "mas", 0.5), M.Seleccion("goles_visitante", "mas", 0.5),
    M.Seleccion("goles_local", "mas", 1.5), M.Seleccion("goles_visitante", "mas", 1.5),
    M.Seleccion("1t_goles", "mas", 0.5),
]
MERCADOS_CORNERS = [M.Seleccion("corners", "mas", 7.5), M.Seleccion("corners", "mas", 8.5),
                    M.Seleccion("corners", "menos", 11.5), M.Seleccion("corners", "menos", 12.5)]

CALIB_ENCOGIMIENTO = 300  # casos "virtuales" a favor de no corregir (evita sobreajustar tramos chicos)

PERFILES = {  # probabilidad calibrada mínima por selección
    "ultra": {"nombre": "Ultra segura", "p_min": 0.85, "emoji": "🛡️"},
    "segura": {"nombre": "Segura", "p_min": 0.75, "emoji": "✅"},
    "equilibrada": {"nombre": "Equilibrada", "p_min": 0.65, "emoji": "⚖️"},
    "arriesgada": {"nombre": "Arriesgada", "p_min": 0.50, "emoji": "🔥"},
}


@dataclass
class Candidata:
    liga: str
    inicio: pd.Timestamp
    local: str
    visitante: str
    seleccion: M.Seleccion
    p_modelo: float | None
    p_mercado: float | None
    p_bot: float
    p_cal: float
    cuota: float
    cuota_tipo: str            # "referencia" (promedio de casas) o "estimada"
    lam: float
    mu: float
    evidencia: str | None = None
    p_pago_anticipado: float | None = None

    @property
    def valor(self) -> float:
        return self.p_cal * self.cuota - 1

    @property
    def partido(self) -> str:
        from .equipos import nombre
        return f"{nombre(self.local)} vs {nombre(self.visitante)}"

    def etiqueta(self) -> tuple[str, str]:
        return self.seleccion.etiqueta(self.local, self.visitante)

    def grupo(self, fuente: str = "bot") -> A.Grupo:
        return A.Grupo(self.liga, self.local, self.visitante, [self.seleccion], self.cuota,
                       str(self.inicio.date()), None, fuente)


@dataclass
class Combinada:
    patas: list[Candidata]
    monto: float = 0.0
    titulo: str = ""
    notas: list = field(default_factory=list)

    @property
    def cuota_total(self) -> float:
        return float(np.prod([c.cuota for c in self.patas])) if self.patas else 0.0

    @property
    def p_total(self) -> float:
        return float(np.prod([c.p_cal for c in self.patas])) if self.patas else 0.0

    @property
    def ganancia_potencial(self) -> float:
        return self.monto * self.cuota_total

    @property
    def tipo(self) -> str:
        n = len(self.patas)
        return "Simple" if n == 1 else ("Doble" if n == 2 else ("Triple" if n == 3 else f"Combinada de {n}"))

    def promos(self) -> dict:
        grupos = [c.grupo() for c in self.patas]
        cuotas = [c.cuota for c in self.patas]
        return {"multi_bono": B.multi_bono(grupos, cuotas), "seguro": B.seguro_betano(grupos, cuotas)}


# --- calibración con el backtest ------------------------------------------------------

def calibrar(s: M.Seleccion, p: float | None) -> float | None:
    if p is None:
        return None
    ev = A._evento_backtest(s)
    tabla = A.resumen_evaluacion().get("calibracion_por_evento", {})
    if ev is None or ev[0] not in tabla:
        return p
    nombre, invertido = ev
    bins = tabla[nombre]
    if not bins:
        return p
    q = 1 - p if invertido else p
    # tramo que contiene q (o el más cercano)
    b = min(bins, key=lambda b: 0 if b["lo"] < q <= b["hi"] else min(abs(q - b["lo"]), abs(q - b["hi"])) + 1)
    # se corrige solo en proporción a la evidencia: con pocos casos casi no se toca
    k = b["n"] / (b["n"] + CALIB_ENCOGIMIENTO)
    r = float(np.clip(q + k * (b["frecuencia_real"] - b["prob_estimada"]), 0.001, 0.999))
    return 1 - r if invertido else r


# --- candidatas -------------------------------------------------------------------------

def ahora_peru() -> pd.Timestamp:
    return pd.Timestamp.now(tz=C.ZONA_HORARIA).tz_localize(None)


def ventana(cuando: str) -> tuple[pd.Timestamp, pd.Timestamp, str]:
    """Rango de inicio de partidos (hora de Perú) para 'hoy', 'manana', 'finde', 'semana' o 'AAAA-MM-DD'."""
    ahora = ahora_peru()
    hoy = ahora.normalize()
    if cuando == "hoy":
        return ahora, hoy + pd.Timedelta(days=1), f"hoy {hoy:%d/%m}"
    if cuando == "manana":
        d = hoy + pd.Timedelta(days=1)
        return d, d + pd.Timedelta(days=1), f"mañana {d:%d/%m}"
    if cuando == "pasado":
        d = hoy + pd.Timedelta(days=2)
        return d, d + pd.Timedelta(days=1), f"pasado mañana {d:%d/%m}"
    if cuando == "finde":
        sab = hoy + pd.Timedelta(days=(5 - hoy.dayofweek) % 7)
        ini = max(ahora, sab) if hoy.dayofweek < 5 else ahora
        fin = sab + pd.Timedelta(days=2) if hoy.dayofweek < 5 else hoy + pd.Timedelta(days=7 - hoy.dayofweek)
        return ini, fin, "el fin de semana"
    if cuando == "semana":
        return ahora, hoy + pd.Timedelta(days=8), "los próximos días"
    try:
        d = pd.Timestamp(cuando).normalize()
        return max(ahora, d), d + pd.Timedelta(days=1), f"el {d:%d/%m}"
    except Exception:
        return ahora, hoy + pd.Timedelta(days=2), "hoy y mañana"


_cache_cands: dict = {}


def candidatas(desde: pd.Timestamp, hasta: pd.Timestamp, ligas: list[str] | None = None,
               corners: bool = False, mercados: list[str] | None = None) -> list[Candidata]:
    """Selecciones candidatas de los partidos que empiezan entre desde y hasta (con caché de 10 min)."""
    mods = tuple(sorted(p.name for p in C.DIR_MODELOS.glob("*/*.json")))
    clave = (datos._firma(), mods, A.resumen_evaluacion().get("fecha"), max(desde, ahora_peru()).floor("10min"),
             hasta, tuple(ligas or ()), corners, tuple(mercados or ()))
    if clave not in _cache_cands:
        if len(_cache_cands) > 30:
            _cache_cands.clear()
        _cache_cands[clave] = _candidatas(desde, hasta, ligas, corners, mercados)
    return [c for c in _cache_cands[clave] if c.inicio >= ahora_peru()]


def _candidatas(desde, hasta, ligas, corners, mercados) -> list[Candidata]:
    px = datos.cargar_proximos()
    if px.empty:
        return []
    px = px[(px["inicio"] >= max(desde, ahora_peru())) & (px["inicio"] < hasta)]
    if ligas:
        px = px[px["liga"].isin(ligas)]
    w, _ = A.peso_modelo()
    lista = MERCADOS_FIJAS + (MERCADOS_CORNERS if corners else [])
    if mercados:
        lista = [s for s in lista if s.mercado in mercados or (s.mercado.startswith("goles") and "goles" in mercados)]
    out: list[Candidata] = []
    for _, f in px.iterrows():
        ml = A.cargar_modelo(f.liga)
        if not ml or not (ml.ft.tiene(f.local) and ml.ft.tiene(f.visitante)):
            continue
        mod = M.MotorPartido.desde_modelo(ml, f.local, f.visitante)
        ref = A.cuotas_proximo(f.liga, f.local, f.visitante)
        mer = M.motor_mercado(f.local, f.visitante, ref, ml) if ref else None
        if mer is None:
            continue  # sin cuotas de mercado no se proponen fijas (el modelo solo es menos fiable)
        for s in lista:
            pm = mod.prob([s])["conjunta"]
            pk = mer.prob([s])["conjunta"]
            if pm is None:
                continue
            pb = M.combinar(pm, pk, w)
            pc = calibrar(s, pb)
            cref = B.cuota_referencia(f, s)
            cuota, tipo = (cref, "referencia") if cref else (B.cuota_estimada(pk if pk else pb, s.mercado), "estimada")
            if not cuota:
                continue
            c = Candidata(f.liga, f.inicio, f.local, f.visitante, s, pm, pk, pb, pc, cuota, tipo,
                          mod.lam, mod.mu, A.evidencia(s, pb))
            if s.mercado == "1x2":
                lam_b = 0.8 * mer.lam + 0.2 * mod.lam
                mu_b = 0.8 * mer.mu + 0.2 * mod.mu
                _, c.p_pago_anticipado = B.prob_pago_anticipado(lam_b, mu_b, s.opcion)
            out.append(c)
    return out


def filtrar(cands: list[Candidata], perfil: str = "segura", cuota_min: float = 1.15,
            cuota_max: float = 3.0) -> list[Candidata]:
    p_min = PERFILES[perfil]["p_min"]
    return [c for c in cands if c.p_cal >= p_min and cuota_min <= c.cuota <= cuota_max and c.p_cal <= 0.97]


def mejores_simples(cands: list[Candidata], n: int = 8) -> list[Candidata]:
    """La mejor selección de cada partido, ordenadas por probabilidad calibrada."""
    por_partido: dict = {}
    for c in cands:
        k = (c.local, c.visitante)
        if k not in por_partido or (c.p_cal, c.valor) > (por_partido[k].p_cal, por_partido[k].valor):
            por_partido[k] = c
    return sorted(por_partido.values(), key=lambda c: (-c.p_cal, -c.valor))[:n]


def armar_combinada(cands: list[Candidata], n: int | None = 3, cuota_objetivo: float | None = None,
                    max_patas: int = 8, opciones_por_partido: int = 4) -> list[Candidata]:
    """Máxima probabilidad conjunta con un partido por línea, n patas y/o cuota total ≥ objetivo."""
    grupos: dict = {}
    for c in sorted(cands, key=lambda c: -c.p_cal):
        k = (c.local, c.visitante)
        if len(grupos.setdefault(k, [])) < opciones_por_partido:
            grupos[k].append(c)
    grupos_l = list(grupos.values())
    if not grupos_l:
        return []
    if not cuota_objetivo:
        n = min(n or 3, len(grupos_l))
        return sorted([g[0] for g in grupos_l], key=lambda c: -c.p_cal)[:n]

    W = max(1, int(math.ceil(math.log(cuota_objetivo) / 0.01)))
    nmax = n if n else max_patas
    NEG = -1e18
    # dp[k][w] = (log-prob, lista de candidatas)
    dp = [[(NEG, None) for _ in range(W + 1)] for _ in range(nmax + 1)]
    dp[0][0] = (0.0, [])
    for opciones in grupos_l:
        nuevo = [fila[:] for fila in dp]
        for k in range(nmax):
            for w_ in range(W + 1):
                val, sel = dp[k][w_]
                if sel is None:
                    continue
                for c in opciones:
                    w2 = min(W, w_ + int(round(math.log(c.cuota) / 0.01)))
                    v2 = val + math.log(c.p_cal)
                    if v2 > nuevo[k + 1][w2][0]:
                        nuevo[k + 1][w2] = (v2, sel + [c])
        dp = nuevo
    filas = [dp[n][W]] if n else [dp[k][W] for k in range(1, nmax + 1)]
    mejores = [f for f in filas if f[1] is not None]
    if not mejores:
        return []
    return max(mejores, key=lambda f: f[0])[1]


def bet_builders(liga: str, local: str, visitante: str, cuota_min: float = 1.30, n: int = 3) -> list[dict]:
    """Bet Builders de 2 patas del mismo partido con la mayor probabilidad conjunta."""
    ml = A.cargar_modelo(liga)
    if not ml or not (ml.ft.tiene(local) and ml.ft.tiene(visitante)):
        return []
    mod = M.MotorPartido.desde_modelo(ml, local, visitante)
    ref = A.cuotas_proximo(liga, local, visitante)
    mer = M.motor_mercado(local, visitante, ref, ml) if ref else None
    w, _ = A.peso_modelo()
    base = [M.Seleccion("doble", "1X"), M.Seleccion("doble", "X2"), M.Seleccion("1x2", "local"),
            M.Seleccion("1x2", "visitante")]
    goles = [M.Seleccion("goles", "mas", 0.5), M.Seleccion("goles", "mas", 1.5), M.Seleccion("goles", "mas", 2.5),
             M.Seleccion("goles", "menos", 3.5), M.Seleccion("goles", "menos", 4.5), M.Seleccion("btts", "si"),
             M.Seleccion("goles_local", "mas", 0.5), M.Seleccion("goles_visitante", "mas", 0.5)]
    out = []
    for a in base:
        for b in goles:
            sels = [a, b]
            pm = mod.prob(sels)["conjunta"]
            pk = mer.prob(sels)["conjunta"] if mer else None
            pf = M.combinar(pm, pk, w)
            cuota = B.cuota_estimada(pk or pf, "doble", n_patas=2)
            if cuota and cuota >= cuota_min and pf:
                out.append({"selecciones": sels, "p": pf, "cuota": cuota, "p_modelo": pm, "p_mercado": pk})
    out.sort(key=lambda x: -x["p"])
    return out[:n]


# --- explicaciones ----------------------------------------------------------------------

def razon(c: Candidata, df: pd.DataFrame | None = None) -> str:
    """Una o dos frases con el porqué, a partir de datos (no de opiniones)."""
    from . import ficha
    df = datos.cargar_partidos() if df is None else df
    partes = [f"Goles esperados {c.lam + c.mu:.1f} ({c.local} {c.lam:.1f} · {c.visitante} {c.mu:.1f})."]
    s = c.seleccion
    temp = ficha.temporada_actual()
    try:
        if s.mercado in ("goles", "btts", "1t_goles", "goles_local", "goles_visitante"):
            frases = []
            for eq in (c.local, c.visitante):
                v = ficha._vista_equipo(df[df["liga"] == c.liga], eq).tail(8)
                if len(v):
                    tot = v["gf"] + v["gc"]
                    if s.mercado == "goles" and s.opcion == "mas":
                        k = int((tot > s.linea).sum())
                    elif s.mercado == "goles":
                        k = int((tot < s.linea).sum())
                    elif s.mercado == "btts":
                        b = (v["gf"] > 0) & (v["gc"] > 0)
                        k = int(b.sum() if s.opcion == "si" else (~b).sum())
                    elif s.mercado == "goles_local" and eq == c.local:
                        k = int((v["gf"] > s.linea).sum())
                    elif s.mercado == "goles_visitante" and eq == c.visitante:
                        k = int((v["gf"] > s.linea).sum())
                    else:
                        continue
                    frases.append(f"{eq} {k}/{len(v)}")
            if frases:
                partes.append("Se cumplió en los últimos partidos: " + ", ".join(frases) + ".")
        elif s.mercado in ("1x2", "doble"):
            for eq in (c.local, c.visitante):
                v = ficha._vista_equipo(df[(df["liga"] == c.liga) & (df["temporada"] == temp)], eq)
                if len(v):
                    partes.append(f"{eq}: {(v.res == 'G').sum()}G-{(v.res == 'E').sum()}E-{(v.res == 'P').sum()}P esta temporada.")
    except Exception:
        pass
    if c.p_modelo is not None and c.p_mercado is not None and abs(c.p_modelo - c.p_mercado) > C.UMBRAL_DISCREPANCIA:
        partes.append("⚠️ Modelo y mercado discrepan: revisa bajas y alineaciones.")
    return " ".join(partes)


def combinada_desde_texto_cuota(c: Combinada) -> str:
    lineas = [f"{c.tipo} · propuesta del bot (verifica cuotas en Betano)"]
    for p in c.patas:
        tit, sub = p.etiqueta()
        lineas.append(f"⚽ {tit} — {sub}\n   {p.partido} · {p.inicio:%d/%m %H:%M}\n   Cuota {'≈' if p.cuota_tipo == 'estimada' else ''}{p.cuota:.2f} · prob. {p.p_cal:.0%}")
    lineas.append(f"Cuota total {c.cuota_total:.2f}")
    if c.monto:
        lineas.append(f"Apuesta S/{c.monto:.2f} → Ganancias potenciales S/{c.ganancia_potencial:.2f}")
    lineas.append(f"Probabilidad de acertar todo: {c.p_total:.0%}")
    return "\n".join(lineas)
