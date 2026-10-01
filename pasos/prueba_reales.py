"""
Pruebas del modo documental (pasos/reales.py).

Lo que se protege:

  1. CLAUDE ELIGE, PERO NO INVENTA: solo cuentan los ids que existen y las
     busquedas de verdad; lo que conteste de mas o en null se ignora. Y se
     pregunta UNA vez por plan.
  2. NUNCA REAL CON TEXTO NI CON CAPA GRAFICA: ni se le ofrecen a Claude.
  3. UN CLIP NO SE REPITE en dos planos, y uno mas corto que el plano no
     entra (se quedaria congelado).
  4. LO QUE NO SE ENCUENTRA SIGUE CON IA, avisado. Sin claves, nada cambia.

Ninguna llamada sale a la red ni al CLI: los dos se sustituyen.
"""
import os
import shutil
import subprocess
import sys
import tempfile

TEMPORAL = tempfile.mkdtemp(prefix="prueba_reales_")
os.environ["ESTUDIO_SECRETOS"] = os.path.join(TEMPORAL, "secretos")
for nombre in ("PEXELS_API_KEY", "PIXABAY_API_KEY"):
    os.environ.pop(nombre, None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import medios  # noqa: E402
import reales  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, obtenido, esperado):
    comprobar(titulo, obtenido == esperado, f"esperaba {esperado!r}, salio {obtenido!r}")


def escena(sid, t_in, t_out, direccion="A busy harbour at dawn.", **extra):
    base = {"id": sid, "t_in": t_in, "t_out": t_out, "direccion": direccion,
            "narracion": "El puerto despierta.", "accion": ""}
    base.update(extra)
    return base


class Proyecto:
    raiz = os.path.join(TEMPORAL, "proyecto")


print("\n== el modo ==")
igual("apagado por defecto", reales.modo_de({}), "")
igual("bien escrito", reales.modo_de({"video_real": " Mezcla "}), "mezcla")
igual("mal escrito es apagado", reales.modo_de({"video_real": "todo"}), "")

print("\n== que planos se ofrecen ==")
igual("uno limpio, si", reales.puede_ser_real(escena("S1", 0, 3)), None)
igual("con texto dibujado, se le ofrece (lo decide Claude: va marcado)",
      reales.puede_ser_real(escena("S1", 0, 3, 'A sign reading "OPEN".')), None)
comprobar("con capa grafica, no",
          reales.puede_ser_real(escena("S1", 0, 3), "<svg><text>x</text></svg>") is not None)

print("\n== Claude elige (y se guarda) ==")
plan = [escena("S001", 0, 3), escena("S002", 3, 6),
        escena("S003", 6, 9, 'A poster reading "SALE".'), escena("S004", 9, 12)]
llamadas, vistas = [], []
original = cli_claude.ejecutar


def claude_falso(instruccion, **kw):
    llamadas.append(1)
    vistas.append(instruccion)
    return ('Aqui va: {"S001": "harbour dawn boats", "S002": null, "S003": "sale sign", '
            '"S004": "  fishing   nets  ", "S999": "nope"}', {})


cli_claude.ejecutar = claude_falso
try:
    elegido, avisos = reales.planificar(Proyecto, plan, "mezcla")
    igual("solo los ids reales con busqueda; espacios limpios",
          elegido, {"S001": "harbour dawn boats", "S003": "sale sign",
                     "S004": "fishing nets"})
    comprobar("el del cartel va marcado con TEXTO: si",
              "S003 (3.0s)" in vistas[0] and "TEXTO: si" in vistas[0])
    reales.planificar(Proyecto, plan, "mezcla")
    igual("la segunda vez sale de lo guardado", len(llamadas), 1)
    reales.planificar(Proyecto, plan, "maximo")
    igual("otro modo es otra pregunta", len(llamadas), 2)
    igual("apagado no pregunta", reales.planificar(Proyecto, plan, ""), ({}, []))

    def claude_roto(instruccion, **kw):
        raise RuntimeError("sin sesion")
    cli_claude.ejecutar = claude_roto
    elegido, avisos = reales.planificar(Proyecto, [escena("S010", 0, 3)], "mezcla")
    comprobar("si Claude falla: nada real y se dice",
              elegido == {} and avisos and "con IA" in avisos[0], avisos)
