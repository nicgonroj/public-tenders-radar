# public-tenders-radar

Radar de compras públicas para Chile: detecta **licitaciones y compras ágiles abiertas en Mercado Público
(ChileCompra)** que calzan con el perfil de una empresa, **recuerda lo ya visto** en SQLite, **prioriza por
fecha de cierre** y genera un resumen diario en Markdown y CSV. Es la versión pública y general de una
herramienta que uso a diario: cualquier empresa la configura con su propio archivo de perfiles.

> Este repositorio no contiene datos reales de compradores ni de proveedores. Los perfiles de ejemplo son
> genéricos y los fixtures del modo demo son 100 % sintéticos: organismos, códigos, montos y textos inventados.

## El problema

ChileCompra publica miles de oportunidades: cientos de licitaciones activas y un flujo diario de compras ágiles
que cierran en pocos días. Filtrarlas a mano en el buscador es lento, depende de acertar con las palabras de
búsqueda y obliga a revisar todos los días lo mismo. El resultado típico: se pierden cierres, se cotiza tarde
y se gasta tiempo leyendo fichas que nunca calzaron (una "plataforma" puede ser de datos o de hormigón).

## La solución

```text
API licitaciones v1 ─┐                                   ┌─► perfil 1 ─┐
                     ├─► prefiltro ─► detalle (caché) ─► motor de      ├─► memoria SQLite ─► prioridad ─► resumen .md
API Compra Ágil v2 ──┘   por nombre   solo candidatas    perfiles      │   (nueva / ya vista)  por cierre   + .csv
 (búsqueda o barrido                                     └─► perfil N ─┘
  incremental)            zona y monto ─────────────────────────────────┘
```

- **Cliente de las APIs oficiales** (`api.py`): licitaciones v1 y Compra Ágil v2 con ticket por variable de
  entorno, reintentos con backoff ante 429 y errores transitorios (respeta `Retry-After`), paginación y
  registro que nunca expone el ticket. Los detalles de licitación se piden de a uno porque la API castiga
  las consultas simultáneas.
- **Prefiltro por nombre** (`barrido.py`): pedir el detalle es la consulta cara; solo se pide para lo que
  algún perfil podría aceptar, y queda en caché para no volver a pedirlo.
- **Motor de perfiles** (`perfiles.py`): palabras **fuertes** (bastan solas), **débiles** que necesitan
  contexto ("traslado" solo cuenta si hay "pasajeros" o "estudiantes"), **exclusiones** y **exclusiones
  duras**, más filtros de **región/comuna** (con comunas preferidas) y **rango de monto**. Calce **A** es
  claro; **B** conviene revisarlo.
- **Memoria y deduplicación** (`almacen.py`): cada oportunidad se registra por perfil con su primera y
  última vez; lo ya visto no vuelve a marcarse como nuevo y lo que deja de calzar se olvida. El barrido
  completo de compra ágil es incremental: se detiene al llegar a páginas ya vistas y solo marca como visto
  un barrido sin huecos.
- **Priorización** (`clasificacion.py`): cruza tipo de proceso, horas al cierre y calidad del calce. Un
  segundo llamado de compra ágil va primero; una licitación a menos de 24 h queda como "Sin tiempo".
- **Salidas** (`reporte.py`): resumen Markdown por perfil (nuevas primero, con ⚠ en plazo crítico) y CSV
  plano para Excel, Sheets o un BI.

## Resultados del modo offline

Medidos sobre los fixtures sintéticos (`fixtures/`, generados con `python scripts/generar_fixtures.py`) y los
tres perfiles de `profiles.example.json`. Son resultados de la demo, no métricas de producción.

| Etapa | Licitaciones | Compras ágiles | Total |
|---|---:|---:|---:|
| Publicadas en los fixtures | 19 | 18 | 37 |
| Revisadas (búsqueda por términos / barrido completo) | 19 | 15 / 18 | 34 / 37 |
| Pasan el prefiltro por nombre (se pide su detalle) | 13 | 13 | 26 |
| Descartadas sin pedir detalle | 6 | 5 | 11 |
| Oportunidades con calce para al menos un perfil | 9 | 10 | **19** |

| Perfil | Calce A | Calce B | Descartadas por zona, monto, cierre o débil sin contexto |
|---|---:|---:|---:|
| Consultora de analítica de datos | 7 | 3 | 2 (1 fuera de monto, 1 ya cerrada) |
| Empresa de transporte de pasajeros | 2 | 2 | 4 (3 fuera de zona, 1 ya cerrada) |
| Proveedor de insumos de aseo | 4 | 1 | 3 (1 fuera de monto, 1 ya cerrada, 1 débil sin contexto) |

