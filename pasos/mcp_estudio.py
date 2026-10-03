"""Las herramientas del Estudio para el asistente: un servidor MCP minimo.

POR QUE EXISTE
--------------
El asistente contestaba «no puedo probar las claves: no tengo acceso a
internet ni ejecuto nada». Y era verdad: tenia Read, Grep y Glob y nada mas. Lo
que la persona espera de una burbuja de ayuda es lo contrario: que PRUEBE las
claves, que mire que trabajo esta parado y por que, que cancele el que se ha
quedado colgado -- desde la primera instalacion y sin que nadie tenga que
darle permisos.

Darle Bash o WebFetch para eso seria darle la puerta entera. Esto es la
alternativa: un puñado de herramientas escritas aqui, con nombre y con
contrato, que el CLI carga como servidor MCP (`--mcp-config`) y que van
PRE-AUTORIZADAS en la orden (`--allowedTools mcp__estudio__...`), de modo que
en headless no hay ninguna pregunta que nadie pueda contestar.

COMO FUNCIONA
-------------
Es un proceso aparte que arranca el propio CLI: JSON-RPC 2.0 por stdin/stdout,
un mensaje por linea (el transporte stdio de MCP). Se implementa a mano y no
con la biblioteca `mcp` porque son cinco metodos (`initialize`, `ping`,
`tools/list`, `tools/call` y la notificacion `initialized`) y una dependencia
mas es una cosa mas que puede faltar en un despliegue.

Cada herramienta llama a la API del Estudio en `ESTUDIO_API` (la pone
`app.py` al arrancar con su propio puerto): no importa codigo de la
aplicacion, habla con ella por contrato, igual que los motores. Asi lo que
hace la herramienta es EXACTAMENTE lo que haria la pantalla, y una ruta que
cambie rompe aqui igual que alli.

Se puede probar a mano:

    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python pasos/mcp_estudio.py
"""
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

API = (os.environ.get("ESTUDIO_API") or "http://127.0.0.1:8020").rstrip("/")
PROYECTO_ABIERTO = os.environ.get("ESTUDIO_PROYECTO_ABIERTO") or ""

#: Tope de lo que se le devuelve al modelo por herramienta. Una bitacora entera
#: o una ficha con 300 unidades no ayudan: se recorta y se dice.
TOPE = 14000

PROTOCOLO = "2024-11-05"


# ------------------------------------------------------------------ HTTP

def _llamar(metodo, ruta, datos=None, tiempo=60):
    """Una peticion a la API del Estudio. -> (codigo, json|texto)"""
    url = API + ruta
    cuerpo = None
    cabeceras = {"Accept": "application/json"}
    if datos is not None:
        cuerpo = json.dumps(datos).encode("utf-8")
        cabeceras["Content-Type"] = "application/json"
    peticion = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=tiempo) as respuesta:
            crudo = respuesta.read().decode("utf-8", errors="replace")
            codigo = respuesta.status
    except urllib.error.HTTPError as fallo:
        crudo = fallo.read().decode("utf-8", errors="replace")
        codigo = fallo.code
    except (urllib.error.URLError, OSError) as fallo:
        return 0, f"no se ha podido hablar con el Estudio en {url}: {fallo}"
    try:
        return codigo, json.loads(crudo)
    except ValueError:
        return codigo, crudo


def _recortar(texto):
    texto = str(texto)
    if len(texto) <= TOPE:
        return texto
    return texto[:TOPE] + f"\n[... recortado: {len(texto) - TOPE} caracteres mas]"


def _error_de(codigo, datos):
    if isinstance(datos, dict) and datos.get("error"):
        return f"el Estudio contesta {codigo}: {datos['error']}"
    return f"el Estudio contesta {codigo}: {_recortar(datos)}"


def _pid(argumentos):
    return str(argumentos.get("proyecto") or PROYECTO_ABIERTO or "").strip()


# ------------------------------------------------------------------ herramientas

def probar_claves(argumentos):
    """Prueba cada clave contra su servicio: OpenAI, Cartesia, Jamendo, FreeSound."""
    con_claude = bool(argumentos.get("claude", False))
    codigo, datos = _llamar("POST", "/api/claves/probar", {"claude": con_claude},
                            tiempo=400 if con_claude else 120)
    if codigo != 200:
        return _error_de(codigo, datos)
    return datos.get("resumen") or json.dumps(datos, ensure_ascii=False, indent=1)


