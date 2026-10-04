"""
LA REVISION DEL CONTENIDO de las cuentas (solo en el estudio del admin).

Cada media hora mira lo que las OTRAS cuentas han creado o cambiado -- videos
(nombre, material y guion), shorts trabajados y clippings -- y le pide a Claude
que diga, de cada cosa, si esta bien, si hay que mirarla o si es grave, y por
que. Gratis (la suscripcion del admin). Lo que no esta bien sale en el panel de
admin y llega como aviso (campana y Telegram).

Que se busca: odio o acoso, violencia explicita, contenido sexual, menores en
situaciones inapropiadas, estafas o fraudes (inversiones milagro, suplantar a
marcas o personas), desinformacion peligrosa (salud, emergencias) y copias
integras de contenido ajeno sin aportar nada.

Solo se revisa lo NUEVO o lo que CAMBIO (por la huella de su texto), asi que una
pasada sin novedades no llama a nadie.
"""
import hashlib
import json
import os
import re
import tempfile
import threading
import time

try:
    from . import avisos, cli_claude, medios, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import avisos
    import cli_claude
    import medios
    import presets_canal

DATOS = os.path.dirname(os.path.abspath(presets_canal.FICHERO))
CUENTAS = os.environ.get("ESTUDIO_COPIAS_CUENTAS") or os.path.join(os.path.dirname(DATOS), "cuentas")
FICHERO = os.path.join(DATOS, "moderacion.json")
INTERVALO_S = 30 * 60
POR_LLAMADA = 12
NIVELES = ("ok", "dudoso", "grave")
_CANDADO = threading.Lock()
_ESTADO = {"revisando": False, "error": ""}

INSTRUCCION = """Eres moderador de una plataforma que genera videos con IA. Revisa estos \
contenidos (titulo, material y guion de cada uno) y clasifica cada uno:

  ok      nada que objetar
  dudoso  conviene que lo mire una persona
  grave   claramente prohibido

Prohibido: odio o acoso a personas o grupos; violencia explicita o apologia; contenido \
sexual; menores en situaciones inapropiadas; estafas o fraudes (inversiones o curas \
milagro, suplantar marcas, famosos o instituciones); desinformacion peligrosa (salud, \
emergencias, elecciones); copias integras de contenido ajeno sin aportar nada.
Opiniones, humor, historias o temas delicados tratados con respeto son OK. No seas \
paranoico: en la duda razonable, «dudoso», no «grave».

CONTENIDOS (JSON):
{contenidos}

Contesta SOLO este JSON: {{"revision": [{{"id": "...", "nivel": "ok|dudoso|grave", \
"motivo": "<una frase, vacia si ok>"}}]}}
"""


def leer():
    return medios.leer_json(FICHERO, {}) or {"items": {}, "ultima": 0}


def _guardar(d):
    medios.escribir_json(FICHERO, d)


def _texto_guion(carpeta_proyecto):
    """El guion activo de un proyecto, en texto plano (o '')."""
    guion = os.path.join(carpeta_proyecto, "pasos", "guion")
    activa = (medios.leer_json(os.path.join(guion, "activa.json"), {}) or {}).get("activa")
    versiones = [activa] if activa else sorted(
        (int(n[1:]) for n in (os.listdir(guion) if os.path.isdir(guion) else []) if n[:1] == "v" and n[1:].isdigit()),
        reverse=True)[:1]
    for v in versiones:
        doc = medios.leer_json(os.path.join(guion, f"v{v}", "guion.json"), {}) or {}
        bloques = doc.get("guion") or doc.get("bloques_detalle") or []
        return " ".join(str(b.get("texto") or "") for b in bloques if isinstance(b, dict))
    return ""


def _material(carpeta_proyecto):
    estado = medios.leer_json(os.path.join(carpeta_proyecto, "estado.json"), {}) or {}
    params = (((estado.get("pasos") or {}).get("ingesta") or {}).get("params")) or {}
    return str(params.get("texto") or "")


def contenidos():
    """Todo lo revisable de las otras cuentas. -> [{id, cuenta, tipo, ref, nombre, texto}]"""
    salida = []
    if not os.path.isdir(CUENTAS):
        return salida
    for cuenta in sorted(os.listdir(CUENTAS)):
        datos = os.path.join(CUENTAS, cuenta, "datos")
        proyectos = os.path.join(datos, "proyectos")
        for pid in sorted(os.listdir(proyectos)) if os.path.isdir(proyectos) else []:
            carpeta = os.path.join(proyectos, pid)
            ficha = medios.leer_json(os.path.join(carpeta, "proyecto.json"), {}) or {}
            if not ficha:
                continue
            texto = f"MATERIAL: {_material(carpeta)[:2500]}\nGUION: {_texto_guion(carpeta)[:5000]}"
            salida.append({"id": f"{cuenta}/video/{pid}", "cuenta": cuenta, "tipo": "video", "ref": pid,
                           "nombre": str(ficha.get("nombre") or pid), "texto": texto})
        for tipo, sub, nombre_de, texto_de in (
                ("short", "trabajados", lambda f: f.get("titulo") or f.get("nombre"), lambda f: f.get("texto") or ""),
                ("clipping", "clipping", lambda f: f.get("nombre"), lambda f: " | ".join(
                    f"{c.get('titulo', '')}: {c.get('porque', '')}" for c in f.get("clips") or []) + f" URL: {f.get('url', '')}")):
            base = os.path.join(datos, sub)
            for ident in sorted(os.listdir(base)) if os.path.isdir(base) else []:
                f = medios.leer_json(os.path.join(base, ident, "ficha.json"), {}) or {}
                if not f or f.get("estado") == "trabajando":
                    continue
                salida.append({"id": f"{cuenta}/{tipo}/{ident}", "cuenta": cuenta, "tipo": tipo, "ref": ident,
                               "nombre": str(nombre_de(f) or ident), "texto": str(texto_de(f))[:5000]})
    return salida


