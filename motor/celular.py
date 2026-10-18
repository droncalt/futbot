"""Aprendizaje traído del celular por USB (actualizar_celular.bat → adb pull).

- Líneas que Betano ofrece (vistas en capturas) → conocimiento/betano_lineas.json, que usa el combinador y la nube.
- Resultado de cada pata de tus boletas → datos/celular/patas.csv (PRIVADO, no se sube) y un resumen por mercado:
  acierto real vs lo que prometía el bot. No cambia el modelo solo: con pocas patas el ruido domina (ver config).
"""
from __future__ import annotations

import json

import pandas as pd

from . import config as C

DIR = C.DIR_DATOS / "celular"
ARCHIVO = DIR / "futbot_aprendizaje.json"


def importar() -> dict:
    if not ARCHIVO.exists():
        return {"ok": False, "motivo": "No hay datos del celular (conéctalo y usa actualizar_celular.bat)."}
    d = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    nuevas = _lineas_betano(d.get("lineas_betano", {}))
    patas = _patas(d.get("boletas", []))
    DIR.mkdir(parents=True, exist_ok=True)
    patas.to_csv(DIR / "patas.csv", index=False, encoding="utf-8")
    resumen = []
    if not patas.empty:
        r = patas[patas["resultado"].isin(["ganada", "perdida"])]
        if not r.empty:
            g = r.assign(ok=r["resultado"].eq("ganada")).groupby("mercado").agg(
                patas=("ok", "size"), real=("ok", "mean"), bot=("p", "mean"))
            resumen = [{"mercado": m, "patas": int(x.patas), "real": round(float(x.real), 3),
                        "bot": round(float(x.bot), 3) if pd.notna(x.bot) else None} for m, x in g.iterrows()]
    return {"ok": True, "exportado": d.get("exportado"), "boletas": len(d.get("boletas", [])),
            "patas": len(patas), "lineas_betano_nuevas": nuevas, "por_mercado": resumen}


def _lineas_betano(cel: dict) -> list[str]:
    ruta = C.RUTA_LINEAS_BETANO
    cat = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    jug = cat.setdefault("jug_arco", {})
    nuevas = []
    for nombre, v in (cel.get("jug_arco") or {}).items():
        if v.get("min") is None:
            continue
        previo = jug.get(nombre, {})
        if previo.get("min") != v["min"]:
            nuevas.append(f"{nombre}: desde {v['min']}+")
        jug[nombre] = {"min": int(v["min"]), "visto": v.get("visto"), "fuente": "captura del usuario"}
    if nuevas:
        ruta.write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    return nuevas


def _patas(boletas: list) -> pd.DataFrame:
    filas = []
    for b in boletas:
        for l in b.get("lineas", []):
            for p in l.get("patas", []):
                s = p.get("sel") or {}
                filas.append({"boleta": b.get("id"), "fecha": b.get("fecha"), "origen": b.get("origen", "bot"),
                              "tipo": b.get("tipo"), "liga": l.get("liga"), "local": l.get("local"),
                              "visitante": l.get("visitante"), "mercado": s.get("mercado") or p.get("mercado"),
                              "opcion": s.get("opcion"), "linea": s.get("linea"), "jugador": s.get("jugador_nombre"),
                              "cuota": p.get("cuota"), "p": p.get("p"), "resultado": p.get("resultado")})
    return pd.DataFrame(filas)
