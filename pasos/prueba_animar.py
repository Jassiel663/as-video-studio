"""
Pruebas de animar: que planos se animan con Veo y como llega el clip al render.

Lo que se protege aqui, por orden de lo que cuesta si se rompe:

  1. NINGUN PLANO CON TEXTO SE ANIMA. Veo deforma las letras (medido el
     29-09-2026: una notificacion que desaparece, una cifra ilegible). Un plano
     con texto animado es un plano estropeado Y pagado.
  2. UN CLIP NO SE PAGA DOS VECES. Volver a renderizar reutiliza el del cache;
     solo otra imagen u otro prompt piden uno nuevo.
  3. APAGADO ES LO DE SIEMPRE. Sin `video_ia` el render no pregunta nada a
     Veo, y la pagina de un plano normal no cambia.
  4. UN CLIP QUE FALLA NO TUMBA EL RENDER: ese plano sale con imagen y zoom y
     se dice en los avisos.

NINGUNA LLAMADA SALE A GOOGLE: `generar` se sustituye por un doble que devuelve
un MP4 hecho aqui con ffmpeg (si no hay ffmpeg, esa parte se omite y se dice).
"""
import os
import shutil
import subprocess
import sys
import tempfile

TEMPORAL = tempfile.mkdtemp(prefix="prueba_animar_")
# ANTES de importar nada del Estudio: las claves de mentira van a una carpeta
# propia y el gasto global a un fichero de la prueba
os.environ["ESTUDIO_SECRETOS"] = os.path.join(TEMPORAL, "secretos")
os.environ["ESTUDIO_COSTE_GLOBAL"] = os.path.join(TEMPORAL, "coste_global.jsonl")
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("FAL_KEY", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import animar  # noqa: E402
import claves  # noqa: E402
import medios  # noqa: E402
import p8_render  # noqa: E402
from nucleo import coste as COSTE  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, obtenido, esperado):
    comprobar(titulo, obtenido == esperado,
              f"esperaba {esperado!r}, salio {obtenido!r}")


def escena(sid="S001", t_in=0.0, t_out=3.0, **extra):
    base = {"id": sid, "t_in": t_in, "t_out": t_out,
            "direccion": "A calm harbour at dawn, boats rocking gently.",
            "accion": "The protagonist watches the sea.",
            "luz": "soft dawn light", "zoom": {"tipo": "in"}}
    base.update(extra)
    return base


veo = medios.motor("video_veo/veo.py")

print("\n== el modo: apagado salvo que se pida bien ==")
igual("sin params, apagado", animar.modo_de(None), "")
igual("vacio, apagado", animar.modo_de({"video_ia": ""}), "")
igual("mayusculas y espacios se normalizan", animar.modo_de({"video_ia": " FAST "}), "fast")
igual("un modo inventado se lee como apagado", animar.modo_de({"video_ia": "turbo"}), "")

print("\n== la duracion que se pide a Veo ==")
igual("2,6 s se piden de 4 a 720p", veo.duracion_de_clip(2.6), (4, "720p"))
igual("4 s justos, de 4", veo.duracion_de_clip(4.0), (4, "720p"))
igual("5 s, de 6", veo.duracion_de_clip(5.0), (6, "720p"))
igual("7 s necesitan el de 8, que es 1080p", veo.duracion_de_clip(7.0), (8, "1080p"))
igual("9 s no caben en un clip", veo.duracion_de_clip(9.0), (None, None))

print("\n== que planos se animan: NINGUNO con texto ==")
igual("un plano limpio se anima", animar.motivo_para_no_animar(escena()), None)
comprobar("texto entre comillas: no",
          animar.motivo_para_no_animar(escena(
              direccion='A banner reading "Deposito recibido" slides in.')) is not None)
comprobar("comillas tipograficas tambien: no",
          animar.motivo_para_no_animar(escena(
              direccion="The sign says «CERRADO» in red.")) is not None)
