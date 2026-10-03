"""
TIKTOK Y FACEBOOK: cada estilo conecta SUS cuentas y el estudio sube solo.

El mismo esquema que pasos/youtube.py: una app por red para todo el sitio (la
crea la persona una vez y pega su id y su secreto en Configuracion › Claves),
y con ella CADA ESTILO conecta su cuenta (OAuth con la cuenta de ese canal).
Los permisos se guardan en secretos/<red>/<estilo>.json; cada persona conecta
la suya y nadie publica en la cuenta de otro.

TIKTOK (Content Posting API, developers.tiktok.com)
  · borrador  -> /v2/post/publish/inbox/video/init/: el video llega a la app de
                 TikTok de esa cuenta y se publica desde el movil. Funciona SIN
                 que TikTok revise la app.
  · directo   -> /v2/post/publish/video/init/: publica ya. Sin revision, TikTok
                 solo deja SELF_ONLY (privado).
  El video se sube por trozos al upload_url que devuelve el init.

FACEBOOK (Graph API, developers.facebook.com)
  Se conecta la cuenta, se listan sus PAGINAS y se publica en la elegida
  (/{pagina}/videos), ya o programado. El token de pagina sale de un token de
  usuario de larga duracion y no caduca. En modo desarrollo de Meta solo
  funciona para quien tenga un rol en la app (anadir a los amigos como
  «evaluadores»).
"""
import calendar
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

REDES = ("tiktok", "facebook")
GRAPH = "https://graph.facebook.com/v19.0"
TIKTOK = "https://open.tiktokapis.com/v2"
TROZO_TIKTOK = 10 * 1024 * 1024

_ESTADOS = {}
_CANDADO = threading.Lock()
_SUBIENDO = set()


def _app(red):
    datos = claves.leer()
    return (datos[f"{red}_id"]["clave"] or "", datos[f"{red}_secreto"]["clave"] or "")


def app_lista(red):
    cid, secreto = _app(red)
    return bool(cid and secreto)


def _ruta(red, estilo_id):
    return os.path.join(claves.CARPETA_SECRETOS, red,
                        f"{re.sub(r'[^A-Za-z0-9_-]', '_', str(estilo_id))[:80]}.json")


def _leer(red, estilo_id):
    return medios.leer_json(_ruta(red, estilo_id), {}) or {}


def _guardar_conexion(red, estilo_id, datos):
    ruta = _ruta(red, estilo_id)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    medios.escribir_json(ruta, datos)
    try:
        os.chmod(ruta, 0o600)
    except OSError:
        pass


def conexion(red, estilo_id):
    """Lo que se puede ensenar de la cuenta conectada (sin tokens). -> {}"""
    d = _leer(red, estilo_id)
    if red == "tiktok" and d.get("refresh_token"):
        return {"cuenta": d.get("cuenta", ""), "conectado": d.get("conectado")}
    if red == "facebook" and d.get("paginas"):
        return {"cuenta": d.get("cuenta", ""), "conectado": d.get("conectado"),
                "pagina": d.get("pagina", ""),
                "paginas": [{"id": p["id"], "nombre": p.get("nombre", "")} for p in d["paginas"]]}
    return {}


def desconectar(red, estilo_id):
    if os.path.exists(_ruta(red, estilo_id)):
        os.remove(_ruta(red, estilo_id))


def elegir_pagina(estilo_id, pagina_id):
    d = _leer("facebook", estilo_id)
    if not any(p["id"] == pagina_id for p in d.get("paginas") or []):
        raise ValueError("esa pagina no es de la cuenta conectada")
    d["pagina"] = pagina_id
    _guardar_conexion("facebook", estilo_id, d)
    return conexion("facebook", estilo_id)


def vuelta(base, red):
    return base.rstrip("/") + f"/api/publicar/{red}/vuelta"


# ----------------------------------------------------------------- conectar

def url_de_autorizacion(red, estilo_id, base):
    cid, _ = _app(red)
    if not cid:
        raise ValueError(f"falta la app de {red}: pega su id y su secreto en Configuracion › Claves › Publicar")
    estado = secrets.token_urlsafe(24)
    with _CANDADO:
        ahora = time.time()
        for k in [k for k, (_, _, t) in _ESTADOS.items() if ahora - t > 1800]:
            _ESTADOS.pop(k, None)
        _ESTADOS[estado] = (red, estilo_id, ahora)
    if red == "tiktok":
        return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode({
            "client_key": cid, "scope": "user.info.basic,video.upload,video.publish",
            "response_type": "code", "redirect_uri": vuelta(base, red), "state": estado})
    return "https://www.facebook.com/v19.0/dialog/oauth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": vuelta(base, red), "state": estado,
        "scope": "pages_show_list,pages_read_engagement,pages_manage_posts"})


