"""
Pruebas de los estudios de un estilo (pasos/estudios.py), sin red ni CLI.

  1. COMPETENCIA: lleva los canales pedidos, puede buscar en la web, y guarda
     lo que devuelve.
  2. MIS VIDEOS: sin videos con guion es un ValueError; con ellos, el guion
     entra recortado y se guarda la revision.
  3. CHAT: la conversacion se guarda en orden; las ACCIONES se separan del
     texto y solo pasan las validas.
"""
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_estudios_")
os.environ["ESTUDIO_ESTUDIOS"] = os.path.join(TEMPORAL, "estudios")
os.environ["ESTUDIO_IDEAS"] = os.path.join(TEMPORAL, "ideas")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import estudios  # noqa: E402
import presets_canal  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


PRESET = {"id": "pr1", "nombre": "Canal", "datos": {"guion": {"idioma_salida": "es"},
                                                    "origen": {"tono_prompt": "cercano"}}}
originales = (presets_canal.leer, cli_claude.ejecutar)
presets_canal.leer = lambda pid: PRESET if pid == "pr1" else None
llamadas = []
respuestas = []


def claude(instruccion, **kw):
    llamadas.append((instruccion, kw))
    return respuestas.pop(0), {}


cli_claude.ejecutar = claude


def esperar(tipo):
    for _ in range(100):
        d = estudios.leer("pr1", tipo)
        if d.get("estado") != "pensando":
            return d
        time.sleep(0.05)
    return d


try:
    print("\n== competencia ==")
    respuestas.append(json.dumps({"canales": [{"nombre": "What If", "exitos": ["x"]}],
                                  "conclusion": "hazlo mejor", "fuentes": ["u"]}))
    estudios.competencia("pr1", ["@quepasaria", " ", "Supercurioso"])
    d = esperar("competencia")
    comprobar("listo con sus canales", d.get("estado") == "listo" and d["canales"][0]["nombre"] == "What If", d)
    instruccion, kw = llamadas[-1]
    comprobar("pide los canales y descarta los vacios",
              "@quepasaria; Supercurioso" in instruccion, instruccion[-300:])
    comprobar("puede buscar en la web", "WebSearch" in (kw.get("herramientas_permitidas") or ()))
    try:
        estudios.competencia("pr1", [])
        comprobar("sin canales, ValueError", False)
    except ValueError:
        comprobar("sin canales, ValueError", True)

    print("\n== mis videos ==")
    try:
        estudios.mis_videos("pr1", [{"titulo": "a", "guion": ""}])
        comprobar("sin guion, ValueError", False)
    except ValueError:
        comprobar("sin guion, ValueError", True)
    respuestas.append(json.dumps({"general": "va bien", "videos": [{"titulo": "A", "nota": 7}],
                                  "prioridades": ["ganchos"]}))
    estudios.mis_videos("pr1", [{"titulo": "A", "duracion_s": 120, "guion": "palabra " * 2000}])
    d = esperar("mis_videos")
    comprobar("guarda la revision", d.get("general") == "va bien" and d["videos"][0]["nota"] == 7, d)
    comprobar("el guion va recortado", len(llamadas[-1][0]) < 6000)

    print("\n== chat ==")
    respuestas.append("Te propongo a Lola, la vecina.\n<acciones>[{\"tipo\": \"personajes\", "
                      "\"nombre\": \"Lola\", \"idea\": \"vecina curiosa\"}, {\"tipo\": \"idea\", "
                      "\"titulo\": \"Lola y el wifi\", \"material\": \"m\"}, {\"tipo\": \"raro\"}]"
                      "</acciones>")
    estudios.chat("pr1", "invéntame una secundaria", taller="personajes: Nico")
    d = esperar("chat")
    msgs = d.get("mensajes") or []
    comprobar("mi mensaje y su respuesta, en orden",
              [m["quien"] for m in msgs] == ["yo", "claude"], msgs)
    comprobar("el bloque de acciones no sale en el texto",
              "<acciones>" not in msgs[-1]["texto"] and "Lola" in msgs[-1]["texto"])
    comprobar("solo las acciones validas",
              [a["tipo"] for a in msgs[-1]["acciones"]] == ["personajes", "idea"], msgs[-1])
    comprobar("el taller llega al prompt", "personajes: Nico" in llamadas[-1][0])
    respuestas.append("Claro.")
    estudios.chat("pr1", "y otra cosa")
    d = esperar("chat")
    comprobar("la segunda vuelta lleva el historial", "invéntame una secundaria" in llamadas[-1][0])
    comprobar("y se acumula", len(d["mensajes"]) == 4)
    comprobar("borrar empieza de cero", estudios.borrar_chat("pr1")["mensajes"] == [])
finally:
    presets_canal.leer, cli_claude.ejecutar = originales
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("ESTUDIOS OK: todas las comprobaciones pasan")