comprobar("una cartela: no",
          animar.motivo_para_no_animar(escena(cartela="cifra")) is not None)
comprobar("una pantalla aunque no lleve comillas: no",
          animar.motivo_para_no_animar(escena(
              direccion="Close-up of a phone lying on the table.")) is not None)
comprobar("una capa vectorial en el plan: no",
          animar.motivo_para_no_animar(escena(capa_vectorial=[{"tipo": "flecha"}]))
          is not None)
comprobar("mas de 8 s: no",
          animar.motivo_para_no_animar(escena(t_out=9.5)) is not None)
comprobar("una capa SVG con algo visible: no",
          animar.motivo_para_no_animar(escena(), '<svg><text>Hola</text></svg>')
          is not None)
igual("una capa SVG vacia no molesta",
      animar.motivo_para_no_animar(escena(), '<svg xmlns="x"><defs></defs></svg>'), None)

print("\n== el primer plano: el gancho se anima aunque lleve texto ==")
con_letras = escena(direccion='A banner reading "Deposito recibido" slides in.')
igual("el primero con texto SI se anima",
      animar.motivo_para_no_animar(con_letras, primero=True), None)
comprobar("el mismo plano en otra posicion, no",
          animar.motivo_para_no_animar(con_letras) is not None)
comprobar("el primero de mas de 8 s sigue sin caber",
          animar.motivo_para_no_animar(escena(t_out=9.5), primero=True) is not None)
comprobar("el primero con capa grafica encima tampoco",
          animar.motivo_para_no_animar(escena(), '<svg><text>Hola</text></svg>',
                                       primero=True) is not None)
comprobar("a Veo se le pide dejar el texto quieto y legible",
          "stays EXACTLY as drawn" in animar.prompt_de(con_letras))
comprobar("y sin pedirle que quite las letras",
          ", text," not in animar.negativo_de(con_letras)
          and "garbled letters" in animar.negativo_de(con_letras))
igual("un plano sin texto sigue con el negativo de siempre (sus clips valen)",
      animar.negativo_de(escena()), animar.NEGATIVO)
comprobar("y su prompt no cambia", "stays EXACTLY" not in animar.prompt_de(escena()))

print("\n== el prompt: lo que pasa y como se mueve ==")
prompt = animar.prompt_de(escena())
comprobar("lleva la direccion del plano", "calm harbour" in prompt)
comprobar("lleva la accion", "watches the sea" in prompt)
comprobar("pide conservar el estilo", "style" in prompt.lower())
comprobar("zoom de entrada -> push-in", "push-in" in prompt)
comprobar("zoom de salida -> pull-back",
          "pull-back" in animar.prompt_de(escena(zoom={"tipo": "out"})))

print("\n== la prevision de coste ==")
plan = [escena("S001", 0, 2.6), escena("S002", 2.6, 7.6),
        escena("S003", 7.6, 10.0, direccion='A poster reading "SALE".')]
igual("apagado no cuesta nada", animar.prevision(plan, ""),
      {"clips": 0, "segundos": 0, "usd": 0.0})
fast = animar.prevision(plan, "fast")
igual("fast: dos clips (el del cartel no)", fast["clips"], 2)
con_gancho = [escena("S001", 0, 2.6, direccion='A sign reading "OPEN".')] + plan[1:]
igual("el primero con texto tambien cuenta en la prevision",
      animar.prevision(con_gancho, "fast")["clips"], 2)
igual("fast: 4 + 6 segundos pagados", fast["segundos"], 10)
igual("fast: 10 s a 0,10 $", fast["usd"], 1.0)
igual("lite: la mitad", animar.prevision(plan, "lite")["usd"], 0.5)

print("\n== cuantos planos: de solo el primero a todos ==")
igual("sin ponerlo es sin_texto, lo de siempre", animar.alcance_de({}), "sin_texto")
igual("un valor raro tambien", animar.alcance_de({"video_ia_planos": "muchos"}),
      "sin_texto")
