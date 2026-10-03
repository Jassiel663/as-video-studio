"""
Pruebas de Mind: el estudio de nicho desde cero (pasos/nicho.py) y la REGLA DEL
DINERO de sus herramientas (pasos/mcp_estudio.py). Sin red ni CLI.

  1. NICHO: lleva el tema, el idioma y las referencias; guarda el canal
     propuesto con un ritmo valido; lista y borra.
  2. EL DINERO NO SE GASTA SIN UN SI: una accion de pago sin confirmo_coste (o
     con menos) NO llama a la API que gasta y devuelve NECESITA CONFIRMACION;
     con la cifra, si. Lo gratis (el guion) no pide nada.
"""
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_mind_")
os.environ["ESTUDIO_NICHOS"] = os.path.join(TEMPORAL, "nichos")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import mcp_estudio  # noqa: E402
import nicho  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


original = cli_claude.ejecutar
pedidos = []


def claude(instruccion, **kw):
    pedidos.append((instruccion, kw))
    return json.dumps({"tema": "finanzas jovenes", "resumen": "si", "puntuacion": 8,
                       "canal": {"nombre": "Dinero Claro", "ritmo": "rapidisimo"},
                       "videos": [{"titulo": "a"}]}), {}


try:
    print("\n== nicho desde cero ==")
    cli_claude.ejecutar = claude
    ficha = nicho.estudiar("finanzas para jovenes", "es", "poco dinero",
                           ["https://youtube.com/@x", "  ", "Canal Y"])
    for _ in range(100):
        d = nicho.leer(ficha["id"])
        if d.get("estado") != "pensando":
            break
        time.sleep(0.05)
    comprobar("acaba listo con su canal", d.get("estado") == "listo"
              and d["canal"]["nombre"] == "Dinero Claro", d)
    comprobar("un ritmo raro se queda en medio", d["canal"]["ritmo"] == "medio")
    instruccion, kw = pedidos[-1]
    comprobar("lleva las referencias sin las vacias",
              "https://youtube.com/@x; Canal Y" in instruccion, instruccion[-400:])
    comprobar("y puede buscar en la web", "WebSearch" in (kw.get("herramientas_permitidas") or ()))
    comprobar("sale en la lista", [n["id"] for n in nicho.listar()] == [ficha["id"]])
    nicho.borrar(ficha["id"])
    comprobar("y se borra", nicho.listar() == [])
    try:
        nicho.estudiar("   ")
        comprobar("sin tema, ValueError", False)
    except ValueError:
        comprobar("sin tema, ValueError", True)

    print("\n== las preguntas antes del guion ==")
    import preguntas

    def claude_preguntas(instruccion, **kw):
        pedidos.append((instruccion, kw))
        return json.dumps({"preguntas": [{"pregunta": "¿Para quien es?", "por_que": "x",
                                          "opciones": ["jovenes", "padres"]}, {"pregunta": ""}]}), {}
    cli_claude.ejecutar = claude_preguntas
    ficha = preguntas.preguntar("El leon vive en manada.", "El leon", "documental")
    for _ in range(100):
        d = preguntas.leer(ficha["id"])
        if d.get("estado") != "pensando":
            break
        time.sleep(0.05)
    comprobar("solo las preguntas con texto, con sus opciones",
              d.get("estado") == "listo" and len(d["preguntas"]) == 1
              and d["preguntas"][0]["opciones"] == ["jovenes", "padres"], d)
    comprobar("lleva el material y el tipo", "manada" in pedidos[-1][0] and "documental" in pedidos[-1][0])
    try:
        preguntas.preguntar("", "")
        comprobar("sin material ni titulo, ValueError", False)
    except ValueError:
        comprobar("sin material ni titulo, ValueError", True)

    print("\n== la regla del dinero ==")
    llamadas = []

    def api(metodo, ruta, datos=None, tiempo=60):
        llamadas.append((metodo, ruta, datos))
        if "/generar?tanda=" in ruta:
            return 200, {"coste": {"usd_por_generar": 1.98, "usd_total": 1.98}}
        if ruta.endswith("/generar"):
            return 202, {"trabajo_id": "t1"}
        if ruta.endswith("/miniaturas"):
            return 200, {"estado": "pensando"}
        return 200, {}
    original_api = mcp_estudio._llamar
    mcp_estudio._llamar = api
    try:
        r = mcp_estudio.generar({"proyecto": "p", "tanda": "render"})
        comprobar("sin confirmo: pide confirmacion con la cifra",
                  r.startswith("NECESITA CONFIRMACION") and "1.98" in r, r)
        comprobar("y NO lanza nada", not any(m == "POST" for m, _, _ in llamadas))
        r = mcp_estudio.generar({"proyecto": "p", "tanda": "render", "confirmo_coste": 1.5})
        comprobar("con menos de lo que cuesta, tampoco", r.startswith("NECESITA"))
        r = mcp_estudio.generar({"proyecto": "p", "tanda": "render", "confirmo_coste": 1.98})
        comprobar("con la cifra, lanza", "lanzada" in r and any(m == "POST" for m, _, _ in llamadas), r)
        llamadas.clear()
        r = mcp_estudio.generar({"proyecto": "p", "tanda": "guion"})
        comprobar("el guion es gratis: no pide nada", "lanzada" in r, r)
        llamadas.clear()
        r = mcp_estudio.miniaturas({"proyecto": "p"})
        comprobar("miniaturas sin si: no llama", r.startswith("NECESITA") and not llamadas)
    finally:
        mcp_estudio._llamar = original_api
    nombres = mcp_estudio.nombres_permitidos()
    comprobar("las herramientas nuevas van autorizadas",
              "mcp__estudio__estudiar_nicho" in nombres and "mcp__estudio__generar" in nombres)
finally:
    cli_claude.ejecutar = original
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("MIND OK: todas las comprobaciones pasan")