def probar_claude(argumentos):
    """Prueba las cuentas de Claude con una llamada minima y dice cual contesta."""
    codigo, datos = _llamar("POST", "/api/asistente/probar", {}, tiempo=400)
    if codigo != 200:
        return _error_de(codigo, datos)
    lineas = []
    for cuenta in datos.get("cuentas") or []:
        salud = cuenta.get("salud") or {}
        lineas.append(f"- {cuenta.get('etiqueta')}: "
                      + ("con sesion" if cuenta.get("sesion") else "sin sesion")
                      + (f"; {cuenta['motivo']}" if cuenta.get("motivo") else
                         f"; contesta (comprobado {salud.get('cuando', '?')})"))
    lineas.append("el asistente " + ("puede contestar" if datos.get("listo")
                                     else f"NO puede contestar: {datos.get('motivo')}"))
    return "\n".join(lineas)


def estado_estudio(argumentos):
    """La foto del estado del Estudio ahora mismo (claves, proyecto, pasos, trabajos)."""
    consulta = urllib.parse.urlencode({"proyecto": _pid(argumentos)})
    codigo, datos = _llamar("GET", f"/api/asistente/foto?{consulta}")
    if codigo != 200:
        return _error_de(codigo, datos)
    return _recortar(datos.get("foto", ""))


def trabajos(argumentos):
    """Los trabajos de un proyecto (o de todos los abiertos), con su estado y su error."""
    pid = _pid(argumentos)
    consulta = urllib.parse.urlencode({"proyecto": pid, "activos": 0}) if pid else "activos=0"
    codigo, datos = _llamar("GET", f"/api/trabajos?{consulta}")
    if codigo != 200:
        return _error_de(codigo, datos)
    lista = datos.get("trabajos") or []
    if not lista:
        return "no hay trabajos que el servicio recuerde" + (f" en {pid}" if pid else "")
    lineas = []
    for t in lista[:40]:
        lineas.append(
            f"- {t.get('id')}  {t.get('nombre')} [{t.get('paso')}] {t.get('estado')} "
            f"{round(100 * float(t.get('progreso') or 0))} % ({t.get('segundos')} s)"
            + (f"  proyecto={t.get('proyecto')}" if t.get("proyecto") else "")
            + (f"\n    mensaje: {t.get('mensaje')}" if t.get("mensaje") else "")
            + (f"\n    ERROR: {str(t.get('error'))[:900]}" if t.get("error") else ""))
    return _recortar("\n".join(lineas))


def ficha_paso(argumentos):
    """La ficha de un paso de un proyecto: estado, mensaje, params, unidades obsoletas."""
    pid = _pid(argumentos)
    paso = str(argumentos.get("paso") or "").strip()
    if not pid or not paso:
        return "hacen falta 'proyecto' y 'paso'"
    codigo, datos = _llamar("GET", f"/api/proyectos/{urllib.parse.quote(pid)}/pasos/"
                                   f"{urllib.parse.quote(paso)}")
    if codigo != 200:
        return _error_de(codigo, datos)
    ficha = {k: datos.get(k) for k in (
        "id", "nombre", "estado", "mensaje", "version", "num_versiones", "firma",
        "unidades_obsoletas", "unidades_sin_hacer", "conservado", "trabajo",
        "descripcion", "aviso", "motor", "params")}
    ficha["unidades"] = len(datos.get("unidades") or [])
    ficha["versiones"] = [{k: v.get(k) for k in ("n", "fecha", "activa", "unidades")}
                          for v in (datos.get("versiones") or [])[-8:]]
    return _recortar(json.dumps(ficha, ensure_ascii=False, indent=1, default=str))


def bitacora(argumentos):
    """Los ultimos eventos de la bitacora de un proyecto, opcionalmente de un paso."""
    pid = _pid(argumentos)
    if not pid:
        return "hace falta 'proyecto'"
    limite = int(argumentos.get("limite") or 60)
    paso = str(argumentos.get("paso") or "").strip()
    consulta = urllib.parse.urlencode({"paso": paso, "limite": limite} if paso
                                      else {"limite": limite})
    codigo, datos = _llamar("GET", f"/api/proyectos/{urllib.parse.quote(pid)}/bitacora?{consulta}")
    if codigo != 200:
        return _error_de(codigo, datos)
    eventos = datos.get("eventos") if isinstance(datos, dict) else datos
    lineas = []
    for ev in (eventos or [])[-limite:]:
        d = ev.get("datos") if isinstance(ev.get("datos"), dict) else {}
        resumen = ", ".join(f"{k}={str(v)[:100]}" for k, v in sorted(d.items()))
        lineas.append(f"{ev.get('fecha', '?')}  {ev.get('evento', '?')}"
                      + (f" [{ev.get('paso')}]" if ev.get("paso") else "")
                      + (f" ({ev.get('unidad')})" if ev.get("unidad") else "")
                      + (f"  {resumen[:300]}" if resumen else ""))
    return _recortar("\n".join(lineas) or "sin eventos")


