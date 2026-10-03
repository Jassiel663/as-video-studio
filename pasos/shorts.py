"""
La zona Shorts: que estilos son canales de shorts, y los shorts GRATIS.

Hay tres maneras de tener un short, y dos viven fuera de aqui:

  desde cero      un video nuevo con un canal de shorts (crear_video_light con
                  `short`): vertical y de 15 a 60 s. Se paga como un video.
  desde un video  `POST /short` de app.py: el mismo material, guion corto
                  nuevo y vertical de verdad. Se paga como un video corto.
  recorte         AQUI. Un trozo del video YA MONTADO, llevado a vertical con
                  ffmpeg. Las imagenes, la voz y la musica ya estan pagadas:
                  cuesta CERO dolares, solo maquina.

EL RECORTE SE CORTA EN LOS LIMITES DE PLANO, nunca a mitad: un plano del plan
es una frase dicha entera, asi que cortar ahi es no cortar a mitad de palabra.
El trozo lo elige quien lo pide (un segundo de inicio) o Claude, leyendo el
guion con sus tiempos y buscando el tramo con mejor gancho que se entienda
solo. Claude va por la suscripcion y no suma al gasto.

LOS CANALES DE SHORTS son estilos de canal normales con una marca. La marca
vive aparte (shorts.json, junto a tarifas.json: en el servidor, en datos/) y
no dentro del preset, para no tocar el formato de los presets ni su firma.
"""
import json
import os
import re
import subprocess
import time
import uuid

try:
    from nucleo import coste as COSTE
except ImportError:                                   # corriendo desde pasos/
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from nucleo import coste as COSTE
from nucleo.proyecto import ahora, escribir_json, leer_json

import cli_claude
import comun
import medios

DURACION_S = (15, 60)
ENCUADRES = {
    "fondo": "el plano entero en el centro, con el mismo video desenfocado "
             "arriba y abajo",
    "centro": "pantalla completa, recortando los lados del plano",
}
CARPETA_RECORTES = "recortes"


def _ruta():
    return (os.environ.get("ESTUDIO_SHORTS")
            or os.path.join(os.path.dirname(os.path.abspath(COSTE.RUTA_TARIFAS)),
                            "shorts.json"))


def _leer():
    datos = leer_json(_ruta())
    datos = datos if isinstance(datos, dict) else {}
    canales = datos.get("canales")
    return {"canales": [str(c) for c in canales] if isinstance(canales, list) else []}


def canales():
    """Los ids de los estilos que son canales de shorts."""
    return _leer()["canales"]


def marcar_canal(preset_id, es_short):
    """Marca o desmarca un estilo como canal de shorts. -> canales()"""
    preset_id = str(preset_id or "").strip()
    if not preset_id:
        raise ValueError("falta el estilo")
    datos = _leer()
    lista = [c for c in datos["canales"] if c != preset_id]
    if es_short:
        lista.append(preset_id)
    datos["canales"] = lista
    escribir_json(_ruta(), datos)
    return lista


# ------------------------------------------------------------------ recortes

def _carpeta(proyecto):
    return os.path.join(proyecto.raiz, CARPETA_RECORTES)


def recortes(proyecto):
    """Los recortes hechos de un video, del mas nuevo al mas viejo."""
    lista = leer_json(os.path.join(_carpeta(proyecto), "recortes.json"))
    lista = lista if isinstance(lista, list) else []
    vivos = [r for r in lista
             if os.path.exists(os.path.join(_carpeta(proyecto), r.get("fichero") or ""))]
    return sorted(vivos, key=lambda r: str(r.get("creado") or ""), reverse=True)


def _guardar_lista(proyecto, lista):
    escribir_json(os.path.join(_carpeta(proyecto), "recortes.json"), lista)


def borrar_recorte(proyecto, rid):
    """Quita un recorte (el mp4 y su ficha). Se puede volver a sacar gratis."""
    lista = leer_json(os.path.join(_carpeta(proyecto), "recortes.json"))
    lista = lista if isinstance(lista, list) else []
    queda = []
    borrado = False
    for r in lista:
        if r.get("id") == rid:
            borrado = True
            try:
                os.remove(os.path.join(_carpeta(proyecto), r.get("fichero") or ""))
            except OSError:
                pass
        else:
            queda.append(r)
    if not borrado:
        raise KeyError(rid)
    _guardar_lista(proyecto, queda)
    return queda


