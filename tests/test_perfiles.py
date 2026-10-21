"""Motor de perfiles: fuertes, débiles con contexto, exclusiones, zona y monto."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tenders_radar.perfiles import Perfil, cargar_configuracion, cargar_perfiles  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]

CFG = {
    "fuertes": ["análisis de datos", "tablero de control", "power bi"],
    "debiles": ["plataforma", "sistema"],
    "contexto": ["datos", "indicadores"],
    "exclusiones": ["computadores", "capacitación"],
    "exclusiones_duras": ["licencias"],
    "zona": {"regiones": ["metropolitana"], "comunas_excluidas": ["melipilla"],
             "comunas_preferidas": ["ñuñoa"]},
    "monto": {"minimo": 1_000_000, "maximo": 50_000_000},
}


class TestEvaluar(unittest.TestCase):
    def setUp(self):
        self.p = Perfil("Demo", CFG)

    def test_fuerte_en_nombre_es_A(self):
        ev = self.p.evaluar("Servicio de Análisis de Datos")
        self.assertEqual(ev.nivel, "A")
        self.assertEqual(ev.calce, ["análisis de datos"])

    def test_fuerte_en_nombre_gana_a_exclusion_normal(self):
        self.assertEqual(self.p.evaluar("Capacitación en Power BI").nivel, "A")

    def test_exclusion_dura_gana_a_fuerte(self):
        ev = self.p.evaluar("Renovación de licencias Power BI")
        self.assertIsNone(ev.nivel)
        self.assertIn("exclusión dura", ev.motivo_descarte)

    def test_exclusion_sin_fuerte_descarta(self):
        ev = self.p.evaluar("Compra de computadores para sistema", "datos")
        self.assertIsNone(ev.nivel)
        self.assertTrue(ev.motivo_descarte.startswith("exclusión"))

    def test_debil_mas_fuerte_en_detalle_es_A(self):
        ev = self.p.evaluar("Desarrollo de plataforma", "incluye tablero de control")
        self.assertEqual(ev.nivel, "A")
        self.assertEqual(ev.calce, ["tablero de control", "plataforma"])

    def test_debil_con_contexto_es_B(self):
        self.assertEqual(self.p.evaluar("Plataforma de indicadores").nivel, "B")
        self.assertEqual(self.p.evaluar("Contratación de plataforma", "publicar datos").nivel, "B")

    def test_debil_sin_contexto_descarta(self):
        ev = self.p.evaluar("Mantención de sistema de climatización")
        self.assertIsNone(ev.nivel)
        self.assertIn("débil sin contexto", ev.motivo_descarte)

    def test_debil_solo_en_detalle_no_cuenta(self):
        self.assertIsNone(self.p.evaluar("Compra de muebles", "plataforma de datos").nivel)

    def test_fuerte_solo_en_detalle_es_B(self):
        self.assertEqual(self.p.evaluar("Servicio profesional", "análisis de datos").nivel, "B")

    def test_sin_senales(self):
        ev = self.p.evaluar("Construcción de veredas")
        self.assertIsNone(ev.nivel)
        self.assertEqual(ev.motivo_descarte, "")


class TestPrefiltro(unittest.TestCase):
    def test_puntajes(self):
        p = Perfil("Demo", CFG)
        self.assertEqual(p.prefiltro("Tablero de control"), 2)
        self.assertEqual(p.prefiltro("Plataforma web"), 1)
        self.assertEqual(p.prefiltro("Computadores y plataforma"), 0)
        self.assertEqual(p.prefiltro("Licencias de tablero de control"), 0)
        self.assertEqual(p.prefiltro("Neumáticos"), 0)


class TestZonaYMonto(unittest.TestCase):
    def setUp(self):
        self.p = Perfil("Demo", CFG)

    def test_region(self):
        self.assertEqual(self.p.en_zona("Región Metropolitana de Santiago", "Santiago"), (True, False))
        self.assertEqual(self.p.en_zona("Región de Valparaíso", "Viña del Mar"), (False, False))

    def test_comunas(self):
        self.assertEqual(self.p.en_zona("Metropolitana", "Municipalidad X Melipilla"), (False, False))
        self.assertEqual(self.p.en_zona("Metropolitana", "Av. Demo 1, Nunoa"), (True, True))

    def test_sin_zona_acepta_todo(self):
        self.assertEqual(Perfil("Libre", {"fuertes": ["x"]}).en_zona("", ""), (True, False))

    def test_monto(self):
        self.assertTrue(self.p.en_rango_monto(None))
        self.assertTrue(self.p.en_rango_monto(1_000_000))
        self.assertFalse(self.p.en_rango_monto(999_999))
        self.assertFalse(self.p.en_rango_monto(60_000_000))


class TestEjemplo(unittest.TestCase):
    def test_profiles_example_carga(self):
        cfg = cargar_configuracion(RAIZ / "profiles.example.json")
        perfiles = cargar_perfiles(cfg)
        self.assertEqual(len(perfiles), 3)
        self.assertTrue(all(p.fuertes and p.busquedas for p in perfiles))
        self.assertEqual(cfg["plazo_critico_horas"]["compra_agil"], 24)


if __name__ == "__main__":
    unittest.main()
