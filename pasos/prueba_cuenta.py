"""
El estudio de OTRA cuenta (ESTUDIO_CUENTA): arranca app.py de verdad en un
puerto libre, con datos temporales, y comprueba:

  1. lo de la instalacion (claves, tarifas, saldo, copias, ajustes del CLI)
     contesta 403 y no se toca;
  2. /api/cuenta dice de quien es, su tope y su gasto de ESTE mes;
  3. al llegar al tope, lo que gasta dinero contesta 402 (y lo gratis no);
  4. el tope se lee en cada peticion: subirlo deja seguir sin reiniciar.
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPORAL = tempfile.mkdtemp(prefix="prueba_cuenta_")
fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


def libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


D = os.path.join(TEMPORAL, "datos")
os.makedirs(os.path.join(D, "proyectos"))
os.makedirs(os.path.join(D, "secretos"))
FICHA = os.path.join(TEMPORAL, "ana.json")


def tope(usd):
    with open(FICHA, "w", encoding="utf-8") as fh:
        json.dump({"usuario": "ana", "tope_mes_usd": usd}, fh)


tope(1)
mes = time.strftime("%Y-%m")
with open(os.path.join(D, "coste_global.jsonl"), "w", encoding="utf-8") as fh:
    fh.write(json.dumps({"usd": 1.25, "momento": f"{mes}-01T10:00:00"}) + "\n")
    fh.write(json.dumps({"usd": 50, "momento": "2020-01-01T00:00:00"}) + "\n")

puerto = libre()
entorno = dict(os.environ, ESTUDIO_PROYECTOS=os.path.join(D, "proyectos"), ESTUDIO_PRESETS=os.path.join(D, "presets.json"),
               ESTUDIO_SECRETOS=os.path.join(D, "secretos"), ESTUDIO_ENV=os.path.join(D, "secretos", ".env"),
               ESTUDIO_COSTE_GLOBAL=os.path.join(D, "coste_global.jsonl"), ESTUDIO_RECETAS=os.path.join(D, "recetas.json"),
               ESTUDIO_AJUSTES=os.path.join(D, "ajustes.json"), ESTUDIO_ESTADISTICAS=os.path.join(D, "estadisticas.json"),
               ESTUDIO_BITACORA_GLOBAL=os.path.join(D, "bitacora.jsonl"), ESTUDIO_BANCO_PRESETS=os.path.join(D, "bp"),
               ESTUDIO_CUENTA="ana", ESTUDIO_CUENTA_FICHA=FICHA, ESTUDIO_COPIAS_APAGADAS="1",
               ESTUDIO_API=f"http://127.0.0.1:{puerto}", ESTUDIO_SIMULAR="1")
proceso = subprocess.Popen([sys.executable, os.path.join(RAIZ, "app.py"), "--puerto", str(puerto), "--host", "127.0.0.1"],
                           env=entorno, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=RAIZ)
B = f"http://127.0.0.1:{puerto}"
try:
    for _ in range(80):
        try:
            requests.get(B + "/api/cuenta", timeout=2)
            break
        except requests.RequestException:
            time.sleep(0.5)

    print("\n== lo de la instalacion ==")
    for metodo, ruta in (("PUT", "/api/claves"), ("POST", "/api/claves/probar"), ("PUT", "/api/coste/tarifas"),
                         ("PUT", "/api/saldo"), ("POST", "/api/copias"), ("PUT", "/api/ajustes")):
        r = requests.request(metodo, B + ruta, json={}, timeout=10)
        comprobar(f"{metodo} {ruta}: 403", r.status_code == 403, (r.status_code, r.text[:100]))
    comprobar("y no se ha escrito ninguna clave", not os.path.exists(os.path.join(D, "secretos", "claves.json")))

    print("\n== nada privado del admin ==")
    r = requests.post(B + "/api/proyectos", json={"nombre": "Video de admin@ejemplo.com"}, timeout=20)
    lista = requests.get(B + "/api/proyectos", timeout=20).text
    comprobar("ningun correo sale del estudio de una cuenta (se borran de las respuestas)",
              r.status_code in (200, 201) and "admin@ejemplo.com" not in lista and "Video de" in lista, (r.status_code, lista[:200]))
    saldo = requests.get(B + "/api/saldo", timeout=10).json()
    comprobar("ni el saldo de los proveedores", saldo == {"cuentas": {}, "bajos": []}, saldo)
    asistente = requests.get(B + "/api/asistente", timeout=20).text
    comprobar("ni la cuenta de Claude de Mind", "@" not in asistente, asistente[:200])

    print("\n== /api/cuenta ==")
    c = requests.get(B + "/api/cuenta", timeout=10).json()
    comprobar("de quien es, su tope y su gasto de ESTE mes",
              c == {"cuenta": "ana", "admin": False, "tope_mes_usd": 1, "gastado_mes": 1.25}, c)

    print("\n== el tope ==")
    r = requests.post(B + "/api/proyectos/un_video/generar", json={"tanda": "voz"}, timeout=10)
    comprobar("pasado el tope, generar contesta 402", r.status_code == 402 and r.json().get("tope"), (r.status_code, r.text[:200]))
    r = requests.post(B + "/api/presets-light", json={}, timeout=10)
    comprobar("crear un estilo (dibuja) tambien", r.status_code == 402, r.status_code)
    r = requests.post(B + "/api/presets-light/x/ideas", json={}, timeout=10)
    comprobar("lo gratis (ideas) no se para por el tope", r.status_code != 402, r.status_code)
    tope(10)
    r = requests.post(B + "/api/proyectos/un_video/generar", json={"tanda": "voz"}, timeout=10)
    comprobar("subir el tope deja seguir al momento (ya no es 402)", r.status_code != 402, (r.status_code, r.text[:120]))
    tope(None)
    comprobar("sin tope, sin limite", requests.post(B + "/api/proyectos/un_video/generar", json={"tanda": "voz"},
                                                    timeout=10).status_code != 402)
finally:
    proceso.terminate()
    try:
        proceso.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proceso.kill()
    shutil.rmtree(TEMPORAL, ignore_errors=True)

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("CUENTA OK: todas las comprobaciones pasan")