def planos(proyecto):
    """[{id, desde, hasta, texto}] en segundos DEL MP4 (el primero empieza en 0)."""
    plan = comun.leer_salida(proyecto, "assets", "plan.json", obligatorio=False) or {}
    escenas = plan.get("escenas") or []
    if not escenas:
        return []
    cero = float(escenas[0]["t_in"])
    return [{"id": e["id"], "desde": round(float(e["t_in"]) - cero, 3),
             "hasta": round(float(e["t_out"]) - cero, 3),
             "texto": " ".join(str(e.get("narracion") or "").split())}
            for e in escenas]


def tramo_desde(lista, inicio_s, duracion_s):
    """(primero, ultimo) indices de planos: empieza en el plano que contiene
    `inicio_s` y acaba en el limite de plano mas cercano a la duracion pedida,
    sin pasarse del maximo."""
    if not lista:
        raise ValueError("este video no tiene planos")
    primero = 0
    for i, p in enumerate(lista):
        if p["desde"] <= inicio_s < p["hasta"]:
            primero = i
            break
        if p["desde"] > inicio_s:
            primero = i
            break
    else:
        primero = len(lista) - 1
    return primero, _ultimo_para(lista, primero, duracion_s)


def _ultimo_para(lista, primero, duracion_s):
    objetivo = lista[primero]["desde"] + float(duracion_s)
    maximo = lista[primero]["desde"] + DURACION_S[1]
    mejor = primero
    for i in range(primero, len(lista)):
        if lista[i]["hasta"] > maximo + 0.01:
            break
        mejor = i
        if lista[i]["hasta"] >= objetivo:
            # el limite de plano mas cercano al objetivo, por arriba o por abajo
            if (i > primero and objetivo - lista[i - 1]["hasta"]
                    < lista[i]["hasta"] - objetivo):
                mejor = i - 1
            break
    return mejor


INSTRUCCION_TRAMO = """Eres editor de YouTube Shorts. Abajo esta el guion de un video
ya montado, plano a plano, con sus tiempos en segundos.

Elige UN tramo seguido de planos que funcione SOLO como short de unos
{segundos} segundos (entre {minimo} y {maximo}): que el primer plano enganche
(una pregunta, una cifra sorprendente, un giro) y que se entienda sin haber
visto el resto. Mejor un momento fuerte del medio que la introduccion.

Contesta SOLO con este JSON, sin nada alrededor:
{{"desde": "<id del primer plano>", "hasta": "<id del ultimo plano>",
  "titulo": "<titulo corto para el short, en el idioma del guion>"}}

GUION
{guion}
"""


def tramo_auto(lista, duracion_s, cwd=None):
    """(primero, ultimo, titulo, por_claude). Si Claude falla, el principio, y
    `por_claude` en False para que el recorte lo diga en vez de fingir que lo
    eligio el."""
    guion = "\n".join(f"{p['id']} [{p['desde']:.1f}-{p['hasta']:.1f}] {p['texto']}"
                      for p in lista)
    instruccion = INSTRUCCION_TRAMO.format(segundos=int(duracion_s),
                                           minimo=DURACION_S[0], maximo=DURACION_S[1],
                                           guion=guion[:60000])
    try:
        texto, _ = cli_claude.ejecutar(instruccion, modelo="sonnet", esfuerzo="medium",
                                       cwd=cwd, tiempo_max_s=240,
                                       para="elegir el tramo de un short")
        encaje = re.search(r"\{.*\}", texto or "", re.S)
        eleccion = json.loads(encaje.group(0)) if encaje else {}
    except Exception:                                   # noqa: BLE001
        eleccion = {}
    ids = [p["id"] for p in lista]
    if eleccion.get("desde") in ids:
        primero = ids.index(eleccion["desde"])
        ultimo = ids.index(eleccion["hasta"]) if eleccion.get("hasta") in ids else primero
        ultimo = max(primero, ultimo)
        largo = lista[ultimo]["hasta"] - lista[primero]["desde"]
        # EL INICIO LO DECIDE CLAUDE, LA DURACION QUIEN LO PIDE. Si su tramo se
        # sale de los limites o se aleja de lo pedido (pidiendo 45 s eligio 55
        # en la primera prueba), el final se lleva al limite de plano mas
        # cercano a la duracion elegida
        if (not DURACION_S[0] <= largo <= DURACION_S[1]
                or abs(largo - float(duracion_s)) > max(6.0, 0.15 * float(duracion_s))):
            ultimo = _ultimo_para(lista, primero, duracion_s)
        return primero, ultimo, str(eleccion.get("titulo") or "").strip()[:80], True
    primero, ultimo = tramo_desde(lista, 0.0, duracion_s)
    return primero, ultimo, "", False


