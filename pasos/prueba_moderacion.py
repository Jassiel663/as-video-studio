"""
La revision del contenido de las cuentas (pasos/moderacion.py), con un Claude
de mentira:

  1. encuentra los videos (nombre + material + guion), shorts y clippings de
     cada cuenta;
  2. revisa solo lo NUEVO o CAMBIADO (segunda pasada sin novedades: 0 llamadas);
  3. lo marcado avisa una vez (no en cada pasada) y sale en el resumen, lo
     grave y sin ver primero;
  4. «visto» lo baja de la lista; lo borrado desaparece de la revision.
"""
import json
import os
import shutil
import sys
import tempfile

TEMPORAL = tempfile.mkdtemp(prefix="prueba_moderacion_")
os.environ["ESTUDIO_COPIAS_CUENTAS"] = os.path.join(TEMPORAL, "cuentas")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import avisos  # noqa: E402
import moderacion  # noqa: E402

moderacion.FICHERO = os.path.join(TEMPORAL, "moderacion.json")
fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def escribir(ruta, datos):
    ruta = os.path.join(TEMPORAL, "cuentas", ruta)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(datos, fh)


escribir("ana/datos/proyectos/leones/proyecto.json", {"nombre": "Los leones"})
escribir("ana/datos/proyectos/leones/estado.json", {"pasos": {"ingesta": {"params": {"texto": "Los leones cazan de noche."}}}})
escribir("ana/datos/proyectos/leones/pasos/guion/activa.json", {"activa": 1})
escribir("ana/datos/proyectos/leones/pasos/guion/v1/guion.json", {"guion": [{"id": "B1", "texto": "El rey de la sabana."}]})
escribir("pedro/datos/proyectos/cripto/proyecto.json", {"nombre": "Duplica tu dinero"})
escribir("pedro/datos/proyectos/cripto/estado.json", {"pasos": {"ingesta": {"params": {"texto": "Invierte 100 y gana 10.000 garantizado"}}}})
escribir("pedro/datos/trabajados/t1/ficha.json", {"estado": "listo", "titulo": "Mi gato", "texto": "mi gato duerme"})
escribir("pedro/datos/clipping/c1/ficha.json", {"estado": "listo", "nombre": "Podcast", "url": "https://youtu.be/x",
                                               "clips": [{"titulo": "Clip 1", "porque": "gracioso"}]})

llamadas = []


def clasificar(lote):
    llamadas.append([c["id"] for c in lote])
    salida = {}
    for c in lote:
        if "garantizado" in c["texto"]:
            salida[c["id"]] = {"nivel": "grave", "motivo": "promete ganancias garantizadas: posible estafa"}
        elif c["tipo"] == "clipping":
            salida[c["id"]] = {"nivel": "dudoso", "motivo": "clips de un video ajeno: comprobar permiso"}
        else:
            salida[c["id"]] = {"nivel": "ok", "motivo": ""}
    return salida


avisados = []
original = avisos.avisar
avisos.avisar = lambda tipo, titulo, texto="", estilo="", enlace="": avisados.append(titulo)
try:
    print("\n== que se revisa ==")
    lista = moderacion.contenidos()
    ids = sorted(c["id"] for c in lista)
    comprobar("videos, shorts y clippings de cada cuenta", ids == [
        "ana/video/leones", "pedro/clipping/c1", "pedro/short/t1", "pedro/video/cripto"], ids)
    leones = next(c for c in lista if c["id"] == "ana/video/leones")
    comprobar("con su material y su guion", "cazan de noche" in leones["texto"] and "rey de la sabana" in leones["texto"], leones)

    print("\n== una pasada ==")
    r = moderacion.revisar(clasificar)
    comprobar("revisa las 4", r["revisados"] == 4 and len(llamadas) == 1, r)
    comprobar("avisa de lo grave y lo dudoso", len(avisados) == 2 and any("Duplica" in a for a in avisados), avisados)
    res = moderacion.resumen()
    comprobar("el resumen: lo grave primero", [m["nivel"] for m in res["marcados"]] == ["grave", "dudoso"], res["marcados"])

    print("\n== la segunda pasada ==")
    llamadas.clear()
    avisados.clear()
    r = moderacion.revisar(clasificar)
    comprobar("sin novedades: ni una llamada", r["revisados"] == 0 and not llamadas, (r, llamadas))
    escribir("ana/datos/proyectos/leones/pasos/guion/v1/guion.json", {"guion": [{"id": "B1", "texto": "ganancia garantizado: 10.000 $"}]})
    r = moderacion.revisar(clasificar)
    comprobar("solo lo que cambio", llamadas == [["ana/video/leones"]], llamadas)
    comprobar("y avisa del cambio a grave", len(avisados) == 1 and "Los leones" in avisados[0], avisados)
    llamadas.clear()
    avisados.clear()
    escribir("ana/datos/proyectos/leones/pasos/guion/v1/guion.json", {"guion": [{"id": "B1", "texto": "otro texto, tambien garantizado"}]})
    moderacion.revisar(clasificar)
    comprobar("si sigue igual de grave no vuelve a avisar", not avisados, avisados)

    print("\n== visto y borrado ==")
    clave = next(m["clave"] for m in moderacion.resumen()["marcados"] if m["cuenta"] == "pedro" and m["nivel"] == "grave")
    moderacion.marcar_visto(clave)
    res = moderacion.resumen()["marcados"]
    comprobar("lo visto baja al final", res[-1]["clave"] == clave and res[-1]["visto"] is True, res)
    shutil.rmtree(os.path.join(TEMPORAL, "cuentas", "pedro", "datos", "clipping"))
    moderacion.revisar(clasificar)
    comprobar("lo borrado sale de la revision", all(m["tipo"] != "clipping" for m in moderacion.resumen()["marcados"]))
    try:
        moderacion.marcar_visto("nadie/video/x")
        comprobar("marcar algo que no existe da error", False)
    except ValueError:
        comprobar("marcar algo que no existe da error", True)
finally:
    avisos.avisar = original
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("MODERACION OK: todas las comprobaciones pasan")
