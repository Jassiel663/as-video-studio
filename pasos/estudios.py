"""
ESTUDIOS DE UN ESTILO: la competencia, tus propios videos, y el chat creativo.

Tres cosas que se le piden a Claude sobre un canal, gratis (suscripcion del
CLI) y en un hilo, con su estado en un fichero que la pantalla va mirando --la
misma mecanica que pasos/ideas.py, que es la cuarta--:

  competencia   canales concretos que nombra quien pide (URL o nombre): Claude
                busca en la web sus videos mas vistos, como titulan, como son
                sus miniaturas y su ritmo, y que copiar y que evitar.
  mis_videos    los videos hechos con el estilo (titulo, guion, duracion): el
                gancho, el ritmo, el titulo, y que mejorar en cada uno y en
                general. Sin estadisticas de YouTube: lee lo que hay aqui.
  chat          una conversacion sobre el canal. Claude conoce el estilo, su
                taller, su nicho y sus videos, y cuando propone algo concreto lo
                devuelve tambien como ACCION (crear un personaje, un lugar, un
                objeto, o una idea de video) para hacerlo de un clic.

Se guarda en datos/estudios/<estilo>_<tipo>.json.
"""
import json
import os
import re
import tempfile
import threading
import time

try:
    from . import cli_claude, ideas, medios, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import ideas
    import medios
    import presets_canal

CARPETA = os.environ.get("ESTUDIO_ESTUDIOS") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "estudios")
TIPOS = ("competencia", "mis_videos", "chat")
MAX_MENSAJES = 60

_CANDADO = threading.Lock()
_EN_MARCHA = set()

CANAL = """EL CANAL
- Nombre del estilo: {nombre}
- Idioma de los videos: {idioma}
- Como habla: {tono}
- Guia de guion: {guia}
- Como se ve: {estetica}
- Videos ya hechos: {hechos}
"""

COMPETENCIA = """Eres analista de YouTube. Estudia estos canales de la \
competencia de mi canal buscando DE VERDAD en internet (sus paginas de YouTube, \
Social Blade, articulos, listas de videos mas vistos). No inventes cifras: si \
no encuentras un dato, dilo.

{canal}
CANALES A ESTUDIAR: {canales}

Contesta SOLO con este JSON (texto en {idioma}):
{{"canales": [{{"nombre": "...", "url": "...", "resumen": "que hacen y para quien", \
"exitos": ["titulos o temas de sus videos que mejor funcionan"], \
"titulos": "como titulan (patrones)", "miniaturas": "como son sus miniaturas", \
"ritmo": "duracion, frecuencia, estructura", "copiar": ["..."], "evitar": ["..."]}}],
 "conclusion": "que deberia hacer MI canal para ganarles: 4-6 frases concretas",
 "fuentes": ["url"]}}
"""

MIS_VIDEOS = """Eres editor jefe de un canal de YouTube. Revisa los videos que \
ya ha hecho este canal (te paso titulo, duracion y el principio del guion) y \
dime, con franqueza y de forma practica, que mejorar.

{canal}
VIDEOS:
{videos}

Contesta SOLO con este JSON (texto en {idioma}):
{{"general": "diagnostico del canal en 3-5 frases", \
"videos": [{{"titulo": "...", "nota": 7, "gancho": "como es el gancho de los 5 primeros \
segundos y como mejorarlo", "titulo_mejor": "un titulo mejor", "mejoras": ["..."]}}], \
"prioridades": ["las 3-5 cosas que mas impacto tendrian, en orden"]}}
"""

CHAT = """Eres el companero creativo del creador de este canal de YouTube \
(guionista, director de arte y estratega a la vez). Habla en {idioma}, cercano \
y concreto, sin rodeos.

{canal}
TALLER DEL CANAL (personajes, lugares y objetos fijos): {taller}
NICHO ESTUDIADO: {nicho}

CONVERSACION HASTA AHORA:
{historial}

MENSAJE NUEVO DEL CREADOR: {mensaje}

Contesta al mensaje. Si propones cosas CONCRETAS que se puedan crear en el \
estudio, anade AL FINAL un bloque exactamente asi (y si no, no lo pongas):
<acciones>[{{"tipo": "personajes|lugares|objetos", "nombre": "...", "idea": \
"como es, en una frase"}}, {{"tipo": "idea", "titulo": "...", "material": \
"5-10 lineas con los hechos y el orden de la historia", "formato": \
"video|documental|short"}}]</acciones>
"""


