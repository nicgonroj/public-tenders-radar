"""Motor de perfiles: decide si una oportunidad calza con lo que vende una empresa.

Cada perfil se define en JSON (ver profiles.example.json) con estas listas de frases:

- fuertes: bastan por sí solas. Si aparecen en el nombre, el calce es claro (nivel A).
- debiles: palabras ambiguas ("plataforma", "traslado"). Solo cuentan en el nombre y necesitan una
  palabra de contexto, o una fuerte en el detalle, para generar calce.
- contexto: confirman que una débil se usa en el sentido del perfil.
- exclusiones: descartan si aparecen en el nombre, salvo que también haya una fuerte en el nombre.
- exclusiones_duras: descartan siempre que aparezcan en el nombre, aunque haya fuertes.
- busquedas_compra_agil: términos que se usan para buscar en la API de Compra Ágil (modo rápido).

Y dos filtros opcionales:

- zona: regiones aceptadas, comunas excluidas y comunas preferidas (estas suben la prioridad).
- monto: mínimo y máximo en pesos. Una oportunidad sin monto informado no se descarta por monto.

Niveles: "A" = calce claro, "B" = conviene revisarlo, None = sin calce.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .texto import buscar, compilar, norm


@dataclass
class Evaluacion:
    """Resultado de evaluar una oportunidad contra un perfil."""

    nivel: str | None                       # "A", "B" o None
    calce: list[str] = field(default_factory=list)
    motivo_descarte: str = ""               # por qué no calzó (vacío si calzó o si no hubo ninguna señal)


class Perfil:
    def __init__(self, nombre: str, cfg: dict):
        self.nombre = nombre
        self.fuertes = compilar(cfg.get("fuertes", []))
        self.debiles = compilar(cfg.get("debiles", []))
        self.contexto = compilar(cfg.get("contexto", []))
        self.exclusiones = compilar(cfg.get("exclusiones", []))
        self.duras = compilar(cfg.get("exclusiones_duras", []))
        self.busquedas = list(cfg.get("busquedas_compra_agil", []))

        zona = cfg.get("zona") or {}
        self.regiones = [norm(r).strip() for r in zona.get("regiones", []) if norm(r).strip()]
        self.comunas_excluidas = compilar(zona.get("comunas_excluidas", []))
        self.comunas_preferidas = compilar(zona.get("comunas_preferidas", []))

        monto = cfg.get("monto") or {}
        self.monto_minimo = monto.get("minimo")
        self.monto_maximo = monto.get("maximo")

    # --- Texto -------------------------------------------------------------------------------

    def evaluar(self, nombre: str, detalle: str = "") -> Evaluacion:
        """Evalúa el nombre y el detalle (descripción + ítems) de una oportunidad.

        El nombre pesa más que el detalle: los detalles suelen traer texto genérico de las bases
        ("software", "plataforma") que por sí solo genera falsos positivos.
        """
        n, d = norm(nombre), norm(detalle)

        duras = buscar(self.duras, n)
        if duras:
            return Evaluacion(None, [], "exclusión dura: " + ", ".join(duras))

        fuertes_nombre = buscar(self.fuertes, n)
        fuertes_detalle = [f for f in buscar(self.fuertes, d) if f not in fuertes_nombre]
        debiles = buscar(self.debiles, n)                     # las débiles solo cuentan en el nombre
        hay_contexto = bool(buscar(self.contexto, n + " " + d))
        exclusiones = buscar(self.exclusiones, n)

        # 1) Una fuerte en el nombre manda, incluso sobre una exclusión normal.
        if fuertes_nombre:
            return Evaluacion("A", fuertes_nombre + fuertes_detalle)
        # 2) Sin fuerte en el nombre, una exclusión descarta.
        if exclusiones:
            return Evaluacion(None, [], "exclusión: " + ", ".join(exclusiones))
        # 3) Fuerte en el detalle + débil en el nombre: dos señales independientes, calce claro.
        if fuertes_detalle and debiles:
            return Evaluacion("A", fuertes_detalle + debiles[:3])
        # 4) Una sola señal: fuerte solo en el detalle, o débil con contexto. Hay que revisarla.
        if fuertes_detalle or (debiles and hay_contexto):
            return Evaluacion("B", fuertes_detalle + debiles[:4])
        if debiles:
            return Evaluacion(None, [], "palabra débil sin contexto: " + ", ".join(debiles))
        return Evaluacion(None)

    def prefiltro(self, nombre: str) -> int:
        """Puntaje barato con solo el nombre, para decidir a qué oportunidades pedirles el detalle.

        2 = fuerte en el nombre, 1 = débil en el nombre, 0 = no vale la pena pedir el detalle.
        Pedir detalles es lo caro (una consulta por oportunidad), por eso se filtra antes.
        """
        n = norm(nombre)
        if buscar(self.duras, n):
            return 0
        if buscar(self.fuertes, n):
            return 2
        if buscar(self.exclusiones, n):
            return 0
        if buscar(self.debiles, n):
            return 1
        return 0

    # --- Filtros de zona y monto ---------------------------------------------------------------

    def en_zona(self, region: str, lugar: str) -> tuple[bool, bool]:
        """Devuelve (dentro, preferida).

        `region` es la región del comprador y `lugar` un texto con su comuna, organismo y dirección
        de entrega. Se evalúa dónde está el comprador, que es lo que la API informa de forma estable.
        """
        if self.regiones and not any(r in norm(region) for r in self.regiones):
            return False, False
        n = norm(lugar)
        if buscar(self.comunas_excluidas, n):
            return False, False
        return True, bool(buscar(self.comunas_preferidas, n))

    def en_rango_monto(self, monto: float | None) -> bool:
        """True si el monto está dentro del rango del perfil. Sin monto informado, no se descarta."""
        if monto is None:
            return True
        if self.monto_minimo is not None and monto < self.monto_minimo:
            return False
        if self.monto_maximo is not None and monto > self.monto_maximo:
            return False
        return True


def cargar_configuracion(ruta: Path) -> dict:
    """Lee el JSON de perfiles y completa los valores por defecto."""
    cfg = json.loads(Path(ruta).read_text(encoding="utf-8"))
    if not cfg.get("perfiles"):
        raise ValueError(f"{ruta}: falta la sección 'perfiles' o está vacía")
    cfg.setdefault("plazo_critico_horas", {"licitacion": 72, "compra_agil": 24})
    return cfg


def cargar_perfiles(cfg: dict) -> list[Perfil]:
    return [Perfil(nombre, c) for nombre, c in cfg["perfiles"].items() if not nombre.startswith("_")]
