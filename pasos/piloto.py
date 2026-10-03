"""
EL PILOTO AUTOMATICO: cada estilo produce y publica solo, con su presupuesto.

Se configura por estilo («2 videos y 3 shorts a la semana, maximo 15 $ a la
semana, publicalos en mis cuentas») y un reloj en segundo plano (cada minuto)
lo va haciendo, UN video a la vez por estilo, con el MISMO camino que la
pantalla (la API del estudio):

    idea      la siguiente idea sin usar del estudio de nicho del estilo (si no
              hay, se lanza el estudio, gratis, y se espera)
    crear     el video o el short con esa idea como material (gratis)
    guion     tanda guion (gratis)
    dinero    se calcula lo que costaran voz e imagenes. Si no cabe en lo que
              queda del presupuesto de la semana, se espera a la siguiente. Si
              el estilo pide permiso, se para y se avisa con el coste: sigue al
              pulsar «Aprobar». Si no, sigue solo (dentro del presupuesto).
    voz       tanda voz
    render    imagenes y montaje
    publicar  mini estudio del momento + textos, y subida a las cuentas
              conectadas del estilo que esten marcadas
    hecho     se avisa y se apunta

Todo queda en datos/piloto/<estilo>.json, asi que un reinicio del servicio no
pierde por donde iba: el reloj retoma la fase en la que estaba.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    from . import avisos, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import avisos
    import presets_canal

CARPETA = os.environ.get("ESTUDIO_PILOTO") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "piloto")
INTERVALO_S = 60
_CANDADO = threading.Lock()

POR_DEFECTO = {"activo": False, "videos_semana": 1, "shorts_semana": 2, "duracion_s": 300,
               "documental": False, "presupuesto_semana_usd": 10.0, "aprobacion": "pedir",
               "publicar": {"youtube": False, "tiktok": False, "facebook": False},
               "privacidad": "public", "tiktok_modo": "borrador", "enfoque": ""}


def _ruta(estilo_id):
    return os.path.join(CARPETA, f"{re.sub(r'[^A-Za-z0-9_-]', '_', str(estilo_id))[:80]}.json")


def leer(estilo_id):
    d = json.loads(json.dumps(POR_DEFECTO))
    guardado = {}
    try:
        with open(_ruta(estilo_id), "r", encoding="utf-8") as fh:
            guardado = json.load(fh)
    except (OSError, ValueError):
        pass
    d.update({k: v for k, v in guardado.items() if k != "publicar"})
    d["publicar"].update(guardado.get("publicar") or {})
    d.setdefault("hechos", [])
    d.setdefault("usadas", [])
    d.setdefault("en_curso", None)
    d["estilo"] = estilo_id
    return d


def _guardar(estilo_id, d):
    os.makedirs(CARPETA, exist_ok=True)
    temporal = _ruta(estilo_id) + ".tmp"
    with open(temporal, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=1)
    os.replace(temporal, _ruta(estilo_id))


def configurar(estilo_id, cambios):
    with _CANDADO:
        d = leer(estilo_id)
        for k in ("activo", "documental"):
            if k in cambios:
                d[k] = bool(cambios[k])
        for k, tope in (("videos_semana", 14), ("shorts_semana", 21)):
            if k in cambios:
                d[k] = max(0, min(int(cambios[k] or 0), tope))
        if "duracion_s" in cambios:
            d["duracion_s"] = max(60, min(int(cambios["duracion_s"] or 300), 1800))
        if "presupuesto_semana_usd" in cambios:
            d["presupuesto_semana_usd"] = max(0.0, float(cambios["presupuesto_semana_usd"] or 0))
        if cambios.get("aprobacion") in ("pedir", "solo"):
            d["aprobacion"] = cambios["aprobacion"]
        if cambios.get("privacidad") in ("public", "unlisted", "private"):
            d["privacidad"] = cambios["privacidad"]
        if cambios.get("tiktok_modo") in ("borrador", "directo"):
            d["tiktok_modo"] = cambios["tiktok_modo"]
        if "enfoque" in cambios:
            d["enfoque"] = " ".join(str(cambios["enfoque"] or "").split())[:300]
        if isinstance(cambios.get("publicar"), dict):
            for red in ("youtube", "tiktok", "facebook"):
                if red in cambios["publicar"]:
                    d["publicar"][red] = bool(cambios["publicar"][red])
        _guardar(estilo_id, d)
        return d


def listar():
    if not os.path.isdir(CARPETA):
        return []
    return [leer(n[:-5]) for n in sorted(os.listdir(CARPETA)) if n.endswith(".json")]


# ------------------------------------------------------------------ la API

def _api(metodo, ruta, datos=None, tiempo=120):
    base = (os.environ.get("ESTUDIO_API") or "http://127.0.0.1:8110").rstrip("/")
    cuerpo = json.dumps(datos).encode("utf-8") if datos is not None else None
    peticion = urllib.request.Request(base + ruta, data=cuerpo, method=metodo,
                                      headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(peticion, timeout=tiempo) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as fallo:
        try:
            detalle = json.loads(fallo.read().decode("utf-8")).get("error")
        except Exception:                                   # noqa: BLE001
            detalle = str(fallo)
        raise RuntimeError(detalle or str(fallo))


def _q(texto):
    return urllib.parse.quote(str(texto), safe="")


def _semana():
    return time.strftime("%G-W%V")


def _gastado_semana(d):
    return round(sum(float(h.get("usd") or 0) for h in d["hechos"] if h.get("semana") == _semana()), 2)


def _pendiente(d):
    """Que toca hacer ahora: 'video', 'short' o None."""
    semana = [h for h in d["hechos"] if h.get("semana") == _semana()]
    hechos_v = sum(1 for h in semana if h.get("tipo") == "video")
    hechos_s = sum(1 for h in semana if h.get("tipo") == "short")
    total = (d["videos_semana"] or 0) + (d["shorts_semana"] or 0)
    if not total:
        return None
    # REPARTIDOS EN LA SEMANA: no todos el lunes. Uno cada 7/total dias.
    ultimo = max([h.get("ts", 0) for h in d["hechos"]] or [0])
    if time.time() - ultimo < (7 * 86400 / total) * 0.9:
        return None
    if hechos_v < d["videos_semana"] and (hechos_v / max(1, d["videos_semana"])
                                          <= hechos_s / max(1, d["shorts_semana"] or 1)):
        return "video"
    if hechos_s < d["shorts_semana"]:
        return "short"
    if hechos_v < d["videos_semana"]:
        return "video"
    return None


def _aviso(d, tipo, titulo, texto=""):
    nombre = (presets_canal.leer(d["estilo"]) or {}).get("nombre", d["estilo"])
    avisos.avisar(tipo, f"🤖 {nombre}: {titulo}", texto, d["estilo"],
                  os.environ.get("ESTUDIO_URL_PUBLICA") or "")


def _estado_trabajo(tid):
    return _api("GET", f"/api/trabajos/{_q(tid)}")


def _coste(pid, tanda):
    plan = _api("GET", f"/api/proyectos/{_q(pid)}/generar?tanda={tanda}")
    c = plan.get("coste") or {}
    return float(c.get("usd_por_generar", c.get("usd_total", 0)) or 0)


def _lanzar(pid, tanda):
    return _api("POST", f"/api/proyectos/{_q(pid)}/generar", {"tanda": tanda, "modo": "pendientes"}).get("trabajo_id")


def _avanzar(d):
    """Un paso de la maquina de un estilo. Devuelve True si cambio algo."""
    e = d["en_curso"]
    estilo = d["estilo"]
    if e is None:
        tipo = _pendiente(d)
        if not tipo:
            return False
        d["en_curso"] = {"tipo": tipo, "fase": "idea", "desde": time.time()}
        return True

    fase = e["fase"]
    if fase in ("esperando_ok",):
        return False
    if fase == "sin_presupuesto":
        if e.get("semana") != _semana():
            e["fase"] = "dinero"
            return True
        return False

    if fase == "idea":
        ideas = _api("GET", f"/api/presets-light/{_q(estilo)}/ideas")
        if ideas.get("estado") == "pensando":
            return False
        libres = [i for i in ideas.get("ideas") or [] if i.get("titulo") not in d["usadas"]
                  and (i.get("tipo") == "short") == (e["tipo"] == "short")]
        libres = libres or [i for i in ideas.get("ideas") or [] if i.get("titulo") not in d["usadas"]]
        if not libres:
            # sin ideas libres: se estudia el nicho (gratis). Tres intentos y no mas
            e["pedidas_ideas"] = int(e.get("pedidas_ideas") or 0) + 1
            if e["pedidas_ideas"] > 3:
                raise RuntimeError("no salen ideas nuevas del estudio de nicho")
            _api("POST", f"/api/presets-light/{_q(estilo)}/ideas", {"enfoque": d.get("enfoque") or ""})
            return True
        idea = libres[0]
        d["usadas"].append(idea["titulo"])
        e.update(idea=idea["titulo"], material="\n\n".join(x for x in (
            idea.get("titulo"), idea.get("gancho") and f"Gancho: {idea['gancho']}", idea.get("material")) if x),
            fase="crear")
        return True

    if fase == "crear":
        short = e["tipo"] == "short"
        r = _api("POST", f"/api/presets-light/{_q(estilo)}/video", {
            "nombre": e["idea"][:60], "material": e["material"],
            "duracion_objetivo_s": 50 if short else d["duracion_s"],
            "formato": "vertical" if short else "horizontal", "short": short, "viral": True,
            "documental": "mezcla" if (d.get("documental") and not short) else ""})
        e["pid"] = (r.get("proyecto") or {}).get("id")
        e["tid"] = _lanzar(e["pid"], "guion")
        e["fase"] = "guion"
        return True

    if fase in ("guion", "voz", "render", "seo"):
        if fase == "seo":
            seo = (_api("GET", f"/api/proyectos/{_q(e['pid'])}/publicar").get("seo") or {})
            estado = seo.get("estado")
            if estado == "pensando":
                return False
            if estado != "listo":
                raise RuntimeError(f"no se han podido escribir los textos: {seo.get('error')}")
            e["fase"] = "subir"
            return True
        t = _estado_trabajo(e["tid"])
        if t.get("estado") in ("pendiente", "ejecutando"):
            return False
        if t.get("estado") != "listo":
            raise RuntimeError(f"la tanda {fase} ha fallado: {str(t.get('error') or t.get('estado'))[:300]}")
        e["fase"] = {"guion": "dinero", "voz": "lanzar_render", "render": "publicar"}[fase]
        return True

    if fase == "dinero":
        coste = round(_coste(e["pid"], "voz") + _coste(e["pid"], "render"), 2)
        e["coste"] = coste
        queda = round(float(d["presupuesto_semana_usd"]) - _gastado_semana(d), 2)
        if coste > queda:
            e.update(fase="sin_presupuesto", semana=_semana())
            _aviso(d, "piloto", "presupuesto de la semana agotado",
                   f"El siguiente ({e['idea']}) cuesta {coste:.2f} $ y quedan {queda:.2f} $. Sigo la semana que viene.")
            return True
        if d["aprobacion"] == "pedir":
            e["fase"] = "esperando_ok"
            _aviso(d, "aprobar", f"¿Hago «{e['idea']}»?",
                   f"Cuesta unos {coste:.2f} $ (quedan {queda:.2f} $ esta semana). Apruébalo en Piloto automático.")
            return True
        e["fase"] = "lanzar_voz"
        return True

    if fase == "lanzar_voz":
        e.update(tid=_lanzar(e["pid"], "voz"), fase="voz")
        return True
    if fase == "lanzar_render":
        e.update(tid=_lanzar(e["pid"], "render"), fase="render")
        return True

    if fase == "publicar":
        d["hechos"].append({"tipo": e["tipo"], "pid": e["pid"], "idea": e["idea"], "usd": e.get("coste", 0),
                            "semana": _semana(), "ts": time.time(), "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")})
        if not any(d["publicar"].values()):
            _aviso(d, "listo", f"listo: «{e['idea']}»", "Está montado en el estudio, sin publicar (el piloto no tiene redes marcadas).")
            d["en_curso"] = None
            return True
        _api("POST", f"/api/proyectos/{_q(e['pid'])}/publicar/seo", {})
        e["fase"] = "seo"
        return True

    if fase == "subir":
        info = _api("GET", f"/api/proyectos/{_q(e['pid'])}/publicar")
        enviados, fallos = [], []
        for red, quiere in d["publicar"].items():
            if not quiere:
                continue
            conexion = (info.get(red) or {}).get("conexion") or {}
            if not (conexion.get("canal") or conexion.get("cuenta")):
                fallos.append(f"{red}: sin cuenta conectada")
                continue
            try:
                _api("POST", f"/api/proyectos/{_q(e['pid'])}/publicar/{red}", {
                    "privacidad": d["privacidad"], "modo": d["tiktok_modo"]})
                enviados.append(red)
            except Exception as fallo:                      # noqa: BLE001
                fallos.append(f"{red}: {fallo}")
        _aviso(d, "publicado", f"«{e['idea']}» enviado a {', '.join(enviados) or 'ninguna red'}",
               "; ".join(fallos))
        d["en_curso"] = None
        return True
    return False


def tick():
    for d in listar():
        # apagado solo sigue lo que ya esta en marcha (p. ej. «Hacer uno ahora»)
        if not d.get("activo") and not d.get("en_curso"):
            continue
        with _CANDADO:
            d = leer(d["estilo"])
            try:
                cambio = _avanzar(d)
            except Exception as fallo:                      # noqa: BLE001
                e = d.get("en_curso") or {}
                _aviso(d, "error", f"el piloto se ha parado en «{e.get('idea', '?')}»", str(fallo)[:400])
                d["ultimo_error"] = f"{time.strftime('%Y-%m-%d %H:%M')} · {str(fallo)[:300]}"
                d["en_curso"] = None
                cambio = True
            if cambio:
                _guardar(d["estilo"], d)


def aprobar(estilo_id):
    with _CANDADO:
        d = leer(estilo_id)
        if (d.get("en_curso") or {}).get("fase") != "esperando_ok":
            raise ValueError("no hay nada esperando tu aprobacion")
        d["en_curso"]["fase"] = "lanzar_voz"
        _guardar(estilo_id, d)
        return d


def cancelar(estilo_id):
    with _CANDADO:
        d = leer(estilo_id)
        d["en_curso"] = None
        _guardar(estilo_id, d)
        return d


def ahora(estilo_id):
    """Empieza el siguiente ya, sin esperar al reparto de la semana."""
    with _CANDADO:
        d = leer(estilo_id)
        if d.get("en_curso"):
            raise ValueError("ya hay uno en marcha")
        quedan_v = d["videos_semana"] - sum(1 for h in d["hechos"] if h.get("semana") == _semana() and h.get("tipo") == "video")
        d["en_curso"] = {"tipo": "video" if quedan_v > 0 or not d["shorts_semana"] else "short",
                         "fase": "idea", "desde": time.time()}
        _guardar(estilo_id, d)
        return d


def _bucle():
    time.sleep(45)
    while True:
        try:
            tick()
        except Exception:                                   # noqa: BLE001
            pass
        time.sleep(INTERVALO_S)


def arrancar():
    threading.Thread(target=_bucle, daemon=True, name="piloto").start()