igual("y lo bien escrito se respeta", animar.alcance_de({"video_ia_planos": " TODOS "}),
      "todos")
texto = escena(direccion='A poster reading "SALE".')
comprobar("solo el primero: un plano limpio en otra posicion NO",
          animar.motivo_para_no_animar(escena(), alcance="primero", indice=3) is not None)
igual("solo el primero: el primero si",
      animar.motivo_para_no_animar(escena(), primero=True, alcance="primero"), None)
comprobar("mitad: uno con texto en posicion impar sigue quieto",
          animar.motivo_para_no_animar(texto, alcance="mitad", indice=3) is not None)
igual("mitad: en posicion par se anima",
      animar.motivo_para_no_animar(texto, alcance="mitad", indice=4), None)
igual("mitad: los sin texto se animan todos, pares o impares",
      animar.motivo_para_no_animar(escena(), alcance="mitad", indice=3), None)
igual("todos: tambien el de texto",
      animar.motivo_para_no_animar(texto, alcance="todos", indice=3), None)
comprobar("todos: pero no el que lleva capa grafica encima",
          animar.motivo_para_no_animar(escena(), '<svg><text>Hola</text></svg>',
                                       alcance="todos", indice=3) is not None)
comprobar("todos: ni el que no cabe en un clip",
          animar.motivo_para_no_animar(escena(t_out=9.5), alcance="todos") is not None)
largo = [escena(f"S{i:03d}", i * 3.0, i * 3.0 + 3.0,
                direccion=('A sign reading "OPEN".' if i % 3 else "A quiet field."))
         for i in range(12)]
cuentas = [animar.prevision(largo, "lite", a)["clips"] for a in animar.ALCANCES]
igual("cada escalon anima lo del anterior y mas (12 planos)", cuentas, [1, 4, 8, 12])
comprobar("y cuesta mas en el mismo orden",
          [animar.prevision(largo, "lite", a)["usd"] for a in animar.ALCANCES]
          == sorted(animar.prevision(largo, "lite", a)["usd"] for a in animar.ALCANCES))

print("\n== el fotograma de partida ==")
try:
    from PIL import Image
    origen = os.path.join(TEMPORAL, "plano.png")
    Image.new("RGB", (1536, 1024), (40, 90, 160)).save(origen)
    salida = animar.preparar_imagen(origen, os.path.join(TEMPORAL, "e.png"), 1920, 1080)
    with Image.open(salida) as im:
        igual("horizontal: 1280x720 para Veo", im.size, (1280, 720))
    vertical = os.path.join(TEMPORAL, "plano_v.png")
    Image.new("RGB", (1024, 1536), (40, 90, 160)).save(vertical)
    salida = animar.preparar_imagen(vertical, os.path.join(TEMPORAL, "ev.png"), 1080, 1920)
    with Image.open(salida) as im:
        igual("vertical: 720x1280", im.size, (720, 1280))
except ImportError:
    print("  (sin Pillow: se omite)")

print("\n== el clip: se paga UNA vez ==")
hay_ffmpeg = bool(shutil.which(medios.ffmpeg()) or os.path.exists(medios.ffmpeg()))
if not hay_ffmpeg:
    print("  (sin ffmpeg: se omite la parte de clips y fotogramas)")
