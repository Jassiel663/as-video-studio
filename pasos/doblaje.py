"""
EL DOBLAJE: el mismo video en otro idioma, sin volver a pagar las imagenes.

Un video se hace en UN idioma (ver la cabecera de p3_guion), asi que el doblaje
es OTRO video, hermano del original y enlazado a el:

  1. TRADUCIR (gratis, Claude): el guion bloque a bloque, como se traduce para
     doblar -- natural para el oido y de largo parecido, para que el ritmo del
     video no cambie --, y el titulo.
  2. CREAR el video hermano con el mismo estilo, el guion traducido como «guion
     propio» (no se reescribe), el idioma nuevo y la misma voz y los mismos
     ajustes de montaje. El guion se lanza solo (gratis).
  3. Lo que cuesta dinero es SOLO LA VOZ nueva, y se paga como siempre: con el
     boton y su precio delante.
  4. LAS IMAGENES NO SE DIBUJAN: al cortar los planos del doblaje, cada plano
     nuevo recibe la imagen del plano del original que cuenta lo mismo (mismo
     bloque del guion y la misma altura dentro de el; si los bloques no casan,
     la misma altura del video). Se copian a la carpeta de planos con su ficha
     y el paso de imagenes las da por hechas: 0 $. Igual las hojas de reparto.
     Los subtitulos y los rotulos salen ya en el idioma nuevo, porque se
     escriben de la narracion.
  5. Los clips animados (Veo/fal) NO se copian: el doblaje sale con las
     imagenes quietas con su movimiento de camara, gratis. Se pueden animar
     despues como cualquier video.

El estado de cada doblaje vive en el ORIGINAL: <proyecto>/doblajes.json.
"""
import json
import os
import shutil
import tempfile
import threading
import time

try:
    from . import cli_claude, comun, medios
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import cli_claude
    import comun
    import medios

IDIOMAS = {"en": "inglés", "pt": "portugués", "fr": "francés", "it": "italiano",
           "de": "alemán", "es": "español"}
_EN_MARCHA = set()
_CANDADO = threading.Lock()

INSTRUCCION = """Eres traductor de doblaje para videos de YouTube. Traduce este guion de \
{origen} a {destino} para que lo locute una voz en off.

Reglas:
- Natural para el oido en {destino}, como lo diria un narrador nativo: nada de traduccion literal.
- De LARGO PARECIDO a cada bloque original (mas o menos las mismas silabas): el video va \
montado a ese ritmo.
- Un bloque traducido por cada bloque original, con el MISMO id y en el mismo orden. No \
juntes ni partas bloques.
- Respeta nombres propios, cifras y datos. Las unidades y monedas, como se dicen en {destino}.
- Traduce tambien el titulo del video.

Contesta SOLO con este JSON:
{{"titulo": "...", "bloques": [{{"id": "...", "texto": "..."}}]}}

Titulo original: {titulo}

Guion (JSON):
{guion}
"""


def _ruta_estado(proyecto):
    return os.path.join(proyecto.raiz, "doblajes.json")


def leer(proyecto):
    datos = medios.leer_json(_ruta_estado(proyecto), {}) or {}
    for idioma, d in datos.items():
        if d.get("estado") == "pensando" and (proyecto.raiz, idioma) not in _EN_MARCHA:
            d["estado"] = "error"
            d["error"] = "se corto (el estudio se reinicio); vuelve a pedirlo"
    return datos


def _guardar(proyecto, idioma, ficha):
    with _CANDADO:
        datos = medios.leer_json(_ruta_estado(proyecto), {}) or {}
        datos[idioma] = ficha
        medios.escribir_json(_ruta_estado(proyecto), datos)


