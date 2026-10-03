"""
LA MARCA DE CADA ESTILO: marca de agua, intro y cierre. Gratis (solo ffmpeg).

Se configura por estilo (Crear › Marca) y se aplica sola al terminar:
  · el render de un video          -> video_final.mp4 al lado de video.mp4
  · un short sacado de un video    -> sobre el propio recorte
  · un short trabajado             -> sobre el propio short

EL VIDEO.MP4 NO SE TOCA. Los cortes de shorts, el previsualizador y los
capitulos del SEO van por los tiempos del plan; con una intro delante todos
se descuadrarian. Por eso la marca va a un fichero APARTE (video_final.mp4),
que es el que se ve, se descarga y se publica, y su intro se apunta
(`marca.json`) para correr los capitulos lo que dure.

Las piezas:
  agua   un logo (PNG, mejor con fondo transparente) o, sin logo, el nombre del
         canal en texto. En una esquina, con su transparencia y tamano.
  intro  la que sube la persona (un video corto) o una AUTOMATICA: el logo o
         el nombre sobre fondo oscuro con el color del estilo, 2-3 s.
  cierre el que sube o uno automatico: «¡Suscríbete!» + nombre + logo, 5 s
         (lo justo para las pantallas finales de YouTube).
En los shorts, por defecto, solo la marca de agua: una intro en un short es
perder a la gente en el primer segundo.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile

try:
    from . import medios, presets_canal, viral
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import medios
    import presets_canal
    import viral

CARPETA = os.environ.get("ESTUDIO_MARCA") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "marca")

POSICIONES = ("arriba_izquierda", "arriba_derecha", "abajo_izquierda", "abajo_derecha")
EXT_IMAGEN = (".png", ".jpg", ".jpeg", ".webp")
EXT_VIDEO = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
MAX_PIEZA_S = 20.0
FPS = 30

POR_DEFECTO = {
    "agua": {"activa": False, "posicion": "arriba_derecha", "opacidad": 0.7, "tamano": 0.12, "texto": ""},
    "intro": {"activa": False, "tipo": "auto", "texto": "", "segundos": 2.5},
    "outro": {"activa": False, "tipo": "auto", "texto": "¡Suscríbete!", "segundos": 5.0},
    "en_shorts": {"agua": True, "intro": False, "outro": False},
}


def _carpeta(estilo_id):
    return os.path.join(CARPETA, re.sub(r"[^A-Za-z0-9_-]", "_", str(estilo_id))[:80])


def _fichero(estilo_id, que):
    """La pieza subida (logo / intro / outro) que haya, o ''."""
    carpeta = _carpeta(estilo_id)
    if not os.path.isdir(carpeta):
        return ""
    for nombre in sorted(os.listdir(carpeta)):
        if os.path.splitext(nombre)[0] == que:
            return os.path.join(carpeta, nombre)
    return ""


def _nombre_canal(estilo_id):
    nombre = str((presets_canal.leer(estilo_id) or {}).get("nombre") or "").strip()
    # «Mis mil malas decisiones | Nico» -> lo de antes de la barra
    return nombre.split("|")[0].strip() or nombre


def _acento(estilo_id):
    ficha = presets_canal.leer(estilo_id) or {}
    paleta = (((ficha.get("datos") or {}).get("rotulos") or {}).get("paleta")) or {}
    color = str(paleta.get("acento") or "#a78bfa").strip()
    return color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#a78bfa"


def leer(estilo_id):
    d = json.loads(json.dumps(POR_DEFECTO))
    guardado = medios.leer_json(os.path.join(_carpeta(estilo_id), "marca.json"), {}) or {}
    for parte in d:
        if isinstance(guardado.get(parte), dict):
            d[parte].update({k: v for k, v in guardado[parte].items() if k in d[parte]})
    d["estilo"] = estilo_id
    d["nombre_canal"] = _nombre_canal(estilo_id)
    d["hay"] = {que: bool(_fichero(estilo_id, que)) for que in ("logo", "intro", "outro")}
    return d


def configurar(estilo_id, cambios):
    if not isinstance(cambios, dict):
        raise ValueError("se esperaba un objeto")
    d = leer(estilo_id)
    a, i, o, s = (cambios.get(k) or {} for k in ("agua", "intro", "outro", "en_shorts"))
    if "activa" in a:
        d["agua"]["activa"] = bool(a["activa"])
    if "posicion" in a:
        if a["posicion"] not in POSICIONES:
            raise ValueError(f"posicion desconocida: {a['posicion']}")
        d["agua"]["posicion"] = a["posicion"]
    if "opacidad" in a:
        d["agua"]["opacidad"] = min(1.0, max(0.1, float(a["opacidad"])))
    if "tamano" in a:
        d["agua"]["tamano"] = min(0.4, max(0.04, float(a["tamano"])))
    if "texto" in a:
        d["agua"]["texto"] = str(a["texto"] or "").strip()[:40]
    for parte, nuevo in (("intro", i), ("outro", o)):
        if "activa" in nuevo:
            d[parte]["activa"] = bool(nuevo["activa"])
        if "tipo" in nuevo:
            if nuevo["tipo"] not in ("auto", "subido"):
                raise ValueError("el tipo es 'auto' o 'subido'")
            d[parte]["tipo"] = nuevo["tipo"]
        if "texto" in nuevo:
            d[parte]["texto"] = str(nuevo["texto"] or "").strip()[:60]
        if "segundos" in nuevo:
            d[parte]["segundos"] = round(min(8.0, max(1.5, float(nuevo["segundos"]))), 1)
    for k in ("agua", "intro", "outro"):
        if k in s:
            d["en_shorts"][k] = bool(s[k])
    os.makedirs(_carpeta(estilo_id), exist_ok=True)
    medios.escribir_json(os.path.join(_carpeta(estilo_id), "marca.json"),
                         {k: d[k] for k in POR_DEFECTO})
    return leer(estilo_id)


def guardar_pieza(estilo_id, que, ruta_temporal, ext):
    """Guarda el logo (imagen) o la intro / el cierre (video) subidos."""
    ext = str(ext or "").lower()
    if que not in ("logo", "intro", "outro"):
        raise ValueError(f"pieza desconocida: {que}")
    if que == "logo" and ext not in EXT_IMAGEN:
        raise ValueError("el logo tiene que ser una imagen (png, jpg o webp)")
    if que != "logo" and ext not in EXT_VIDEO:
        raise ValueError("sube un video (mp4, mov, webm...)")
    carpeta = _carpeta(estilo_id)
    os.makedirs(carpeta, exist_ok=True)
    try:
        if que == "logo":
            # a PNG siempre: conserva la transparencia y ffmpeg lo lee igual
            destino = os.path.join(carpeta, "logo.png.tmp.png")
            proceso = subprocess.run(
                [medios.ffmpeg(), "-y", "-loglevel", "error", "-i", ruta_temporal,
                 "-vf", "scale='min(800,iw)':-2", "-frames:v", "1", destino],
                capture_output=True, text=True, timeout=120, **medios.SIN_VENTANA)
            if proceso.returncode != 0 or not os.path.exists(destino):
                raise ValueError("no se ha podido leer esa imagen")
            final = os.path.join(carpeta, "logo.png")
        else:
            duracion = medios.duracion_media(ruta_temporal) or 0
            if duracion <= 0:
                raise ValueError("no se ha podido leer ese video")
            if duracion > MAX_PIEZA_S:
                raise ValueError(f"la {'intro' if que == 'intro' else 'pieza de cierre'} dura "
                                 f"{duracion:.0f} s: como mucho {MAX_PIEZA_S:.0f} s")
            destino = ruta_temporal
            final = os.path.join(carpeta, que + ext)
        borrar_pieza(estilo_id, que)
        shutil.move(destino, final)
    finally:
        if os.path.exists(ruta_temporal):
            os.remove(ruta_temporal)
    if que != "logo":
        configurar(estilo_id, {que: {"tipo": "subido", "activa": True}})
    return leer(estilo_id)


def borrar_pieza(estilo_id, que):
    ruta = _fichero(estilo_id, que)
    if ruta:
        os.remove(ruta)
    if que in ("intro", "outro") and not _fichero(estilo_id, que):
        d = leer(estilo_id)
        if d[que]["tipo"] == "subido":
            configurar(estilo_id, {que: {"tipo": "auto"}})
    return leer(estilo_id)


# ------------------------------------------------------------------ aplicar

def piezas(estilo_id, short=False):
    """Lo que toca poner en este video: {'agua','intro','outro'} -> bool."""
    if not estilo_id or not presets_canal.leer(estilo_id):
        return {"agua": False, "intro": False, "outro": False}
    d = leer(estilo_id)
    salida = {}
    for parte in ("agua", "intro", "outro"):
        quiere = d[parte]["activa"] and (not short or d["en_shorts"][parte])
        if quiere and parte != "agua" and d[parte]["tipo"] == "subido" and not d["hay"][parte]:
            quiere = False
        salida[parte] = bool(quiere)
    return salida


def activa(estilo_id, short=False):
    return any(piezas(estilo_id, short).values())


def _medidas(ruta):
    sonda = subprocess.run(
        [medios.ffprobe(), "-v", "error", "-show_entries", "stream=codec_type,width,height",
         "-of", "json", ruta], capture_output=True, text=True, timeout=60, **medios.SIN_VENTANA)
    try:
        flujos = json.loads(sonda.stdout or "{}").get("streams") or []
    except ValueError:
        flujos = []
    video = next((f for f in flujos if f.get("codec_type") == "video"), {})
    return (int(video.get("width") or 1920), int(video.get("height") or 1080),
            any(f.get("codec_type") == "audio" for f in flujos))


def _escapar(texto):
    return str(texto).replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")


def _fichero_texto(texto):
    fh = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    fh.write(texto)
    fh.close()
    return fh.name


def _ffmpeg(orden, que):
    proceso = subprocess.run(orden, capture_output=True, text=True, timeout=3600, **medios.SIN_VENTANA)
    if proceso.returncode != 0:
        raise RuntimeError(f"no se ha podido hacer {que}: {proceso.stderr[-400:]}")


def generar_pieza(estilo_id, que, ancho, alto, destino):
    """La intro o el cierre AUTOMATICOS, a la medida del video. -> destino"""
    d = leer(estilo_id)
    seg = float(d[que]["segundos"])
    acento = _acento(estilo_id).lstrip("#")
    nombre = d["nombre_canal"] or "Mi canal"
    logo = _fichero(estilo_id, "logo")
    fuente = viral.fuente_negrita()
    if not fuente:
        raise RuntimeError("no hay fuente para el texto de la marca")
    corto = min(ancho, alto)
    temporales = []
    try:
        if que == "intro":
            grande = d["intro"]["texto"] or nombre
            pequeno = ""
        else:
            grande = d["outro"]["texto"] or "¡Suscríbete!"
            pequeno = nombre
        t1 = _fichero_texto(grande)
        temporales.append(t1)
        aparece = "alpha='if(lt(t,0.35),t/0.35,1)'"
        hay_logo = bool(logo)
        tam = int(corto * (0.085 if len(grande) < 18 else 0.06))
        y_centro = int(alto * 0.62) if hay_logo else int((alto - tam) / 2)
        y_texto = str(y_centro)
        # la raya del color del estilo entra desde la izquierda y se queda
        # centrada debajo del texto
        y_barra = y_centro + int(tam * (2.6 if pequeno else 1.35))
        filtros = [
            f"color=c=0x0b0b10:s={ancho}x{alto}:r={FPS}:d={seg}[fondo]",
            f"color=c=0x{acento}:s={int(ancho * 0.22)}x{max(4, int(corto * 0.012))}:r={FPS}:d={seg}[barra]",
            f"[fondo][barra]overlay=x='-w+((W+w)/2)*min(1,t/0.6)':y={y_barra}[f1]",
        ]
        actual = "f1"
        if hay_logo:
            lado = int(corto * 0.34)
            # una imagen es UN fotograma: se repite para que el fundido se vea
            filtros.append(f"movie='{_escapar(logo)}',loop=loop=-1:size=1:start=0,setpts=N/{FPS}/TB,"
                           f"scale={lado}:{lado}:force_original_aspect_ratio=decrease,"
                           f"format=rgba,fade=t=in:st=0:d=0.4:alpha=1[lg]")
            filtros.append(f"[{actual}][lg]overlay=x=(W-w)/2:y='H*0.36-h/2+(1-min(1,t/0.5))*H*0.03'"
                           f":shortest=1[f2]")
            actual = "f2"
        filtros.append(f"[{actual}]drawtext=fontfile='{_escapar(fuente)}':textfile='{_escapar(t1)}':"
                       f"fontsize={tam}:fontcolor=white:x=(w-text_w)/2:y={y_texto}:{aparece}[f3]")
        actual = "f3"
        if pequeno:
            t2 = _fichero_texto(pequeno)
            temporales.append(t2)
            filtros.append(f"[{actual}]drawtext=fontfile='{_escapar(fuente)}':textfile='{_escapar(t2)}':"
                           f"fontsize={int(tam * 0.55)}:fontcolor=0x{acento}:x=(w-text_w)/2:"
                           f"y={y_texto}+{int(tam * 1.5)}:alpha='if(lt(t,0.6),max(0,(t-0.25)/0.35),1)'[f4]")
            actual = "f4"
        filtros.append(f"[{actual}]fade=t=in:st=0:d=0.3,fade=t=out:st={max(0.1, seg - 0.4):.2f}:d=0.4,"
                       f"format=yuv420p[v]")
        _ffmpeg([medios.ffmpeg(), "-y", "-loglevel", "error",
                 "-filter_complex", ";".join(filtros),
                 "-f", "lavfi", "-t", f"{seg}", "-i", "anullsrc=r=48000:cl=stereo",
                 "-map", "[v]", "-map", "0:a", "-t", f"{seg}",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", destino],
                f"la {que} automatica")
    finally:
        for t in temporales:
            if os.path.exists(t):
                os.remove(t)
    return destino


def _filtro_agua(estilo_id, ancho, alto, entrada, salida, indice_logo):
    """El trozo de filtro que pone la marca de agua. -> (filtros, temporales)"""
    d = leer(estilo_id)
    a = d["agua"]
    corto = min(ancho, alto)
    margen = int(corto * 0.035)
    vertical = alto > ancho
    # en vertical, abajo esta la interfaz de TikTok/Shorts: se sube
    abajo = f"H-h-{int(alto * 0.2) if vertical else margen}"
    x = margen if a["posicion"].endswith("izquierda") else f"W-w-{margen}"
    y = margen if a["posicion"].startswith("arriba") else abajo
    if indice_logo is not None:
        ancho_logo = max(24, int(ancho * float(a["tamano"]) * (1.6 if vertical else 1)))
        return ([f"[{indice_logo}:v]scale={ancho_logo}:-1,format=rgba,"
                 f"colorchannelmixer=aa={float(a['opacidad']):.2f}[agua]",
                 f"[{entrada}][agua]overlay=x={x}:y={y}:shortest=1[{salida}]"], [])
    texto = a["texto"] or ("@" + re.sub(r"\s+", "", d["nombre_canal"]) if d["nombre_canal"] else "")
    fuente = viral.fuente_negrita()
    if not texto or not fuente:
        return ([f"[{entrada}]null[{salida}]"], [])
    fichero = _fichero_texto(texto)
    xt = margen if a["posicion"].endswith("izquierda") else f"w-text_w-{margen}"
    yt = margen if a["posicion"].startswith("arriba") else abajo.replace("H-h", "h-text_h")
    tam = max(14, int(corto * 0.045 * float(a["tamano"]) / 0.12))
    op = float(a["opacidad"])
    return ([f"[{entrada}]drawtext=fontfile='{_escapar(fuente)}':textfile='{_escapar(fichero)}':"
             f"fontsize={tam}:fontcolor=white@{op:.2f}:shadowcolor=black@{op * 0.6:.2f}:"
             f"shadowx=2:shadowy=2:x={xt}:y={yt}[{salida}]"], [fichero])


def aplicar(entrada, salida, estilo_id, short=False):
    """El video con la marca del estilo. -> {'intro_s', 'outro_s', 'agua'}"""
    que = piezas(estilo_id, short)
    if not any(que.values()):
        raise ValueError("este estilo no tiene marca que poner")
    ancho, alto, con_audio = _medidas(entrada)
    temporales = []
    entradas = []          # [(ruta, es_imagen)]
    try:
        info = {"intro_s": 0.0, "outro_s": 0.0, "agua": que["agua"]}

        def pieza(parte):
            if not que[parte]:
                return None
            d = leer(estilo_id)
            if d[parte]["tipo"] == "subido":
                ruta = _fichero(estilo_id, parte)
            else:
                ruta = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
                temporales.append(ruta)
                generar_pieza(estilo_id, parte, ancho, alto, ruta)
            entradas.append((ruta, False))
            dur = medios.duracion_media(ruta) or 0
            info[f"{parte}_s"] = round(dur, 3)
            return (len(entradas) - 1, dur, _medidas(ruta)[2])

        intro = pieza("intro")
        entradas.append((entrada, False))
        principal = len(entradas) - 1
        outro = pieza("outro")
        logo = _fichero(estilo_id, "logo") if que["agua"] else ""
        indice_logo = None
        if logo:
            entradas.append((logo, True))
            indice_logo = len(entradas) - 1

        normal = (f"scale={ancho}:{alto}:force_original_aspect_ratio=decrease,"
                  f"pad={ancho}:{alto}:(ow-iw)/2:(oh-ih)/2:color=black,fps={FPS},setsar=1,format=yuv420p")
        audio_normal = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
        filtros = [f"[{principal}:v]{normal}[pv]"]
        if que["agua"]:
            mas, tmp = _filtro_agua(estilo_id, ancho, alto, "pv", "pm", indice_logo)
            filtros += mas
            temporales += tmp
        else:
            filtros.append("[pv]null[pm]")
        orden_concat = []
        for n, trozo in enumerate(t for t in (intro, (principal, None, con_audio), outro) if t):
            i, dur, audio = trozo
            etiqueta_v = "pm" if i == principal else f"v{n}"
            if i != principal:
                filtros.append(f"[{i}:v]{normal}[{etiqueta_v}]")
            if audio:
                filtros.append(f"[{i}:a]{audio_normal}[a{n}]")
            else:
                d = dur if dur else (medios.duracion_media(entrada) or 0)
                filtros.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{d:.3f}[a{n}]")
            orden_concat.append(f"[{etiqueta_v}][a{n}]")
        filtros.append(f"{''.join(orden_concat)}concat=n={len(orden_concat)}:v=1:a=1[v][a]")
        orden = [medios.ffmpeg(), "-y", "-loglevel", "error"]
        for ruta, imagen in entradas:
            orden += (["-loop", "1", "-i", ruta] if imagen else ["-i", ruta])
        orden += ["-filter_complex", ";".join(filtros), "-map", "[v]", "-map", "[a]",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", salida]
        _ffmpeg(orden, "la marca")
    finally:
        for t in temporales:
            if os.path.exists(t):
                os.remove(t)
    return info


def aplicar_en_sitio(mp4, estilo_id, short=True):
    """Como `aplicar`, sustituyendo el fichero. -> info, o None si no toca."""
    if not activa(estilo_id, short):
        return None
    base, ext = os.path.splitext(mp4)
    temporal = f"{base}.marca{ext}"
    info = aplicar(mp4, temporal, estilo_id, short)
    os.replace(temporal, mp4)
    return info


def muestra(estilo_id, short=False):
    """Una imagen de prueba de la marca de agua sobre la cara del estilo. -> png"""
    ancho, alto = (720, 1280) if short else (1280, 720)
    d = leer(estilo_id)
    clave = hashlib.sha1(json.dumps([d, short, os.path.getmtime(_fichero(estilo_id, "logo"))
                                     if d["hay"]["logo"] else 0], sort_keys=True).encode()).hexdigest()[:12]
    destino = os.path.join(_carpeta(estilo_id), f"muestra_{'v' if short else 'h'}_{clave}.png")
    if os.path.exists(destino):
        return destino
    os.makedirs(_carpeta(estilo_id), exist_ok=True)
    for viejo in os.listdir(_carpeta(estilo_id)):
        if viejo.startswith(f"muestra_{'v' if short else 'h'}_"):
            os.remove(os.path.join(_carpeta(estilo_id), viejo))
    ficha = presets_canal.leer(estilo_id) or {}
    cara = ""
    try:
        cara = presets_canal.ruta_de_miniatura(ficha)
    except Exception:                                       # noqa: BLE001
        pass
    entradas = (["-i", cara] if cara and os.path.exists(cara)
                else ["-f", "lavfi", "-i", f"color=c=0x2a2a35:s={ancho}x{alto}"])
    logo = _fichero(estilo_id, "logo")
    if logo:
        entradas += ["-i", logo]
    filtros = [f"[0:v]scale={ancho}:{alto}:force_original_aspect_ratio=increase,crop={ancho}:{alto},setsar=1[base]"]
    mas, temporales = _filtro_agua(estilo_id, ancho, alto, "base", "v", 1 if logo else None)
    try:
        _ffmpeg([medios.ffmpeg(), "-y", "-loglevel", "error", *entradas,
                 "-filter_complex", ";".join(filtros + mas), "-map", "[v]", "-frames:v", "1", destino],
                "la muestra")
    finally:
        for t in temporales:
            if os.path.exists(t):
                os.remove(t)
    return destino


def muestra_pieza(estilo_id, que, short=False):
    """La intro o el cierre automaticos para verlos antes. -> mp4"""
    ancho, alto = (720, 1280) if short else (1280, 720)
    d = leer(estilo_id)
    clave = hashlib.sha1(json.dumps([d, que, short, os.path.getmtime(_fichero(estilo_id, "logo"))
                                     if d["hay"]["logo"] else 0], sort_keys=True).encode()).hexdigest()[:12]
    destino = os.path.join(_carpeta(estilo_id), f"muestra_{que}_{'v' if short else 'h'}_{clave}.mp4")
    if not os.path.exists(destino):
        os.makedirs(_carpeta(estilo_id), exist_ok=True)
        for viejo in os.listdir(_carpeta(estilo_id)):
            if viejo.startswith(f"muestra_{que}_{'v' if short else 'h'}_"):
                os.remove(os.path.join(_carpeta(estilo_id), viejo))
        generar_pieza(estilo_id, que, ancho, alto, destino)
    return destino
