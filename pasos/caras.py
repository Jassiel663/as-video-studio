"""
EL ENCUADRE QUE SIGUE LA CARA (clipping y shorts en vertical).

Un video apaisado pasado a vertical pierde dos tercios del cuadro. Recortar el
centro corta a quien no esta en el centro (los podcasts de dos personas), y el
fondo desenfocado deja la cara pequena. Esto mira, en cada trozo del clip,
DONDE ESTA LA CARA de quien sale y centra el recorte vertical en ella; si en el
trozo siguiente sale otra persona, el «plano» salta a ella, como haria un
realizador. Sin cara, ese trozo va entero sobre su fondo desenfocado.

Detector: YuNet (OpenCV), un modelo de 230 KB que se baja una vez a la carpeta
de modelos. Si no se puede bajar, el clasificador Haar que trae OpenCV.
"""
import os
import urllib.request

try:
    from . import medios, presets_canal
except ImportError:  # ejecutado con la carpeta pasos directamente en sys.path
    import medios
    import presets_canal

MODELOS = os.environ.get("ESTUDIO_MODELOS") or os.path.join(
    os.path.dirname(os.path.abspath(presets_canal.FICHERO)), "modelos")
YUNET = "face_detection_yunet_2023mar.onnx"
URL_YUNET = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")
MUESTRAS = 4          # fotogramas mirados por trozo
ANCHO_ANALISIS = 640  # se analiza en pequeno: es rapido y basta
_DETECTOR = {}


def _detector():
    import cv2
    if "d" in _DETECTOR:
        return _DETECTOR["d"]
    ruta = os.path.join(MODELOS, YUNET)
    if not os.path.exists(ruta):
        try:
            os.makedirs(MODELOS, exist_ok=True)
            urllib.request.urlretrieve(URL_YUNET, ruta + ".parcial")
            os.replace(ruta + ".parcial", ruta)
        except Exception:                                   # noqa: BLE001
            pass
    if os.path.exists(ruta):
        _DETECTOR["d"] = ("yunet", cv2.FaceDetectorYN.create(ruta, "", (320, 320), 0.7, 0.3, 50))
    else:
        _DETECTOR["d"] = ("haar", cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades,
                                                                     "haarcascade_frontalface_default.xml")))
    return _DETECTOR["d"]


def caras_en(imagen):
    """Las caras de una imagen BGR. -> [(x, y, ancho, alto)] en pixeles"""
    import cv2
    tipo, det = _detector()
    if tipo == "yunet":
        alto, ancho = imagen.shape[:2]
        det.setInputSize((ancho, alto))
        _, caras = det.detect(imagen)
        return [tuple(int(v) for v in c[:4]) for c in (caras if caras is not None else [])]
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    return [tuple(int(v) for v in c) for c in det.detectMultiScale(gris, 1.15, 6, minSize=(40, 40))]


def centro_de(original, desde, hasta, captura=None):
    """Donde esta (en horizontal, 0-1) la cara principal entre `desde` y `hasta`. -> float o None"""
    import cv2
    propia = captura is None
    captura = captura or cv2.VideoCapture(original)
    votos = []
    try:
        for k in range(MUESTRAS):
            t = desde + (hasta - desde) * (k + 0.5) / MUESTRAS
            captura.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, imagen = captura.read()
            if not ok or imagen is None:
                continue
            alto, ancho = imagen.shape[:2]
            escala = ANCHO_ANALISIS / float(ancho)
            if escala < 1:
                imagen = cv2.resize(imagen, (ANCHO_ANALISIS, int(alto * escala)))
            caras = caras_en(imagen)
            if not caras:
                continue
            # la principal: la mas grande (la de quien esta hablando a camara)
            x, _, w, _ = max(caras, key=lambda c: c[2] * c[3])
            votos.append((x + w / 2.0) / imagen.shape[1])
    finally:
        if propia:
            captura.release()
    if len(votos) < max(1, MUESTRAS // 2):
        return None                                         # en mas de la mitad no hay cara: no fiarse
    votos.sort()
    return round(votos[len(votos) // 2], 3)                 # la mediana: un fotograma raro no la mueve


def centros(original, tramos, quieto=0.08):
    """El centro de cara de cada trozo. Si cambia muy poco del anterior, se
    queda quieto (sin temblores de camara). -> [float o None]"""
    import cv2
    captura = cv2.VideoCapture(original)
    salida = []
    try:
        for a, b in tramos:
            c = centro_de(original, a, b, captura)
            if c is not None and salida and salida[-1] is not None and abs(c - salida[-1]) < quieto:
                c = salida[-1]
            salida.append(c)
    finally:
        captura.release()
    return salida


def filtro_recorte(centro, ancho_fuente, alto_fuente, ancho=1080, alto=1920):
    """El trozo de filtro ffmpeg que recorta en vertical centrado en la cara."""
    corte_w = min(ancho_fuente, int(round(alto_fuente * ancho / alto / 2)) * 2)
    x = int(round(centro * ancho_fuente - corte_w / 2))
    x = max(0, min(ancho_fuente - corte_w, x))
    return f"crop={corte_w}:{alto_fuente}:{x}:0,scale={ancho}:{alto}"
