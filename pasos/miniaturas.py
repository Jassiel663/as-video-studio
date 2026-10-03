"""
MINIATURAS DE YOUTUBE: tres propuestas por video, dibujadas en el estilo del canal.

La miniatura es la mitad de lo que decide si alguien pulsa. Esto lee el guion
(titulo y gancho) y:

  1. CLAUDE PROPONE tres conceptos distintos (suscripcion, sin coste): el texto
     grande de la miniatura (2-5 palabras, nunca el titulo entero), que se ve,
     la emocion de la cara, y por que haria pulsar.
  2. SE DIBUJAN con el motor de imagen en 16:9, con las laminas del estilo y las
     hojas de los personajes del video como referencia (que el protagonista sea
     el mismo), ~0,07 $ cada una en calidad media.

Se guardan en el proyecto (`miniaturas/`) con su ficha. Rehacer una con nota
(«mas grande el texto», «que se le vea asustado») vuelve a dibujar solo esa.
"""
import glob
import json
import os
import re
import tempfile
import threading
import time

try:
    from . import cli_claude, medios, p6_assets
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import medios
    import p6_assets

CALIDAD = "medium"
_CANDADO = threading.Lock()
_EN_MARCHA = set()

INSTRUCCION = """Eres disenador de miniaturas de YouTube de canales que crecen. \
Te paso el titulo y el guion de un video. Propon {cuantas} miniaturas MUY \
distintas entre si (no variaciones de la misma idea).

TITULO: {titulo}
IDIOMA DEL CANAL: {idioma}
PERSONAJES QUE SALEN: {reparto}
{indicaciones}
GUION (resumen del principio):
{guion}

Reglas de una buena miniatura: UNA idea que se entiende en 1 segundo en un \
movil; texto grande de 2 a 5 palabras como mucho (que NO repita el titulo, que \
lo complete); una cara con emocion fuerte si hay personaje; contraste alto; \
nada de detalles pequenos.

Devuelve SOLO un JSON: {{"miniaturas": [{{"texto": "<2-5 palabras, en el idioma \
del canal, puede ser ''>", "escena": "<que se ve, en ingles, 30-60 palabras: \
sujeto, accion, emocion de la cara, fondo, encuadre>", "por_que": "<una frase, \
en el idioma del canal>"}}]}}
"""


def carpeta_de(proyecto):
    return os.path.join(proyecto.raiz, "miniaturas")


def ruta_ficha(proyecto):
    return os.path.join(carpeta_de(proyecto), "miniaturas.json")


def leer(proyecto):
    datos = medios.leer_json(ruta_ficha(proyecto), {}) or {}
    datos.setdefault("miniaturas", [])
    if datos.get("estado") == "pensando" and proyecto.raiz not in _EN_MARCHA:
        datos["estado"] = "error"
        datos["error"] = "se corto (el estudio se reinicio); vuelve a pedirlas"
    return datos


def _guardar(proyecto, datos):
    os.makedirs(carpeta_de(proyecto), exist_ok=True)
    medios.escribir_json(ruta_ficha(proyecto), datos)


def _referencias(proyecto, estilo, max_reparto=2):
    """Laminas del estilo (caras y cuerpos) y las hojas del reparto del video."""
    refs = [r for r in (estilo or {}).get("referencias") or []
            if isinstance(r, str) and os.path.exists(r)
            and any(e in os.path.basename(r) for e in ("cara", "cuerpos"))][:2]
    hojas = sorted(glob.glob(os.path.join(proyecto.raiz, "pasos", "assets", "v*",
                                          "reparto", "*.png")), reverse=True)
    vistas, reparto = set(), []
    for hoja in hojas:
        nombre = os.path.basename(hoja)
        if nombre not in vistas:
            vistas.add(nombre)
            reparto.append(hoja)
    return refs, reparto[:max_reparto]


def _prompt(concepto, estilo, idioma, con_reparto, nota=""):
    lineas = ["Design a YouTube THUMBNAIL, 16:9, to be seen small on a phone.",
              "The first reference images are the STYLE SHEET of the channel: draw "
              "in exactly that style -- line, palette, shapes -- never copy their content."]
    lineas.extend(p6_assets.guia_escrita(estilo or {}))
    if con_reparto:
        lineas.append("The following reference images are CAST SHEETS: the characters "
                      "in the thumbnail are these exact characters -- same face, hair "
                      "and clothes.")
    lineas.append(f"Scene: {concepto.get('escena', '')}.")
    texto = str(concepto.get("texto") or "").strip()
    if texto:
        lineas.append(f"Big bold text on the thumbnail, exactly this and nothing else, "
                      f"spelled exactly (language: {idioma}): \"{texto}\". Huge, "
                      f"high-contrast, with a thick outline, occupying a large part of "
                      f"the frame without covering the main face.")
    else:
        lineas.append("No text at all in the image.")
    lineas.append("One clear focal point, strong contrast, saturated colours, "
                  "simple background, an expressive face if there is a character. "
                  "No watermark, no YouTube interface, no small text.")
    if nota:
        lineas.append(f"The creator looked at the previous version and asked for "
                      f"this change, which is NOT optional: {nota}.")
    return " ".join(lineas)


