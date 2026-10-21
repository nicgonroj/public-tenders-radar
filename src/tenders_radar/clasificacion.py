"""Clasificación: cruza cada oportunidad con cada perfil, deduplica contra la memoria y prioriza."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from . import almacen
from .modelos import COMPRA_AGIL, Deteccion, Oportunidad
from .perfiles import Perfil


def clasificar(oportunidades: list[Oportunidad], perfiles: list[Perfil], db, ahora: datetime,
               plazos: dict) -> tuple[dict[str, list[Deteccion]], dict[str, Counter]]:
    """Devuelve (detecciones por perfil, motivos de descarte por perfil).

    Una oportunidad es "nueva" para un perfil si no estaba en la memoria antes de esta corrida.
    Lo que deja de calzar (cambió el perfil o la zona) se olvida de la memoria.
    """
    resultado = {p.nombre: [] for p in perfiles}
    descartes = {p.nombre: Counter() for p in perfiles}
    vistos = set()                                     # dedup dentro de la corrida
    for o in oportunidades:
        if o.cierre and o.cierre < ahora:
            for p in perfiles:
                descartes[p.nombre]["ya cerrada"] += 1
            continue
        for p in perfiles:
            if (o.codigo, p.nombre) in vistos:
                continue
            vistos.add((o.codigo, p.nombre))
            ev = p.evaluar(o.nombre, o.detalle)
            if not ev.nivel:
                descartes[p.nombre][_motivo_corto(ev.motivo_descarte)] += 1
                continue
            dentro, preferida = p.en_zona(o.region, o.lugar or o.organismo)
            if not dentro or not p.en_rango_monto(o.monto):
                descartes[p.nombre]["fuera de zona" if not dentro else "fuera del rango de monto"] += 1
                almacen.olvidar(db, o.codigo, p.nombre)
                continue
            previa = almacen.primera_vez(db, o.codigo, p.nombre)
            d = Deteccion(o, p.nombre, ev.nivel, ev.calce, nueva=previa is None, preferida=preferida)
            d.orden, d.prioridad = prioridad(d, ahora, plazos)
            almacen.registrar_deteccion(db, d, previa or ahora.isoformat(), ahora)
            resultado[p.nombre].append(d)
    db.commit()
    for dets in resultado.values():
        dets.sort(key=clave_orden)
    return resultado, descartes


def _motivo_corto(motivo: str) -> str:
    """Agrupa los motivos para el conteo: 'exclusión: x' -> 'exclusión'."""
    return motivo.split(":")[0] if motivo else "sin palabras del perfil"


def recuperar_recientes(resultado: dict[str, list[Deteccion]], perfiles: list[Perfil], db,
                        ahora: datetime, plazos: dict, horas: int = 26) -> int:
    """Suma lo que otra corrida reciente detectó y sigue abierto.

    Sirve para combinar una búsqueda rápida de la mañana con un barrido completo nocturno: el resumen
    muestra ambas. Se vuelve a evaluar con el perfil vigente; lo que ya no calza se olvida.
    """
    agregadas = 0
    desde = ahora - timedelta(hours=horas)
    for p in perfiles:
        ya = {d.oportunidad.codigo for d in resultado[p.nombre]}
        for (codigo, fuente, tipo, nombre, org, region, lugar, cierre, monto, detalle, url,
             primera) in almacen.detecciones_recientes(db, p.nombre, desde):
            c = datetime.fromisoformat(cierre) if cierre else None
            if codigo in ya or (c and c < ahora):
                continue
            ev = p.evaluar(nombre, detalle or "")
            dentro, preferida = p.en_zona(region, lugar or org)
            if not ev.nivel or not dentro or not p.en_rango_monto(monto):
                almacen.olvidar(db, codigo, p.nombre)
                continue
            o = Oportunidad(codigo=codigo, fuente=fuente, nombre=nombre, detalle=detalle or "", tipo=tipo,
                            organismo=org, region=region, lugar=lugar, cierre=c, monto=monto, url=url,
                            con_detalle=True)
            d = Deteccion(o, p.nombre, ev.nivel, ev.calce, nueva=False, preferida=preferida)
            d.orden, d.prioridad = prioridad(d, ahora, plazos)
            resultado[p.nombre].append(d)
            agregadas += 1
        resultado[p.nombre].sort(key=clave_orden)
    db.commit()
    return agregadas


# --- Priorización ------------------------------------------------------------------------------

def clave_orden(d: Deteccion):
    """Primero la prioridad; a igual prioridad, lo que cierra antes."""
    c = d.oportunidad.cierre
    return (d.orden, c.timestamp() if c else float("inf"))


def prioridad(d: Deteccion, ahora: datetime, plazos: dict) -> tuple[float, str]:
    """Cruza tipo de proceso, cercanía del cierre y calidad del calce. Menor orden = antes.

    Reglas:
    - Compra ágil: plazos cortos (días). Si cierra dentro del plazo crítico, "Cotizar hoy".
      Un segundo llamado va primero: el primero quedó desierto y suele haber menos competencia.
    - Licitación: necesita preparar documentos. Menos de 24 h es "Sin tiempo"; dentro del plazo
      crítico, "Urgente: decidir hoy"; hasta 10 días, "Preparar"; más allá, "Planificar".
    - Calce B (revisar) baja tres posiciones respecto del A.
    - Comprador en comuna preferida del perfil sube un poco y se marca con ★.
    """
    o = d.oportunidad
    horas = (o.cierre - ahora).total_seconds() / 3600 if o.cierre else None
    extra = 3 if d.nivel == "B" else 0
    sufijo = " (revisar calce)" if d.nivel == "B" else ""

    if o.fuente == COMPRA_AGIL:
        hoy = horas is not None and horas <= plazos["compra_agil"]
        if o.llamado == 2:
            orden, etiqueta = (0.5 if hoy else 0.7) + (0.1 if extra else 0), ("2° llamado: cotizar hoy" if hoy else "2° llamado: cotizar")
        elif hoy:
            orden, etiqueta = 1 + extra, "Cotizar hoy"
        else:
            orden, etiqueta = 3 + extra, "Cotizar esta semana"
    else:
        if horas is None:
            orden, etiqueta = 6 + extra, "Revisar cierre"
        elif horas < 24:
            orden, etiqueta = 11, "Sin tiempo"
        elif horas <= plazos["licitacion"]:
            orden, etiqueta = 1.5 + extra, "Urgente: decidir hoy"
        elif horas <= 240:
            orden, etiqueta = 2 + extra, "Preparar"
        else:
            orden, etiqueta = 4 + extra, "Planificar"
    if orden < 11:                       # a lo que ya no tiene tiempo no vale la pena pedirle revisión
        etiqueta += sufijo
    if d.preferida:
        return orden - 0.3, etiqueta + " · ★ zona preferida"
    return orden, etiqueta
