"""
Busca y baja VIDEOS REALES de bancos gratis: el material del modo documental.

Dos bancos, los dos gratis y con licencia para usar los videos en YouTube sin
pagar ni citar (aunque el estudio guarda de donde sale cada uno):

    pexels   api.pexels.com/videos. Calidad alta, mucho material de ciudades,
             naturaleza, gente y oficios. Cupo gratis: 200 busquedas por hora.
    pixabay  pixabay.com/api/videos. Mas variado y con mas cupo (100 por
             minuto). Algo menos de calidad media.

Se pregunta a los dos que tengan clave y se juntan los resultados: con el cupo
de Pexels, un video de doscientos planos lo agotaria solo, y Pixabay sigue.

Las claves se leen por CONTRATO, como las demas: PEXELS_API_KEY y
PIXABAY_API_KEY en el entorno, o `pexels.clave` / `pixabay.clave` en el
claves.json de la carpeta de secretos, o esas lineas del .env de esa carpeta.

No cuesta dinero: no hay medidor de coste.
"""
import json
import os

import requests

CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "secretos")

BANCOS = ("pexels", "pixabay")
_ENTORNO = {"pexels": "PEXELS_API_KEY", "pixabay": "PIXABAY_API_KEY"}


class SinClave(RuntimeError):
    """Ningun banco de video tiene clave."""


def clave(banco):
    nombre = _ENTORNO[banco]
    valor = (os.environ.get(nombre) or "").strip()
    if valor:
        return valor
    try:
        with open(os.path.join(CARPETA_SECRETOS, "claves.json"), "r",
                  encoding="utf-8-sig") as fh:
            valor = str(((json.load(fh) or {}).get(banco) or {}).get("clave") or "")
        if valor.strip():
            return valor.strip()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(CARPETA_SECRETOS, ".env"), "r",
                  encoding="utf-8-sig") as fh:
            for linea in fh:
                n, _, v = linea.strip().partition("=")
                if n.strip() == nombre and v.strip():
                    return v.strip()
    except OSError:
        pass
    return ""


def con_clave():
    """Los bancos que tienen clave puesta, en orden de preferencia."""
    return [b for b in BANCOS if clave(b)]


def _archivo_pexels(video, ancho):
    """El fichero del video mas pequeno que cubra `ancho` (o el mayor si no)."""
    ficheros = [f for f in video.get("video_files") or []
                if f.get("link") and f.get("width") and f.get("height")
                and str(f.get("file_type") or "").endswith("mp4")]
    if not ficheros:
        return None
    validos = sorted((f for f in ficheros if f["width"] >= ancho),
                     key=lambda f: f["width"])
    return validos[0] if validos else max(ficheros, key=lambda f: f["width"])


def _pexels(busqueda, vertical, ancho, por_pagina):
    respuesta = requests.get(
        "https://api.pexels.com/videos/search",
        params={"query": busqueda, "per_page": por_pagina,
                "orientation": "portrait" if vertical else "landscape"},
        headers={"Authorization": clave("pexels")}, timeout=30)
    if respuesta.status_code == 429:
        raise RuntimeError("pexels: cupo de busquedas agotado (200 por hora)")
    respuesta.raise_for_status()
    salida = []
    for video in respuesta.json().get("videos") or []:
        fichero = _archivo_pexels(video, ancho)
        if not fichero:
            continue
        salida.append({
            "banco": "pexels", "id": f"pexels-{video['id']}",
            "url": fichero["link"], "ancho": fichero["width"],
            "alto": fichero["height"], "duracion": float(video.get("duration") or 0),
            "autor": ((video.get("user") or {}).get("name") or ""),
            "pagina": video.get("url") or "",
            "miniatura": video.get("image") or ""})
    return salida


def _pixabay(busqueda, vertical, ancho, por_pagina):
    respuesta = requests.get(
        "https://pixabay.com/api/videos/",
        params={"key": clave("pixabay"), "q": busqueda[:100],
                "per_page": max(3, por_pagina), "safesearch": "true"},
        timeout=30)
    if respuesta.status_code == 429:
        raise RuntimeError("pixabay: cupo de busquedas agotado")
    respuesta.raise_for_status()
    salida = []
    for video in respuesta.json().get("hits") or []:
        tamanos = [t for t in (video.get("videos") or {}).values()
                   if isinstance(t, dict) and t.get("url") and t.get("width")]
        if not tamanos:
            continue
        validos = sorted((t for t in tamanos if t["width"] >= ancho),
                         key=lambda t: t["width"])
        elegido = validos[0] if validos else max(tamanos, key=lambda t: t["width"])
        if bool(vertical) != (elegido["height"] > elegido["width"]):
            continue
        salida.append({
            "banco": "pixabay", "id": f"pixabay-{video['id']}",
            "url": elegido["url"], "ancho": elegido["width"],
            "alto": elegido["height"], "duracion": float(video.get("duration") or 0),
            "autor": video.get("user") or "", "pagina": video.get("pageURL") or "",
            "miniatura": ((video.get("videos") or {}).get("tiny") or {}).get("thumbnail", "")})
    return salida


def buscar(busqueda, *, vertical=False, ancho=1920, por_pagina=15):
    """Videos de todos los bancos con clave para esta busqueda (en ingles).

    -> (lista de candidatos, [avisos]). Un banco que falla no tumba la
    busqueda: se dice en los avisos y se sigue con el otro.
    """
    bancos = con_clave()
    if not bancos:
        raise SinClave("no hay clave de Pexels ni de Pixabay")
    candidatos, avisos = [], []
    for banco in bancos:
        try:
            funcion = _pexels if banco == "pexels" else _pixabay
            candidatos.extend(funcion(busqueda, vertical, ancho, por_pagina))
        except Exception as fallo:                          # noqa: BLE001
            avisos.append(f"{banco}: {fallo}")
    return candidatos, avisos


def descargar(url, destino):
    """Baja el video a `destino` de una vez (via un .parcial). -> destino"""
    temporal = destino + ".parcial"
    with requests.get(url, stream=True, timeout=120) as respuesta:
        respuesta.raise_for_status()
        with open(temporal, "wb") as fh:
            for trozo in respuesta.iter_content(1 << 20):
                fh.write(trozo)
    os.replace(temporal, destino)
    return destino
