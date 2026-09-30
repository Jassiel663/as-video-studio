"""
Anima un plano con Google Veo: una imagen quieta entra, un clip corto sale.

Es IMAGEN A VIDEO y no texto a video a proposito: el plano ya esta dibujado con
el estilo y el reparto del canal, y lo que se le pide a Veo es que lo MUEVA, no
que lo vuelva a dibujar. Asi el clip conserva la cara del protagonista y la
paleta del video, que es lo que un generador de texto a video no sabe sostener.

Lo que Veo NO sabe hacer, medido en la prueba del 29-09-2026: mantener texto.
Una notificacion desaparece, una cifra se deforma. Por eso quien decide QUE
planos se animan (pasos/animar.py) deja fuera cualquiera que lleve letras; este
motor no lo sabe ni lo comprueba.

La clave se lee por CONTRATO, como en imagen_openai: GEMINI_API_KEY en el
entorno, o `google.clave` en el claves.json de la carpeta de secretos, o la
linea GEMINI_API_KEY del .env de esa carpeta. Nunca importando pasos/claves.py.

    mp4, meta = generar("plano.png", "slow push-in...", segundos=4)

La API: POST models/<modelo>:predictLongRunning, que devuelve una operacion; se
pregunta por ella hasta que dice `done` y se baja el video de la URI que trae.
Se paga el clip ENTERO (4, 6 u 8 s) aunque el plano dure menos.
"""
import base64
import json
import os
import time

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"

MODELOS = {
    "lite": "veo-3.1-lite-generate-preview",
    "fast": "veo-3.1-fast-generate-preview",
}

#: Duraciones que acepta la API. A 720p solo 4 y 6: el clip de 8 s exige 1080p.
DURACIONES_720 = (4, 6)
DURACION_1080 = 8

#: Cada cuanto se pregunta por la operacion. En la prueba un clip de 4 s tardo
#: 42-44 s; preguntar mas a menudo no lo acelera y gasta cuota de lectura.
ESPERA_ENTRE_CONSULTAS_S = 8.0
PLAZO_S = 900.0

CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "secretos")


class SinClave(RuntimeError):
    """No hay clave de Google en ningun sitio donde se busca."""


class Rechazado(RuntimeError):
    """Veo termino sin devolver video: su filtro de contenido lo descarto."""


def clave():
    """La clave de la Gemini API, del entorno o del almacen del Estudio."""
    valor = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if valor:
        return valor
    try:
        with open(os.path.join(CARPETA_SECRETOS, "claves.json"), "r",
                  encoding="utf-8-sig") as fh:
            valor = str(((json.load(fh) or {}).get("google") or {}).get("clave") or "")
        if valor.strip():
            return valor.strip()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(CARPETA_SECRETOS, ".env"), "r",
                  encoding="utf-8-sig") as fh:
            for linea in fh:
                nombre, _, valor = linea.strip().partition("=")
                if nombre.strip() == "GEMINI_API_KEY" and valor.strip():
                    return valor.strip()
    except OSError:
        pass
    return ""


def duracion_de_clip(segundos_plano):
    """(segundos que se piden a Veo, resolucion) para cubrir un plano. -> tuple

    Lo mas corto que lo cubre: un plano de 2,6 s se pide de 4. Por encima de 6 s
    hace falta el de 8, que la API solo da a 1080p. Mas de 8 no cabe en un clip:
    devuelve (None, None) y ese plano no se anima.
    """
    for opcion in DURACIONES_720:
        if segundos_plano <= opcion + 1e-6:
            return opcion, "720p"
    if segundos_plano <= DURACION_1080 + 1e-6:
        return DURACION_1080, "1080p"
    return None, None


