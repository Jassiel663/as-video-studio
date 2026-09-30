"""
Pruebas de la cola de trabajos pesados (`trabajos._Turno`).

Lo que se protege, por orden de lo que cuesta si se rompe:

  1. DOS TRABAJOS PESADOS NO CORREN A LA VEZ, aunque sean de videos distintos
     (cada video tiene su gestor): dos tandas de imagenes a la vez tardan el
     doble por imagen y pierden el registro del gasto.
  2. EL TURNO SE SUELTA SIEMPRE: si un trabajo revienta o se cancela, el
     siguiente empieza. Un turno que no se suelta es un estudio parado.
  3. LOS LIGEROS NO ESPERAN: el guion o la voz de otro video no hacen cola
     detras de un render de veinte minutos.
  4. UN TRABAJO EN COLA SE PUEDE CANCELAR, y entonces no llega a empezar.
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trabajos import TURNO, Cancelado, GestorTrabajos  # noqa: E402,F401

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def esperar_estado(gestor, tid, estados, limite=10.0):
    fin = time.time() + limite
    while time.time() < fin:
        if gestor.estado(tid)["estado"] in estados:
            return gestor.estado(tid)
        time.sleep(0.02)
    return gestor.estado(tid)


# cada trabajo apunta cuando empieza y cuando acaba, y se queda dentro hasta
# que se le abre su puerta: asi la prueba decide el orden y no el reloj
diario, candado = [], threading.Lock()


def pesado(avisar, nombre, puerta):
    with candado:
        diario.append(("empieza", nombre))
    while not puerta.wait(0.02):
        avisar(0.5)                      # la cancelacion entra por aqui
    with candado:
        diario.append(("acaba", nombre))
    return nombre


def revienta(avisar):
    raise RuntimeError("fallo a proposito")


video_a, video_b, video_c = GestorTrabajos(), GestorTrabajos(), GestorTrabajos()

print("\n== dos videos, dos trabajos pesados: de uno en uno ==")
puerta_a, puerta_b = threading.Event(), threading.Event()
ta = video_a.lanzar("render", pesado, "A", puerta_a, cola=True)
esperar_estado(video_a, ta, ("ejecutando",))
time.sleep(0.1)
tb = video_b.lanzar("imagenes", pesado, "B", puerta_b, cola=True)
time.sleep(0.4)
comprobar("A ha empezado", ("empieza", "A") in diario)
comprobar("B NO ha empezado mientras A corre", ("empieza", "B") not in diario, diario)
ficha_b = video_b.estado(tb)
comprobar("B se ve como ejecutando al 0 %, para que la pantalla lo pinte",
          ficha_b["estado"] == "ejecutando" and ficha_b["progreso"] == 0.0, ficha_b)
comprobar("B dice que esta en cola, con uno delante",
          ficha_b["en_cola"] and ficha_b["por_delante"] == 1, ficha_b)
comprobar("y lo dice en publico", ficha_b["publico"].startswith("En cola"), ficha_b["publico"])
puerta_a.set()
esperar_estado(video_a, ta, ("listo",))
esperar_estado(video_b, tb, ("ejecutando",))
time.sleep(0.2)
comprobar("al acabar A, empieza B", ("empieza", "B") in diario, diario)
comprobar("y en ese orden: A acaba antes de que B empiece",
          diario.index(("acaba", "A")) < diario.index(("empieza", "B")), diario)
ficha_b = video_b.estado(tb)
comprobar("B ya no dice que esta en cola", not ficha_b["en_cola"], ficha_b)
comprobar("y su reloj empezo al empezar, no al pedirlo", ficha_b["segundos"] < 0.4,
          ficha_b["segundos"])
puerta_b.set()
esperar_estado(video_b, tb, ("listo",))

print("\n== los ligeros no esperan ==")
diario.clear()
puerta_p, puerta_l = threading.Event(), threading.Event()
tp = video_a.lanzar("render", pesado, "P", puerta_p, cola=True)
esperar_estado(video_a, tp, ("ejecutando",))
time.sleep(0.1)
tl = video_b.lanzar("guion", pesado, "L", puerta_l)          # sin cola
time.sleep(0.3)
comprobar("un trabajo ligero empieza aunque haya un pesado corriendo",
          ("empieza", "L") in diario, diario)
puerta_l.set()
puerta_p.set()
esperar_estado(video_a, tp, ("listo",))
esperar_estado(video_b, tl, ("listo",))

print("\n== el turno se suelta aunque el trabajo reviente ==")
diario.clear()
tr = video_a.lanzar("render", revienta, cola=True)
esperar_estado(video_a, tr, ("error",))
puerta_d = threading.Event()
td = video_b.lanzar("imagenes", pesado, "D", puerta_d, cola=True)
esperar_estado(video_b, td, ("ejecutando",))
time.sleep(0.3)
comprobar("tras un error, el siguiente empieza", ("empieza", "D") in diario, diario)
puerta_d.set()
esperar_estado(video_b, td, ("listo",))
comprobar("y la fila queda vacia", TURNO.foto() == {"ahora": None, "fila": []},
          TURNO.foto())

print("\n== cancelar en la cola: no llega a empezar ==")
diario.clear()
puerta_1, puerta_2, puerta_3 = threading.Event(), threading.Event(), threading.Event()
t1 = video_a.lanzar("render", pesado, "1", puerta_1, cola=True)
esperar_estado(video_a, t1, ("ejecutando",))
time.sleep(0.1)
t2 = video_b.lanzar("imagenes", pesado, "2", puerta_2, cola=True)
time.sleep(0.1)
t3 = video_c.lanzar("imagenes", pesado, "3", puerta_3, cola=True)
time.sleep(0.3)
comprobar("el tercero tiene dos delante", video_c.estado(t3)["por_delante"] == 2,
          video_c.estado(t3))
video_b.cancelar(t2)
f2 = esperar_estado(video_b, t2, ("cancelado",))
comprobar("el cancelado en la cola queda cancelado", f2["estado"] == "cancelado", f2)
time.sleep(1.2)
comprobar("el tercero sube un puesto", video_c.estado(t3)["por_delante"] == 1,
          video_c.estado(t3))
puerta_1.set()
esperar_estado(video_a, t1, ("listo",))
esperar_estado(video_c, t3, ("ejecutando",))
time.sleep(0.2)
comprobar("el cancelado no llego a empezar", ("empieza", "2") not in diario, diario)
comprobar("y el tercero si", ("empieza", "3") in diario, diario)
puerta_3.set()
esperar_estado(video_c, t3, ("listo",))

print("\n== cancelar el que corre suelta el turno ==")
diario.clear()
puerta_x, puerta_y = threading.Event(), threading.Event()
tx = video_a.lanzar("render", pesado, "X", puerta_x, cola=True)
esperar_estado(video_a, tx, ("ejecutando",))
time.sleep(0.1)
ty = video_b.lanzar("imagenes", pesado, "Y", puerta_y, cola=True)
time.sleep(0.2)
video_a.cancelar(tx)
esperar_estado(video_a, tx, ("cancelado",))
esperar_estado(video_b, ty, ("ejecutando",))
time.sleep(0.3)
comprobar("al cancelar el que corre, empieza el siguiente", ("empieza", "Y") in diario,
          diario)
puerta_y.set()
esperar_estado(video_b, ty, ("listo",))
comprobar("la fila acaba vacia", TURNO.foto() == {"ahora": None, "fila": []},
          TURNO.foto())

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("COLA OK: todas las comprobaciones pasan")