def cancelar_trabajo(argumentos):
    """Pide parar un trabajo por su id (cancelacion cooperativa)."""
    tid = str(argumentos.get("trabajo_id") or "").strip()
    if not tid:
        return "hace falta 'trabajo_id'"
    codigo, datos = _llamar("POST", f"/api/trabajos/{urllib.parse.quote(tid)}/cancelar", {})
    if codigo != 200:
        return _error_de(codigo, datos)
    return (f"cancelacion {'pedida' if datos.get('cancelacion_pedida') else 'NO necesaria'}; "
            f"estado del trabajo: {datos.get('estado')}")


def salud_servicio(argumentos):
    """Si el servicio esta bien: version, pasos cargados, trabajos activos, carpeta."""
    codigo, datos = _llamar("GET", "/api/salud")
    if codigo != 200:
        return _error_de(codigo, datos)
    return json.dumps(datos, ensure_ascii=False, indent=1)


HERRAMIENTAS = {
    "probar_claves": (probar_claves,
        "Prueba DE VERDAD cada clave contra su servicio (OpenAI, Cartesia, Jamendo, "
        "FreeSound) con una llamada que no cuesta dinero, y dice cual autentica y cual "
        "no. Con claude=true prueba tambien las cuentas de Claude (tarda mas). Usala "
        "cuando pregunten si las claves estan bien o si algo falla por una clave.",
        {"claude": {"type": "boolean", "description": "probar tambien las cuentas de Claude"}}),
    "probar_claude": (probar_claude,
        "Prueba las cuentas de Claude del CLI con una llamada minima y dice cual "
        "contesta, cual tiene el cupo agotado (y cuando se renueva) y cual no tiene sesion.",
        {}),
    "estado_estudio": (estado_estudio,
        "La foto del estado del Estudio ahora mismo: claves puestas, cuentas de Claude, "
        "proyectos, y del proyecto abierto sus ocho pasos, trabajos, bitacora y coste.",
        {"proyecto": {"type": "string", "description": "id del proyecto; por defecto el abierto"}}),
    "trabajos": (trabajos,
        "Lista los trabajos (generaciones) con estado, progreso, mensaje y error, para ver "
        "que esta corriendo, parado o fallado.",
        {"proyecto": {"type": "string", "description": "id del proyecto; vacio = todos los abiertos"}}),
    "ficha_paso": (ficha_paso,
        "La ficha de un paso (ingesta, brief, guion, voz, revision_audio, assets, callouts, "
        "render): estado, mensaje, version activa, params, unidades obsoletas y sin hacer.",
        {"proyecto": {"type": "string", "description": "id del proyecto"},
         "paso": {"type": "string", "description": "id del paso"}}),
    "bitacora": (bitacora,
        "Los ultimos eventos de la bitacora de un proyecto: que se genero, que fallo y "
        "con que motivo, en orden.",
        {"proyecto": {"type": "string", "description": "id del proyecto"},
         "paso": {"type": "string", "description": "solo los de este paso (opcional)"},
         "limite": {"type": "integer", "description": "cuantos eventos, por defecto 60"}}),
    "cancelar_trabajo": (cancelar_trabajo,
        "Pide parar un trabajo que se ha quedado colgado o que la persona quiere detener. "
        "Solo si la persona lo pide o esta claro que esta colgado.",
        {"trabajo_id": {"type": "string", "description": "id del trabajo"}}),
    "salud_servicio": (salud_servicio,
        "Si el servicio del Estudio esta bien: version, si los pasos cargaron, trabajos activos.",
        {}),
}


# ====================================================================== MIND
#
# LAS MANOS DEL ASISTENTE. Hasta aqui todo era mirar (y cancelar algo colgado).
# Con esto Mind HACE: estudia nichos, crea estilos y videos, genera, saca
# shorts, miniaturas, personajes del taller... por la misma API que la
# pantalla, o sea exactamente lo que haria quien pulsa.
#
# EL DINERO NO SE GASTA SIN UN SI. Toda accion de pago calcula antes su coste y,
# si `confirmo_coste` no llega a esa cifra, NO hace nada: devuelve
# «NECESITA CONFIRMACION: cuesta X $». El prompt de sistema le manda preguntar
# a la persona y volver a llamar con confirmo_coste=X solo si dice que si. Asi
# la regla no depende de que el modelo se acuerde: la herramienta se niega.

