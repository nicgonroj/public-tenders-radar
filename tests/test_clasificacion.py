"""Deduplicación en SQLite, priorización por cierre y barrido incremental."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tenders_radar import almacen  # noqa: E402
from tenders_radar.api import ClienteMercadoPublico  # noqa: E402
from tenders_radar.barrido import _barrido_completo, prefiltrar  # noqa: E402
from tenders_radar.clasificacion import clasificar, prioridad, recuperar_recientes  # noqa: E402
from tenders_radar.modelos import CL, COMPRA_AGIL, LICITACION, Deteccion, Oportunidad  # noqa: E402
from tenders_radar.offline import TransporteFixtures  # noqa: E402
from tenders_radar.perfiles import Perfil  # noqa: E402

AHORA = datetime(2026, 10, 20, 8, 0, tzinfo=CL)
PLAZOS = {"licitacion": 72, "compra_agil": 24}
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def op(codigo="1-1-L126", nombre="Servicio de análisis de datos", horas=100, fuente=LICITACION, **k):
    return Oportunidad(codigo=codigo, fuente=fuente, nombre=nombre, cierre=AHORA + timedelta(hours=horas),
                       region=k.pop("region", "Metropolitana"), **k)


def det(o, nivel="A", preferida=False):
    return Deteccion(o, "P", nivel, preferida=preferida)


class TestDeduplicacion(unittest.TestCase):
    def setUp(self):
        self.db = almacen.abrir(":memory:")
        self.addCleanup(self.db.close)
        self.perfil = Perfil("P", {"fuertes": ["análisis de datos"],
                                   "zona": {"regiones": ["metropolitana"]}})

    def test_segunda_corrida_no_es_nueva_y_conserva_primera_vez(self):
        r1, _ = clasificar([op()], [self.perfil], self.db, AHORA, PLAZOS)
        self.assertTrue(r1["P"][0].nueva)
        despues = AHORA + timedelta(hours=5)
        r2, _ = clasificar([op()], [self.perfil], self.db, despues, PLAZOS)
        self.assertFalse(r2["P"][0].nueva)
        primera, ultima = self.db.execute("select primera_vez, ultima_vez from oportunidades").fetchone()
        self.assertEqual((primera, ultima), (AHORA.isoformat(), despues.isoformat()))

    def test_duplicado_en_la_misma_corrida(self):
        r, _ = clasificar([op(), op()], [self.perfil], self.db, AHORA, PLAZOS)
        self.assertEqual(len(r["P"]), 1)

    def test_cerradas_se_omiten(self):
        r, descartes = clasificar([op(horas=-1)], [self.perfil], self.db, AHORA, PLAZOS)
        self.assertEqual(r["P"], [])
        self.assertEqual(descartes["P"]["ya cerrada"], 1)

    def test_lo_que_sale_de_zona_se_olvida(self):
        clasificar([op()], [self.perfil], self.db, AHORA, PLAZOS)
        clasificar([op(region="Región de Valparaíso")], [self.perfil], self.db, AHORA, PLAZOS)
        self.assertEqual(self.db.execute("select count(*) from oportunidades").fetchone()[0], 0)

    def test_recuperar_recientes_de_otra_corrida(self):
        clasificar([op(codigo="A-1-L126"), op(codigo="B-1-L126")], [self.perfil], self.db, AHORA, PLAZOS)
        r, _ = clasificar([op(codigo="A-1-L126")], [self.perfil], self.db, AHORA + timedelta(hours=1), PLAZOS)
        n = recuperar_recientes(r, [self.perfil], self.db, AHORA + timedelta(hours=1), PLAZOS)
        self.assertEqual(n, 1)
        self.assertEqual({d.oportunidad.codigo for d in r["P"]}, {"A-1-L126", "B-1-L126"})
        self.assertFalse(next(d for d in r["P"] if d.oportunidad.codigo == "B-1-L126").nueva)


class TestPrioridad(unittest.TestCase):
    def etiqueta(self, o, **k):
        return prioridad(det(o, **k), AHORA, PLAZOS)

    def test_licitaciones_por_cercania_del_cierre(self):
        self.assertEqual(self.etiqueta(op(horas=10))[1], "Sin tiempo")
        self.assertEqual(self.etiqueta(op(horas=48))[1], "Urgente: decidir hoy")
        self.assertEqual(self.etiqueta(op(horas=120))[1], "Preparar")
        self.assertEqual(self.etiqueta(op(horas=400))[1], "Planificar")

    def test_compra_agil_y_segundo_llamado(self):
        hoy = self.etiqueta(op(fuente=COMPRA_AGIL, horas=10))
        semana = self.etiqueta(op(fuente=COMPRA_AGIL, horas=60))
        segundo = self.etiqueta(op(fuente=COMPRA_AGIL, horas=60, llamado=2))
        self.assertEqual(hoy[1], "Cotizar hoy")
        self.assertEqual(semana[1], "Cotizar esta semana")
        self.assertTrue(segundo[1].startswith("2° llamado"))
        self.assertLess(segundo[0], hoy[0])
        self.assertLess(hoy[0], semana[0])

    def test_calce_B_baja_y_zona_preferida_sube(self):
        a, b = self.etiqueta(op(horas=120)), self.etiqueta(op(horas=120), nivel="B")
        self.assertGreater(b[0], a[0])
        self.assertIn("revisar calce", b[1])
        pref = self.etiqueta(op(horas=120), preferida=True)
        self.assertLess(pref[0], a[0])
        self.assertIn("★", pref[1])

    def test_orden_final_por_prioridad_y_luego_cierre(self):
        db = almacen.abrir(":memory:")
        self.addCleanup(db.close)
        perfil = Perfil("P", {"fuertes": ["análisis de datos"]})
        ops = [op(codigo="L-PLAN", horas=400), op(codigo="L-PREP2", horas=200), op(codigo="L-PREP1", horas=100),
               op(codigo="CA-HOY", fuente=COMPRA_AGIL, horas=5)]
        r, _ = clasificar(ops, [perfil], db, AHORA, PLAZOS)
        self.assertEqual([d.oportunidad.codigo for d in r["P"]], ["CA-HOY", "L-PREP1", "L-PREP2", "L-PLAN"])


class TestBarrido(unittest.TestCase):
    def setUp(self):
        self.db = almacen.abrir(":memory:")
        self.addCleanup(self.db.close)
        self.cliente = ClienteMercadoPublico(TransporteFixtures(FIXTURES), "demo", pausa_licitaciones=0)

    def test_prefiltro_ordena_fuertes_primero(self):
        p = Perfil("P", {"fuertes": ["tablero"], "debiles": ["plataforma"]})
        items = [{"n": "plataforma"}, {"n": "nada"}, {"n": "tablero"}]
        self.assertEqual([i["n"] for i in prefiltrar(items, [p], "n")], ["tablero", "plataforma"])

    def test_barrido_incremental_se_detiene_en_lo_ya_visto(self):
        log = lambda m: None
        vistos, fallas, _ = _barrido_completo(self.cliente, self.db, 100, AHORA, log, tamano=3)
        self.assertEqual((len(vistos), fallas), (18, []))
        # Segunda pasada: tres páginas seguidas ya conocidas bastan para parar.
        consultas = self.cliente.transporte.consultas
        vistos2, fallas2, _ = _barrido_completo(self.cliente, self.db, 100, AHORA, log, tamano=3)
        self.assertEqual((len(vistos2), fallas2), (9, []))
        self.assertEqual(self.cliente.transporte.consultas - consultas, 3)

    def test_barrido_con_hueco_no_marca_vistos(self):
        transporte = TransporteFixtures(FIXTURES)
        original = transporte._pagina_compra_agil
        transporte._pagina_compra_agil = lambda p: None if p.get("numero_pagina") == 2 else original(p)
        cliente = ClienteMercadoPublico(transporte, "demo", pausa_licitaciones=0)
        _, fallas, _ = _barrido_completo(cliente, self.db, 100, AHORA, lambda m: None, tamano=3)
        self.assertIn("página 2", fallas)
        self.assertEqual(self.db.execute("select count(*) from vistos_ca").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
