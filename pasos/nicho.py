"""
ESTUDIO DE NICHO DESDE CERO: antes de tener canal, ¿de que hago videos?

pasos/ideas.py estudia el nicho DE UN ESTILO que ya existe. Esto va antes: se
le da un tema --o solo una inquietud vaga («algo de dinero», «me gusta la
historia»)-- y Claude investiga en la web (WebSearch/WebFetch, nada mas) si hay
demanda, quien compite, cuanto se paga por mil vistas en ese tema, que
subnichos tienen hueco, y propone UN CANAL concreto: formato, como se ve, como
habla, que voz, nombres posibles y sus diez primeros videos.

Lo propuesto viene ya con la forma del encargo de un estilo nuevo (nombre,
estilo_prompt, tono_prompt, voz_prompt, idioma, ritmo): «Crear este canal» lo
pasa tal cual a la pantalla de crear estilo.

Gratis (suscripcion del CLI), en un hilo, en datos/nichos/<id>.json.
"""
import json
import os
import re
import tempfile
import threading
import time
import uuid

try:
    from . import cli_claude, ideas, medios, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import ideas
    import medios
    import presets_canal

CARPETA = os.environ.get("ESTUDIO_NICHOS") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "nichos")
_CANDADO = threading.Lock()
_EN_MARCHA = set()

INSTRUCCION = """Eres estratega de canales de YouTube faceless (videos narrados \
con ilustracion o animacion, sin presentador). Alguien quiere empezar un canal y \
te da esto:

TEMA O IDEA: {tema}
IDIOMA DEL CANAL: {idioma}
{notas}{referencias}
Investiga DE VERDAD en internet (YouTube, Google Trends, Social Blade, blogs de \
creadores, datos de RPM/CPM publicados en 2025-2026). No inventes cifras: si no \
encuentras un dato, da un rango y di de donde sale o que es una estimacion.

Contesta SOLO con este JSON, todo el texto en {idioma}:
{{"tema": "<el tema tal como lo entiendes, 3-8 palabras>",
 "resumen": "<el veredicto en 3-4 frases: merece la pena, por que, para quien>",
 "demanda": "<cuanta gente lo busca y si crece o baja>",
 "competencia": "<quien domina, que tan saturado esta>",
 "monetizacion": "<RPM/CPM aproximado en ese idioma y tema, patrocinios, afiliacion>",
 "puntuacion": <1-10, lo recomendable que es para un canal nuevo>,
 "subnichos": [{{"nombre": "...", "por_que": "...", "dificultad": "baja|media|alta"}}],
 "canal": {{
   "nombre": "<el nombre que recomiendas>",
   "alternativas": ["<otros 4 nombres>"],
   "formato": "<que tipo de videos, duracion, frecuencia, shorts si o no>",
   "estilo_prompt": "<como se VE: el estilo de ilustracion en una o dos frases, \
concreto (tecnica, colores, personajes)>",
   "tono_prompt": "<como HABLA el narrador: registro, ritmo, humor, trato al espectador>",
   "voz_prompt": "<como SUENA la voz: genero, edad aparente, energia>",
   "ritmo": "lento|medio|rapido"}},
 "videos": [{{"titulo": "...", "gancho": "...", "tipo": "video|documental|short"}}],
 "riesgos": ["..."],
 "fuentes": ["url o nombre"]}}
Los videos son 10, los subnichos 3-5.
"""

_IDIOMAS = {"es": "español", "en": "inglés", "pt": "portugués", "fr": "francés",
            "it": "italiano", "de": "alemán"}


def _ruta(ident):
    return os.path.join(CARPETA, f"{re.sub(r'[^A-Za-z0-9_-]', '_', str(ident))[:40]}.json")


def leer(ident):
    datos = medios.leer_json(_ruta(ident), {}) or {}
    if datos.get("estado") == "pensando" and ident not in _EN_MARCHA:
        datos["estado"] = "error"
        datos["error"] = "se corto (el estudio se reinicio); vuelve a pedirlo"
    return datos