else:
    muestra = os.path.join(TEMPORAL, "muestra.mp4")
    subprocess.run([medios.ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi",
                    "-i", "testsrc=size=320x180:rate=24:duration=4",
                    "-pix_fmt", "yuv420p", muestra], check=True)
    with open(muestra, "rb") as fh:
        BYTES = fh.read()
    llamadas, pagos = [], []
    original_generar = veo.generar
    original_reportar = animar.COSTE.reportar_veo

    def doble(imagen, prompt, **kw):
        llamadas.append(kw)
        return BYTES, {"modelo": veo.MODELOS[kw["modo"]], "modo": kw["modo"],
                       "segundos": kw["segundos"], "resolucion": kw["resolucion"]}

    veo.generar = doble
    animar.COSTE.reportar_veo = lambda *a, **k: pagos.append((a, k))

    class Proyecto:
        raiz = os.path.join(TEMPORAL, "proyecto")

    try:
        ruta, pagado, _ = animar.clip(Proyecto, escena(), origen, 1920, 1080, "fast")
        comprobar("la primera vez se paga", pagado and os.path.exists(ruta))
        igual("y se pide de 4 s a 720p", (llamadas[-1]["segundos"],
                                          llamadas[-1]["resolucion"]), (4, "720p"))
        igual("y se anota el gasto una vez", len(pagos), 1)
        ruta2, pagado2, _ = animar.clip(Proyecto, escena(), origen, 1920, 1080, "fast")
        comprobar("la segunda sale del cache, sin pagar", not pagado2 and ruta2 == ruta)
        igual("sin llamar a Veo otra vez", len(llamadas), 1)
        animar.clip(Proyecto, escena(), origen, 1920, 1080, "lite")
        igual("otro modelo es otro clip", len(llamadas), 2)

        cuadros, fps_clip = animar.fotogramas(ruta, os.path.join(TEMPORAL, "f"),
                                              640, 360, 2.6)
        comprobar("fotogramas al fps del clip (24)", abs(fps_clip - 24.0) < 0.01, fps_clip)
        comprobar("solo lo que dura el plano (~2,6 s)", 60 <= len(cuadros) <= 70,
                  len(cuadros))
        with Image.open(cuadros[0]) as im:
            igual("escalados al cuadro del video", im.size, (640, 360))

        print("\n== el render: engancha el clip o deja el plano como estaba ==")
        tarea = {"id": "S001", "hyper": origen,
                 "mov": {"ventana_ini": [0.1, 0.1, 0.8, 0.8],
                         "ventana_fin": [0.2, 0.2, 0.6, 0.6]}}
        avisos = p8_render._animar_tareas(
            [(tarea, escena(), origen, tarea["mov"])], Proyecto, "fast",
            640, 360, os.path.join(TEMPORAL, "trabajo"), lambda *a: None)
        comprobar("sin clave de Google no se anima y se dice",
                  "fotogramas" not in tarea and avisos and "clave" in avisos[0])

        os.environ["GEMINI_API_KEY"] = "clave-de-mentira"
        avisos = p8_render._animar_tareas(
            [(tarea, escena(), origen, tarea["mov"])], Proyecto, "fast",
            640, 360, os.path.join(TEMPORAL, "trabajo"), lambda *a: None)
        comprobar("con clave, la tarea lleva sus fotogramas", bool(tarea.get("fotogramas")))
        igual("y la ventana va a cuadro completo", tarea["mov"]["ventana_ini"], [0, 0, 1, 1])
        comprobar("y el aviso cuenta el plano animado",
                  avisos and avisos[0].startswith("1 plano(s) animados"), avisos)

        def rechaza(*a, **k):
            raise veo.Rechazado("filtro de contenido")
        veo.generar = rechaza
        otra = {"id": "S009", "hyper": origen,
                "mov": {"ventana_ini": [0, 0, 1, 1], "ventana_fin": [0, 0, 1, 1]}}
        avisos = p8_render._animar_tareas(
            [(otra, escena("S009", direccion="A different harbour."), origen, otra["mov"])],
            Proyecto, "fast", 640, 360, os.path.join(TEMPORAL, "trabajo"),
            lambda *a: None)
        comprobar("un clip rechazado deja el plano quieto",
                  "fotogramas" not in otra and otra["hyper"] == origen)
        comprobar("y se dice en los avisos", avisos and "S009" in " ".join(avisos), avisos)

        print("\n== sin cuota: no se pide mas, y lo guardado se sigue usando ==")
        # uno guardado de antes (con el doble bueno) y dos que no estan
        veo.generar = doble
        guardada = escena("S020", direccion="A quiet street at night.")
        animar.clip(Proyecto, guardada, origen, 640, 360, "fast",
                    ventana=[0, 0, 1, 1])
        pedidas = []

        def sin_cuota(*a, **k):
            pedidas.append(1)
            raise veo.CuotaAgotada("You exceeded your current quota")
        veo.generar = sin_cuota
        mov = {"ventana_ini": [0, 0, 1, 1], "ventana_fin": [0, 0, 1, 1]}
        t1 = {"id": "S021", "hyper": origen, "mov": dict(mov)}
        t2 = {"id": "S020", "hyper": origen, "mov": dict(mov)}
        t3 = {"id": "S022", "hyper": origen, "mov": dict(mov)}
        antes = p8_render.ANIMAR_A_LA_VEZ
        p8_render.ANIMAR_A_LA_VEZ = 1           # en orden, para poder contarlo
        try:
            avisos = p8_render._animar_tareas(
                [(t1, escena("S021", direccion="A windy beach."), origen, mov),
                 (t2, guardada, origen, mov),
                 (t3, escena("S022", direccion="A foggy forest."), origen, mov)],
                Proyecto, "fast", 640, 360, os.path.join(TEMPORAL, "trabajo"),
                lambda *a: None)
        finally:
            p8_render.ANIMAR_A_LA_VEZ = antes
        igual("se pide UNA vez; tras la cuota agotada no se pide mas", len(pedidas), 1)
        comprobar("el clip guardado se usa igual", bool(t2.get("fotogramas")), t2)
        comprobar("los otros dos quedan quietos",
                  "fotogramas" not in t1 and "fotogramas" not in t3)
        texto = " ".join(avisos)
        comprobar("y el aviso dice que es la cuota, y que no se ha cobrado",
                  "sin cuota" in texto and "sin cobrarse" in texto, avisos)

        print("\n== el respaldo de fal.ai: Google sin cuota, fal toma el relevo ==")
        fal = medios.motor("video_fal/fal.py")
        original_fal = fal.generar
        original_reportar_fal = animar.COSTE.reportar_fal
        modelos_fal, pagos_fal = [], []

        def doble_fal(imagen, prompt, **kw):
            modelos_fal.append(kw["modelo"])
            return BYTES, {"modelo": fal.MODELOS[kw["modelo"]], "corto": kw["modelo"],
                           "segundos": kw["segundos"]}
        fal.generar = doble_fal
        animar.COSTE.reportar_fal = lambda *a, **k: pagos_fal.append((a, k))
        os.environ["FAL_KEY"] = "id:de-mentira"
        pedidas.clear()
        gancho = escena("S030", direccion='A sign reading "OPEN" swings.')
        tp = {"id": "S030", "hyper": origen, "mov": dict(mov), "primero": True}
        tk = {"id": "S031", "hyper": origen, "mov": dict(mov)}
        p8_render.ANIMAR_A_LA_VEZ = 1
        try:
            avisos = p8_render._animar_tareas(
                [(tp, gancho, origen, mov),
                 (tk, escena("S031", direccion="A calm lake at dusk."), origen, mov)],
                Proyecto, "fast", 640, 360, os.path.join(TEMPORAL, "trabajo"),
                lambda *a: None)
        finally:
            p8_render.ANIMAR_A_LA_VEZ = antes
        igual("a Google se le pregunta una vez y luego ya no", len(pedidas), 1)
        comprobar("los dos planos se animan igual", bool(tp.get("fotogramas"))
                  and bool(tk.get("fotogramas")))
        igual("el primero con texto va con Veo Fast, el otro con Kling",
              modelos_fal, ["veofast", "kling"])
        igual("y se anotan los dos gastos en fal", len(pagos_fal), 2)
        comprobar("y el aviso dice que tomo el relevo fal.ai",
                  "fal.ai" in " ".join(avisos), avisos)
        igual("Kling pide su clip de 5 s (no hay de 4)",
              fal.duracion_de_clip("kling", 2.6), 5)
        igual("y de 10 para un plano de 7", fal.duracion_de_clip("kling", 7.0), 10)

        modelos_fal.clear()

        def fal_sin_saldo(*a, **k):
            modelos_fal.append(1)
            raise fal.SinSaldo("la cuenta de fal.ai no tiene saldo")
        fal.generar = fal_sin_saldo
        u1 = {"id": "S040", "hyper": origen, "mov": dict(mov)}
        u2 = {"id": "S041", "hyper": origen, "mov": dict(mov)}
        p8_render.ANIMAR_A_LA_VEZ = 1
        try:
            avisos = p8_render._animar_tareas(
                [(u1, escena("S040", direccion="A red barn."), origen, mov),
                 (u2, escena("S041", direccion="A blue boat."), origen, mov)],
                Proyecto, "fast", 640, 360, os.path.join(TEMPORAL, "trabajo"),
                lambda *a: None)
        finally:
            p8_render.ANIMAR_A_LA_VEZ = antes
            fal.generar = original_fal
            animar.COSTE.reportar_fal = original_reportar_fal
            os.environ.pop("FAL_KEY", None)
        igual("fal sin saldo: se le pide UNA vez y no mas", len(modelos_fal), 1)
        comprobar("y los planos quedan quietos, avisado",
                  "fotogramas" not in u1 and "fotogramas" not in u2
                  and "sin cobrarse" in " ".join(avisos), avisos)

        print("\n== a la vez: Google de cuatro en cuatro, fal.ai de ocho en ocho ==")
        import threading
        import time
        cuenta = {"ahora": 0, "maximo": 0}
        candado_cuenta = threading.Lock()

        def contando(resultado):
            def generar(*a, **k):
                with candado_cuenta:
                    cuenta["ahora"] += 1
                    cuenta["maximo"] = max(cuenta["maximo"], cuenta["ahora"])
                time.sleep(0.3)
                with candado_cuenta:
                    cuenta["ahora"] -= 1
                return resultado(k)
            return generar

        def lote(prefijo, n):
            tareas = []
            for i in range(n):
                sid = f"{prefijo}{i:02d}"
                t = {"id": sid, "hyper": origen, "mov": dict(mov)}
                tareas.append((t, escena(sid, direccion=f"Harbour number {sid}."),
                               origen, mov))
            return tareas

        veo.generar = contando(lambda k: doble(None, None, **k))
        p8_render._animar_tareas(
            lote("S1", 12), Proyecto, "fast", 640, 360,
            os.path.join(TEMPORAL, "trabajo"), lambda *a: None)
        igual("con ocho hilos, a Google nunca le llegan mas de cuatro",
              cuenta["maximo"], animar.GOOGLE_A_LA_VEZ)

        cuenta["maximo"] = 0
        veo.generar = sin_cuota
        fal.generar = contando(lambda k: doble_fal(None, None, **k))
        animar.COSTE.reportar_fal = lambda *a, **k: None
        os.environ["FAL_KEY"] = "id:de-mentira"
        try:
            # el primero agota Google; los demas van directos a fal
            p8_render._animar_tareas(
                lote("S2", 12), Proyecto, "fast", 640, 360,
                os.path.join(TEMPORAL, "trabajo"), lambda *a: None)
        finally:
            fal.generar = original_fal
            animar.COSTE.reportar_fal = original_reportar_fal
            os.environ.pop("FAL_KEY", None)
        igual("y a fal.ai le llegan ocho a la vez",
              cuenta["maximo"], p8_render.ANIMAR_A_LA_VEZ)

        print("\n== leer el 429 de Google ==")

        class Respuesta:
            def __init__(self, cuerpo):
                self.cuerpo = cuerpo
                self.text = str(cuerpo)

            def json(self):
                return self.cuerpo
        diario = Respuesta({"error": {"message": "You exceeded your current quota",
                                      "details": [{"violations": [{
                                          "quotaId": "PredictLongRunningRequestsPerDayPerProject"}]}]}})
        igual("un quotaId PerDay es cuota diaria", veo._detalle_429(diario)[0], True)
        minuto = Respuesta({"error": {"message": "Resource exhausted",
                                      "details": [{"violations": [{
                                          "quotaId": "RequestsPerMinutePerProject"}]},
                                          {"retryDelay": "37s"}]}})
        igual("uno de minuto no es diario y trae su espera",
              veo._detalle_429(minuto)[:2], (False, 37.0))
        igual("sin detalles se toma como de minuto",
              veo._detalle_429(Respuesta({"error": {"message": "x"}}))[:2], (False, None))
    finally:
        veo.generar = original_generar
        animar.COSTE.reportar_veo = original_reportar
        os.environ.pop("GEMINI_API_KEY", None)

