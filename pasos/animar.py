"""
Los planos SIN TEXTO que se animan con Veo, y el clip de cada uno.

El render sigue siendo lo que era --una imagen quieta con una camara que se
mueve encima-- salvo en los planos que pasan el filtro de aqui: esos se animan
con Google Veo a partir de su propia imagen y el render pinta los fotogramas
del clip en lugar de la imagen.

POR QUE SOLO LOS PLANOS SIN TEXTO. La prueba del 29-09-2026 con tres planos de
un video real lo dejo claro: Veo mantiene el estilo de dibujo y el reparto, pero
NO el texto. La notificacion «Deposito recibido» desaparecio a mitad de clip y
la cifra «$1.000.000.000» salio ilegible. Un plano con letras animado es un
plano estropeado, asi que no se anima ninguno que las lleve.

COMO SE SABE SI UN PLANO LLEVA TEXTO. No mirando la imagen: leyendo lo que se
le pidio al dibujarla. El plan guarda la `direccion` de cada plano, y el prompt
de imagen dibuja SOLO las palabras que la direccion pone entre comillas
(«LETTERING ... draw only the words this prompt asked for in quotes»). Ademas
se descartan las pantallas, carteles y paginas aunque no lleven comillas --el
prompt las pinta con garabatos que se leen como texto de lejos, y Veo los
deforma igual--, las cartelas y cualquier plano con capa grafica encima.

EL PARAM ES `video_ia` DEL RENDER: "" / ausente (apagado), "lite" o "fast".
Ausente es apagado y NO se escribe por defecto: la firma del render se calcula
sobre los params guardados, y escribir un valor que un proyecto nunca tuvo lo
dejaria obsoleto (ver CLAUDE.md, «aqui se paga por generar»).

LOS CLIPS SE GUARDAN POR HUELLA en <proyecto>/video_ia/: imagen + prompt +
modelo + duracion. Volver a renderizar no vuelve a pagar un clip; cambiar el
plano (otra imagen) si, porque es otro clip.
"""
import hashlib
import os
import re
import subprocess

try:
    from nucleo import coste as COSTE
except ImportError:                                   # corriendo desde pasos/
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import coste as COSTE

import medios

PARAM = "video_ia"
MODOS = ("", "lite", "fast")

#: Sube si cambia la forma de pedir el clip (prompt, recorte): los clips de la
#: version anterior dejan de valer y se piden otra vez.
VERSION = 1

#: Letras entre comillas en la direccion del plano: lo que el prompt dibuja.
_COMILLAS = re.compile(r"[\"“”«»]([^\"“”«»]{1,120})[\"“”«»]")

#: Superficies que el prompt de imagen pinta con texto ilegible. Veo las
#: deforma igual que el texto de verdad, asi que tambien se quedan quietas.
_SUPERFICIES = re.compile(
    r"\b(screen|phone|smartphone|laptop|monitor|display|tablet|sign|signs|"
    r"signboard|billboard|poster|banner|page|pages|book|newspaper|magazine|"
    r"label|menu|receipt|ticket|card|document|letter|note|chart|graph|map|"
    r"whiteboard|blackboard|screenshot|notification|app)\b", re.I)

#: Elementos de una capa SVG que se VEN. Una capa vacia es un <svg> con, como
#: mucho, <defs>; si lleva algo de esto va dibujado encima del plano en
#: coordenadas de la imagen, y con un clip debajo dejaria de cuadrar.
_VISIBLE_SVG = re.compile(r"<(text|image|path|rect|circle|ellipse|line|"
                          r"polyline|polygon|use|foreignObject)\b", re.I)

ESTILO = ("Keep EXACTLY the illustrated style of the image: same line work, "
          "palette, textures, lighting and character design. Animate this exact "
          "frame, do not redraw it, do not cut to another shot. ")
NEGATIVO = ("photorealistic, style change, morphing, text, letters, subtitles, "
            "watermark, extra limbs, extra fingers, flicker, scene cut")
#: El del primer plano CON texto: pedir «sin letras» ahi es pedir que las borre.
NEGATIVO_CON_TEXTO = ("photorealistic, style change, morphing, warped text, "
                      "garbled letters, changing numbers, new text, watermark, "
                      "extra limbs, extra fingers, flicker, scene cut")
TEXTO_QUIETO = ("Every piece of on-screen text, number and sign stays EXACTLY as "
                "drawn: same words, same digits, fully legible, not moving, not "
                "morphing. Animate only the characters, objects and camera around it. ")


def negativo_de(escena):
    return NEGATIVO_CON_TEXTO if lleva_texto(escena) else NEGATIVO


def modo_de(params):
    """El modo pedido en los params del render, normalizado. -> "" | lite | fast"""
    valor = str((params or {}).get(PARAM) or "").strip().lower()
    return valor if valor in MODOS else ""


