"""
Pruebas del clipping (pasos/clipping.py). Con ffmpeg de verdad; Whisper y
Claude, de mentira.

  1. LAS SENALES de la ficha de YouTube: picos de «lo mas repetido», minutos
     citados en comentarios (con su peso) y capitulos.
  2. AJUSTAR: bordes en palabras, duracion entre el minimo y el maximo, mejor
     acabando en final de frase.
  3. ELEGIR: N clips sin solaparse, los de mas puntuacion; sin Claude, los
     picos de la grafica.
  4. Sin la casilla del permiso no se empieza.
  5. DE PUNTA A PUNTA: un video de 2 min -> 2 clips editados en vertical,
     guardados como shorts trabajados, con su version limpia y su .srt.
  6. Los estilos de subtitulos y re-editar un clip con otros minutos.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_clipping_")
os.environ["ESTUDIO_CLIPPING"] = os.path.join(TEMPORAL, "clipping")
os.environ["ESTUDIO_TRABAJADOS"] = os.path.join(TEMPORAL, "trabajados")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cli_claude  # noqa: E402
import clipping  # noqa: E402
import medios  # noqa: E402
import trabajado  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def habla(total=120.0):
    """Una palabra cada 0,4 s; cada 10 palabras, final de frase."""
    palabras, t, k = [], 0.5, 0
    while t < total - 1:
        k += 1
        palabras.append({"p": f"palabra{k}" + ("." if k % 10 == 0 else ""), "i": round(t, 2), "f": round(t + 0.3, 2)})
        t += 0.4
    return palabras


P = habla()
original_cli, original_trans = cli_claude.ejecutar, trabajado.transcribir
try:
    print("\n== senales ==")
    info = {"title": "Podcast", "channel": "Canal X", "description": "desc",
            "heatmap": [{"start_time": s, "end_time": s + 10, "value": v}
                        for s, v in zip(range(0, 100, 10), [0.1, 0.2, 0.9, 0.3, 0.2, 0.1, 1.0, 0.4, 0.2, 0.1])],
            "chapters": [{"start_time": 0, "title": "Intro"}, {"start_time": 60, "title": "Lo bueno"}],
            "comments": [{"text": "el 1:05 jajaja", "like_count": 40}, {"text": "1:05 y 0:20!!", "like_count": 0},
                         {"text": "sin minutos"}, {"text": "en 99:99 no", "like_count": 3}]}
    sen = clipping.senales(info, duracion=120)
    comprobar("los picos de lo mas repetido, el mayor primero", sen["picos"][0][:2] == [60, 70] and sen["picos"][1][:2] == [20, 30], sen["picos"])
    comprobar("los minutos citados, con el peso de los likes", sen["citados"].get(65, 0) > sen["citados"].get(20, 0) > 0, sen["citados"])
    comprobar("los que se salen del video, fuera", all(s <= 120 for s in sen["citados"]))
    comprobar("capitulos y datos", sen["capitulos"][1] == [60, "Lo bueno"] and sen["titulo"] == "Podcast")
    comprobar("sin ficha, todo vacio y sin romper", clipping.senales({})["picos"] == [])

    print("\n== ajustar ==")
    a, b = clipping.ajustar({"inicio": 10.1, "fin": 40.0}, P, 30, 60)
    comprobar("empieza en una palabra", any(abs(w["i"] - 0.1 - a) < 0.01 for w in P), a)
    comprobar("dura entre 30 y 60", 30 <= b - a <= 60.6, b - a)
    ultima = max((w for w in P if w["f"] + 0.25 <= b + 0.01), key=lambda w: w["f"])
    comprobar("acaba en final de frase", ultima["p"].endswith("."), ultima)
    a, b = clipping.ajustar({"inicio": 50, "fin": 55}, P, 30, 60)
    comprobar("si Claude lo da corto, se alarga al minimo", b - a >= 30, b - a)
    a, b = clipping.ajustar({"inicio": 5, "fin": 110}, P, 30, 60)
    comprobar("si lo da largo, se recorta al maximo", b - a <= 60.6, b - a)

    print("\n== elegir ==")
    respuesta = {"clips": [
        {"inicio": 10, "fin": 45, "titulo": "Uno", "gancho": "MIRA ESTO", "porque": "p", "puntuacion": 7, "hashtags": ["#a"]},
        {"inicio": 20, "fin": 50, "titulo": "Se pisa", "gancho": "", "porque": "", "puntuacion": 6},
        {"inicio": 70, "fin": 105, "titulo": "Dos", "gancho": "OJO", "porque": "q", "puntuacion": 9},
        {"inicio": "x", "fin": 3}]}
    pedidos = []

    def claude(instruccion, **kw):
        pedidos.append(instruccion)
        return "aqui va\n" + json.dumps(respuesta), {}

    cli_claude.ejecutar = claude
    clips, por_claude = clipping.elegir(P, sen, 2, 30, 60)
    comprobar("dos clips, sin solaparse, en orden del video", [c["titulo"] for c in clips] == ["Uno", "Dos"], clips)
    comprobar("numerados", [c["n"] for c in clips] == [1, 2])
    comprobar("el prompt lleva picos, citados y capitulos",
              "[60, 70, 1.0]" in pedidos[0] and "65" in pedidos[0] and "Lo bueno" in pedidos[0])
    cli_claude.ejecutar = lambda *a, **k: ("no se", {})
    clips, por_claude = clipping.elegir(P, sen, 2, 30, 60)
    comprobar("sin Claude, por los picos de la grafica", not por_claude and len(clips) == 2
              and any(c["inicio"] <= 65 <= c["fin"] for c in clips), clips)

    print("\n== permiso ==")
    falso = os.path.join(TEMPORAL, "v.mp4")
    open(falso, "wb").write(b"x")
    try:
        clipping.crear(falso, "x", permiso=False)
        comprobar("sin la casilla no se empieza", False)
    except ValueError as fallo:
        comprobar("sin la casilla no se empieza", "permiso" in str(fallo))

    print("\n== de punta a punta ==")
    video = os.path.join(TEMPORAL, "largo.mp4")
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=1280x720:rate=30:duration=120", "-f", "lavfi", "-i",
                    "sine=frequency=300:duration=120", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", video], check=True, timeout=600)
    info_ruta = os.path.join(TEMPORAL, "largo.info.json")
    json.dump(info, open(info_ruta, "w"))
    trabajado.transcribir = lambda wav, idioma=None: (P, "es")
    cli_claude.ejecutar = claude
    ficha = clipping.crear(video, "Mi podcast", "", {"n": 2, "min_s": 30, "max_s": 60, "estilo_sub": "pop"},
                           ruta_info=info_ruta, permiso=True, url="https://youtu.be/x")
    comprobar("apunta el permiso y la ficha", ficha["permiso"] and ficha["con_ficha"] and ficha["picos"] > 0)
    for _ in range(600):
        if clipping.leer(ficha["id"]).get("estado") != "trabajando":
            break
        time.sleep(1)
    f = clipping.leer(ficha["id"])
    comprobar("termina bien", f.get("estado") == "listo", f.get("error"))
    clips = f.get("clips") or []
    comprobar("dos clips listos", len(clips) == 2 and all(c.get("estado") == "listo" for c in clips), clips)
    for c in clips:
        t = trabajado.leer(c["trabajado"])
        mp4 = trabajado._ruta(c["trabajado"], "final.mp4")
        dur = medios.duracion_media(mp4) or 0
        comprobar(f"clip {c['n']}: es un short trabajado listo", t.get("estado") == "listo" and t.get("origen") == "clipping")
        comprobar(f"clip {c['n']}: dura lo que el tramo", abs(dur - (c["fin"] - c["inicio"])) < 1.0, (dur, c["fin"] - c["inicio"]))
        sonda = subprocess.run([medios.ffprobe(), "-v", "error", "-select_streams", "v:0", "-show_entries",
                                "stream=width,height", "-of", "csv=p=0", mp4], capture_output=True, text=True).stdout.strip()
        comprobar(f"clip {c['n']}: vertical 1080x1920", sonda == "1080,1920", sonda)
        comprobar(f"clip {c['n']}: version limpia y .srt para CapCut",
                  os.path.exists(clipping.ruta_descarga(ficha["id"], c["n"], "limpio"))
                  and "-->" in open(clipping.ruta_descarga(ficha["id"], c["n"], "srt"), encoding="utf-8").read())
    comprobar("los clips salen en la lista de shorts trabajados", len([t for t in trabajado.listar() if t.get("origen") == "clipping"]) == 2)

    print("\n== re-editar y estilos ==")
    c1 = clips[0]
    clipping.rehacer_clip(ficha["id"], 1, 0, 35)
    for _ in range(300):
        if clipping.leer(ficha["id"]).get("estado") != "trabajando":
            break
        time.sleep(1)
    nuevo = clipping.leer(ficha["id"])["clips"][0]
    comprobar("re-editado con los minutos nuevos", nuevo["estado"] == "listo" and nuevo["inicio"] < 1 and nuevo["trabajado"] == c1["trabajado"], nuevo)
    paleta = {"texto": "#ffffff", "acento": "#ff3366", "sombra": "#000000"}
    for estilo in clipping.ESTILOS_SUB:
        ass = clipping._ass(P[:12], paleta, os.path.join(TEMPORAL, f"{estilo}.ass"), estilo)
        texto = open(ass, encoding="utf-8").read()
        comprobar(f"subtitulos «{estilo}»", "Dialogue:" in texto and "PlayResY: 1920" in texto)
    comprobar("«pop» rebota", r"\t(0,90,\fscx108" in open(os.path.join(TEMPORAL, "pop.ass"), encoding="utf-8").read())
    comprobar("«minimal» no va en mayusculas", "palabra1 " in open(os.path.join(TEMPORAL, "minimal.ass"), encoding="utf-8").read())
    clipping.borrar(ficha["id"])
    comprobar("borrar quita el clipping (los clips siguen como shorts)", not clipping.leer(ficha["id"])
              and len([t for t in trabajado.listar() if t.get("origen") == "clipping"]) == 2)
finally:
    cli_claude.ejecutar, trabajado.transcribir = original_cli, original_trans
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("CLIPPING OK: todas las comprobaciones pasan")
