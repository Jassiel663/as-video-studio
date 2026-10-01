"""
Pruebas de Ideas y nicho (pasos/ideas.py), sin salir a la red ni al CLI.

  1. EL ESTUDIO CORRE EN UN HILO y deja su estado en un fichero: pensando,
     luego listo con el nicho, las ideas y las mejoras.
  2. SOLO PUEDE BUSCAR EN LA WEB: el resto de herramientas siguen vetadas.
  3. UN FALLO SE DICE Y NO BORRA LO ANTERIOR: lo ultimo bueno sigue ahi.
  4. UN ESTILO QUE NO EXISTE es un ValueError (la API lo da como 404).
"""
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_ideas_")
os.environ["ESTUDIO_IDEAS"] = os.path.join(TEMPORAL, "ideas")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import ideas  # noqa: E402
import presets_canal  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def esperar(estilo):
    for _ in range(100):
        if ideas.leer(estilo).get("estado") != "pensando":
            break
        time.sleep(0.05)
    return ideas.leer(estilo)


PRESET = {"id": "pr1", "nombre": "Que pasa si", "datos": {
    "guion": {"idioma_salida": "es", "instrucciones": "como un amigo"},
    "origen": {"tono_prompt": "cercano y con humor", "estilo_prompt": "monigotes"}}}
original_leer, original_ejecutar = presets_canal.leer, cli_claude.ejecutar
presets_canal.leer = lambda pid: PRESET if pid == "pr1" else None
llamadas = []


def claude_bueno(instruccion, **kw):
    llamadas.append((instruccion, kw))
    time.sleep(0.1)
    return ("texto antes " + json.dumps({
        "nicho": {"resumen": "curiosidades", "funciona": ["x"], "fuentes": ["u"]},
        "ideas": [{"titulo": "Idea A", "tipo": "video", "material": "m"},
                  {"titulo": "", "tipo": "video"}, "basura"],
        "mejoras": ["titulos cortos", ""]}), {})


try:
    print("\n== estudiar ==")
    cli_claude.ejecutar = claude_bueno
    primero = ideas.estudiar("pr1", hechos=["Video viejo"], enfoque="dinero")
    comprobar("devuelve enseguida, pensando", primero.get("estado") == "pensando", primero)
    d = esperar("pr1")
    comprobar("y acaba listo", d.get("estado") == "listo", d)
    comprobar("solo las ideas con titulo", [i["titulo"] for i in d["ideas"]] == ["Idea A"], d["ideas"])
    comprobar("las mejoras vacias fuera", d["mejoras"] == ["titulos cortos"], d["mejoras"])
    instruccion, kw = llamadas[0]
    comprobar("le cuenta el canal, lo hecho y el enfoque",
              "cercano y con humor" in instruccion and "Video viejo" in instruccion
              and "dinero" in instruccion)
    comprobar("puede buscar en la web",
              set(kw.get("herramientas_permitidas") or ()) == {"WebSearch", "WebFetch"})
    comprobar("y nada mas: Bash, Read, Write siguen vetadas",
              {"Bash", "Read", "Write"} <= set(kw.get("herramientas_vetadas") or ())
              and "WebSearch" not in (kw.get("herramientas_vetadas") or ()))

    print("\n== un fallo ==")

    def claude_roto(instruccion, **kw):
        raise RuntimeError("sin sesion")
    cli_claude.ejecutar = claude_roto
    ideas.estudiar("pr1")
    d = esperar("pr1")
    comprobar("se dice", d.get("estado") == "error" and "sin sesion" in d.get("error", ""), d)
    comprobar("y lo anterior sigue", [i["titulo"] for i in d.get("ideas") or []] == ["Idea A"])

    print("\n== un estilo que no existe ==")
    try:
        ideas.estudiar("no-existe")
        comprobar("ValueError", False)
    except ValueError:
        comprobar("ValueError", True)
finally:
    presets_canal.leer, cli_claude.ejecutar = original_leer, original_ejecutar
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("IDEAS OK: todas las comprobaciones pasan")
