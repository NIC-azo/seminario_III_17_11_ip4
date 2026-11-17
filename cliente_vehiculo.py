"""
FleetGuard DMS - Nodo Vehículo (Cliente Edge en OpenCV)
Rol: Integrante B (Ingeniero Telemetría & Cliente Edge - Vehículo)

Funcionalidades:
1. Captura de video en tiempo real desde la webcam con OpenCV.
2. Detección facial y ocular con lógica de ventana temporal (>= 1.5s) anti-falsos positivos.
3. Envío autenticado por red (WebSocket) con encabezado X-API-Key y query param.
4. Medición de métricas de red en vivo (Kbps consumidos y FPS de cabina).
5. Interfaz de cabina HUD con alertas visuales y sonoras (winsound / beep).
6. Soporte multi-cliente para prueba de estrés y concurrencia.
"""

import cv2
import asyncio
import json
import base64
import time
import os
import sys
import platform
import argparse
import threading

# Intentar importar winsound en Windows para alertas sonoras
try:
    import winsound
    HAVE_WINSOUND = True
except ImportError:
    HAVE_WINSOUND = False

# Intentar importar websockets
try:
    import websockets
except ImportError:
    print("[ERROR] Por favor instala 'websockets': pip install websockets")
    sys.exit(1)


def sonar_alarma():
    """Emite pitido de advertencia sonora según el sistema operativo"""
    if HAVE_WINSOUND:
        try:
            winsound.Beep(1200, 250)
        except Exception:
            pass
    else:
        sys.stdout.write('\a')
        sys.stdout.flush()


