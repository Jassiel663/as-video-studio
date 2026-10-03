"""
Pruebas del piloto automatico (pasos/piloto.py) y de los avisos (pasos/avisos.py).
Sin red: la API del estudio y Telegram son de mentira.

  1. AVISOS: se apuntan, cuentan los sin leer, se marcan leidos; Telegram solo
     a quien le toca (filtro de estilos) y «Vincular» apunta a los del /start.
  2. PILOTO, camino entero de un video: idea -> crear -> guion -> dinero ->
     (pide permiso) -> aprobar -> voz -> render -> publicar -> seo -> subir.
  3. EL DINERO: si el coste no cabe en lo que queda de la semana, NO lanza
     nada que gaste y se espera; en modo «solo» sigue sin preguntar.
  4. Un fallo para el piloto, lo apunta y avisa; «ahora» arranca uno aunque
     el piloto este apagado.
"""
import os
import shutil
import sys
import tempfile

TEMPORAL = tempfile.mkdtemp(prefix="prueba_piloto_")
os.environ["ESTUDIO_AVISOS"] = os.path.join(TEMPORAL, "avisos")
os.environ["ESTUDIO_PILOTO"] = os.path.join(TEMPORAL, "piloto")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import avisos  # noqa: E402
import piloto  # noqa: E402
import presets_canal  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


enviados = []


def tg_falso(metodo, **params):
    if metodo == "getUpdates":
        return {"result": [{"message": {"text": "/start", "chat": {"id": 11, "first_name": "Ana"}}},
                           {"message": {"text": "hola", "chat": {"id": 12, "first_name": "Otro"}}},
                           {"message": {"text": "/start", "chat": {"id": 13, "first_name": "Luis"}}}]}
    if metodo == "getMe":
        return {"result": {"username": "mind_bot"}}
    enviados.append((metodo, params))
    return {"ok": True}


# --------------------------------------------------------- la API de mentira
llamadas = []
ESTADO = {"trabajos": {}, "seo": "pensando", "coste_voz": 0.5, "coste_render": 2.0, "falla": None}


def api_falsa(metodo, ruta, datos=None, tiempo=120):
    llamadas.append((metodo, ruta, datos))
    if ESTADO["falla"] and ESTADO["falla"] in ruta:
        raise RuntimeError("se ha roto")
    if ruta.endswith("/ideas") and metodo == "GET":
        return {"estado": "listo", "ideas": [
            {"titulo": "El leon blanco", "gancho": "nadie lo vio", "tipo": "video", "material": "m"},
            {"titulo": "Short del leon", "tipo": "short"}]}
    if ruta.endswith("/video"):
        return {"proyecto": {"id": "p1"}}
    if "/generar?tanda=" in ruta:
        tanda = ruta.split("tanda=")[1]
        return {"coste": {"usd_por_generar": ESTADO["coste_voz"] if tanda == "voz" else ESTADO["coste_render"]}}
    if ruta.endswith("/generar"):
        tid = f"t-{datos['tanda']}"
        ESTADO["trabajos"][tid] = "ejecutando"
        return {"trabajo_id": tid}
    if ruta.startswith("/api/trabajos/"):
        return {"estado": ESTADO["trabajos"].get(ruta.rsplit("/", 1)[1])}
    if ruta.endswith("/publicar/seo"):
        return {}
    if ruta.endswith("/publicar") and metodo == "GET":
        return {"seo": {"estado": ESTADO["seo"]}, "youtube": {"conexion": {"canal": "Mi canal"}},
                "tiktok": {"conexion": {}}, "facebook": {"conexion": {}}}
    if "/publicar/" in ruta:
        return {"ok": True}
    raise AssertionError(f"ruta inesperada {metodo} {ruta}")


def pasos(n=1):
    for _ in range(n):
        piloto.tick()
    return piloto.leer("leon")


