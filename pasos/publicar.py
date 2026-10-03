"""
PUBLICAR: donde se publica cada estilo, y el kit SEO de cada video.

Cada estilo es un canal distinto con SUS cuentas (el YouTube de Nico no es el
de Mr Jass), asi que los destinos van por estilo:

    datos/publicar/<estilo>.json   {youtube, tiktok, facebook, instagram}

y cada video lleva su KIT SEO, que escribe Claude (suscripcion, gratis) a partir
del titulo y del guion, uno por plataforma porque cada una se escribe distinto:

    youtube    titulo (y 3 alternativas), descripcion con capitulos, etiquetas
    tiktok     texto corto con hashtags
    facebook   texto del post / reel
    instagram  texto del reel con hashtags

Se guarda en el proyecto (`publicar/seo.json`). La subida de momento la hace la
persona con un clic --la pantalla descarga el video, copia los textos y abre la
pagina de subida de la cuenta de ese estilo--; la subida automatica por las APIs
de cada plataforma necesita que registre una app en cada una (fase B).
"""
import json
import os
import re
import tempfile
import threading
import time

try:
    from . import cli_claude, medios, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import medios
    import presets_canal

CARPETA = os.environ.get("ESTUDIO_PUBLICAR") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "publicar")
PLATAFORMAS = ("youtube", "tiktok", "facebook", "instagram")
_CANDADO = threading.Lock()
_EN_MARCHA = set()

#: La pagina de SUBIDA de cada plataforma. YouTube Studio abre la cuenta con la
#: que se este dentro; si el enlace del estilo trae el id del canal (UC...), se
#: abre directamente en ese canal.
SUBIDA = {"youtube": "https://studio.youtube.com/",
          "tiktok": "https://www.tiktok.com/tiktokstudio/upload",
          "facebook": "https://www.facebook.com/",
          "instagram": "https://www.instagram.com/"}

INSTRUCCION = """Eres el community manager de un canal de videos. Escribe el \
texto para publicar ESTE video en cada plataforma, en {idioma}, para que lo \
encuentren y pulsen (SEO), sin clickbait que mienta.

TITULO DE TRABAJO: {titulo}
TIPO: {tipo} ({duracion})
CANAL: {canal}
GUION (con el segundo en que empieza cada parte):
{guion}

Devuelve SOLO este JSON:
{{"youtube": {{"titulo": "<max 70 caracteres, la palabra clave al principio>", \
"alternativas": ["<3 titulos mas, distintos>"], \
"descripcion": "<2-3 parrafos: gancho, de que va, llamada a suscribirse; despues \
los capitulos si el video dura mas de 3 min, en lineas 'M:SS Titulo' empezando por 0:00; \
despues 3-5 hashtags>", "etiquetas": ["<10-15 etiquetas de busqueda>"]}},
 "tiktok": {{"texto": "<max 150 caracteres, gancho + 3-5 hashtags>"}},
 "facebook": {{"texto": "<2-3 frases que inviten a ver y comentar>"}},
 "instagram": {{"texto": "<gancho, 1-2 frases y 5-8 hashtags>"}}}}
"""


def _ruta(estilo_id):
    return os.path.join(CARPETA, f"{re.sub(r'[^A-Za-z0-9_-]', '_', str(estilo_id))[:80]}.json")


def destinos(estilo_id):
    datos = medios.leer_json(_ruta(estilo_id), {}) or {}
    return {p: str(datos.get(p) or "") for p in PLATAFORMAS}


def guardar_destinos(estilo_id, cambios):
    actuales = destinos(estilo_id)
    for plataforma in PLATAFORMAS:
        if plataforma in (cambios or {}):
            valor = " ".join(str(cambios[plataforma] or "").split())[:300]
            if valor and not re.match(r"^https?://", valor):
                valor = "https://" + valor.lstrip("/")
            actuales[plataforma] = valor
    os.makedirs(CARPETA, exist_ok=True)
    medios.escribir_json(_ruta(estilo_id), actuales)
    return actuales


