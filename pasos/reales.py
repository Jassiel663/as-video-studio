"""
MODO DOCUMENTAL: planos con VIDEO REAL de bancos gratis, y la IA para el resto.

QUE HACE
--------
Con el param `video_real` del render puesto, antes de montar:

  1. CLAUDE LEE EL PLAN (narracion, direccion, personajes de cada plano) y dice,
     plano a plano, si encaja un video real de banco y con que busqueda en
     ingles. Va por la suscripcion del CLI: no cuesta dinero. Se guarda, asi que
     volver a montar no lo vuelve a preguntar mientras el plan no cambie.
  2. SE BUSCA en Pexels y Pixabay (gratis, ver motores/video_stock) y se baja
     el primer clip que dure lo que el plano y no se haya usado ya en otro.
  3. EL CLIP ENTRA COMO LOS DE VEO: fotogramas al tamano del video, a cuadro
     completo, con la capa del plano (subtitulos) encima.

Lo que no encaja --o no se encuentra-- sigue con la IA: su imagen y, si el
video lo pide, su animacion con Veo. De ahi «agregarle IA»: el documental
mezcla lo real con lo dibujado.

Dos modos:

    mezcla   real donde hay material generico que lo cuente bien (lugares,
             naturaleza, ciudades, objetos, oficios, multitudes); IA para el
             protagonista, la historia concreta y las metaforas
    maximo   real en todo plano donde haya algo plausible; IA solo si no

Claude piensa como un MONTADOR: el b-roll ilustra lo que dice la NARRACION, no
la escena dibujada (la primera version miraba el dibujo y, con guiones de
protagonista, solo encontraba 2-8 planos de 200). Siempre con IA: los que
llevan una capa grafica encima (sus flechas apuntan a sitios de la imagen
dibujada) y los que tienen una cifra o un texto que hay que leer.
"""
import hashlib
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import animar
import cli_claude
import medios

PARAM = "video_real"
MODOS = ("", "mezcla", "maximo")

#: Cuantos clips se bajan a la vez. Es red, no CPU, y los bancos no limitan
#: las descargas: cuatro es suficiente para que doscientos planos no tarden.
A_LA_VEZ = 4

#: Mas corto que esto, un clip se queda congelado al final del plano: se busca
#: otro. Un poco de margen porque el plano se recorta al principio del clip.
MARGEN_S = 0.3

INSTRUCCION = """Eres el montador de un documental de YouTube. Te paso el plan de planos de un video: para cada uno, lo que dice la NARRACION en ese momento y la ilustracion que habia prevista.

Elige en que planos va mejor un PLANO DE RECURSO REAL (b-roll de un banco de stock: Pexels, Pixabay) que ilustre LO QUE DICE LA NARRACION, en lugar de la ilustracion. Piensa como en un documental: si la narracion habla de dinero, unas manos contando billetes; si habla de una fabrica, una fabrica; si alguien se siente solo, una calle vacia de noche. No hace falta que salga el protagonista: el b-roll cuenta la idea, no la escena exacta.

{criterio}

La ilustracion se queda cuando el plano necesita:
- una cifra, un texto o una pantalla que el espectador TIENE que leer para   seguir la historia (marcado TEXTO: si)
- algo imposible, fantastico o tan concreto que ningun banco lo tiene
{extra}
La busqueda va EN INGLES, de 2 a 6 palabras, como lo etiquetaria un banco de stock: «aerial city night traffic», «hands counting cash», «warehouse boxes shelves», «stormy ocean waves». Sin nombres propios de personas. Lugares famosos si. Varia las busquedas: dos planos seguidos no deben pedir lo mismo.

Contesta SOLO un JSON: {{"S001": "busqueda" o null, ...}} con TODOS los ids.

PLANOS:
{planos}
"""

CRITERIOS = {
    "mezcla": "MEZCLA: alterna. Real para dar contexto (lugares, objetos, oficios, naturaleza, ciudad, dinero, tiempo); la ilustracion para los momentos del protagonista que mueven la historia. Mas o menos un plano de cada tres real.",
    "maximo": "MAXIMO: real en todos los planos donde un b-roll razonable cuente la narracion, aunque sea aproximado (unas manos, un detalle, una silueta, un lugar parecido). Lo normal es que la mayoria de los planos salgan reales.",
}

EXTRA = {
    "mezcla": "- el protagonista haciendo algo que importa para la historia\n",
    "maximo": "",
}


def modo_de(params):
    valor = str((params or {}).get(PARAM) or "").strip().lower()
    return valor if valor in MODOS else ""


