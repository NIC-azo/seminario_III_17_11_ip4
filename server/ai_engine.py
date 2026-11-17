from ultralytics import YOLO
import cv2
import numpy as np
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(BASE_DIR, 'best.pt')

# Cargar el modelo en memoria una sola vez
model = YOLO(MODEL_PATH)

def evaluar_conducta_yolo(image_bytes):
    """
    Recibe la imagen decodificada y retorna la clase detectada y su nivel de confianza.
    Soporta tanto modelos de Clasificación (probs) como de Detección (boxes).
    """
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    if frame is None:
        return "sin_conductor", 1.0, None

    # Inferencia acelerada (tamaño 320 para mínima latencia)
    results = model.predict(source=frame, imgsz=320, verbose=False)
    
    if len(results) > 0:
        res = results[0]
        # Modelo de Clasificación (probs)
        if hasattr(res, 'probs') and res.probs is not None:
            clase_id = int(res.probs.top1)
            confianza = float(res.probs.top1conf.item())
            clase_nombre = model.names[clase_id]
            
            # Si no es conduccion_segura (clase_id 0) y supera umbral moderado
            if clase_id != 0 and confianza >= 0.50:
                return clase_nombre, confianza, frame
            elif clase_id == 0:
                return "conduccion_segura", confianza, frame
            else:
                return "conduccion_segura", round(1.0 - confianza, 2), frame

        # Modelo de Detección (boxes) como fallback
        elif hasattr(res, 'boxes') and res.boxes is not None and len(res.boxes) > 0:
            clase_id = int(res.boxes.cls[0].item())
            confianza = float(res.boxes.conf[0].item())
            clase_nombre = model.names[clase_id]
            if clase_id != 0 and confianza >= 0.50:
                return clase_nombre, confianza, frame

    return "conduccion_segura", 1.0, frame