def pagina_de_subida(plataforma, enlace=""):
    """A donde lleva «Publicar»: la subida de esa cuenta si se puede saber."""
    if plataforma == "youtube":
        canal = re.search(r"/channel/(UC[\w-]{20,})", enlace or "")
        if canal:
            return f"https://studio.youtube.com/channel/{canal.group(1)}/videos/upload?d=ud"
    if plataforma == "facebook" and enlace:
        return enlace
    if plataforma == "instagram" and enlace:
        return enlace
    return SUBIDA.get(plataforma, "")


def carpeta_de(proyecto):
    return os.path.join(proyecto.raiz, "publicar")


def leer_seo(proyecto):
    datos = medios.leer_json(os.path.join(carpeta_de(proyecto), "seo.json"), {}) or {}
    if datos.get("estado") == "pensando" and proyecto.raiz not in _EN_MARCHA:
        datos["estado"] = "error"
        datos["error"] = "se corto (el estudio se reinicio); vuelve a pedirlo"
    return datos


def _guardar_seo(proyecto, datos):
    os.makedirs(carpeta_de(proyecto), exist_ok=True)
    medios.escribir_json(os.path.join(carpeta_de(proyecto), "seo.json"), datos)


def _mmss(segundos):
    s = int(max(0, float(segundos or 0)))
    return f"{s // 60}:{s % 60:02d}"


def generar_seo(proyecto, titulo, escenas, idioma="es", tipo="video", canal=""):
    """Lanza en un hilo el kit SEO. `escenas`: [{t_in, narracion}] del plan."""
    with _CANDADO:
        if proyecto.raiz in _EN_MARCHA:
            return leer_seo(proyecto)
        _EN_MARCHA.add(proyecto.raiz)
    previo = leer_seo(proyecto)
    _guardar_seo(proyecto, dict(previo, estado="pensando", error="", desde=time.time()))
    lineas, ultimo = [], -999.0
    for e in escenas or []:
        t = float(e.get("t_in") or 0)
        texto = " ".join(str(e.get("narracion") or "").split())
        if not texto:
            continue
        if t - ultimo >= 20 or not lineas:
            lineas.append(f"[{_mmss(t)}] {texto}")
            ultimo = t
        else:
            lineas[-1] += " " + texto
    duracion = max([float(e.get("t_out") or 0) for e in escenas or []] or [0])
    instruccion = INSTRUCCION.format(
        idioma={"es": "español", "en": "inglés", "pt": "portugués"}.get(idioma, idioma),
        titulo=titulo, tipo=tipo, duracion=_mmss(duracion) + " min",
        canal=canal or "(sin describir)", guion="\n".join(lineas)[:14000])

    def correr():
        try:
            datos, texto = None, ""
            for intento in range(2):
                pedido = instruccion if not intento else instruccion + "\nSOLO el JSON."
                texto, _ = cli_claude.ejecutar(pedido, modelo="sonnet", esfuerzo="medium",
                                               cwd=tempfile.gettempdir(), tiempo_max_s=300,
                                               extra=["--no-session-persistence"],
                                               para="escribir el SEO del video")
                encaje = re.search(r"\{.*\}", texto or "", re.S)
                try:
                    datos = json.loads(encaje.group(0)) if encaje else None
                except ValueError:
                    datos = None
                if isinstance(datos, dict) and datos.get("youtube"):
                    break
                datos = None
            if not datos:
                raise ValueError("la respuesta no trae el kit: " + " ".join(str(texto).split())[:160])
            limpio = {p: datos.get(p) if isinstance(datos.get(p), dict) else {} for p in PLATAFORMAS}
            _guardar_seo(proyecto, dict(limpio, estado="listo",
                                        fecha=time.strftime("%Y-%m-%dT%H:%M:%S")))
        except Exception as fallo:                          # noqa: BLE001
            _guardar_seo(proyecto, dict(previo, estado="error",
                                        error=f"{type(fallo).__name__}: {str(fallo)[:300]}"))
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(proyecto.raiz)

    threading.Thread(target=correr, daemon=True, name="seo").start()
    return leer_seo(proyecto)