def _q(texto):
    return urllib.parse.quote(str(texto or ""), safe="")


def _necesita(confirmo, coste, que):
    """None si se puede gastar `coste`; si no, el texto que lo pide."""
    try:
        coste = float(coste or 0)
    except (TypeError, ValueError):
        coste = 0.0
    if coste < 0.005:
        return None
    try:
        dado = float(confirmo or 0)
    except (TypeError, ValueError):
        dado = 0.0
    if dado + 1e-6 >= round(coste, 2):
        return None
    return (f"NECESITA CONFIRMACION: {que} cuesta unos {coste:.2f} $. No se ha hecho "
            f"nada. Pregunta a la persona si quiere gastarlo y, SOLO si contesta que "
            f"si, vuelve a llamar con confirmo_coste={coste:.2f}.")


def _json(datos):
    return _recortar(json.dumps(datos, ensure_ascii=False, indent=1, default=str))


def listar_estilos(argumentos):
    """Los estilos (canales) con su id, y cuales son canales de shorts."""
    codigo, datos = _llamar("GET", "/api/presets-light")
    if codigo != 200:
        return _error_de(codigo, datos)
    shorts = set(((datos.get("shorts") or {}).get("canales")) or [])
    lineas = [f"- {p.get('nombre')}  (id={p.get('id')})"
              + ("  [canal de shorts]" if p.get("id") in shorts else "")
              + "  · " + " · ".join(str((v or {}).get("texto") or v)[:60]
                                    for v in (p.get("vinetas") or [])[:3])
              for p in datos.get("presets") or []]
    return "\n".join(lineas) or "no hay ningun estilo todavia"


def listar_videos(argumentos):
    """Los videos del estudio: id, nombre, estilo, tipo y si esta montado."""
    codigo, datos = _llamar("GET", "/api/proyectos")
    if codigo != 200:
        return _error_de(codigo, datos)
    filas = sorted((p for p in datos.get("proyectos") or [] if p.get("video_light")),
                   key=lambda p: p.get("actualizado") or "", reverse=True)
    lineas = [f"- {p.get('nombre')}  (id={p.get('id')}, estilo={p.get('estilo_light')}, "
              f"{'short' if p.get('short') else 'documental' if p.get('documental') else 'video'}, "
              f"{'MONTADO' if p.get('tiene_mp4') else 'en curso'}, {p.get('actualizado')})"
              for p in filas[:40]]
    return "\n".join(lineas) or "no hay videos todavia"


def panel(argumentos):
    """Lo que esta en marcha, el gasto del mes y el saldo de cada cuenta."""
    codigo, datos = _llamar("GET", "/api/panel")
    if codigo != 200:
        return _error_de(codigo, datos)
    _, saldo = _llamar("GET", "/api/saldo")
    return _json({"panel": datos, "saldo": (saldo or {}).get("cuentas") if isinstance(saldo, dict) else saldo})


def estudiar_nicho(argumentos):
    """Estudio de nicho DESDE CERO (gratis). Tarda 2-6 min: luego leer_nicho."""
    codigo, datos = _llamar("POST", "/api/nichos", {
        "tema": argumentos.get("tema"), "idioma": argumentos.get("idioma") or "es",
        "notas": argumentos.get("notas") or "", "referencias": argumentos.get("referencias") or []})
    if codigo != 200:
        return _error_de(codigo, datos)
    return (f"estudio en marcha (id={datos.get('id')}). Tarda de 2 a 6 minutos: diselo a la "
            f"persona y consultalo con leer_nicho cuando pregunte o en tu siguiente turno. "
            f"Tambien sale en la pantalla Mind.")


def leer_nicho(argumentos):
    """Un estudio de nicho (o la lista si no se da id)."""
    ident = str(argumentos.get("id") or "").strip()
    if not ident:
        codigo, datos = _llamar("GET", "/api/nichos")
        return _error_de(codigo, datos) if codigo != 200 else _json(datos.get("nichos"))
    codigo, datos = _llamar("GET", f"/api/nichos/{_q(ident)}")
    return _error_de(codigo, datos) if codigo != 200 else _json(datos)


