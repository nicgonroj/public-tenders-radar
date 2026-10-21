"""Corrida completa del modo offline contra los resultados esperados de los fixtures."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tenders_radar.cli import main  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]


class TestOffline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def correr(self, *extra):
        args = ["--offline", "--silencioso", "--perfiles", str(RAIZ / "profiles.example.json"),
                "--db", str(self.dir / "demo.sqlite"), "--salida", str(self.dir / "out"), *extra]
        self.assertEqual(main(args), 0)
        with (self.dir / "out" / "radar-2026-10-20.csv").open(encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def esperado(self):
        esp = json.loads((RAIZ / "fixtures" / "esperado.json").read_text(encoding="utf-8"))
        return {(cod, perfil, nivel) for cod, por_perfil in esp.items()
                for perfil, nivel in por_perfil.items() if not perfil.startswith("_")}

    def test_barrido_completo_detecta_exactamente_lo_esperado(self):
        filas = self.correr("--barrido-completo")
        self.assertEqual({(f["codigo"], f["perfil"], f["nivel"]) for f in filas}, self.esperado())

    def test_segunda_corrida_no_repite_nuevas(self):
        primera = self.correr()
        self.assertTrue(all(f["nueva"] == "si" for f in primera))
        segunda = self.correr()
        self.assertEqual(len(segunda), len(primera))
        self.assertTrue(all(f["nueva"] == "no" for f in segunda))

    def test_reclasificar_sin_api(self):
        antes = self.correr()
        self.assertEqual(main(["--reclasificar", "--offline", "--silencioso", "--perfiles",
                               str(RAIZ / "profiles.example.json"), "--db", str(self.dir / "demo.sqlite"),
                               "--salida", str(self.dir / "out")]), 0)
        self.assertTrue((self.dir / "out" / "radar-2026-10-20.md").exists())
        self.assertTrue(antes)

    def test_markdown_tiene_cobertura_y_perfiles(self):
        self.correr()
        md = (self.dir / "out" / "radar-2026-10-20.md").read_text(encoding="utf-8")
        for texto in ("## Cobertura", "## Consultora de analítica de datos", "## Empresa de transporte de pasajeros",
                      "## Proveedor de insumos de aseo", "Candidatas sin detalle todavía (se completan en la próxima corrida): 1"):
            self.assertIn(texto, md)


if __name__ == "__main__":
    unittest.main()