class ClienteVehiculoEdge:
    def __init__(self, vehiculo_id="BUS-04", token="fleetguard_token_secreto_2026", host="localhost:8000"):
        self.vehiculo_id = vehiculo_id
        self.token = token
        self.host = host
        self.ws_url = f"ws://{host}/ws/flota/{vehiculo_id}?token={token}"
        
        # Estado de conexión
        self.websocket = None
        self.conectado = False
        self.error_auth = False
        
        # Lógica Temporal (Anti-Falsos Positivos)
        self.inicio_ojos_cerrados = 0
        self.UMBRAL_MICROSUEÑO_SEG = 1.5
        self.estado_alerta = "CONDUCCION_SEGURA"
        self.ultima_alerta_tiempo = 0
        
        # Telemetría
        self.bytes_enviados_seg = 0
        self.kbps_actual = 0.0
        self.fps_actual = 0.0
        self.ultimo_calculo_red = time.time()
        self.servidor_ia_evento = "NORMAL"
        self.servidor_ia_conf = 1.0

        # Cargar clasificadores OpenCV
        casc_path = cv2.data.haarcascades
        self.face_cascade = cv2.CascadeClassifier(os.path.join(casc_path, 'haarcascade_frontalface_default.xml'))
        self.eye_cascade = cv2.CascadeClassifier(os.path.join(casc_path, 'haarcascade_eye.xml'))
        
        # Cola de mensajes para WebSocket
        self.cola_envio = asyncio.Queue()

    async def conectar_websocket(self):
        """Mantiene la conexión WebSocket y gestiona la autenticación"""
        headers = [("X-API-Key", self.token)] if self.token else []
        print(f"[{self.vehiculo_id}] Conectando a {self.ws_url}...")
        
        try:
            async with websockets.connect(self.ws_url, extra_headers=headers) as ws:
                self.websocket = ws
                self.conectado = True
                self.error_auth = False
                print(f"[{self.vehiculo_id}] Autenticado y conectado exitosamente.")
                
                # Tareas concurrentes: Enviar telemetría y recibir respuestas de IA Cloud
                tarea_enviar = asyncio.create_task(self._bucle_envio())
                tarea_recibir = asyncio.create_task(self._bucle_recepcion())
                
                done, pending = await asyncio.wait(
                    [tarea_enviar, tarea_recibir],
                    return_when=asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
        except websockets.exceptions.InvalidStatusCode as e:
            if e.status_code == 401 or e.status_code == 1008:
                self.error_auth = True
                print(f"[{self.vehiculo_id}] ERROR 401: Conexión rechazada por servidor. Token no autorizado.")
            else:
                print(f"[{self.vehiculo_id}] Error HTTP WebSocket: {e}")
        except Exception as e:
            print(f"[{self.vehiculo_id}] Desconexión de red: {e}")
        finally:
            self.conectado = False
            self.websocket = None

    async def _bucle_envio(self):
        while self.conectado and self.websocket:
            payload = await self.cola_envio.get()
            mensaje = json.dumps(payload)
            await self.websocket.send(mensaje)
            self.bytes_enviados_seg += len(mensaje.encode('utf-8'))
            self.cola_envio.task_done()

    async def _bucle_recepcion(self):
        while self.conectado and self.websocket:
            try:
                mensaje = await self.websocket.receive()
                if mensaje:
                    data = json.loads(mensaje)
                    if data.get("alerta"):
                        self.servidor_ia_evento = data.get("evento", "ALERTA")
                        self.servidor_ia_conf = float(data.get("confianza", 0.0))
                        self.disparar_alerta(self.servidor_ia_evento)
                    else:
                        self.servidor_ia_evento = "CONDUCCION_SEGURA"
                        self.servidor_ia_conf = float(data.get("confianza", 1.0))
            except Exception:
                break

    def disparar_alerta(self, evento):
        self.estado_alerta = evento
        self.ultima_alerta_tiempo = time.time()
        threading.Thread(target=sonar_alarma, daemon=True).start()

    def comprimir_frame(self, frame):
        """Comprime frame a 320x240 JPEG con calidad dinámica"""
        frame_pequeno = cv2.resize(frame, (320, 240))
        _, buffer = cv2.imencode('.jpg', frame_pequeno, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        return base64.b64encode(buffer).decode('utf-8')

    def procesar_vision(self, frame):
        """Detección facial, cálculo de ventana de cierre y dibujo del HUD"""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(80, 80))
        
        tiempo_cierre_actual = 0.0
        rostro_detectado = len(faces) > 0
        ojos_abiertos = False
        
        for (x, y, w, h) in faces:
            roi_gray = gray[y:y + int(h * 0.6), x:x + w] # Parte superior de la cara
            eyes = self.eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=3, minSize=(20, 20))
            
            if len(eyes) >= 1:
                ojos_abiertos = True
                for (ex, ey, ew, eh) in eyes:
                    cv2.rectangle(frame, (x + ex, y + ey), (x + ex + ew, y + ey + eh), (0, 255, 0), 1)

            color_rect = (0, 255, 0) if self.estado_alerta == "CONDUCCION_SEGURA" else (0, 0, 255)
            cv2.rectangle(frame, (x, y), (x + w, y + h), color_rect, 2)
            break

        # Lógica Temporal: Anti-Falsos Positivos
        ahora = time.time()
        if rostro_detectado and not ojos_abiertos:
            if self.inicio_ojos_cerrados == 0:
                self.inicio_ojos_cerrados = ahora
            tiempo_cierre_actual = ahora - self.inicio_ojos_cerrados

            if tiempo_cierre_actual >= self.UMBRAL_MICROSUEÑO_SEG:
                if self.estado_alerta != "MICROSUEÑO_DETECTADO":
                    self.disparar_alerta("MICROSUEÑO_DETECTADO")
                    # Enviar evidencia crítica al servidor
                    if self.conectado:
                        asyncio.run_coroutine_threadsafe(
                            self.cola_envio.put({
                                "tipo": "evento_critico",
                                "evento": "MICROSUEÑO_DETECTADO",
                                "duracion_seg": round(tiempo_cierre_actual, 2),
                                "confianza_custom": 1.0,
                                "imagen": self.comprimir_frame(frame)
                            }),
                            self.loop
                        )
                    self.inicio_ojos_cerrados = ahora  # Reiniciar ventana
        else:
            self.inicio_ojos_cerrados = 0
            if ahora - self.ultima_alerta_tiempo > 2.0:
                self.estado_alerta = "CONDUCCION_SEGURA"

        return frame, tiempo_cierre_actual, rostro_detectado

    def dibujar_hud(self, frame, tiempo_cierre, rostro_detectado):
        """Renderiza interfaz de cabina tipo telemetría con métricas en vivo"""
        h, w = frame.shape[:2]
        
        # Barra superior semi-transparente
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, 55), (20, 20, 25), -1)
        cv2.rectangle(overlay, (0, h - 35), (w, h), (20, 20, 25), -1)
        cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)

        # Estado de conexión
        if self.conectado:
            estado_net = f"WS: CONECTADO [{self.vehiculo_id}]"
            color_net = (0, 255, 0)
        elif self.error_auth:
            estado_net = "WS: RECHAZADO 401 (TOKEN INVALIDO)"
            color_net = (0, 0, 255)
        else:
            estado_net = "WS: DESCONECTADO (Reintentando...)"
            color_net = (0, 165, 255)

        cv2.putText(frame, estado_net, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color_net, 2)
        cv2.putText(frame, f"NET: {self.kbps_actual:.1f} Kbps | FPS: {self.fps_actual:.0f}", (w - 240, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Estado central de alerta
        color_alerta = (0, 255, 0) if self.estado_alerta == "CONDUCCION_SEGURA" else (0, 0, 255)
        texto_alerta = f"ESTADO: {self.estado_alerta}"
        if tiempo_cierre > 0:
            texto_alerta += f" (Cierre: {tiempo_cierre:.1f}s / 1.5s)"
        cv2.putText(frame, texto_alerta, (10, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color_alerta, 2)

        # Barra inferior
        cv2.putText(frame, f"Cloud YOLOv8: {self.servidor_ia_evento} ({self.servidor_ia_conf*100:.0f}%)",
                    (10, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        cv2.putText(frame, "FleetGuard DMS Edge | Presiona [Q] para salir", (w - 340, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

        # Borde exterior de advertencia si hay alerta
        if self.estado_alerta != "CONDUCCION_SEGURA":
            cv2.rectangle(frame, (0, 0), (w, h), (0, 0, 255), 6)


async def main_edge(args):
    cliente = ClienteVehiculoEdge(
        vehiculo_id=args.id,
        token="" if args.no_token else args.token,
        host=args.host
    )
    cliente.loop = asyncio.get_running_loop()

    # Iniciar conexión WebSocket en segundo plano
    asyncio.create_task(cliente.conectar_websocket())

    # Abrir cámara web
    cap = cv2.VideoCapture(args.cam)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not cap.isOpened():
        print("[ERROR] No se pudo acceder a la webcam.")
        return

    print("=====================================================")
    print(f" FLEETGUARD DMS - CABINA EDGE VEHICULO {args.id}")
    print("=====================================================")
    print("Simulación de prueba:")
    print(" 1. Parpadeo normal: No dispara alerta (< 1.5s).")
    print(" 2. Ojos cerrados 2s: Activa alarma sonora y guarda evidencia en nube.")
    print(" 3. Uso celular: YOLOv8 en Cloud detecta y devuelve alerta.")
    print("=====================================================")

    frame_count = 0
    t_fps = time.time()
    ultimo_muestreo = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1
        t_ahora = time.time()

        # Medición de FPS y Kbps
        if t_ahora - t_fps >= 1.0:
            cliente.fps_actual = frame_count / (t_ahora - t_fps)
            frame_count = 0
            t_fps = t_ahora
            cliente.kbps_actual = (cliente.bytes_enviados_seg * 8) / 1024.0
            cliente.bytes_enviados_seg = 0

        # Procesar geometría facial y ventana temporal
        frame, t_cierre, rostro = cliente.procesar_vision(frame)

        # Muestreo periódico a Cloud YOLOv8 (1 vez por segundo)
        if t_ahora - ultimo_muestreo >= 1.0:
            if cliente.conectado:
                asyncio.run_coroutine_threadsafe(
                    cliente.cola_envio.put({
                        "tipo": "muestreo_yolo",
                        "imagen": cliente.comprimir_frame(frame)
                    }),
                    cliente.loop
                )
            ultimo_muestreo = t_ahora

        # Renderizar telemetría HUD
        cliente.dibujar_hud(frame, t_cierre, rostro)
        cv2.imshow(f"FleetGuard DMS Edge - {args.id}", frame)

        # Procesar eventos de interfaz y ceder control a asyncio
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        await asyncio.sleep(0.005)

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FleetGuard DMS - Edge Client")
    parser.add_argument("--id", type=str, default="BUS-04", help="ID del vehículo (ej: BUS-04, BUS-02)")
    parser.add_argument("--token", type=str, default="fleetguard_token_secreto_2026", help="API Key / Token de autenticación")
    parser.add_argument("--host", type=str, default="localhost:8000", help="Host del servidor central (ej: localhost:8000)")
    parser.add_argument("--cam", type=int, default=0, help="Índice de la webcam (default: 0)")
    parser.add_argument("--no-token", action="store_true", help="Simula conexión no autenticada para probar rechazo 401")
    
    args = parser.parse_args()
    asyncio.run(main_edge(args))