def ideas_de_estilo(argumentos):
    """Estudia el nicho de un estilo ya creado y propone 8 videos (gratis)."""
    estilo = str(argumentos.get("estilo") or "").strip()
    if argumentos.get("solo_leer"):
        codigo, datos = _llamar("GET", f"/api/presets-light/{_q(estilo)}/ideas")
    else:
        codigo, datos = _llamar("POST", f"/api/presets-light/{_q(estilo)}/ideas",
                                {"enfoque": argumentos.get("enfoque") or ""})
    return _error_de(codigo, datos) if codigo != 200 else _json(datos)


def estudio_de_estilo(argumentos):
    """Competencia (canales dados) o revision de mis videos de un estilo (gratis)."""
    estilo = str(argumentos.get("estilo") or "").strip()
    tipo = str(argumentos.get("tipo") or "").strip()
    if tipo not in ("competencia", "mis_videos"):
        return "tipo tiene que ser competencia o mis_videos"
    if argumentos.get("solo_leer"):
        codigo, datos = _llamar("GET", f"/api/presets-light/{_q(estilo)}/estudios/{tipo}")
    else:
        codigo, datos = _llamar("POST", f"/api/presets-light/{_q(estilo)}/estudios/{tipo}",
                                {"canales": argumentos.get("canales") or []})
    return _error_de(codigo, datos) if codigo != 200 else _json(datos)


def crear_estilo(argumentos):
    """Crea un estilo (canal) nuevo: genera sus laminas de referencia. DE PAGO."""
    encargo = {k: argumentos.get(k) or "" for k in
               ("nombre", "idioma", "estilo_prompt", "tono_prompt", "voz_prompt", "ritmo")}
    encargo["idioma"] = encargo["idioma"] or "es"
    encargo["estilo_imagenes"] = []
    codigo, plan = _llamar("POST", "/api/presets-light/plan", encargo)
    if codigo != 200:
        return _error_de(codigo, plan)
    coste = int((plan or {}).get("imagenes") or 8) * 0.075
    falta = _necesita(argumentos.get("confirmo_coste"), coste, f"crear el estilo «{encargo['nombre']}»")
    if falta:
        return falta
    codigo, datos = _llamar("POST", "/api/presets-light", encargo, tiempo=120)
    if codigo not in (200, 202):
        return _error_de(codigo, datos)
    return (f"estilo en marcha (taller={datos.get('taller')}, trabajo={datos.get('trabajo_id')}). "
            f"Tarda unos minutos; sale en Mis estilos al terminar.")


def crear_video(argumentos):
    """Crea un video, short o documental con un estilo (no gasta: solo el encargo)."""
    estilo = str(argumentos.get("estilo") or "").strip()
    tipo = str(argumentos.get("tipo") or "video")
    cuerpo = {"nombre": argumentos.get("nombre") or "", "material": argumentos.get("material") or "",
              "formato": "vertical" if tipo == "short" else (argumentos.get("formato") or "horizontal"),
              "duracion_objetivo_s": int(argumentos.get("duracion_s") or (60 if tipo == "short" else 300)),
              "short": tipo == "short", "documental": "mezcla" if tipo == "documental" else "",
              "viral": argumentos.get("viral", True) is not False}
    codigo, datos = _llamar("POST", f"/api/presets-light/{_q(estilo)}/video", cuerpo, tiempo=120)
    if codigo not in (200, 201):
        return _error_de(codigo, datos)
    pid = (datos.get("proyecto") or {}).get("id")
    return (f"creado (proyecto={pid}). Siguiente: generar con tanda=guion (gratis), "
            f"despues voz, y despues render (imagenes + montaje).")


def generar(argumentos):
    """Lanza una tanda de un video: guion, voz, video (imagenes) o render. DE PAGO salvo el guion."""
    pid = _pid(argumentos)
    tanda = str(argumentos.get("tanda") or "").strip()
    if tanda not in ("guion", "voz", "video", "render"):
        return "tanda tiene que ser guion, voz, video o render"
    codigo, plan = _llamar("GET", f"/api/proyectos/{_q(pid)}/generar?tanda={tanda}")
    if codigo != 200:
        return _error_de(codigo, plan)
    coste = ((plan or {}).get("coste") or {})
    usd = coste.get("usd_por_generar", coste.get("usd_total", 0)) or 0
    if tanda == "guion":
        usd = 0
    falta = _necesita(argumentos.get("confirmo_coste"), usd, f"la tanda {tanda} de {pid}")
    if falta:
        return falta
    codigo, datos = _llamar("POST", f"/api/proyectos/{_q(pid)}/generar",
                            {"tanda": tanda, "modo": "pendientes"}, tiempo=120)
    if codigo not in (200, 202):
        return _error_de(codigo, datos)
    return f"tanda {tanda} lanzada (trabajo={datos.get('trabajo_id')}). Se ve en la Cola."


