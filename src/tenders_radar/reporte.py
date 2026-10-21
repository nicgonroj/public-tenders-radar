"""Salidas del radar: resumen diario en Markdown y tabla plana en CSV."""
from __future__ import annotations

import csv
from collections import Counter
from datetime import datetime
from pathlib import Path

from .modelos import COMPRA_AGIL, Deteccion
from .texto import celda, plata

COLUMNAS_CSV = ["perfil", "prioridad", "orden", "nivel", "nueva", "fuente", "tipo", "codigo", "nombre",
                "organismo", "region", "cierre", "horas_al_cierre", "monto_clp", "llamado", "ofertas",
                "calce", "url"]


def _horas(d: Deteccion, ahora: datetime) -> float | None:
    c = d.oportunidad.cierre
    return round((c - ahora).total_seconds() / 3600, 1) if c else None


def _quedan(d: Deteccion, ahora: datetime, plazos: dict) -> str:
    h = _horas(d, ahora)
    if h is None:
        return "?"
    texto = f"{h:.0f} h" if h < 48 else f"{h / 24:.0f} d"
    limite = plazos["compra_agil"] if d.oportunidad.fuente == COMPRA_AGIL else plazos["licitacion"]
    return texto + (" ⚠" if h <= limite else "")


def _llamado(d: Deteccion) -> str:
    o = d.oportunidad
    if o.fuente != COMPRA_AGIL:
        return ""
    partes = [("**2° llamado**" if o.llamado == 2 else "1er llamado") if o.llamado else "llamado s/d"]
    if o.ofertas is not None:
        partes.append(f"{o.ofertas} oferta" + ("" if o.ofertas == 1 else "s"))
    return " · ".join(partes)


def escribir_markdown(resultado: dict[str, list[Deteccion]], descartes: dict[str, Counter], stats: dict,
                      plazos: dict, ahora: datetime, destino: Path, modo: str) -> Path:
    L = [f"# Radar de compras públicas · {ahora:%Y-%m-%d}", "",
         f"Generado el {ahora:%Y-%m-%d a las %H:%M} (hora de Chile) · modo: {modo}.", "",
         "Calce **A** es claro por nombre (o por nombre y detalle); calce **B** conviene revisarlo. "
         f"⚠ marca plazo crítico: licitación a {plazos['licitacion']} h o menos del cierre; "
         f"compra ágil a {plazos['compra_agil']} h o menos. Es un filtro por reglas sobre el texto de la "
         "ficha: no reemplaza leer las bases.", "",
         "## Cobertura", "",
         f"- Licitaciones activas revisadas: {stats.get('licitaciones', 0)} "
         f"(pasan el prefiltro por nombre: {stats.get('licitaciones_prefiltro', 0)})",
         f"- Compras ágiles publicadas revisadas: {stats.get('compras_agiles', 0)} "
         f"({stats.get('modo_compra_agil', 'no se corrió')}; pasan el prefiltro: {stats.get('compras_agiles_prefiltro', 0)})",
         f"- Consultas que la API no respondió: {', '.join(stats.get('fallas') or []) or 'ninguna'}"]
    if stats.get("topes"):
        L.append("- Búsquedas al tope de resultados (el barrido completo cubre el resto): " + ", ".join(stats["topes"]))
    unicas = {d.oportunidad.codigo for ds in resultado.values() for d in ds}
    L.append(f"- Oportunidades distintas con calce para al menos un perfil: {len(unicas)}")
    L.append(f"- Candidatas sin detalle todavía (se completan en la próxima corrida): {stats.get('sin_detalle', 0)}")
    L.append("")

    for perfil, dets in resultado.items():
        nuevas = sum(d.nueva for d in dets)
        L += [f"## {perfil}", "",
              f"{sum(d.nivel == 'A' for d in dets)} con calce claro · {sum(d.nivel == 'B' for d in dets)} para revisar · "
              f"{nuevas} nuevas en esta corrida.", ""]
        grupos = (("Nuevas · calce claro", lambda d: d.nueva and d.nivel == "A"),
                  ("Nuevas · para revisar", lambda d: d.nueva and d.nivel == "B"),
                  ("Ya vistas y siguen abiertas · calce claro", lambda d: not d.nueva and d.nivel == "A"),
                  ("Ya vistas y siguen abiertas · para revisar", lambda d: not d.nueva and d.nivel == "B"))
        if not dets:
            L += ["Sin oportunidades con calce.", ""]
        for titulo, cond in grupos:
            grupo = [d for d in dets if cond(d)]
            if not grupo:
                continue
            L += [f"### {titulo} ({len(grupo)})", "",
                  "| Prioridad | Cierre | Quedan | Tipo | Oportunidad | Organismo | Monto | Calce |",
                  "|---|---|---|---|---|---|---|---|"]
            for d in grupo:
                o = d.oportunidad
                tipo = o.tipo + (f" · {_llamado(d)}" if o.fuente == COMPRA_AGIL else "")
                cierre = f"{o.cierre:%d-%m %H:%M}" if o.cierre else "sin dato"
                L.append(f"| {d.prioridad} | {cierre} | {_quedan(d, ahora, plazos)} | {tipo} | "
                         f"[{celda(o.nombre, 70)}]({o.url}) `{o.codigo}` | {celda(o.organismo, 36)} | "
                         f"{plata(o.monto)} | {celda(', '.join(d.calce), 60)} |")
            L.append("")
        motivos = descartes.get(perfil) or Counter()
        if motivos:
            L += ["Candidatas descartadas para este perfil: " +
                  ", ".join(f"{n} por {m}" for m, n in motivos.most_common()) + ".", ""]
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("\n".join(L), encoding="utf-8")
    return destino


def escribir_csv(resultado: dict[str, list[Deteccion]], ahora: datetime, destino: Path) -> Path:
    """Una fila por detección (perfil × oportunidad), útil para Excel, Sheets o un BI."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(COLUMNAS_CSV)
        for perfil, dets in resultado.items():
            for d in dets:
                o = d.oportunidad
                w.writerow([perfil, d.prioridad, d.orden, d.nivel, "si" if d.nueva else "no", o.fuente, o.tipo,
                            o.codigo, o.nombre, o.organismo, o.region,
                            o.cierre.isoformat() if o.cierre else "", _horas(d, ahora),
                            int(o.monto) if o.monto else "", o.llamado or "", "" if o.ofertas is None else o.ofertas,
                            "; ".join(d.calce), o.url])
    return destino
