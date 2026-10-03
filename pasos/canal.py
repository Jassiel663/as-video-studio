"""
EL TALLER DEL CANAL: personajes, lugares y objetos FIJOS de un estilo.

Un estilo sabe como se dibuja, pero el reparto lo inventaba cada video: el
catalogo (catalogo_visual.py) leia el guion y describia de nuevo al
protagonista, y el «Nico» de un video no era el del siguiente. Aqui se crean una
vez, con su hoja dibujada en el estilo del canal, y entran en todos los videos
de ese estilo:

  personajes  hoja de personaje (bustos arriba, cuerpo entero abajo), la misma
              que dibuja p6_assets para su reparto (`_prompt_reparto`)
  lugares     una imagen de referencia del sitio (la oficina, la casa)
  objetos     una hoja del objeto (un coche, una mascota de peluche, un logo)

COMO SE CREA: quien lo pide escribe la idea en su idioma («un chico de 25 anos,
despeinado, con sudadera verde»), y opcionalmente sube una foto o un dibujo.
Claude (suscripcion, sin coste) la convierte en la descripcion visual
permanente en ingles que leen los prompts, y saca las palabras con las que el
guion lo nombrara. Despues se dibuja la hoja con las referencias del estilo
(~0,07-0,15 $ en calidad media).

COMO ENTRA EN LOS VIDEOS (ver app.py y p6_assets.py):
  - al deducir el catalogo de un video de este estilo, se le dice a Claude que
    estos existen y con que id, y despues se fusionan en el reparto y los sitios
    con su descripcion fija;
  - en assets, un personaje u objeto del canal NO se vuelve a dibujar: se copia
    su hoja (0 $), y un lugar del canal se adjunta como referencia a cada plano
    que ocurre alli.

Se guarda fuera del preset (datos/canal/<estilo>.json y sus imagenes al lado),
para no tocar la maquinaria de presets: un estilo se puede editar o duplicar
sin arrastrar ni romper esto.
"""
import base64
import io
import json
import os
import re
import tempfile
import threading
import time

try:
    from . import cli_claude, medios, p6_assets, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import medios
    import p6_assets
    import presets_canal

CARPETA = os.environ.get("ESTUDIO_CANAL") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "canal")

TIPOS = ("personajes", "lugares", "objetos")

#: EL TALLER LIBRE: personajes, lugares y objetos creados DESDE CERO, sin
#: estilo. Llevan su propio «aspecto» (como se dibujan) escrito por quien los
#: crea, y despues se pueden PASAR a un estilo, donde se redibujan en el estilo
#: de ese canal usando la hoja libre como referencia de identidad.
LIBRE = "_libre"

_PRESET_LIBRE = {"id": LIBRE, "nombre": "Sin estilo",
                 "datos": {"estilo": {}, "guion": {"idioma_salida": "es"}, "origen": {}}}
#: calidad de las hojas: son referencias que se copian en cada plano, merecen
#: mas que la baja de los planos
CALIDAD = "medium"
MAX_FOTO = 8 * 1024 * 1024

_CANDADO = threading.Lock()
_EN_MARCHA = set()

INSTRUCCION = """Eres el director de arte de un canal de YouTube animado. Te paso \
la idea de {que} que aparecera en todos los videos del canal, escrita por su \
creador en su idioma, y el estilo de dibujo del canal.

IDEA: {idea}
NOMBRE: {nombre}
ESTILO DEL CANAL: {estilo}
IDIOMA DE LOS VIDEOS: {idioma}
{foto}
Devuelve SOLO este JSON:
{{"descripcion": "<{campo}, en ingles, 40-90 palabras, sin accion ni escena>",
 "papel": "<quien o que es, 3-6 palabras, en el idioma de los videos>",
 "palabras": ["<como lo nombrara el guion en el idioma de los videos: nombre, apodos, 'el perro', etc.>"]}}
"""

_QUE = {
    "personajes": ("un PERSONAJE recurrente",
                   "descripcion FISICA permanente: edad aparente, complexion, cara, "
                   "pelo, piel, ropa habitual, rasgo distintivo; adaptada al estilo "
                   "del canal (si el estilo son monigotes, describelo como monigote)"),
    "lugares": ("un LUGAR recurrente",
                "descripcion visual permanente del sitio: tipo de lugar, distribucion, "
                "muebles o elementos clave, materiales, colores, epoca, luz habitual"),
    "objetos": ("un OBJETO recurrente",
                "descripcion visual permanente del objeto: forma, tamano, colores, "
                "materiales, marcas o detalles que lo hacen reconocible"),
}


