"""
Pruebas del taller del canal (pasos/canal.py) y de como entra en los videos.
Sin red: el CLI de Claude y el motor de imagen se sustituyen.

  1. CREAR: Claude describe, se dibuja la hoja con las laminas del estilo (y la
     foto si la hay), y la ficha queda lista con su imagen.
  2. REHACER con nota: la nota entra en el prompt y la version sube.
  3. ENTRA EN EL CATALOGO: personajes y objetos al reparto con su hoja, lugares
     a los sitios con su imagen; el rotulo del video no se pisa.
  4. EN ASSETS la hoja del canal NO se paga: se copia.
  5. EN EL PLANO: el lugar del canal va como referencia y se presenta como tal.
"""
import base64
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_canal_")
os.environ["ESTUDIO_CANAL"] = os.path.join(TEMPORAL, "canal")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import canal  # noqa: E402
import cli_claude  # noqa: E402
import medios  # noqa: E402
import p6_assets  # noqa: E402
import presets_canal  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, a, b):
    comprobar(titulo, a == b, f"esperaba {b!r}, salio {a!r}")


_buf = __import__("io").BytesIO()
__import__("PIL.Image", fromlist=["Image"]).new("RGB", (4, 4), (200, 30, 30)).save(_buf, format="PNG")
PNG = _buf.getvalue()
lamina = os.path.join(TEMPORAL, "00_00_cara.png")
sitio = os.path.join(TEMPORAL, "02_02_interior.png")
for ruta in (lamina, sitio):
    with open(ruta, "wb") as fh:
        fh.write(PNG)
PRESET = {"id": "pr1", "nombre": "Canal", "datos": {
    "estilo": {"referencias": [lamina, sitio], "guia": {"resumen_es": "monigotes"}},
    "guion": {"idioma_salida": "es"}, "origen": {}}}

originales = (presets_canal.leer, cli_claude.ejecutar)
presets_canal.leer = lambda pid: PRESET if pid == "pr1" else None
pedidos_claude, pedidos_imagen = [], []


def claude(instruccion, **kw):
    pedidos_claude.append(instruccion)
    return json.dumps({"descripcion": "a stick figure with a green hoodie",
                       "papel": "el protagonista", "palabras": ["Nico", "el chico"]}), {}


class Imagen:
    @staticmethod
    def normalizar(ruta, cache):
        return ruta

    @staticmethod
    def generar(prompt, refs, quality="low", tamano="apaisado"):
        pedidos_imagen.append((prompt, list(refs), quality))
        return PNG, {"coste": 0.09}


cli_claude.ejecutar = claude
original_motor = medios.motor
medios.motor = lambda ruta: Imagen if "imagen" in ruta else original_motor(ruta)


def esperar(tipo, ident):
    for _ in range(100):
        f = canal.leer("pr1")[tipo].get(ident) or {}
        if f.get("estado") != "pensando":
            return f
        time.sleep(0.05)
    return f


try:
    print("\n== crear ==")
    f = canal.crear("pr1", "personajes", "Nico", "un chico despeinado con sudadera verde",
                    foto_b64="data:image/png;base64," + base64.b64encode(PNG).decode())
    igual("el id sale del nombre", f["id"], "nico")
    f = esperar("personajes", "nico")
    igual("y acaba listo", f.get("estado"), "listo")
    comprobar("con la descripcion de Claude", "green hoodie" in f.get("descripcion", ""))
    comprobar("y las palabras con el nombre delante", f.get("palabras", [])[:1] == ["Nico"], f.get("palabras"))
    prompt, refs, calidad = pedidos_imagen[-1]
    comprobar("la hoja usa la lamina de caras, no la de sitios", lamina in refs and sitio not in refs, refs)
    comprobar("y la foto va la ultima, dicha en el prompt", refs[-1] == f["foto"] and "photo or drawing" in prompt)
    igual("en calidad media", calidad, "medium")
    comprobar("la imagen existe", os.path.exists(f["imagen"]))
    igual("un segundo con el mismo nombre no pisa al primero",
          canal.crear("pr1", "personajes", "Nico", "otro")["id"], "nico_2")
    esperar("personajes", "nico_2")
    canal.borrar("pr1", "personajes", "nico_2")

    canal.crear("pr1", "lugares", "La oficina", "una oficina pequena con plantas")
    lugar = esperar("lugares", "la_oficina")
    comprobar("un lugar usa la lamina de interiores", sitio in pedidos_imagen[-1][1])
    canal.crear("pr1", "objetos", "La taza", "una taza roja con un rayo")
    esperar("objetos", "la_taza")

    print("\n== rehacer con nota ==")
    canal.crear("pr1", "personajes", "", "", ident="nico", nota="mas joven")
    f = esperar("personajes", "nico")
    comprobar("la nota entra en el prompt", "mas joven" in pedidos_imagen[-1][0])
    igual("y la version sube", f.get("version"), 2)
    igual("sin volver a preguntar a Claude la descripcion", len(pedidos_claude), 4)

    print("\n== entra en el catalogo ==")
    cat = {"reparto": {"nico": {"descripcion": "otro", "palabras": ["Nicolas"]}},
           "sets": {"la_oficina": {"rotulo": "Madrid, 9:00", "descripcion": "x"}}}
    igual("entran los tres", canal.fusionar(cat, "pr1"), 3)
    comprobar("el personaje con su hoja y sus palabras juntas",
              cat["reparto"]["nico"]["hoja_canal"] == f["imagen"]
              and set(cat["reparto"]["nico"]["palabras"]) >= {"Nico", "Nicolas"})
    comprobar("el objeto marcado como objeto", cat["reparto"]["la_taza"]["objeto"])
    igual("el rotulo del video no se pisa", cat["sets"]["la_oficina"]["rotulo"], "Madrid, 9:00")
    comprobar("la peticion a Claude nombra los ids", "nico = Nico" in canal.peticion_para_catalogo("pr1")
              and "la_oficina" in canal.peticion_para_catalogo("pr1"))

    print("\n== en assets y en el plano ==")
    plan = {"escenas": [{"id": "S001", "personajes": ["nico"], "set": "la_oficina"}]}
    necesarios = p6_assets._assets_necesarios(plan, cat, {})
    igual("el asset lleva la hoja del canal", necesarios["asset:nico"]["hoja_canal"], f["imagen"])
    frase = p6_assets.frase_de_referencia(3, {"papel": "lugar", "nombre": "la_oficina"})
    comprobar("el lugar se presenta como lugar recurrente", "recurring location" in (frase or ""))
    frase = p6_assets.frase_de_referencia(4, {"papel": "reparto", "nombre": "la_taza", "objeto": True})
    comprobar("y el objeto como objeto, sin hablar de caras", "object" in frase and "faces" not in frase)
finally:
    presets_canal.leer, cli_claude.ejecutar = originales
    medios.motor = original_motor
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("CANAL OK: todas las comprobaciones pasan")
