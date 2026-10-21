"""Normalización de texto y patrones de palabra completa."""
import doctest
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tenders_radar import texto  # noqa: E402
from tenders_radar.texto import buscar, celda, compilar, norm, plata  # noqa: E402


class TestNorm(unittest.TestCase):
    def test_minusculas_tildes_y_signos(self):
        self.assertEqual(norm("Análisis de DATOS, 2026!").split(), ["analisis", "de", "datos", "2026"])

    def test_enie_y_dieresis(self):
        self.assertEqual(norm("Ñuñoa"), "nunoa")
        self.assertEqual(norm("pingüino"), "pinguino")

    def test_none_y_vacio(self):
        self.assertEqual(norm(None), "")
        self.assertEqual(norm(""), "")

    def test_doctest(self):
        self.assertEqual(doctest.testmod(texto).failed, 0)


class TestCompilar(unittest.TestCase):
    def test_palabra_completa(self):
        pat = compilar(["rpa"])
        self.assertEqual(buscar(pat, norm("Servicio de RPA para finanzas")), ["rpa"])
        self.assertEqual(buscar(pat, norm("Compra de tarpaulin")), [])

    def test_frase_con_tildes_y_espacios_dobles(self):
        pat = compilar(["análisis de datos"])
        self.assertEqual(buscar(pat, norm("ANALISIS  DE   DATOS")), ["análisis de datos"])
        # La puntuación entre palabras se vuelve espacio y la frase igual calza.
        self.assertEqual(buscar(pat, norm("análisis de-datos")), ["análisis de datos"])

    def test_frases_vacias_se_ignoran(self):
        self.assertEqual(compilar(["", "  ", "!!"]), [])


class TestFormato(unittest.TestCase):
    def test_plata(self):
        self.assertEqual(plata(1234567), "$1.234.567")
        self.assertEqual(plata(None), "sin dato")
        self.assertEqual(plata(0), "sin dato")

    def test_celda(self):
        self.assertEqual(celda("a | b\n c"), "a / b c")
        self.assertEqual(celda("x" * 10, 5), "xxxx…")


if __name__ == "__main__":
    unittest.main()