def listar():
    """Los estudios hechos, del mas reciente al mas antiguo (sin el detalle)."""
    if not os.path.isdir(CARPETA):
        return []
    salida = []
    for nombre in os.listdir(CARPETA):
        if nombre.endswith(".json"):
            d = leer(nombre[:-5])
            salida.append({"id": d.get("id") or nombre[:-5], "tema": d.get("tema") or d.get("pedido"),
                           "pedido": d.get("pedido"), "estado": d.get("estado"),
                           "puntuacion": d.get("puntuacion"), "fecha": d.get("fecha") or "",
                           "canal": (d.get("canal") or {}).get("nombre", "")})
    return sorted(salida, key=lambda x: x["fecha"], reverse=True)


def borrar(ident):
    ruta = _ruta(ident)
    if not os.path.exists(ruta):
        raise ValueError(f"no hay ningun estudio '{ident}'")
    os.remove(ruta)


def _guardar(ident, datos):
    os.makedirs(CARPETA, exist_ok=True)
    medios.escribir_json(_ruta(ident), datos)


def estudiar(tema, idioma="es", notas="", referencias=()):
    """Lanza el estudio en un hilo. -> la ficha (estado pensando)"""
    tema = " ".join(str(tema or "").split())[:400]
    if not tema:
        raise ValueError("di de que tema quieres el estudio (aunque sea una idea vaga)")
    idioma = idioma if idioma in _IDIOMAS else "es"
    referencias = [r for r in (" ".join(str(x).split())[:300] for x in referencias or []) if r][:8]
    ident = time.strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]
    with _CANDADO:
        _EN_MARCHA.add(ident)
    base = {"id": ident, "pedido": tema, "idioma": idioma,
            "notas": " ".join(str(notas or "").split())[:600],
            "referencias": referencias,
            "estado": "pensando", "desde": time.time(), "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _guardar(ident, base)
    instruccion = INSTRUCCION.format(
        tema=tema, idioma=_IDIOMAS[idioma],
        notas=f"LO QUE AÑADE: {base['notas']}\n" if base["notas"] else "",
        referencias=("VIDEOS Y CANALES DE REFERENCIA que le gustan o que son su "
                     "competencia (abrelos o buscalos y estudialos: que hacen bien, como "
                     "titulan, como se ven, como hablan; la propuesta tiene que "
                     "inspirarse en ellos y mejorarlos, y tienen que aparecer en "
                     "«competencia» y en «fuentes»): " + "; ".join(referencias) + "\n")
                    if referencias else "")

    def correr():
        arranque = time.time()
        try:
            datos, texto = None, ""
            for intento in range(2):
                pedido = instruccion if not intento else (
                    instruccion + "\nIMPORTANTE: tu mensaje final debe ser UNICAMENTE el JSON.")
                texto, _ = cli_claude.ejecutar(
                    pedido, modelo="sonnet", esfuerzo="medium", cwd=tempfile.gettempdir(),
                    tiempo_max_s=720, herramientas_vetadas=ideas.VETADAS,
                    herramientas_permitidas=ideas.SOLO_WEB,
                    extra=["--no-session-persistence"], para="estudiar un nicho desde cero")
                encaje = re.search(r"\{.*\}", texto or "", re.S)
                try:
                    datos = json.loads(encaje.group(0)) if encaje else None
                except ValueError:
                    datos = None
                if isinstance(datos, dict) and datos.get("canal"):
                    break
                datos = None
            if not datos:
                raise ValueError("la respuesta no trae el estudio: "
                                 + " ".join(str(texto).split())[:160])
            canal = datos.get("canal") if isinstance(datos.get("canal"), dict) else {}
            if canal.get("ritmo") not in ("lento", "medio", "rapido"):
                canal["ritmo"] = "medio"
            _guardar(ident, {**base, **{k: v for k, v in datos.items() if k != "id"},
                             "canal": canal, "estado": "listo",
                             "segundos": round(time.time() - arranque)})
        except Exception as fallo:                          # noqa: BLE001
            _guardar(ident, dict(base, estado="error",
                                 error=f"{type(fallo).__name__}: {str(fallo)[:300]}"))
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(ident)

    threading.Thread(target=correr, daemon=True, name=f"nicho-{ident}").start()
    return leer(ident)
