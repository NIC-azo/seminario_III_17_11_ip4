import cv2
import requests
import time
import os
import winsound
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "fleetguard_token_secreto_2026")
VEHICULO_ID = os.getenv("VEHICULO_ID", "BUS-04")

HEADERS = {"X-API-Key": API_KEY}

def main():
    cap = cv2.VideoCapture(0)
    
    # Variables para la lógica de ventana temporal
    inicio_ojos_cerrados = None
    tiempo_umbral_microsueno = 1.5
    
    # Variables para métricas
    bandwidth_kbps = 0.0

    print(f"Iniciando Nodo Edge [{VEHICULO_ID}] - Presiona 'q' para salir.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        # 1. Compresión Dinámica a JPEG (Optimización de red)
        # Reducimos resolución para enviar por red más rápido y bajamos calidad al 70%
        frame_resized = cv2.resize(frame, (640, 480))
        _, buffer = cv2.imencode('.jpg', frame_resized, [cv2.IMWRITE_JPEG_QUALITY, 70])
        imagen_bytes = buffer.tobytes()

        # Calcular tamaño del payload en bits
        tamano_bits = len(imagen_bytes) * 8

        # 2. Transmisión y medición de Ancho de Banda
        t0 = time.time()
        try:
            # Enviar al servidor para inferencia híbrida
            files = {"file": ("frame.jpg", imagen_bytes, "image/jpeg")}
            res = requests.post(f"{SERVER_URL}/flota/analizar", headers=HEADERS, files=files, timeout=2)
            t1 = time.time()
            
            # Ancho de banda: (bits) / (tiempo_en_milisegundos) = Kbps
            tiempo_peticion_ms = (t1 - t0) * 1000
            if tiempo_peticion_ms > 0:
                bandwidth_kbps = tamano_bits / tiempo_peticion_ms
            
            datos = res.json()
            
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión: {e}")
            datos = {"ojos_cerrados": False, "ear": 0, "clase_conducta": "desconocido", "confianza_yolo": 0}

        # 3. Lógica Temporal (Anti-Falsos Positivos)
        ojos_cerrados = datos.get("ojos_cerrados", False)
        clase_conducta = datos.get("clase_conducta", "desconocido")
        confianza_yolo = datos.get("confianza_yolo", 0.0)
        
        estado_pantalla = "CONDUCCION NORMAL"
        color_texto = (0, 255, 0) # Verde
        alerta_disparada = False
        evento_tipo = ""

        # Evaluación de Microsueño
        if ojos_cerrados:
            if inicio_ojos_cerrados is None:
                inicio_ojos_cerrados = time.time()
            else:
                duracion = time.time() - inicio_ojos_cerrados
                if duracion >= tiempo_umbral_microsueno:
                    estado_pantalla = f"ALERTA: MICROSUEÑO ({round(duracion, 1)}s)"
                    color_texto = (0, 0, 255) # Rojo
                    alerta_disparada = True
                    evento_tipo = "MICROSUEÑO_DETECTADO"
        else:
            inicio_ojos_cerrados = None # Reiniciar contador (Parpadeo normal o despertó)

        # Evaluación de Conductas Custom Vision (Ej. Uso de celular)
        if clase_conducta in ["uso_celular", "distraccion_lateral"] and confianza_yolo > 0.70:
             estado_pantalla = f"ALERTA: {clase_conducta.upper()}"
             color_texto = (0, 165, 255) # Naranja
             alerta_disparada = True
             evento_tipo = clase_conducta.upper()

        # 4. Disparar Alarma y Guardar Evidencia
        if alerta_disparada:
            # Alarma sonora (Frecuencia 1000Hz, Duración 500ms)
            winsound.Beep(1000, 500)
            
            # Enviar evidencia al servidor
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
                
            # Pequeña pausa para no saturar la base de datos con un mismo evento continuo
            time.sleep(1) 

        # 5. Renderizar Interfaz de Cabina
        ear_val = datos.get("ear", 0.0)
        cv2.putText(frame, f"Estado: {estado_pantalla}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_texto, 2)
        cv2.putText(frame, f"EAR (Ojos): {ear_val}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"Red: {round(bandwidth_kbps, 1)} Kbps", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        cv2.putText(frame, f"Conducta (YOLO): {clase_conducta} ({round(confianza_yolo*100)}%)", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        cv2.imshow("FleetGuard DMS - Cabina Edge", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()