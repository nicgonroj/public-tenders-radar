"""Memoria del radar en SQLite.

Tablas:
- detalles: caché del JSON de detalle por código. Pedir un detalle es la consulta cara; con la caché
  cada oportunidad se pide una sola vez.
- oportunidades: lo que calzó con cada perfil, con la primera y la última vez que se vio. Es la base
  de la deduplicación: una oportunidad ya vista no vuelve a marcarse como "nueva".
- vistos_ca: códigos de compra ágil ya leídos en un barrido completo (permite barridos incrementales).
- corridas: registro de cada ejecución, para auditar que el radar corrió y qué encontró.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .modelos import Deteccion

ESQUEMA = """
create table if not exists detalles(
    codigo text primary key, fuente text, json text, fecha text);
create table if not exists oportunidades(
    codigo text, perfil text, fuente text, tipo text, nombre text, organismo text, region text,
    lugar text, cierre text, monto real, nivel text, calce text, detalle text, url text,
    primera_vez text, ultima_vez text, primary key(codigo, perfil));
create table if not exists vistos_ca(codigo text primary key, fecha text);
create table if not exists corridas(
    inicio text, fin text, modo text, licitaciones integer, compras_agiles integer,
    fallas text, resumen text);
"""


def abrir(ruta: Path | str) -> sqlite3.Connection:
    if str(ruta) != ":memory:":
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(ruta))
    db.executescript(ESQUEMA)
    return db


# --- Caché de detalles -----------------------------------------------------------------------

def tiene_detalle(db, codigo: str) -> bool:
    return db.execute("select 1 from detalles where codigo=?", (codigo,)).fetchone() is not None


def guardar_detalle(db, codigo: str, fuente: str, detalle: dict, ahora: datetime) -> None:
    db.execute("insert or replace into detalles values(?,?,?,?)",
               (codigo, fuente, json.dumps(detalle, ensure_ascii=False), ahora.isoformat()))


def detalle(db, codigo: str) -> dict:
    fila = db.execute("select json from detalles where codigo=?", (codigo,)).fetchone()
    return json.loads(fila[0]) if fila else {}


# --- Barrido incremental de compra ágil --------------------------------------------------------

def visto_ca(db, codigo: str) -> bool:
    return db.execute("select 1 from vistos_ca where codigo=?", (codigo,)).fetchone() is not None


def marcar_vistos_ca(db, codigos: list[str], ahora: datetime) -> None:
    db.executemany("insert or ignore into vistos_ca values(?,?)", [(c, ahora.isoformat()) for c in codigos])


# --- Deduplicación de detecciones -------------------------------------------------------------

def primera_vez(db, codigo: str, perfil: str) -> str | None:
    fila = db.execute("select primera_vez from oportunidades where codigo=? and perfil=?",
                      (codigo, perfil)).fetchone()
    return fila[0] if fila else None


def registrar_deteccion(db, d: Deteccion, primera: str, ahora: datetime) -> None:
    """Inserta o actualiza la detección conservando la fecha en que se vio por primera vez."""
    o = d.oportunidad
    db.execute("insert or replace into oportunidades values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (o.codigo, d.perfil, o.fuente, o.tipo, o.nombre, o.organismo, o.region, o.lugar,
                o.cierre.isoformat() if o.cierre else None, o.monto, d.nivel, ", ".join(d.calce),
                o.detalle[:600], o.url, primera, ahora.isoformat()))


def olvidar(db, codigo: str, perfil: str) -> None:
    """Quita una detección que dejó de calzar (por ejemplo, tras cambiar el perfil)."""
    db.execute("delete from oportunidades where codigo=? and perfil=?", (codigo, perfil))


def detecciones_recientes(db, perfil: str, desde: datetime) -> list[tuple]:
    return db.execute("""select codigo, fuente, tipo, nombre, organismo, region, lugar, cierre, monto,
                                detalle, url, primera_vez
                         from oportunidades where perfil=? and ultima_vez>=?""",
                      (perfil, desde.isoformat())).fetchall()


def registrar_corrida(db, inicio: datetime, fin: datetime, modo: str, stats: dict, resumen: dict) -> None:
    db.execute("insert into corridas values(?,?,?,?,?,?,?)",
               (inicio.isoformat(), fin.isoformat(), modo, stats.get("licitaciones"),
                stats.get("compras_agiles"), json.dumps(stats.get("fallas") or [], ensure_ascii=False),
                json.dumps(resumen, ensure_ascii=False)))
