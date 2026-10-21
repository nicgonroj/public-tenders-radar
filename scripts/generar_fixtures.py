#!/usr/bin/env python3
"""Genera los fixtures sintéticos del modo offline (fixtures/*.json).

Todo es inventado: organismos, códigos (prefijo 9xxx, que no corresponde a compradores reales),
montos y textos. Las regiones y comunas son reales solo para ejercitar el filtro de zona. La forma
de cada objeto replica los campos que el radar lee de las respuestas reales de la API.

Cada caso declara en `esperado` qué debería hacer el radar con él; los tests lo verifican.

    python scripts/generar_fixtures.py
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

DESTINO = Path(__file__).resolve().parents[1] / "fixtures"
REFERENCIA = datetime(2026, 10, 20, 8, 0)          # hora de Chile (UTC-3 en octubre), igual a FECHA_DEMO
UTC_OFFSET = timedelta(hours=3)

RM = "Región Metropolitana de Santiago"

# (código, nombre, tipo, organismo, comuna, región, horas al cierre, monto, descripción, ítems, esperado)
LICITACIONES = [
    ("9001-11-LE26", "Servicio de inteligencia de negocios y tableros de control para la gestión municipal", "LE",
     "Municipalidad de Valle Ficticio", "Providencia", RM, 9 * 24, 45_000_000,
     "Implementación de modelo de datos, tableros de control e indicadores de gestión para direcciones municipales.",
     [("Servicio de consultoría", "Desarrollo de tableros en herramienta de BI")],
     {"Consultora de analítica de datos": "A"}),
    ("9002-4-L126", "Desarrollo de plataforma de indicadores de gestión", "L1",
     "Servicio Regional de Demostración", "Santiago", RM, 50, 8_000_000,
     "Se requiere análisis de datos de atenciones y un tablero de control para jefaturas.", [],
     {"Consultora de analítica de datos": "A"}),
    ("9003-7-LE26", "Estudio de satisfacción usuaria de los servicios de atención", "LE",
     "Hospital Base Ficticio", "Temuco", "Región de La Araucanía", 15 * 24, 12_000_000,
     "Diseño muestral, levantamiento de encuestas y análisis estadístico de resultados.", [],
     {"Consultora de analítica de datos": "B"}),
    ("9004-2-LP26", "Adquisición de equipos computacionales para sistema de información", "LP",
     "Universidad Pública de Ejemplo", "Valparaíso", "Región de Valparaíso", 20 * 24, 150_000_000,
     "Compra de computadores de escritorio y servidores.", [], {}),
    ("9005-9-L126", "Capacitación en Power BI para funcionarios", "L1",
     "Gobierno Regional Demo", "Concepción", "Región del Biobío", 30 * 24, 3_000_000,
     "Curso de 24 horas sobre modelamiento y visualización.", [],
     {"Consultora de analítica de datos": "A"}),
    ("9006-3-L126", "Análisis de datos de flujos de tránsito", "L1",
     "Municipalidad de Valle Ficticio", "Providencia", RM, -24, 5_000_000,
     "Análisis de conteos vehiculares.", [], {"_motivo": "ya cerrada"}),
    ("9007-5-LE26", "Servicio de transporte de pasajeros para funcionarios del hospital", "LE",
     "Hospital Base Ficticio", "Santiago", RM, 6 * 24, 60_000_000,
     "Traslado diario de funcionarios en turnos de mañana y noche.", [],
     {"Empresa de transporte de pasajeros": "A"}),
    ("9008-1-L126", "Servicio de traslado de adultos mayores a actividades comunitarias", "L1",
     "Municipalidad de Valle Ficticio", "Ñuñoa", RM, 5 * 24, 4_500_000,
     "Traslado ida y vuelta de grupos de adultos mayores.", [],
     {"Empresa de transporte de pasajeros": "B"}),
    ("9009-6-L126", "Servicio de transporte de pasajeros para delegaciones deportivas", "L1",
     "Gobierno Regional Demo", "Viña del Mar", "Región de Valparaíso", 7 * 24, 9_000_000,
     "Traslado de deportistas a competencias regionales.", [], {"_motivo": "fuera de zona"}),
    ("9010-8-L126", "Servicio de transporte de carga y mudanza de oficinas", "L1",
     "Servicio Regional de Demostración", "Santiago", RM, 8 * 24, 6_000_000,
     "Traslado de mobiliario y archivos.", [], {"_motivo": "exclusión"}),
    ("9011-2-LE26", "Adquisición de insumos de aseo y artículos de limpieza para establecimientos educacionales", "LE",
     "Corporación de Educación Demo", "Puente Alto", RM, 4 * 24, 18_000_000,
     "Suministro mensual de cloro, detergente, papel higiénico y bolsas de basura.", [],
     {"Proveedor de insumos de aseo": "A"}),
    ("9012-4-L126", "Servicio de aseo y limpieza de dependencias", "L1",
     "Servicio Regional de Demostración", "Santiago", RM, 10 * 24, 25_000_000,
     "Personal de aseo para oficinas centrales.", [], {"_motivo": "exclusión"}),
    ("9013-3-LP26", "Suministro de papel higiénico y toallas de papel", "LP",
     "Hospital Base Ficticio", "Santiago", RM, 12 * 24, 80_000_000,
     "Convenio de suministro por 24 meses.", [], {"_motivo": "fuera del rango de monto"}),
    ("9014-7-L126", "Construcción de veredas en sector norte", "L1",
     "Municipalidad de Valle Ficticio", "Providencia", RM, 9 * 24, 70_000_000, "Obra civil.", [], {}),
    ("9015-1-L126", "Adquisición de neumáticos para vehículos municipales", "L1",
     "Municipalidad de Valle Ficticio", "Providencia", RM, 6 * 24, 7_000_000, "Neumáticos 195/65 R15.", [], {}),
    ("9016-5-LE26", "Mantención de áreas verdes y arbolado urbano", "LE",
     "Municipalidad de Valle Ficticio", "Providencia", RM, 11 * 24, 90_000_000, "Riego, poda y reposición.", [], {}),
    ("9017-2-L126", "Servicio de transporte de pasajeros para funcionarios municipales", "L1",
     "Municipalidad de Costa Ficticia", "Melipilla", RM, 6 * 24, 15_000_000,
     "Traslado de funcionarios entre sedes.", [], {"_motivo": "fuera de zona"}),
    ("9018-9-L126", "Adquisición de detergente y desinfectante para centros de salud", "L1",
     "Servicio de Salud Demo Norte", "Independencia", RM, 20, 6_500_000,
     "Detergente industrial y desinfectante de superficies.", [],
     {"Proveedor de insumos de aseo": "A"}),
    # Sin detalle en los fixtures: la API devolvería 404 o fallaría. El radar la detecta igual por el
    # nombre y la reporta como "candidata sin detalle".
    ("9019-4-L126", "Servicio de análisis de datos para la gestión hospitalaria", None,
     None, None, None, 14 * 24, None, None, [], {"Consultora de analítica de datos": "A"}),
]

# (código, nombre, organismo, región, dirección de entrega, horas al cierre, monto, llamado, ofertas,
#  descripción, productos, horas desde publicación, esperado)
COMPRAS_AGILES = [
    ("9101-120-COT26", "Desarrollo de dashboard de indicadores de atención", "Servicio de Salud Demo Norte", RM,
     "Av. Ejemplo 100, Independencia", 72, 4_500_000, 1, 2, "Dashboard con indicadores de tiempos de espera.",
     [("Servicio de desarrollo de dashboard", "Incluye carga de datos mensual")], 30,
     {"Consultora de analítica de datos": "A"}),
    ("9102-121-COT26", "Servicio de análisis de datos de encuesta de satisfacción", "Universidad Pública de Ejemplo",
     "Región de Valparaíso", "Calle Demo 45, Valparaíso", 12, 2_800_000, 1, 4,
     "Procesamiento y análisis de una encuesta de 1.200 casos.", [], 50,
     {"Consultora de analítica de datos": "A"}),
    ("9103-122-COT26", "Asesoría en visualización de datos para unidad de estudios", "Gobierno Regional Demo",
     "Región del Biobío", "Pasaje Ficticio 9, Concepción", 48, 3_900_000, 2, 0,
     "Segundo llamado: el primero se declaró desierto.", [], 90,
     {"Consultora de analítica de datos": "A"}),
    ("9104-123-COT26", "Contratación de plataforma de reportes", "Servicio Regional de Demostración", RM,
     "Calle Demo 200, Santiago", 96, 2_000_000, 1, 1,
     "Plataforma web para publicar reportes con datos de gestión.", [], 20,
     {"Consultora de analítica de datos": "B"}),
    ("9105-124-COT26", "Renovación de licencias Power BI Pro", "Universidad Pública de Ejemplo",
     "Región de Valparaíso", "Calle Demo 45, Valparaíso", 60, 3_200_000, 1, 3,
     "Renovación anual de 40 licencias.", [], 40, {"_motivo": "exclusión dura"}),
    ("9106-125-COT26", "Elaboración de tablero de control de inventario", "Corporación de Educación Demo", RM,
     "Av. Ejemplo 300, Puente Alto", 80, 600_000, 1, 0, "Tablero simple en planilla.", [], 15,
     {"_motivo": "fuera del rango de monto"}),
    ("9107-126-COT26", "Traslado de estudiantes a actividad deportiva", "Municipalidad de Valle Ficticio", RM,
     "Av. Ejemplo 123, Providencia", 20, 1_200_000, 1, 1, "Bus para 40 estudiantes, ida y vuelta.", [], 10,
     {"Empresa de transporte de pasajeros": "B"}),
    ("9108-127-COT26", "Arriendo de buses con conductor para paseo de adultos mayores",
     "Municipalidad de Llano Ficticio", RM, "Calle Demo 77, Maipú", 72, 1_800_000, 1, 2,
     "Dos buses de 45 pasajeros.", [], 25, {"Empresa de transporte de pasajeros": "A"}),
    ("9109-128-COT26", "Transporte de pasajeros aeropuerto - hotel para seminario", "Gobierno Regional Demo",
     "Región del Biobío", "Pasaje Ficticio 9, Concepción", 50, 900_000, 1, 0, "Traslados para 30 personas.", [], 35,
     {"_motivo": "fuera de zona"}),
    ("9110-129-COT26", "Servicio de transporte de residuos domiciliarios", "Municipalidad de Llano Ficticio", RM,
     "Calle Demo 77, Maipú", 70, 2_500_000, 1, 1, "Retiro y traslado a relleno sanitario.", [], 60,
     {"_motivo": "exclusión dura"}),
    ("9111-130-COT26", "Compra de artículos de aseo para jardín infantil", "Corporación de Educación Demo", RM,
     "Av. Ejemplo 300, Puente Alto", 48, 900_000, 1, 3, "Cloro, lavalozas y toallas de papel.",
     [("Cloro gel 900 ml", ""), ("Toalla de papel", "Rollo 25 m")], 12,
     {"Proveedor de insumos de aseo": "A"}),
    ("9112-131-COT26", "Adquisición de alcohol gel y jabón líquido", "Servicio de Salud Demo Norte", RM,
     "Av. Ejemplo 100, Independencia", 10, 1_100_000, 2, 1, "Segundo llamado.", [], 100,
     {"Proveedor de insumos de aseo": "A"}),
    ("9113-132-COT26", "Insumos para sanitización de oficinas", "Servicio Regional de Demostración", RM,
     "Calle Demo 200, Santiago", 90, 700_000, 1, 0, "Pulverizadores y sanitizante.", [], 5,
     {"Proveedor de insumos de aseo": "B"}),
    ("9114-133-COT26", "Insumos de oficina", "Servicio Regional de Demostración", RM,
     "Calle Demo 200, Santiago", 70, 400_000, 1, 5, "Lápices, cuadernos y archivadores.", [], 8,
     {"_motivo": "palabra débil sin contexto"}),
    ("9115-134-COT26", "Compra de alimentos para casino institucional", "Hospital Base Ficticio", RM,
     "Calle Demo 1, Santiago", 40, 2_000_000, 1, 6, "Abarrotes y frutas.", [], 3, {}),
    ("9116-135-COT26", "Reparación de techumbre de bodega", "Municipalidad de Valle Ficticio", RM,
     "Av. Ejemplo 123, Providencia", 100, 3_000_000, 1, 2, "Cambio de planchas de zinc.", [], 70, {}),
    ("9117-136-COT26", "Servicio de mantención de ascensores", "Universidad Pública de Ejemplo",
     "Región de Valparaíso", "Calle Demo 45, Valparaíso", 120, 1_500_000, 1, 1, "Mantención preventiva.", [], 80, {}),
    ("9118-137-COT26", "Plataforma de gestión de datos de salud", "Servicio de Salud Demo Norte", RM,
     "Av. Ejemplo 100, Independencia", 150, 4_000_000, 1, 0, "Plataforma para integrar datos de atenciones.", [], 2,
     {"Consultora de analítica de datos": "B"}),
]


def iso_local(horas):
    return (REFERENCIA + timedelta(hours=horas)).strftime("%Y-%m-%dT%H:%M:%S")


def iso_utc(horas):
    return (REFERENCIA + timedelta(hours=horas) + UTC_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ")


def construir():
    activas, det_lic, esperado = [], {}, {}
    for cod, nombre, tipo, org, comuna, region, horas, monto, desc, items, esp in LICITACIONES:
        activas.append({"CodigoExterno": cod, "Nombre": nombre, "CodigoEstado": 5, "FechaCierre": iso_local(horas)})
        esperado[cod] = esp
        if tipo is None:
            continue                                     # caso sin detalle
        det_lic[cod] = {"Cantidad": 1, "Version": "v1", "Listado": [{
            "CodigoExterno": cod, "Nombre": nombre, "CodigoEstado": 5, "Estado": "Publicada",
            "Descripcion": desc, "Tipo": tipo, "Moneda": "CLP", "MontoEstimado": monto,
            "Comprador": {"CodigoOrganismo": "9" + cod[:3], "NombreOrganismo": org,
                          "NombreUnidad": "Unidad de Compras", "ComunaUnidad": comuna, "RegionUnidad": region},
            "Fechas": {"FechaPublicacion": iso_local(-10 * 24), "FechaCierre": iso_local(horas)},
            "Items": {"Cantidad": len(items), "Listado": [
                {"Correlativo": i + 1, "NombreProducto": n, "Descripcion": d, "Cantidad": 1}
                for i, (n, d) in enumerate(items)]},
        }]}
    lista_lic = {"Cantidad": len(activas), "FechaCreacion": iso_local(0), "Version": "v1", "Listado": activas}

    items_ca, det_ca = [], {}
    for (cod, nombre, org, region, entrega, horas, monto, llamado, ofertas, desc, prods, pub, esp) in COMPRAS_AGILES:
        esperado[cod] = esp
        base = {
            "codigo": cod, "nombre": nombre, "estado": "publicada",
            "institucion": {"organismo_comprador": org, "nombre_region": region},
            "fechas": {"fecha_publicacion": iso_utc(-pub), "fecha_cierre": iso_utc(horas)},
            "montos": {"monto_disponible_clp": monto},
            "convocatoria": {"estado_convocatoria": llamado},
            "resumen": {"total_ofertas_recibidas": ofertas},
        }
        items_ca.append(base)
        det_ca[cod] = {"success": "OK", "payload": {
            **base, "descripcion": desc, "entrega": {"direccion_entrega": entrega},
            "productos_solicitados": [{"nombre": n, "descripcion": d, "cantidad": 1} for n, d in prods],
        }}
    lista_ca = {"success": "OK", "payload": {"items": items_ca, "paginacion": {
        "numero_pagina": 1, "tamano_pagina": len(items_ca), "total_resultados": len(items_ca), "total_paginas": 1}}}
    return {"licitaciones_activas.json": lista_lic, "licitaciones_detalle.json": det_lic,
            "compra_agil_publicadas.json": lista_ca, "compra_agil_detalle.json": det_ca,
            "esperado.json": esperado}


if __name__ == "__main__":
    DESTINO.mkdir(exist_ok=True)
    for nombre, contenido in construir().items():
        (DESTINO / nombre).write_text(json.dumps(contenido, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print("escrito", DESTINO / nombre)
