"""Parseo de fechas y de las respuestas de la API (fixtures), reintentos y paginación."""
import io
import json
import sys
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tenders_radar.api import ClienteMercadoPublico, TransporteHTTP, espera_reintento  # noqa: E402
from tenders_radar.modelos import (CL, COMPRA_AGIL, LICITACION, Oportunidad, compra_agil_a_oportunidad,  # noqa: E402
                                   fecha_cl, licitacion_a_oportunidad, llamado_y_ofertas)
from tenders_radar.offline import TransporteFixtures  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def leer(nombre):
    return json.loads((FIXTURES / nombre).read_text(encoding="utf-8"))


class TestFechas(unittest.TestCase):
    def test_utc_con_z_pasa_a_chile(self):
        self.assertEqual(fecha_cl("2026-10-20T11:00:00Z"), datetime(2026, 10, 20, 8, 0, tzinfo=CL))

    def test_local_sin_zona(self):
        self.assertEqual(fecha_cl("2026-10-27T15:00:00"), datetime(2026, 10, 27, 15, 0, tzinfo=CL))

    def test_fraccion_y_vacios(self):
        self.assertEqual(fecha_cl("2026-10-27T15:00:00.1234567").minute, 0)
        self.assertIsNone(fecha_cl(None))
        self.assertIsNone(fecha_cl("no es fecha"))


class TestParseoFixtures(unittest.TestCase):
    def test_licitacion(self):
        resumen = leer("licitaciones_activas.json")["Listado"][0]
        detalle = leer("licitaciones_detalle.json")[resumen["CodigoExterno"]]["Listado"][0]
        o = licitacion_a_oportunidad(resumen, detalle)
        self.assertEqual(o.fuente, LICITACION)
        self.assertEqual(o.tipo, "Licitación LE")
        self.assertEqual(o.monto, 45_000_000)
        self.assertIn("Providencia", o.lugar)
        self.assertIn("tableros", o.detalle)            # incluye descripción e ítems
        self.assertTrue(o.con_detalle)
        self.assertIn(o.codigo, o.url)
        self.assertEqual(o.cierre.tzinfo, CL)

    def test_licitacion_sin_detalle(self):
        o = licitacion_a_oportunidad({"CodigoExterno": "X-1-L126", "Nombre": "N", "FechaCierre": "2026-11-01T10:00:00"}, None)
        self.assertFalse(o.con_detalle)
        self.assertIsNone(o.monto)
        self.assertEqual(o.tipo, "Licitación")

    def test_compra_agil(self):
        item = leer("compra_agil_publicadas.json")["payload"]["items"][0]
        det = leer("compra_agil_detalle.json")[item["codigo"]]["payload"]
        o = compra_agil_a_oportunidad(item, det)
        self.assertEqual(o.fuente, COMPRA_AGIL)
        self.assertEqual((o.llamado, o.ofertas), (1, 2))
        self.assertIn("Independencia", o.lugar)             # dirección de entrega
        self.assertIn("carga de datos", o.detalle)          # productos solicitados
        self.assertEqual(o.cierre, datetime(2026, 10, 23, 8, 0, tzinfo=CL))

    def test_json_ida_y_vuelta(self):
        item = leer("compra_agil_publicadas.json")["payload"]["items"][0]
        o = compra_agil_a_oportunidad(item, None)
        self.assertEqual(Oportunidad.desde_json(json.loads(json.dumps(o.a_json()))), o)

    def test_llamado_y_ofertas(self):
        lista = {"convocatoria": {"estado_convocatoria": 1}, "resumen": {"total_ofertas_recibidas": 2}}
        # El detalle es más nuevo: ya pasó a segundo llamado y las ofertas vuelven a contarse.
        self.assertEqual(llamado_y_ofertas(lista, {"convocatoria": {"estado_convocatoria": 2},
                                                   "resumen": {"total_ofertas_recibidas": 0}}), (2, 0))
        # Mismo llamado: las ofertas solo aumentan.
        self.assertEqual(llamado_y_ofertas(lista, {"convocatoria": {"estado_convocatoria": 1},
                                                   "resumen": {"total_ofertas_recibidas": 5}}), (1, 5))
        self.assertEqual(llamado_y_ofertas(lista, {}), (1, 2))


class RespuestaFalsa(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def error_http(codigo, retry_after=None):
    cabeceras = {"Retry-After": retry_after} if retry_after else {}
    e = urllib.error.HTTPError("https://api.example/x", codigo, "error", cabeceras, io.BytesIO(b""))
    return e


class TestReintentos(unittest.TestCase):
    def test_429_reintenta_con_backoff_y_respeta_retry_after(self):
        esperas = []
        t = TransporteHTTP(dormir=esperas.append)
        ok = RespuestaFalsa(b'{"Listado": []}')
        with mock.patch("urllib.request.urlopen", side_effect=[error_http(429), error_http(429, "1"), ok]) as m:
            self.assertEqual(t("https://api.example/x", {"ticket": "t"}), {"Listado": []})
        self.assertEqual(m.call_count, 3)
        self.assertEqual(esperas, [6.0, 1.0])

    def test_404_no_reintenta_y_no_expone_ticket(self):
        mensajes = []
        t = TransporteHTTP(dormir=lambda s: None, registro=mensajes.append)
        with mock.patch("urllib.request.urlopen", side_effect=[error_http(404)]) as m:
            self.assertIsNone(t("https://api.example/x", {"ticket": "secreto"}))
        self.assertEqual(m.call_count, 1)
        self.assertNotIn("secreto", " ".join(mensajes))

    def test_agota_intentos(self):
        esperas = []
        t = TransporteHTTP(dormir=esperas.append)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("sin red")):
            self.assertIsNone(t("https://api.example/x", intentos=3))
        self.assertEqual(esperas, [2.0, 4.0])              # no espera después del último intento

    def test_espera_creciente(self):
        self.assertLess(espera_reintento(0, 500), espera_reintento(1, 500))
        self.assertGreater(espera_reintento(0, 429), espera_reintento(0, 500))
        self.assertEqual(espera_reintento(0, 429, "no-numero"), 6.0)


class TestPaginacion(unittest.TestCase):
    def setUp(self):
        self.cliente = ClienteMercadoPublico(TransporteFixtures(FIXTURES), "demo", pausa_licitaciones=0)

    def test_busqueda_lee_todas_las_paginas(self):
        items, estado = self.cliente.buscar_compra_agil("datos", tamano=1, max_paginas=10)
        self.assertEqual(estado, "ok")
        self.assertEqual(len(items), 4)
        self.assertEqual(len({i["codigo"] for i in items}), 4)

    def test_busqueda_al_tope(self):
        items, estado = self.cliente.buscar_compra_agil("datos", tamano=1, max_paginas=2)
        self.assertEqual((len(items), estado), (2, "tope"))

    def test_busqueda_con_falla(self):
        cliente = ClienteMercadoPublico(lambda *a, **k: None, "demo", pausa_licitaciones=0)
        self.assertEqual(cliente.buscar_compra_agil("x"), ([], "falla"))

    def test_detalle_inexistente(self):
        self.assertIsNone(self.cliente.detalle_licitacion("9019-4-L126"))
        self.assertIsNone(self.cliente.detalle_compra_agil("0000-0-COT26"))


if __name__ == "__main__":
    unittest.main()
