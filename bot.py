"""Línea de comandos del bot (la usa también la skill de informes de Claude Code).

Ejemplos:
  python -P bot.py actualizar                 # descarga datos, re-ajusta modelos, liquida boletas
  python -P bot.py backtest                   # evalúa el modelo en la temporada pasada
  python -P bot.py equipos --liga SP1         # nombres exactos de los equipos
  python -P bot.py proximos --liga E0         # próximos partidos con probabilidades
  python -P bot.py analizar --liga SP1 --local Barcelona --visitante Getafe
  python -P bot.py analizar --liga OTRA --local Inter --visitante "Club Brugge" --cuotas 1.30,5.5,9.0 --ou 1.65,2.20
  python -P bot.py analizar --liga E0 --local "Man City" --visitante Arsenal --jugador Haaland
  python -P bot.py jugadores --descargar      # datos de jugadores (API-Football con .env, o Understat)
  python -P bot.py jugadores --plan           # clave, plan y consultas de hoy de API-Football
  python -P bot.py jugadores --buscar Lautaro
  python -P bot.py backtest-jugadores         # calibración del mercado «<Jugador> Tiros al Arco»
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd

from motor import analisis as A
from motor import config as C
from motor import datos, ficha, modelo, registro
from motor import evaluacion as E
from motor import mercados as M


def _imprimir(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def cmd_actualizar(a):
    res = datos.actualizar(forzar=a.forzar, progreso=lambda p, m: print(f"{p:4.0%} {m}", file=sys.stderr))
    print(res["estado"].value_counts().to_string())
    df = datos.cargar_partidos()
    print(modelo.ajustar_todas(df).to_string())
    if not a.sin_jugadores:  # la nube lo omite: el historial de Understat tarda >40 min la 1.ª vez
        try:  # datos de jugadores (incremental: solo los partidos nuevos)
            from motor import jugadores as J
            print(J.actualizar(progreso=lambda m: print(m, file=sys.stderr, flush=True)).to_string(index=False))
        except Exception as e:  # sin internet, cambios en la fuente, etc.: no frena el resto
            print("Datos de jugadores: no se pudieron actualizar:", type(e).__name__, e)
    print("Líneas liquidadas:", registro.liquidar_automatico(df))
    q = datos.calidad_datos(df)
    print("Calidad:", {k: v for k, v in q.items() if k != "problemas"}, "| problemas:", len(q["problemas"]))


def cmd_backtest(a):
    r = E.ejecutar_backtest(datos.cargar_partidos(), ligas=a.ligas,
                            progreso=lambda p, m: print(f"{p:4.0%} {m}", file=sys.stderr))
    _imprimir({k: r[k] for k in ("fecha", "partidos", "peso_modelo", "logloss_global", "fijas_global")}
              | {"comparacion_mismo_partido": r.get("comparacion_mismo_partido")})


def cmd_equipos(a):
    print("\n".join(datos.equipos_de_liga(a.liga)))


def cmd_proximos(a):
    t = A.tabla_proximos()
    if a.liga:
        t = t[t["liga"] == a.liga]
    cols = [n for n, _ in A.SELECCIONES_TABLA]
    t = t.copy()
    t[cols] = (t[cols] * 100).round(1)
    print(t[["fecha", "hora", "liga", "local", "visitante", "goles_esperados"] + cols].to_string(index=False))


def _cuotas(a) -> dict | None:
    if not a.cuotas:
        return None
    c1, cx, c2 = (float(v) for v in a.cuotas.split(","))
    out = {"1": c1, "x": cx, "2": c2, "fuente": "cuotas ingresadas"}
    if a.ou:
        o, u = (float(v) for v in a.ou.split(","))
        out.update({"o25": o, "u25": u})
    return out


def cmd_analizar(a):
    """Salida JSON con todo lo que el modelo sabe del partido (para el informe A–J)."""
    df = datos.cargar_partidos()
    liga = a.liga.upper()
    cuotas = _cuotas(a) or (A.cuotas_proximo(liga, a.local, a.visitante) if liga in C.LIGAS_EUROPA else None)
    ml = A.cargar_modelo(liga)
    w, origen_w = A.peso_modelo()
    out = {"partido": f"{a.local} vs {a.visitante}", "liga": C.LIGAS.get(liga, "Otra competición"),
           "fuente_datos": C.FUENTE_NOMBRE, "ultima_consulta_datos": datos.ultima_descarga(),
           "version_modelo": ml.version if ml else None, "peso_modelo_vs_mercado": w, "origen_peso": origen_w,
           "cuotas_referencia": cuotas, "avisos": []}
    mod = None
    if ml and ml.ft.tiene(a.local) and ml.ft.tiene(a.visitante):
        mod = M.MotorPartido.desde_modelo(ml, a.local, a.visitante)
        out["avisos"] += mod.avisos
    elif liga in C.LIGAS:
        out["avisos"].append("Equipo no encontrado: revisa los nombres con 'bot.py equipos --liga " + liga + "'.")
    mer = M.motor_mercado(a.local, a.visitante, cuotas, ml) if cuotas else None
    if mer:
        out["avisos"] += mer.avisos
    base = mod or mer
    if base is None:
        out["error"] = "Sin modelo ni cuotas: no se puede calcular nada."
        _imprimir(out)
        return
    out["goles_esperados"] = {"modelo": (round(mod.lam, 3), round(mod.mu, 3)) if mod else None,
                              "mercado": (round(mer.lam, 3), round(mer.mu, 3)) if mer else None}
    out["marcadores_probables"] = [(s, round(p, 4)) for s, p in base.marcadores_probables(8)]
    out["medias_corners_tarjetas"] = base.medias_conteo()
    fm = mod.resumen_mercados() if mod else None
    fk = mer.resumen_mercados() if mer else None
    filas = []
    for i, f in enumerate(fm or fk):
        pm = fm[i]["p"] if fm else None
        pk = fk[i]["p"] if fk and i < len(fk) and fk[i]["opcion"] == f["opcion"] else None
        pf = M.combinar(pm, pk, w)
        filas.append({"mercado": f["mercado"], "seleccion": f["opcion"],
                      "p_modelo": None if pm is None else round(pm, 4),
                      "p_mercado": None if pk is None else round(pk, 4),
                      "p_bot": None if pf is None else round(pf, 4),
                      "cuota_justa": None if not pf else round(1 / pf, 3),
                      "evidencia_backtest": A.evidencia(f["seleccion"], pf)})
    out["mercados"] = filas
    if liga in C.LIGAS:
        temp = ficha.temporada_actual() if liga in C.LIGAS_EUROPA else None
        for lado, eq in (("local", a.local), ("visitante", a.visitante)):
            out[f"ficha_{lado}"] = {
                "resumen_temporada": ficha.resumen(df, eq, liga, temp).to_dict("records"),
                "ultimos_8": ficha.ultimos(df, eq, 8).to_dict("records"),
            }
        out["h2h"] = ficha.h2h(df, a.local, a.visitante).to_dict("records")
    out["tiros_al_arco_jugadores"] = _jugadores_partido(liga, a.local, a.visitante, a.jugador)
    _imprimir(out)


def _jugadores_partido(liga: str, local: str, visitante: str, filtro: str | None = None, n: int = 8) -> dict:
    """Mercado «<Jugador> Tiros al Arco» (para el informe A–J): ver modelo_jugadores.jugadores_partido."""
    from motor import modelo_jugadores as MJ
    return MJ.jugadores_partido(liga, local, visitante, n=n, jugador=filtro)


def cmd_backtest_jugadores(a):
    from motor import evaluacion_jugadores as EJ
    r = EJ.backtest_jugadores(progreso=lambda p, m: print(f"{p:4.0%} {m}", file=sys.stderr, flush=True))
    _imprimir({k: r[k] for k in ("fecha", "fuente", "periodo_ajuste", "periodo_validacion", "filas", "parametros",
                                 "comparacion", "calibrado", "contraste_definicion")})


def cmd_jugadores(a):
    """Datos de jugadores: descarga incremental, estado de la clave/cuota y búsqueda de nombres."""
    from motor import jugadores as J
    if a.descargar:
        fuentes = [a.fuente] if a.fuente else None
        res = J.actualizar(progreso=lambda m: print(m, file=sys.stderr, flush=True), fuentes=fuentes,
                           max_partidos=a.max_partidos)
        print(res.to_string(index=False))
    if a.plan:
        _imprimir({"clave_en_env": bool(J.leer_clave()), "plan": J.estado_plan() if J.leer_clave() else None,
                   "consumo_hoy": J.consumo_api(), "consultas_disponibles": J.consultas_disponibles()})
    fuente = a.fuente or J.fuente_activa()
    if a.buscar:
        ap = J.cargar_apariciones(fuente)
        import unicodedata

        def norm(s):
            return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
        q = norm(a.buscar)
        d = ap[ap["jugador"].map(norm).str.contains(q, regex=False)]
        print(d.groupby(["jugador_id", "jugador"]).agg(equipo=("equipo", "last"), partidos=("partido_id", "nunique"),
                                                      ultimo=("fecha", "max")).reset_index().to_string(index=False))
    if not (a.descargar or a.plan or a.buscar):
        print("Fuente activa:", fuente)
        print(J.cobertura(fuente).to_string(index=False))


def cmd_exportar(a):
    """Paquete diario para la app del celular (publicar/paquete.json + escudos)."""
    from motor import exportar
    print(exportar.exportar(jugadores=not a.sin_jugadores))


def main():
    p = argparse.ArgumentParser(description="Bot analítico de fútbol")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("actualizar"); s.add_argument("--forzar", action="store_true")
    s.add_argument("--sin-jugadores", action="store_true"); s.set_defaults(f=cmd_actualizar)
    s = sub.add_parser("backtest"); s.add_argument("--ligas", nargs="*"); s.set_defaults(f=cmd_backtest)
    s = sub.add_parser("equipos"); s.add_argument("--liga", required=True); s.set_defaults(f=cmd_equipos)
    s = sub.add_parser("proximos"); s.add_argument("--liga"); s.set_defaults(f=cmd_proximos)
    s = sub.add_parser("exportar"); s.add_argument("--sin-jugadores", action="store_true"); s.set_defaults(f=cmd_exportar)
    s = sub.add_parser("analizar")
    s.add_argument("--liga", required=True, help="Código de liga (E0, SP1…) u OTRA")
    s.add_argument("--local", required=True); s.add_argument("--visitante", required=True)
    s.add_argument("--cuotas", help="1,X,2 de Betano, ej. 1.30,5.5,9.0")
    s.add_argument("--ou", help="Más 2.5, Menos 2.5, ej. 1.65,2.20")
    s.add_argument("--jugador", help="Filtra los tiros al arco de jugadores por nombre, ej. Haaland")
    s.set_defaults(f=cmd_analizar)
    s = sub.add_parser("backtest-jugadores", help="Backtest walk-forward de tiros al arco de jugadores")
    s.set_defaults(f=cmd_backtest_jugadores)
    s = sub.add_parser("jugadores", help="Datos de jugadores (tiros al arco)")
    s.add_argument("--descargar", action="store_true", help="Descarga lo que falta (incremental)")
    s.add_argument("--fuente", choices=["apifootball", "understat"])
    s.add_argument("--max-partidos", type=int, help="Máximo de partidos nuevos por liga y temporada (Understat)")
    s.add_argument("--plan", action="store_true", help="Estado de la clave, el plan y la cuota de API-Football")
    s.add_argument("--buscar", help="Busca un jugador por nombre, ej. Haaland")
    s.set_defaults(f=cmd_jugadores)
    a = p.parse_args()
    pd.set_option("display.width", 200)
    a.f(a)


if __name__ == "__main__":
    main()
