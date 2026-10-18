"""Verificador de fijas y armado de boletas.

Para cada línea de la boleta (una selección simple o un Bet Builder) calcula:
* p_modelo: probabilidad del modelo estadístico propio;
* p_mercado: probabilidad del mercado sin margen (cuotas de referencia);
* p_final: combinación de ambas con el peso que justificó el backtest;
* valor esperado con la cuota de Betano que ingresa el usuario.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C
from . import datos, modelo
from . import mercados as M


@dataclass
class Grupo:
    """Una línea de la boleta: un partido con una o varias selecciones (Bet Builder)."""
    liga: str
    local: str
    visitante: str
    selecciones: list[M.Seleccion]
    cuota: float | None = None              # cuota que muestra Betano para esta línea
    fecha: str | None = None
    cuotas_ref: dict | None = None          # 1X2 (+ Más/Menos 2.5) para el modelo de mercado
    fuente: str = "propia"

    @property
    def bet_builder(self) -> bool:
        return len(self.selecciones) > 1

    def to_dict(self) -> dict:
        return {"liga": self.liga, "local": self.local, "visitante": self.visitante,
                "selecciones": [s.to_dict() for s in self.selecciones], "cuota": self.cuota,
                "fecha": self.fecha, "cuotas_ref": self.cuotas_ref, "fuente": self.fuente}

    @staticmethod
    def from_dict(d: dict) -> "Grupo":
        return Grupo(liga=d["liga"], local=d["local"], visitante=d["visitante"],
                     selecciones=[M.Seleccion(**s) for s in d["selecciones"]], cuota=d.get("cuota"),
                     fecha=d.get("fecha"), cuotas_ref=d.get("cuotas_ref"), fuente=d.get("fuente", "propia"))


# --- parámetros aprendidos en el backtest ---------------------------------------

def resumen_evaluacion() -> dict:
    ruta = C.DIR_EVALUACION / "resumen.json"
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def peso_modelo() -> tuple[float, str]:
    r = resumen_evaluacion()
    w = r.get("peso_modelo")
    if w is None:
        return C.PESO_MODELO_DEFECTO, "valor por defecto (aún no hay backtest)"
    return float(w), f"estimado en el backtest del {r.get('fecha', '?')}"


_cache_modelos: dict = {}


def cargar_modelo(liga: str) -> modelo.ModeloLiga | None:
    if liga not in C.LIGAS:
        return None
    carpeta = C.DIR_MODELOS / liga
    archivos = sorted(carpeta.glob("*.json")) if carpeta.exists() else []
    if not archivos:
        return None
    clave = (liga, archivos[-1].name)
    if clave not in _cache_modelos:
        _cache_modelos[clave] = modelo.cargar(liga)
    return _cache_modelos[clave]


def cuotas_proximo(liga: str, local: str, visitante: str) -> dict | None:
    """Cuotas de referencia del partido en la lista de próximos (si existe)."""
    px = datos.cargar_proximos()
    if px.empty:
        return None
    f = px[(px["liga"] == liga) & (px["local"] == local) & (px["visitante"] == visitante)]
    if f.empty:
        return None
    f = f.iloc[0]

    def trio(p):
        v = [f.get(p + k) for k in ("1", "x", "2")]
        return [float(x) for x in v] if datos.cuotas_sanas(*v, minimo=0.97, maximo=1.20) else None

    def par(p):
        v = [f.get(p + "o25"), f.get(p + "u25")]
        return [float(x) for x in v] if datos.cuotas_sanas(*v, minimo=0.97, maximo=1.15) else None

    # Betfair Exchange es la referencia más afilada, pero en mercados sin liquidez publica precios
    # absurdos: solo se usa si es sana y coherente con el promedio de casas.
    s3, c3, s2, c2 = trio("s_"), trio("c_"), par("s_"), par("c_")
    if s3 and (not c3 or datos.cuotas_coherentes(s3, c3)):
        t3, nombre = s3, "Betfair Exchange"
    elif c3:
        t3, nombre = c3, "promedio de casas"
    else:
        return None
    if s2 and (not c2 or datos.cuotas_coherentes(s2, c2)):
        t2 = s2
    else:
        t2 = c2
    out = {"1": t3[0], "x": t3[1], "2": t3[2], "fuente": nombre, "consulta": f.get("fuente_consulta")}
    if t2:
        out["o25"], out["u25"] = t2
    return out


def _evento_backtest(s: M.Seleccion) -> tuple[str, bool] | None:
    """Evento del backtest equivalente a la selección (y si es su complemento)."""
    o, L = s.opcion, s.linea
    if s.mercado == "1x2" and o in ("local", "visitante"):
        return ("Gana local" if o == "local" else "Gana visitante"), False
    if s.mercado == "doble" and o in ("1X", "X2"):
        return ("Local o empate" if o == "1X" else "Visitante o empate"), False
    if s.mercado == "goles":
        if L in (0.5, 1.5, 2.5):
            return f"Más de {L}", o == "menos"
        if L in (3.5, 4.5):
            return f"Menos de {L}", o == "mas"
    if s.mercado == "btts":
        return "Ambos anotan", o == "no"
    if s.mercado == "corners" and L in (8.5, 9.5, 10.5):
        return f"Córners más de {L}", o == "menos"
    if s.mercado == "tarjetas" and L in (3.5, 4.5):
        return f"Tarjetas más de {L}", o == "menos"
    return None


def evidencia(s: M.Seleccion, p: float | None, corta: bool = False) -> str | None:
    """Qué pasó en el backtest cuando el bot dio una probabilidad parecida a este mercado."""
    if p is None:
        return None
    if s.es_jugador:
        from . import modelo_jugadores as MJ
        return MJ.evidencia(int(s.opcion.rstrip("+")), s.escenario or MJ.ESCENARIO_DEFECTO, p, corta)
    ev = _evento_backtest(s)
    tabla = resumen_evaluacion().get("calibracion_por_evento", {})
    if ev is None or ev[0] not in tabla:
        return None
    nombre, invertido = ev
    q = 1 - p if invertido else p
    for b in tabla[nombre]:
        if b["lo"] < q <= b["hi"] and b["n"] >= 20:
            real = 1 - b["frecuencia_real"] if invertido else b["frecuencia_real"]
            est = 1 - b["prob_estimada"] if invertido else b["prob_estimada"]
            alerta = " ⚠️ el bot fue demasiado optimista en este rango" if est - real > 0.05 else ""
            if corta:
                return f"{real:.0%} real en {b['n']:,} casos" + (" ⚠️" if alerta else "")
            return (f"Backtest: cuando el bot dio ~{est:.0%} a este mercado, se cumplió el {real:.0%} "
                    f"({b['n']:,} casos).{alerta}")
    return None


# --- análisis ---------------------------------------------------------------------

def veredicto(valor: float | None, p: float | None, cuota: float | None) -> str:
    if p is None:
        return "⚪ Sin datos suficientes"
    if not cuota:
        return "Ingresa la cuota de Betano"
    if valor >= C.UMBRAL_VALOR:
        return "🟢 Cuota con valor"
    if valor <= -C.UMBRAL_VALOR:
        return "🔴 Mal pagada"
    return "🟡 Cuota justa (sin ventaja)"


def _probs_jugadores(g: Grupo, avisos: list[str]) -> dict[int, float | None]:
    """Probabilidad de cada pata «<Jugador> Tiros al Arco N+» (solo modelo: no hay mercado de referencia)."""
    idx = [i for i, s in enumerate(g.selecciones) if s.es_jugador]
    if not idx:
        return {}
    from . import modelo_jugadores as MJ
    est = MJ.estado_calibracion()
    if not est["hay_backtest"]:
        avisos.append(est["texto"])
        return {i: None for i in idx}
    mj = MJ.modelo_vigente()
    if mj is None:
        avisos.append("No hay datos de jugadores descargados: ejecuta «python -P bot.py jugadores --descargar».")
        return {i: None for i in idx}
    out = {}
    for i in idx:
        s = g.selecciones[i]
        es_local = None if s.lado not in ("local", "visitante") else s.lado == "local"
        rival = None if es_local is None else (g.visitante if es_local else g.local)
        r = mj.predecir(s.jugador, g.liga, rival, es_local)
        if r is None:
            avisos.append(f"{s.jugador_nombre}: no aparece en los datos de jugadores.")
            out[i] = None
            continue
        k, esc = int(s.opcion.rstrip("+")), s.escenario or MJ.ESCENARIO_DEFECTO
        ps = r["probs"]
        out[i] = ps[esc][k]
        avisos.append(
            f"{r['jugador']} {k}+ tiros al arco depende de que sea titular y de cuántos minutos juegue: titular "
            f"{ps['titular'][k]:.0%} · juega (titular o suplente) {ps['sin_confirmar'][k]:.0%} · si entra desde el banco "
            f"{ps['suplente'][k]:.0%} (se usó «{MJ.ESCENARIOS[esc]}»). {MJ.REGLA_BETANO}")
        avisos += [f"{r['jugador']}: {a}" for a in r["avisos"]]
    if not est["calibrado"]:
        avisos.append(est["texto"])
    if len(idx) < len(g.selecciones) or len(idx) > 1:
        avisos.append("Se asume independencia entre los tiros al arco del jugador y las otras patas (aproximación: "
                      "si su equipo domina, suelen subir juntas).")
    return out


def analizar_grupo(g: Grupo, w: float | None = None) -> dict:
    if w is None:
        w, _ = peso_modelo()
    avisos: list[str] = []
    p_jug = _probs_jugadores(g, avisos)
    hay_equipo = len(p_jug) < len(g.selecciones)
    ml = cargar_modelo(g.liga)
    motor_mod = None
    if ml is not None and ml.ft is not None:
        faltan = [e for e in (g.local, g.visitante) if not ml.ft.tiene(e)]
        if faltan:
            avisos.append(f"No encontré a {', '.join(faltan)} en los datos de {C.LIGAS[g.liga]}.")
        else:
            motor_mod = M.MotorPartido.desde_modelo(ml, g.local, g.visitante)
    elif g.liga != C.OTRA_COMPETICION:
        avisos.append("Esta liga todavía no tiene modelo ajustado.")

    cuotas_ref = g.cuotas_ref
    if not cuotas_ref and g.liga in C.LIGAS_EUROPA:
        cuotas_ref = cuotas_proximo(g.liga, g.local, g.visitante)
    motor_mer = M.motor_mercado(g.local, g.visitante, cuotas_ref, ml) if cuotas_ref else None
    if motor_mer is None and g.liga == C.OTRA_COMPETICION and hay_equipo:
        avisos.append("Para partidos de otras competiciones ingresa las cuotas 1X2 (y Más/Menos 2.5) que ves en Betano.")

    r_mod = motor_mod.prob(g.selecciones) if motor_mod else None
    r_mer = motor_mer.prob(g.selecciones) if motor_mer else None
    for r in (r_mod, r_mer):
        if r:
            for a in r["avisos"]:
                if a not in avisos:
                    avisos.append(a)

    patas = []
    for i, s in enumerate(g.selecciones):
        if s.es_jugador:
            pm, pk = p_jug.get(i), None
        else:
            pm = r_mod["individuales"][i] if r_mod else None
            pk = r_mer["individuales"][i] if r_mer else None
        tit, sub = s.etiqueta(g.local, g.visitante)
        pf = M.combinar(pm, pk, w)
        patas.append({"titulo": tit, "mercado": sub, "p_modelo": pm, "p_mercado": pk,
                      "p_final": pf, "evidencia": evidencia(s, pf)})

    p_mod = r_mod["conjunta"] if r_mod else None
    p_mer = r_mer["conjunta"] if r_mer else None
    p_fin = M.combinar(p_mod, p_mer, w)
    if p_jug:  # patas de jugador: solo modelo, independientes del resto (aproximación avisada)
        pj = None if any(v is None for v in p_jug.values()) else float(np.prod(list(p_jug.values())))
        if not hay_equipo:
            p_mod, p_mer, p_fin = pj, None, pj
        else:
            p_mod, p_mer, p_fin = (None if (x is None or pj is None) else x * pj for x in (p_mod, p_mer, p_fin))
    valor = (p_fin * g.cuota - 1) if (p_fin is not None and g.cuota) else None
    texto_veredicto = veredicto(valor, p_fin, g.cuota)
    if p_mod is not None and p_mer is None and hay_equipo:
        avisos.append("Sin cuotas de mercado para este partido: la probabilidad es SOLO del modelo, que en el "
                      "backtest fue menos preciso que el mercado. Ingresa las cuotas 1X2 y Más/Menos 2.5 de Betano "
                      "(en «Cuotas de referencia») para un veredicto más fiable.")
        if valor is not None and valor >= C.UMBRAL_VALOR:
            texto_veredicto += " (solo según el modelo: confírmalo con las cuotas 1X2)"
    if p_mod is not None and p_mer is not None and abs(p_mod - p_mer) > C.UMBRAL_DISCREPANCIA:
        avisos.append(
            f"El modelo ({p_mod:.0%}) y el mercado ({p_mer:.0%}) discrepan: revisa lesiones, "
            "rotaciones y alineaciones antes de decidir. Normalmente el mercado sabe algo que el modelo no.")
    return {
        "grupo": g, "patas": patas, "p_modelo": p_mod, "p_mercado": p_mer, "p_final": p_fin,
        "cuota": g.cuota, "p_implicita": (1 / g.cuota) if g.cuota else None,
        "cuota_justa": (1 / p_fin) if p_fin else None, "valor": valor,
        "veredicto": texto_veredicto, "avisos": avisos,
        "cuotas_ref": cuotas_ref, "peso_modelo": w,
        "lambdas_modelo": (motor_mod.lam, motor_mod.mu) if motor_mod else None,
        "lambdas_mercado": (motor_mer.lam, motor_mer.mu) if motor_mer else None,
        "version_modelo": ml.version if ml else None,
    }


def analizar_boleta(grupos: list[Grupo], importe: float = 0.0) -> dict:
    w, origen_w = peso_modelo()
    lineas = [analizar_grupo(g, w) for g in grupos]
    ps = [l["p_final"] for l in lineas]
    cuotas = [l["cuota"] for l in lineas]
    p_total = float(np.prod(ps)) if ps and all(p is not None for p in ps) else None
    cuota_total = float(np.prod(cuotas)) if cuotas and all(cuotas) else None
    avisos = []
    partidos = [(g.local, g.visitante) for g in grupos]
    if len(set(partidos)) < len(partidos):
        avisos.append("Hay dos líneas del mismo partido: Betano obliga a juntarlas en un Bet Builder.")
    if len(grupos) >= 4 and p_total is not None:
        avisos.append(
            f"Con {len(grupos)} líneas la probabilidad de acertar todas cae a {p_total:.0%}, aunque cada una "
            "parezca segura. Cada pata extra multiplica la cuota y también el riesgo.")
    debil = None
    if all(p is not None for p in ps) and len(ps) > 1:
        i = int(np.argmin(ps))
        resto_p = float(np.prod([p for j, p in enumerate(ps) if j != i]))
        resto_c = float(np.prod([c for j, c in enumerate(cuotas) if j != i])) if cuota_total else None
        debil = {"indice": i, "p": ps[i], "p_sin_ella": resto_p, "cuota_sin_ella": resto_c}
    valor = (p_total * cuota_total - 1) if (p_total is not None and cuota_total) else None
    return {
        "lineas": lineas, "p_total": p_total, "cuota_total": cuota_total, "importe": importe,
        "ganancia_potencial": importe * cuota_total if cuota_total else None,
        "valor": valor, "retorno_esperado": importe * p_total * cuota_total if valor is not None else None,
        "pata_mas_debil": debil, "avisos": avisos, "peso_modelo": w, "origen_peso": origen_w,
    }


SELECCIONES_TABLA = [
    ("1", M.Seleccion("1x2", "local")), ("X", M.Seleccion("1x2", "empate")), ("2", M.Seleccion("1x2", "visitante")),
    ("1X", M.Seleccion("doble", "1X")), ("X2", M.Seleccion("doble", "X2")),
    ("Más 1.5", M.Seleccion("goles", "mas", 1.5)), ("Más 2.5", M.Seleccion("goles", "mas", 2.5)),
    ("Menos 3.5", M.Seleccion("goles", "menos", 3.5)), ("Ambos anotan", M.Seleccion("btts", "si")),
]


def tabla_proximos() -> pd.DataFrame:
    """Probabilidades del bot para los mercados más jugados de cada partido próximo."""
    px = datos.cargar_proximos()
    if px.empty:
        return px
    w, _ = peso_modelo()
    filas = []
    for _, f in px.iterrows():
        ml = cargar_modelo(f.liga)
        mod = None
        if ml and ml.ft.tiene(f.local) and ml.ft.tiene(f.visitante):
            mod = M.MotorPartido.desde_modelo(ml, f.local, f.visitante)
        ref = cuotas_proximo(f.liga, f.local, f.visitante)
        mer = M.motor_mercado(f.local, f.visitante, ref, ml) if ref else None
        fila = {"fecha": f.fecha, "hora": f.hora, "liga": f.liga, "local": f.local, "visitante": f.visitante,
                "goles_esperados": round(mod.lam + mod.mu, 2) if mod else None}
        for nombre, s in SELECCIONES_TABLA:
            pm = mod.prob([s])["conjunta"] if mod else None
            pk = mer.prob([s])["conjunta"] if mer else None
            fila[nombre] = M.combinar(pm, pk, w)
        fila["cuota_1"], fila["cuota_x"], fila["cuota_2"] = f.get("c_1"), f.get("c_x"), f.get("c_2")
        filas.append(fila)
    return pd.DataFrame(filas)


def texto_boleta(res: dict) -> str:
    """Versión en texto para copiar (WhatsApp/Telegram/notas)."""
    lineas = res["lineas"]
    n = len(lineas)
    cab = "Simple" if n == 1 else ("Doble" if n == 2 else f"Combinada de {n}")
    out = [f"{cab}  ·  propuesta del bot (no es un comprobante)", ""]
    for l in lineas:
        g = l["grupo"]
        cuota = f"{l['cuota']:.2f}" if l["cuota"] else "—"
        if g.bet_builder:
            out.append(f"⚽ Bet Builder  [{cuota}]")
        else:
            out.append(f"⚽ {l['patas'][0]['titulo']}  [{cuota}]")
            out.append(f"   {l['patas'][0]['mercado']}")
        out.append(f"   {g.local} vs {g.visitante}")
        if g.bet_builder:
            for p in l["patas"]:
                out.append(f"   • {p['titulo']} — {p['mercado']}")
        pf = l["p_final"]
        out.append(f"   Prob. estimada: {pf:.0%}" if pf is not None else "   Prob. estimada: sin datos")
        out.append("")
    if res["cuota_total"]:
        out.append(f"Cuota total: {res['cuota_total']:.2f}")
    if res["importe"]:
        out.append(f"Apuesta: S/{res['importe']:.2f}")
        if res["ganancia_potencial"]:
            out.append(f"Ganancias potenciales: S/{res['ganancia_potencial']:.2f}")
    if res["p_total"] is not None:
        out.append(f"Probabilidad de acertar todo: {res['p_total']:.0%}")
    return "\n".join(out)
