"""
LAS COPIAS DE SEGURIDAD del estudio. Gratis, solas, una al dia.

Que se copia: TODO lo de datos/ que costo dinero o trabajo -- estilos, presets,
proyectos con su guion, su voz y sus imagenes (las de pago), el banco de
imagenes, los clips de Veo, el taller, los estudios, la marca, los avisos, el
piloto y las claves (secretos/).

Que NO: lo que se rehace gratis y pesa mucho -- los MP4 montados y los
fotogramas del render (pasos/render), las carpetas de trabajo a medias y el
modelo de Whisper (se vuelve a bajar).

Como: rsync con --link-dest. Cada copia parece completa, pero los ficheros que
no cambiaron desde la anterior son el MISMO fichero en disco (enlace duro), asi
que una copia diaria ocupa solo lo nuevo de ese dia.

Cuantas: las de los ultimos 7 dias, una por semana de las 4 anteriores y las 3
ultimas hechas a mano.

Recuperar NUNCA pisa nada: un video sale de la copia con otro id
(«<id>_recuperado_<fecha>») y el de ahora se queda como esta.

OJO: las copias viven en el MISMO disco que el estudio. Protegen de borrar
algo sin querer o de un fallo del programa; de un disco roto, no. Para eso hay
que sacarlas fuera (ver CLAUDE.md del proyecto).
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time

try:
    from . import avisos, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import avisos
    import presets_canal

DATOS = os.path.dirname(os.path.abspath(presets_canal.FICHERO))
CARPETA = os.environ.get("ESTUDIO_COPIAS") or os.path.join(os.path.dirname(DATOS), "copias")
#: Los estudios de las OTRAS cuentas (despliegue/asvs-cuentas): van en la misma
#: copia, dentro de `_cuentas/`, con las mismas exclusiones.
CUENTAS = os.environ.get("ESTUDIO_COPIAS_CUENTAS") or os.path.join(os.path.dirname(DATOS), "cuentas")
HORA = int(os.environ.get("ESTUDIO_COPIAS_HORA") or 4)       # 04:xx del servidor
EXCLUIR = ["proyectos/*/pasos/render/", "proyectos/*/pasos/*/trabajo/", "modelos/",
           "trabajados/_subidas/", "*.parcial/", "*.tmp", "*.marca.mp4", "*.viral.mp4"]
DIAS, SEMANAS, MANUALES = 7, 4, 3
_CANDADO = threading.Lock()
_ESTADO = {"haciendo": False, "error": "", "desde": 0}
_NOMBRE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}(_manual)?$")


def _copias():
    if not os.path.isdir(CARPETA):
        return []
    return sorted(n for n in os.listdir(CARPETA)
                  if _NOMBRE.match(n) and os.path.isdir(os.path.join(CARPETA, n)))


def listar():
    salida = []
    for nombre in reversed(_copias()):
        ruta = os.path.join(CARPETA, nombre)
        info = {}
        try:
            with open(os.path.join(ruta, ".copia.json"), encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            pass
        proyectos = []
        carpeta_p = os.path.join(ruta, "proyectos")
        if os.path.isdir(carpeta_p):
            for pid in sorted(os.listdir(carpeta_p)):
                try:
                    with open(os.path.join(carpeta_p, pid, "proyecto.json"), encoding="utf-8") as fh:
                        proyectos.append({"id": pid, "nombre": json.load(fh).get("nombre") or pid})
                except (OSError, ValueError):
                    continue
        salida.append({"nombre": nombre, "manual": nombre.endswith("_manual"),
                       "fecha": info.get("fecha") or nombre[:10], "segundos": info.get("segundos"),
                       "nuevo_mb": info.get("nuevo_mb"), "proyectos": proyectos})
    return {"copias": salida, "haciendo": _ESTADO["haciendo"], "error": _ESTADO["error"],
            "carpeta": CARPETA, "hora": HORA}


def _nuevo_mb(stats):
    m = re.search(r"Total transferred file size: ([\d,.]+)", stats or "")
    try:
        return round(float(m.group(1).replace(",", "")) / 1e6, 1) if m else None
    except ValueError:
        return None


def hacer(manual=False):
    """Una copia ahora (en el hilo que llama). -> nombre"""
    with _CANDADO:
        if _ESTADO["haciendo"]:
            raise ValueError("ya se esta haciendo una copia")
        _ESTADO.update(haciendo=True, error="", desde=time.time())
    try:
        os.makedirs(CARPETA, exist_ok=True)
        os.chmod(CARPETA, 0o700)
        nombre = time.strftime("%Y-%m-%d_%H%M") + ("_manual" if manual else "")
        destino = os.path.join(CARPETA, nombre)
        if os.path.exists(destino):
            raise ValueError("ya hay una copia de este mismo minuto")
        parcial = destino + ".parcial"
        if os.path.exists(parcial):
            shutil.rmtree(parcial)
        anteriores = _copias()
        orden = ["rsync", "-a", "--stats"] + [f"--exclude={e}" for e in EXCLUIR]
        if anteriores:
            orden.append(f"--link-dest={os.path.join(CARPETA, anteriores[-1])}")
        arranque = time.time()
        proceso = subprocess.run(orden + [DATOS.rstrip("/") + "/", parcial + "/"],
                                 capture_output=True, text=True, timeout=6 * 3600)
        # 24 = algun fichero desaparecio mientras se copiaba: normal con el
        # estudio trabajando, y lo demas esta bien copiado
        if proceso.returncode not in (0, 24):
            shutil.rmtree(parcial, ignore_errors=True)
            raise RuntimeError(f"rsync fallo ({proceso.returncode}): {proceso.stderr[-300:]}")
        if os.path.isdir(CUENTAS) and os.listdir(CUENTAS):
            orden_c = ["rsync", "-a", "--stats"] + [f"--exclude={e}" for e in EXCLUIR]
            if anteriores and os.path.isdir(os.path.join(CARPETA, anteriores[-1], "_cuentas")):
                orden_c.append(f"--link-dest={os.path.join(CARPETA, anteriores[-1], '_cuentas')}")
            otra = subprocess.run(orden_c + [CUENTAS.rstrip("/") + "/", os.path.join(parcial, "_cuentas") + "/"],
                                  capture_output=True, text=True, timeout=6 * 3600)
            if otra.returncode not in (0, 24):
                shutil.rmtree(parcial, ignore_errors=True)
                raise RuntimeError(f"rsync de las cuentas fallo ({otra.returncode}): {otra.stderr[-300:]}")
        with open(os.path.join(parcial, ".copia.json"), "w", encoding="utf-8") as fh:
            json.dump({"fecha": time.strftime("%Y-%m-%dT%H:%M:%S"), "manual": manual,
                       "segundos": round(time.time() - arranque, 1),
                       "nuevo_mb": _nuevo_mb(proceso.stdout)}, fh)
        os.rename(parcial, destino)
        podar()
        return nombre
    except Exception as fallo:                              # noqa: BLE001
        _ESTADO["error"] = str(fallo)[:300]
        raise
    finally:
        _ESTADO["haciendo"] = False


def podar(hoy=None):
    """Borra las copias AUTOMATICAS que sobran (nunca la ultima). -> borradas"""
    hoy = hoy or time.time()
    todas = _copias()
    automaticas = [n for n in todas if not n.endswith("_manual")]
    manuales = [n for n in todas if n.endswith("_manual")]
    quedan = set(manuales[-MANUALES:])
    if automaticas:
        quedan.add(automaticas[-1])
    por_dia, por_semana = {}, {}
    for n in automaticas:
        t = time.mktime(time.strptime(n[:10], "%Y-%m-%d"))
        edad = (hoy - t) / 86400
        if edad < DIAS:
            por_dia[n[:10]] = n                    # la ultima de cada dia
        elif edad < DIAS + 7 * SEMANAS:
            por_semana[time.strftime("%G-%V", time.localtime(t))] = n
    quedan |= set(por_dia.values()) | set(por_semana.values())
    borradas = [n for n in todas if n not in quedan]
    for n in borradas:
        shutil.rmtree(os.path.join(CARPETA, n), ignore_errors=True)
    return borradas


def recuperar_proyecto(copia, pid):
    """Saca un video de una copia con un id NUEVO. -> id nuevo"""
    if copia not in _copias():
        raise ValueError("esa copia no existe")
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", str(pid or "")):
        raise ValueError("id de video no valido")
    origen = os.path.join(CARPETA, copia, "proyectos", pid)
    if not os.path.isdir(origen):
        raise ValueError("ese video no esta en esa copia")
    nuevo = f"{pid}_recuperado_{copia[:10].replace('-', '')}"[:120]
    destino = os.path.join(DATOS, "proyectos", nuevo)
    n = 2
    while os.path.exists(destino):
        destino = os.path.join(DATOS, "proyectos", f"{nuevo}_{n}")
        n += 1
    shutil.copytree(origen, destino)
    ficha = os.path.join(destino, "proyecto.json")
    try:
        with open(ficha, encoding="utf-8") as fh:
            config = json.load(fh)
        config["id"] = os.path.basename(destino)
        config["nombre"] = f"{config.get('nombre') or pid} (recuperado {copia[:10]})"
        with open(ficha, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False, indent=2)
    except (OSError, ValueError):
        pass
    return os.path.basename(destino)


def _bucle():
    time.sleep(120)
    while True:
        try:
            ultima = (_copias() or [""])[-1]
            hoy = time.strftime("%Y-%m-%d")
            hechas_hoy = [n for n in _copias() if n.startswith(hoy) and not n.endswith("_manual")]
            if not hechas_hoy and time.localtime().tm_hour >= HORA:
                hacer()
            elif not ultima:
                hacer()
        except Exception as fallo:                          # noqa: BLE001
            try:
                avisos.avisar("error", "⚠️ No se ha podido hacer la copia de seguridad", str(fallo)[:300])
            except Exception:                               # noqa: BLE001
                pass
            time.sleep(3 * 3600)                           # no insistir cada 10 min
        time.sleep(600)


def arrancar():
    # una instancia de PRUEBA no hace copias (seria copiar 15 GB para nada)
    if os.environ.get("ESTUDIO_COPIAS_APAGADAS"):
        return
    threading.Thread(target=_bucle, daemon=True, name="copias").start()
