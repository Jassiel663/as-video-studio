"""
Pruebas de TikTok y Facebook (pasos/redes.py), sin red: `requests` se sustituye.

  1. Cada estilo conecta SU cuenta; otro estilo sigue sin conectar; el state
     solo vale una vez y para su red.
  2. TikTok: «borrador» va al inbox (funciona sin revision) y sube el video al
     upload_url; «directo» consulta antes los niveles de privacidad.
  3. Facebook: guarda las paginas, se elige una, y sube a esa pagina;
     programado va con published=false y la hora en segundos UNIX (UTC).
"""
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.parse

TEMPORAL = tempfile.mkdtemp(prefix="prueba_redes_")
os.environ["ESTUDIO_SECRETOS"] = os.path.join(TEMPORAL, "secretos")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import redes  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


class Resp:
    def __init__(self, cuerpo, codigo=200):
        self._c, self.status_code, self.content, self.text = cuerpo, codigo, b"x", json.dumps(cuerpo)

    def json(self):
        return self._c


llamadas = []


class Falso:
    @staticmethod
    def post(url, **kw):
        llamadas.append(("POST", url, kw))
        if url.endswith("/oauth/token/"):
            return Resp({"access_token": "a", "refresh_token": "r", "open_id": "o"})
        if url.endswith("creator_info/query/"):
            return Resp({"data": {"privacy_level_options": ["SELF_ONLY"]}})
        if url.endswith("/init/"):
            return Resp({"data": {"upload_url": "https://subir/tt", "publish_id": "P1"}})
        if "graph-video" in url:
            return Resp({"id": "FBV1"})
        return Resp({})

    @staticmethod
    def get(url, **kw):
        llamadas.append(("GET", url, kw))
        if url.endswith("/user/info/"):
            return Resp({"data": {"user": {"display_name": "Nico TT"}}})
        if url.endswith("/oauth/access_token"):
            return Resp({"access_token": "fb-largo"})
        if url.endswith("/me"):
            return Resp({"name": "Nico FB"})
        if url.endswith("/me/accounts"):
            return Resp({"data": [{"id": "PG1", "name": "Pagina Uno", "access_token": "t1"},
                                  {"id": "PG2", "name": "Pagina Dos", "access_token": "t2"}]})
        return Resp({})

    @staticmethod
    def put(url, **kw):
        llamadas.append(("PUT", url, kw))
        return Resp({}, 201)


original = redes.requests
redes.requests = Falso
redes._app = lambda red: (f"{red}-id", f"{red}-secreto")


class Proyecto:
    raiz = os.path.join(TEMPORAL, "proyecto")


def esperar(red):
    for _ in range(100):
        d = redes.leer_subida(Proyecto, red)
        if d.get("estado") != "subiendo":
            return d
        time.sleep(0.05)
    return d


try:
    print("\n== conectar ==")
    for red in redes.REDES:
        url = redes.url_de_autorizacion(red, "nico", "https://e.test")
        estado = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        comprobar(f"{red}: la vuelta es la del estudio", f"https%3A%2F%2Fe.test%2Fapi%2Fpublicar%2F{red}%2Fvuelta" in url)
        try:
            redes.completar("tiktok" if red == "facebook" else "facebook", "c", estado, "https://e.test")
            comprobar(f"{red}: el state no vale para otra red", False)
        except ValueError:
            comprobar(f"{red}: el state no vale para otra red", True)
        url = redes.url_de_autorizacion(red, "nico", "https://e.test")
        estado = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
        redes.completar(red, "c", estado, "https://e.test")
    comprobar("tiktok conectado al estilo", redes.conexion("tiktok", "nico")["cuenta"] == "Nico TT")
    fb = redes.conexion("facebook", "nico")
    comprobar("facebook con sus paginas y la primera elegida", fb["pagina"] == "PG1" and len(fb["paginas"]) == 2, fb)
    comprobar("los tokens no se ensenan", "token" not in json.dumps(fb))
    comprobar("otro estilo sigue sin conectar", redes.conexion("tiktok", "jass") == {})
    redes.elegir_pagina("nico", "PG2")

    print("\n== subir ==")
    mp4 = os.path.join(TEMPORAL, "v.mp4")
    with open(mp4, "wb") as fh:
        fh.write(b"0" * 5000)
    llamadas.clear()
    redes.subir("tiktok", Proyecto, "nico", mp4, "Titulo", "texto #x", modo="borrador")
    d = esperar("tiktok")
    comprobar("tiktok borrador: va al inbox", d.get("estado") == "listo"
              and any(u.endswith("/inbox/video/init/") for m, u, _ in llamadas), d)
    comprobar("y sube el video al upload_url", any(m == "PUT" and u == "https://subir/tt" for m, u, _ in llamadas))
    llamadas.clear()
    redes.subir("tiktok", Proyecto, "nico", mp4, "Titulo", "texto", modo="directo")
    d = esperar("tiktok")
    comprobar("tiktok directo: consulta la privacidad y avisa si es privado",
              any(u.endswith("creator_info/query/") for _, u, _ in llamadas) and "privado" in d.get("aviso", ""), d)
    llamadas.clear()
    redes.subir("facebook", Proyecto, "nico", mp4, "Titulo", "texto", publicar_en="2026-10-10T18:00:00.000Z")
    d = esperar("facebook")
    post = next(k for m, u, k in llamadas if "graph-video" in u)
    comprobar("facebook: a la pagina elegida", "PG2" in next(u for m, u, _ in llamadas if "graph-video" in u))
    comprobar("programado en UTC", post["data"]["published"] == "false"
              and post["data"]["scheduled_publish_time"] == "1791655200", post["data"])
    comprobar("y queda listo", d.get("estado") == "listo" and d.get("video_id") == "FBV1", d)
finally:
    redes.requests = original
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("REDES OK: todas las comprobaciones pasan")