def lleva_texto(escena):
    """Si el plano lleva letras dibujadas, cartela o superficies con texto."""
    direccion = str(escena.get("direccion") or "")
    return bool(_COMILLAS.search(direccion)
                or escena.get("cartela")
                or str(escena.get("carta") or "").lower() in ("cifra", "cartela")
                or _SUPERFICIES.search(" ".join(str(escena.get(k) or "")
                                                for k in ("direccion", "accion"))))


def motivo_para_no_animar(escena, capa_svg="", primero=False):
    """Por que este plano NO se anima, o None si se puede animar. -> str|None

    EL PRIMER PLANO SE ANIMA AUNQUE LLEVE TEXTO (lo pidio el canal el
    30-09-2026): es el gancho, lo que se ve en el segundo cero. Veo recibe
    entonces la orden de dejar el texto quieto y legible (ver `prompt_de`), y
    sigue sin animarse si no cabe en un clip o lleva capa grafica encima, que
    con el clip debajo dejaria de cuadrar.
    """
    duracion = float(escena.get("t_out") or 0) - float(escena.get("t_in") or 0)
    veo = medios.motor("video_veo/veo.py")
    if veo.duracion_de_clip(duracion)[0] is None:
        return f"dura {duracion:.1f} s y un clip de Veo llega a 8"
    if primero:
        if escena.get("capa_vectorial") or (capa_svg and _VISIBLE_SVG.search(capa_svg)):
            return "lleva capa grafica encima"
        return None
    direccion = str(escena.get("direccion") or "")
    if _COMILLAS.search(direccion):
        return "lleva texto dibujado"
    if escena.get("cartela") or str(escena.get("carta") or "").lower() in ("cifra", "cartela"):
        return "lleva cartela"
    if escena.get("capa_vectorial"):
        return "lleva capa grafica encima"
    if _SUPERFICIES.search(" ".join(str(escena.get(k) or "")
                                    for k in ("direccion", "accion"))):
        return "muestra una pantalla, cartel o pagina"
    if capa_svg and _VISIBLE_SVG.search(capa_svg):
        return "lleva capa grafica encima"
    return None


def prevision(escenas, modo):
    """Lo que costaria animar este plan. -> {"clips", "segundos", "usd"}

    Es el TECHO: no sabe que clips ya estan en el cache ni mira las capas SVG
    (que solo existen despues de callouts), asi que puede contar alguno que al
    final no se anima. Mejor avisar de mas que prometer barato.
    """
    if not modo:
        return {"clips": 0, "segundos": 0, "usd": 0.0}
    veo = medios.motor("video_veo/veo.py")
    clips, segundos, usd = 0, 0, 0.0
    for indice, escena in enumerate(escenas or []):
        if motivo_para_no_animar(escena, primero=indice == 0) is not None:
            continue
        duracion = float(escena["t_out"]) - float(escena["t_in"])
        pedidos, resolucion = veo.duracion_de_clip(duracion)
        precio = COSTE.tarifa_veo(veo.MODELOS[modo], resolucion) or 0.0
        clips += 1
        segundos += pedidos
        usd += pedidos * precio
    return {"clips": clips, "segundos": segundos, "usd": round(usd, 3)}


def _movimiento_de(escena):
    zoom = escena.get("zoom") or {}
    tipo = str(zoom.get("tipo") or "").lower()
    if tipo == "in":
        return "Slow, smooth camera push-in."
    if tipo == "out":
        return "Slow, smooth camera pull-back."
    return "Very subtle camera drift."


def prompt_de(escena):
    """Lo que se le pide a Veo para este plano: lo que pasa, y como se mueve."""
    partes = [ESTILO]
    if lleva_texto(escena):
        partes.append(TEXTO_QUIETO)
    for clave in ("direccion", "accion"):
        texto = " ".join(str(escena.get(clave) or "").split())
        if texto:
            partes.append(texto.rstrip(".") + ".")
    luz = " ".join(str(escena.get("luz") or "").split())
    if luz:
        partes.append(f"Lighting: {luz}.")
    partes.append("Bring the scene gently to life with natural, small motion "
                  "of the characters and the environment. " + _movimiento_de(escena))
    return " ".join(partes)


