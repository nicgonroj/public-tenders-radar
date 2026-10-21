"""Normalización de texto y utilidades de formato.

Las fichas de Mercado Público mezclan mayúsculas, tildes, signos y abreviaturas. Todo el motor de
perfiles compara contra texto normalizado: minúsculas, sin tildes y sin signos de puntuación.
"""
from __future__ import annotations

import re
import unicodedata

# Límite de palabra explícito sobre texto ya normalizado (solo [a-z0-9] y espacios).
_ANTES = r"(?<![a-z0-9])"
_DESPUES = r"(?![a-z0-9])"


def norm(texto: str | None) -> str:
    """Pasa a minúsculas, quita tildes y diéresis, lleva la ñ a n y reemplaza signos por espacios.

    La ñ se lleva a n porque las fichas la escriben de ambas formas ("Ñuñoa" y "Nunoa").

    >>> norm("Adquisición de INSUMOS de aseo, año 2026")
    'adquisicion de insumos de aseo  ano 2026'
    """
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", t)


def compilar(frases: list[str]) -> list[tuple[str, re.Pattern]]:
    """Compila cada frase como patrón de palabra completa sobre texto normalizado.

    La frase se normaliza también, así el perfil puede escribirse con o sin tildes.
    """
    salida = []
    for frase in frases:
        limpia = re.sub(r"\s+", " ", norm(frase)).strip()
        if not limpia:
            continue
        # Los espacios de la frase aceptan uno o más espacios en el texto (la normalización deja dobles).
        cuerpo = r"\s+".join(re.escape(p) for p in limpia.split(" "))
        salida.append((frase, re.compile(_ANTES + cuerpo + _DESPUES)))
    return salida


def buscar(patrones: list[tuple[str, re.Pattern]], texto_normalizado: str) -> list[str]:
    """Devuelve las frases (tal como se escribieron en el perfil) que aparecen en el texto."""
    return [frase for frase, patron in patrones if patron.search(texto_normalizado)]


def celda(texto: str | None, largo: int = 90) -> str:
    """Deja un texto apto para una celda de tabla Markdown: una línea, sin '|' y recortado."""
    t = re.sub(r"\s+", " ", (texto or "").replace("|", "/")).strip()
    return t if len(t) <= largo else t[: largo - 1] + "…"


def plata(monto: float | None) -> str:
    """Formatea pesos chilenos con separador de miles: 1234567 -> $1.234.567."""
    if not monto:
        return "sin dato"
    return "$" + f"{int(monto):,}".replace(",", ".")