def ajustar_video(argumentos):
    """Animacion IA (video_ia lite|fast|'', video_ia_planos) y videos reales (video_real)."""
    pid = _pid(argumentos)
    params = {k: argumentos[k] for k in ("video_ia", "video_ia_planos", "video_real")
              if k in argumentos}
    if not params:
        return "di que cambiar: video_ia, video_ia_planos o video_real"
    codigo, datos = _llamar("PUT", f"/api/proyectos/{_q(pid)}/pasos/render/params",
                            {"params": params})
    return _error_de(codigo, datos) if codigo != 200 else f"ajustado: {params}. Se aplica al generar el render."


def recorte_gratis(argumentos):
    """Short GRATIS recortado de un video ya montado."""
    pid = _pid(argumentos)
    cuerpo = {"duracion_s": int(argumentos.get("duracion_s") or 45),
              "encuadre": argumentos.get("encuadre") or "fondo",
              "viral": argumentos.get("viral", True) is not False}
    if argumentos.get("inicio_s") not in (None, ""):
        cuerpo["inicio_s"] = argumentos.get("inicio_s")
    codigo, datos = _llamar("POST", f"/api/proyectos/{_q(pid)}/recortes", cuerpo)
    return _error_de(codigo, datos) if codigo not in (200, 202) else \
        f"recorte en marcha (trabajo={datos.get('trabajo_id')}); sale en Shorts en un minuto."


def short_de_video(argumentos):
    """Crea un short con guion nuevo a partir de un video (crearlo no gasta)."""
    pid = _pid(argumentos)
    codigo, datos = _llamar("POST", f"/api/proyectos/{_q(pid)}/short",
                            {"duracion_s": int(argumentos.get("duracion_s") or 60),
                             "viral": argumentos.get("viral", True) is not False})
    return _error_de(codigo, datos) if codigo not in (200, 201) else \
        f"short creado (proyecto={(datos.get('proyecto') or {}).get('id')}); falta generarlo."


def miniaturas(argumentos):
    """Tres miniaturas de YouTube para un video. DE PAGO (~0,25 $)."""
    pid = _pid(argumentos)
    falta = _necesita(argumentos.get("confirmo_coste"), 0.25, f"las miniaturas de {pid}")
    if falta:
        return falta
    codigo, datos = _llamar("POST", f"/api/proyectos/{_q(pid)}/miniaturas",
                            {"indicaciones": argumentos.get("indicaciones") or ""})
    return _error_de(codigo, datos) if codigo != 200 else "miniaturas en marcha: salen en la pantalla del video."


def taller(argumentos):
    """Crea un personaje, lugar u objeto fijo de un estilo. DE PAGO (~0,10 $)."""
    estilo = str(argumentos.get("estilo") or "").strip()
    tipo = str(argumentos.get("tipo") or "personajes")
    falta = _necesita(argumentos.get("confirmo_coste"), 0.10,
                      f"dibujar «{argumentos.get('nombre')}» en el taller")
    if falta:
        return falta
    codigo, datos = _llamar("POST", f"/api/presets-light/{_q(estilo)}/canal/{_q(tipo)}",
                            {"nombre": argumentos.get("nombre"), "idea": argumentos.get("idea") or ""})
    return _error_de(codigo, datos) if codigo != 200 else "en marcha: sale en la pestaña Taller del estilo."



def publicar(argumentos):
    """El kit para publicar un video: escribe el SEO (gratis) o lo lee."""
    pid = _pid(argumentos)
    if argumentos.get("escribir"):
        codigo, datos = _llamar("POST", f"/api/proyectos/{_q(pid)}/publicar/seo", {})
    else:
        codigo, datos = _llamar("GET", f"/api/proyectos/{_q(pid)}/publicar")
    if codigo != 200:
        return _error_de(codigo, datos)
    return _json({k: datos.get(k) for k in ("destinos", "subida", "mp4", "seo")})


def cuentas_de_estilo(argumentos):
    """Lee o guarda las cuentas (youtube, tiktok, facebook, instagram) de un estilo."""
    estilo = str(argumentos.get("estilo") or "").strip()
    cambios = {k: argumentos[k] for k in ("youtube", "tiktok", "facebook", "instagram") if k in argumentos}
    if cambios:
        codigo, datos = _llamar("PUT", f"/api/presets-light/{_q(estilo)}/publicar", cambios)
    else:
        codigo, datos = _llamar("GET", f"/api/presets-light/{_q(estilo)}/publicar")
    return _error_de(codigo, datos) if codigo != 200 else _json(datos)


