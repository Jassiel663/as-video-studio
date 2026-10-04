"""
El fondo de los clips (pasos/fondo.py), con audio de verdad y sin red:

  1. MEZCLAR: la musica suena donde no hay voz y BAJA donde la hay (sidechain);
     el video se copia tal cual y dura lo mismo.
  2. Los efectos se colocan en su segundo.
  3. VESTIR: con el banco de mentira, apunta el tema (titulo, artista,
     licencia) y cuantos efectos; sin red ni claves, el clip sale igual y dice
     por que.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy

TEMPORAL = tempfile.mkdtemp(prefix="prueba_fondo_")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fondo  # noqa: E402
import medios  # noqa: E402
import sonido  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def ff(*args):
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", *args], check=True, timeout=300)


def rms(ruta, desde, hasta, filtro=""):
    crudo = subprocess.run([medios.ffmpeg(), "-loglevel", "error", "-ss", str(desde), "-t", str(hasta - desde),
                            "-i", ruta, "-vn", "-ac", "1", "-ar", "16000"] + (["-af", filtro] if filtro else [])
                           + ["-f", "f32le", "-"], capture_output=True, timeout=60).stdout
    m = numpy.frombuffer(crudo, dtype=numpy.float32)
    return float(numpy.sqrt(numpy.mean(m ** 2))) if len(m) else 0.0


try:
    # «voz»: un tono de 300 Hz los 3 primeros segundos y silencio despues
    video = os.path.join(TEMPORAL, "clip.mp4")
    ff("-f", "lavfi", "-i", "color=c=0x334455:s=360x640:r=30:d=6",
       "-f", "lavfi", "-i", "sine=frequency=300:duration=3,apad=whole_dur=6,volume=0.5",
       "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video)
    tema = os.path.join(TEMPORAL, "tema.mp3")
    ff("-f", "lavfi", "-i", "sine=frequency=1500:duration=4", "-c:a", "libmp3lame", tema)
    golpe = os.path.join(TEMPORAL, "whoosh.wav")
    ff("-f", "lavfi", "-i", "anoisesrc=d=0.3:a=0.6", golpe)

    print("\n== mezclar ==")
    salida = os.path.join(TEMPORAL, "out.mp4")
    fondo.mezclar(video, salida, tema, [(4.5, golpe, 0.5)])
    comprobar("dura lo mismo", abs(medios.duracion_media(salida) - 6) < 0.15, medios.duracion_media(salida))
    sonda = subprocess.run([medios.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=nb_frames", "-of", "csv=p=0", salida], capture_output=True, text=True).stdout.strip()
    comprobar("el video se copia tal cual (mismos fotogramas)", sonda in ("180", "181"), sonda)
    alto = "highpass=f=1200"                                # solo la musica (1500 Hz), sin la «voz» (300 Hz)
    con_voz, sin_voz = rms(salida, 0.8, 2.6, alto), rms(salida, 3.4, 4.2, alto)
    comprobar("la musica suena donde no hay voz", sin_voz > 0.01, sin_voz)
    comprobar("y baja (al menos a la mitad) mientras hay voz", con_voz < sin_voz * 0.5, (con_voz, sin_voz))
    comprobar("el efecto suena en su segundo", rms(salida, 4.45, 4.75) > rms(salida, 3.9, 4.2) * 1.3)
    comprobar("la voz sigue ahi (casi igual que antes)", rms(salida, 0.5, 2.5, "lowpass=f=600") > rms(video, 0.5, 2.5, "lowpass=f=600") * 0.8)

    print("\n== vestir ==")
    original_musica, original_efectos = fondo.musica, fondo.efectos
    fondo.musica = lambda animo, semilla="": (tema, {"titulo": "Tema", "artista": "Alguien", "licencia": "cc-by"})
    fondo.efectos = lambda papel, cuantos=4: [golpe]
    copia = os.path.join(TEMPORAL, "copia.mp4")
    shutil.copyfile(video, copia)
    info = fondo.vestir_en_sitio(copia, "motivacional", [2.0, 4.0], semilla="x")
    comprobar("apunta el tema para el credito", info["musica"] == {"titulo": "Tema", "artista": "Alguien",
                                                                  "licencia": "cc-by", "animo": "motivacional",
                                                                  "comercial": True}, info)
    comprobar("un whoosh por corte y el golpe del gancho", info["efectos"] == 3, info)

    def sin_red(*a, **k):
        raise RuntimeError("sin red")

    fondo.musica, fondo.efectos = sin_red, sin_red
    shutil.copyfile(video, copia)
    info = fondo.vestir_en_sitio(copia, "motivacional", [2.0])
    comprobar("sin red, el clip sale igual y dice por que", "sin musica" in info["aviso"] and "sin efectos" in info["aviso"]
              and abs(medios.duracion_media(copia) - 6) < 0.15, info)
    fondo.musica, fondo.efectos = original_musica, original_efectos
    try:
        fondo.musica("reggaeton_de_marte")
        comprobar("un animo que no existe se rechaza", False)
    except ValueError:
        comprobar("un animo que no existe se rechaza", True)
finally:
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("FONDO OK: todas las comprobaciones pasan")
