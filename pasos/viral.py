"""
EDICION VIRAL DE SHORTS: el guion y el montaje pensados para retener.

Un short no se ve: se DECIDE si se sigue viendo, cada segundo. Esto junta en un
interruptor («Edicion viral», encendido por defecto en los shorts) lo que el
estudio ya sabia hacer, empujado a su extremo, y dos cosas nuevas encima:

  GUION     el mini guion viral (GUION): gancho en el primer segundo y medio,
            una pregunta abierta que se cierra al final, un giro o dato nuevo
            cada 3-5 s, frases cortas, y un final que enlaza con el principio
            para que se vuelva a ver.
  MONTAJE   planos de 1 a 2,5 s, subtitulos enormes palabra a palabra,
            transiciones de golpe (latigazo, destello, zoom, glitch) y mas
            efectos en los cortes (PARAMS).
  ENCIMA    al terminar el MP4 (`pulir`): un TEXTO GANCHO grande los primeros
            2 s y una BARRA DE PROGRESO arriba, que es lo que mas retiene en
            vertical. Lo mismo sirve para un recorte gratis.

El texto del gancho lo escribe Claude (suscripcion, gratis) a partir del guion;
si no contesta, se usan las primeras palabras de la narracion.
"""
import glob
import os
import re
import subprocess
import tempfile

try:
    from . import cli_claude, medios
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import medios

GUION = (
    "EDICION VIRAL (manda sobre lo anterior en estructura, no en tono): "
    "1) GANCHO en la primera frase, que se diga en menos de 2 segundos y en menos de "
    "10 palabras: una afirmacion que choca, una pregunta que pica o un contraste. "
    "Nunca empieces saludando ni presentando el tema. "
    "2) Abre una pregunta y promete la respuesta al final, para que se quede. "
    "3) Cada 3-5 segundos, algo nuevo: un dato, un giro, un 'pero', una pregunta. "
    "Nada de relleno ni de frases de transicion. "
    "4) Frases cortas (menos de 12 palabras), en presente, directas a quien mira. "
    "5) La respuesta llega justo antes del final, y la ultima frase enlaza con la "
    "primera para que el video se vuelva a ver en bucle. Sin despedida.")

#: Los mandos de siempre, a fondo. Paso -> params.
PARAMS = {
    "assets": {"min_s": 1.0, "max_s": 2.5},
    "callouts": {"subtitulo_tam": "enorme"},
    "render": {"transiciones": ["whip-pan", "flash-through-white", "cinematic-zoom",
                                "glitch", "chromatic-split"],
               "duracion_transicion": 0.25, "efectos_db": 3.0, "viral": True},
}

#: El color de la barra: el violeta de Mind.
COLOR_BARRA = "0xA78BFA"
#: LA BARRA DE PROGRESO, APAGADA DE FABRICA (04-10-2026: «arriba del video
#: aparece una linea morada corriendo, quiero quitarla»). Se enciende por video
#: con `barra=True` (la casilla «Barra de progreso» de la pantalla).
BARRA_POR_DEFECTO = str(os.environ.get("ESTUDIO_BARRA_VIRAL", "")).strip().lower() in ("1", "true", "si")
SEGUNDOS_GANCHO = 2.2

INSTRUCCION_GANCHO = """Escribe el TEXTO GANCHO que va en grande en pantalla \
durante los 2 primeros segundos de este short vertical: de 2 a 5 palabras, en \
{idioma}, en MAYUSCULAS, que piquen la curiosidad sin repetir lo que dice la voz. \
Contesta SOLO el texto, sin comillas.

GUION:
{guion}
"""


def gancho_de(guion, idioma="español", cwd=None):
    """El texto gancho de un short (2-5 palabras en mayusculas)."""
    texto = " ".join(str(guion or "").split())
    try:
        respuesta, _ = cli_claude.ejecutar(
            INSTRUCCION_GANCHO.format(idioma=idioma, guion=texto[:3000]),
            modelo="sonnet", esfuerzo="low", cwd=cwd or tempfile.gettempdir(),
            tiempo_max_s=120, extra=["--no-session-persistence"], para="el gancho del short")
        limpio = " ".join(str(respuesta or "").replace('"', "").replace("«", "").replace("»", "").split())
        if 1 <= len(limpio.split()) <= 7:
            return limpio.upper()[:60]
    except Exception:                                       # noqa: BLE001
        pass
    primera = re.split(r"[.!?¿¡]", texto)[0] if texto else ""
    return " ".join(primera.split()[:5]).upper()[:60]


