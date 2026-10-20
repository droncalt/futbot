"""Súper boletas seguras: un Bet Builder por partido con las patas más probables, y la combinada de varios.

Para cada partido:
1. Calcula cada pata posible (goles, doble oportunidad, "equipo anota", córners, tarjetas y tiros al arco 1+
   de jugadores titulares) con la probabilidad del bot (modelo + mercado) corregida por la calibración.
2. Arma el Bet Builder sumando, una por una, la pata que MENOS probabilidad le quita al conjunto,
   descartando las redundantes (no suben la cuota) y parando cuando el conjunto baja del nivel pedido.
3. Precalcula la probabilidad y la cuota estimada de cada subconjunto de patas, para que la boleta
   interactiva recalcule al instante cuando el usuario desmarca una pata.

La probabilidad de las patas del mismo partido se calcula en conjunto (no se multiplican como si fueran
independientes). Entre goles, córners/tarjetas y jugadores se asume independencia (aproximación avisada).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import analisis as A
from . import betano as B
from . import config as C
from . import datos
from . import fijas as F
from . import mercados as M

NIVELES = {  # cuota mínima que debe pagar cada línea y probabilidad mínima de la línea y de cada pata
    "ultra": {"nombre": "Ultra segura", "cuota_min": 1.15, "linea": 0.78, "pata": 0.80, "emoji": "🛡️"},
    "segura": {"nombre": "Segura", "cuota_min": 1.25, "linea": 0.68, "pata": 0.72, "emoji": "✅"},
    "equilibrada": {"nombre": "Equilibrada", "cuota_min": 1.40, "linea": 0.58, "pata": 0.62, "emoji": "⚖️"},
}
CANDIDATAS_POR_PARTIDO = 12

PATAS_GOLES = [
    ("doble", M.Seleccion("doble", "1X")), ("doble", M.Seleccion("doble", "X2")),
    ("doble", M.Seleccion("1x2", "local")), ("doble", M.Seleccion("1x2", "visitante")),
    ("total", M.Seleccion("goles", "mas", 0.5)), ("total", M.Seleccion("goles", "mas", 1.5)),
    ("total", M.Seleccion("goles", "mas", 2.5)), ("total_bajo", M.Seleccion("goles", "menos", 3.5)),
    ("total_bajo", M.Seleccion("goles", "menos", 4.5)),
    ("gl", M.Seleccion("goles_local", "mas", 0.5)), ("gl", M.Seleccion("goles_local", "mas", 1.5)),
    ("gv", M.Seleccion("goles_visitante", "mas", 0.5)), ("gv", M.Seleccion("goles_visitante", "mas", 1.5)),
    ("t1", M.Seleccion("1t_goles", "mas", 0.5)), ("btts", M.Seleccion("btts", "si")),
]
PATAS_CORNERS = [
    ("corn", M.Seleccion("corners", "mas", 6.5)), ("corn", M.Seleccion("corners", "mas", 7.5)),
    ("corn", M.Seleccion("corners", "mas", 8.5)),
    ("cl", M.Seleccion("corners_local", "mas", 2.5)), ("cl", M.Seleccion("corners_local", "mas", 3.5)),
    ("cv", M.Seleccion("corners_visitante", "mas", 2.5)), ("cv", M.Seleccion("corners_visitante", "mas", 3.5)),
]
PATAS_TARJETAS = [("tarj", M.Seleccion("tarjetas", "mas", 1.5)), ("tarj", M.Seleccion("tarjetas", "mas", 2.5)),
                  ("tarj", M.Seleccion("tarjetas", "mas", 3.5))]
REDUNDANTE = 0.94      # si la pata se cumple ≥ 94 % de las veces que se cumplen las demás, casi no suma cuota
MAX_SUBCONJ = 4        # patas máximas por Bet Builder (2^4 − 1 = 15 subconjuntos precalculados)


@dataclass
class Pata:
    grupo: str
    seleccion: M.Seleccion
    titulo: str
    mercado: str
    p: float                       # probabilidad calibrada de la pata sola
    familia: str
    alternativas: dict | None = None  # jugadores: {"1+": p, "2+": p, ...} para elegir la línea que Betano ofrece


@dataclass
class Linea:
    id: str
    liga: str
    inicio: pd.Timestamp
    local: str
    visitante: str
    patas: list[Pata]
    p: float
    cuota: float
    cuota_tipo: str
    subconjuntos: dict = field(default_factory=dict)   # máscara -> {"p", "cuota"}
    avisos: list = field(default_factory=list)

    @property
    def partido(self) -> str:
        from .equipos import nombre
        return f"{nombre(self.local)} vs {nombre(self.visitante)}"

    def grupo(self, mascara: int | None = None, cuota: float | None = None, fuente: str = "bot") -> A.Grupo:
        sels = [pt.seleccion for i, pt in enumerate(self.patas) if mascara is None or mascara >> i & 1]
        return A.Grupo(self.liga, self.local, self.visitante, sels, cuota or self.cuota,
                       str(self.inicio.date()), None, fuente)


class _Rejillas:
    """Distribuciones de un motor (modelo o mercado) con máscaras de cada pata, para calcular rápido."""

    def __init__(self, motor: M.MotorPartido):
        self.ft = motor.matriz_ft()
        k = np.arange(self.ft.shape[0])
        self.H, self.A = np.meshgrid(k, k, indexing="ij")
        P4, H4, A4, H1, A1, H2, A2 = motor._rejilla_mitades()
        self.mit = (P4, H4, A4, H1, A1, H2, A2)
        self.corn = motor.corners
        self.tarj = motor.tarjetas
        self._mascaras: dict = {}

    def mascara(self, s: M.Seleccion, mitades: bool):
        clave = (s.mercado, s.opcion, s.linea, mitades)
        if clave not in self._mascaras:
            fam = M.MERCADOS[s.mercado]["familia"]
            if fam in ("goles", "mitades"):
                if mitades:
                    _, H4, A4, H1, A1, H2, A2 = self.mit
                    m = M._cumple_goles(s, H4, A4, H1, A1, H2, A2)
                else:
                    m = M._cumple_goles(s, self.H, self.A)
            else:
                Mx = self.corn if fam == "corners" else self.tarj
                kk = np.arange(Mx.shape[0])
                X, Y = np.meshgrid(kk, kk, indexing="ij")
                m = M._cumple_conteo(s, X, Y)
            self._mascaras[clave] = m
        return self._mascaras[clave]

    def prob(self, sels: list[M.Seleccion]) -> float:
        p = 1.0
        goles = [s for s in sels if M.MERCADOS[s.mercado]["familia"] in ("goles", "mitades")]
        if goles:
            mit = any(M.MERCADOS[s.mercado]["familia"] == "mitades" for s in goles)
            P = self.mit[0] if mit else self.ft
            p *= float(P[np.logical_and.reduce([self.mascara(s, mit) for s in goles])].sum())
        for fam, Mx in (("corners", self.corn), ("tarjetas", self.tarj)):
            sub = [s for s in sels if M.MERCADOS[s.mercado]["familia"] == fam]
            if sub:
                p *= float(Mx[np.logical_and.reduce([self.mascara(s, False) for s in sub])].sum())
        return p


class _Partido:
    """Calcula probabilidades conjuntas de un partido (modelo + mercado + jugadores)."""

    def __init__(self, liga, local, visitante, w, fila=None):
        self.liga, self.local, self.visitante, self.w = liga, local, visitante, w
        self.fila = fila   # fila del partido en la lista de próximos (cuotas de referencia)
        ml = A.cargar_modelo(liga)
        ref = A.cuotas_proximo(liga, local, visitante)
        self.ref = ref
        con_modelo = bool(ml) and ml.ft.tiene(local) and ml.ft.tiene(visitante)
        self.mer = M.motor_mercado(local, visitante, ref, ml if con_modelo else None) if ref else None
        if con_modelo:
            self.mod = M.MotorPartido.desde_modelo(ml, local, visitante)
        elif self.mer is not None:  # Champions, Libertadores, equipo sin historial: solo el mercado
            self.mod = self.mer
            self.mod.avisos.append("Sin modelo propio para este partido: probabilidades del mercado (cuotas de DraftKings vía ESPN).")
        else:
            raise ValueError("sin modelo ni cuotas")
        self.r_mod = _Rejillas(self.mod)
        self.r_mer = _Rejillas(self.mer) if self.mer else None
        self._cache: dict = {}
        self._cruda: dict = {}

    def bruta(self, sels: list[M.Seleccion]) -> tuple[float, float | None]:
        pm = self.r_mod.prob(sels)
        pk = self.r_mer.prob(sels) if self.r_mer else None
        return pm, pk

    def conjunta(self, patas: list[Pata]) -> tuple[float, float]:
        """(probabilidad del bot calibrada, probabilidad "justa" para estimar la cuota)."""
        clave = tuple(sorted(id(p) for p in patas))
        if clave in self._cache:
            return self._cache[clave]
        equipo = [p for p in patas if p.familia != "jugadores"]
        jug = [p for p in patas if p.familia == "jugadores"]
        pb, pj = 1.0, 1.0
        if equipo:
            pm, pk = self.bruta([p.seleccion for p in equipo])
            pb = M.combinar(pm, pk, self.w) or 0.0
            pj = pk if pk is not None else pb
            # corrección de calibración: el factor de cada pata (calibrada / sin calibrar), acotado
            factor = 1.0
            for p in equipo:
                if id(p) not in self._cruda:
                    self._cruda[id(p)] = M.combinar(*self.bruta([p.seleccion]), self.w)
                cruda = self._cruda[id(p)]
                if cruda:
                    factor *= min(1.05, max(0.85, p.p / cruda))
            pb = min(pb * factor, min(p.p for p in equipo))
        for p in jug:  # jugadores: independientes del resto (aproximación)
            pb *= p.p
            pj *= p.p
        self._cache[clave] = (float(pb), float(pj))
        return self._cache[clave]


def _normal(nombre: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in t.replace("-", " ").split() if w not in ("lottin", "junior", "jr"))


def lineas_betano() -> dict:
    try:
        import json
        return json.loads(C.RUTA_LINEAS_BETANO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def linea_min_jugador(nombre: str, probs: dict) -> int:
    """Línea más baja de tiros al arco que Betano ofrece para el jugador: lo visto en capturas o, si no hay,
    2+ cuando 1+ es tan probable que Betano suele ocultarla (C.JUG_ARCO_1_OCULTA)."""
    vistos = lineas_betano().get("jug_arco", {})
    n = _normal(nombre)
    for k, v in vistos.items():
        if k == n or (k.split()[-1] == n.split()[-1] and k.split()[0][:1] == n.split()[0][:1]):
            return int(v.get("min", 1))
    return 2 if (probs.get("1+") or 0) > C.JUG_ARCO_1_OCULTA else 1


def _patas_partido(pt: _Partido, p_min: float, jugadores: bool, corners: bool, tarjetas: bool) -> list[Pata]:
    lista = PATAS_GOLES + (PATAS_CORNERS if corners else []) + (PATAS_TARJETAS if tarjetas else [])
    out = []
    for grupo, s in lista:
        fam = M.MERCADOS[s.mercado]["familia"]
        if fam in ("corners", "tarjetas") and (pt.mod.corners is None if fam == "corners" else pt.mod.tarjetas is None):
            continue
        pm, pk = pt.bruta([s])
        pc = F.calibrar(s, M.combinar(pm, pk, pt.w))
        if pc is None or pc < p_min or pc > 0.985:
            continue
        tit, sub = s.etiqueta(pt.local, pt.visitante)
        out.append(Pata(grupo, s, tit, sub, float(pc), fam))
    if jugadores and pt.liga in C.LIGAS_JUGADORES:
        try:
            from . import modelo_jugadores as MJ
            r = MJ.jugadores_partido(pt.liga, pt.local, pt.visitante, MJ.ESCENARIO_DEFECTO, n=6)
            if r.get("disponible"):
                for lado in ("local", "visitante"):
                    for f in r[lado]:
                        k = linea_min_jugador(f["jugador"], f["prob"])
                        pk = f["prob"].get(f"{k}+")
                        if pk and p_min <= pk <= 0.985:
                            s = M.Seleccion("jug_arco", f"{k}+", k - 0.5, **f["seleccion"])
                            tit, sub = s.etiqueta(pt.local, pt.visitante)
                            out.append(Pata(f"jug_{f['jugador_id']}", s, tit, sub, float(pk), "jugadores",
                                            dict(f["prob"])))
        except Exception:
            pass
    return sorted(out, key=lambda x: -x.p)


def _construir(pt: _Partido, patas: list[Pata], p_linea: float, max_patas: int, cuota_min: float) -> list[Pata]:
    """El Bet Builder (1 a max_patas patas) MÁS PROBABLE que pague al menos cuota_min."""
    cands = patas[:CANDIDATAS_POR_PARTIDO]
    mejor, mejor_p = None, -1.0
    for r in range(1, max_patas + 1):
        for combo in itertools.combinations(cands, r):
            grupos = [p.grupo for p in combo]
            if len(set(grupos)) < r or sum(p.familia == "jugadores" for p in combo) > 1:
                continue
            p, pj = pt.conjunta(list(combo))
            if p < p_linea or p <= mejor_p:
                continue
            # cada pata debe aportar: si se cumple casi siempre que se cumplen las otras, sobra
            if r > 1 and any(p / pt.conjunta([q for q in combo if q is not x])[0] > REDUNDANTE for x in combo):
                continue
            cuota, _ = _cuota_linea(pt, list(combo), pj)
            if cuota < cuota_min:
                continue
            mejor, mejor_p = list(combo), p
    return mejor or []


def _cuota_linea(pt: _Partido, patas: list[Pata], p_justa: float) -> tuple[float, str]:
    if len(patas) == 1 and patas[0].familia != "jugadores" and pt.fila is not None:
        ref = B.cuota_referencia(pt.fila, patas[0].seleccion)
        if ref:
            return ref, "referencia"
    merc = patas[0].seleccion.mercado if len(patas) == 1 else "doble"
    return B.cuota_estimada(p_justa, merc, n_patas=len(patas)) or 1.01, "estimada"


_cache: dict = {}


def generar(desde: pd.Timestamp, hasta: pd.Timestamp, nivel: str = "segura", ligas: list[str] | None = None,
            jugadores: bool = True, corners: bool = True, tarjetas: bool = False,
            max_patas: int = 3) -> list[Linea]:
    """Un Bet Builder seguro por partido que empiece entre desde y hasta, ordenados por probabilidad."""
    mods = tuple(sorted(p.name for p in C.DIR_MODELOS.glob("*/*.json")))
    clave = (datos._firma(), mods, A.resumen_evaluacion().get("fecha"), max(desde, F.ahora_peru()).floor("10min"),
             hasta, nivel, tuple(ligas or ()), jugadores, corners, tarjetas, max_patas)
    if clave not in _cache:
        if len(_cache) > 20:
            _cache.clear()
        _cache[clave] = _generar(desde, hasta, nivel, ligas, jugadores, corners, tarjetas, max_patas)
    return [l for l in _cache[clave] if l.inicio >= F.ahora_peru()]


def _generar(desde, hasta, nivel, ligas, jugadores, corners, tarjetas, max_patas) -> list[Linea]:
    cfg = NIVELES[nivel]
    px = datos.cargar_proximos()
    if px.empty:
        return []
    px = px[(px["inicio"] >= max(desde, F.ahora_peru())) & (px["inicio"] < hasta)]
    if ligas:
        px = px[px["liga"].isin(ligas)]
    w, _ = A.peso_modelo()
    lineas = []
    for _, f in px.iterrows():
        try:
            pt = _Partido(f.liga, f.local, f.visitante, w, f)
        except Exception:
            continue
        if pt.mer is None:
            continue  # sin cuotas de mercado no se proponen (el modelo solo es menos fiable)
        patas = _patas_partido(pt, cfg["pata"], jugadores, corners, tarjetas)
        elegidas = _construir(pt, patas, cfg["linea"], min(max_patas, MAX_SUBCONJ), cfg["cuota_min"])
        if not elegidas:
            continue
        p, pj = pt.conjunta(elegidas)
        cuota, tipo = _cuota_linea(pt, elegidas, pj)
        sub = {}
        for r in range(1, len(elegidas) + 1):
            for combo in itertools.combinations(range(len(elegidas)), r):
                mask = sum(1 << i for i in combo)
                ps, pjs = pt.conjunta([elegidas[i] for i in combo])
                cs, ts = _cuota_linea(pt, [elegidas[i] for i in combo], pjs)
                sub[mask] = {"p": round(ps, 4), "cuota": round(cs, 2), "estimada": ts == "estimada"}
        avisos = list(pt.mod.avisos)
        if any(p.familia == "jugadores" for p in elegidas):
            avisos.append("Tiros al arco: supone que el jugador es titular. En Betano, si no sale de titular, "
                          "se anula la selección y con ella TODO el Bet Builder (te devuelven lo apostado).")
        if any(p.familia in ("corners", "tarjetas") for p in elegidas):
            avisos.append("Córners/tarjetas: solo modelo (sin cuota de mercado); se asumen independientes de los goles.")
        lineas.append(Linea(f"{f.liga}|{f.local}|{f.visitante}", f.liga, f.inicio, f.local, f.visitante, elegidas,
                            float(p), float(cuota), tipo, sub, avisos))
    return sorted(lineas, key=lambda l: (-l.p, -l.cuota))


def preseleccion(lineas: list[Linea], n: int | None = None, cuota_objetivo: float | None = None,
                 max_lineas: int = 10) -> list[int]:
    """Índices de las líneas marcadas por defecto: las más probables hasta n o hasta la cuota objetivo."""
    elegidas, cuota = [], 1.0
    for i, l in enumerate(lineas):
        if n and len(elegidas) >= n:
            break
        if not n and cuota_objetivo and cuota >= cuota_objetivo:
            break
        if not n and not cuota_objetivo and len(elegidas) >= 4:
            break
        elegidas.append(i)
        cuota *= l.cuota
        if len(elegidas) >= max_lineas:
            break
    return elegidas


def a_boleta_vivo(lineas: list[Linea], marcadas: list[int], monto: float, titulo: str,
                  extras: int = 8) -> dict:
    """Datos para el componente de boleta en tiempo real (todas las cuentas se hacen en el navegador)."""
    from . import equipos as EQ
    mostrar = list(dict.fromkeys(marcadas + list(range(len(lineas)))))[: len(marcadas) + extras]
    out = []
    for i in mostrar:
        l = lineas[i]
        unico = len(l.patas) == 1
        s0 = l.patas[0].seleccion
        out.append({
            "id": l.id, "liga": l.liga, "liga_nombre": C.LIGAS.get(l.liga, l.liga),
            "hora": F.ahora_peru().strftime("%d/%m") if l.inicio is None else
            ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][l.inicio.dayofweek] + f" {l.inicio:%d/%m %H:%M}",
            "local": EQ.nombre(l.local), "visitante": EQ.nombre(l.visitante),
            "escudo_local": EQ.escudo_uri(l.local), "escudo_visitante": EQ.escudo_uri(l.visitante),
            "betano": EQ.enlace_liga(l.liga), "marcada": i in marcadas,
            "patas": [{"titulo": p.titulo, "mercado": p.mercado, "p": round(p.p, 4)} for p in l.patas],
            "sub": {str(k): v for k, v in l.subconjuntos.items()},
            "cuota": round(l.cuota, 2), "estimada": l.cuota_tipo == "estimada", "p": round(l.p, 4),
            "multibono_ok": unico and s0.mercado in B.MULTI_BONO_MERCADOS and l.liga in B.MULTI_BONO_LIGAS,
            "seguro_ok": unico and s0.mercado in B.SEGURO_MERCADOS,
            "avisos": l.avisos[:3],
        })
    return {"titulo": titulo, "monto": monto, "lineas": out, "multibono": B.MULTI_BONO_FUTBOL,
            "minimo": B.APUESTA_MINIMA}
