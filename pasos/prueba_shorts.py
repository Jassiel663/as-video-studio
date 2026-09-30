"""
Pruebas de la zona Shorts (`pasos/shorts.py`).

Lo que se protege:

  1. EL RECORTE SE CORTA EN LIMITES DE PLANO y dentro de 15-60 s: cortar a
     mitad de plano es cortar a mitad de frase.
  2. EL RECORTE SALE VERTICAL 1080x1920 con los dos encuadres, y dura lo que
     el tramo.
  3. LOS CANALES DE SHORTS se marcan y desmarcan, y la marca vive fuera del
     codigo (junto a tarifas.json).
  4. SI CLAUDE NO CONTESTA, el recorte lo dice: no finge que lo eligio el.

No llama a Claude de verdad: `cli_claude.ejecutar` se sustituye por un doble.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

TEMPORAL = tempfile.mkdtemp(prefix="prueba_shorts_")
os.environ["ESTUDIO_TARIFAS"] = os.path.join(TEMPORAL, "datos", "tarifas.json")
os.environ.pop("ESTUDIO_SHORTS", None)
os.makedirs(os.path.join(TEMPORAL, "datos"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import medios  # noqa: E402
import shorts  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, obtenido, esperado):
    comprobar(titulo, obtenido == esperado, f"esperaba {esperado!r}, salio {obtenido!r}")


# 60 planos de 3,5 s: el video de mentira dura 210 s
LISTA = [{"id": f"S{i:03d}", "desde": round(i * 3.5, 3), "hasta": round((i + 1) * 3.5, 3),
          "texto": f"frase {i}"} for i in range(60)]


def largo(a, b):
    return LISTA[b]["hasta"] - LISTA[a]["desde"]


print("\n== el tramo a mano: limites de plano y 15-60 s ==")
a, b = shorts.tramo_desde(LISTA, 0, 45)
igual("empieza en el plano que contiene el segundo pedido", LISTA[a]["id"], "S000")
comprobar("acaba cerca de lo pedido (45 s)", abs(largo(a, b) - 45) <= 3.5, largo(a, b))
a, b = shorts.tramo_desde(LISTA, 100, 30)
igual("el segundo 100 cae en S028 (98-101,5)", LISTA[a]["id"], "S028")
comprobar("30 s pedidos, a un plano de distancia como mucho", abs(largo(a, b) - 30) <= 3.5,
          largo(a, b))
a, b = shorts.tramo_desde(LISTA, 190, 60)
comprobar("cerca del final se corta donde acaba el video, sin pasarse", b == 59 and
          largo(a, b) <= 60, (LISTA[a]["id"], LISTA[b]["id"], largo(a, b)))
a, b = shorts.tramo_desde(LISTA, 0, 60)
comprobar("nunca pasa de 60 s", largo(a, b) <= 60, largo(a, b))

print("\n== el tramo automatico ==")
original = cli_claude.ejecutar
try:
    cli_claude.ejecutar = lambda *a, **k: (
        '{"desde": "S030", "hasta": "S040", "titulo": "El giro"}', {})
    a, b, titulo, por_claude = shorts.tramo_auto(LISTA, 40)
    comprobar("respeta el inicio que elige Claude", LISTA[a]["id"] == "S030" and por_claude)
    igual("y su titulo", titulo, "El giro")
    comprobar("y la duracion pedida (40 s, no los 38,5 de su tramo si se aleja poco)",
              abs(largo(a, b) - 40) <= 6, largo(a, b))

    cli_claude.ejecutar = lambda *a, **k: (
        '{"desde": "S010", "hasta": "S050", "titulo": "Demasiado"}', {})
    a, b, _, _ = shorts.tramo_auto(LISTA, 30)
    comprobar("si Claude se pasa de 60 s, se corta a lo pedido", abs(largo(a, b) - 30) <= 3.5,
              largo(a, b))

    def roto(*a, **k):
        raise RuntimeError("Not logged in")
    cli_claude.ejecutar = roto
    a, b, titulo, por_claude = shorts.tramo_auto(LISTA, 30)
    comprobar("si Claude falla, el principio", LISTA[a]["id"] == "S000")
    comprobar("y lo dice (no finge que lo eligio Claude)", por_claude is False)
finally:
    cli_claude.ejecutar = original

print("\n== los canales de shorts ==")
igual("viven junto a tarifas.json", os.path.dirname(shorts._ruta()),
      os.path.join(TEMPORAL, "datos"))
igual("al principio ninguno", shorts.canales(), [])
shorts.marcar_canal("pr_uno", True)
shorts.marcar_canal("pr_dos", True)
shorts.marcar_canal("pr_uno", True)
igual("marcar dos veces no lo repite", shorts.canales(), ["pr_dos", "pr_uno"])
shorts.marcar_canal("pr_dos", False)
igual("desmarcar lo quita", shorts.canales(), ["pr_uno"])
try:
    shorts.marcar_canal("", True)
    comprobar("un estilo vacio se rechaza", False)
except ValueError:
    comprobar("un estilo vacio se rechaza", True)

print("\n== el corte en vertical ==")
hay_ffmpeg = bool(shutil.which(medios.ffmpeg()) or os.path.exists(medios.ffmpeg()))
if not hay_ffmpeg:
    print("  (sin ffmpeg: se omite)")
else:
    fuente = os.path.join(TEMPORAL, "largo.mp4")
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=1920x1080:rate=30:duration=20",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=20",
                    "-shortest", "-pix_fmt", "yuv420p", fuente], check=True)
    for encuadre in ("fondo", "centro"):
        salida = os.path.join(TEMPORAL, f"corte_{encuadre}.mp4")
        shorts.cortar(fuente, 4.0, 19.0, encuadre, salida)
        info = subprocess.run([medios.ffprobe(), "-v", "error", "-show_entries",
                               "stream=codec_type,width,height:format=duration",
                               "-of", "json", salida], capture_output=True, text=True)
        datos = json.loads(info.stdout)
        video = [s for s in datos["streams"] if s["codec_type"] == "video"][0]
        igual(f"{encuadre}: 1080x1920", (video["width"], video["height"]), (1080, 1920))
        comprobar(f"{encuadre}: lleva audio",
                  any(s["codec_type"] == "audio" for s in datos["streams"]))
        comprobar(f"{encuadre}: dura el tramo (15 s)",
                  abs(float(datos["format"]["duration"]) - 15.0) < 0.3,
                  datos["format"]["duration"])

shutil.rmtree(TEMPORAL, ignore_errors=True)
print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("SHORTS OK: todas las comprobaciones pasan")
