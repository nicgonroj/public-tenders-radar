"""Modo demo sin red: un transporte que responde como la API usando fixtures JSON sintéticos.

Los fixtures de `fixtures/` tienen la misma forma que las respuestas reales, pero todos los
organismos, códigos, montos y textos son inventados. Así el radar completo (paginación, prefiltro,
detalles, motor de perfiles, memoria y reportes) corre igual que en línea, sin ticket.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from .api import API_COMPRA_AGIL, API_LICITACIONES
from .modelos import CL
from .texto import norm

# Instante de referencia de los fixtures. En modo offline el radar "vive" en esta fecha, para que
# los cierres sintéticos sigan abiertos y los resultados sean reproducibles en cualquier día.
FECHA_DEMO = datetime(2026, 10, 20, 8, 0, tzinfo=CL)

CARPETA_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


class TransporteFixtures:
    """Emula los endpoints usados por el radar a partir de archivos JSON."""

    def __init__(self, carpeta: Path = CARPETA_FIXTURES):
        carpeta = Path(carpeta)
        leer = lambda nombre: json.loads((carpeta / nombre).read_text(encoding="utf-8"))
        self.lic_activas = leer("licitaciones_activas.json")
        self.lic_detalle = leer("licitaciones_detalle.json")
        self.ca_publicadas = leer("compra_agil_publicadas.json")["payload"]["items"]
        self.ca_detalle = leer("compra_agil_detalle.json")
        self.consultas = 0                  # cuántas "llamadas a la API" se hicieron (para el reporte)

    def __call__(self, url, params=None, cabeceras=None, intentos=4):
        self.consultas += 1
        params = params or {}
        if url == API_LICITACIONES:
            if "codigo" in params:
                return self.lic_detalle.get(params["codigo"])       # None = código inexistente (404)
            return self.lic_activas
        if url == API_COMPRA_AGIL:
            return self._pagina_compra_agil(params)
        if url.startswith(API_COMPRA_AGIL + "/"):
            return self.ca_detalle.get(url.rsplit("/", 1)[1])
        return None

    def _pagina_compra_agil(self, params: dict) -> dict:
        items = list(self.ca_publicadas)
        if params.get("q"):
            # La búsqueda real es por texto libre; aquí se exige que todas las palabras del término
            # aparezcan en el nombre o la descripción.
            palabras = norm(params["q"]).split()
            def texto(it):
                det = (self.ca_detalle.get(it["codigo"]) or {}).get("payload") or {}
                return norm(f"{it.get('nombre', '')} {det.get('descripcion', '')}")
            items = [it for it in items if all(p in texto(it).split() for p in palabras)]
        if params.get("ordenar_por") == "FechaPublicacion":
            items.sort(key=lambda it: (it.get("fechas") or {}).get("fecha_publicacion") or "", reverse=True)
        tamano = int(params.get("tamano_pagina") or 10)
        numero = int(params.get("numero_pagina") or 1)
        total_paginas = max(1, math.ceil(len(items) / tamano))
        pagina = items[(numero - 1) * tamano: numero * tamano]
        return {"success": "OK", "payload": {
            "items": pagina,
            "paginacion": {"numero_pagina": numero, "tamano_pagina": tamano,
                           "total_resultados": len(items), "total_paginas": total_paginas},
        }}
