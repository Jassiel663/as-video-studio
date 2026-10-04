"""
El encuadre que sigue la cara (pasos/caras.py y clipping._montar_cara), con un
video de verdad: una cara a la DERECHA los 3 primeros segundos y a la
IZQUIERDA los 3 siguientes, sobre un apaisado de 1920x1080.

  1. centros(): encuentra la cara en cada trozo y su lado;
  2. sin cara (un trozo vacio) dice None;
  3. _montar_cara(): sale en vertical 1080x1920 con la cara en el centro de
     cada trozo, y el trozo sin cara va entero sobre el fondo desenfocado.

La cara es la foto de muestra de OpenCV (samples/data), bajada una vez.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

TEMPORAL = tempfile.mkdtemp(prefix="prueba_caras_")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2  # noqa: E402

import caras  # noqa: E402
import clipping  # noqa: E402
import medios  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def ff(*args):
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", *args], check=True, timeout=600)


try:
    foto = os.path.join(TEMPORAL, "cara.jpg")
    urllib.request.urlretrieve("https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/lena.jpg", foto)
    cara = os.path.join(TEMPORAL, "cara_p.png")
    ff("-i", foto, "-vf", "scale=420:420", cara)
    video = os.path.join(TEMPORAL, "podcast.mp4")
    # derecha (x=1350) 0-3 s, izquierda (x=150) 3-6 s, nada 6-8 s
    ff("-f", "lavfi", "-i", "color=c=0x404850:s=1920x1080:r=30:d=8", "-loop", "1", "-i", cara,
       "-f", "lavfi", "-i", "sine=frequency=220:duration=8",
       "-filter_complex", "[0:v][1:v]overlay=x='if(lt(t,3),1350,150)':y=330:enable='lt(t,6)':shortest=1[v]",
       "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "8", video)

    print("\n== donde esta la cara ==")
    cs = caras.centros(video, [[0, 3], [3, 6], [6, 8]])
    derecha = (1350 + 210) / 1920
    izquierda = (150 + 210) / 1920
    comprobar("trozo 1: la cara a la derecha", cs[0] is not None and abs(cs[0] - derecha) < 0.05, cs)
    comprobar("trozo 2: la cara a la izquierda", cs[1] is not None and abs(cs[1] - izquierda) < 0.05, cs)
    comprobar("trozo 3: sin cara, None", cs[2] is None, cs)
    f = caras.filtro_recorte(0.0, 1920, 1080)
    comprobar("el recorte no se sale del cuadro (cara pegada al borde)", "crop=608:1080:0:0" in f, f)
    f = caras.filtro_recorte(1.0, 1920, 1080)
    comprobar("ni por el otro lado", "crop=608:1080:1312:0" in f, f)

    print("\n== el montaje ==")
    destino = os.path.join(TEMPORAL, "vertical.mp4")
    clipping._montar_cara(video, [[0, 3], [3, 6], [6, 8]], destino, mejorar_audio=False, zooms=True)
    cap = cv2.VideoCapture(destino)
    comprobar("vertical 1080x1920", (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))) == (1080, 1920))

    def cara_centrada(t):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, img = cap.read()
        pequena = cv2.resize(img, (540, 960))
        encontradas = caras.caras_en(pequena)
        if not encontradas:
            return None
        x, _, w, _ = max(encontradas, key=lambda c: c[2] * c[3])
        return (x + w / 2) / 540

    for t, que in ((1.5, "derecha"), (4.5, "izquierda")):
        c = cara_centrada(t)
        comprobar(f"la cara de la {que} sale CENTRADA en vertical", c is not None and abs(c - 0.5) < 0.12, c)
    cap.set(cv2.CAP_PROP_POS_MSEC, 7000)
    ok, img = cap.read()
    arriba = img[50:300, 400:680].mean()
    comprobar("el trozo sin cara va sobre el fondo desenfocado (no recortado)", ok and arriba < 90, arriba)
    cap.release()
    comprobar("dura lo mismo (8 s)", abs(medios.duracion_media(destino) - 8) < 0.2, medios.duracion_media(destino))
finally:
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("CARAS OK: todas las comprobaciones pasan")
