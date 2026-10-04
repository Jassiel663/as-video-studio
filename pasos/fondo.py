"""
EL FONDO de un clip o un short: musica debajo y efectos en los cortes. Gratis.

    musica   un tema de Jamendo con el ANIMO elegido (motivacional, epica...),
             normalizado bajo y que se APARTA SOLO cuando alguien habla
             (sidechain: la voz manda), con fundido de entrada y de salida.
    efectos  un «whoosh» suave en cada corte del clip y un golpe al entrar el
             gancho, de Freesound, colocados por su GOLPE y no por su primera
             muestra (`sonido.golpe_de`).

Todo sale del banco del estudio (`sonido.banco`): lo que ya se bajo una vez no
se vuelve a pedir, y las busquedas se guardan una semana. Si la red o una clave
fallan, el clip sale igual, sin fondo, y se dice por que.

OJO con la licencia: los temas de Jamendo son Creative Commons y muchos son
«no comercial». El titulo, el artista y la licencia se apuntan en el clip para
poner el credito; para monetizar, mejor temas con licencia comercial.
"""
import hashlib
import json
import os
import subprocess
import time

try:
    from . import medios, sonido
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import medios
    import sonido

ANIMOS = {
    "motivacional": "motivational uplifting inspiring",
    "epica": "epic cinematic powerful",
    "tension": "tense suspense dark",
    "alegre": "happy upbeat fun",
    "lofi": "lofi chill hiphop",
    "misterio": "mysterious ambient",
    "emotiva": "emotional piano",
}
CACHE_S = 7 * 86400
VOLUMEN_WHOOSH = 0.35
VOLUMEN_GOLPE = 0.5


def _guardado(nombre, crear):
    """Lo que devuelve `crear()`, guardado una semana en el banco."""
    ruta = sonido.banco("_busquedas", f"{nombre}.json")
    d = medios.leer_json(ruta, {}) or {}
    if d.get("lista") and time.time() - float(d.get("cuando") or 0) < CACHE_S:
        return d["lista"]
    lista = crear()
    if lista:
        medios.escribir_json(ruta, {"cuando": time.time(), "lista": lista})
    return lista


def musica(animo, semilla=""):
    """Un tema para ese animo, siempre el mismo para la misma semilla. -> (ruta, ficha)"""
    etiquetas = ANIMOS.get(animo)
    if not etiquetas:
        raise ValueError(f"animo de musica desconocido: {animo}")
    candidatos = _guardado(f"musica_{animo}", lambda: sonido.buscar_musica(etiquetas, duracion_s=120, cuantas=24))
    candidatos = [c for c in candidatos if c.get("descarga")]
    # PARA MONETIZAR, LOS DE USO COMERCIAL PRIMERO: «by-nc» no deja usarlos en
    # algo que gana dinero. Si no hay ninguno, se usan los demas (y el credito
    # dice la licencia).
    comerciales = [c for c in candidatos if "-nc" not in str(c.get("licencia") or "")]
    candidatos = comerciales or candidatos
    if not candidatos:
        raise RuntimeError("no ha salido ningun tema para ese animo")
    k = int(hashlib.sha1(str(semilla).encode()).hexdigest(), 16) % min(6, len(candidatos))
    for ficha in candidatos[k:] + candidatos[:k]:
        try:
            return sonido.traer(ficha, "musica"), ficha
        except Exception:                                   # noqa: BLE001
            continue
    raise RuntimeError("no se ha podido bajar ningun tema")


def efectos(papel, cuantos=4):
    """Rutas de efectos de ese papel ya bajados al banco."""
    fichas = _guardado(f"efectos_{papel}", lambda: [
        {k: f.get(k) for k in ("fuente", "id", "titulo", "descarga", "autor", "licencia")}
        for f in sonido.surtir(papel, cuantos)])
    rutas = []
    for ficha in fichas:
        try:
            rutas.append(sonido.traer(ficha, "efectos"))
        except Exception:                                   # noqa: BLE001
            continue
    return rutas


