"""
Pruebas de publicar (pasos/publicar.py), sin red ni CLI.

  1. CUENTAS POR ESTILO: se guardan por estilo, se les pone https:// si falta,
     y una plataforma que no se manda no se borra.
  2. LA SUBIDA: un enlace de YouTube con id de canal abre el Studio de ESE canal.
  3. EL KIT SEO: lleva el guion con marcas de tiempo (para los capitulos) y
     guarda los textos de cada plataforma.
"""
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_publicar_")
os.environ["ESTUDIO_PUBLICAR"] = os.path.join(TEMPORAL, "publicar")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import publicar  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


class Proyecto:
    raiz = os.path.join(TEMPORAL, "proyecto")


original = cli_claude.ejecutar
pedidos = []
try:
    print("\n== cuentas por estilo ==")
    publicar.guardar_destinos("nico", {"youtube": "youtube.com/@nico", "tiktok": "https://tiktok.com/@n"})
    publicar.guardar_destinos("nico", {"facebook": "https://facebook.com/nico"})
    d = publicar.destinos("nico")
    comprobar("se pone https:// si falta", d["youtube"] == "https://youtube.com/@nico", d)
    comprobar("lo que no se manda no se borra", d["tiktok"] == "https://tiktok.com/@n" and d["facebook"])
    comprobar("otro estilo tiene las suyas", publicar.destinos("jass")["youtube"] == "")

    print("\n== la subida ==")
    url = publicar.pagina_de_subida("youtube", "https://www.youtube.com/channel/UC1234567890abcdefghijkl")
    comprobar("con id de canal abre ese Studio", "/channel/UC1234567890abcdefghijkl/videos/upload" in url, url)
    comprobar("con @handle, el Studio general", publicar.pagina_de_subida("youtube", "https://youtube.com/@x")
              == "https://studio.youtube.com/")

    print("\n== el kit SEO ==")

    def claude(instruccion, **kw):
        pedidos.append(instruccion)
        return json.dumps({"youtube": {"titulo": "T", "descripcion": "D", "etiquetas": ["a"]},
                           "tiktok": {"texto": "tt #x"}}), {}
    cli_claude.ejecutar = claude
    escenas = [{"t_in": 0, "t_out": 5, "narracion": "Hola."}, {"t_in": 5, "t_out": 30, "narracion": "Seguimos."},
               {"t_in": 30, "t_out": 200, "narracion": "Final."}]
    publicar.generar_seo(Proyecto, "Mi video", escenas)
    for _ in range(100):
        s = publicar.leer_seo(Proyecto)
        if s.get("estado") != "pensando":
            break
        time.sleep(0.05)
    comprobar("listo con sus textos", s.get("estado") == "listo" and s["youtube"]["titulo"] == "T"
              and s["tiktok"]["texto"] == "tt #x", s)
    comprobar("las plataformas que no vienen quedan vacias", s["facebook"] == {} and s["instagram"] == {})
    comprobar("el guion lleva marcas de tiempo para los capitulos",
              "[0:00] Hola." in pedidos[-1] and "[0:30] Final." in pedidos[-1], pedidos[-1][-300:])
    comprobar("y la duracion", "3:20 min" in pedidos[-1])
finally:
    cli_claude.ejecutar = original
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("PUBLICAR OK: todas las comprobaciones pasan")
