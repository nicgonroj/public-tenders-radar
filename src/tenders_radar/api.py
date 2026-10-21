"""Cliente de las APIs públicas oficiales de Mercado Público (ChileCompra).

- Licitaciones v1: https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json
  El ticket va como parámetro `ticket`. Rechaza consultas simultáneas o muy seguidas con HTTP 429,
  por eso los detalles se piden de a uno y con una pausa entre consultas.
- Compra Ágil v2: https://api2.mercadopublico.cl/v2/compra-agil
  El ticket va en la cabecera `ticket`. Es paginada y lenta (decenas de segundos por página grande).

El ticket se pide gratis en la página oficial de la API (ver README) y se lee de la variable de
entorno MERCADOPUBLICO_TICKET. Nunca se escribe en disco ni se muestra en los registros.

El transporte es intercambiable: `TransporteHTTP` consulta la red y `offline.TransporteFixtures`
responde con archivos JSON sintéticos. Ambos reciben (url, params, cabeceras) y devuelven el JSON
decodificado o None.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol

API_LICITACIONES = "https://api.mercadopublico.cl/servicios/v1/publico/licitaciones.json"
API_COMPRA_AGIL = "https://api2.mercadopublico.cl/v2/compra-agil"
VARIABLE_TICKET = "MERCADOPUBLICO_TICKET"


class Transporte(Protocol):
    def __call__(self, url: str, params: dict | None = None, cabeceras: dict | None = None,
                 intentos: int = 4) -> dict | None: ...


def leer_ticket() -> str | None:
    """Devuelve el ticket de la variable de entorno, o None si no está definido."""
    t = os.environ.get(VARIABLE_TICKET, "").strip()
    return t or None


def espera_reintento(intento: int, codigo_http: int | None, retry_after: str | None = None) -> float:
    """Segundos a esperar antes del reintento `intento` (0, 1, 2…).

    Backoff lineal creciente: 429 (demasiadas consultas) espera más que un error transitorio.
    Si el servidor envía Retry-After en segundos, se respeta.
    """
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    base = 6 if codigo_http == 429 else 2
    return float(base * (intento + 1))


class TransporteHTTP:
    """Consulta la red con urllib. Reintenta 429, 5xx y errores de red; 400/404 devuelven None."""

    def __init__(self, timeout: float = 90, dormir: Callable[[float], None] = time.sleep,
                 registro: Callable[[str], None] | None = None):
        self.timeout = timeout
        self.dormir = dormir
        self.registro = registro or (lambda _m: None)

    def __call__(self, url, params=None, cabeceras=None, intentos=4):
        completa = url + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(completa, headers={"Accept": "application/json", **(cabeceras or {})})
        for i in range(intentos):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                e.close()                    # libera la conexión del error
                if e.code in (400, 401, 403, 404):
                    # Sin sentido reintentar: parámetro inválido, ticket rechazado o código inexistente.
                    # Se registra solo la ruta, nunca la URL completa, porque llevaría el ticket.
                    self.registro(f"  HTTP {e.code} en {urllib.parse.urlsplit(url).path}")
                    return None
                espera = espera_reintento(i, e.code, e.headers.get("Retry-After") if e.headers else None)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
                espera = espera_reintento(i, None)
            if i < intentos - 1:
                self.dormir(espera)
        return None


class ClienteMercadoPublico:
    """Operaciones de alto nivel sobre las dos APIs, independientes del transporte."""

    def __init__(self, transporte: Transporte, ticket: str, pausa_licitaciones: float = 0.6,
                 dormir: Callable[[float], None] = time.sleep):
        self.transporte = transporte
        self.ticket = ticket
        self.pausa = pausa_licitaciones
        self.dormir = dormir

    # --- Licitaciones v1 ---------------------------------------------------------------------

    def licitaciones_activas(self) -> list[dict] | None:
        """Lista resumida de licitaciones activas (código, nombre, estado y cierre)."""
        r = self.transporte(API_LICITACIONES, {"estado": "activas", "ticket": self.ticket})
        if r is None:
            return None
        return r.get("Listado") or []

    def detalle_licitacion(self, codigo: str) -> dict | None:
        r = self.transporte(API_LICITACIONES, {"codigo": codigo, "ticket": self.ticket}, intentos=3)
        if self.pausa:
            self.dormir(self.pausa)        # la API v1 castiga con 429 las consultas seguidas
        listado = (r or {}).get("Listado") or []
        return listado[0] if listado else None

    # --- Compra Ágil v2 ----------------------------------------------------------------------

    def pagina_compra_agil(self, numero: int, tamano: int, **filtros) -> dict | None:
        """Una página de compras ágiles publicadas. Devuelve el payload o None si falló."""
        params = {**filtros, "estado": "publicada", "tamano_pagina": tamano, "numero_pagina": numero}
        r = self.transporte(API_COMPRA_AGIL, params, {"ticket": self.ticket}, intentos=3)
        if not r or r.get("success") != "OK":
            return None
        return r.get("payload") or {}

    def detalle_compra_agil(self, codigo: str) -> dict | None:
        r = self.transporte(f"{API_COMPRA_AGIL}/{urllib.parse.quote(codigo)}", None,
                            {"ticket": self.ticket}, intentos=2)
        if not r or r.get("success") != "OK":
            return None
        return r.get("payload")

    def buscar_compra_agil(self, termino: str, tamano: int = 10, max_paginas: int = 8) -> tuple[list[dict], str]:
        """Lee todas las páginas de una búsqueda por texto (hasta `max_paginas`).

        Devuelve (items, estado): "ok" si leyó todo, "tope" si quedaron páginas sin leer y "falla" si
        la API no respondió. "tope" no es un error: el término tiene más resultados que los pedidos.
        """
        items, pagina, total = [], 1, 1
        while pagina <= total and pagina <= max_paginas:
            payload = self.pagina_compra_agil(pagina, tamano, q=termino)
            if payload is None:
                return items, "falla"
            items.extend(payload.get("items") or [])
            total = (payload.get("paginacion") or {}).get("total_paginas") or 1
            pagina += 1
        return items, "ok" if pagina > total else "tope"