def carpeta_de(proyecto):
    carpeta = os.path.join(proyecto.raiz, "pasos", "render", "reales")
    os.makedirs(os.path.join(carpeta, "clips"), exist_ok=True)
    return carpeta


def puede_ser_real(escena, capa_svg=""):
    """Si el plano admite un video real. -> None o el motivo de que no.

    El texto DIBUJADO no lo impide: es parte de la ilustracion, y si el plano
    va con b-roll la ilustracion no sale. Lo decide Claude (va marcado en la
    linea del plano). Lo que si lo impide es la capa grafica: va ENCIMA del
    plano y apunta a sitios de la imagen dibujada.
    """
    if escena.get("capa_vectorial") or (capa_svg and animar._VISIBLE_SVG.search(capa_svg)):
        return "lleva capa grafica encima"
    return None


def _linea(escena):
    duracion = float(escena["t_out"]) - float(escena["t_in"])
    trozos = [f"{escena['id']} ({duracion:.1f}s)",
              f"NARRACION: {' '.join(str(escena.get('narracion') or '').split())}",
              f"IMAGEN: {' '.join(str(escena.get('direccion') or '').split())[:300]}"]
    if escena.get("personajes"):
        trozos.append(f"PERSONAJES: {', '.join(map(str, escena['personajes']))}")
    trozos.append(f"TEXTO: {'si' if animar.lleva_texto(escena) else 'no'}")
    return " | ".join(trozos)


def planificar(proyecto, escenas, modo, avisar=None):
    """{sid: busqueda} de los planos que van con video real. Guardado por plan.

    Si Claude no contesta, {} y un aviso: el video sale entero con IA, que es
    lo que habria salido sin el modo.
    """
    if modo not in CRITERIOS:
        return {}, []
    aptas = [e for e in escenas if puede_ser_real(e) is None]
    if not aptas:
        return {}, []
    texto_plan = "\n".join(_linea(e) for e in aptas)
    huella = hashlib.sha1(f"{modo}\n{texto_plan}".encode("utf-8")).hexdigest()[:16]
    guardado = os.path.join(carpeta_de(proyecto), f"plan_{huella}.json")
    if os.path.exists(guardado):
        return medios.leer_json(guardado, {}) or {}, []
    if avisar:
        avisar(0.01, f"modo documental: Claude elige que planos van con video real "
                     f"({len(aptas)} candidatos)")
    instruccion = INSTRUCCION.format(criterio=CRITERIOS[modo], extra=EXTRA[modo],
                                     planos=texto_plan[:150000])
    try:
        texto, _ = cli_claude.ejecutar(instruccion, modelo="sonnet", esfuerzo="medium",
                                       cwd=proyecto.raiz, tiempo_max_s=600,
                                       para="elegir los planos con video real")
        encaje = re.search(r"\{.*\}", texto or "", re.S)
        crudo = json.loads(encaje.group(0)) if encaje else {}
    except Exception as fallo:                              # noqa: BLE001
        return {}, [f"Modo documental: Claude no ha podido elegir los planos con "
                    f"video real ({type(fallo).__name__}: {str(fallo)[:120]}). El "
                    f"video ha salido entero con IA."]
    ids = {e["id"] for e in aptas}
    plan = {sid: " ".join(str(b).split())[:80] for sid, b in (crudo or {}).items()
            if sid in ids and isinstance(b, str) and b.strip()}
    medios.escribir_json(guardado, plan)
    return plan, []


def _busqueda_guardada(carpeta, busqueda, vertical, ancho, stock):
    """Los candidatos de una busqueda, guardados: el cupo de Pexels es corto."""
    nombre = hashlib.sha1(f"{busqueda}|{vertical}|{ancho}".encode()).hexdigest()[:16]
    ruta = os.path.join(carpeta, "busquedas", f"{nombre}.json")
    if os.path.exists(ruta):
        return medios.leer_json(ruta, []) or [], []
    candidatos, avisos = stock.buscar(busqueda, vertical=vertical, ancho=ancho)
    if candidatos:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        medios.escribir_json(ruta, candidatos)
    return candidatos, avisos


