"""
CLIPPING: de un video largo (de YouTube o subido) salen N clips de 30-60 s,
editados y listos para publicar. Gratis (Whisper + Claude + ffmpeg).

    1. el video llega SUBIDO (y, si viene de YouTube, con su FICHA: el
       .info.json de yt-dlp, que trae titulo, descripcion, capitulos, la
       grafica de «lo mas repetido» y los comentarios). Bajarlo de YouTube no
       se hace en el servidor: YouTube bloquea las IP de los centros de datos
       («confirma que no eres un robot»); se baja en el PC de la persona.
    2. se transcribe entero (Whisper, palabra a palabra).
    3. Claude elige los N mejores momentos con todo junto: lo que se dice, los
       picos de «lo mas repetido», los minutos que cita la gente en los
       comentarios, los capitulos y el titulo. Cada clip: inicio, fin, gancho,
       titulo, por que, puntuacion y hashtags. Sin Claude, los picos de la
       grafica o los tramos con mas habla.
    4. cada clip se ajusta a las palabras (no corta ninguna, acaba en final de
       frase si puede) y a la duracion pedida, sin solaparse con otro.
    5. se monta con la edicion del short trabajado (pasos/trabajado.py):
       vertical, punch-in alterno cada ~5 s, audio limpio, subtitulos con el
       ESTILO elegido (CapCut: clasico, pop, caja, minimal), gancho y barra de
       progreso (pasos/viral.py) y la marca del estilo (pasos/marca.py).
    6. cada clip terminado se guarda como un SHORT TRABAJADO, asi que hereda su
       pantalla de publicar (textos, mini estudio del momento y subida a las
       cuentas del estilo). Al lado queda la version LIMPIA (sin subtitulos ni
       textos) y sus subtitulos en .srt, para retocarlo en CapCut.

La persona confirma al empezar que el video es suyo o que tiene permiso para
hacer clips (campanas de clipping): queda apuntado en la ficha.
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
    from . import cli_claude, marca, medios, presets_canal, trabajado, viral
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import marca
    import medios
    import presets_canal
    import trabajado
    import viral

CARPETA = os.environ.get("ESTUDIO_CLIPPING") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "clipping")
ESTILOS_SUB = ("clasico", "pop", "caja", "minimal")
MAX_CLIPS = 10
TROZO_S = 4.5            # cada cuanto alterna el punch-in dentro de un clip
_EN_MARCHA = set()
_CANDADO = threading.Lock()
_UNO_A_LA_VEZ = threading.Semaphore(1)      # Whisper y ffmpeg comen CPU: de uno en uno

INSTRUCCION = """Eres un clipper profesional: de videos largos sacas los clips que mas \
visualizaciones consiguen en Shorts, TikTok y Reels. Elige los {n} MEJORES momentos de \
este video para clips de entre {min_s} y {max_s} segundos.

Un buen clip: empieza FUERTE (una frase que engancha en el primer segundo, sin contexto \
previo necesario), tiene una idea completa (historia, dato, opinion polemica, chiste, \
momento emocional o consejo) y acaba en un cierre o un remate, nunca a mitad de frase. \
Prioriza lo que la gente ya ha senalado: los picos de «lo mas repetido» y los minutos \
que citan los comentarios. Los clips no se pisan entre si.

{indicaciones}
DATOS DEL VIDEO
Titulo: {titulo}
Canal: {canal}
Descripcion: {descripcion}
Capitulos: {capitulos}
Picos de «lo mas repetido» (inicio-fin en segundos, intensidad 0-1): {picos}
Minutos citados en comentarios (segundo: veces): {citados}

TRANSCRIPCION ([segundo] frase):
{transcripcion}