def preparar_imagen(hyper, destino, ancho, alto, ventana=None):
    """El fotograma de partida para Veo: la imagen recortada al cuadro del video.

    Veo trabaja en 16:9 o 9:16 y el plano es 3:2 (o 2:3). Se recorta al formato
    de salida SOBRE EL CENTRO DE LA VENTANA DE ZOOM, que es donde el plan dijo
    que estaba lo importante, y se deja a 1280x720 (o 720x1280).
    """
    from PIL import Image                                  # noqa: PLC0415
    vertical = alto > ancho
    objetivo = (720, 1280) if vertical else (1280, 720)
    with Image.open(hyper) as origen:
        imagen = origen.convert("RGB")
    iw, ih = imagen.size
    aspecto = ancho / float(alto)
    if iw / float(ih) > aspecto:
        cw, ch = round(ih * aspecto), ih
    else:
        cw, ch = iw, round(iw / aspecto)
    cx, cy = iw / 2.0, ih / 2.0
    if ventana and len(ventana) == 4:
        cx = (float(ventana[0]) + float(ventana[2]) / 2.0) * iw
        cy = (float(ventana[1]) + float(ventana[3]) / 2.0) * ih
    x = int(min(max(cx - cw / 2.0, 0), iw - cw))
    y = int(min(max(cy - ch / 2.0, 0), ih - ch))
    recorte = imagen.crop((x, y, x + cw, y + ch)).resize(objetivo, Image.LANCZOS)
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    recorte.save(destino, "PNG")
    return destino


def carpeta_de(proyecto):
    """Donde viven los clips de un proyecto: fuera de las versiones del render."""
    raiz = getattr(proyecto, "raiz", None) or str(proyecto)
    return os.path.join(raiz, "video_ia")


def clip(proyecto, escena, hyper, ancho, alto, modo, ventana=None, avisar=None,
         solo_cache=False):
    """El clip de Veo de este plano, del cache o recien pagado. -> (ruta, pagado)

    Con `solo_cache` no se pide nada a Veo: si el clip no estaba guardado se
    levanta CuotaAgotada. Es lo que se usa cuando la cuenta ya se ha quedado
    sin cuota en este mismo montaje: lo guardado no gasta cuota y sigue valiendo.
    """
    veo = medios.motor("video_veo/veo.py")
    duracion = float(escena["t_out"]) - float(escena["t_in"])
    segundos, resolucion = veo.duracion_de_clip(duracion)
    carpeta = carpeta_de(proyecto)
    entrada = os.path.join(carpeta, "entradas", f"{escena['id']}.png")
    preparar_imagen(hyper, entrada, ancho, alto, ventana=ventana)
    prompt = prompt_de(escena)
    with open(entrada, "rb") as fh:
        huella = hashlib.sha1(fh.read())
    negativo = negativo_de(escena)
    for trozo in (prompt, negativo, veo.MODELOS[modo], str(segundos), resolucion,
                  str(VERSION)):
        huella.update(b"\0" + trozo.encode("utf-8"))
    destino = os.path.join(carpeta, f"{escena['id']}_{huella.hexdigest()[:16]}.mp4")
    if os.path.exists(destino) and os.path.getsize(destino) > 0:
        return destino, False
    if solo_cache:
        raise veo.CuotaAgotada("sin cuota de Veo en este montaje y el clip no "
                               "estaba guardado")
    mp4, meta = veo.generar(entrada, prompt, modo=modo, segundos=segundos,
                            resolucion=resolucion,
                            aspecto="9:16" if alto > ancho else "16:9",
                            negativo=negativo, avisar=avisar)
    temporal = destino + ".parcial"
    with open(temporal, "wb") as fh:
        fh.write(mp4)
    os.replace(temporal, destino)
    COSTE.reportar_veo(meta["segundos"], meta["modelo"], meta["resolucion"],
                       unidad=f"escena:{escena['id']}",
                       detalle={"tardo_s": meta.get("tardo_s")})
    return destino, True


def fotogramas(clip_mp4, carpeta, ancho, alto, segundos):
    """Los fotogramas del clip, al tamano del video, para que el render los pinte.

    Se escalan CUBRIENDO el cuadro (sin bandas) y solo los `segundos` que dura
    el plano. -> (lista de rutas, fps del clip)
    """
    os.makedirs(carpeta, exist_ok=True)
    salida = subprocess.run(
        [medios.ffprobe(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", clip_mp4],
        capture_output=True, text=True, timeout=60, **medios.SIN_VENTANA)
    try:
        num, _, den = salida.stdout.strip().partition("/")
        fps = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        fps = 24.0
    escala = (f"scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
              f"crop={ancho}:{alto}")
    orden = [medios.ffmpeg(), "-y", "-loglevel", "error", "-i", clip_mp4,
             "-t", f"{float(segundos) + 0.2:.3f}", "-vf", escala,
             "-q:v", "2", os.path.join(carpeta, "v%05d.jpg")]
    proceso = subprocess.run(orden, capture_output=True, text=True, timeout=600,
                             **medios.SIN_VENTANA)
    if proceso.returncode != 0:
        raise RuntimeError(f"ffmpeg no pudo sacar los fotogramas de {clip_mp4}: "
                           f"{proceso.stderr[-300:]}")
    rutas = sorted(os.path.join(carpeta, n) for n in os.listdir(carpeta)
                   if n.startswith("v") and n.endswith(".jpg"))
    if not rutas:
        raise RuntimeError(f"el clip {clip_mp4} no dio ningun fotograma")
    return rutas, fps
