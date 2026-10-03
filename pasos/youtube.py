"""
SUBIR A YOUTUBE SOLO: cada estilo conectado a SU canal, y la subida de un video.

LA APP la crea la persona una vez en Google Cloud (YouTube Data API v3, OAuth
de tipo «Aplicacion web») y pega su id y su secreto en Configuracion › Claves.
Con esa app, CADA ESTILO se conecta a su canal: «Conectar YouTube» abre la
pantalla de Google, se elige la cuenta/canal y Google devuelve un permiso que
se guarda para ese estilo (refresh token, en secretos/youtube/<estilo>.json).
Asi Nico sube al canal de Nico y Mr Jass al suyo.

LA SUBIDA (videos.insert, subida reanudable): el MP4 con titulo, descripcion y
etiquetas del kit SEO (pasos/publicar.py), la privacidad que se pida y, si se
da fecha, programado (YouTube lo exige en privado con publishAt). Despues la
miniatura (thumbnails.set), si el canal lo permite.

OJO: mientras Google no revise la app (la revision se pide desde la consola),
YouTube deja los videos subidos por la API en PRIVADO. No es un fallo de aqui.

No cuesta dinero: la API de YouTube es gratis (con una cuota diaria de unas 6
subidas por proyecto de Google).
"""
import json
import os
import re
import secrets
import threading
import time
import urllib.parse

import requests

try:
    from . import claves, medios
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import claves
    import medios

AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/youtube/v3"
SUBIDA = "https://www.googleapis.com/upload/youtube/v3"
ALCANCES = ("https://www.googleapis.com/auth/youtube.upload "
            "https://www.googleapis.com/auth/youtube.readonly")
RUTA_VUELTA = "/api/publicar/youtube/vuelta"
PRIVACIDADES = ("private", "unlisted", "public")
TROZO = 8 * 1024 * 1024

_ESTADOS = {}            # state de OAuth -> (estilo, cuando)
_CANDADO = threading.Lock()
_SUBIENDO = set()


def carpeta():
    return os.path.join(claves.CARPETA_SECRETOS, "youtube")


def _ruta(estilo_id):
    return os.path.join(carpeta(), f"{re.sub(r'[^A-Za-z0-9_-]', '_', str(estilo_id))[:80]}.json")


def app_lista():
    cid, secreto = claves.youtube()
    return bool(cid and secreto)


def conexion(estilo_id):
    """El canal conectado a un estilo, sin el permiso. -> {} si no hay."""
    datos = medios.leer_json(_ruta(estilo_id), {}) or {}
    if not datos.get("refresh_token"):
        return {}
    return {k: datos.get(k) for k in ("canal_id", "canal", "conectado")}


def url_de_autorizacion(estilo_id, base):
    """A donde se manda a la persona para conectar el canal de este estilo."""
    cid, _ = claves.youtube()
    if not cid:
        raise ValueError("falta la app de Google: pega el ID y el secreto de cliente en "
                         "Configuracion › Claves › YouTube")
    estado = secrets.token_urlsafe(24)
    with _CANDADO:
        ahora = time.time()
        for k in [k for k, (_, t) in _ESTADOS.items() if ahora - t > 1800]:
            _ESTADOS.pop(k, None)
        _ESTADOS[estado] = (estilo_id, ahora)
    return AUTORIZAR + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": base.rstrip("/") + RUTA_VUELTA,
        "response_type": "code", "scope": ALCANCES, "access_type": "offline",
        "prompt": "consent select_account", "include_granted_scopes": "true",
        "state": estado})


def completar(codigo, estado, base):
    """La vuelta de Google: cambia el codigo por el permiso y lo guarda. -> ficha"""
    with _CANDADO:
        fila = _ESTADOS.pop(estado, None)
    if not fila:
        raise ValueError("la conexion ha caducado o no se pidio desde el estudio: vuelve a pulsar Conectar")
    estilo_id = fila[0]
    cid, secreto = claves.youtube()
    respuesta = requests.post(TOKEN, data={
        "code": codigo, "client_id": cid, "client_secret": secreto,
        "redirect_uri": base.rstrip("/") + RUTA_VUELTA, "grant_type": "authorization_code"},
        timeout=30)
    datos = respuesta.json() if respuesta.content else {}
    if respuesta.status_code != 200 or not datos.get("refresh_token"):
        raise ValueError(f"Google no ha dado el permiso: {datos.get('error_description') or datos.get('error') or respuesta.status_code}")
    canal = requests.get(f"{API}/channels", params={"part": "snippet", "mine": "true"},
                         headers={"Authorization": f"Bearer {datos['access_token']}"}, timeout=30).json()
    item = (canal.get("items") or [{}])[0]
    ficha = {"estilo": estilo_id, "refresh_token": datos["refresh_token"],
             "canal_id": item.get("id", ""), "canal": (item.get("snippet") or {}).get("title", ""),
             "conectado": time.strftime("%Y-%m-%dT%H:%M:%S")}
    os.makedirs(carpeta(), exist_ok=True)
    medios.escribir_json(_ruta(estilo_id), ficha)
    try:
        os.chmod(_ruta(estilo_id), 0o600)
    except OSError:
        pass
    return {k: ficha[k] for k in ("estilo", "canal_id", "canal")}


def desconectar(estilo_id):
    if os.path.exists(_ruta(estilo_id)):
        os.remove(_ruta(estilo_id))


