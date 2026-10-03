"""
Pruebas de la marca de cada estilo (pasos/marca.py), con ffmpeg de verdad.

  1. Sin configurar no hay marca; los ajustes se validan y se guardan.
  2. Marca de agua en TEXTO y con LOGO: el video dura lo mismo, mide lo mismo
     y la esquina elegida cambia (la contraria no).
  3. Intro y cierre AUTOMATICOS: el video crece lo que duran, con audio.
  4. Intro SUBIDA (vertical y muda) sobre un video horizontal sin audio: se
     ajusta al tamano y el resultado sigue teniendo audio.
  5. Piezas que no valen: una intro de 25 s, un logo que no es imagen.
  6. En los shorts, por defecto, solo la marca de agua; en sitio.
  7. Las muestras (imagen y video) salen.
"""
import os
import shutil
import subprocess
import sys
import tempfile

TEMPORAL = tempfile.mkdtemp(prefix="prueba_marca_")
os.environ["ESTUDIO_MARCA"] = os.path.join(TEMPORAL, "marca")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image  # noqa: E402

import marca  # noqa: E402
import medios  # noqa: E402
import presets_canal  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def ff(*args):
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", *args], check=True, timeout=300)


def video(nombre, ancho, alto, segundos, audio=True):
    ruta = os.path.join(TEMPORAL, nombre)
    entradas = ["-f", "lavfi", "-i", f"color=c=0x336699:s={ancho}x{alto}:r=30:d={segundos}"]
    if audio:
        entradas += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={segundos}"]
    ff(*entradas, "-c:v", "libx264", "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if audio else []), "-shortest", ruta)
    return ruta


def fotograma(ruta, t):
    png = ruta + f".{t}.png"
    ff("-ss", str(t), "-i", ruta, "-frames:v", "1", png)
    return Image.open(png).convert("RGB")


def media(img, caja):
    trozo = img.crop(caja).resize((1, 1), Image.BILINEAR)
    return trozo.getpixel((0, 0))


def distinto(a, b, umbral=25):
    return sum(abs(x - y) for x, y in zip(a, b)) > umbral


def medidas(ruta):
    return marca._medidas(ruta)


original_leer = presets_canal.leer
try:
    presets_canal.leer = lambda pid: {"id": pid, "nombre": "Leones Salvajes | Nico", "tipo": "canal",
                                      "datos": {"rotulos": {"paleta": {"acento": "#ff3366"}}}}
    presets_canal.ruta_de_miniatura = lambda ficha: ""
    hor = video("h.mp4", 1280, 720, 4)

    print("\n== configurar ==")
    comprobar("sin configurar no hay marca", not marca.activa("leon") and not marca.activa("leon", True))
    d = marca.leer("leon")
    comprobar("el nombre del canal sin la barra", d["nombre_canal"] == "Leones Salvajes", d["nombre_canal"])
    try:
        marca.configurar("leon", {"agua": {"posicion": "en_medio"}})
        comprobar("una posicion rara se rechaza", False)
    except ValueError:
        comprobar("una posicion rara se rechaza", True)
    comprobar("por defecto arriba a la derecha (abajo estan los subtitulos)",
              marca.leer("leon")["agua"]["posicion"] == "arriba_derecha")
    d = marca.configurar("leon", {"agua": {"activa": True, "opacidad": 5, "tamano": 0.15,
                                           "posicion": "abajo_derecha"}})
    comprobar("se acota la opacidad", d["agua"]["opacidad"] == 1.0)
    comprobar("y se guarda", marca.leer("leon")["agua"]["activa"] is True)

    print("\n== marca de agua en texto ==")
    out = os.path.join(TEMPORAL, "agua_texto.mp4")
    info = marca.aplicar(hor, out, "leon")
    comprobar("sin intro ni cierre", info == {"intro_s": 0.0, "outro_s": 0.0, "agua": True}, info)
    comprobar("dura lo mismo", abs(medios.duracion_media(out) - 4) < 0.15, medios.duracion_media(out))
    comprobar("mide lo mismo y tiene audio", medidas(out) == (1280, 720, True), medidas(out))
    a, b = fotograma(hor, 1), fotograma(out, 1)
    comprobar("la esquina de abajo a la derecha cambia", distinto(media(a, (1000, 640, 1270, 712)), media(b, (1000, 640, 1270, 712))))
    comprobar("la de arriba a la izquierda no", not distinto(media(a, (0, 0, 300, 120)), media(b, (0, 0, 300, 120))))

    print("\n== con logo ==")
    logo_src = os.path.join(TEMPORAL, "milogo.webp")
    ff("-f", "lavfi", "-i", "color=c=yellow:s=300x300", "-frames:v", "1", logo_src)
    d = marca.guardar_pieza("leon", "logo", logo_src, ".webp")
    comprobar("el logo se guarda (como PNG)", d["hay"]["logo"] and marca._fichero("leon", "logo").endswith("logo.png"))
    marca.configurar("leon", {"agua": {"posicion": "arriba_izquierda", "opacidad": 1}})
    out = os.path.join(TEMPORAL, "agua_logo.mp4")
    marca.aplicar(hor, out, "leon")
    b = fotograma(out, 2)
    esquina = media(b, (50, 50, 120, 120))
    comprobar("el logo amarillo esta arriba a la izquierda", esquina[0] > 180 and esquina[1] > 180 and esquina[2] < 120, esquina)
    comprobar("y abajo a la derecha no", not distinto(media(a, (1000, 600, 1270, 712)), media(b, (1000, 600, 1270, 712))))

    print("\n== intro y cierre automaticos ==")
    marca.configurar("leon", {"intro": {"activa": True, "segundos": 2.5}, "outro": {"activa": True, "segundos": 5}})
    out = os.path.join(TEMPORAL, "completo.mp4")
    info = marca.aplicar(hor, out, "leon")
    comprobar("apunta lo que dura la intro", abs(info["intro_s"] - 2.5) < 0.15 and abs(info["outro_s"] - 5) < 0.15, info)
    comprobar("el video crece lo que duran", abs(medios.duracion_media(out) - 11.5) < 0.3, medios.duracion_media(out))
    comprobar("misma medida y con audio", medidas(out) == (1280, 720, True), medidas(out))
    intro = fotograma(out, 1.2)
    comprobar("la intro es oscura (no es el video)", sum(media(intro, (0, 0, 200, 100))) < 80)
    comprobar("el video empieza despues", not distinto(media(fotograma(out, 3.5), (500, 300, 700, 400)), media(a, (500, 300, 700, 400))))

    print("\n== intro subida ==")
    vert = video("intro_v.mp4", 720, 1280, 3, audio=False)
    marca.guardar_pieza("leon", "intro", vert, ".mp4")
    d = marca.leer("leon")
    comprobar("subirla la pone como «la mia» y activa", d["intro"]["tipo"] == "subido" and d["intro"]["activa"] and d["hay"]["intro"])
    mudo = video("mudo.mp4", 1280, 720, 4, audio=False)
    out = os.path.join(TEMPORAL, "subida.mp4")
    info = marca.aplicar(mudo, out, "leon")
    comprobar("dura 3 + 4 + 5", abs(medios.duracion_media(out) - 12) < 0.3, medios.duracion_media(out))
    comprobar("se ajusta al tamano del video y lleva audio", medidas(out) == (1280, 720, True), medidas(out))
    lado = media(fotograma(out, 1), (0, 300, 200, 400))
    comprobar("la vertical va con bandas negras a los lados", sum(lado) < 30, lado)
    marca.borrar_pieza("leon", "intro")
    comprobar("quitarla vuelve a la automatica", marca.leer("leon")["intro"]["tipo"] == "auto")

    print("\n== piezas que no valen ==")
    largo = video("largo.mp4", 640, 360, 25, audio=False)
    try:
        marca.guardar_pieza("leon", "outro", largo, ".mp4")
        comprobar("una intro de 25 s se rechaza", False)
    except ValueError as fallo:
        comprobar("una pieza de 25 s se rechaza", "20" in str(fallo), str(fallo))
    falso = os.path.join(TEMPORAL, "logo.png")
    open(falso, "w").write("no soy una imagen")
    try:
        marca.guardar_pieza("leon", "logo", falso, ".png")
        comprobar("un logo roto se rechaza", False)
    except ValueError:
        comprobar("un logo roto se rechaza (y el bueno sigue)", marca.leer("leon")["hay"]["logo"])

    print("\n== shorts ==")
    comprobar("en shorts solo la marca de agua", marca.piezas("leon", True) == {"agua": True, "intro": False, "outro": False})
    corto = video("short.mp4", 720, 1280, 3)
    info = marca.aplicar_en_sitio(corto, "leon", True)
    comprobar("en sitio, sin intro", info and info["intro_s"] == 0 and abs(medios.duracion_media(corto) - 3) < 0.15, info)
    comprobar("el short sigue vertical", medidas(corto)[:2] == (720, 1280))
    marca.configurar("leon", {"agua": {"activa": False}, "intro": {"activa": False}, "outro": {"activa": False}})
    comprobar("todo apagado: no toca nada", marca.aplicar_en_sitio(corto, "leon", True) is None)
    comprobar("un estilo que no existe no lleva marca", (presets_canal.__setattr__("leer", lambda pid: None)
                                                         or not marca.activa("nadie")))
    presets_canal.leer = lambda pid: {"id": pid, "nombre": "Leones Salvajes", "tipo": "canal"}

    print("\n== muestras ==")
    marca.configurar("leon", {"agua": {"activa": True}})
    png = marca.muestra("leon")
    comprobar("muestra horizontal", Image.open(png).size == (1280, 720))
    comprobar("muestra vertical", Image.open(marca.muestra("leon", True)).size == (720, 1280))
    comprobar("se reutiliza si nada cambia", marca.muestra("leon") == png)
    mp4 = marca.muestra_pieza("leon", "outro")
    comprobar("muestra del cierre", abs(medios.duracion_media(mp4) - 5) < 0.2 and medidas(mp4)[:2] == (1280, 720))
    marca.borrar_pieza("leon", "logo")
    comprobar("sin logo la intro automatica sale igual", os.path.exists(marca.muestra_pieza("leon", "intro", True)))
finally:
    presets_canal.leer = original_leer
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("MARCA OK: todas las comprobaciones pasan")
