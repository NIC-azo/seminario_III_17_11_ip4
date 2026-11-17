import cv2
import requests
import time
import os
import winsound
import threading
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "fleetguard_token_secreto_2026")
VEHICULO_ID = os.getenv("VEHICULO_ID", "BUS-04")
HEADERS = {"X-API-Key": API_KEY}

# Variables globales para compartir datos entre la cámara y la red
datos_api = {"ojos_cerrados": False, "ear": 0.0, "clase_conducta": "desconocido", "confianza_yolo": 0.0}
ancho_banda_kbps = 0.0
peticion_en_curso = False

def tarea_analisis_red(imagen_bytes, tamano_bits):
    """Hilo secundario que envía el frame al servidor sin congelar la cámara"""
    global datos_api, ancho_banda_kbps, peticion_en_curso
    t0 = time.time()
    try:
        files = {"file": ("frame.jpg", imagen_bytes, "image/jpeg")}
        res = requests.post(f"{SERVER_URL}/flota/analizar", headers=HEADERS, files=files, timeout=2)
        t1 = time.time()
        
        tiempo_peticion_ms = (t1 - t0) * 1000
        if tiempo_peticion_ms > 0:
            ancho_banda_kbps = tamano_bits / tiempo_peticion_ms
            
        datos_api = res.json()
    except requests.exceptions.RequestException:
        pass # Si hay lag en la red, ignoramos para no saturar la consola
    finally:
        peticion_en_curso = False

def main():
    global peticion_en_curso, datos_api, ancho_banda_kbps
    cap = cv2.VideoCapture(0)
    
    inicio_ojos_cerrados = None
    tiempo_umbral_microsueno = 1.5

    print(f"Iniciando Nodo Edge Optimizado [{VEHICULO_ID}] - Presiona 'q' para salir.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # 1. Compresión Dinámica
        frame_resized = cv2.resize(frame, (640, 480))
        _, buffer = cv2.imencode('.jpg', frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 70])
        imagen_bytes = buffer.tobytes()
        tamano_bits = len(imagen_bytes) * 8

        # 2. Enviar a servidor SOLO si el hilo anterior ya terminó (Evita encolar peticiones)
        if not peticion_en_curso:
            peticion_en_curso = True
            hilo = threading.Thread(target=tarea_analisis_red, args=(imagen_bytes, tamano_bits))
            hilo.daemon = True
            hilo.start()

        # 3. Leer los últimos resultados procesados por el hilo secundario
        ojos_cerrados = datos_api.get("ojos_cerrados", False)
        clase_conducta = datos_api.get("clase_conducta", "desconocido")
        confianza_yolo = datos_api.get("confianza_yolo", 0.0)
        
        estado_pantalla = "CONDUCCION NORMAL"
        color_texto = (0, 255, 0)
        alerta_disparada = False
        evento_tipo = ""

        # Lógica de Microsueño
        if ojos_cerrados:
            if inicio_ojos_cerrados is None:
                inicio_ojos_cerrados = time.time()
            else:
                duracion = time.time() - inicio_ojos_cerrados
                if duracion >= tiempo_umbral_microsueno:
                    estado_pantalla = f"ALERTA: MICROSUENO ({round(duracion, 1)}s)"
                    color_texto = (0, 0, 255)
                    alerta_disparada = True
                    evento_tipo = "MICROSUEÑO_DETECTADO"
        else:
            inicio_ojos_cerrados = None 

        # Lógica de Custom Vision
        if clase_conducta in ["uso_celular", "distraccion_lateral"] and confianza_yolo > 0.70:
             estado_pantalla = f"ALERTA: {clase_conducta.upper()}"
             color_texto = (0, 165, 255)
             alerta_disparada = True
             evento_tipo = clase_conducta.upper()

        # Disparar Alerta Crítica (Bloqueante intencional por 1 segundo para guardar la foto)
        if alerta_disparada:
            winsound.Beep(1000, 500)
            dur = time.time() - inicio_ojos_cerrados if inicio_ojos_cerrados else 0.0
            data_alerta = {
                "vehiculo_id": VEHICULO_ID,
                "evento": evento_tipo,
                "duracion_seg": round(dur, 2),
                "confianza_custom": confianza_yolo
            }
            files_alerta = {"file": ("evidencia.jpg", imagen_bytes, "image/jpeg")}
            try:
                requests.post(f"{SERVER_URL}/flota/alerta", headers=HEADERS, data=data_alerta, files=files_alerta)
            except:
                pass
            time.sleep(1) # Pausa para no saturar la BD local con la misma infracción

        # 4. Renderizar UI sin interrupciones (a 30 FPS)
        cv2.putText(frame, f"Estado: {estado_pantalla}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_texto, 2)
        cv2.putText(frame, f"EAR: {datos_api.get('ear', 0.0)}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"Red: {round(ancho_banda_kbps, 1)} Kbps", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        cv2.putText(frame, f"YOLO: {clase_conducta} ({round(confianza_yolo*100)}%)", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        cv2.imshow("FleetGuard DMS - Cabina Edge", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()