def _seguro(texto, tope=80):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(texto))[:tope]


def ruta_de(estilo_id):
    return os.path.join(CARPETA, f"{_seguro(estilo_id)}.json")


def carpeta_imagenes(estilo_id):
    return os.path.join(CARPETA, _seguro(estilo_id))


def leer(estilo_id):
    """Lo que tiene el taller de este estilo. -> {"personajes": {...}, ...}"""
    datos = medios.leer_json(ruta_de(estilo_id), {}) or {}
    for tipo in TIPOS:
        datos.setdefault(tipo, {})
        for ident, ficha in datos[tipo].items():
            if ficha.get("estado") == "pensando" and (estilo_id, tipo, ident) not in _EN_MARCHA:
                ficha["estado"] = "error"
                ficha["error"] = "se corto (el estudio se reinicio); pulsa Rehacer"
    return datos


def _guardar(estilo_id, datos):
    os.makedirs(CARPETA, exist_ok=True)
    medios.escribir_json(ruta_de(estilo_id), datos)


def _actualizar(estilo_id, tipo, ident, cambios):
    with _CANDADO:
        datos = medios.leer_json(ruta_de(estilo_id), {}) or {}
        datos.setdefault(tipo, {})
        ficha = dict(datos[tipo].get(ident) or {})
        ficha.update(cambios)
        datos[tipo][ident] = ficha
        _guardar(estilo_id, datos)
        return ficha


def ruta_imagen(estilo_id, ident):
    return os.path.join(carpeta_imagenes(estilo_id), f"{_seguro(ident)}.png")


def _estilo_del_preset(preset):
    datos = preset.get("datos") or {}
    estilo = dict(datos.get("estilo") or {})
    origen = datos.get("origen") or {}
    guion = datos.get("guion") or {}
    resumen = ((estilo.get("guia") or {}).get("resumen_es")
               or origen.get("estilo_prompt") or "")
    idioma = guion.get("idioma_salida") or origen.get("idioma") or "es"
    return estilo, " ".join(str(resumen).split())[:700], idioma


def _referencias(estilo, tipo):
    """Las laminas del estilo que tocan a lo que se dibuja: las de personas para
    un personaje, las de sitios para un lugar, la de objeto para un objeto."""
    refs = [r for r in estilo.get("referencias") or [] if isinstance(r, str) and os.path.exists(r)]
    ejes = {"personajes": ("cara", "cuerpos"), "lugares": ("interior", "exterior"),
            "objetos": ("objeto", "cuerpos")}[tipo]
    elegidas = [r for r in refs if any(e in os.path.basename(r) for e in ejes)]
    return (elegidas or refs)[:3]


def _prompt_lugar(ficha, estilo):
    lineas = ["Draw a reference image of a recurring LOCATION for an animated "
              "channel: a wide establishing view that shows the whole place clearly.",
              "The first reference images are the STYLE SHEET: copy the drawing "
              "style they show -- line weight, palette, shapes -- never their content."]
    lineas.extend(p6_assets.guia_escrita(estilo))
    lineas.append(f"The location: {ficha['descripcion']}.")
    lineas.append("No people in it, evenly lit, nothing cropped at the edges. Do not "
                  "annotate: no captions, labels, arrows or watermarks.")
    return " ".join(lineas)


def _prompt_objeto(ficha, estilo):
    lineas = ["Draw a reference sheet of a recurring OBJECT for an animated channel.",
              "The first reference images are the STYLE SHEET: copy the drawing "
              "style they show -- line weight, palette, shapes -- never their content."]
    lineas.extend(p6_assets.guia_escrita(estilo))
    lineas.append(f"The object: {ficha['descripcion']}.")
    lineas.append("Show it three times side by side on a plain flat background: "
                  "front view, three-quarter view and side view, the same object in "
                  "all of them. No people. Do not annotate: no captions, labels, "
                  "arrows or watermarks.")
    return " ".join(lineas)


def _prompt(tipo, ficha, estilo):
    if tipo == "personajes":
        return p6_assets._prompt_reparto({"descripcion": ficha["descripcion"],
                                          "grupo": False, "feedback": ficha.get("nota", "")},
                                         estilo)
    base = _prompt_lugar(ficha, estilo) if tipo == "lugares" else _prompt_objeto(ficha, estilo)
    if ficha.get("nota"):
        base += (" The creator looked at the previous version and asked for this "
                 f"change, which is NOT optional: {ficha['nota']}.")
    return base