def fuente_negrita():
    carpeta = os.environ.get("ESTUDIO_FUENTES") or ""
    for nombre in ("arialbd.ttf", "verdanab.ttf", "segoeuib.ttf", "tahomabd.ttf"):
        ruta = os.path.join(carpeta, nombre)
        if carpeta and os.path.exists(ruta):
            return ruta
    candidatas = glob.glob("/usr/share/fonts/**/*Bold*.ttf", recursive=True)
    return candidatas[0] if candidatas else ""


def _partir(texto, por_linea=14):
    """El gancho en 1-2 lineas, para que quepa grande en vertical."""
    palabras, lineas, actual = texto.split(), [], ""
    for p in palabras:
        if actual and len(actual) + 1 + len(p) > por_linea:
            lineas.append(actual)
            actual = p
        else:
            actual = f"{actual} {p}".strip()
    if actual:
        lineas.append(actual)
    return "\n".join(lineas[:3])


def pulir(entrada, salida, gancho="", segundos_gancho=SEGUNDOS_GANCHO, barra=None):
    """El MP4 con la barra de progreso y el texto gancho encima. -> salida"""
    duracion = medios.duracion_media(entrada) or 0
    if duracion <= 0:
        raise RuntimeError(f"no se puede medir {entrada}")
    sonda = subprocess.run(
        [medios.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height", "-of", "csv=p=0:s=x", entrada],
        capture_output=True, text=True, timeout=60, **medios.SIN_VENTANA)
    try:
        ancho, alto = [int(x) for x in sonda.stdout.strip().split("x")[:2]]
    except ValueError:
        ancho, alto = 1080, 1920
    if barra is None:
        barra = BARRA_POR_DEFECTO
    if barra:
        alto_barra = max(6, int(alto * 0.007))
        filtros = [f"color=c={COLOR_BARRA}:s={ancho}x{alto_barra}:r=30[barra]",
                   f"[0:v][barra]overlay=x='-w+W*t/{duracion:.3f}':y=0:shortest=1[v1]"]
    else:
        filtros = ["[0:v]null[v1]"]
    fichero_texto = ""
    fuente = fuente_negrita()
    if gancho and fuente:
        fichero_texto = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                                    encoding="utf-8").name
        with open(fichero_texto, "w", encoding="utf-8") as fh:
            fh.write(_partir(gancho))
        tam = int(min(ancho, alto) * 0.085)
        filtros.append(
            f"[v1]drawtext=fontfile='{fuente}':textfile='{fichero_texto}':"
            f"fontsize={tam}:fontcolor=white:line_spacing={int(tam * 0.18)}:"
            f"box=1:boxcolor=black@0.62:boxborderw={int(tam * 0.4)}:"
            f"x=(w-text_w)/2:y=h*0.17:enable='between(t,0,{segundos_gancho})'[v]")
    else:
        filtros.append("[v1]null[v]")
    orden = [medios.ffmpeg(), "-y", "-loglevel", "error", "-i", entrada,
             "-filter_complex", ";".join(filtros), "-map", "[v]", "-map", "0:a?",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "copy", "-movflags", "+faststart", salida]
    try:
        proceso = subprocess.run(orden, capture_output=True, text=True, timeout=1800,
                                 **medios.SIN_VENTANA)
    finally:
        if fichero_texto and os.path.exists(fichero_texto):
            os.remove(fichero_texto)
    if proceso.returncode != 0 or not os.path.exists(salida):
        raise RuntimeError(f"no se ha podido pulir el short: {proceso.stderr[-400:]}")
    return salida


def pulir_en_sitio(mp4, gancho="", barra=None):
    """Como `pulir`, sustituyendo el fichero (a traves de un temporal)."""
    base, ext = os.path.splitext(mp4)
    temporal = f"{base}.viral{ext}"
    pulir(mp4, temporal, gancho, barra=barra)
    os.replace(temporal, mp4)
    return mp4
