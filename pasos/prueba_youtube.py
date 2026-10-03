"""
Pruebas de la subida a YouTube (pasos/youtube.py), sin red: `requests` se
sustituye.

  1. CONECTAR: la URL de Google lleva el id de la app, la vuelta del estudio y
     un `state` que solo vale una vez; la vuelta guarda el permiso PARA ESE
     ESTILO y otro estilo sigue sin canal.
  2. SUBIR: subida reanudable con el titulo y la privacidad; programado va en
     privado con publishAt; al acabar, el enlace del video.
  3. SIN CANAL O SIN TITULO no se sube nada.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse

TEMPORAL = tempfile.mkdtemp(prefix="prueba_yt_")
os.environ["ESTUDIO_SECRETOS"] = os.path.join(TEMPORAL, "secretos")
os.environ["YOUTUBE_CLIENT_ID"] = "id-app.apps.googleusercontent.com"
os.environ["YOUTUBE_CLIENT_SECRET"] = "secreto-app"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claves  # noqa: E402
import youtube  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


class Resp:
    def __init__(self, codigo, cuerpo=None, cabeceras=None):
        self.status_code, self._c, self.headers = codigo, cuerpo or {}, cabeceras or {}
        self.content = b"x"
        self.text = json.dumps(self._c)

    def json(self):
        return self._c


llamadas = []


class Falso:
    @staticmethod
    def post(url, **kw):
        llamadas.append(("POST", url, kw))
        if "oauth2" in url and kw["data"].get("grant_type") == "authorization_code":
            return Resp(200, {"access_token": "a1", "refresh_token": "r1"})
        if "oauth2" in url:
            return Resp(200, {"access_token": "a2"})
        if "uploadType" in str(kw.get("params")) or url.endswith("/videos"):
            return Resp(200, {}, {"Location": "https://subida/1"})
        return Resp(200, {})

    @staticmethod
    def get(url, **kw):
        llamadas.append(("GET", url, kw))
        return Resp(200, {"items": [{"id": "UC123", "snippet": {"title": "Canal de Nico"}}]})

    @staticmethod
    def put(url, **kw):
        llamadas.append(("PUT", url, kw))
        return Resp(200, {"id": "VID1"})


original = youtube.requests
youtube.requests = Falso
claves.youtube = lambda: ("id-app.apps.googleusercontent.com", "secreto-app")


class Proyecto:
    raiz = os.path.join(TEMPORAL, "proyecto")


try:
    print("\n== conectar ==")
    url = youtube.url_de_autorizacion("nico", "https://estudio.test")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    comprobar("lleva la app y la vuelta del estudio",
              q["client_id"] == ["id-app.apps.googleusercontent.com"]
              and q["redirect_uri"] == ["https://estudio.test/api/publicar/youtube/vuelta"])
    comprobar("pide subir y permiso permanente", "youtube.upload" in q["scope"][0] and q["access_type"] == ["offline"])
    ficha = youtube.completar("codigo", q["state"][0], "https://estudio.test")
    comprobar("guarda el canal de ESE estilo", ficha["canal"] == "Canal de Nico"
              and youtube.conexion("nico")["canal_id"] == "UC123", ficha)
    comprobar("y otro estilo sigue sin canal", youtube.conexion("jass") == {})
    try:
        youtube.completar("codigo", q["state"][0], "https://estudio.test")
        comprobar("el state no vale dos veces", False)
    except ValueError:
        comprobar("el state no vale dos veces", True)
    comprobar("el permiso no se ensena", "refresh_token" not in youtube.conexion("nico"))

    print("\n== subir ==")
    mp4 = os.path.join(TEMPORAL, "v.mp4")
    with open(mp4, "wb") as fh:
        fh.write(b"0" * 1000)
    try:
        youtube.subir(Proyecto, "jass", mp4, "Titulo")
        comprobar("sin canal conectado, no sube", False)
    except ValueError:
        comprobar("sin canal conectado, no sube", True)
    try:
        youtube.subir(Proyecto, "nico", mp4, "  ")
        comprobar("sin titulo, no sube", False)
    except ValueError:
        comprobar("sin titulo, no sube", True)
    llamadas.clear()
    youtube.subir(Proyecto, "nico", mp4, "Mi titulo", "desc", ["a"], privacidad="public",
                  publicar_en="2026-10-10T18:00:00Z")
    for _ in range(100):
        d = youtube.leer_subida(Proyecto)
        if d.get("estado") != "subiendo":
            break
        time.sleep(0.05)
    comprobar("acaba con el enlace", d.get("estado") == "listo" and d.get("url") == "https://youtu.be/VID1", d)
    inicio = next(k for m, u, k in llamadas if m == "POST" and u.endswith("/videos"))
    meta = json.loads(inicio["data"])
    comprobar("con el titulo y las etiquetas", meta["snippet"]["title"] == "Mi titulo" and meta["snippet"]["tags"] == ["a"])
    comprobar("programado: privado con publishAt", meta["status"] == {
        "privacyStatus": "private", "publishAt": "2026-10-10T18:00:00Z", "selfDeclaredMadeForKids": False},
        meta["status"])
    comprobar("el video va por la direccion reanudable", any(m == "PUT" and u == "https://subida/1" for m, u, _ in llamadas))
finally:
    youtube.requests = original
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("YOUTUBE OK: todas las comprobaciones pasan")