def _pedir(metodo, url, api_key, **kw):
    cabeceras = {"x-goog-api-key": api_key}
    cabeceras.update(kw.pop("headers", {}) or {})
    ultimo = None
    for intento in range(5):
        try:
            r = requests.request(metodo, url, headers=cabeceras, timeout=120, **kw)
        except requests.RequestException as fallo:
            ultimo = f"{type(fallo).__name__}: {fallo}"
            time.sleep(min(5 * (intento + 1), 30))
            continue
        # 429 es cuota por minuto: se espera y se vuelve. Un 5xx, igual.
        if r.status_code in (429, 500, 502, 503, 504):
            ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
            time.sleep(min(10 * (intento + 1), 60))
            continue
        return r
    raise RuntimeError(f"Veo no contesta tras varios intentos: {ultimo}")


def generar(imagen, prompt, *, modo="fast", segundos=4, resolucion="720p",
            aspecto="16:9", negativo="", api_key=None, avisar=None):
    """Anima `imagen` (un PNG del disco). -> (bytes del mp4, meta)

    `modo` es "lite" o "fast" (ver MODELOS). `segundos` tiene que ser uno de los
    que da `duracion_de_clip`: la API rechaza cualquier otro.
    """
    api_key = api_key or clave()
    if not api_key:
        raise SinClave("no hay clave de Google para Veo: ponla en "
                       "Configuracion > Claves (Google Veo)")
    modelo = MODELOS.get(modo)
    if not modelo:
        raise ValueError(f"modo de Veo desconocido: {modo!r} (son {', '.join(MODELOS)})")
    with open(imagen, "rb") as fh:
        datos = base64.b64encode(fh.read()).decode("ascii")
    parametros = {"aspectRatio": aspecto, "durationSeconds": int(segundos),
                  "resolution": resolucion,
                  # con imagen de entrada es el unico valor que admite la API
                  "personGeneration": "allow_adult"}
    # LO QUE NO SE QUIERE VA DENTRO DEL PROMPT, no en `negativePrompt`. Fast
    # acepta el parametro y Lite lo rechaza con un 400 («negativePrompt isn't
    # supported by this model», 30-09-2026): con el parametro, el mismo render
    # animaba en un modo y en el otro dejaba todos los planos quietos.
    if negativo:
        prompt = f"{prompt} Avoid: {negativo}."
    cuerpo = {"instances": [{"prompt": prompt,
                             "image": {"bytesBase64Encoded": datos,
                                       "mimeType": "image/png"}}],
              "parameters": parametros}

    t0 = time.time()
    r = _pedir("POST", f"{BASE}/models/{modelo}:predictLongRunning", api_key,
               json=cuerpo)
    if r.status_code != 200:
        raise RuntimeError(f"Veo rechaza la peticion (HTTP {r.status_code}): {r.text[:400]}")
    operacion = r.json().get("name")
    if not operacion:
        raise RuntimeError(f"Veo no devolvio operacion: {r.text[:300]}")

    while True:
        if time.time() - t0 > PLAZO_S:
            raise RuntimeError(f"Veo no termino en {PLAZO_S:.0f} s ({operacion})")
        time.sleep(ESPERA_ENTRE_CONSULTAS_S)
        estado = _pedir("GET", f"{BASE}/{operacion}", api_key).json()
        if avisar:
            avisar(time.time() - t0)
        if estado.get("done"):
            break
    if estado.get("error"):
        raise RuntimeError(f"Veo fallo: {estado['error']}")
    respuesta = (estado.get("response") or {}).get("generateVideoResponse") or {}
    muestras = respuesta.get("generatedSamples") or []
    if not muestras:
        # sin video y sin error: lo ha descartado su filtro. Se paga? No: la API
        # solo cobra los segundos que devuelve.
        motivo = respuesta.get("raiMediaFilteredReasons") or respuesta
        raise Rechazado(f"Veo no devolvio video (filtro de contenido): "
                        f"{json.dumps(motivo, ensure_ascii=False)[:300]}")
    uri = muestras[0]["video"]["uri"]
    bajada = _pedir("GET", uri, api_key, allow_redirects=True)
    if bajada.status_code != 200 or not bajada.content:
        raise RuntimeError(f"no se pudo bajar el clip de Veo (HTTP {bajada.status_code})")
    return bajada.content, {"modelo": modelo, "modo": modo,
                            "segundos": int(segundos), "resolucion": resolucion,
                            "tardo_s": round(time.time() - t0, 1)}
