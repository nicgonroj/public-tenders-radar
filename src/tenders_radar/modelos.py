"""Estructuras de datos comunes y conversión desde las respuestas de la API.

Las dos APIs devuelven formas distintas (la de licitaciones usa CamelCase en español y la de Compra
Ágil snake_case). Aquí se traducen a una sola `Oportunidad`, para que el resto del radar no dependa
de la fuente.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CL = ZoneInfo("America/Santiago")

FICHA_LICITACION = "https://www.mercadopublico.cl/Procurement/Modules/RFB/DetailsAcquisition.aspx?idlicitacion={}"
FICHA_COMPRA_AGIL = "https://buscador.mercadopublico.cl/ficha?code={}"

LICITACION = "licitacion"
COMPRA_AGIL = "compra_agil"


@dataclass
class Oportunidad:
    codigo: str
    fuente: str                      # LICITACION o COMPRA_AGIL
    nombre: str
    detalle: str = ""                # descripción + productos/ítems, para el motor de perfiles
    tipo: str = ""                   # etiqueta legible: "Licitación LE", "Compra ágil"
    organismo: str = ""
    region: str = ""
    lugar: str = ""                  # comuna, organismo y dirección: insumo del filtro de zona
    cierre: datetime | None = None
    monto: float | None = None
    url: str = ""
    con_detalle: bool = False        # False si todavía no se pudo pedir el detalle
    llamado: int | None = None       # compra ágil: 1er o 2° llamado
    ofertas: int | None = None       # compra ágil: ofertas recibidas al momento de la consulta

    def a_json(self) -> dict:
        d = asdict(self)
        d["cierre"] = self.cierre.isoformat() if self.cierre else None
        return d

    @classmethod
    def desde_json(cls, d: dict) -> "Oportunidad":
        d = dict(d)
        d["cierre"] = datetime.fromisoformat(d["cierre"]) if d.get("cierre") else None
        return cls(**d)


@dataclass
class Deteccion:
    """Una oportunidad que calzó con un perfil, lista para priorizar y reportar."""

    oportunidad: Oportunidad
    perfil: str
    nivel: str                       # "A" o "B"
    calce: list[str] = field(default_factory=list)
    nueva: bool = True               # primera vez que se detecta para este perfil
    preferida: bool = False          # comprador en una comuna preferida del perfil
    orden: float = 99.0              # menor = más prioritaria
    prioridad: str = ""


def fecha_cl(valor: str | None) -> datetime | None:
    """Convierte una fecha de la API a hora de Chile.

    La API de licitaciones entrega hora local sin zona ("2026-10-27T15:00:00"); la de Compra Ágil
    suele entregar UTC con "Z". Ambas se llevan a America/Santiago.
    """
    if not valor:
        return None
    v = str(valor).strip()
    try:
        if v.endswith("Z"):
            return datetime.fromisoformat(v[:-1]).replace(tzinfo=timezone.utc).astimezone(CL)
        dt = datetime.fromisoformat(v[:26] if "." in v else v)
        return dt.astimezone(CL) if dt.tzinfo else dt.replace(tzinfo=CL)
    except ValueError:
        return None


def _numero(valor) -> float | None:
    try:
        n = float(valor)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def licitacion_a_oportunidad(resumen: dict, detalle: dict | None) -> Oportunidad:
    """`resumen` es un elemento de la lista de activas; `detalle`, la respuesta por código."""
    det = detalle or {}
    comprador = det.get("Comprador") or {}
    items = (det.get("Items") or {}).get("Listado") or []
    texto_items = " ".join(f"{x.get('NombreProducto') or ''} {x.get('Descripcion') or ''}" for x in items)
    codigo = resumen.get("CodigoExterno") or det.get("CodigoExterno") or ""
    return Oportunidad(
        codigo=codigo,
        fuente=LICITACION,
        nombre=resumen.get("Nombre") or det.get("Nombre") or "",
        detalle=f"{det.get('Descripcion') or ''} {texto_items}".strip(),
        tipo=("Licitación " + (det.get("Tipo") or "")).strip(),
        organismo=comprador.get("NombreOrganismo") or "",
        region=(comprador.get("RegionUnidad") or "").strip(),
        lugar=f"{comprador.get('ComunaUnidad') or ''} {comprador.get('NombreOrganismo') or ''}".strip(),
        # La lista de activas trae el cierre vigente; el detalle en caché puede ser anterior a una prórroga.
        cierre=fecha_cl(resumen.get("FechaCierre") or (det.get("Fechas") or {}).get("FechaCierre")),
        monto=_numero(det.get("MontoEstimado")),
        url=FICHA_LICITACION.format(codigo),
        con_detalle=bool(det),
    )


def compra_agil_a_oportunidad(item: dict, detalle: dict | None) -> Oportunidad:
    """`item` es un elemento del listado de Compra Ágil; `detalle`, el payload por código."""
    det = detalle or {}
    inst = item.get("institucion") or det.get("institucion") or {}
    productos = det.get("productos_solicitados") or []
    texto_productos = " ".join(f"{x.get('nombre') or ''} {x.get('descripcion') or ''}" for x in productos)
    entrega = (det.get("entrega") or {}).get("direccion_entrega") or ""
    llamado, ofertas = llamado_y_ofertas(item, det)
    codigo = item.get("codigo") or det.get("codigo") or ""
    return Oportunidad(
        codigo=codigo,
        fuente=COMPRA_AGIL,
        nombre=item.get("nombre") or det.get("nombre") or "",
        detalle=f"{det.get('descripcion') or ''} {texto_productos}".strip(),
        tipo="Compra ágil",
        organismo=inst.get("organismo_comprador") or "",
        region=inst.get("nombre_region") or "",
        lugar=f"{inst.get('organismo_comprador') or ''} {entrega}".strip(),
        cierre=fecha_cl((item.get("fechas") or det.get("fechas") or {}).get("fecha_cierre")),
        monto=_numero((item.get("montos") or det.get("montos") or {}).get("monto_disponible_clp")),
        url=FICHA_COMPRA_AGIL.format(codigo),
        con_detalle=bool(det),
        llamado=llamado,
        ofertas=ofertas,
    )


def llamado_y_ofertas(item: dict, detalle: dict) -> tuple[int | None, int | None]:
    """Combina el llamado y las ofertas del listado con los del detalle guardado.

    El detalle puede ser más nuevo (ya pasó a segundo llamado) o más viejo que el listado. Dentro de
    un mismo llamado las ofertas solo aumentan, así que se toma el máximo.
    """
    llamado = (item.get("convocatoria") or {}).get("estado_convocatoria")
    ofertas = (item.get("resumen") or {}).get("total_ofertas_recibidas")
    ll_det = (detalle.get("convocatoria") or {}).get("estado_convocatoria")
    of_det = (detalle.get("resumen") or {}).get("total_ofertas_recibidas")
    if ll_det and (not llamado or ll_det > llamado):
        return ll_det, of_det
    if of_det is not None and (not llamado or ll_det == llamado):
        ofertas = max(ofertas or 0, of_det)
    return llamado or ll_det, ofertas
