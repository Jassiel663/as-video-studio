"""
IDEAS Y NICHO: Claude estudia el nicho de un estilo y propone videos concretos.

Para que sirve: un estilo sabe COMO se cuenta (tono, voz, dibujo) pero no DE QUE
hablar. Esto mira el estilo --su tono, su idioma, lo que ya se ha hecho con el--
y BUSCA EN INTERNET que funciona hoy en ese nicho en YouTube: formatos, temas
que tiran, como son los titulos y las miniaturas de los canales que crecen.
Devuelve:

    nicho     de que va, para quien, que funciona y que esta saturado
    ideas     videos concretos con titulo, gancho, por que funcionarian y el
              material de partida (lo que se pega en el encargo)
    mejoras   sugerencias para el canal: ritmo, titulos, miniaturas, shorts

Va por la suscripcion del CLI de Claude (sin coste) y con WebSearch/WebFetch
permitidos: es lo unico del estudio que sale a buscar, y es justo para esto.
Tarda unos minutos, asi que corre en un hilo y deja su estado en un fichero
(`datos/ideas/<estilo>.json`) que la pantalla va mirando. Lo ultimo estudiado
se queda guardado: volver a la pantalla no vuelve a gastar tiempo.
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

CARPETA = os.environ.get("ESTUDIO_IDEAS") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "ideas")

#: Diez minutos de tope: buscar y leer una docena de paginas cabe de sobra.
TIEMPO_MAX_S = 600

SOLO_WEB = ("WebSearch", "WebFetch")
VETADAS = tuple(h for h in cli_claude.HERRAMIENTAS_VETADAS if h not in SOLO_WEB)

INSTRUCCION = """Eres estratega de contenido de YouTube. Te paso un canal (su \
estilo, su tono y lo que ya ha publicado). Estudia SU NICHO con busquedas reales \
en internet (YouTube, Google, blogs de creadores, noticias del tema) y dime que \
hacer.

EL CANAL
- Nombre del estilo: {nombre}
- Idioma de los videos: {idioma}
- Como habla (tono): {tono}
- Como se ve: {estetica}
- Videos ya hechos: {hechos}
{enfoque}
QUE QUIERO, buscando de verdad (cita lo que encuentres, no inventes cifras):
1. EL NICHO: de que va este tipo de canal, quien lo ve, que formatos y temas \
estan funcionando AHORA (2026), que esta saturado y que hueco hay.
2. {cuantas} IDEAS DE VIDEO concretas para este canal, variadas. Para cada una: \
titulo (como se publicaria, en el idioma del canal), gancho de los primeros 5 \
segundos, por que funcionaria (con lo que viste), tipo ("video", "documental" si \
encaja con material real de archivo/stock, o "short"), duracion en minutos, y \
el MATERIAL: 5-10 lineas con los hechos, datos y el orden de la historia, listo \
para que un guionista escriba el video.
3. MEJORAS para el canal: 4-6 sugerencias practicas (titulos, miniaturas, \
ritmo, frecuencia, shorts, series).

Contesta SOLO con un JSON asi (todo el texto en {idioma}):
{{"nicho": {{"resumen": "...", "publico": "...", "funciona": ["..."], \
"saturado": ["..."], "hueco": "...", "fuentes": ["url o nombre"]}},
 "ideas": [{{"titulo": "...", "gancho": "...", "por_que": "...", "tipo": "video", \
"minutos": 8, "material": "..."}}],
 "mejoras": ["..."]}}