def _huella(c):
    return hashlib.sha1((c["nombre"] + "\n" + c["texto"]).encode("utf-8")).hexdigest()[:16]


def _clasificar(lote):
    pedido = [{"id": c["id"], "tipo": c["tipo"], "titulo": c["nombre"], "texto": c["texto"]} for c in lote]
    respuesta, _ = cli_claude.ejecutar(
        INSTRUCCION.format(contenidos=json.dumps(pedido, ensure_ascii=False)), modelo="sonnet", esfuerzo="low",
        cwd=tempfile.gettempdir(), tiempo_max_s=600, extra=["--no-session-persistence"], para="revisar contenido")
    encaje = re.search(r"\{.*\}", respuesta or "", re.S)
    datos = json.loads(encaje.group(0)) if encaje else {}
    salida = {}
    for r in datos.get("revision") or []:
        if isinstance(r, dict) and r.get("id") and r.get("nivel") in NIVELES:
            salida[str(r["id"])] = {"nivel": r["nivel"], "motivo": str(r.get("motivo") or "")[:300]}
    return salida


def revisar(clasificar=None):
    """Una pasada: revisa lo nuevo o cambiado. -> {revisados, avisos}"""
    clasificar = clasificar or _clasificar
    with _CANDADO:
        if _ESTADO["revisando"]:
            return {"revisados": 0, "avisos": 0, "ocupado": True}
        _ESTADO.update(revisando=True, error="")
    try:
        d = leer()
        items = d.setdefault("items", {})
        pendientes = [c for c in contenidos() if (items.get(c["id"]) or {}).get("huella") != _huella(c)]
        revisados = avisados = 0
        for k in range(0, len(pendientes), POR_LLAMADA):
            lote = pendientes[k:k + POR_LLAMADA]
            resultado = clasificar(lote)
            for c in lote:
                r = resultado.get(c["id"])
                if not r:
                    continue                                 # sin respuesta: la siguiente pasada
                previo = items.get(c["id"]) or {}
                items[c["id"]] = {"cuenta": c["cuenta"], "tipo": c["tipo"], "ref": c["ref"], "nombre": c["nombre"],
                                  "nivel": r["nivel"], "motivo": r["motivo"], "huella": _huella(c),
                                  "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                  "visto": previo.get("visto") if previo.get("nivel") == r["nivel"] else False}
                revisados += 1
                if r["nivel"] != "ok" and previo.get("nivel") != r["nivel"]:
                    avisados += 1
                    try:
                        avisos.avisar("moderacion", f"{'🚫' if r['nivel'] == 'grave' else '👀'} @{c['cuenta']}: «{c['nombre'][:60]}»",
                                      f"{'GRAVE' if r['nivel'] == 'grave' else 'Para mirar'} ({c['tipo']}): {r['motivo']}. "
                                      "Míralo en el Panel de admin.")
                    except Exception:                       # noqa: BLE001
                        pass
            _guardar(d)
        # lo que ya no existe (borrado) sale de la lista
        vivos = {c["id"] for c in contenidos()}
        for clave in [k for k in items if k not in vivos]:
            items.pop(clave)
        d["ultima"] = time.time()
        _guardar(d)
        return {"revisados": revisados, "avisos": avisados}
    except Exception as fallo:                              # noqa: BLE001
        _ESTADO["error"] = str(fallo)[:300]
        raise
    finally:
        _ESTADO["revisando"] = False


def marcar_visto(clave, visto=True):
    d = leer()
    if clave not in d.get("items", {}):
        raise ValueError("eso no esta en la revision")
    d["items"][clave]["visto"] = bool(visto)
    _guardar(d)
    return d["items"][clave]


def resumen():
    d = leer()
    items = d.get("items") or {}
    marcados = [dict(v, clave=k) for k, v in items.items() if v.get("nivel") != "ok"]
    # sin ver primero, lo grave antes que lo dudoso, y lo mas nuevo arriba
    marcados.sort(key=lambda v: v.get("fecha", ""), reverse=True)
    marcados.sort(key=lambda v: (v.get("visto") is True, v.get("nivel") != "grave"))
    return {"revisados": len(items), "marcados": marcados, "ultima": d.get("ultima") or 0,
            "revisando": _ESTADO["revisando"], "error": _ESTADO["error"]}


def _bucle():
    time.sleep(300)
    while True:
        try:
            revisar()
        except Exception:                                   # noqa: BLE001
            pass
        time.sleep(INTERVALO_S)


def arrancar():
    # solo el estudio del admin, y nunca en una instancia de prueba
    if os.environ.get("ESTUDIO_CUENTA") or os.environ.get("ESTUDIO_MODERACION_APAGADA") \
            or os.environ.get("ESTUDIO_COPIAS_APAGADAS"):
        return
    threading.Thread(target=_bucle, daemon=True, name="moderacion").start()