- El 100 % de los casos que `fixtures/esperado.json` marca como calce se detecta con el nivel esperado y
  ninguno de los distractores entra (lo verifica `tests/test_offline.py`).
- Se pidieron 26 detalles en vez de 37: el prefiltro evita 11 consultas caras (30 %). Una licitación no
  tiene detalle a propósito (simula un 404) y se reporta como "candidata sin detalle"; igual se detecta por
  su nombre.
- **Deduplicación**: la primera corrida marca 19 detecciones como nuevas; la segunda, con la misma memoria,
  marca 0 y las muestra como "ya vistas y siguen abiertas".
- **Barrido incremental**: con páginas de 3 resultados, la segunda pasada lee 3 páginas en vez de 6.

Los casos difíciles muestran las reglas: «Capacitación en Power BI» entra (la palabra fuerte manda sobre la
exclusión "capacitación"), «Renovación de licencias Power BI Pro» no entra (exclusión dura) y «Insumos de
oficina» no entra para el proveedor de aseo (débil sin contexto).

## Cómo usarlo

```bash
# Demo sin red ni ticket: usa los fixtures sintéticos y vive en la fecha de referencia de los fixtures
PYTHONPATH=src python -m tenders_radar --offline
PYTHONPATH=src python -m tenders_radar --offline --barrido-completo

# Con la API real
cp profiles.example.json profiles.json      # adapta los perfiles a tu empresa
export MERCADOPUBLICO_TICKET=...            # tu ticket personal, nunca en el repositorio
PYTHONPATH=src python -m tenders_radar                       # licitaciones + compra ágil por términos
PYTHONPATH=src python -m tenders_radar --barrido-completo    # compra ágil completa e incremental (lento)
PYTHONPATH=src python -m tenders_radar --reclasificar        # re-filtrar la última corrida tras editar perfiles
PYTHONPATH=src python -m tenders_radar --solo licitaciones   # una sola fuente

python -m unittest discover -s tests
```

El ticket se solicita gratis en la [página oficial de la API de Mercado Público](https://api.mercadopublico.cl/).
Sin ticket, el radar se detiene y sugiere `--offline`; el modo en línea solo se usa si hay ticket.

Las salidas quedan en `output/radar-AAAA-MM-DD.md` y `.csv`; la memoria, en `data/radar.sqlite`
(`data/demo.sqlite` en modo offline). Ambas carpetas están fuera del control de versiones. Para una corrida
diaria basta un `cron` o un `launchd` que llame al comando con el ticket en el entorno.

### Cómo escribir un perfil

```json
"Empresa de transporte de pasajeros": {
  "fuertes": ["transporte de pasajeros", "arriendo de buses"],
  "debiles": ["traslado", "transporte"],
  "contexto": ["pasajeros", "estudiantes", "adultos mayores"],
  "exclusiones": ["carga", "mudanza"],
  "exclusiones_duras": ["transporte de residuos"],
  "busquedas_compra_agil": ["transporte", "traslado", "buses"],
  "zona": {"regiones": ["metropolitana"], "comunas_excluidas": ["melipilla"], "comunas_preferidas": ["providencia"]},
  "monto": {"minimo": 1000000}
}
```

Las frases se comparan sin tildes ni mayúsculas y como palabras completas. Las débiles y las exclusiones
solo se buscan en el nombre, que es lo que mejor describe la compra; las fuertes y el contexto también en
el detalle (descripción e ítems).

## Limitaciones

- Es un filtro por reglas sobre el texto de la ficha: no lee las bases ni los adjuntos, y no reemplaza
  revisarlas. Un calce B o una oportunidad con palabras poco usuales pueden requerir ajustar el perfil.
- La búsqueda rápida de compra ágil depende de los términos del perfil; el barrido completo cubre todo,
  pero la API tarda decenas de segundos por página.
- El filtro de zona usa la ubicación del comprador que informa la API, no el lugar donde se presta el servicio.
- Las cifras de esta página salen de datos sintéticos; el rendimiento real depende de la calidad de cada perfil.
- Usa `zoneinfo`; en Windows puede requerir el paquete `tzdata`.

## Stack

Python 3.10+ (solo biblioteca estándar) · API pública de Mercado Público · SQLite · unittest

---

**Nicolás González Rojas** · Head of Data & BI · [LinkedIn](https://www.linkedin.com/in/nicolas-gonzalez-rojas)