def ruta_de(estilo_id, tipo):
    seguro = re.sub(r"[^A-Za-z0-9_-]", "_", str(estilo_id))[:80]
    return os.path.join(CARPETA, f"{seguro}_{tipo}.json")


def leer(estilo_id, tipo):
    datos = medios.leer_json(ruta_de(estilo_id, tipo), {}) or {}
    if tipo == "chat":
        datos.setdefault("mensajes", [])
    if datos.get("estado") == "pensando" and (estilo_id, tipo) not in _EN_MARCHA:
        datos["estado"] = "error"
        datos["error"] = "se corto (el estudio se reinicio); vuelve a pedirlo"
    return datos


def _guardar(estilo_id, tipo, datos):
    os.makedirs(CARPETA, exist_ok=True)
    medios.escribir_json(ruta_de(estilo_id, tipo), datos)


def _canal(preset, hechos):
    ficha = ideas._ficha_del_canal(preset, list(hechos))
    return CANAL.format(**ficha), ficha["idioma"]


def _json(texto):
    encaje = re.search(r"\{.*\}", texto or "", re.S)
    if not encaje:
        return None
    try:
        return json.loads(encaje.group(0))
    except ValueError:
        return None


def _lanzar(estilo_id, tipo, previo, trabajo):
    """Corre `trabajo()` en un hilo; lo que devuelva (dict) se guarda listo."""
    with _CANDADO:
        if (estilo_id, tipo) in _EN_MARCHA:
            return leer(estilo_id, tipo)
        _EN_MARCHA.add((estilo_id, tipo))
    _guardar(estilo_id, tipo, dict(previo, estado="pensando", error="", desde=time.time()))

    def correr():
        try:
            resultado = trabajo()
            _guardar(estilo_id, tipo, dict(resultado, estado="listo",
                                           fecha=time.strftime("%Y-%m-%dT%H:%M:%S")))
        except Exception as fallo:                          # noqa: BLE001
            _guardar(estilo_id, tipo, dict(previo, estado="error",
                                           error=f"{type(fallo).__name__}: {str(fallo)[:300]}"))
        finally:
            with _CANDADO:
                _EN_MARCHA.discard((estilo_id, tipo))

    threading.Thread(target=correr, daemon=True, name=f"estudio-{tipo}").start()
    return leer(estilo_id, tipo)


def _preset(estilo_id):
    preset = presets_canal.leer(estilo_id)
    if not preset:
        raise ValueError(f"no hay ningun estilo '{estilo_id}'")
    return preset


def _claude(instruccion, web, para):
    for intento in range(2):
        pedido = instruccion if not intento else (
            instruccion + "\nIMPORTANTE: tu mensaje final debe ser UNICAMENTE el JSON pedido.")
        kw = ({"herramientas_vetadas": ideas.VETADAS, "herramientas_permitidas": ideas.SOLO_WEB}
              if web else {})
        texto, _ = cli_claude.ejecutar(pedido, modelo="sonnet", esfuerzo="medium",
                                       cwd=tempfile.gettempdir(), tiempo_max_s=600,
                                       extra=["--no-session-persistence"], para=para, **kw)
        datos = _json(texto)
        if isinstance(datos, dict):
            return datos
    raise ValueError("la respuesta no trae el JSON pedido: "
                     + " ".join(str(texto or "").split())[:160])


def competencia(estilo_id, canales, hechos=()):
    canales = [c for c in (" ".join(str(x).split()) for x in canales or []) if c][:5]
    if not canales:
        raise ValueError("di al menos un canal (su URL de YouTube o su nombre)")
    preset = _preset(estilo_id)
    texto_canal, idioma = _canal(preset, hechos)
    instruccion = COMPETENCIA.format(canal=texto_canal, canales="; ".join(canales), idioma=idioma)
    previo = leer(estilo_id, "competencia")

    def trabajo():
        datos = _claude(instruccion, True, "estudiar la competencia")
        return {"pedidos": canales, "canales": [c for c in datos.get("canales") or []
                                                if isinstance(c, dict)],
                "conclusion": str(datos.get("conclusion") or ""),
                "fuentes": [str(f) for f in datos.get("fuentes") or []][:12]}
    return _lanzar(estilo_id, "competencia", previo, trabajo)