"""

_NOMBRES_IDIOMA = {"es": "español", "en": "inglés", "pt": "portugués",
                   "fr": "francés", "it": "italiano", "de": "alemán"}

_EN_MARCHA = set()
_CANDADO = threading.Lock()


def ruta_de(estilo_id):
    seguro = re.sub(r"[^A-Za-z0-9_-]", "_", str(estilo_id))[:80]
    return os.path.join(CARPETA, f"{seguro}.json")


def leer(estilo_id):
    """Lo ultimo estudiado de este estilo, con su estado. -> dict"""
    datos = medios.leer_json(ruta_de(estilo_id), {}) or {}
    if datos.get("estado") == "pensando" and estilo_id not in _EN_MARCHA:
        # un reinicio del servicio a mitad: el hilo ya no existe
        datos["estado"] = "error"
        datos["error"] = "se corto (el estudio se reinicio); vuelve a pedirlo"
    return datos


def _guardar(estilo_id, datos):
    os.makedirs(CARPETA, exist_ok=True)
    medios.escribir_json(ruta_de(estilo_id), datos)


def _ficha_del_canal(preset, hechos):
    datos = preset.get("datos") or {}
    origen = datos.get("origen") or {}
    guion = datos.get("guion") or {}
    idioma = (guion.get("idioma_salida") or origen.get("idioma") or "es")
    tono = " ".join(str(origen.get("tono_prompt") or guion.get("instrucciones")
                        or "").split())[:900]
    estetica = " ".join(str(origen.get("estilo_prompt") or "").split())[:400]
    return {
        "nombre": preset.get("nombre") or preset.get("id"),
        "idioma": _NOMBRES_IDIOMA.get(idioma, idioma),
        "tono": tono or "(sin describir)",
        "estetica": estetica or "(sin describir)",
        "hechos": "; ".join(hechos[:25]) or "ninguno todavia",
    }


def estudiar(estilo_id, hechos=(), enfoque="", cuantas=8):
    """Lanza el estudio en un hilo. -> lo que hay guardado (estado pensando).

    `hechos` son los nombres de los videos ya hechos con el estilo (para no
    repetirlos), `enfoque` lo que quien pide quiera priorizar («mas
    documentales», «temas de dinero»).
    """
    preset = presets_canal.leer(estilo_id)
    if not preset:
        raise ValueError(f"no hay ningun estilo '{estilo_id}'")
    with _CANDADO:
        if estilo_id in _EN_MARCHA:
            return leer(estilo_id)
        _EN_MARCHA.add(estilo_id)
    previo = medios.leer_json(ruta_de(estilo_id), {}) or {}
    _guardar(estilo_id, dict(previo, estado="pensando", desde=time.time(), error=""))
    ficha = _ficha_del_canal(preset, list(hechos))
    texto_enfoque = (f"- Lo que quiere priorizar: {' '.join(str(enfoque).split())[:400]}\n"
                     if str(enfoque or "").strip() else "")
    instruccion = INSTRUCCION.format(enfoque=texto_enfoque,
                                     cuantas=max(3, min(int(cuantas or 8), 12)), **ficha)

    def correr():
        arranque = time.time()
        try:
            texto, _ = cli_claude.ejecutar(
                instruccion, modelo="sonnet", esfuerzo="medium",
                cwd=tempfile.gettempdir(), tiempo_max_s=TIEMPO_MAX_S,
                herramientas_vetadas=VETADAS, herramientas_permitidas=SOLO_WEB,
                extra=["--no-session-persistence"],
                para=f"estudiar el nicho de «{ficha['nombre']}»")
            encaje = re.search(r"\{.*\}", texto or "", re.S)
            datos = json.loads(encaje.group(0)) if encaje else None
            if not isinstance(datos, dict) or not datos.get("ideas"):
                raise ValueError("la respuesta no trae ideas")
            ideas = [i for i in datos.get("ideas") or [] if isinstance(i, dict)
                     and str(i.get("titulo") or "").strip()]
            _guardar(estilo_id, {
                "estado": "listo", "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "segundos": round(time.time() - arranque),
                "enfoque": str(enfoque or ""),
                "nicho": datos.get("nicho") if isinstance(datos.get("nicho"), dict) else {},
                "ideas": ideas,
                "mejoras": [str(m) for m in datos.get("mejoras") or [] if str(m).strip()],
            })
        except Exception as fallo:                          # noqa: BLE001
            _guardar(estilo_id, dict(previo, estado="error",
                                     error=f"{type(fallo).__name__}: {str(fallo)[:300]}"))
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(estilo_id)

    threading.Thread(target=correr, daemon=True, name=f"ideas-{estilo_id}").start()
    return leer(estilo_id)