print("\n== la pagina del render ==")
normal = p8_render._pagina_de({"t_in": 0, "t_out": 2},
                              {"ventana_ini": [0, 0, 1, 1], "ventana_fin": [0, 0, 1, 1]},
                              "", "fondo.png", {"resolucion": [640, 360]},
                              os.path.join(TEMPORAL, "normal.html"))
with open(normal, encoding="utf-8") as fh:
    texto = fh.read()
comprobar("un plano normal no lleva fotogramas", "const FOTOGRAMAS = []" in texto)
comprobar("y no queda ningun hueco sin rellenar", "__" not in texto.split("<script>")[1]
          .replace("__proto__", ""))
animada = p8_render._pagina_de({"t_in": 0, "t_out": 2},
                               {"ventana_ini": [0, 0, 1, 1], "ventana_fin": [0, 0, 1, 1]},
                               "", "fondo.png", {"resolucion": [640, 360]},
                               os.path.join(TEMPORAL, "animada.html"),
                               fotogramas=["/a/v00001.jpg", "/a/v00002.jpg"],
                               fps_clip=24)
with open(animada, encoding="utf-8") as fh:
    texto = fh.read()
comprobar("un plano animado lleva sus fotogramas", "v00002.jpg" in texto)
comprobar("y el fps del clip", "FPS_CLIP = 24.0000" in texto)

