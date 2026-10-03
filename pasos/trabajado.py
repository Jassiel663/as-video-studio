"""
EL SHORT TRABAJADO: subes TU video corto y el estudio lo edita.

Para lo que no sale del estudio --un video grabado con el movil, una charla, un
clip propio--: se sube, se elige el estilo (sus colores visten los
subtitulos) y el estudio hace lo que haria un editor de shorts:

  1. TRANSCRIBE palabra a palabra, en el propio servidor (faster-whisper,
     modelo «small», gratis).
  2. DECIDE QUE SE QUEDA: Claude (suscripcion) lee la transcripcion con sus
     tiempos y elige los tramos buenos --fuera silencios, muletillas,
     repeticiones y lo que no aporta--, empieza por la frase mas potente como
     gancho, respeta la duracion pedida y escribe el texto gancho. Si Claude no
     contesta, se quitan solo los silencios.
  3. MONTA: corta y empalma los tramos con un PUNCH-IN alterno (un plano normal,
     el siguiente acercado) para que los cortes no se noten y den ritmo; pasa a
     vertical 1080x1920 (pantalla completa o con fondo desenfocado).
  4. AUDIO: filtro de graves, limpieza de ruido y volumen de redes (-14 LUFS).
  5. SUBTITULOS grandes palabra a palabra, la palabra que suena en el color de
     acento del estilo.
  6. EDICION VIRAL encima (pasos/viral.py): texto gancho y barra de progreso.

Todo gratis (CPU del servidor y suscripcion de Claude). Se guarda en
datos/trabajados/<id>/ con el original, el resultado y su ficha.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

try:
    from . import cli_claude, medios, presets_canal, viral
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import medios
    import presets_canal
    import viral

CARPETA = os.environ.get("ESTUDIO_TRABAJADOS") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "trabajados")
MODELOS = os.environ.get("ESTUDIO_MODELOS") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "modelos")
ANCHO, ALTO = 1080, 1920
ACERCADO = 1.12          # el punch-in de los tramos impares
_EN_MARCHA = set()
_CANDADO = threading.Lock()
_MODELO = {}

INSTRUCCION = """Eres editor de shorts virales. Te paso la transcripcion de un \
video grabado, palabra a palabra con su segundo. Elige QUE SE QUEDA para un \
short de como mucho {maximo} segundos que retenga hasta el final.

Reglas: quita silencios, muletillas («eh», «este», «o sea»), frases repetidas o \
empezadas dos veces, y lo que no aporta. Los tramos van EN EL ORDEN ORIGINAL, \
salvo el primero: puedes empezar por la frase mas potente (el gancho) aunque \
este mas adelante, y despues seguir en orden. Corta siempre entre palabras, \
nunca a mitad. Cada tramo de al menos 1 segundo.

{indicaciones}
TRANSCRIPCION ([segundo] palabra):
{palabras}

