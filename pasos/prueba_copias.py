"""
Pruebas de las copias de seguridad (pasos/copias.py), con rsync de verdad.

  1. Una copia lleva lo que vale y NO lo que se rehace gratis (render, trabajo,
     modelos).
  2. La segunda copia no duplica: lo que no cambio es el mismo fichero (enlace
     duro).
  3. Recuperar un video saca uno NUEVO y no pisa el de ahora.
  4. Podar: 7 dias, 4 semanas, 3 manuales y nunca la ultima.
"""
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_copias_")
DATOS = os.path.join(TEMPORAL, "datos")
os.environ["ESTUDIO_COPIAS"] = os.path.join(TEMPORAL, "copias")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import copias  # noqa: E402

copias.DATOS = DATOS
fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def escribir(ruta, contenido="x"):
    ruta = os.path.join(DATOS, ruta)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(contenido)


try:
    escribir("presets.json", "{}")
    escribir("secretos/claves.json", "{}")
    escribir("proyectos/leon/proyecto.json", json.dumps({"id": "leon", "nombre": "El leon"}))
    escribir("proyectos/leon/pasos/assets/v1/escenas/S001.png", "imagen pagada")
    escribir("proyectos/leon/pasos/render/v1/video.mp4", "mp4 pesado")
    escribir("proyectos/leon/pasos/voz/trabajo/temp.wav", "a medias")
    escribir("modelos/whisper.bin", "modelo")

    print("\n== una copia ==")
    n1 = copias.hacer()
    raiz = os.path.join(copias.CARPETA, n1)
    existe = lambda r: os.path.exists(os.path.join(raiz, r))
    comprobar("lleva estilos, claves e imagenes pagadas",
              existe("presets.json") and existe("secretos/claves.json")
              and existe("proyectos/leon/pasos/assets/v1/escenas/S001.png"))
    comprobar("NO lleva el render, lo de trabajo ni el modelo",
              not existe("proyectos/leon/pasos/render") and not existe("proyectos/leon/pasos/voz/trabajo")
              and not existe("modelos"))
    lista = copias.listar()
    comprobar("se lista con sus videos", lista["copias"][0]["proyectos"] == [{"id": "leon", "nombre": "El leon"}], lista)

    print("\n== la segunda no duplica ==")
    escribir("proyectos/leon/notas.txt", "nuevo")
    n2 = copias.hacer(manual=True)
    a = os.stat(os.path.join(copias.CARPETA, n1, "proyectos/leon/pasos/assets/v1/escenas/S001.png"))
    b = os.stat(os.path.join(copias.CARPETA, n2, "proyectos/leon/pasos/assets/v1/escenas/S001.png"))
    comprobar("lo que no cambio es el mismo fichero (enlace duro)", a.st_ino == b.st_ino)
    comprobar("y lo nuevo esta", os.path.exists(os.path.join(copias.CARPETA, n2, "proyectos/leon/notas.txt")))

    print("\n== recuperar ==")
    escribir("proyectos/leon/proyecto.json", json.dumps({"id": "leon", "nombre": "El leon ESTROPEADO"}))
    nuevo = copias.recuperar_proyecto(n1, "leon")
    comprobar("sale con otro id", nuevo.startswith("leon_recuperado_"), nuevo)
    ficha = json.load(open(os.path.join(DATOS, "proyectos", nuevo, "proyecto.json"), encoding="utf-8"))
    comprobar("con el contenido de la copia", ficha["nombre"].startswith("El leon (recuperado") and ficha["id"] == nuevo, ficha)
    actual = json.load(open(os.path.join(DATOS, "proyectos/leon/proyecto.json"), encoding="utf-8"))
    comprobar("y el de ahora no se toca", actual["nombre"] == "El leon ESTROPEADO")
    comprobar("recuperar dos veces no pisa", copias.recuperar_proyecto(n1, "leon") != nuevo)
    for malo in ("../secretos", "nadie"):
        try:
            copias.recuperar_proyecto(n1, malo)
            comprobar(f"un id raro se rechaza ({malo})", False)
        except ValueError:
            comprobar(f"un id raro se rechaza ({malo})", True)

    print("\n== podar ==")
    hoy = time.mktime(time.strptime("2026-10-20", "%Y-%m-%d"))
    for dia in range(1, 21):
        os.makedirs(os.path.join(copias.CARPETA, f"2026-09-{dia:02d}_0400"))
        os.makedirs(os.path.join(copias.CARPETA, f"2026-10-{dia:02d}_0400"))
    for m in range(5):
        os.makedirs(os.path.join(copias.CARPETA, f"2026-08-0{m + 1}_1200_manual"))
    copias.podar(hoy)
    quedan = [n for n in copias._copias() if n.startswith("2026-")]
    dias = [n for n in quedan if n >= "2026-10-14" and not n.endswith("_manual")]
    comprobar("las de los 7 ultimos dias", len(dias) == 7, dias)
    semanales = [n for n in quedan if "2026-09-15" <= n < "2026-10-14" and not n.endswith("_manual")]
    comprobar("una por semana de las 4 anteriores", 4 <= len(semanales) <= 5, semanales)
    manuales = [n for n in quedan if n.endswith("_manual")]
    comprobar("las 3 manuales mas nuevas", len(manuales) == 3 and "2026-08-02_1200_manual" not in manuales, manuales)
    comprobar("las viejas se van", "2026-09-01_0400" not in quedan)
finally:
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("COPIAS OK: todas las comprobaciones pasan")