def mis_videos(estilo_id, videos):
    """`videos`: [{"titulo", "duracion_s", "guion"}] de los videos del estilo."""
    videos = [v for v in videos or [] if str(v.get("guion") or "").strip()][:15]
    if not videos:
        raise ValueError("este estilo todavia no tiene videos con guion que revisar")
    preset = _preset(estilo_id)
    texto_canal, idioma = _canal(preset, [v["titulo"] for v in videos])
    lista = "\n\n".join(
        f"- «{v['titulo']}» ({round(float(v.get('duracion_s') or 0) / 60, 1)} min):\n  "
        + " ".join(str(v["guion"]).split())[:1500] for v in videos)
    instruccion = MIS_VIDEOS.format(canal=texto_canal, videos=lista, idioma=idioma)
    previo = leer(estilo_id, "mis_videos")

    def trabajo():
        datos = _claude(instruccion, False, "revisar mis videos")
        return {"general": str(datos.get("general") or ""),
                "videos": [v for v in datos.get("videos") or [] if isinstance(v, dict)],
                "prioridades": [str(p) for p in datos.get("prioridades") or []]}
    return _lanzar(estilo_id, "mis_videos", previo, trabajo)


def _acciones_de(texto):
    """Separa la respuesta del bloque <acciones>. -> (texto, [acciones])"""
    encaje = re.search(r"<acciones>(.*?)</acciones>", texto or "", re.S)
    if not encaje:
        return (texto or "").strip(), []
    try:
        acciones = json.loads(encaje.group(1))
    except ValueError:
        acciones = []
    validas = []
    for a in acciones if isinstance(acciones, list) else []:
        if not isinstance(a, dict):
            continue
        if a.get("tipo") in ("personajes", "lugares", "objetos") and str(a.get("nombre") or "").strip():
            validas.append({"tipo": a["tipo"], "nombre": str(a["nombre"])[:60],
                            "idea": str(a.get("idea") or "")[:600]})
        elif a.get("tipo") == "idea" and str(a.get("titulo") or "").strip():
            validas.append({"tipo": "idea", "titulo": str(a["titulo"])[:120],
                            "material": str(a.get("material") or "")[:2000],
                            "formato": str(a.get("formato") or "video")})
    limpio = (texto[:encaje.start()] + texto[encaje.end():]).strip()
    return limpio, validas[:8]


def chat(estilo_id, mensaje, taller="", hechos=()):
    mensaje = " ".join(str(mensaje or "").split())[:3000]
    if not mensaje:
        raise ValueError("escribe algo")
    preset = _preset(estilo_id)
    texto_canal, idioma = _canal(preset, hechos)
    previo = leer(estilo_id, "chat")
    mensajes = list(previo.get("mensajes") or [])
    historial = "\n".join(f"{'CREADOR' if m['quien'] == 'yo' else 'TU'}: {m['texto'][:1500]}"
                          for m in mensajes[-16:]) or "(empieza ahora)"
    nicho = (ideas.leer(estilo_id).get("nicho") or {}).get("resumen") or "(sin estudiar)"
    instruccion = CHAT.format(idioma=idioma, canal=texto_canal, taller=taller or "(vacio)",
                              nicho=str(nicho)[:800], historial=historial, mensaje=mensaje)
    mensajes.append({"quien": "yo", "texto": mensaje, "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")})
    previo = dict(previo, mensajes=mensajes[-MAX_MENSAJES:])

    def trabajo():
        texto, _ = cli_claude.ejecutar(instruccion, modelo="sonnet", esfuerzo="medium",
                                       cwd=tempfile.gettempdir(), tiempo_max_s=300,
                                       herramientas_vetadas=ideas.VETADAS,
                                       herramientas_permitidas=ideas.SOLO_WEB,
                                       extra=["--no-session-persistence"],
                                       para="el chat creativo")
        respuesta, acciones = _acciones_de(texto)
        nuevos = previo["mensajes"] + [{"quien": "claude", "texto": respuesta,
                                        "acciones": acciones,
                                        "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")}]
        return {"mensajes": nuevos[-MAX_MENSAJES:]}
    return _lanzar(estilo_id, "chat", previo, trabajo)


def borrar_chat(estilo_id):
    ruta = ruta_de(estilo_id, "chat")
    if os.path.exists(ruta):
        os.remove(ruta)
    return leer(estilo_id, "chat")
