"""
Anima un plano con fal.ai: el RESPALDO de Veo cuando Google se queda sin cuota.

Google limita cuantos clips de Veo se pueden pedir AL DIA por modelo, y en una
cuenta nueva el limite es bajo: el 30-09-2026 un video de 27 planos se quedo
en 13 con saldo de sobra. fal.ai sirve los mismos generadores (y otros) sin ese
tope diario: solo limita cuantos van a la vez. El estudio usa Google mientras
tiene cuota y pasa aqui para lo que falte (ver pasos/animar.py).

Dos modelos, elegidos por la prueba de ese mismo dia sobre planos reales:

    kling    Kling 2.6 Pro. 1080p, mucho movimiento, el mas barato por plano.
             Se toma libertades: en un plano con una cifra en un movil,
             levanto el movil fuera de cuadro. Para planos SIN texto.
    veofast  Veo 3.1 Fast servido por fal. Mas obediente: la cifra siguio en
             pantalla. Para el primer plano y cualquiera con texto.

Imagen a video, como en video_veo: la imagen va dentro de la peticion como
data URI. Sin audio: el estudio pone su propia voz y su musica.

La clave (formato «id:secreto») se lee por CONTRATO: FAL_KEY en el entorno, o
`fal.clave` en el claves.json de la carpeta de secretos, o la linea FAL_KEY del
.env de esa carpeta.
"""
import base64
import json
import os
import time

import requests

COLA = "https://queue.fal.run"

MODELOS = {
    "kling": "fal-ai/kling-video/v2.6/pro/image-to-video",
    "veofast": "fal-ai/veo3.1/fast/image-to-video",
}

ESPERA_ENTRE_CONSULTAS_S = 8.0
PLAZO_S = 1200.0

CARPETA_SECRETOS = os.environ.get("ESTUDIO_SECRETOS") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "secretos")


class SinClave(RuntimeError):
    """No hay clave de fal.ai en ningun sitio donde se busca."""


class SinSaldo(RuntimeError):
    """fal.ai contesta que la cuenta no tiene saldo (402) o que la clave no vale."""


def clave():
    valor = (os.environ.get("FAL_KEY") or "").strip()
    if valor:
        return valor
    try:
        with open(os.path.join(CARPETA_SECRETOS, "claves.json"), "r",
                  encoding="utf-8-sig") as fh:
            valor = str(((json.load(fh) or {}).get("fal") or {}).get("clave") or "")
        if valor.strip():
            return valor.strip()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        with open(os.path.join(CARPETA_SECRETOS, ".env"), "r",
                  encoding="utf-8-sig") as fh:
            for linea in fh:
                nombre, _, valor = linea.strip().partition("=")
                if nombre.strip() == "FAL_KEY" and valor.strip():
                    return valor.strip()
    except OSError:
        pass
    return ""


def duracion_de_clip(modelo, segundos_plano):
    """Segundos que se piden (y se pagan) para cubrir un plano, o None."""
    opciones = (5, 10) if modelo == "kling" else (4, 6, 8)
    for opcion in opciones:
        if segundos_plano <= opcion + 1e-6:
            return opcion
    return None


def _cuerpo(modelo, uri, prompt, segundos, aspecto, negativo):
    if modelo == "kling":
        return {"prompt": prompt, "start_image_url": uri, "duration": str(segundos),
                "aspect_ratio": aspecto, "generate_audio": False,
                "negative_prompt": negativo or "blur, distort, low quality"}
    return {"prompt": prompt, "image_url": uri, "duration": f"{segundos}s",
            "resolution": "720p", "aspect_ratio": aspecto, "generate_audio": False,
            "negative_prompt": negativo or ""}


def _pedir(metodo, url, api_key, **kw):
    ultimo = None
    for intento in range(5):
        try:
            r = requests.request(metodo, url, timeout=120,
                                 headers={"Authorization": f"Key {api_key}"}, **kw)
        except requests.RequestException as fallo:
            ultimo = f"{type(fallo).__name__}: {fallo}"
            time.sleep(min(5 * (intento + 1), 30))
            continue
        if r.status_code in (401, 403):
            raise SinSaldo(f"fal.ai no acepta la clave ({r.status_code}): {r.text[:200]}")
        if r.status_code == 402:
            raise SinSaldo(f"la cuenta de fal.ai no tiene saldo: {r.text[:200]}")
        if r.status_code in (429, 500, 502, 503, 504):
            ultimo = f"HTTP {r.status_code}: {r.text[:300]}"
            time.sleep(min(10 * (intento + 1), 60))
            continue
        return r
    raise RuntimeError(f"fal.ai no contesta tras varios intentos: {ultimo}")


def generar(imagen, prompt, *, modelo="kling", segundos=5, aspecto="16:9",
            negativo="", api_key=None, avisar=None):
    """Anima `imagen` (un PNG). -> (bytes del mp4, meta)"""
    api_key = api_key or clave()
    if not api_key:
        raise SinClave("no hay clave de fal.ai: ponla en Configuracion > Claves")
    ruta = MODELOS.get(modelo)
    if not ruta:
        raise ValueError(f"modelo de fal desconocido: {modelo!r}")
    with open(imagen, "rb") as fh:
        uri = "data:image/png;base64," + base64.b64encode(fh.read()).decode("ascii")
    t0 = time.time()
    r = _pedir("POST", f"{COLA}/{ruta}", api_key,
               json=_cuerpo(modelo, uri, prompt, segundos, aspecto, negativo))
    if r.status_code != 200:
        raise RuntimeError(f"fal.ai rechaza la peticion (HTTP {r.status_code}): {r.text[:400]}")
    envio = r.json()
    estado_url, respuesta_url = envio.get("status_url"), envio.get("response_url")
    if not estado_url or not respuesta_url:
        raise RuntimeError(f"fal.ai no devolvio la cola: {r.text[:300]}")
    while True:
        if time.time() - t0 > PLAZO_S:
            raise RuntimeError(f"fal.ai no termino en {PLAZO_S:.0f} s")
        time.sleep(ESPERA_ENTRE_CONSULTAS_S)
        estado = _pedir("GET", estado_url, api_key).json()
        if avisar:
            avisar(time.time() - t0)
        if estado.get("status") == "COMPLETED":
            break
    res = _pedir("GET", respuesta_url, api_key)
    if res.status_code != 200:
        raise RuntimeError(f"fal.ai fallo al generar (HTTP {res.status_code}): {res.text[:400]}")
    url = ((res.json() or {}).get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"fal.ai termino sin video: {res.text[:300]}")
    bajada = requests.get(url, timeout=300)
    if bajada.status_code != 200 or not bajada.content:
        raise RuntimeError(f"no se pudo bajar el clip de fal.ai (HTTP {bajada.status_code})")
    return bajada.content, {"modelo": ruta, "corto": modelo, "segundos": int(segundos),
                            "tardo_s": round(time.time() - t0, 1)}