def poner(candidatos, proyecto, ancho, alto, trabajo, avisar):
    """Busca, baja y engancha el clip real de cada candidato.

    `candidatos` son (tarea, escena, busqueda). A la tarea que sale bien se le
    ponen sus fotogramas (como a un plano animado). -> (ids puestos, avisos)
    Los que no se encuentran se devuelven fuera para que sigan con la IA.
    """
    if not candidatos:
        return set(), []
    stock = medios.motor("video_stock/stock.py")
    if not stock.con_clave():
        return set(), [f"Modo documental: {len(candidatos)} plano(s) iban con video "
                       f"real, pero no hay clave de Pexels ni de Pixabay "
                       f"(Configuración › Claves › Vídeo). Han salido con IA."]
    carpeta = carpeta_de(proyecto)
    vertical = alto > ancho
    usados, candado = set(), threading.Lock()
    # UNA BUSQUEDA A LA VEZ POR TEXTO: dos planos que piden «harbour» a la vez
    # irian los dos a la red antes de que el primero la guardara, y el cupo de
    # Pexels (200 por hora) no esta para gastarlo dos veces.
    por_busqueda, candado_busquedas = {}, threading.Lock()
    puestos, no_hallados, avisos_red, creditos = set(), [], [], {}

    def elegir(escena, busqueda):
        duracion = float(escena["t_out"]) - float(escena["t_in"])
        with candado_busquedas:
            propio = por_busqueda.setdefault(busqueda, threading.Lock())
        with propio:
            lista, avisos = _busqueda_guardada(carpeta, busqueda, vertical, ancho, stock)
        with candado:
            avisos_red.extend(avisos)
            for c in lista:
                if c["id"] in usados or c["duracion"] < duracion + MARGEN_S:
                    continue
                usados.add(c["id"])
                return c
        return None

    def uno(tarea, escena, busqueda):
        clip = elegir(escena, busqueda)
        if clip is None:
            return tarea, None, None
        destino = os.path.join(carpeta, "clips", f"{clip['id']}.mp4")
        if not (os.path.exists(destino) and os.path.getsize(destino) > 0):
            stock.descargar(clip["url"], destino)
        segundos = float(escena["t_out"]) - float(escena["t_in"])
        rutas, fps_clip = animar.fotogramas(
            destino, os.path.join(trabajo, "reales", tarea["id"]), ancho, alto, segundos)
        return tarea, clip, (rutas, fps_clip)

    avisar(0.015, f"modo documental: buscando {len(candidatos)} video(s) reales")
    with ThreadPoolExecutor(max_workers=A_LA_VEZ) as pool:
        futuros = [pool.submit(uno, *c) for c in candidatos]
        for hechos, futuro in enumerate(as_completed(futuros), 1):
            try:
                tarea, clip, cuadros = futuro.result()
            except Exception as fallo:                      # noqa: BLE001
                avisos_red.append(f"{type(fallo).__name__}: {str(fallo)[:120]}")
                continue
            if clip is None:
                no_hallados.append(tarea["id"])
                continue
            rutas, fps_clip = cuadros
            tarea["fotogramas"] = rutas
            tarea["fps_clip"] = fps_clip
            tarea["hyper"] = rutas[0]
            tarea["mov"] = {"ventana_ini": [0, 0, 1, 1], "ventana_fin": [0, 0, 1, 1],
                            "hyperframe_px": [ancho, alto]}
            tarea["real"] = clip["id"]
            puestos.add(tarea["id"])
            creditos[tarea["id"]] = {k: clip[k] for k in
                                     ("banco", "id", "autor", "pagina")}
            avisar(0.015 + 0.01 * hechos / len(candidatos),
                   f"modo documental: {len(puestos)} de {len(candidatos)} videos reales")

    # DE DONDE SALE CADA CLIP. Las licencias no obligan a citar, pero un canal
    # puede querer agradecerlo en la descripcion, y es lo que se mira si alguien
    # reclama un video.
    if creditos:
        previos = medios.leer_json(os.path.join(carpeta, "creditos.json"), {}) or {}
        previos.update(creditos)
        medios.escribir_json(os.path.join(carpeta, "creditos.json"), previos)

    avisos = []
    if puestos:
        avisos.append(f"Modo documental: {len(puestos)} plano(s) con video real de "
                      f"Pexels/Pixabay (gratis). La lista con autores está en "
                      f"pasos/render/reales/creditos.json.")
    if no_hallados:
        avisos.append(f"{len(no_hallados)} plano(s) no encontraron un video real que "
                      f"durase lo bastante y siguen con IA: "
                      + ", ".join(no_hallados[:8])
                      + (f" y {len(no_hallados) - 8} más" if len(no_hallados) > 8 else ""))
    if avisos_red:
        unicos = list(dict.fromkeys(avisos_red))
        avisos.append("Los bancos de video avisaron: " + "; ".join(unicos[:3]))
    return puestos, avisos