def _prompt_libre(tipo, ficha, aspecto):
    """El prompt del taller libre: sin laminas, con el aspecto escrito."""
    que = {"personajes": "a reference CHARACTER SHEET", "lugares": "a reference image of a LOCATION",
           "objetos": "a reference sheet of an OBJECT"}[tipo]
    lineas = [f"Draw {que} for an animated channel, in this art style: {aspecto}."]
    if tipo == "personajes":
        lineas.append("Two rows on a plain flat background: top row large head-and-shoulders "
                      "portraits (front, three-quarter, profile), bottom row the same character "
                      "standing full body. Exactly ONE character, identical in every view. Face fully "
                      f"visible with eyes, eyebrows and mouth. The character: {ficha['descripcion']}.")
    elif tipo == "lugares":
        lineas.append(f"A wide establishing view, no people, evenly lit. The location: {ficha['descripcion']}.")
    else:
        lineas.append("Three views side by side (front, three-quarter, side) on a plain flat "
                      f"background, no people. The object: {ficha['descripcion']}.")
    if ficha.get("nota"):
        lineas.append(f"The creator asked for this change, which is NOT optional: {ficha['nota']}.")
    lineas.append("Do not annotate: no captions, labels, arrows or watermarks.")
    return " ".join(lineas)


def pasar_a_estilo(tipo, ident, estilo_destino):
    """Copia un elemento del taller LIBRE a un estilo, redibujado en su estilo."""
    origen = (leer(LIBRE).get(tipo) or {}).get(ident)
    if not origen or origen.get("estado") != "listo":
        raise ValueError("ese elemento del taller libre no existe o no esta terminado")
    if not presets_canal.leer(estilo_destino):
        raise ValueError(f"no hay ningun estilo '{estilo_destino}'")
    return crear(estilo_destino, tipo, origen.get("nombre"),
                 origen.get("idea") or origen.get("descripcion") or origen.get("nombre"),
                 foto_ruta=origen.get("imagen") or "")


def _con_contexto_de_coste(preset, funcion):
    """Lo que se gasta aqui se apunta en el TALLER del estilo, que es el
    proyecto donde se genero: asi sale en el coste global y en el saldo."""
    try:
        from nucleo import coste as COSTE
        from nucleo.proyecto import Proyecto
        taller = ((preset.get("datos") or {}).get("origen") or {}).get("taller")
        raiz = os.environ.get("ESTUDIO_PROYECTOS")
        if taller and raiz and os.path.isdir(os.path.join(raiz, taller)):
            with COSTE.contexto(Proyecto(os.path.join(raiz, taller)), "taller"):
                return funcion()
    except ImportError:
        pass
    return funcion()