def mezclar(entrada, salida, ruta_musica=None, golpes=(), volumen_musica=1.0):
    """El video con la musica debajo (apartandose de la voz) y los efectos.

    `golpes`: [(segundo, ruta, volumen)] -- el efecto se coloca para que su
    golpe caiga en ese segundo. El video se copia tal cual."""
    duracion = medios.duracion_media(entrada) or 0
    if duracion <= 0:
        raise RuntimeError(f"no se puede medir {entrada}")
    orden = [medios.ffmpeg(), "-y", "-loglevel", "error", "-i", entrada]
    filtros = ["[0:a]aresample=48000,asplit=2[voz][sc]"]
    mezcla = ["[voz]"]
    n = 1
    if ruta_musica:
        orden += ["-stream_loop", "-1", "-i", ruta_musica]
        fuera = max(0.0, duracion - 1.2)
        filtros.append(
            f"[{n}:a]aresample=48000,atrim=0:{duracion:.3f},asetpts=PTS-STARTPTS,"
            f"loudnorm=I=-27:TP=-3:LRA=11,volume={volumen_musica:.2f},"
            f"afade=t=in:st=0:d=0.8,afade=t=out:st={fuera:.3f}:d=1.2[mus]")
        # la voz manda: la musica baja sola mientras se habla
        filtros.append("[mus][sc]sidechaincompress=threshold=0.025:ratio=8:attack=15:release=350[musb]")
        mezcla.append("[musb]")
        n += 1
    else:
        filtros.append("[sc]anullsink")
    for k, (t, ruta, volumen) in enumerate(golpes or []):
        if not ruta or not os.path.exists(ruta) or t >= duracion:
            continue
        retardo = max(0.0, float(t) - sonido.golpe_de(ruta))
        ms = int(retardo * 1000)
        orden += ["-i", ruta]
        filtros.append(f"[{n}:a]aresample=48000,volume={volumen:.2f},adelay={ms}|{ms}[e{k}]")
        mezcla.append(f"[e{k}]")
        n += 1
    if len(mezcla) == 1:
        filtros.append("[voz]anull[a]")
    else:
        filtros.append(f"{''.join(mezcla)}amix=inputs={len(mezcla)}:normalize=0:duration=first,"
                       "alimiter=limit=0.95[a]")
    orden += ["-filter_complex", ";".join(filtros), "-map", "0:v", "-map", "[a]",
              "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", salida]
    proceso = subprocess.run(orden, capture_output=True, text=True, timeout=1800, **medios.SIN_VENTANA)
    if proceso.returncode != 0 or not os.path.exists(salida):
        raise RuntimeError(f"no se ha podido mezclar el fondo: {proceso.stderr[-400:]}")
    return salida


def vestir_en_sitio(mp4, animo="", cortes=(), semilla="", con_efectos=True, gancho_en=0.0):
    """Musica y efectos sobre el propio fichero. -> {musica, efectos, aviso}"""
    info = {"musica": None, "efectos": 0, "aviso": ""}
    ruta_musica = None
    if animo:
        try:
            ruta_musica, ficha = musica(animo, semilla)
            info["musica"] = {"titulo": ficha.get("titulo"), "artista": ficha.get("artista"),
                              "licencia": ficha.get("licencia"), "animo": animo,
                              "comercial": "-nc" not in str(ficha.get("licencia") or "")}
        except Exception as fallo:                          # noqa: BLE001
            info["aviso"] = f"sin musica: {str(fallo)[:150]}"
    golpes = []
    if con_efectos:
        try:
            suaves = efectos("transicion_suave")
            fuertes = efectos("transicion_acento", 3)
            for k, t in enumerate(c for c in cortes if c > 0.5):
                if suaves:
                    golpes.append((t, suaves[k % len(suaves)], VOLUMEN_WHOOSH))
            if fuertes:
                golpes.append((max(0.05, gancho_en), fuertes[0], VOLUMEN_GOLPE))
        except Exception as fallo:                          # noqa: BLE001
            info["aviso"] = (info["aviso"] + "; " if info["aviso"] else "") + f"sin efectos: {str(fallo)[:150]}"
    if not ruta_musica and not golpes:
        return info
    base, ext = os.path.splitext(mp4)
    temporal = f"{base}.fondo{ext}"
    mezclar(mp4, temporal, ruta_musica, golpes)
    os.replace(temporal, mp4)
    info["efectos"] = len(golpes)
    return info