def subir_video(argumentos):
    """Sube un video a la cuenta de YouTube/TikTok/Facebook de su estilo.
    Publicar es hacia fuera: sin confirmado=true no hace nada."""
    pid = _pid(argumentos)
    red = str(argumentos.get("red") or "").strip().lower()
    if red not in ("youtube", "tiktok", "facebook"):
        return "red tiene que ser youtube, tiktok o facebook"
    if not argumentos.get("confirmado"):
        return (f"NECESITA CONFIRMACION: vas a publicar el video {pid} en {red}. Dile a la "
                f"persona en que cuenta y con que privacidad, y SOLO si dice que si vuelve a "
                f"llamar con confirmado=true.")
    cuerpo = {k: argumentos[k] for k in ("privacidad", "modo", "publicar_en") if argumentos.get(k)}
    codigo, datos = _llamar("POST", f"/api/proyectos/{_q(pid)}/publicar/{red}", cuerpo)
    return _error_de(codigo, datos) if codigo != 200 else f"enviando a {red}: se ve el progreso en Publicar del video."

_TXT = {"type": "string"}
_NUM = {"type": "number"}
_CONF = {"type": "number", "description": "SOLO tras un si explicito de la persona: el coste que aceptó"}

HERRAMIENTAS.update({
    "listar_estilos": (listar_estilos, "Lista los estilos (canales) con su id.", {}),
    "listar_videos": (listar_videos, "Lista los videos con id, estilo, tipo y si estan montados.", {}),
    "panel": (panel, "Lo que se esta generando, el gasto del mes y el saldo de cada cuenta.", {}),
    "estudiar_nicho": (estudiar_nicho,
        "Estudio de nicho DESDE CERO (sin estilo): demanda, competencia, dinero, subnichos "
        "y un canal propuesto con 10 videos. Gratis. Admite videos/canales de referencia.",
        {"tema": _TXT, "idioma": _TXT, "notas": _TXT,
         "referencias": {"type": "array", "items": _TXT, "description": "URLs o nombres de videos/canales"}}),
    "leer_nicho": (leer_nicho, "Lee un estudio de nicho por id (sin id: la lista).", {"id": _TXT}),
    "ideas_de_estilo": (ideas_de_estilo,
        "Estudia el nicho de un estilo existente y propone videos (gratis). solo_leer=true para leer el ultimo.",
        {"estilo": _TXT, "enfoque": _TXT, "solo_leer": {"type": "boolean"}}),
    "estudio_de_estilo": (estudio_de_estilo,
        "Competencia (con canales) o revision de mis_videos de un estilo (gratis). solo_leer=true para leer.",
        {"estilo": _TXT, "tipo": _TXT, "canales": {"type": "array", "items": _TXT},
         "solo_leer": {"type": "boolean"}}),
    "crear_estilo": (crear_estilo,
        "Crea un estilo/canal nuevo (dibuja sus laminas: DE PAGO, pide confirmacion).",
        {"nombre": _TXT, "idioma": _TXT, "estilo_prompt": _TXT, "tono_prompt": _TXT,
         "voz_prompt": _TXT, "ritmo": _TXT, "confirmo_coste": _CONF}),
    "crear_video": (crear_video,
        "Crea un video/short/documental con un estilo y su material (gratis: solo el encargo).",
        {"estilo": _TXT, "nombre": _TXT, "material": _TXT, "tipo": _TXT,
         "duracion_s": _NUM, "formato": _TXT, "viral": {"type": "boolean"}}),
    "generar": (generar,
        "Lanza una tanda de un video: guion (gratis), voz, video o render (de pago, pide confirmacion).",
        {"proyecto": _TXT, "tanda": _TXT, "confirmo_coste": _CONF}),
    "ajustar_video": (ajustar_video,
        "Cambia la animacion IA (video_ia: ''|lite|fast; video_ia_planos: primero|sin_texto|mitad|todos) "
        "o los videos reales (video_real: ''|mezcla|maximo) de un video.",
        {"proyecto": _TXT, "video_ia": _TXT, "video_ia_planos": _TXT, "video_real": _TXT}),
    "recorte_gratis": (recorte_gratis, "Short GRATIS recortado de un video montado (viral=true por defecto: gancho y barra de progreso).",
        {"proyecto": _TXT, "duracion_s": _NUM, "encuadre": _TXT, "inicio_s": _NUM, "viral": {"type": "boolean"}}),
    "short_de_video": (short_de_video, "Crea un short con guion nuevo a partir de un video (crear es gratis). "
        "viral=true por defecto: mini guion con gancho y giros, cortes rapidos, subtitulos enormes, barra de progreso.",
        {"proyecto": _TXT, "duracion_s": _NUM, "viral": {"type": "boolean"}}),
    "miniaturas": (miniaturas, "Tres miniaturas de YouTube para un video (de pago, pide confirmacion).",
        {"proyecto": _TXT, "indicaciones": _TXT, "confirmo_coste": _CONF}),
    "publicar": (publicar,
        "Kit para publicar un video: con escribir=true redacta titulo, descripcion con capitulos, "
        "etiquetas y textos de TikTok/Facebook/Instagram (gratis); sin el, lo lee con las paginas de subida.",
        {"proyecto": _TXT, "escribir": {"type": "boolean"}}),
    "cuentas_de_estilo": (cuentas_de_estilo,
        "Lee o guarda los enlaces de las cuentas donde publica un estilo (youtube, tiktok, facebook, instagram).",
        {"estilo": _TXT, "youtube": _TXT, "tiktok": _TXT, "facebook": _TXT, "instagram": _TXT}),
    "subir_video": (subir_video,
        "Sube un video montado a la cuenta conectada de su estilo en youtube (privacidad "
        "private|unlisted|public, publicar_en ISO opcional), tiktok (modo borrador|directo) o "
        "facebook (publicar_en opcional). Pide confirmacion antes.",
        {"proyecto": _TXT, "red": _TXT, "privacidad": _TXT, "modo": _TXT, "publicar_en": _TXT,
         "confirmado": {"type": "boolean"}}),
    "taller": (taller, "Crea un personaje/lugar/objeto fijo de un estilo (de pago, pide confirmacion).",
        {"estilo": _TXT, "tipo": _TXT, "nombre": _TXT, "idea": _TXT, "confirmo_coste": _CONF}),
})


