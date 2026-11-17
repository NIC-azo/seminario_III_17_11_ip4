import cv2
import requests
import time
import os
import winsound
import threading
from dotenv import load_dotenv

load_dotenv()
SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "fleetguard_token_secreto_2026")
VEHICULO_ID = os.getenv("VEHICULO_ID", "BUS-04")
HEADERS = {"X-API-Key": API_KEY}

datos_api = {"ojos_cerrados": False, "ear": 0.0, "clase_conducta": "desconocido", "confianza_yolo": 0.0}
ancho_banda_kbps = 0.0
peticion_en_curso = False

class CamaraEdge:
    """Hilo dedicado EXCLUSIVAMENTE a vaciar el buffer de la webcam para eliminar el lag"""
    def __init__(self, src=0):
        # Forzar DirectShow (CAP_DSHOW) elimina el 90% del lag en Windows 11
        self.cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.ret, self.frame = self.cap.read()
        self.running = True
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        # Drenaje continuo en segundo plano
        while self.running:
            self.ret, self.frame = self.cap.read()

    def read(self):
        # Retorna siempre el fotograma más reciente
        return self.ret, self.frame.copy() if self.ret else None

    def release(self):
        self.running = False
        self.thread.join()
        self.cap.release()

def tarea_analisis_red(imagen_bytes, tamano_bits):
    """Hilo terciario para la telemetría HTTP"""
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
        pass 
    finally:
        peticion_en_curso = False

def main():
    global peticion_en_curso, datos_api, ancho_banda_kbps
    
    # Inicializar el hilo de la cámara
    camara = CamaraEdge(0)
    
    inicio_ojos_cerrados = None
    tiempo_umbral_microsueno = 1.5
    tiempo_ultima_peticion = 0
    FPS_RED = 4  # Limitador de peticiones al servidor Docker

    print(f"Iniciando Nodo Edge Avanzado [{VEHICULO_ID}] - Presiona 'q' para salir.")

    while True:
        ret, frame = camara.read()
        if not ret or frame is None:
            continue
            
        tiempo_actual = time.time()
        
        # Enviar telemetría solo 4 veces por segundo
        if not peticion_en_curso and (tiempo_actual - tiempo_ultima_peticion) >= (1.0 / FPS_RED):
            tiempo_ultima_peticion = tiempo_actual
            peticion_en_curso = True
            
            # Redimensionar SOLO la imagen que viaja por red (Optimiza ancho de banda y carga del server)
            frame_red = cv2.resize(frame, (640, 480))
            _, buffer = cv2.imencode('.jpg', frame_red, [cv2.IMWRITE_JPEG_QUALITY, 70])
            imagen_bytes = buffer.tobytes()
            
            hilo = threading.Thread(target=tarea_analisis_red, args=(imagen_bytes, len(imagen_bytes) * 8), daemon=True)
            hilo.start()

        # Extraer variables
        ojos_cerrados = datos_api.get("ojos_cerrados", False)
        clase_conducta = datos_api.get("clase_conducta", "desconocido")
        confianza_yolo = datos_api.get("confianza_yolo", 0.0)
        
        estado_pantalla = "CONDUCCION NORMAL"
        color_texto = (0, 255, 0)
        alerta_disparada = False
        evento_tipo = ""

        # Evaluación Temporal (Microsueño)
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

        # Evaluación Custom Vision (Conductas)
        if clase_conducta in ["uso_celular", "distraccion_lateral"] and confianza_yolo > 0.70:
             estado_pantalla = f"ALERTA: {clase_conducta.upper()}"
             color_texto = (0, 165, 255)
             alerta_disparada = True
             evento_tipo = clase_conducta.upper()

        # Acción Crítica
        if alerta_disparada:
            winsound.Beep(1000, 500)
            dur = time.time() - inicio_ojos_cerrados if inicio_ojos_cerrados else 0.0
            data_alerta = {
                "vehiculo_id": VEHICULO_ID,
                "evento": evento_tipo,
                "duracion_seg": round(dur, 2),
                "confianza_custom": confianza_yolo
            }
            # Guardamos la evidencia usando el frame ORIGINAL en alta resolución
            _, buffer_alerta = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            files_alerta = {"file": ("evidencia.jpg", buffer_alerta.tobytes(), "image/jpeg")}
            
            try:
                requests.post(f"{SERVER_URL}/flota/alerta", headers=HEADERS, data=data_alerta, files=files_alerta)
            except:
                pass
            time.sleep(1)

        # Renderizado fluido UI
        cv2.putText(frame, f"Estado: {estado_pantalla}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_texto, 2)
        cv2.putText(frame, f"EAR: {datos_api.get('ear', 0.0)}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(frame, f"Red: {round(ancho_banda_kbps, 1)} Kbps", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 1)
        cv2.putText(frame, f"YOLO: {clase_conducta} ({round(confianza_yolo*100)}%)", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        cv2.imshow("FleetGuard DMS - Cabina Edge", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    camara.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()