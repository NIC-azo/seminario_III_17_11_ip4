import cv2
import mediapipe as mp
import math
import numpy as np
from ultralytics import YOLO

# Inicializar MediaPipe Face Mesh
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# Inicializar modelo YOLO entrenado en Colab
try:
    model_yolo = YOLO('best.pt')
except Exception as e:
    print(f"Advertencia: No se pudo cargar best.pt. Asegúrate de que esté en la carpeta server/. Error: {e}")
    model_yolo = None

# Índices de los puntos clave (landmarks) de los ojos en MediaPipe
RIGHT_EYE = [33, 160, 158, 133, 153, 144]
LEFT_EYE = [362, 385, 387, 263, 373, 380]

def calculate_ear(eye_points, landmarks, img_w, img_h):
    """Calcula el Eye Aspect Ratio (EAR) a partir de coordenadas 2D."""
    def get_pt(idx):
        lm = landmarks.landmark[idx]
        return np.array([lm.x * img_w, lm.y * img_h])
    
    # Coordenadas de los 6 puntos
    p0, p1, p2, p3, p4, p5 = [get_pt(i) for i in eye_points]
    
    # Distancias verticales
    v1 = np.linalg.norm(p1 - p5)
    v2 = np.linalg.norm(p2 - p4)
    # Distancia horizontal
    h = np.linalg.norm(p0 - p3)
    
    return (v1 + v2) / (2.0 * h)

def analizar_frame_sincrono(image_bytes: bytes):
    """
    Función síncrona que procesa los bytes de la imagen.
    Devuelve un diccionario con el EAR y la clase detectada.
    """
    # Decodificar imagen
    np_arr = np.frombuffer(image_bytes, np.uint8)
    frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if frame is None:
        return {"error": "Imagen no válida"}

    img_h, img_w, _ = frame.shape
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    
    # 1. Analizar EAR con MediaPipe
    results_mp = face_mesh.process(frame_rgb)
    ear_promedio = 0.0
    ojos_cerrados = False
    rostro_detectado = False

    if results_mp.multi_face_landmarks:
        rostro_detectado = True
        landmarks = results_mp.multi_face_landmarks[0]
        
        ear_right = calculate_ear(RIGHT_EYE, landmarks, img_w, img_h)
        ear_left = calculate_ear(LEFT_EYE, landmarks, img_w, img_h)
        ear_promedio = (ear_right + ear_left) / 2.0
        
        # Umbral estándar (si baja de 0.20, se considera cerrado)
        if ear_promedio < 0.20:
            ojos_cerrados = True

    # 2. Analizar Conducta con YOLOv8 (Custom Vision)
    clase_detectada = "desconocido"
    confianza = 0.0
    
    if model_yolo:
        resultados_yolo = model_yolo.predict(frame, verbose=False)
        if len(resultados_yolo) > 0:
            probs = resultados_yolo[0].probs
            # Obtener el índice con mayor probabilidad
            top1_idx = probs.top1
            confianza = float(probs.top1conf)
            clase_detectada = model_yolo.names[top1_idx]

    return {
        "rostro_detectado": rostro_detectado,
        "ear": round(ear_promedio, 3),
        "ojos_cerrados": ojos_cerrados,
        "clase_conducta": clase_detectada,
        "confianza_yolo": round(confianza, 3)
    }