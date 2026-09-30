"""
Pruebas del saldo de las cuentas (`coste.saldo` y `coste.fijar_saldo`).

Lo que se protege:

  1. EL SALDO ES LO APUNTADO MENOS LO GASTADO DESDE ENTONCES, por cuenta: lo
     gastado antes de apuntar ya estaba descontado, y lo de otra cuenta no
     cuenta.
  2. EL AVISO SALTA AL BAJAR DEL MINIMO, y solo en esa cuenta.
  3. VIVE FUERA DEL CODIGO: junto a tarifas.json, que en el servidor esta en
     datos/ y sobrevive a las actualizaciones.
  4. UN VALOR IMPOSIBLE SE RECHAZA al apuntarlo, no se guarda.
"""
import json
import os
import shutil
import sys
import tempfile
import time

TEMPORAL = tempfile.mkdtemp(prefix="prueba_saldo_")
os.environ["ESTUDIO_TARIFAS"] = os.path.join(TEMPORAL, "datos", "tarifas.json")
os.environ["ESTUDIO_COSTE_GLOBAL"] = os.path.join(TEMPORAL, "datos", "coste_global.jsonl")
os.environ.pop("ESTUDIO_SALDO", None)
os.makedirs(os.path.join(TEMPORAL, "datos"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nucleo import coste as COSTE  # noqa: E402
from nucleo.proyecto import ahora  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def igual(titulo, obtenido, esperado):
    comprobar(titulo, obtenido == esperado, f"esperaba {esperado!r}, salio {obtenido!r}")


def gasto(proveedor, usd, momento=None):
    with open(COSTE.RUTA_GLOBAL, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"proveedor": proveedor, "usd": usd,
                             "momento": momento or ahora()}) + "\n")


print("\n== donde vive ==")
igual("junto a tarifas.json (datos/), no junto al codigo",
      os.path.dirname(COSTE.RUTA_SALDO), os.path.join(TEMPORAL, "datos"))

print("\n== sin apuntar nada ==")
vacio = COSTE.saldo()
comprobar("las cuatro cuentas salen, sin apuntar",
          sorted(vacio["cuentas"]) == ["fal", "openai", "tts", "veo"]
          and not any(c["apuntado"] for c in vacio["cuentas"].values()), vacio)
igual("y no hay ninguna baja", vacio["bajos"], [])
comprobar("cada una con su enlace de recarga",
          all(c["recarga"].startswith("https://") for c in vacio["cuentas"].values()))

print("\n== lo apuntado menos lo gastado DESDE ENTONCES ==")
gasto("openai", 3.0, "2020-01-01T00:00:00")     # antes de apuntar: no cuenta
COSTE.fijar_saldo("openai", 20, minimo=5)
time.sleep(1.1)                                  # los momentos van por segundos
gasto("openai", 4.5)
gasto("openai", 2.25)
gasto("veo", 9.0)                                # otra cuenta: no cuenta aqui
openai = COSTE.saldo()["cuentas"]["openai"]
igual("gastado: solo lo de despues y solo de OpenAI", openai["gastado"], 6.75)
igual("quedan 20 - 6,75", openai["restante"], 13.25)
comprobar("por encima del aviso, no esta baja", not openai["bajo"])

print("\n== el aviso ==")
gasto("openai", 9.0)
datos = COSTE.saldo()
comprobar("al bajar de 5 $ salta el aviso", datos["cuentas"]["openai"]["bajo"],
          datos["cuentas"]["openai"])
igual("y solo en esa cuenta", datos["bajos"], ["openai"])
comprobar("veo, sin apuntar, no avisa aunque haya gastado",
          not datos["cuentas"]["veo"]["apuntado"])

print("\n== recargar: se vuelve a apuntar y el reloj empieza de nuevo ==")
COSTE.fijar_saldo("openai", 50, minimo=5)
openai = COSTE.saldo()["cuentas"]["openai"]
igual("lo gastado antes de recargar ya no cuenta", openai["gastado"], 0.0)
igual("quedan los 50", openai["restante"], 50.0)
igual("y el aviso se apaga", COSTE.saldo()["bajos"], [])

print("\n== sin minimo no avisa nunca ==")
COSTE.fijar_saldo("veo", 1)
time.sleep(1.1)
gasto("veo", 3.0)
veo = COSTE.saldo()["cuentas"]["veo"]
igual("puede quedar en negativo (se gasto mas de lo apuntado)", veo["restante"], -2.0)
comprobar("pero sin minimo no hay aviso", not veo["bajo"])

print("\n== valores imposibles ==")
for titulo, args in (("una cuenta que no existe", ("claude_cli", 5)),
                     ("un importe negativo", ("openai", -1)),
                     ("un importe que no es numero", ("openai", "mucho")),
                     ("un aviso negativo", ("openai", 5, -2))):
    try:
        COSTE.fijar_saldo(*args)
        comprobar(f"rechaza {titulo}", False, "no levanto ValueError")
    except ValueError:
        comprobar(f"rechaza {titulo}", True)
igual("y lo guardado sigue como estaba", COSTE.saldo()["cuentas"]["openai"]["cargado"], 50.0)

print("\n== dejar de seguir una cuenta ==")
COSTE.fijar_saldo("openai", None)
comprobar("cargado None la quita", not COSTE.saldo()["cuentas"]["openai"]["apuntado"])

shutil.rmtree(TEMPORAL, ignore_errors=True)
print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("SALDO OK: todas las comprobaciones pasan")
