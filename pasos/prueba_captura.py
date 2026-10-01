"""
Pruebas de la captura en JPEG del render (`p8_render.FORMATO_FOTOGRAMA`).

Lo que se protege:

  1. EL VIDEO SE VE IGUAL. El mismo plano --con su transicion desde el plano
     anterior-- renderizado con PNG y con JPEG da clips que no se distinguen
     (PSNR alto) y con los mismos fotogramas.
  2. EL ULTIMO FOTOGRAMA SIGUE SIENDO UN PNG DE VERDAD: es lo que lee el plano
     siguiente, tambien en un render de un solo plano que lee el de un render
     de antes.
  3. LA TRANSICION ESCRIBE EN EL FORMATO DEL FOTOGRAMA: un JPEG que de pronto
     llevara bytes de PNG romperia la codificacion de ffmpeg.

Necesita Edge y ffmpeg: sin ellos dice que se omite y no falla.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import medios  # noqa: E402
import p8_render  # noqa: E402
import transiciones  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, obtenido, esperado):
    comprobar(titulo, obtenido == esperado, f"esperaba {esperado!r}, salio {obtenido!r}")


TEMPORAL = tempfile.mkdtemp(prefix="prueba_captura_")

print("\n== el nombre del fotograma ==")
igual("por defecto, JPEG", p8_render.FORMATO_FOTOGRAMA, "jpg")
igual("numerado desde 1 con cinco cifras",
      os.path.basename(p8_render.fotograma(TEMPORAL, 7)), "f00007.jpg")

print("\n== el ultimo fotograma, siempre PNG ==")
jpeg = os.path.join(TEMPORAL, "f00001.jpg")
Image.new("RGB", (64, 36), (200, 40, 40)).save(jpeg, quality=95)
ultimo = os.path.join(TEMPORAL, "ultimo.png")
p8_render._guardar_ultimo(jpeg, ultimo)
with Image.open(ultimo) as im:
    igual("de un JPEG sale un PNG de verdad", im.format, "PNG")
    igual("con el mismo tamano", im.size, (64, 36))
comprobar("sin dejar el temporal", not os.path.exists(ultimo + ".parcial"))


def hyper_de_prueba(ruta, ancho, alto):
    """Una imagen como las del estudio: fondo en degradado, formas con borde y
    trazos. NO un tablero de cuadros finos: ese es el peor caso del JPEG y no
    se parece a ningun plano (con el, 40,9 dB y JPEG mas lento a 960x540)."""
    from PIL import ImageDraw
    fondo = Image.linear_gradient("L").resize((ancho, alto))
    im = Image.merge("RGB", (fondo, fondo.rotate(90).resize((ancho, alto)),
                             Image.new("L", (ancho, alto), 120)))
    dibujo = ImageDraw.Draw(im)
    for i in range(12):
        x, y = (i * 157) % ancho, (i * 89) % alto
        dibujo.ellipse([x, y, x + ancho // 8, y + alto // 6],
                       fill=(40 + i * 15, 200 - i * 10, 90), outline=(20, 20, 20),
                       width=4)
        dibujo.line([0, y, ancho, (y * 3) % alto], fill=(240, 230, 210), width=3)
    im.save(ruta)
    return ruta


def renderizar(formato, carpeta, hyper, anterior, ancho, alto, fps, total):
    p8_render.FORMATO_FOTOGRAMA = formato
    os.makedirs(carpeta, exist_ok=True)
    pagina_trans = transiciones.pagina(os.path.join(carpeta, "trans.html"),
                                       ancho, alto, {})
    tarea = {"id": "S002", "escena": {"id": "S002", "t_in": 0.0,
                                      "t_out": total / float(fps)},
             "mov": {"ventana_ini": [0.0, 0.0, 1.0, 1.0],
                     "ventana_fin": [0.1, 0.1, 0.8, 0.8],
                     "hyperframe_px": [ancho, alto]},
             "capa": "", "capa_fija": "", "hyper": hyper, "frames": total,
             "fps": fps, "resolucion": [ancho, alto], "calidad": "alta",
             "carpeta": os.path.join(carpeta, "frames"),
             "clip": os.path.join(carpeta, "S002.mp4"),
             "ultimo": os.path.join(carpeta, "ultimo", "S002.png"),
             "desde": time.time() - 5, "anterior": anterior, "previo": "S001",
             "esperar_anterior": False,
             "corte": {"tipo": "fundido", "shader": transiciones.frag_de("fundido"),
                       "duracion": 0.4, "ranura": "suave"},
             "pagina_trans": pagina_trans, "conservar_frames": True}
    os.makedirs(os.path.dirname(tarea["ultimo"]), exist_ok=True)
    navegador = p8_render.Navegador(ancho, alto)
    try:
        inicio = time.perf_counter()
        ficha = p8_render.renderizar_plano(tarea, navegador)
        tardo = time.perf_counter() - inicio
    finally:
        navegador.cerrar()
    return tarea, ficha, tardo


def psnr(a, b):
    salida = subprocess.run(
        [medios.ffmpeg(), "-i", a, "-i", b, "-lavfi", "psnr", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    hallado = re.search(r"average:([0-9.]+|inf)", salida)
    return float("inf") if hallado and hallado.group(1) == "inf" else (
        float(hallado.group(1)) if hallado else 0.0)


def fotogramas_de(clip):
    salida = subprocess.run(
        [medios.ffprobe() if hasattr(medios, "ffprobe") else "ffprobe", "-v", "error",
         "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_frames", "-of", "csv=p=0", clip],
        capture_output=True, text=True).stdout.strip()
    return int(salida or 0)


print("\n== el mismo plano en PNG y en JPEG, con transicion ==")
try:
    edge = medios.edge()
    hay_edge = bool(edge) and (os.path.exists(edge) or shutil.which(edge))
except Exception:                                               # noqa: BLE001
    hay_edge = False
if not hay_edge:
    print("  (sin Edge: se omite el render de verdad)")
else:
    ANCHO, ALTO, FPS, TOTAL = 1920, 1080, 30, 45
    hyper = hyper_de_prueba(os.path.join(TEMPORAL, "hyper.png"), ANCHO, ALTO)
    anterior = os.path.join(TEMPORAL, "anterior.png")
    Image.new("RGB", (ANCHO, ALTO), (30, 90, 160)).save(anterior)
    formato_de_fabrica = p8_render.FORMATO_FOTOGRAMA
    try:
        t_png, f_png, s_png = renderizar("png", os.path.join(TEMPORAL, "png"),
                                         hyper, anterior, ANCHO, ALTO, FPS, TOTAL)
        t_jpg, f_jpg, s_jpg = renderizar("jpg", os.path.join(TEMPORAL, "jpg"),
                                         hyper, anterior, ANCHO, ALTO, FPS, TOTAL)
    finally:
        p8_render.FORMATO_FOTOGRAMA = formato_de_fabrica
    print(f"  (PNG {s_png:.1f} s, JPEG {s_jpg:.1f} s para {TOTAL} fotogramas)")
    comprobar("los dos clips existen", os.path.exists(t_png["clip"])
              and os.path.exists(t_jpg["clip"]))
    igual("la transicion se cuece igual en los dos",
          f_jpg["frames_transicion"], f_png["frames_transicion"])
    comprobar("y si se cuece", f_jpg["frames_transicion"] > 0, f_jpg)
    igual("los mismos fotogramas en el clip",
          fotogramas_de(t_jpg["clip"]), fotogramas_de(t_png["clip"]))
    valor = psnr(t_png["clip"], t_jpg["clip"])
    comprobar(f"y no se distinguen (PSNR {valor:.1f} dB, hace falta >= 42)",
              valor >= 42, valor)
    capturados = sorted(os.listdir(t_jpg["carpeta"]))
    comprobar("los fotogramas son .jpg",
              capturados and all(n.endswith(".jpg") for n in capturados
                                 if n.startswith("f")), capturados[:3])
    with Image.open(p8_render.fotograma(t_jpg["carpeta"], 1)) as im:
        igual("y el de la transicion es JPEG de verdad, no un PNG renombrado",
              im.format, "JPEG")
    comprobar("sin temporales de la transicion",
              not any(".tmp" in n for n in capturados))
    with Image.open(t_jpg["ultimo"]) as im:
        igual("el ultimo del plano es PNG", im.format, "PNG")
    # LA VELOCIDAD NO SE COMPRUEBA AQUI: depende de la imagen. Con esta, que
    # el PNG comprime facil, salen parecidos; con un plano de verdad del
    # estudio (S010 de un video real, 1920x1080, 60 fotogramas) el plano paso
    # de 87,7 s a 19,1 s el 01-10-2026. Para medirlo: pasos/medir_render.py.

shutil.rmtree(TEMPORAL, ignore_errors=True)
print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("CAPTURA OK: todas las comprobaciones pasan")
