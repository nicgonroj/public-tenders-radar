"""Barridos de las dos fuentes: listar lo abierto, prefiltrar por nombre y completar detalles.

El flujo es el mismo para ambas fuentes:

1. Listar lo abierto (licitaciones activas, o compras ágiles publicadas por búsqueda o barrido).
2. Prefiltrar con solo el nombre: descarta en memoria lo que ningún perfil podría aceptar.
3. Pedir el detalle solo de las candidatas que no estén en la caché (hasta un tope por corrida).
4. Convertir todo a `Oportunidad`.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable

from . import almacen
from .api import ClienteMercadoPublico
from .modelos import COMPRA_AGIL, LICITACION, Oportunidad, compra_agil_a_oportunidad, licitacion_a_oportunidad
from .perfiles import Perfil

Registro = Callable[[str], None]


def prefiltrar(items: list[dict], perfiles: list[Perfil], campo_nombre: str) -> list[dict]:
    """Deja los items cuyo nombre interesa a algún perfil, primero los de palabra fuerte."""
    puntuados = [(max(p.prefiltro(it.get(campo_nombre) or "") for p in perfiles), it) for it in items]
    puntuados = [x for x in puntuados if x[0] > 0]
    puntuados.sort(key=lambda x: -x[0])          # sort estable: conserva el orden original en empates
    return [it for _, it in puntuados]


def completar_detalles(db, codigos: list[str], fuente: str, obtener: Callable[[str], dict | None],
                       tope: int, hilos: int, ahora: datetime, log: Registro) -> int:
    """Pide en paralelo los detalles que faltan en la caché (como máximo `tope`) y los guarda."""
    faltan = [c for c in codigos if not almacen.tiene_detalle(db, c)][:tope]
    hechos = 0
    with ThreadPoolExecutor(max_workers=max(1, hilos)) as ex:
        # Las escrituras en SQLite se hacen en este hilo; los hilos solo hacen la consulta HTTP.
        for codigo, det in zip(faltan, ex.map(obtener, faltan)):
            if det is not None:
                almacen.guardar_detalle(db, codigo, fuente, det, ahora)
                hechos += 1
    db.commit()
    log(f"  detalles nuevos: {hechos} de {len(faltan)} pedidos ({len(codigos) - len(faltan)} ya en caché o sobre el tope)")
    return hechos


def barrer_licitaciones(cliente: ClienteMercadoPublico, perfiles: list[Perfil], db, tope: int,
                        ahora: datetime, log: Registro) -> tuple[list[Oportunidad], dict]:
    lista = cliente.licitaciones_activas()
    stats = {"licitaciones": len(lista or []), "fallas": [] if lista is not None else ["licitaciones activas"]}
    lista = lista or []
    log(f"Licitaciones activas: {len(lista)}")
    candidatas = prefiltrar(lista, perfiles, "Nombre")
    stats["licitaciones_prefiltro"] = len(candidatas)
    log(f"  pasan el prefiltro por nombre: {len(candidatas)}")
    # Un hilo: la API v1 responde 429 a consultas simultáneas.
    completar_detalles(db, [it["CodigoExterno"] for it in candidatas], LICITACION,
                       cliente.detalle_licitacion, tope, 1, ahora, log)
    return [licitacion_a_oportunidad(it, almacen.detalle(db, it["CodigoExterno"])) for it in candidatas], stats


def barrer_compra_agil(cliente: ClienteMercadoPublico, perfiles: list[Perfil], db, tope: int,
                       completo: bool, max_paginas: int, ahora: datetime, log: Registro,
                       hilos: int = 4) -> tuple[list[Oportunidad], dict]:
    """Modo rápido: una búsqueda por cada término de los perfiles. Modo completo: barrido incremental."""
    if completo:
        vistos, fallas, topes = _barrido_completo(cliente, db, max_paginas, ahora, log)
    else:
        vistos, fallas, topes = _busqueda_por_terminos(cliente, perfiles, hilos, log)
    lista = list(vistos.values())
    stats = {"compras_agiles": len(lista), "fallas": fallas, "topes": topes,
             "modo_compra_agil": "barrido completo" if completo else "búsqueda por términos"}
    candidatas = prefiltrar(lista, perfiles, "nombre")
    stats["compras_agiles_prefiltro"] = len(candidatas)
    log(f"  pasan el prefiltro por nombre: {len(candidatas)}")
    completar_detalles(db, [it["codigo"] for it in candidatas], COMPRA_AGIL,
                       cliente.detalle_compra_agil, tope, hilos, ahora, log)
    return [compra_agil_a_oportunidad(it, almacen.detalle(db, it["codigo"])) for it in candidatas], stats


def _busqueda_por_terminos(cliente, perfiles, hilos, log):
    terminos = sorted({t for p in perfiles for t in p.busquedas})
    vistos, fallas, topes = {}, [], []
    marcas = {"ok": "", "tope": " (al tope: hay más resultados; el barrido completo los cubre)",
              "falla": " (la API no respondió)"}
    with ThreadPoolExecutor(max_workers=max(1, hilos)) as ex:
        for termino, (items, estado) in zip(terminos, ex.map(cliente.buscar_compra_agil, terminos)):
            for it in items:
                vistos[it["codigo"]] = it               # un mismo código puede salir en varios términos
            if estado == "falla":
                fallas.append(f"búsqueda '{termino}'")
            elif estado == "tope":
                topes.append(termino)
            log(f"  búsqueda '{termino}': {len(items)} resultados{marcas[estado]}")
    log(f"Compras ágiles publicadas encontradas por búsqueda: {len(vistos)} (sin duplicados)")
    return vistos, fallas, topes


def _barrido_completo(cliente, db, max_paginas, ahora, log, tamano=20, paginas_conocidas_para_parar=3,
                      fallas_para_parar=6):
    """Lee las publicadas de la más nueva a la más antigua y se detiene al llegar a lo ya visto.

    Solo un barrido sin huecos marca lo leído como visto. Si faltó una página o se cortó antes de
    llegar a la zona conocida, no se marca nada: el próximo barrido vuelve a leer desde el inicio y
    cubre el hueco. Así nunca se pierde una compra ágil por una falla transitoria de la API.
    """
    vistos, fallas, por_marcar = {}, [], []
    pagina, fallas_seguidas, conocidas, leidas, llego_al_final = 1, 0, 0, 0, False
    while pagina <= max_paginas and fallas_seguidas < fallas_para_parar and conocidas < paginas_conocidas_para_parar:
        payload = cliente.pagina_compra_agil(pagina, tamano, ordenar_por="FechaPublicacion")
        if payload is None:
            fallas_seguidas += 1
            fallas.append(f"página {pagina}")
            pagina += 1
            continue
        fallas_seguidas = 0
        items = payload.get("items") or []
        if not items:
            llego_al_final = True
            break
        leidas += 1
        ya_vistos = sum(1 for it in items if almacen.visto_ca(db, it["codigo"]))
        conocidas = conocidas + 1 if ya_vistos == len(items) else 0
        for it in items:
            vistos[it["codigo"]] = it
            por_marcar.append(it["codigo"])
        if pagina >= ((payload.get("paginacion") or {}).get("total_paginas") or 1):
            llego_al_final = True
            break
        pagina += 1
    if fallas_seguidas >= fallas_para_parar:
        fallas.append("barrido detenido por fallas seguidas de la API")
    elif not (llego_al_final or conocidas >= paginas_conocidas_para_parar):
        fallas.append("barrido cortado en el máximo de páginas sin llegar a lo ya visto")
    if not fallas:
        almacen.marcar_vistos_ca(db, por_marcar, ahora)
        db.commit()
    else:
        log("  Barrido incompleto: no se marca lo leído como visto, el próximo barrido lo cubre.")
    log(f"Compras ágiles leídas en el barrido: {len(vistos)} en {leidas} páginas")
    return vistos, fallas, []
