"""Línea de comandos del radar.

Ejemplos:
    PYTHONPATH=src python -m tenders_radar --offline              # demo sin red ni ticket
    export MERCADOPUBLICO_TICKET=...                               # ticket propio
    PYTHONPATH=src python -m tenders_radar                         # corrida diaria en línea
    PYTHONPATH=src python -m tenders_radar --barrido-completo      # compra ágil completa (lento)
    PYTHONPATH=src python -m tenders_radar --reclasificar          # re-filtrar tras editar perfiles
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from . import almacen
from .api import VARIABLE_TICKET, ClienteMercadoPublico, TransporteHTTP, leer_ticket
from .barrido import barrer_compra_agil, barrer_licitaciones
from .clasificacion import clasificar, recuperar_recientes
from .modelos import CL, Oportunidad
from .offline import CARPETA_FIXTURES, FECHA_DEMO, TransporteFixtures
from .perfiles import cargar_configuracion, cargar_perfiles
from .reporte import escribir_csv, escribir_markdown


def argumentos(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="tenders_radar",
                                 description="Radar de licitaciones y compras ágiles de Mercado Público.")
    ap.add_argument("--offline", action="store_true",
                    help="modo demo: usa los fixtures sintéticos en vez de la API (no requiere ticket)")
    ap.add_argument("--perfiles", type=Path,
                    help="JSON de perfiles (por defecto profiles.json si existe, si no profiles.example.json)")
    ap.add_argument("--salida", type=Path, default=Path("output"), help="carpeta del resumen y el CSV")
    ap.add_argument("--db", type=Path,
                    help="base SQLite de memoria (por defecto data/radar.sqlite; en offline data/demo.sqlite)")
    ap.add_argument("--fixtures", type=Path, default=CARPETA_FIXTURES, help="carpeta de fixtures del modo offline")
    ap.add_argument("--ahora", help="fecha y hora de referencia ISO (por defecto: ahora; en offline, la fecha de los fixtures)")
    ap.add_argument("--solo", choices=["licitaciones", "compra-agil"], help="correr una sola fuente")
    ap.add_argument("--barrido-completo", action="store_true",
                    help="compra ágil: leer todas las publicadas de forma incremental en vez de buscar por términos")
    ap.add_argument("--max-paginas", type=int, default=600, help="máximo de páginas del barrido completo")
    ap.add_argument("--tope-detalles", type=int, default=400, help="máximo de detalles nuevos por fuente y corrida")
    ap.add_argument("--hilos", type=int, default=4, help="consultas simultáneas a la API de Compra Ágil")
    ap.add_argument("--reclasificar", action="store_true",
                    help="no consulta ninguna fuente: vuelve a filtrar la última corrida con los perfiles actuales")
    ap.add_argument("--silencioso", action="store_true", help="no imprimir el avance")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    a = argumentos(argv)
    log = (lambda _m: None) if a.silencioso else (lambda m: print(m, flush=True))

    ruta_perfiles = a.perfiles or (Path("profiles.json") if Path("profiles.json").exists() else Path("profiles.example.json"))
    cfg = cargar_configuracion(ruta_perfiles)
    perfiles = cargar_perfiles(cfg)
    plazos = cfg["plazo_critico_horas"]

    if a.ahora:
        ahora = datetime.fromisoformat(a.ahora)
        ahora = ahora if ahora.tzinfo else ahora.replace(tzinfo=CL)
    else:
        ahora = FECHA_DEMO if a.offline else datetime.now(CL)

    db_ruta = a.db or Path("data") / ("demo.sqlite" if a.offline else "radar.sqlite")
    db = almacen.abrir(db_ruta)
    cache_corrida = db_ruta.with_name(db_ruta.stem + "-ultima-corrida.json")

    if a.offline:
        transporte = TransporteFixtures(a.fixtures)
        cliente = ClienteMercadoPublico(transporte, ticket="demo", pausa_licitaciones=0)
        modo = "offline (fixtures sintéticos)"
    elif not a.reclasificar:
        ticket = leer_ticket()
        if not ticket:
            print(f"Falta el ticket: define la variable de entorno {VARIABLE_TICKET} "
                  "o usa --offline para la demo con datos sintéticos.", file=sys.stderr)
            return 2
        cliente = ClienteMercadoPublico(TransporteHTTP(registro=log), ticket)
        modo = "en línea (API de Mercado Público)"
    else:
        cliente, modo = None, "reclasificar (sin consultar la API)"

    log(f"Radar · {modo} · perfiles: {ruta_perfiles} ({len(perfiles)}) · referencia {ahora:%Y-%m-%d %H:%M}")
    stats: dict = {"fallas": [], "topes": []}
    oportunidades: list[Oportunidad] = []

    if a.reclasificar:
        if not cache_corrida.exists():
            print(f"No hay una corrida previa guardada en {cache_corrida}.", file=sys.stderr)
            return 2
        guardado = json.loads(cache_corrida.read_text(encoding="utf-8"))
        stats = guardado["stats"]
        oportunidades = [Oportunidad.desde_json(o) for o in guardado["oportunidades"]]
    else:
        if a.solo != "compra-agil":
            ops, s = barrer_licitaciones(cliente, perfiles, db, a.tope_detalles, ahora, log)
            oportunidades += ops
            stats["fallas"] += s.pop("fallas")
            stats.update(s)
        if a.solo != "licitaciones":
            ops, s = barrer_compra_agil(cliente, perfiles, db, a.tope_detalles, a.barrido_completo,
                                        a.max_paginas, ahora, log, hilos=a.hilos)
            oportunidades += ops
            stats["fallas"] += s.pop("fallas")
            stats["topes"] += s.pop("topes")
            stats.update(s)
        cache_corrida.write_text(json.dumps({"stats": stats, "oportunidades": [o.a_json() for o in oportunidades]},
                                            ensure_ascii=False), encoding="utf-8")
    stats["sin_detalle"] = sum(1 for o in oportunidades if not o.con_detalle)

    resultado, descartes = clasificar(oportunidades, perfiles, db, ahora, plazos)
    recuperadas = recuperar_recientes(resultado, perfiles, db, ahora, plazos)
    if recuperadas:
        log(f"Recuperadas de corridas recientes y aún abiertas: {recuperadas}")

    md = escribir_markdown(resultado, descartes, stats, plazos, ahora, a.salida / f"radar-{ahora:%Y-%m-%d}.md", modo)
    csv_ = escribir_csv(resultado, ahora, a.salida / f"radar-{ahora:%Y-%m-%d}.csv")
    resumen = {p: {"claro": sum(d.nivel == "A" for d in ds), "revisar": sum(d.nivel == "B" for d in ds),
                   "nuevas": sum(d.nueva for d in ds)} for p, ds in resultado.items()}
    almacen.registrar_corrida(db, ahora, datetime.now(CL) if not a.offline else ahora, modo, stats, resumen)
    db.commit()
    db.close()

    for p, r in resumen.items():
        log(f"{p}: {r['claro']} con calce claro, {r['revisar']} para revisar, {r['nuevas']} nuevas")
    log(f"Resumen: {md}")
    log(f"CSV: {csv_}")
    return 0