def traducir(bloques, destino, origen="es", titulo=""):
    """-> (titulo traducido, [{"id","texto"}]) con los mismos ids y en orden."""
    if destino not in IDIOMAS:
        raise ValueError(f"idioma no disponible: {destino}")
    guion = json.dumps([{"id": b["id"], "texto": b["texto"]} for b in bloques], ensure_ascii=False)
    instruccion = INSTRUCCION.format(origen=IDIOMAS.get(origen, origen), destino=IDIOMAS[destino],
                                     titulo=titulo or "(sin titulo)", guion=guion)
    ultimo = ""
    for intento in range(2):
        texto, _ = cli_claude.ejecutar(
            instruccion if not intento else instruccion + "\nSOLO el JSON, con TODOS los ids.",
            modelo="sonnet", esfuerzo="low", cwd=tempfile.gettempdir(), tiempo_max_s=900,
            extra=["--no-session-persistence"], para="traducir el guion")
        try:
            datos = comun.extraer_json(texto, "la traduccion")
        except Exception as fallo:                          # noqa: BLE001
            ultimo = str(fallo)
            continue
        por_id = {str(b.get("id")): str(b.get("texto") or "").strip()
                  for b in datos.get("bloques") or [] if isinstance(b, dict)}
        faltan = [b["id"] for b in bloques if not por_id.get(b["id"])]
        if faltan:
            ultimo = f"faltan {len(faltan)} bloques en la traduccion"
            continue
        return (str(datos.get("titulo") or titulo).strip()[:90],
                [{"id": b["id"], "texto": por_id[b["id"]]} for b in bloques])
    raise RuntimeError(f"no se ha podido traducir el guion: {ultimo}")


def lanzar(proyecto, bloques, destino, origen, titulo, crear):
    """Traduce y crea el doblaje en un hilo. `crear(titulo, bloques) -> pid`."""
    if destino not in IDIOMAS:
        raise ValueError(f"idioma no disponible: {destino}")
    if destino == origen:
        raise ValueError("ese ya es el idioma del video")
    if not bloques:
        raise ValueError("este video todavia no tiene guion")
    clave = (proyecto.raiz, destino)
    with _CANDADO:
        if clave in _EN_MARCHA:
            return leer(proyecto)
        _EN_MARCHA.add(clave)
    _guardar(proyecto, destino, {"estado": "pensando", "desde": time.time(), "error": ""})

    def correr():
        try:
            titulo_nuevo, traducidos = traducir(bloques, destino, origen, titulo)
            pid = crear(titulo_nuevo, traducidos)
            _guardar(proyecto, destino, {"estado": "listo", "pid": pid, "titulo": titulo_nuevo,
                                         "fecha": time.strftime("%Y-%m-%dT%H:%M:%S")})
        except Exception as fallo:                          # noqa: BLE001
            _guardar(proyecto, destino, {"estado": "error", "error": str(fallo)[:400]})
        finally:
            with _CANDADO:
                _EN_MARCHA.discard(clave)

    threading.Thread(target=correr, daemon=True, name=f"doblaje-{destino}").start()
    return leer(proyecto)


# ------------------------------------------------------------- las imagenes

def _carpeta_activa(raiz, paso):
    """La carpeta de la version activa de un paso de OTRO proyecto, o ''."""
    activa = medios.leer_json(os.path.join(raiz, "pasos", paso, "activa.json"), {}) or {}
    version = activa.get("activa") if isinstance(activa.get("activa"), int) else None
    if not version:
        versiones = sorted((int(n[1:]) for n in os.listdir(os.path.join(raiz, "pasos", paso))
                            if n[:1] == "v" and n[1:].isdigit()), reverse=True) \
            if os.path.isdir(os.path.join(raiz, "pasos", paso)) else []
        version = versiones[0] if versiones else None
    ruta = os.path.join(raiz, "pasos", paso, f"v{version}") if version else ""
    return ruta if ruta and os.path.isdir(ruta) else ""


def origen_de(proyecto, pid_origen):
    """La carpeta de imagenes del video original y su plan. -> (carpeta, plan)"""
    raiz = os.path.join(os.path.dirname(proyecto.raiz), str(pid_origen))
    carpeta = _carpeta_activa(raiz, "assets")
    if not carpeta:
        return "", {}
    return carpeta, medios.leer_json(os.path.join(carpeta, "plan.json"), {}) or {}


def mapear(nuevas, viejas):
    """Que plano del original ilustra cada plano del doblaje. -> {nuevo: viejo}

    Por BLOQUE si los dos casan (el mismo id de bloque del guion): el plano i de
    n del bloque toma el de su misma altura entre los m del original. Si no,
    por la ALTURA EN EL VIDEO: el centro del plano nuevo, como fraccion del
    doblaje, contra el centro de cada plano del original."""
    def bloque(e):
        return ((e.get("origen") or {}).get("bloque")) or ""

    por_bloque = {}
    for e in viejas:
        por_bloque.setdefault(bloque(e), []).append(e)
    nuevas_por_bloque = {}
    for e in nuevas:
        nuevas_por_bloque.setdefault(bloque(e), []).append(e)
    total_v = max([float(e.get("t_out") or 0) for e in viejas] or [1]) or 1
    total_n = max([float(e.get("t_out") or 0) for e in nuevas] or [1]) or 1
    centros_v = [((float(e.get("t_in") or 0) + float(e.get("t_out") or 0)) / 2 / total_v, e) for e in viejas]
    salida = {}
    for bid, grupo in nuevas_por_bloque.items():
        candidatos = por_bloque.get(bid) if bid else None
        for i, e in enumerate(grupo):
            if candidatos:
                elegido = candidatos[min(len(candidatos) - 1, int((i + 0.5) * len(candidatos) / len(grupo)))]
            elif centros_v:
                altura = (float(e.get("t_in") or 0) + float(e.get("t_out") or 0)) / 2 / total_n
                elegido = min(centros_v, key=lambda par: abs(par[0] - altura))[1]
            else:
                continue
            salida[e["id"]] = elegido["id"]
    return salida