def _dibujar(proyecto, indice, concepto, estilo, idioma, nota=""):
    refs, reparto = _referencias(proyecto, estilo)
    imagen = medios.motor("imagen_openai/imagen.py")
    cache = os.path.join(carpeta_de(proyecto), "_cache")
    todas = [imagen.normalizar(r, cache) for r in refs + reparto]
    png, meta = imagen.generar(_prompt(concepto, estilo, idioma, bool(reparto), nota),
                               todas, quality=CALIDAD, tamano="apaisado")
    destino = os.path.join(carpeta_de(proyecto), f"miniatura_{indice + 1}.png")
    with open(destino, "wb") as fh:
        fh.write(png)
    return destino, float(meta.get("coste") or 0)


def _contexto_coste(proyecto):
    """Lo que se gasta se apunta en el proyecto (paso «miniaturas»)."""
    import contextlib
    try:
        from nucleo import coste as COSTE
        from nucleo.proyecto import Proyecto
    except ImportError:
        return contextlib.nullcontext()
    if not isinstance(proyecto, Proyecto):
        return contextlib.nullcontext()
    return COSTE.contexto(proyecto, "miniaturas")


def proponer(proyecto, titulo, guion, estilo, idioma="es", reparto="", indicaciones="",
             cuantas=3):
    """Lanza en un hilo: Claude propone y se dibujan. -> lo guardado (pensando)"""
    with _CANDADO:
        if proyecto.raiz in _EN_MARCHA:
            return leer(proyecto)
        _EN_MARCHA.add(proyecto.raiz)
    previo = leer(proyecto)
    _guardar(proyecto, dict(previo, estado="pensando", error="", desde=time.time()))

    def correr():
        try:
            texto, _ = cli_claude.ejecutar(
                INSTRUCCION.format(
                    cuantas=cuantas, titulo=titulo, idioma=idioma,
                    reparto=reparto or "(ninguno fijo)",
                    indicaciones=(f"LO QUE PIDE EL CREADOR: {indicaciones}\n"
                                  if str(indicaciones or "").strip() else ""),
                    guion=" ".join(str(guion).split())[:6000]),
                modelo="sonnet", esfuerzo="medium", cwd=tempfile.gettempdir(),
                tiempo_max_s=300, extra=["--no-session-persistence"],
                para="proponer miniaturas")
            encaje = re.search(r"\{.*\}", texto or "", re.S)
            conceptos = [c for c in (json.loads(encaje.group(0)) if encaje else {})
                         .get("miniaturas") or [] if isinstance(c, dict)][:cuantas]
            if not conceptos:
                raise ValueError("Claude no ha propuesto ninguna miniatura")
            hechas = []
            with _contexto_coste(proyecto):
                for i, concepto in enumerate(conceptos):
                    ruta, coste = _dibujar(proyecto, i, concepto, estilo, idioma)
                    hechas.append({"n": i + 1, "texto": concepto.get("texto", ""),
                                   "escena": concepto.get("escena", ""),
                                   "por_que": concepto.get("por_que", ""),
                                   "fichero": os.path.basename(ruta), "version": 1,
                                   "coste": round(coste, 3)})
                    _guardar(proyecto, {"estado": "pensando", "desde": time.time(),
                                        "miniaturas": hechas})
            _guardar(proyecto, {"estado": "listo", "miniaturas": hechas,
                                "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                "estilo": estilo and True, "idioma": idioma})
        except Exception as fallo:                          # noqa: BLE001
            _guardar(proyecto, dict(leer(proyecto), estado="error",
                                    error=f"{type(fallo).__name__}: {str(fallo)[:300]}"))
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(proyecto.raiz)

    threading.Thread(target=correr, daemon=True, name="miniaturas").start()
    return leer(proyecto)


def rehacer(proyecto, n, nota, estilo, idioma="es", texto=None):
    """Vuelve a dibujar la miniatura `n` con una nota (y otro texto si se da)."""
    datos = leer(proyecto)
    elegida = next((m for m in datos["miniaturas"] if m.get("n") == int(n)), None)
    if not elegida:
        raise ValueError(f"no hay miniatura {n}")
    with _CANDADO:
        if proyecto.raiz in _EN_MARCHA:
            return datos
        _EN_MARCHA.add(proyecto.raiz)
    if texto is not None:
        elegida["texto"] = " ".join(str(texto).split())[:60]
    _guardar(proyecto, dict(datos, estado="pensando", error="", desde=time.time()))

    def correr():
        try:
            with _contexto_coste(proyecto):
                _, coste = _dibujar(proyecto, int(n) - 1, elegida, estilo, idioma,
                                    nota=" ".join(str(nota or "").split())[:500])
            elegida["version"] = int(elegida.get("version") or 1) + 1
            elegida["coste"] = round(float(elegida.get("coste") or 0) + coste, 3)
            _guardar(proyecto, dict(datos, estado="listo", error=""))
        except Exception as fallo:                          # noqa: BLE001
            _guardar(proyecto, dict(datos, estado="error",
                                    error=f"{type(fallo).__name__}: {str(fallo)[:300]}"))
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(proyecto.raiz)

    threading.Thread(target=correr, daemon=True, name="miniatura").start()
    return leer(proyecto)