def crear(estilo_id, tipo, nombre, idea, foto_b64="", ident=None, nota="", aspecto="",
          foto_ruta=""):
    """Crea (o rehace, con `ident`) una ficha del taller en un hilo. -> la ficha

    En el taller LIBRE (`estilo_id == LIBRE`) no hay laminas de estilo: manda
    `aspecto` (como se dibuja, en palabras). `foto_ruta` es una imagen que ya
    esta en disco como referencia (la usa «pasar a un estilo»)."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo '{tipo}' no vale: {', '.join(TIPOS)}")
    preset = _PRESET_LIBRE if estilo_id == LIBRE else presets_canal.leer(estilo_id)
    if not preset:
        raise ValueError(f"no hay ningun estilo '{estilo_id}'")
    nombre = " ".join(str(nombre or "").split())[:60]
    idea = " ".join(str(idea or "").split())[:1500]
    previa = (leer(estilo_id).get(tipo) or {}).get(ident) if ident else None
    if ident and not previa:
        raise ValueError(f"no hay ningun {tipo[:-1]} '{ident}' en este estilo")
    if not ident:
        if not nombre:
            raise ValueError("hace falta un nombre")
        base = medios.identificador(nombre) or "elemento"
        ocupados = set(leer(estilo_id).get(tipo) or {})
        ident, n = base, 1
        while ident in ocupados:
            n += 1
            ident = f"{base}_{n}"
    clave = (estilo_id, tipo, ident)
    with _CANDADO:
        if clave in _EN_MARCHA:
            return leer(estilo_id)[tipo].get(ident)
        _EN_MARCHA.add(clave)

    foto = ""
    if foto_b64:
        crudo = base64.b64decode(str(foto_b64).split(",")[-1])
        if len(crudo) > MAX_FOTO:
            with _CANDADO:
                _EN_MARCHA.discard(clave)
            raise ValueError("la foto pesa demasiado (maximo 8 MB)")
        os.makedirs(carpeta_imagenes(estilo_id), exist_ok=True)
        foto = os.path.join(carpeta_imagenes(estilo_id), f"{_seguro(ident)}_foto.png")
        # se guarda como PNG DE VERDAD, venga como venga (jpg del movil, webp):
        # el motor de imagen lee el formato por la extension
        try:
            from PIL import Image
            with Image.open(io.BytesIO(crudo)) as subida:
                subida.convert("RGBA").save(foto, format="PNG")
        except Exception:                                   # noqa: BLE001
            with _CANDADO:
                _EN_MARCHA.discard(clave)
            raise ValueError("eso no parece una imagen (sube un jpg o png)")
    elif foto_ruta and os.path.exists(foto_ruta):
        foto = foto_ruta
    elif previa:
        foto = previa.get("foto") or ""
    aspecto = " ".join(str(aspecto or (previa or {}).get("aspecto") or "").split())[:600]
    if estilo_id == LIBRE and not aspecto:
        aspecto = "clean modern 2D cartoon illustration, bold outlines, flat colours"

    ficha = _actualizar(estilo_id, tipo, ident, {
        "aspecto": aspecto,
        "id": ident, "tipo": tipo, "nombre": nombre or (previa or {}).get("nombre", ident),
        "idea": idea or (previa or {}).get("idea", ""), "foto": foto,
        "nota": " ".join(str(nota or "").split())[:600],
        "estado": "pensando", "error": "", "desde": time.time()})

    def correr():
        try:
            estilo, resumen, idioma = _estilo_del_preset(preset)
            if estilo_id == LIBRE:
                resumen = aspecto
            descripcion = (previa or {}).get("descripcion") if previa and not idea else ""
            datos_ia = {}
            if not descripcion:
                que, campo = _QUE[tipo]
                texto, _ = cli_claude.ejecutar(
                    INSTRUCCION.format(
                        que=que, campo=campo, idea=ficha["idea"] or ficha["nombre"],
                        nombre=ficha["nombre"], estilo=resumen or "(sin describir)",
                        idioma=idioma,
                        foto=("Hay una FOTO/DIBUJO de referencia adjunto aparte: describe "
                              "lo que la idea diga; la foto se usara como referencia visual.\n"
                              if foto else "")),
                    modelo="sonnet", esfuerzo="low", cwd=tempfile.gettempdir(),
                    tiempo_max_s=240, extra=["--no-session-persistence"],
                    para=f"describir {ficha['nombre']} para el taller")
                encaje = re.search(r"\{.*\}", texto or "", re.S)
                datos_ia = json.loads(encaje.group(0)) if encaje else {}
                descripcion = " ".join(str(datos_ia.get("descripcion") or "").split())
                if not descripcion:
                    raise ValueError("Claude no ha devuelto la descripcion")
            fusion = dict(ficha, descripcion=descripcion)
            refs = _referencias(estilo, tipo)
            if foto and os.path.exists(foto):
                refs = refs + [foto]
            prompt = (_prompt_libre(tipo, fusion, aspecto) if estilo_id == LIBRE
                      else _prompt(tipo, fusion, estilo))
            if foto:
                prompt += (" The LAST reference image is a photo or drawing of the "
                           "real subject: keep its identity and key features, but "
                           "redraw it completely in the channel's style.")
            imagen = medios.motor("imagen_openai/imagen.py")
            cache = os.path.join(carpeta_imagenes(estilo_id), "_cache")
            refs = [imagen.normalizar(r, cache) for r in refs]
            png, meta = _con_contexto_de_coste(preset, lambda: imagen.generar(
                prompt, refs, quality=CALIDAD, tamano="apaisado"))
            destino = ruta_imagen(estilo_id, ident)
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "wb") as fh:
                fh.write(png)
            palabras = [str(p).strip() for p in (datos_ia.get("palabras") or
                                                 (previa or {}).get("palabras") or [])
                        if str(p).strip()][:8]
            if ficha["nombre"] and ficha["nombre"] not in palabras:
                palabras.insert(0, ficha["nombre"])
            _actualizar(estilo_id, tipo, ident, {
                "estado": "listo", "descripcion": descripcion,
                "papel": str(datos_ia.get("papel") or (previa or {}).get("papel") or ""),
                "palabras": palabras, "imagen": destino,
                "version": int((previa or {}).get("version") or 0) + 1,
                "coste": round(float(meta.get("coste") or 0), 3),
                "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")})
        except Exception as fallo:                          # noqa: BLE001
            _actualizar(estilo_id, tipo, ident, {
                "estado": "error", "error": f"{type(fallo).__name__}: {str(fallo)[:300]}"})
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(clave)

    threading.Thread(target=correr, daemon=True, name=f"canal-{ident}").start()
    return ficha


def borrar(estilo_id, tipo, ident):
    with _CANDADO:
        datos = medios.leer_json(ruta_de(estilo_id), {}) or {}
        ficha = (datos.get(tipo) or {}).pop(ident, None)
        if ficha is None:
            raise ValueError(f"no hay ningun '{ident}'")
        _guardar(estilo_id, datos)
    for ruta in (ficha.get("imagen"), ficha.get("foto")):
        if ruta and os.path.exists(ruta) and os.path.dirname(ruta) == carpeta_imagenes(estilo_id):
            os.remove(ruta)
    return ficha


def para_catalogo(estilo_id):
    """Lo listo del taller, con la forma del catalogo de un video.

    -> {"reparto": {...}, "sets": {...}} -- los personajes y objetos van al
    reparto (con su hoja ya dibujada en `hoja_canal`), los lugares a los sitios
    (con su imagen en `imagen_canal`).
    """
    datos = leer(estilo_id)
    reparto, sets = {}, {}
    for tipo in ("personajes", "objetos"):
        for ident, f in datos[tipo].items():
            if f.get("estado") != "listo" or not os.path.exists(f.get("imagen") or ""):
                continue
            reparto[ident] = {"nombre": f.get("nombre") or ident, "papel": f.get("papel") or "",
                              "descripcion": f["descripcion"], "palabras": f.get("palabras") or [],
                              "grupo": False, "canal": True, "objeto": tipo == "objetos",
                              "hoja_canal": f["imagen"]}
    for ident, f in datos["lugares"].items():
        if f.get("estado") != "listo" or not os.path.exists(f.get("imagen") or ""):
            continue
        sets[ident] = {"rotulo": "", "descripcion": f["descripcion"],
                       "palabras": f.get("palabras") or [], "canal": True,
                       "imagen_canal": f["imagen"]}
    return {"reparto": reparto, "sets": sets}


def peticion_para_catalogo(estilo_id):
    """La frase que se le anade a Claude al deducir el catalogo de un video."""
    fijos = para_catalogo(estilo_id)
    if not fijos["reparto"] and not fijos["sets"]:
        return ""
    trozos = []
    if fijos["reparto"]:
        trozos.append("Personajes y objetos FIJOS del canal (si el guion los nombra, "
                      "usa EXACTAMENTE estos ids en el reparto y no inventes otro para "
                      "ellos): " + "; ".join(
                          f"{i} = {f['nombre']} ({', '.join(f['palabras'][:4])})"
                          for i, f in fijos["reparto"].items()))
    if fijos["sets"]:
        trozos.append("Lugares FIJOS del canal (si el guion ocurre en ellos, usa "
                      "EXACTAMENTE estos ids en sets): " + "; ".join(
                          f"{i} ({', '.join(f['palabras'][:4])})" for i, f in fijos["sets"].items()))
    return " ".join(trozos)


def fusionar(catalogo, estilo_id):
    """Mete lo del taller en un catalogo ya deducido. -> cuantos entraron"""
    fijos = para_catalogo(estilo_id)
    catalogo.setdefault("reparto", {})
    catalogo.setdefault("sets", {})
    for ident, f in fijos["reparto"].items():
        previo = catalogo["reparto"].get(ident) or {}
        palabras = list(dict.fromkeys((f["palabras"] or []) + (previo.get("palabras") or [])))
        catalogo["reparto"][ident] = {**previo, **f, "palabras": palabras}
    for ident, f in fijos["sets"].items():
        previo = catalogo["sets"].get(ident) or {}
        palabras = list(dict.fromkeys((f["palabras"] or []) + (previo.get("palabras") or [])))
        nuevo = {**previo, **f, "palabras": palabras}
        # el rotulo (sitio y hora) lo saca el catalogo del guion de ESTE video
        nuevo["rotulo"] = previo.get("rotulo") or ""
        catalogo["sets"][ident] = nuevo
    return len(fijos["reparto"]) + len(fijos["sets"])