def lista_de_herramientas():
    salida = []
    for nombre, (_, descripcion, propiedades) in HERRAMIENTAS.items():
        salida.append({
            "name": nombre,
            "description": descripcion,
            "inputSchema": {"type": "object", "properties": propiedades,
                            "additionalProperties": False},
        })
    return salida


def nombres_permitidos(servidor="estudio"):
    """Como se autorizan en la orden del CLI: mcp__<servidor>__<herramienta>."""
    return tuple(f"mcp__{servidor}__{nombre}" for nombre in HERRAMIENTAS)


# ------------------------------------------------------------------ JSON-RPC

def atender(mensaje):
    """La respuesta a un mensaje, o None si es una notificacion."""
    metodo = mensaje.get("method")
    ident = mensaje.get("id")
    params = mensaje.get("params") or {}

    def ok(resultado):
        return {"jsonrpc": "2.0", "id": ident, "result": resultado}

    def mal(codigo, texto):
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": codigo, "message": texto}}

    if metodo == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOLO,
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": "estudio", "version": "1.0"}})
    if metodo in ("notifications/initialized", "notifications/cancelled"):
        return None
    if metodo == "ping":
        return ok({})
    if metodo == "tools/list":
        return ok({"tools": lista_de_herramientas()})
    if metodo == "tools/call":
        nombre = params.get("name")
        argumentos = params.get("arguments") or {}
        entrada = HERRAMIENTAS.get(nombre)
        if entrada is None:
            return mal(-32602, f"herramienta desconocida: {nombre}")
        try:
            texto = entrada[0](argumentos if isinstance(argumentos, dict) else {})
            return ok({"content": [{"type": "text", "text": str(texto)}], "isError": False})
        except Exception as fallo:                     # noqa: BLE001
            return ok({"content": [{"type": "text",
                                    "text": f"la herramienta ha fallado: "
                                            f"{type(fallo).__name__}: {fallo}"}],
                       "isError": True})
    if ident is None:
        return None
    return mal(-32601, f"metodo desconocido: {metodo}")


def servir(entrada=None, salida=None):
    entrada = entrada or sys.stdin
    salida = salida or sys.stdout
    for linea in entrada:
        linea = linea.strip()
        if not linea:
            continue
        try:
            mensaje = json.loads(linea)
        except ValueError:
            continue
        respuesta = atender(mensaje)
        if respuesta is not None:
            salida.write(json.dumps(respuesta, ensure_ascii=False) + "\n")
            salida.flush()


if __name__ == "__main__":
    servir()