def _token(estilo_id):
    datos = medios.leer_json(_ruta(estilo_id), {}) or {}
    if not datos.get("refresh_token"):
        raise ValueError("este estilo no tiene canal de YouTube conectado")
    cid, secreto = claves.youtube()
    respuesta = requests.post(TOKEN, data={
        "client_id": cid, "client_secret": secreto, "refresh_token": datos["refresh_token"],
        "grant_type": "refresh_token"}, timeout=30)
    cuerpo = respuesta.json() if respuesta.content else {}
    if respuesta.status_code != 200:
        raise ValueError(f"Google no renueva el permiso ({cuerpo.get('error')}): vuelve a conectar el canal")
    return cuerpo["access_token"]


def ruta_estado(proyecto):
    return os.path.join(proyecto.raiz, "publicar", "youtube.json")


def leer_subida(proyecto):
    datos = medios.leer_json(ruta_estado(proyecto), {}) or {}
    if datos.get("estado") == "subiendo" and proyecto.raiz not in _SUBIENDO:
        datos["estado"] = "error"
        datos["error"] = "se corto (el estudio se reinicio); vuelve a subirlo"
    return datos


def _guardar(proyecto, datos):
    os.makedirs(os.path.dirname(ruta_estado(proyecto)), exist_ok=True)
    medios.escribir_json(ruta_estado(proyecto), datos)


def subir(proyecto, estilo_id, mp4, titulo, descripcion="", etiquetas=(), privacidad="private",
          publicar_en="", miniatura="", idioma="es"):
    """Sube en un hilo. -> estado (subiendo)"""
    if privacidad not in PRIVACIDADES:
        raise ValueError(f"privacidad: {', '.join(PRIVACIDADES)}")
    if not mp4 or not os.path.exists(mp4):
        raise ValueError("este video todavia no esta montado")
    if not str(titulo or "").strip():
        raise ValueError("falta el titulo: escribe primero los textos SEO")
    if not conexion(estilo_id):
        raise ValueError("este estilo no tiene canal de YouTube conectado (Publicar › Conectar YouTube)")
    with _CANDADO:
        if proyecto.raiz in _SUBIENDO:
            return leer_subida(proyecto)
        _SUBIENDO.add(proyecto.raiz)
    estado = {"estado": "subiendo", "desde": time.time(), "progreso": 0.0, "error": "",
              "privacidad": privacidad, "publicar_en": publicar_en or ""}
    _guardar(proyecto, estado)

    def correr():
        try:
            acceso = _token(estilo_id)
            status = {"privacyStatus": privacidad, "selfDeclaredMadeForKids": False}
            if publicar_en:
                # programado: YouTube lo exige en privado y en hora UTC ISO
                status = {"privacyStatus": "private", "publishAt": publicar_en,
                          "selfDeclaredMadeForKids": False}
            cuerpo = {"snippet": {"title": str(titulo)[:100], "description": str(descripcion or "")[:4900],
                                  "tags": [str(t)[:60] for t in etiquetas or []][:30],
                                  "categoryId": "22", "defaultLanguage": idioma,
                                  "defaultAudioLanguage": idioma},
                      "status": status}
            tam = os.path.getsize(mp4)
            inicio = requests.post(f"{SUBIDA}/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                                   headers={"Authorization": f"Bearer {acceso}",
                                            "Content-Type": "application/json; charset=UTF-8",
                                            "X-Upload-Content-Length": str(tam),
                                            "X-Upload-Content-Type": "video/mp4"},
                                   data=json.dumps(cuerpo), timeout=60)
            if inicio.status_code != 200 or not inicio.headers.get("Location"):
                raise RuntimeError(f"YouTube no acepta la subida ({inicio.status_code}): {inicio.text[:300]}")
            destino, enviado, video = inicio.headers["Location"], 0, None
            with open(mp4, "rb") as fh:
                while enviado < tam:
                    trozo = fh.read(TROZO)
                    fin = enviado + len(trozo) - 1
                    r = requests.put(destino, data=trozo, timeout=600, headers={
                        "Authorization": f"Bearer {acceso}", "Content-Length": str(len(trozo)),
                        "Content-Range": f"bytes {enviado}-{fin}/{tam}"})
                    if r.status_code in (200, 201):
                        video = r.json()
                        enviado = tam
                    elif r.status_code == 308:
                        rango = r.headers.get("Range", "")
                        enviado = int(rango.split("-")[-1]) + 1 if rango else enviado + len(trozo)
                        fh.seek(enviado)
                    else:
                        raise RuntimeError(f"la subida se corto ({r.status_code}): {r.text[:300]}")
                    _guardar(proyecto, dict(estado, progreso=round(enviado / tam, 3)))
            vid = (video or {}).get("id")
            if not vid:
                raise RuntimeError("YouTube no ha devuelto el id del video")
            aviso = ""
            if miniatura and os.path.exists(miniatura):
                with open(miniatura, "rb") as fh:
                    m = requests.post(f"{SUBIDA}/thumbnails/set", params={"videoId": vid},
                                      headers={"Authorization": f"Bearer {acceso}", "Content-Type": "image/png"},
                                      data=fh.read(), timeout=120)
                if m.status_code != 200:
                    aviso = ("la miniatura no se ha podido poner (el canal tiene que estar "
                             "verificado por telefono para miniaturas propias)")
            _guardar(proyecto, {"estado": "listo", "video_id": vid,
                                "url": f"https://youtu.be/{vid}", "privacidad": privacidad,
                                "publicar_en": publicar_en or "", "aviso": aviso,
                                "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")})
        except Exception as fallo:                          # noqa: BLE001
            _guardar(proyecto, dict(estado, estado="error",
                                    error=f"{type(fallo).__name__}: {str(fallo)[:400]}"))
        finally:
            with _CANDADO:
                _SUBIENDO.discard(proyecto.raiz)

    threading.Thread(target=correr, daemon=True, name="youtube").start()
    return leer_subida(proyecto)
