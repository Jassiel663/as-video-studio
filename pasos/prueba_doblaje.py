"""
Pruebas del doblaje (pasos/doblaje.py). Sin red ni CLI.

  1. MAPEAR: cada plano del doblaje toma el del original de su mismo bloque y
     su misma altura; si los bloques no casan, la misma altura del video.
  2. TRADUCIR: los mismos ids y en orden; si faltan bloques se reintenta y,
     si sigue faltando, error claro.
  3. LANZAR: pensando -> listo con el video nuevo; un fallo queda escrito.
  4. LAS IMAGENES: se copian con su ficha (0 $), las cartelas no, una segunda
     pasada no recopia, y sin imagenes en el original se dice.
  5. LA VOZ: nativa del mismo genero; «misma» deja la del original.
"""
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_doblaje_")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import doblaje  # noqa: E402
import p4_voz  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def escena(sid, bloque, t_in, t_out, cartela=False, narracion="x"):
    e = {"id": sid, "t_in": t_in, "t_out": t_out, "narracion": narracion,
         "origen": {"bloque": bloque, "indice": 0}}
    if cartela:
        e["cartela"] = {"plantilla": "negro"}
    return e


class Proyecto:
    def __init__(self, raiz):
        self.raiz = raiz
        os.makedirs(raiz, exist_ok=True)