def _filtro(encuadre, ancho=1080, alto=1920):
    if encuadre == "centro":
        return (f"[0:v]scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
                f"crop={ancho}:{alto},format=yuv420p[v]")
    return (f"[0:v]split[a][b];"
            f"[a]scale={ancho}:{alto}:force_original_aspect_ratio=increase,"
            f"crop={ancho}:{alto},boxblur=25:2,eq=brightness=-0.15[fondo];"
            f"[b]scale={ancho}:-2[frente];"
            f"[fondo][frente]overlay=0:(H-h)/2,format=yuv420p[v]")


def cortar(mp4, desde, hasta, encuadre, destino):
    """El trozo [desde, hasta] del mp4, en vertical 1080x1920. -> destino"""
    duracion = max(0.5, float(hasta) - float(desde))
    fundido = max(0.0, duracion - 1.2)
    orden = [medios.ffmpeg(), "-y", "-loglevel", "error",
             "-ss", f"{float(desde):.3f}", "-i", mp4, "-t", f"{duracion:.3f}",
             "-filter_complex",
             _filtro(encuadre) + f";[0:a]afade=t=in:d=0.3,afade=t=out:st={fundido:.3f}:d=1.2[a]",
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", destino]
    proceso = subprocess.run(orden, capture_output=True, text=True, timeout=1800,
                             **medios.SIN_VENTANA)
    if proceso.returncode != 0 or not os.path.exists(destino):
        raise RuntimeError(f"ffmpeg no pudo sacar el recorte: {proceso.stderr[-400:]}")
    return destino


def hacer_recorte(proyecto, duracion_s, encuadre="fondo", inicio_s=None,
                  avisar=None, cwd=None, viral=False):
    """Saca un short GRATIS del video montado. -> ficha del recorte"""
    avisar = avisar or (lambda *a, **k: None)
    if encuadre not in ENCUADRES:
        raise ValueError(f"encuadre desconocido: {encuadre}. Son: {', '.join(ENCUADRES)}")
    mp4 = medios.salida_de(proyecto, "render", claves=("mp4",), patrones=(r"video\.mp4",))
    if not mp4 or not os.path.exists(mp4):
        raise RuntimeError("este video todavia no esta montado: genera el video "
                           "antes de sacarle un short")
    lista = planos(proyecto)
    avisar(0.1, "eligiendo el tramo" if inicio_s is None else "buscando el tramo")
    if inicio_s is None:
        primero, ultimo, titulo, por_claude = tramo_auto(lista, duracion_s, cwd=cwd)
        elegido_por = ("claude" if por_claude
                       else "el principio (Claude no ha contestado)")
    else:
        primero, ultimo = tramo_desde(lista, float(inicio_s), duracion_s)
        titulo, elegido_por = "", "a mano"
    desde, hasta = lista[primero]["desde"], lista[ultimo]["hasta"]
    rid = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    os.makedirs(_carpeta(proyecto), exist_ok=True)
    fichero = f"short_{rid}.mp4"
    avisar(0.3, f"cortando {desde:.0f}-{hasta:.0f} s en vertical")
    cortar(mp4, desde, hasta, encuadre, os.path.join(_carpeta(proyecto), fichero))
    if viral:
        # EDICION VIRAL tambien en el recorte: el gancho (el titulo que eligio
        # Claude, o la primera frase) y la barra de progreso. Sigue siendo 0 $.
        avisar(0.8, "edicion viral: gancho y barra de progreso")
        try:
            import viral as _viral
        except ImportError:
            from . import viral as _viral
        gancho = (titulo or " ".join(lista[primero]["texto"].split()[:5])).upper()[:60]
        try:
            _viral.pulir_en_sitio(os.path.join(_carpeta(proyecto), fichero), gancho)
        except Exception as fallo:                          # noqa: BLE001
            avisar(0.85, f"edicion viral no aplicada: {str(fallo)[:120]}")
    ficha = {"id": rid, "fichero": fichero,
             "ruta": f"{CARPETA_RECORTES}/{fichero}",
             "desde": desde, "hasta": hasta, "duracion": round(hasta - desde, 1),
             "planos": [lista[primero]["id"], lista[ultimo]["id"]],
             "titulo": titulo or lista[primero]["texto"][:60],
             "encuadre": encuadre, "elegido_por": elegido_por, "creado": ahora(),
             "viral": bool(viral)}
    anteriores = leer_json(os.path.join(_carpeta(proyecto), "recortes.json"))
    anteriores = anteriores if isinstance(anteriores, list) else []
    _guardar_lista(proyecto, anteriores + [ficha])
    avisar(1.0, f"short de {ficha['duracion']:.0f} s listo")
    return ficha