def completar(red, codigo, estado, base):
    with _CANDADO:
        fila = _ESTADOS.pop(estado, None)
    if not fila or fila[0] != red:
        raise ValueError("la conexion ha caducado o no se pidio desde el estudio: vuelve a pulsar Conectar")
    estilo_id = fila[1]
    cid, secreto = _app(red)
    ahora = time.strftime("%Y-%m-%dT%H:%M:%S")
    if red == "tiktok":
        r = requests.post(f"{TIKTOK}/oauth/token/", data={
            "client_key": cid, "client_secret": secreto, "code": codigo,
            "grant_type": "authorization_code", "redirect_uri": vuelta(base, red)}, timeout=30)
        d = r.json() if r.content else {}
        if not d.get("refresh_token"):
            raise ValueError(f"TikTok no ha dado el permiso: {d.get('error_description') or d.get('error') or r.status_code}")
        info = requests.get(f"{TIKTOK}/user/info/", params={"fields": "open_id,display_name"},
                            headers={"Authorization": f"Bearer {d['access_token']}"}, timeout=30).json()
        nombre = ((info.get("data") or {}).get("user") or {}).get("display_name", "")
        _guardar_conexion(red, estilo_id, {"refresh_token": d["refresh_token"], "open_id": d.get("open_id"),
                                           "cuenta": nombre, "conectado": ahora})
        return {"estilo": estilo_id, "cuenta": nombre}
    # facebook: codigo -> token corto -> token largo -> paginas
    r = requests.get(f"{GRAPH}/oauth/access_token", params={
        "client_id": cid, "client_secret": secreto, "code": codigo,
        "redirect_uri": vuelta(base, red)}, timeout=30)
    corto = (r.json() if r.content else {}).get("access_token")
    if not corto:
        raise ValueError(f"Facebook no ha dado el permiso: {r.text[:200]}")
    largo = requests.get(f"{GRAPH}/oauth/access_token", params={
        "grant_type": "fb_exchange_token", "client_id": cid, "client_secret": secreto,
        "fb_exchange_token": corto}, timeout=30).json().get("access_token") or corto
    yo = requests.get(f"{GRAPH}/me", params={"access_token": largo, "fields": "name"}, timeout=30).json()
    cuentas = requests.get(f"{GRAPH}/me/accounts", params={"access_token": largo, "fields": "id,name,access_token"},
                           timeout=30).json()
    paginas = [{"id": p["id"], "nombre": p.get("name", ""), "token": p["access_token"]}
               for p in cuentas.get("data") or [] if p.get("access_token")]
    if not paginas:
        raise ValueError("esa cuenta no administra ninguna pagina de Facebook (o no se dio permiso a ninguna)")
    _guardar_conexion(red, estilo_id, {"cuenta": yo.get("name", ""), "paginas": paginas,
                                       "pagina": paginas[0]["id"], "conectado": ahora})
    return {"estilo": estilo_id, "cuenta": yo.get("name", ""), "paginas": len(paginas)}


# ----------------------------------------------------------------- subir

def ruta_estado(proyecto, red):
    return os.path.join(proyecto.raiz, "publicar", f"{red}.json")


def leer_subida(proyecto, red):
    d = medios.leer_json(ruta_estado(proyecto, red), {}) or {}
    if d.get("estado") == "subiendo" and (proyecto.raiz, red) not in _SUBIENDO:
        d["estado"] = "error"
        d["error"] = "se corto (el estudio se reinicio); vuelve a subirlo"
    return d


def _guardar(proyecto, red, datos):
    os.makedirs(os.path.dirname(ruta_estado(proyecto, red)), exist_ok=True)
    medios.escribir_json(ruta_estado(proyecto, red), datos)


def _token_tiktok(estilo_id):
    d = _leer("tiktok", estilo_id)
    cid, secreto = _app("tiktok")
    r = requests.post(f"{TIKTOK}/oauth/token/", data={
        "client_key": cid, "client_secret": secreto, "grant_type": "refresh_token",
        "refresh_token": d.get("refresh_token", "")}, timeout=30)
    nuevo = r.json() if r.content else {}
    if not nuevo.get("access_token"):
        raise ValueError("TikTok no renueva el permiso: vuelve a conectar la cuenta")
    if nuevo.get("refresh_token"):
        d["refresh_token"] = nuevo["refresh_token"]
        _guardar_conexion("tiktok", estilo_id, d)
    return nuevo["access_token"]