original_cli = cli_claude.ejecutar
original_listar, original_resolver = p4_voz.listar_voces, p4_voz.resolver_params
try:
    print("\n== mapear ==")
    viejas = [escena("S001", "B1", 0, 4), escena("S002", "B1", 4, 8), escena("S003", "B2", 8, 12),
              escena("S004", "B2", 12, 16), escena("S005", "B2", 16, 20)]
    nuevas = [escena("S001", "B1", 0, 9), escena("S002", "B2", 9, 13), escena("S003", "B2", 13, 17)]
    m = doblaje.mapear(nuevas, viejas)
    comprobar("un plano por bloque toma el del medio", m["S001"] in ("S001", "S002"), m)
    comprobar("dos planos en un bloque de tres: primero y ultimo", m["S002"] == "S003" and m["S003"] == "S005", m)
    sueltas = [escena("S001", "X1", 0, 5), escena("S002", "X2", 15, 20)]
    m = doblaje.mapear(sueltas, viejas)
    comprobar("sin bloques que casen, por la altura del video", m == {"S001": "S001", "S002": "S005"}, m)

    print("\n== traducir ==")
    bloques = [{"id": "B1", "texto": "Hola a todos."}, {"id": "B2", "texto": "Hoy hablamos de leones."}]
    respuestas = [
        '{"titulo": "Lions", "bloques": [{"id": "B1", "texto": "Hi everyone."}]}',
        'Aqui va: ```json\n{"titulo": "Lions", "bloques": [{"id": "B2", "texto": "Today: lions."}, '
        '{"id": "B1", "texto": "Hi everyone."}]}\n```']
    pedidos = []

    def claude(instruccion, **kw):
        pedidos.append(instruccion)
        return respuestas[len(pedidos) - 1], {}

    cli_claude.ejecutar = claude
    titulo, traducidos = doblaje.traducir(bloques, "en", "es", "Leones")
    comprobar("reintenta si faltan bloques", len(pedidos) == 2)
    comprobar("mismos ids y en el orden del original",
              [b["id"] for b in traducidos] == ["B1", "B2"] and traducidos[1]["texto"] == "Today: lions.", traducidos)
    comprobar("traduce el titulo", titulo == "Lions")
    comprobar("pide ingles y largo parecido", "inglés" in pedidos[0] and "LARGO PARECIDO" in pedidos[0])
    cli_claude.ejecutar = lambda instruccion, **kw: ('{"bloques": []}', {})
    try:
        doblaje.traducir(bloques, "en")
        comprobar("sin traduccion completa, error", False)
    except RuntimeError as fallo:
        comprobar("sin traduccion completa, error", "faltan 2" in str(fallo), str(fallo))
    try:
        doblaje.traducir(bloques, "klingon")
        comprobar("un idioma que no hay se rechaza", False)
    except ValueError:
        comprobar("un idioma que no hay se rechaza", True)

    print("\n== lanzar ==")
    origen = Proyecto(os.path.join(TEMPORAL, "proyectos", "leones"))
    cli_claude.ejecutar = lambda instruccion, **kw: (
        '{"titulo": "Lions", "bloques": [{"id": "B1", "texto": "Hi."}, {"id": "B2", "texto": "Lions."}]}', {})
    creados = []

    def crear(titulo, traducidos):
        creados.append((titulo, traducidos))
        return "lions_en"

    doblaje.lanzar(origen, bloques, "en", "es", "Leones", crear)
    for _ in range(50):
        if doblaje.leer(origen).get("en", {}).get("estado") != "pensando":
            break
        time.sleep(0.1)
    d = doblaje.leer(origen)["en"]
    comprobar("queda listo con el video nuevo", d.get("estado") == "listo" and d.get("pid") == "lions_en", d)
    comprobar("crea con el guion traducido", creados and creados[0][1][0]["texto"] == "Hi.")
    try:
        doblaje.lanzar(origen, bloques, "es", "es", "Leones", crear)
        comprobar("al mismo idioma no", False)
    except ValueError:
        comprobar("al mismo idioma no", True)

    def crear_mal(titulo, traducidos):
        raise RuntimeError("no hay estilo")

    doblaje.lanzar(origen, bloques, "pt", "es", "Leones", crear_mal)
    for _ in range(50):
        if doblaje.leer(origen).get("pt", {}).get("estado") != "pensando":
            break
        time.sleep(0.1)
    comprobar("un fallo queda escrito", doblaje.leer(origen)["pt"].get("error") == "no hay estilo")

    print("\n== las imagenes ==")
    activa = os.path.join(origen.raiz, "pasos", "assets", "v2")
    os.makedirs(os.path.join(activa, "escenas"), exist_ok=True)
    os.makedirs(os.path.join(activa, "assets", "reparto"), exist_ok=True)
    with open(os.path.join(origen.raiz, "pasos", "assets", "activa.json"), "w") as fh:
        json.dump({"paso": "assets", "activa": 2}, fh)
    for e in viejas:
        with open(os.path.join(activa, "escenas", f"{e['id']}.png"), "wb") as fh:
            fh.write(e["id"].encode())
    with open(os.path.join(activa, "assets", "reparto", "leona.png"), "wb") as fh:
        fh.write(b"leona")
    with open(os.path.join(activa, "plan.json"), "w") as fh:
        json.dump({"escenas": viejas}, fh)
    dob = Proyecto(os.path.join(TEMPORAL, "proyectos", "lions_en"))
    nuevas.append(escena("S004", "B2", 17, 19, cartela=True))
    carpeta = os.path.join(TEMPORAL, "trabajo", "escenas")
    sin_imagen = lambda e: bool(e.get("cartela"))
    clave = lambda e: str(e.get("narracion") or "").lower()
    n = doblaje.preparar_imagenes(dob, "leones", nuevas, carpeta, sin_imagen, clave)
    comprobar("copia una imagen por plano con imagen", n == 3 and sorted(os.listdir(carpeta)) == [
        "S001.json", "S001.png", "S002.json", "S002.png", "S003.json", "S003.png"], os.listdir(carpeta))
    comprobar("la imagen que toca", open(os.path.join(carpeta, "S003.png"), "rb").read() == b"S005")
    ficha = json.load(open(os.path.join(carpeta, "S002.json"), encoding="utf-8"))
    comprobar("con su ficha: 0 $ y para que narracion vale",
              ficha["coste"] == 0 and ficha["vale_para"] == "x" and ficha["doblaje_de"] == "leones/S003", ficha)
    comprobar("una segunda pasada no recopia", doblaje.preparar_imagenes(dob, "leones", nuevas, carpeta, sin_imagen, clave) == 0)
    reparto = os.path.join(TEMPORAL, "trabajo", "reparto")
    comprobar("las hojas de personaje tambien", doblaje.preparar_reparto(dob, "leones", reparto) == 1
              and os.path.exists(os.path.join(reparto, "leona.png")))
    try:
        doblaje.preparar_imagenes(dob, "nadie", nuevas, carpeta, sin_imagen, clave)
        comprobar("sin imagenes en el original se dice", False)
    except RuntimeError as fallo:
        comprobar("sin imagenes en el original se dice", "pagarlas" in str(fallo))

    print("\n== la voz ==")
    p4_voz.resolver_params = lambda params: {"voz_id": params.get("voz_id") or "hector"}
    voces = [{"id": "hector", "genero": "masculine"}, {"id": "ana", "genero": "feminine"},
             {"id": "john", "genero": "masculine"}, {"id": "mary", "genero": "feminine"}]
    nativas_en = [{"id": "mary", "genero": "feminine"}, {"id": "john", "genero": "masculine"}]
    p4_voz.listar_voces = lambda idioma=None, solo_nativas=False, **k: nativas_en if idioma else voces
    comprobar("nativa del mismo genero", doblaje.voz_para({}, "en") == "john")
    comprobar("nativa del mismo genero (voz femenina)", doblaje.voz_para({"voz_id": "ana"}, "en") == "mary")
    comprobar("«misma» deja la del original", doblaje.voz_para({}, "en", "misma") == "hector")

    def sin_red(*a, **k):
        raise RuntimeError("sin red")

    p4_voz.listar_voces = sin_red
    comprobar("sin poder preguntar, la del original", doblaje.voz_para({}, "en") == "hector")
finally:
    cli_claude.ejecutar = original_cli
    p4_voz.listar_voces, p4_voz.resolver_params = original_listar, original_resolver
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("DOBLAJE OK: todas las comprobaciones pasan")