def preparar_imagenes(proyecto, pid_origen, escenas, carpeta_escenas, es_sin_imagen, texto_clave):
    """Pone en la carpeta de planos del doblaje la imagen que le toca a cada
    plano, con su ficha, para que el paso de imagenes la de por hecha (0 $).
    -> cuantas se han copiado"""
    origen, plan = origen_de(proyecto, pid_origen)
    if not origen:
        raise RuntimeError("el video original ya no tiene imagenes: no se puede doblar sin pagarlas")
    viejas = [e for e in plan.get("escenas") or []
              if not es_sin_imagen(e) and os.path.exists(os.path.join(origen, "escenas", f"{e['id']}.png"))]
    if not viejas:
        raise RuntimeError("el video original no tiene planos dibujados")
    con_imagen = [e for e in escenas if not es_sin_imagen(e)]
    mapa = mapear(con_imagen, viejas)
    os.makedirs(carpeta_escenas, exist_ok=True)
    copiadas = 0
    for e in con_imagen:
        destino = os.path.join(carpeta_escenas, f"{e['id']}.png")
        fuente = mapa.get(e["id"])
        if not fuente:
            continue
        ficha_destino = os.path.join(carpeta_escenas, f"{e['id']}.json")
        previa = medios.leer_json(ficha_destino, {}) or {}
        if os.path.exists(destino) and previa.get("doblaje_de") == f"{pid_origen}/{fuente}":
            continue
        shutil.copyfile(os.path.join(origen, "escenas", f"{fuente}.png"), destino)
        medios.escribir_json(ficha_destino, {
            "tipo": "escena", "png": f"escenas/{e['id']}.png", "origen": "doblaje", "coste": 0.0,
            "narracion": e.get("narracion") or "", "vale_para": texto_clave(e),
            "doblaje_de": f"{pid_origen}/{fuente}"})
        copiadas += 1
    return copiadas


def preparar_reparto(proyecto, pid_origen, carpeta_reparto):
    """Las hojas de personaje del original, para no volver a dibujarlas."""
    origen, _ = origen_de(proyecto, pid_origen)
    fuente = os.path.join(origen, "assets", "reparto") if origen else ""
    if not fuente or not os.path.isdir(fuente):
        return 0
    os.makedirs(carpeta_reparto, exist_ok=True)
    copiadas = 0
    for nombre in os.listdir(fuente):
        if nombre.endswith(".png") and not os.path.exists(os.path.join(carpeta_reparto, nombre)):
            shutil.copyfile(os.path.join(fuente, nombre), os.path.join(carpeta_reparto, nombre))
            copiadas += 1
    return copiadas


# ------------------------------------------------------------------ la voz

def voz_para(params_voz, destino, modo="nativa"):
    """La voz del doblaje. -> voz_id

    «misma»: la del original hablando el idioma nuevo (los modelos de Cartesia
    son multilingues, pero se le nota el acento). «nativa» (por defecto): una
    voz NATIVA de ese idioma y del mismo genero que la original; si no hay
    ninguna o no se puede preguntar, la del original."""
    try:
        from . import p4_voz
    except ImportError:
        import p4_voz
    original = p4_voz.resolver_params(params_voz or {})["voz_id"]
    if modo == "misma":
        return original
    try:
        todas = p4_voz.listar_voces()
        genero = next((v.get("genero") for v in todas if v.get("id") == original), "")
        nativas = p4_voz.listar_voces(destino, solo_nativas=True)
        mismas = [v for v in nativas if not genero or v.get("genero") == genero]
        elegida = (mismas or nativas or [None])[0]
        if elegida and elegida.get("id"):
            return elegida["id"]
    except Exception:                                       # noqa: BLE001
        pass
    return original