original_leer = presets_canal.leer
original_tg, original_token = avisos._tg, avisos._token
try:
    presets_canal.leer = lambda pid: {"id": pid, "nombre": "Leones", "tipo": "canal"}
    piloto._api = api_falsa

    print("\n== el token del bot se guarda ==")
    import claves  # noqa: E402
    claves.FICHERO = os.path.join(TEMPORAL, "claves.json")
    claves.FICHERO_ENV = os.path.join(TEMPORAL, ".env")
    claves.guardar({"telegram": {"clave": "123:abc"}})
    comprobar("el token queda en el almacen", claves.leer()["telegram"]["clave"] == "123:abc")
    comprobar("y en el .env", "TELEGRAM_BOT_TOKEN=" in open(claves.FICHERO_ENV, encoding="utf-8").read())
    comprobar("los avisos lo leen", original_token() == "123:abc")
    comprobar("y la pantalla no lo ve", "123:abc" not in str(claves.resumen()))

    print("\n== avisos ==")
    avisos._token = lambda: ""
    avisos.avisar("listo", "uno", estilo="leon")
    avisos.avisar("error", "dos")
    lista = avisos.listar()
    comprobar("se apuntan y el mas nuevo va primero", [a["titulo"] for a in lista["avisos"]] == ["dos", "uno"])
    comprobar("cuentan como sin leer", lista["sin_leer"] == 2)
    avisos.marcar_leidos()
    comprobar("marcar leidos los deja a cero", avisos.listar()["sin_leer"] == 0)

    avisos._token = lambda: "123:abc"
    avisos._tg = tg_falso
    nuevos = avisos.vincular()
    comprobar("vincular apunta solo a los del /start", sorted(nuevos) == ["Ana", "Luis"], nuevos)
    comprobar("y les confirma por Telegram", len([e for e in enviados if e[0] == "sendMessage"]) == 2)
    comprobar("vincular dos veces no duplica", avisos.vincular() == [] and len(avisos.suscriptores()) == 2)
    avisos.ajustar_suscriptor(13, ["otro_estilo"])
    enviados.clear()
    avisos.avisar("listo", "del leon", estilo="leon")
    destinos = [p["chat_id"] for m, p in enviados if m == "sendMessage"]
    comprobar("el filtro de estilos deja fuera a quien no es suyo", destinos == [11], destinos)
    avisos.ajustar_suscriptor(13, quitar=True)
    comprobar("quitar un suscriptor", [s["chat"] for s in avisos.suscriptores()] == [11])
    comprobar("estado de Telegram con el bot", avisos.estado_telegram()["bot"] == "mind_bot")
    avisos._token = lambda: ""

    print("\n== piloto: un video entero pidiendo permiso ==")
    piloto.configurar("leon", {"activo": True, "videos_semana": 1, "shorts_semana": 0,
                               "presupuesto_semana_usd": 10, "aprobacion": "pedir",
                               "publicar": {"youtube": True, "tiktok": True}})
    d = pasos(3)            # nada -> idea -> crear -> guion
    comprobar("crea el video con la idea del nicho",
              d["en_curso"]["fase"] == "guion" and d["en_curso"]["idea"] == "El leon blanco", d["en_curso"])
    comprobar("la idea queda usada", d["usadas"] == ["El leon blanco"])
    d = pasos()
    comprobar("espera mientras el guion se escribe", d["en_curso"]["fase"] == "guion")
    ESTADO["trabajos"]["t-guion"] = "listo"
    d = pasos(2)
    comprobar("calcula el coste y pide permiso", d["en_curso"]["fase"] == "esperando_ok"
              and d["en_curso"]["coste"] == 2.5, d["en_curso"])
    comprobar("avisa para aprobar", any("¿Hago" in a["titulo"] for a in avisos.listar()["avisos"]))
    pasos(3)
    comprobar("sin el si NO lanza la voz", not any(r.endswith("/generar") and x and x.get("tanda") == "voz"
                                                    for _, r, x in llamadas))
    piloto.aprobar("leon")
    d = pasos()
    comprobar("aprobado: lanza la voz", d["en_curso"]["fase"] == "voz")
    ESTADO["trabajos"]["t-voz"] = "listo"
    d = pasos(2)
    comprobar("y despues el render", d["en_curso"]["fase"] == "render")
    ESTADO["trabajos"]["t-render"] = "listo"
    d = pasos(2)
    comprobar("apunta lo gastado y pide los textos", d["en_curso"]["fase"] == "seo"
              and piloto._gastado_semana(d) == 2.5)
    pasos()
    ESTADO["seo"] = "listo"
    d = pasos(2)
    subidas = [r for m, r, _ in llamadas if m == "POST" and "/publicar/" in r and not r.endswith("/seo")]
    comprobar("sube solo a las redes marcadas Y conectadas", subidas == ["/api/proyectos/p1/publicar/youtube"], subidas)
    comprobar("termina y queda libre", d["en_curso"] is None and len(d["hechos"]) == 1)
    comprobar("avisa de lo publicado (y de la red sin cuenta)",
              any("enviado a youtube" in a["titulo"] and "tiktok" in a["texto"] for a in avisos.listar()["avisos"]))
    d = pasos(2)
    comprobar("con el cupo de la semana hecho no empieza otro", d["en_curso"] is None)

    print("\n== el presupuesto ==")
    llamadas.clear()
    ESTADO.update(trabajos={}, coste_render=9.0)
    d = piloto.leer("leon")
    d["usadas"] = []
    d["hechos"] = [dict(h, ts=0) for h in d["hechos"]]
    piloto._guardar("leon", d)
    piloto.configurar("leon", {"videos_semana": 2, "aprobacion": "solo"})
    pasos(3)
    ESTADO["trabajos"]["t-guion"] = "listo"
    d = pasos(2)
    comprobar("no cabe (9,5 $ y quedan 7,5 $): espera", d["en_curso"]["fase"] == "sin_presupuesto", d["en_curso"])
    pasos(2)
    comprobar("y no gasta nada", not any(r.endswith("/generar") and x and x.get("tanda") in ("voz", "render")
                                          for _, r, x in llamadas))
    ESTADO["coste_render"] = 1.0
    d = piloto.leer("leon")
    d["en_curso"]["semana"] = "1999-W01"     # la semana que viene
    piloto._guardar("leon", d)
    d = pasos(3)
    comprobar("en modo solo y dentro del presupuesto, sigue sin preguntar", d["en_curso"]["fase"] == "voz", d["en_curso"])

    print("\n== fallos y «ahora» ==")
    ESTADO["trabajos"]["t-voz"] = "error"
    d = pasos()
    comprobar("un fallo para el piloto y lo apunta", d["en_curso"] is None and "voz" in (d.get("ultimo_error") or ""))
    comprobar("y avisa", any("se ha parado" in a["titulo"] for a in avisos.listar()["avisos"]))
    piloto.configurar("leon", {"activo": False})
    d = pasos()
    comprobar("apagado no empieza nada", d["en_curso"] is None)
    piloto.ahora("leon")
    d = pasos()
    comprobar("«ahora» arranca uno aunque este apagado", (d["en_curso"] or {}).get("fase") == "crear", d["en_curso"])
    piloto.cancelar("leon")
    comprobar("cancelar lo suelta", piloto.leer("leon")["en_curso"] is None)
    try:
        piloto.aprobar("leon")
        comprobar("aprobar sin nada esperando da error", False)
    except ValueError:
        comprobar("aprobar sin nada esperando da error", True)
finally:
    presets_canal.leer = original_leer
    avisos._tg, avisos._token = original_tg, original_token
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("PILOTO OK: todas las comprobaciones pasan")