finally:
    cli_claude.ejecutar = original

print("\n== buscar, bajar y enganchar ==")
hay_ffmpeg = bool(shutil.which(medios.ffmpeg()) or os.path.exists(medios.ffmpeg()))
stock = medios.motor("video_stock/stock.py")
trabajo = os.path.join(TEMPORAL, "trabajo")
tareas = [{"id": s, "hyper": "x.png", "mov": {}} for s in ("S001", "S004", "S005")]
escenas = {"S001": escena("S001", 0, 3), "S004": escena("S004", 3, 7),
           "S005": escena("S005", 7, 9)}
candidatos = [(t, escenas[t["id"]], b) for t, b in
              zip(tareas, ("harbour", "harbour", "nothing here"))]

avisos = reales.poner(candidatos, Proyecto, 320, 180, trabajo, lambda *a: None)[1]
comprobar("sin claves: nada cambia y se dice",
          all("fotogramas" not in t for t in tareas) and "clave" in avisos[0], avisos)

if not hay_ffmpeg:
    print("  (sin ffmpeg: se omite la parte de clips)")
else:
    muestra = os.path.join(TEMPORAL, "muestra.mp4")
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=size=640x360:rate=25:duration=6",
                    "-pix_fmt", "yuv420p", muestra], check=True)
    os.environ["PEXELS_API_KEY"] = "de-mentira"
    busquedas, bajadas = [], []
    resultados = {
        "harbour": [
            {"banco": "pexels", "id": "pexels-1", "url": "u1", "ancho": 640, "alto": 360,
             "duracion": 2.0, "autor": "Ana", "pagina": "p1"},          # corto
            {"banco": "pexels", "id": "pexels-2", "url": "u2", "ancho": 640, "alto": 360,
             "duracion": 8.0, "autor": "Ana", "pagina": "p2"},
            {"banco": "pixabay", "id": "pixabay-3", "url": "u3", "ancho": 640, "alto": 360,
             "duracion": 8.0, "autor": "Luis", "pagina": "p3"}],
        "nothing here": []}
    original_buscar, original_bajar = stock.buscar, stock.descargar

    def buscar(busqueda, **kw):
        busquedas.append(busqueda)
        return list(resultados.get(busqueda, [])), []

    def descargar(url, destino):
        bajadas.append(url)
        shutil.copy(muestra, destino)
        return destino
    stock.buscar, stock.descargar = buscar, descargar
    try:
        puestos, avisos = reales.poner(candidatos, Proyecto, 320, 180, trabajo,
                                       lambda *a: None)
    finally:
        stock.buscar, stock.descargar = original_buscar, original_bajar
        os.environ.pop("PEXELS_API_KEY", None)
    igual("dos planos con video real", puestos, {"S001", "S004"})
    usados = sorted(t.get("real") for t in tareas if t.get("real"))
    igual("cada uno con un clip distinto, y ninguno el corto", usados,
          ["pexels-2", "pixabay-3"])
    igual("la busqueda repetida se hace una vez (se guarda)", busquedas.count("harbour"), 1)
    t1 = tareas[0]
    comprobar("el plano lleva sus fotogramas al tamano del video",
              t1.get("fotogramas") and t1["mov"]["ventana_ini"] == [0, 0, 1, 1])
    comprobar("el que no encontro nada sigue como estaba (con IA)",
              "fotogramas" not in tareas[2])
    texto = " ".join(avisos)
    comprobar("y se dice cual", "S005" in texto and "con IA" in texto, avisos)
    creditos = medios.leer_json(os.path.join(Proyecto.raiz, "pasos", "render",
                                             "reales", "creditos.json"), {})
    igual("los creditos dicen de donde sale cada uno",
          sorted(c["autor"] for c in creditos.values()), ["Ana", "Luis"])

shutil.rmtree(TEMPORAL, ignore_errors=True)
print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("REALES OK: todas las comprobaciones pasan")
