"""
LAS PREGUNTAS DE MIND ANTES DEL GUION: pedir lo que falta para un video mejor.

Un guion sale tan bueno como el encargo. Antes de generarlo, Mind lee el
material, el tipo de video y el estilo, y hace las 3-5 preguntas cuya respuesta
mas mejoraria el resultado: para quien es, que tiene que sentir o hacer quien lo
vea, que dato o anecdota falta, que se debe evitar, cual es el gancho. Cada una
trae por que importa y, si se puede, opciones para contestar de un toque.

Las respuestas las pega la pantalla en las indicaciones del encargo, que es lo
que lee el guionista: no hay ningun camino nuevo hasta el guion.

Gratis (suscripcion), en un hilo; vive en memoria (una hora), porque es una
conversacion de un momento, no algo que guardar.
"""
import json
import re
import tempfile
import threading
import time
import uuid

try:
    from . import cli_claude
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude

_PREGUNTAS = {}
_CANDADO = threading.Lock()
VIDA_S = 3600

INSTRUCCION = """Eres el productor de un canal de YouTube. Antes de escribir el \
guion de este {tipo}, revisa el encargo y pregunta al creador SOLO lo que mas \
mejoraria el video si lo supieras (de 3 a 5 preguntas, las mas importantes \
primero). Nada que ya este claro en el material. Piensa en: para quien es, que \
tiene que sentir o hacer quien lo vea, el gancho, datos o anecdotas que faltan, \
lo que hay que evitar, el final.

ESTILO DEL CANAL: {estilo}
TITULO: {nombre}
DURACION: {duracion}
MATERIAL:
{material}
INDICACIONES QUE YA DIO: {indicaciones}

Contesta SOLO un JSON, en español:
{{"preguntas": [{{"pregunta": "...", "por_que": "<una frase>", \
"opciones": ["<2-4 respuestas tipicas, cortas; vacio si es abierta>"]}}]}}
"""


def _limpiar():
    ahora = time.time()
    with _CANDADO:
        for clave in [k for k, v in _PREGUNTAS.items() if ahora - v.get("desde", 0) > VIDA_S]:
            _PREGUNTAS.pop(clave, None)


def leer(ident):
    _limpiar()
    with _CANDADO:
        return dict(_PREGUNTAS.get(ident) or {"estado": "error", "error": "ya no existe"})


def preguntar(material, nombre="", tipo="video", estilo="", duracion_s=0, indicaciones=""):
    """Lanza las preguntas en un hilo. -> {id, estado: pensando}"""
    material = str(material or "").strip()
    if not material and not str(nombre or "").strip():
        raise ValueError("escribe primero el material o el titulo: sin eso no hay nada que preguntar")
    _limpiar()
    ident = uuid.uuid4().hex[:12]
    with _CANDADO:
        _PREGUNTAS[ident] = {"id": ident, "estado": "pensando", "desde": time.time()}
    minutos = round(float(duracion_s or 0) / 60, 1)
    instruccion = INSTRUCCION.format(
        tipo={"short": "short vertical", "documental": "mini documental"}.get(tipo, "video"),
        estilo=" ".join(str(estilo or "(sin describir)").split())[:600],
        nombre=nombre or "(sin titulo)", duracion=f"{minutos} min" if minutos else "(sin decir)",
        material=material[:12000] or "(vacio: solo el titulo)",
        indicaciones=" ".join(str(indicaciones or "ninguna").split())[:1500])

    def correr():
        try:
            texto, _ = cli_claude.ejecutar(instruccion, modelo="sonnet", esfuerzo="low",
                                           cwd=tempfile.gettempdir(), tiempo_max_s=180,
                                           extra=["--no-session-persistence"],
                                           para="las preguntas antes del guion")
            encaje = re.search(r"\{.*\}", texto or "", re.S)
            datos = json.loads(encaje.group(0)) if encaje else {}
            lista = []
            for p in (datos.get("preguntas") or [])[:5]:
                if isinstance(p, dict) and str(p.get("pregunta") or "").strip():
                    lista.append({"pregunta": str(p["pregunta"])[:300],
                                  "por_que": str(p.get("por_que") or "")[:300],
                                  "opciones": [str(o)[:120] for o in (p.get("opciones") or [])
                                               if str(o).strip()][:4]})
            if not lista:
                raise ValueError("Claude no ha devuelto preguntas")
            resultado = {"estado": "listo", "preguntas": lista}
        except Exception as fallo:                          # noqa: BLE001
            resultado = {"estado": "error", "error": f"{type(fallo).__name__}: {str(fallo)[:200]}"}
        with _CANDADO:
            if ident in _PREGUNTAS:
                _PREGUNTAS[ident].update(resultado)

    threading.Thread(target=correr, daemon=True, name="preguntas").start()
    return leer(ident)
