"""
Pruebas del short trabajado (pasos/trabajado.py) que no necesitan video:

  1. SIN CLAUDE se quitan los silencios y se respeta la duracion maxima.
  2. LOS TRAMOS no cortan palabras ni se solapan.
  3. LAS PALABRAS pasan al tiempo nuevo (tras cortar y empalmar).
  4. LOS SUBTITULOS: bloques de 3, la palabra que suena en el color de acento.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import trabajado  # noqa: E402

fallos = []


def comprobar(titulo, condicion, detalle=""):
    if condicion:
        print(f"  ok   {titulo}")
    else:
        print(f"  FALLA {titulo}" + (f"   -> {detalle}" if detalle else ""))
        fallos.append(titulo)


P = [{"p": "hola", "i": 0.0, "f": 0.4}, {"p": "que", "i": 0.5, "f": 0.7},
     {"p": "tal", "i": 0.75, "f": 1.1}, {"p": "silencio", "i": 4.0, "f": 4.6},
     {"p": "largo", "i": 4.7, "f": 5.2}, {"p": "fin", "i": 9.0, "f": 9.5}]

tramos = trabajado.tramos_por_silencio(P, 30)
comprobar("sin Claude: un tramo por bloque de habla", len(tramos) == 3, tramos)
comprobar("y respeta el maximo", sum(b - a for a, b in trabajado.tramos_por_silencio(P, 1.5)) <= 1.8)

ajustados = trabajado._ajustar([[0.2, 0.6], [0.5, 1.0]], P, 30)
comprobar("no corta palabras (se ensancha a la palabra)", ajustados[0][0] <= 0.0 + 1e-6, ajustados)
comprobar("y no se solapan", all(ajustados[i][1] <= ajustados[i + 1][0] + 1e-6
                                 for i in range(len(ajustados) - 1)), ajustados)

nuevas = trabajado._remapear(P, [[4.0, 5.3], [0.0, 1.2]])
comprobar("las palabras pasan al tiempo nuevo, en el orden de los tramos",
          [w["p"] for w in nuevas] == ["silencio", "largo", "hola", "que", "tal"]
          and nuevas[0]["i"] == 0.0 and abs(nuevas[2]["i"] - 1.3) < 0.01, nuevas)

ass = os.path.join(tempfile.mkdtemp(), "s.ass")
trabajado.subtitulos_ass(nuevas, {"texto": "#ffffff", "acento": "#a78bfa", "sombra": "#000000"}, ass)
texto = open(ass, encoding="utf-8").read()
comprobar("subtitulos en vertical 1080x1920", "PlayResX: 1080" in texto and "PlayResY: 1920" in texto)
comprobar("una linea por palabra que suena", texto.count("Dialogue:") == len(nuevas))
comprobar("la palabra que suena en el color de acento (BGR de ASS)", r"{\c&H00FA8BA7&}SILENCIO" in texto, texto[-300:])


def _seg(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


# «se ven uno encima del otro»: nunca dos subtitulos vivos a la vez
largas = [{"p": f"palabra{k}" + ("." if k % 4 == 0 else ""), "i": k * 0.35, "f": k * 0.35 + 0.33} for k in range(1, 30)]
trabajado.subtitulos_ass(largas, {"texto": "#ffffff", "acento": "#a78bfa", "sombra": "#000000"}, ass)
textos = open(ass, encoding="utf-8").read()
dialogos = [linea for linea in textos.splitlines() if linea.startswith("Dialogue:")]
tiempos = [(_seg(linea.split(",")[1]), _seg(linea.split(",")[2])) for linea in dialogos]
comprobar("ningun subtitulo pisa al siguiente (no se apilan)",
          all(b <= c + 1e-6 for (_, b), (c, _d) in zip(tiempos, tiempos[1:])), tiempos[:6])
comprobar("cada bloque entra con transicion (fundido y crece)", r"\fad(110,0)" in textos and r"\fad(0,90)" in textos)
visibles = [re.sub(r"\{[^}]*\}", "", linea.split(",,0,0,0,,", 1)[-1]) for linea in dialogos]
comprobar("ningun bloque pasa de 18 caracteres (no se sale por los lados)", all(len(v) <= 18 for v in visibles), visibles[:4])

print()
if fallos:
    print(f"FALLARON {len(fallos)} comprobaciones:")
    for f in fallos:
        print(f"  - {f}")
    raise SystemExit(1)
print("TRABAJADO OK: todas las comprobaciones pasan")
