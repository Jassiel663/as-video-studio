"""
Pruebas de la edicion viral (pasos/viral.py).

  1. PULIR: el MP4 sale con la misma duracion, con audio, y con la barra y el
     gancho encima (el primer fotograma cambia arriba y en el tercio superior;
     al final la barra esta llena).
  2. EL GANCHO: si Claude no contesta, las primeras palabras en mayusculas.
  3. LOS MANDOS: el guion pide gancho y bucle; el montaje, planos cortos,
     subtitulos enormes y transiciones que existen en el catalogo.
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import medios  # noqa: E402
import transiciones  # noqa: E402
import viral  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


TEMPORAL = tempfile.mkdtemp(prefix="prueba_viral_")
try:
    print("\n== los mandos ==")
    comprobar("el guion pide gancho y bucle", "GANCHO" in viral.GUION and "bucle" in viral.GUION)
    comprobar("planos cortos", viral.PARAMS["assets"]["max_s"] <= 2.5)
    comprobar("subtitulos enormes", viral.PARAMS["callouts"]["subtitulo_tam"] == "enorme")
    comprobar("las transiciones existen en el catalogo",
              all(t in transiciones.CATALOGO for t in viral.PARAMS["render"]["transiciones"]),
              viral.PARAMS["render"]["transiciones"])

    print("\n== el gancho ==")
    original = cli_claude.ejecutar

    def roto(*a, **k):
        raise RuntimeError("sin sesion")
    cli_claude.ejecutar = roto
    try:
        igual = viral.gancho_de("Nadie te cuenta esto del dinero. Y es raro.")
    finally:
        cli_claude.ejecutar = original
    comprobar("sin Claude, las primeras palabras en mayusculas", igual == "NADIE TE CUENTA ESTO DEL", igual)
    comprobar("y se parte en lineas para que quepa", "\n" in viral._partir("NADIE TE CUENTA ESTO DEL DINERO"))

    print("\n== pulir ==")
    entrada = os.path.join(TEMPORAL, "in.mp4")
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=0x202020:s=540x960:r=30:d=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", entrada],
                   check=True)
    salida = os.path.join(TEMPORAL, "out.mp4")
    viral.pulir(entrada, salida, "NADIE TE CUENTA ESTO", barra=True)
    comprobar("sale el fichero", os.path.exists(salida))
    comprobar("con la misma duracion", abs(medios.duracion_media(salida) - medios.duracion_media(entrada)) < 0.15)
    audio = subprocess.run([medios.ffprobe(), "-v", "error", "-select_streams", "a",
                            "-show_entries", "stream=codec_type", "-of", "csv=p=0", salida],
                           capture_output=True, text=True).stdout
    comprobar("y con audio", "audio" in audio)

    def fotograma(t, nombre):
        ruta = os.path.join(TEMPORAL, nombre)
        subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", "-ss", str(t), "-i", salida,
                        "-frames:v", "1", ruta], check=True)
        from PIL import Image
        return Image.open(ruta).convert("RGB")
    inicio, final = fotograma(0.5, "a.png"), fotograma(3.9, "b.png")
    comprobar("al principio sale el gancho (pixeles claros en el tercio de arriba)",
              any(max(inicio.getpixel((x, y))[0] for x in range(0, 540, 4)) > 200
                  for y in range(150, 330, 3)))
    r, g, b = final.getpixel((520, 2))
    comprobar("al final la barra esta casi llena (violeta en la esquina derecha)",
              b > 200 and r > 120, (r, g, b))
    sin_barra = os.path.join(TEMPORAL, "sin_barra.mp4")
    viral.pulir(entrada, sin_barra, "NADIE TE CUENTA ESTO")
    ruta_sb = os.path.join(TEMPORAL, "c.png")
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", "-ss", "3.9", "-i", sin_barra,
                    "-frames:v", "1", ruta_sb], check=True)
    from PIL import Image
    r2, g2, b2 = Image.open(ruta_sb).convert("RGB").getpixel((520, 2))
    comprobar("de fabrica SIN la barra morada de arriba", b2 < 80 and r2 < 80, (r2, g2, b2))
    comprobar("y el gancho ya no esta", not any(max(final.getpixel((x, y))[0] for x in range(0, 540, 4)) > 200
                                                for y in range(150, 330, 3)))
finally:
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("VIRAL OK: todas las comprobaciones pasan")