Contesta SOLO este JSON:
{{"tramos": [[inicio_s, fin_s], ...], "gancho": "<texto en pantalla de 2-5 palabras, \
MAYUSCULAS, en el idioma del video>", "titulo": "<titulo corto para el short>"}}
"""


def _ruta(ident, *partes):
    return os.path.join(CARPETA, re.sub(r"[^A-Za-z0-9_-]", "_", str(ident))[:40], *partes)


def leer(ident):
    d = medios.leer_json(_ruta(ident, "ficha.json"), {}) or {}
    if d.get("estado") == "trabajando" and ident not in _EN_MARCHA:
        d["estado"] = "error"
        d["error"] = "se corto (el estudio se reinicio); vuelve a editarlo"
    return d


def listar():
    if not os.path.isdir(CARPETA):
        return []
    salida = [leer(n) for n in os.listdir(CARPETA) if os.path.isdir(os.path.join(CARPETA, n))]
    return sorted([d for d in salida if d], key=lambda d: d.get("creado", ""), reverse=True)


def borrar(ident):
    ruta = _ruta(ident)
    if not os.path.isdir(ruta):
        raise ValueError("ese short no existe")
    shutil.rmtree(ruta)


def _guardar(ident, datos):
    medios.escribir_json(_ruta(ident, "ficha.json"), datos)


def _ffmpeg(orden, que, timeout=1800):
    p = subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error"] + orden,
                       capture_output=True, text=True, timeout=timeout, **medios.SIN_VENTANA)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg no pudo {que}: {p.stderr[-400:]}")


def transcribir(wav, idioma=None):
    """Palabras con su tiempo. -> ([{"p", "i", "f"}], idioma)"""
    from faster_whisper import WhisperModel
    if "small" not in _MODELO:
        _MODELO["small"] = WhisperModel("small", device="cpu", compute_type="int8",
                                        download_root=MODELOS)
    # EL AUDIO VA YA DECODIFICADO (float32 a 16 kHz) y no como fichero: el lector
    # de faster-whisper usa PyAV, y la version que trae no casa con su llamada
    # (`metadata_errors`, 03-10-2026). ffmpeg lo hace igual y ya esta aqui.
    import numpy
    crudo = subprocess.run([medios.ffmpeg(), "-loglevel", "error", "-i", wav, "-f", "f32le",
                            "-ac", "1", "-ar", "16000", "-"], capture_output=True, timeout=600,
                           **medios.SIN_VENTANA).stdout
    audio = numpy.frombuffer(crudo, dtype=numpy.float32)
    segmentos, info = _MODELO["small"].transcribe(audio, language=idioma, word_timestamps=True,
                                                  vad_filter=True)
    palabras = []
    for seg in segmentos:
        for w in seg.words or []:
            texto = w.word.strip()
            if texto:
                palabras.append({"p": texto, "i": round(w.start, 2), "f": round(w.end, 2)})
    return palabras, info.language


def tramos_por_silencio(palabras, maximo, hueco=0.55):
    """Sin Claude: los tramos de habla seguida, hasta llenar `maximo`."""
    tramos = []
    for w in palabras:
        if tramos and w["i"] - tramos[-1][1] <= hueco:
            tramos[-1][1] = w["f"]
        else:
            tramos.append([w["i"], w["f"]])
    salida, total = [], 0.0
    for a, b in tramos:
        if b - a < 0.3:
            continue
        if total + (b - a) > maximo:
            b = a + max(0.0, maximo - total)
            if b - a < 0.8:
                break
        salida.append([round(max(0.0, a - 0.08), 2), round(b + 0.12, 2)])
        total += b - a
        if total >= maximo:
            break
    return salida


def _plan(palabras, maximo, indicaciones=""):
    texto = "\n".join(f"[{w['i']:.2f}] {w['p']}" for w in palabras)[:40000]
    try:
        respuesta, _ = cli_claude.ejecutar(
            INSTRUCCION.format(maximo=int(maximo), palabras=texto,
                               indicaciones=(f"LO QUE PIDE EL CREADOR: {indicaciones}\n" if indicaciones else "")),
            modelo="sonnet", esfuerzo="medium", cwd=tempfile.gettempdir(), tiempo_max_s=300,
            extra=["--no-session-persistence"], para="editar un short")
        encaje = re.search(r"\{.*\}", respuesta or "", re.S)
        datos = json.loads(encaje.group(0)) if encaje else {}
        tramos = [[float(a), float(b)] for a, b in datos.get("tramos") or [] if float(b) - float(a) >= 0.5]
        if tramos:
            return tramos, str(datos.get("gancho") or ""), str(datos.get("titulo") or ""), True
    except Exception:                                       # noqa: BLE001
        pass
    return tramos_por_silencio(palabras, maximo), "", "", False


def _ajustar(tramos, palabras, maximo):
    """Los bordes a las palabras (sin cortar ninguna) y el total al maximo."""
    salida, total = [], 0.0
    for a, b in tramos:
        dentro = [w for w in palabras if w["f"] > a and w["i"] < b]
        if dentro:
            a, b = min(a, dentro[0]["i"]) - 0.06, max(b, dentro[-1]["f"]) + 0.1
        a = max(0.0, a)
        # SIN SOLAPES: al ensanchar los bordes a las palabras, dos tramos
        # seguidos del original podian pisarse unas decimas (y repetir sonido)
        if salida and salida[-1][0] <= a < salida[-1][1]:
            a = salida[-1][1]
        if b - a < 0.3:
            continue
        if total + (b - a) > maximo + 1.0:
            b = a + (maximo - total)
            if b - a < 0.8:
                break
        salida.append([round(a, 2), round(b, 2)])
        total += b - a
    return salida


def _paleta(estilo_id):
    ficha = presets_canal.leer(estilo_id) if estilo_id else None
    paleta = (((ficha or {}).get("datos") or {}).get("rotulos") or {}).get("paleta") or {}
    return {"texto": paleta.get("texto") or "#ffffff", "acento": paleta.get("acento") or "#a78bfa",
            "sombra": paleta.get("sombra") or "#000000"}


def _ass_color(hexa):
    hexa = str(hexa or "#ffffff").lstrip("#")
    if len(hexa) != 6:
        hexa = "ffffff"
    return f"&H00{hexa[4:6]}{hexa[2:4]}{hexa[0:2]}".upper()


def _t(segundos):
    s = max(0.0, segundos)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def subtitulos_ass(palabras_nuevas, paleta, destino, por_bloque=3):
    """Subtitulos grandes de 2-3 palabras, la que suena en el color de acento."""
    fuente = os.path.splitext(os.path.basename(viral.fuente_negrita() or "Arial"))[0] or "Arial"
    cab = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n"
           "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
           "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
           "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
           f"Style: Sub,{'Arial' if 'arial' in fuente.lower() else fuente},86,{_ass_color(paleta['texto'])},"
           f"{_ass_color(paleta['acento'])},{_ass_color(paleta['sombra'])},&H64000000,-1,0,0,0,100,100,0,0,1,7,3,2,70,70,560,1\n\n"
           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lineas = []
    for n in range(0, len(palabras_nuevas), por_bloque):
        bloque = palabras_nuevas[n:n + por_bloque]
        for k, w in enumerate(bloque):
            fin = bloque[k + 1]["i"] if k + 1 < len(bloque) else w["f"] + 0.15
            texto = " ".join((r"{\c" + _ass_color(paleta["acento"]) + r"&}" + x["p"].upper() + r"{\r}")
                             if j == k else x["p"].upper() for j, x in enumerate(bloque))
            lineas.append(f"Dialogue: 0,{_t(w['i'])},{_t(max(fin, w['i'] + 0.05))},Sub,,0,0,0,,{texto}")
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(cab + "\n".join(lineas) + "\n")
    return destino


def _remapear(palabras, tramos):
    """Las palabras en el tiempo NUEVO (tras cortar y empalmar los tramos)."""
    salida, base = [], 0.0
    for a, b in tramos:
        for w in palabras:
            if w["i"] >= a - 0.01 and w["f"] <= b + 0.01:
                salida.append({"p": w["p"], "i": round(base + w["i"] - a, 2), "f": round(base + w["f"] - a, 2)})
        base += b - a
    return salida


def _montar(original, tramos, destino, encuadre, mejorar_audio, zooms):
    """Corta, empalma y pasa a vertical. Cada tramo sale ya a 1080x1920: a
    pantalla completa (recortando los lados) o entero delante de su propio
    fondo desenfocado. Los impares, con el punch-in."""
    partes, n = [], len(tramos)
    for k, (a, b) in enumerate(tramos):
        zoom = (f",scale=iw*{ACERCADO}:ih*{ACERCADO},crop=iw/{ACERCADO}:ih/{ACERCADO}"
                if zooms and k % 2 else "")
        corte = f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS{zoom}"
        if encuadre == "centro":
            partes.append(f"{corte},scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
                          f"crop={ANCHO}:{ALTO},setsar=1,fps=30[v{k}]")
        else:
            partes.append(f"{corte},split[p{k}][q{k}];"
                          f"[p{k}]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=increase,"
                          f"crop={ANCHO}:{ALTO},boxblur=25:2,eq=brightness=-0.15[f{k}];"
                          f"[q{k}]scale={ANCHO}:{ALTO}:force_original_aspect_ratio=decrease[d{k}];"
                          f"[f{k}][d{k}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[v{k}]")
        partes.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{k}]")
    union = "".join(f"[v{k}][a{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[v][ac]"
    audio = ("[ac]highpass=f=80,afftdn=nf=-25,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
             if mejorar_audio else "[ac]anull[a]")
    filtro = ";".join(partes) + ";" + union + ";" + audio
    _ffmpeg(["-i", original, "-filter_complex", filtro, "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-ar", "48000", destino], "montar los tramos")


def editar(ruta_subida, nombre="", estilo_id="", maximo=60, encuadre="fondo", subtitulos=True,
           mejorar_audio=True, zooms=True, viral_on=True, indicaciones=""):
    """Lanza la edicion en un hilo. -> ficha (trabajando)"""
    if not os.path.exists(ruta_subida):
        raise ValueError("no ha llegado el video")
    ident = time.strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:5]
    os.makedirs(_ruta(ident), exist_ok=True)
    ext = os.path.splitext(ruta_subida)[1].lower() or ".mp4"
    original = _ruta(ident, f"original{ext}")
    shutil.move(ruta_subida, original)
    maximo = max(10, min(int(maximo or 60), 180))
    ficha = {"id": ident, "nombre": " ".join(str(nombre or "Mi short").split())[:80], "estilo": estilo_id,
             "estado": "trabajando", "paso": "preparando", "progreso": 0.02, "creado": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "opciones": {"maximo": maximo, "encuadre": encuadre, "subtitulos": bool(subtitulos),
                          "mejorar_audio": bool(mejorar_audio), "zooms": bool(zooms), "viral": bool(viral_on)}}
    _guardar(ident, ficha)
    with _CANDADO:
        _EN_MARCHA.add(ident)

    def paso(texto, progreso):
        ficha.update(paso=texto, progreso=progreso)
        _guardar(ident, ficha)

    def correr():
        try:
            paso("escuchando el audio (transcripcion)", 0.08)
            wav = _ruta(ident, "audio.wav")
            _ffmpeg(["-i", original, "-vn", "-ac", "1", "-ar", "16000", wav], "sacar el audio")
            palabras, idioma = transcribir(wav)
            os.remove(wav)
            if not palabras:
                raise ValueError("no se ha entendido ninguna palabra en el video")
            paso("decidiendo qué se queda (Claude)", 0.35)
            tramos, gancho, titulo, por_claude = _plan(palabras, maximo, indicaciones)
            tramos = _ajustar(tramos, palabras, maximo)
            if not tramos:
                raise ValueError("no ha quedado ningun tramo que montar")
            paso("montando los cortes, el vertical y el audio", 0.55)
            montado = _ruta(ident, "montado.mp4")
            _montar(original, tramos, montado, encuadre, mejorar_audio, zooms)
            final = _ruta(ident, "final.mp4")
            nuevas = _remapear(palabras, tramos)
            if subtitulos:
                paso("poniendo los subtitulos", 0.75)
                ass = subtitulos_ass(nuevas, _paleta(estilo_id), _ruta(ident, "subs.ass"))
                fuentes = os.environ.get("ESTUDIO_FUENTES") or ""
                filtro = f"ass='{ass}'" + (f":fontsdir='{fuentes}'" if fuentes else "")
                _ffmpeg(["-i", montado, "-vf", filtro, "-c:v", "libx264", "-preset", "veryfast",
                         "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", final], "poner los subtitulos")
                os.remove(montado)
            else:
                os.replace(montado, final)
            if viral_on:
                paso("gancho y barra de progreso", 0.9)
                viral.pulir_en_sitio(final, (gancho or viral.gancho_de(" ".join(w["p"] for w in nuevas))).upper()[:60])
            ficha.update(estado="listo", paso="listo", progreso=1.0, idioma=idioma,
                         duracion=round(medios.duracion_media(final) or 0, 1),
                         original_s=round(medios.duracion_media(original) or 0, 1),
                         tramos=tramos, gancho=gancho, titulo=titulo or ficha["nombre"],
                         elegido_por="claude" if por_claude else "silencios",
                         texto=" ".join(w["p"] for w in nuevas)[:4000])
            _guardar(ident, ficha)
        except Exception as fallo:                          # noqa: BLE001
            ficha.update(estado="error", error=f"{type(fallo).__name__}: {str(fallo)[:400]}")
            _guardar(ident, ficha)
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(ident)

    threading.Thread(target=correr, daemon=True, name=f"trabajado-{ident}").start()
    return ficha
