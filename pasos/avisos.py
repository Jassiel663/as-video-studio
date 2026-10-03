"""
LOS AVISOS: lo que pasa en el estudio, en la campana y en el movil (Telegram).

Que avisa (un vigilante en segundo plano, cada 30 s, mirando la propia API):
  · un trabajo que TERMINA (un video montado, un estilo creado...) o FALLA;
  · una cuenta que BAJA del saldo minimo apuntado;
  · lo que mandan otros modulos con `avisar(...)`: el piloto automatico cuando
    necesita un «si» o cuando publica, un short trabajado listo...

Donde avisa:
  · en el estudio (la campana), siempre: datos/avisos/avisos.jsonl;
  · en TELEGRAM, si hay bot: la persona crea uno gratis con @BotFather, pega su
    token en Configuracion › Claves y cada uno que quiera avisos le escribe
    /start al bot y pulsa «Vincular». Cada suscriptor puede quedarse solo con
    SUS estilos (los amigos que usan el sitio no reciben lo de los demas).
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

try:
    from . import claves, medios, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import claves
    import medios
    import presets_canal

CARPETA = os.environ.get("ESTUDIO_AVISOS") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "avisos")
_CANDADO = threading.Lock()
MAX_AVISOS = 500
INTERVALO_S = 30

#: nombres de trabajo que merece la pena contar al terminar (los demas, no:
#: un guion suelto o una prueba de clave no son noticia)
NOMBRES = {"render": "el vídeo está montado", "generar:video+render": "el vídeo está montado",
           "generar:render": "el vídeo está montado", "preset_light": "el estilo está creado",
           "generar:voz": "la voz está lista", "generar:video": "las imágenes están listas"}


def _ruta(nombre):
    return os.path.join(CARPETA, nombre)


def _leer_lista():
    lista = []
    try:
        with open(_ruta("avisos.jsonl"), "r", encoding="utf-8") as fh:
            for linea in fh:
                try:
                    lista.append(json.loads(linea))
                except ValueError:
                    continue
    except OSError:
        pass
    return lista


def listar(limite=60):
    lista = _leer_lista()
    leidos = medios.leer_json(_ruta("leidos.json"), {}) or {}
    ultimo = float(leidos.get("hasta") or 0)
    salida = list(reversed(lista[-limite:]))
    for a in salida:
        a["leido"] = float(a.get("ts") or 0) <= ultimo
    return {"avisos": salida, "sin_leer": sum(1 for a in lista if float(a.get("ts") or 0) > ultimo)}


def marcar_leidos():
    os.makedirs(CARPETA, exist_ok=True)
    medios.escribir_json(_ruta("leidos.json"), {"hasta": time.time()})


def avisar(tipo, titulo, texto="", estilo="", enlace=""):
    """Apunta un aviso y lo manda por Telegram a quien le toque."""
    aviso = {"ts": time.time(), "fecha": time.strftime("%Y-%m-%dT%H:%M:%S"), "tipo": tipo,
             "titulo": str(titulo)[:200], "texto": str(texto)[:1500], "estilo": estilo or "",
             "enlace": enlace or ""}
    with _CANDADO:
        os.makedirs(CARPETA, exist_ok=True)
        lista = _leer_lista()[-(MAX_AVISOS - 1):] + [aviso]
        with open(_ruta("avisos.jsonl"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(json.dumps(a, ensure_ascii=False) for a in lista) + "\n")
    try:
        _telegram_a_todos(aviso)
    except Exception:                                       # noqa: BLE001
        pass
    return aviso


# ------------------------------------------------------------------ telegram

def _token():
    return (claves.leer().get("telegram") or {}).get("clave") or ""


def _tg(metodo, **params):
    url = f"https://api.telegram.org/bot{_token()}/{metodo}"
    datos = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(url, data=datos), timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def suscriptores():
    return medios.leer_json(_ruta("telegram.json"), {}).get("suscriptores") or []


def _guardar_suscriptores(lista):
    os.makedirs(CARPETA, exist_ok=True)
    medios.escribir_json(_ruta("telegram.json"), {"suscriptores": lista})


def estado_telegram():
    if not _token():
        return {"bot": "", "listo": False, "suscriptores": []}
    try:
        yo = _tg("getMe").get("result") or {}
    except Exception as fallo:                              # noqa: BLE001
        return {"bot": "", "listo": False, "error": f"Telegram no acepta el token: {fallo}",
                "suscriptores": suscriptores()}
    return {"bot": yo.get("username", ""), "listo": True, "suscriptores": suscriptores()}


def vincular():
    """Apunta a todos los que le han escrito /start al bot. -> los nuevos"""
    if not _token():
        raise ValueError("falta el token del bot de Telegram en Configuracion › Claves")
    actualizaciones = _tg("getUpdates").get("result") or []
    lista = suscriptores()
    ya = {s["chat"] for s in lista}
    nuevos = []
    for u in actualizaciones:
        msg = u.get("message") or {}
        chat = (msg.get("chat") or {})
        if str(msg.get("text") or "").startswith("/start") and chat.get("id") and chat["id"] not in ya:
            nombre = chat.get("first_name") or chat.get("title") or chat.get("username") or str(chat["id"])
            lista.append({"chat": chat["id"], "nombre": nombre, "estilos": []})
            ya.add(chat["id"])
            nuevos.append(nombre)
            try:
                _tg("sendMessage", chat_id=chat["id"],
                    text="✅ Listo: recibirás aquí los avisos de Mind Videos.")
            except Exception:                               # noqa: BLE001
                pass
    _guardar_suscriptores(lista)
    return nuevos


def ajustar_suscriptor(chat, estilos=None, quitar=False):
    lista = suscriptores()
    if quitar:
        lista = [s for s in lista if str(s["chat"]) != str(chat)]
    else:
        for s in lista:
            if str(s["chat"]) == str(chat):
                s["estilos"] = [str(e) for e in estilos or []]
    _guardar_suscriptores(lista)
    return lista


def _telegram_a_todos(aviso):
    if not _token():
        return
    for s in suscriptores():
        if s.get("estilos") and aviso.get("estilo") and aviso["estilo"] not in s["estilos"]:
            continue
        texto = f"{aviso['titulo']}\n{aviso['texto']}".strip()
        if aviso.get("enlace"):
            texto += f"\n{aviso['enlace']}"
        _tg("sendMessage", chat_id=s["chat"], text=texto[:3900])


def probar():
    return avisar("prueba", "🔔 Prueba de avisos de Mind Videos", "Si lees esto, los avisos funcionan.")


# ------------------------------------------------------------------ el vigilante

def _api(ruta):
    base = (os.environ.get("ESTUDIO_API") or "http://127.0.0.1:8110").rstrip("/")
    with urllib.request.urlopen(base + ruta, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _vigilar():
    vistos = {}
    bajos_previos = None
    publico = os.environ.get("ESTUDIO_URL_PUBLICA") or ""
    time.sleep(20)
    while True:
        try:
            trabajos = _api("/api/trabajos").get("trabajos") or []
            proyectos = {p["id"]: p for p in (_api("/api/proyectos").get("proyectos") or [])}
            for t in trabajos:
                tid, estado = t.get("id"), t.get("estado")
                antes = vistos.get(tid)
                vistos[tid] = estado
                if antes is None or antes == estado or estado not in ("listo", "error"):
                    continue
                p = proyectos.get(t.get("proyecto")) or {}
                nombre = p.get("nombre") or t.get("proyecto") or ""
                if estado == "error":
                    avisar("error", f"⚠️ Ha fallado: {nombre}",
                           f"{t.get('nombre')}: {str(t.get('error') or '')[:300]}",
                           p.get("estilo_light", ""), publico)
                elif t.get("nombre") in NOMBRES:
                    avisar("listo", f"✅ {nombre}: {NOMBRES[t['nombre']]}", "", p.get("estilo_light", ""), publico)
            saldo = _api("/api/saldo")
            bajos = set(saldo.get("bajos") or [])
            if bajos_previos is not None:
                for cuenta in bajos - bajos_previos:
                    c = (saldo.get("cuentas") or {}).get(cuenta) or {}
                    avisar("saldo", f"💸 Saldo bajo en {c.get('etiqueta') or cuenta}",
                           f"Quedan {float(c.get('restante') or 0):.2f} $. Recarga en {c.get('recarga') or ''}")
            bajos_previos = bajos
        except Exception:                                   # noqa: BLE001
            pass
        time.sleep(INTERVALO_S)


def arrancar():
    threading.Thread(target=_vigilar, daemon=True, name="avisos").start()