def _subir_tiktok(estilo_id, mp4, texto, modo, progreso):
    acceso = _token_tiktok(estilo_id)
    cab = {"Authorization": f"Bearer {acceso}", "Content-Type": "application/json; charset=UTF-8"}
    tam = os.path.getsize(mp4)
    trozo = tam if tam <= 64 * 1024 * 1024 else TROZO_TIKTOK
    total = max(1, tam // trozo)
    fuente = {"source": "FILE_UPLOAD", "video_size": tam, "chunk_size": trozo, "total_chunk_count": total}
    if modo == "directo":
        opciones = requests.post(f"{TIKTOK}/post/publish/creator_info/query/", headers=cab, timeout=30).json()
        niveles = ((opciones.get("data") or {}).get("privacy_level_options")) or ["SELF_ONLY"]
        privacidad = "PUBLIC_TO_EVERYONE" if "PUBLIC_TO_EVERYONE" in niveles else niveles[0]
        cuerpo = {"post_info": {"title": texto[:2200], "privacy_level": privacidad},
                  "source_info": fuente}
        url = f"{TIKTOK}/post/publish/video/init/"
    else:
        cuerpo, url, privacidad = {"source_info": fuente}, f"{TIKTOK}/post/publish/inbox/video/init/", ""
    inicio = requests.post(url, headers=cab, data=json.dumps(cuerpo), timeout=60).json()
    datos = inicio.get("data") or {}
    if not datos.get("upload_url"):
        raise RuntimeError(f"TikTok no acepta la subida: {(inicio.get('error') or {}).get('message') or inicio}")
    with open(mp4, "rb") as fh:
        for n in range(total):
            desde = n * trozo
            hasta = tam - 1 if n == total - 1 else desde + trozo - 1
            fh.seek(desde)
            pedazo = fh.read(hasta - desde + 1)
            r = requests.put(datos["upload_url"], data=pedazo, timeout=600, headers={
                "Content-Type": "video/mp4", "Content-Length": str(len(pedazo)),
                "Content-Range": f"bytes {desde}-{hasta}/{tam}"})
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"la subida a TikTok se corto ({r.status_code}): {r.text[:200]}")
            progreso((hasta + 1) / tam)
    return {"publish_id": datos.get("publish_id"), "modo": modo, "privacidad": privacidad,
            "aviso": ("Abre la app de TikTok de esa cuenta: el video te espera en las "
                      "notificaciones / borradores para publicarlo." if modo != "directo" else
                      ("" if privacidad == "PUBLIC_TO_EVERYONE" else
                       "TikTok solo ha dejado publicarlo en privado: la app aun no esta revisada."))}


def _subir_facebook(estilo_id, mp4, titulo, texto, publicar_en, progreso):
    d = _leer("facebook", estilo_id)
    pagina = next((p for p in d.get("paginas") or [] if p["id"] == d.get("pagina")), None)
    if not pagina:
        raise ValueError("elige la pagina de Facebook en Publicar")
    campos = {"access_token": pagina["token"], "title": titulo[:255], "description": texto[:5000]}
    if publicar_en:
        campos.update({"published": "false",
                       # la fecha llega en UTC (toISOString): a segundos UNIX
                       "scheduled_publish_time": str(calendar.timegm(
                           time.strptime(publicar_en[:19], "%Y-%m-%dT%H:%M:%S")))})
    progreso(0.1)
    with open(mp4, "rb") as fh:
        r = requests.post(f"https://graph-video.facebook.com/v19.0/{pagina['id']}/videos",
                          data=campos, files={"source": (os.path.basename(mp4), fh, "video/mp4")},
                          timeout=3600)
    respuesta = r.json() if r.content else {}
    if not respuesta.get("id"):
        raise RuntimeError(f"Facebook no acepta el video: {(respuesta.get('error') or {}).get('message') or r.text[:200]}")
    progreso(1.0)
    return {"video_id": respuesta["id"], "pagina": pagina.get("nombre", ""),
            "url": f"https://www.facebook.com/{pagina['id']}/videos/{respuesta['id']}",
            "publicar_en": publicar_en or ""}


def subir(red, proyecto, estilo_id, mp4, titulo, texto, modo="borrador", publicar_en=""):
    """Sube en un hilo a la cuenta de `red` de ese estilo. -> estado"""
    if red not in REDES:
        raise ValueError(f"red desconocida: {red}")
    if not mp4 or not os.path.exists(mp4):
        raise ValueError("este video todavia no esta montado")
    if not conexion(red, estilo_id):
        raise ValueError(f"este estilo no tiene {red} conectado (Publicar › Conectar)")
    clave = (proyecto.raiz, red)
    with _CANDADO:
        if clave in _SUBIENDO:
            return leer_subida(proyecto, red)
        _SUBIENDO.add(clave)
    estado = {"estado": "subiendo", "progreso": 0.0, "desde": time.time(), "error": "", "modo": modo}
    _guardar(proyecto, red, estado)

    def progreso(f):
        _guardar(proyecto, red, dict(estado, progreso=round(float(f), 3)))

    def correr():
        try:
            if red == "tiktok":
                fin = _subir_tiktok(estilo_id, mp4, texto or titulo, modo, progreso)
            else:
                fin = _subir_facebook(estilo_id, mp4, titulo, texto, publicar_en, progreso)
            _guardar(proyecto, red, dict(fin, estado="listo", fecha=time.strftime("%Y-%m-%dT%H:%M:%S")))
        except Exception as fallo:                          # noqa: BLE001
            _guardar(proyecto, red, dict(estado, estado="error",
                                         error=f"{type(fallo).__name__}: {str(fallo)[:400]}"))
        finally:
            with _CANDADO:
                _SUBIENDO.discard(clave)

    threading.Thread(target=correr, daemon=True, name=f"subir-{red}").start()
    return leer_subida(proyecto, red)
