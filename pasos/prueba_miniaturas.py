"""
Pruebas de las miniaturas de YouTube (pasos/miniaturas.py), sin red.

  1. Claude propone, se dibujan las tres en 16:9 con las laminas del estilo y
     las hojas del reparto del video, y quedan listas en `miniaturas/`.
  2. El texto de la miniatura va entre comillas en el prompt; sin texto, se
     pide la imagen sin letras.
  3. Rehacer una solo redibuja esa, con la nota y el texto nuevo.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import medios  # noqa: E402
import miniaturas  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


TEMPORAL = tempfile.mkdtemp(prefix="prueba_mini_")
buf = io.BytesIO()
Image.new("RGB", (4, 4), (10, 200, 10)).save(buf, format="PNG")
PNG = buf.getvalue()


class Proyecto:
    raiz = os.path.join(TEMPORAL, "proyecto")


lamina = os.path.join(TEMPORAL, "00_00_cara.png")
hoja = os.path.join(Proyecto.raiz, "pasos", "assets", "v1", "reparto", "nico.png")
os.makedirs(os.path.dirname(hoja))
for ruta in (lamina, hoja):
    with open(ruta, "wb") as fh:
        fh.write(PNG)
ESTILO = {"referencias": [lamina], "guia": {}}
dibujos = []


class Imagen:
    @staticmethod
    def normalizar(ruta, cache):
        return ruta

    @staticmethod
    def generar(prompt, refs, quality="low", tamano="apaisado"):
        dibujos.append((prompt, list(refs), quality, tamano))
        return PNG, {"coste": 0.07}


def claude(instruccion, **kw):
    return json.dumps({"miniaturas": [
        {"texto": "ME CONTRATARON", "escena": "a shocked guy", "por_que": "sorpresa"},
        {"texto": "", "escena": "a printer on fire", "por_que": "caos"},
        {"texto": "3 DIAS", "escena": "a calendar", "por_que": "urgencia"}]}), {}


originales = (cli_claude.ejecutar, medios.motor)
cli_claude.ejecutar = claude
medios.motor = lambda ruta: Imagen if "imagen" in ruta else originales[1](ruta)


def esperar():
    for _ in range(100):
        d = miniaturas.leer(Proyecto)
        if d.get("estado") != "pensando":
            return d
        time.sleep(0.05)
    return d


try:
    print("\n== proponer ==")
    miniaturas.proponer(Proyecto, "Dije que sabia", "Nico imprime etiquetas...", ESTILO,
                        "es", "Nico")
    d = esperar()
    comprobar("tres listas", d.get("estado") == "listo" and len(d["miniaturas"]) == 3, d)
    comprobar("en ficheros dentro del proyecto",
              all(os.path.exists(os.path.join(Proyecto.raiz, "miniaturas", m["fichero"]))
                  for m in d["miniaturas"]))
    prompt, refs, calidad, tamano = dibujos[0]
    comprobar("con la lamina y la hoja del reparto", refs == [lamina, hoja], refs)
    comprobar("16:9 en calidad media", tamano == "apaisado" and calidad == "medium")
    comprobar("el texto va entre comillas", '"ME CONTRATARON"' in prompt)
    comprobar("sin texto, se pide sin letras", "No text at all" in dibujos[1][0])

    print("\n== rehacer una ==")
    antes = len(dibujos)
    miniaturas.rehacer(Proyecto, 2, "que arda mas", ESTILO, texto="FUEGO")
    d = esperar()
    comprobar("solo se dibuja esa", len(dibujos) == antes + 1)
    comprobar("con la nota y el texto nuevo", "que arda mas" in dibujos[-1][0]
              and '"FUEGO"' in dibujos[-1][0])
    comprobar("y sube su version", d["miniaturas"][1]["version"] == 2, d["miniaturas"][1])
finally:
    cli_claude.ejecutar, medios.motor = originales
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("MINIATURAS OK: todas las comprobaciones pasan")