Contesta SOLO este JSON (los segundos, numeros; idioma de los textos = el del video):
{{"clips": [{{"inicio": 0.0, "fin": 0.0, "titulo": "<titulo corto y potente>", \
"gancho": "<texto en pantalla de 2-5 palabras, MAYUSCULAS>", "porque": "<por que funciona, \
1 frase>", "puntuacion": 1-10, "hashtags": ["#..."]}}]}}
"""


# ------------------------------------------------------------------ fichas

def _ruta(ident, *partes):
    return os.path.join(CARPETA, re.sub(r"[^A-Za-z0-9_-]", "_", str(ident))[:40], *partes)


def leer(ident):
    d = medios.leer_json(_ruta(ident, "ficha.json"), {}) or {}
    if d.get("estado") == "trabajando" and ident not in _EN_MARCHA:
        d["estado"] = "error"
        d["error"] = "se corto (el estudio se reinicio); pulsa «Reintentar»"
    return d


def listar():
    if not os.path.isdir(CARPETA):
        return []
    salida = [leer(n) for n in os.listdir(CARPETA) if os.path.isdir(os.path.join(CARPETA, n))]
    return sorted([d for d in salida if d.get("id")], key=lambda d: d.get("creado", ""), reverse=True)


def _guardar(ident, datos):
    medios.escribir_json(_ruta(ident, "ficha.json"), datos)


def borrar(ident):
    ficha = leer(ident)
    if not ficha:
        raise ValueError("ese clipping no existe")
    if ident in _EN_MARCHA:
        raise ValueError("todavia se esta haciendo: espera a que acabe")
    shutil.rmtree(_ruta(ident))


# ------------------------------------------------------------- las senales

def _seg(texto):
    """'1:02:03' o '2:35' -> segundos"""
    partes = [int(x) for x in texto.split(":")]
    s = 0
    for p in partes:
        s = s * 60 + p
    return s


def senales(info, duracion=0):
    """Lo que dice la ficha de YouTube sobre donde esta lo bueno."""
    info = info or {}
    picos = []
    mapa = [h for h in info.get("heatmap") or [] if isinstance(h, dict)]
    if mapa:
        # los tramos de la grafica por encima de lo normal, de mas a menos
        valores = sorted(float(h.get("value") or 0) for h in mapa)
        umbral = valores[int(len(valores) * 0.8)] if valores else 0
        for h in sorted(mapa, key=lambda h: -float(h.get("value") or 0)):
            if float(h.get("value") or 0) >= umbral and len(picos) < 15:
                picos.append([round(float(h.get("start_time") or 0)), round(float(h.get("end_time") or 0)),
                              round(float(h.get("value") or 0), 2)])
    citados = {}
    for c in info.get("comments") or []:
        texto = str((c or {}).get("text") or "")
        peso = 1 + min(50, int((c or {}).get("like_count") or 0)) / 10
        for marca_t in re.findall(r"(?<!\d)(\d{1,2}:\d{2}(?::\d{2})?)(?!\d)", texto):
            s = _seg(marca_t)
            if not duracion or s <= duracion:
                citados[s] = round(citados.get(s, 0) + peso, 1)
    citados = dict(sorted(citados.items(), key=lambda kv: -kv[1])[:20])
    capitulos = [[round(float(c.get("start_time") or 0)), str(c.get("title") or "")]
                 for c in info.get("chapters") or [] if isinstance(c, dict)]
    return {"picos": picos, "citados": citados, "capitulos": capitulos,
            "titulo": str(info.get("title") or ""), "canal": str(info.get("channel") or info.get("uploader") or ""),
            "descripcion": str(info.get("description") or "")[:1500],
            "vistas": info.get("view_count"), "url": info.get("webpage_url") or ""}


def _frases(palabras, max_s=8.0):
    """Las palabras en frases con su segundo, para el prompt."""
    lineas, actual, inicio = [], [], None
    for w in palabras:
        if inicio is None:
            inicio = w["i"]
        actual.append(w["p"])
        if re.search(r"[.!?…]$", w["p"]) or w["f"] - inicio >= max_s:
            lineas.append(f"[{inicio:.0f}] {' '.join(actual)}")
            actual, inicio = [], None
    if actual:
        lineas.append(f"[{inicio:.0f}] {' '.join(actual)}")
    return lineas


# ---------------------------------------------------------------- elegir

def _elegir_claude(palabras, sen, n, min_s, max_s, indicaciones=""):
    transcripcion = "\n".join(_frases(palabras))
    if len(transcripcion) > 90000:                         # videos muy largos: se recorta el medio
        transcripcion = transcripcion[:60000] + "\n[...]\n" + transcripcion[-30000:]
    instruccion = INSTRUCCION.format(
        n=n, min_s=min_s, max_s=max_s,
        indicaciones=(f"LO QUE PIDE EL CREADOR: {indicaciones}\n" if indicaciones else ""),
        titulo=sen["titulo"] or "(desconocido)", canal=sen["canal"] or "(desconocido)",
        descripcion=sen["descripcion"] or "(sin descripcion)",
        capitulos=json.dumps(sen["capitulos"], ensure_ascii=False) if sen["capitulos"] else "(ninguno)",
        picos=json.dumps(sen["picos"]) if sen["picos"] else "(no hay datos)",
        citados=json.dumps(sen["citados"]) if sen["citados"] else "(no hay datos)",
        transcripcion=transcripcion)
    respuesta, _ = cli_claude.ejecutar(instruccion, modelo="sonnet", esfuerzo="medium",
                                       cwd=tempfile.gettempdir(), tiempo_max_s=900,
                                       extra=["--no-session-persistence"], para="elegir los clips")
    encaje = re.search(r"\{.*\}", respuesta or "", re.S)
    datos = json.loads(encaje.group(0)) if encaje else {}
    clips = []
    for c in datos.get("clips") or []:
        try:
            clips.append({"inicio": float(c["inicio"]), "fin": float(c["fin"]),
                          "titulo": str(c.get("titulo") or "")[:100], "gancho": str(c.get("gancho") or "")[:60],
                          "porque": str(c.get("porque") or "")[:300],
                          "puntuacion": max(1, min(10, int(float(c.get("puntuacion") or 5)))),
                          "hashtags": [str(h)[:40] for h in (c.get("hashtags") or [])][:8]})
        except (KeyError, TypeError, ValueError):
            continue
    return clips


def _elegir_sin_claude(palabras, sen, n, min_s, max_s):
    """Los picos de la grafica, o las ventanas con mas habla."""
    # ventanas del MINIMO, centradas en cada pico: dos picos cercanos no se
    # pisan y `ajustar` las alarga hasta un final de frase
    objetivo = min_s
    candidatos = []
    for a, b, v in sen["picos"]:
        centro = (a + b) / 2
        candidatos.append((v, centro - objetivo / 2))
    if not candidatos and palabras:
        total = palabras[-1]["f"]
        paso = max(objetivo, total / max(1, n * 3))
        t = 0.0
        while t + objetivo <= total:
            dentro = sum(1 for w in palabras if t <= w["i"] < t + objetivo)
            candidatos.append((dentro, t))
            t += paso
    candidatos.sort(key=lambda x: -x[0])
    return [{"inicio": max(0.0, t), "fin": max(0.0, t) + objetivo, "titulo": "", "gancho": "",
             "porque": "pico de «lo mas repetido»" if sen["picos"] else "tramo con mas habla",
             "puntuacion": 5, "hashtags": []} for _, t in candidatos[: n * 2]]


def ajustar(clip, palabras, min_s, max_s):
    """Los bordes a las palabras y la duracion a [min_s, max_s]. -> (a, b) o None"""
    if not palabras:
        return None
    a, b = clip["inicio"], clip["fin"]
    primeras = [w for w in palabras if w["f"] > a - 0.3]
    if not primeras:
        return None
    k0 = palabras.index(primeras[0])
    a = max(0.0, palabras[k0]["i"] - 0.1)
    # el final: la ultima palabra que acaba antes de b (+0,5); y si se queda
    # corto, se alarga palabra a palabra hasta el minimo
    k1 = k0
    while k1 + 1 < len(palabras) and palabras[k1 + 1]["f"] <= b + 0.5 and palabras[k1 + 1]["f"] - a <= max_s:
        k1 += 1
    while palabras[k1]["f"] - a < min_s and k1 + 1 < len(palabras) and palabras[k1 + 1]["f"] - a <= max_s:
        k1 += 1
    # mejor acabar en final de frase si hay uno en los ultimos segundos
    for k in range(k1, k0, -1):
        if palabras[k]["f"] - a < min_s:
            break
        if re.search(r"[.!?…]$", palabras[k]["p"]):
            k1 = k
            break
    b = palabras[k1]["f"] + 0.25
    if b - a < min(min_s, 8):
        return None
    return round(a, 2), round(min(b, a + max_s + 0.5), 2)


def elegir(palabras, sen, n, min_s, max_s, indicaciones=""):
    """Los N clips, ajustados y sin solaparse. -> (clips, por_claude)"""
    por_claude = True
    try:
        crudos = _elegir_claude(palabras, sen, n, min_s, max_s, indicaciones)
    except Exception:                                       # noqa: BLE001
        crudos = []
    if not crudos:
        por_claude = False
        crudos = _elegir_sin_claude(palabras, sen, n, min_s, max_s)
    elegidos = []
    for c in sorted(crudos, key=lambda c: -c["puntuacion"]):
        borde = ajustar(c, palabras, min_s, max_s)
        if not borde:
            continue
        a, b = borde
        if any(min(b, e["fin"]) - max(a, e["inicio"]) > 1.0 for e in elegidos):
            continue
        elegidos.append(dict(c, inicio=a, fin=b))
        if len(elegidos) >= n:
            break
    elegidos.sort(key=lambda c: c["inicio"])
    for k, c in enumerate(elegidos, 1):
        c["n"] = k
    return elegidos, por_claude


# --------------------------------------------------------------- montar

def trozos(a, b, palabras, cada=TROZO_S):
    """El clip [a, b] en trozos seguidos de ~`cada` s, cortando entre palabras:
    el punch-in alterna de uno a otro (cortes rapidos sin perder audio)."""
    cortes = [a]
    for w in palabras:
        if a < w["i"] < b and w["i"] - cortes[-1] >= cada and b - w["i"] >= 1.5:
            cortes.append(round(w["i"] - 0.03, 2))
    cortes.append(b)
    return [[cortes[k], cortes[k + 1]] for k in range(len(cortes) - 1)]


def _ass(palabras, paleta, destino, estilo):
    """Subtitulos con el estilo elegido (a lo CapCut)."""
    if estilo == "clasico" or estilo not in ESTILOS_SUB:
        return trabajado.subtitulos_ass(palabras, paleta, destino)
    color = trabajado._ass_color
    fuente = os.path.splitext(os.path.basename(viral.fuente_negrita() or "Arial"))[0] or "Arial"
    fuente = "Arial" if "arial" in fuente.lower() else fuente
    if estilo == "pop":
        tam, por, borde, caja, mayus = 104, 2, 8, 1, True
    elif estilo == "caja":
        tam, por, borde, caja, mayus = 80, 3, 14, 3, True
    else:                                                   # minimal
        tam, por, borde, caja, mayus = 64, 5, 2, 1, False
    fondo = "&H5A000000" if estilo == "caja" else "&H64000000"
    cab = ("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 2\n\n"
           "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
           "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
           "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
           f"Style: Sub,{fuente},{tam},{color(paleta['texto'])},{color(paleta['acento'])},"
           f"{color(paleta['sombra']) if caja == 1 else fondo},{fondo},{-1 if estilo != 'minimal' else 0},0,0,0,"
           f"100,100,0,0,{caja},{borde},{3 if estilo != 'caja' else 0},2,70,70,560,1\n\n"
           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
    lineas = []
    for n in range(0, len(palabras), por):
        bloque = palabras[n:n + por]
        for k, w in enumerate(bloque):
            fin = bloque[k + 1]["i"] if k + 1 < len(bloque) else w["f"] + 0.15
            palabra = (lambda x: x["p"].upper() if mayus else x["p"])
            if estilo == "minimal":
                if k:
                    continue                                # una linea por bloque, sin resaltar
                fin = bloque[-1]["f"] + 0.15
                texto = " ".join(palabra(x) for x in bloque)
            else:
                texto = " ".join((r"{\c" + color(paleta["acento"]) + r"&}" + palabra(x) + r"{\r}")
                                 if j == k else palabra(x) for j, x in enumerate(bloque))
                if estilo == "pop" and k == 0:
                    texto = r"{\fscx70\fscy70\t(0,90,\fscx108\fscy108)\t(90,160,\fscx100\fscy100)}" + texto
            lineas.append(f"Dialogue: 0,{trabajado._t(w['i'])},{trabajado._t(max(fin, w['i'] + 0.05))},Sub,,0,0,0,,{texto}")
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write(cab + "\n".join(lineas) + "\n")
    return destino


def _srt(palabras, destino, por=6):
    def t(s):
        s = max(0.0, s)
        return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d},{int(round(s % 1 * 1000)) % 1000:03d}"
    trozos_srt = []
    for k, n in enumerate(range(0, len(palabras), por), 1):
        bloque = palabras[n:n + por]
        trozos_srt.append(f"{k}\n{t(bloque[0]['i'])} --> {t(bloque[-1]['f'] + 0.1)}\n{' '.join(w['p'] for w in bloque)}\n")
    with open(destino, "w", encoding="utf-8") as fh:
        fh.write("\n".join(trozos_srt))
    return destino


def montar_clip(ident, clip, palabras, opciones, estilo_id, idioma):
    """Un clip editado y guardado como short trabajado. -> id del trabajado"""
    original = _original(ident)
    carpeta = _ruta(ident, "clips", str(clip["n"]))
    os.makedirs(carpeta, exist_ok=True)
    a, b = clip["inicio"], clip["fin"]
    tramos = trozos(a, b, palabras)
    limpio = os.path.join(carpeta, "limpio.mp4")
    trabajado._montar(original, tramos, limpio, opciones["encuadre"], opciones["mejorar_audio"], opciones["zooms"])
    nuevas = trabajado._remapear(palabras, tramos)
    _srt(nuevas, os.path.join(carpeta, "subtitulos.srt"))
    final = os.path.join(carpeta, "final.mp4")
    if opciones["subtitulos"] and nuevas:
        ass = _ass(nuevas, trabajado._paleta(estilo_id), os.path.join(carpeta, "subs.ass"), opciones["estilo_sub"])
        fuentes = os.environ.get("ESTUDIO_FUENTES") or ""
        filtro = f"ass='{ass}'" + (f":fontsdir='{fuentes}'" if fuentes else "")
        trabajado._ffmpeg(["-i", limpio, "-vf", filtro, "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy", final], "poner los subtitulos")
    else:
        shutil.copyfile(limpio, final)
    if opciones["viral"]:
        gancho = (clip.get("gancho") or viral.gancho_de(" ".join(w["p"] for w in nuevas))).upper()[:60]
        viral.pulir_en_sitio(final, gancho)
    aviso = ""
    if estilo_id and marca.activa(estilo_id, True):
        try:
            marca.aplicar_en_sitio(final, estilo_id, True)
        except Exception as fallo:                          # noqa: BLE001
            aviso = f"la marca no se ha podido poner: {str(fallo)[:200]}"
    # COMO SHORT TRABAJADO: hereda su pantalla de publicar
    tid = clip.get("trabajado") or f"clip_{ident[-16:]}_{clip['n']}"
    destino_t = trabajado._ruta(tid)
    os.makedirs(destino_t, exist_ok=True)
    shutil.copyfile(final, os.path.join(destino_t, "final.mp4"))
    texto = " ".join(w["p"] for w in nuevas)
    previa = trabajado.leer(tid) or {}
    trabajado._guardar(tid, {
        "id": tid, "nombre": clip.get("titulo") or f"Clip {clip['n']}", "estilo": estilo_id,
        "estado": "listo", "paso": "listo", "progreso": 1.0,
        "creado": previa.get("creado") or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "idioma": idioma, "duracion": round(medios.duracion_media(final) or 0, 1),
        "titulo": clip.get("titulo") or f"Clip {clip['n']}", "gancho": clip.get("gancho") or "",
        "texto": texto[:4000], "origen": "clipping", "clipping": ident, "tramos": tramos,
        "hashtags": clip.get("hashtags") or [], "aviso_marca": aviso,
        "opciones": {"maximo": round(b - a), "encuadre": opciones["encuadre"]}})
    os.remove(final)
    return tid


def _original(ident):
    carpeta = _ruta(ident)
    for nombre in os.listdir(carpeta):
        if nombre.startswith("original"):
            return os.path.join(carpeta, nombre)
    raise ValueError("no esta el video original")


# ----------------------------------------------------------------- lanzar

def opciones_de(datos):
    datos = datos or {}
    n = max(1, min(MAX_CLIPS, int(datos.get("n") or 3)))
    min_s = max(10, min(90, int(datos.get("min_s") or 30)))
    max_s = max(min_s + 5, min(180, int(datos.get("max_s") or 60)))
    estilo_sub = datos.get("estilo_sub") if datos.get("estilo_sub") in ESTILOS_SUB else "pop"
    si = lambda clave, defecto=True: str(datos.get(clave, defecto)).strip().lower() not in ("0", "false", "no", "")
    return {"n": n, "min_s": min_s, "max_s": max_s, "estilo_sub": estilo_sub,
            "encuadre": "centro" if datos.get("encuadre") == "centro" else "fondo",
            "subtitulos": si("subtitulos"), "viral": si("viral"), "mejorar_audio": si("mejorar_audio"),
            "zooms": si("zooms"), "indicaciones": str(datos.get("indicaciones") or "")[:500]}


def crear(ruta_video, nombre="", estilo_id="", datos=None, ruta_info="", permiso=False, url=""):
    """Guarda el video (y su ficha de YouTube) y lanza el clipping. -> ficha"""
    if not permiso:
        raise ValueError("marca la casilla: el video es tuyo o tienes permiso para hacer clips")
    if not os.path.exists(ruta_video):
        raise ValueError("no ha llegado el video")
    ident = time.strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:5]
    os.makedirs(_ruta(ident), exist_ok=True)
    ext = os.path.splitext(ruta_video)[1].lower() or ".mp4"
    shutil.move(ruta_video, _ruta(ident, f"original{ext}"))
    info = {}
    if ruta_info and os.path.exists(ruta_info):
        try:
            with open(ruta_info, encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            info = {}
        os.remove(ruta_info)
    sen = senales(info)
    if sen["url"] or url:
        sen["url"] = sen["url"] or url
    medios.escribir_json(_ruta(ident, "senales.json"), sen)
    ficha = {"id": ident, "nombre": " ".join(str(nombre or sen["titulo"] or "Mi video").split())[:90],
             "estilo": estilo_id, "url": sen["url"], "permiso": True,
             "permiso_fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "con_ficha": bool(info), "picos": len(sen["picos"]), "citados": len(sen["citados"]),
             "estado": "trabajando", "paso": "preparando", "progreso": 0.02,
             "creado": time.strftime("%Y-%m-%dT%H:%M:%S"), "opciones": opciones_de(datos), "clips": []}
    _guardar(ident, ficha)
    _lanzar(ident)
    return ficha


def reintentar(ident):
    ficha = leer(ident)
    if not ficha:
        raise ValueError("ese clipping no existe")
    if ident in _EN_MARCHA:
        return ficha
    ficha.update(estado="trabajando", error="", paso="retomando", progreso=0.02)
    _guardar(ident, ficha)
    _lanzar(ident)
    return ficha


def _lanzar(ident):
    with _CANDADO:
        if ident in _EN_MARCHA:
            return
        _EN_MARCHA.add(ident)

    def correr():
        ficha = leer(ident)

        def paso(texto, progreso):
            ficha.update(paso=texto, progreso=round(progreso, 3))
            _guardar(ident, ficha)

        try:
            with _UNO_A_LA_VEZ:
                op = ficha["opciones"]
                sen = medios.leer_json(_ruta(ident, "senales.json"), {}) or senales({})
                cache = _ruta(ident, "palabras.json")
                guardadas = medios.leer_json(cache, {}) or {}
                if guardadas.get("palabras"):
                    palabras, idioma = guardadas["palabras"], guardadas.get("idioma") or "es"
                else:
                    paso("escuchando el video entero (transcripción)", 0.05)
                    wav = _ruta(ident, "audio.wav")
                    trabajado._ffmpeg(["-i", _original(ident), "-vn", "-ac", "1", "-ar", "16000", wav],
                                      "sacar el audio", timeout=3600)
                    palabras, idioma = trabajado.transcribir(wav)
                    os.remove(wav)
                    if not palabras:
                        raise ValueError("no se ha entendido ninguna palabra en el video")
                    medios.escribir_json(cache, {"palabras": palabras, "idioma": idioma})
                ficha["idioma"] = idioma
                if not ficha.get("clips"):
                    paso("buscando los mejores momentos (Claude)", 0.35)
                    clips, por_claude = elegir(palabras, sen, op["n"], op["min_s"], op["max_s"], op["indicaciones"])
                    if not clips:
                        raise ValueError("no han salido clips: prueba con otra duración o menos clips")
                    for c in clips:
                        c["estado"] = "pendiente"
                    ficha.update(clips=clips, elegido_por="claude" if por_claude else "grafica")
                    _guardar(ident, ficha)
                total = len(ficha["clips"])
                for k, clip in enumerate(ficha["clips"]):
                    if clip.get("estado") == "listo":
                        continue
                    paso(f"editando el clip {k + 1} de {total}", 0.45 + 0.5 * k / total)
                    clip["estado"] = "editando"
                    _guardar(ident, ficha)
                    try:
                        clip["trabajado"] = montar_clip(ident, clip, palabras, op, ficha.get("estilo") or "", idioma)
                        clip.update(estado="listo", error="")
                    except Exception as fallo:              # noqa: BLE001
                        clip.update(estado="error", error=str(fallo)[:300])
                    _guardar(ident, ficha)
            hechos = sum(1 for c in ficha["clips"] if c.get("estado") == "listo")
            ficha.update(estado="listo" if hechos else "error", paso="listo", progreso=1.0,
                         error="" if hechos else "no se ha podido editar ningun clip")
            _guardar(ident, ficha)
        except Exception as fallo:                          # noqa: BLE001
            ficha.update(estado="error", error=f"{type(fallo).__name__}: {str(fallo)[:400]}")
            _guardar(ident, ficha)
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(ident)

    threading.Thread(target=correr, daemon=True, name=f"clipping-{ident}").start()


def rehacer_clip(ident, n, inicio=None, fin=None):
    """Mueve el inicio o el fin de un clip y lo vuelve a editar."""
    ficha = leer(ident)
    clip = next((c for c in ficha.get("clips") or [] if c.get("n") == int(n)), None)
    if not clip:
        raise ValueError("ese clip no existe")
    if ident in _EN_MARCHA:
        raise ValueError("espera a que acabe lo que se esta haciendo")
    palabras = (medios.leer_json(_ruta(ident, "palabras.json"), {}) or {}).get("palabras") or []
    op = ficha["opciones"]
    nuevo = dict(clip, inicio=float(inicio if inicio is not None else clip["inicio"]),
                 fin=float(fin if fin is not None else clip["fin"]))
    if nuevo["fin"] - nuevo["inicio"] < 5:
        raise ValueError("el clip tiene que durar al menos 5 segundos")
    borde = ajustar(nuevo, palabras, min(op["min_s"], nuevo["fin"] - nuevo["inicio"]),
                    max(op["max_s"], nuevo["fin"] - nuevo["inicio"]))
    if not borde:
        raise ValueError("ahi no hay habla suficiente para un clip")
    clip.update(inicio=borde[0], fin=borde[1], estado="pendiente")
    ficha.update(estado="trabajando", paso="re-editando un clip", progreso=0.5)
    _guardar(ident, ficha)
    _lanzar(ident)
    return ficha


def ruta_descarga(ident, n, que):
    """El clip limpio (para CapCut) o sus subtitulos .srt."""
    nombre = {"limpio": "limpio.mp4", "srt": "subtitulos.srt"}.get(que)
    ruta = _ruta(ident, "clips", str(int(n)), nombre) if nombre else ""
    if not ruta or not os.path.exists(ruta):
        raise ValueError("todavia no esta")
    return ruta