print("\n== la clave de Google en el almacen ==")
claves.guardar({"google": {"clave": "AQ.prueba1234"}})
resumen = claves.resumen()
comprobar("se guarda y se ve como puesta", resumen["google"]["puesta"])
igual("sin ensenar la clave entera", resumen["google"]["cola"], "…1234")
with open(claves.FICHERO_ENV, encoding="utf-8") as fh:
    comprobar("se espeja en el .env como GEMINI_API_KEY",
              "GEMINI_API_KEY=AQ.prueba1234" in fh.read())
os.environ.pop("GEMINI_API_KEY", None)
comprobar("y el motor la encuentra por contrato", veo.clave() == "AQ.prueba1234")
claves.guardar({"google": {"clave": ""}})
comprobar("quitarla la borra del .env",
          "GEMINI_API_KEY" not in open(claves.FICHERO_ENV, encoding="utf-8").read())

print("\n== el gasto ==")
sin = COSTE.agregar([{"proveedor": "openai", "usd": 1.0}])
comprobar("un video sin Veo no lo menciona en la cabecera", "Veo" not in sin["cabecera"])
con = COSTE.agregar([{"proveedor": "openai", "usd": 1.0},
                     {"proveedor": "veo", "usd": 0.4}])
comprobar("con Veo, sale en la cabecera", "Veo" in con["cabecera"])
igual("y suma al total", con["total_usd"], 1.4)
igual("la tarifa de fast a 720p", COSTE.tarifa_veo(veo.MODELOS["fast"], "720p"), 0.1)

shutil.rmtree(TEMPORAL, ignore_errors=True)
print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("ANIMAR OK: todas las comprobaciones pasan")
