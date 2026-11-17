from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import Optional
import asyncio
import json
import base64
import os
import cv2
import numpy as np
from datetime import datetime

# Importar motor de IA y modelos de BD
from ai_engine import evaluar_conducta_yolo
import models

# Rutas base del servidor
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
EVIDENCIAS_DIR = os.path.join(STORAGE_DIR, "evidencias")
os.makedirs(EVIDENCIAS_DIR, exist_ok=True)

# Variables de entorno
API_KEY_SECRETO = os.getenv("API_KEY", "fleetguard_token_secreto_2026")

app = FastAPI(
    title="FleetGuard DMS - Central Server Edge",
    description="Servidor privado de monitoreo de fatiga y distracción para cabinas de flota.",
    version="2.0.0"
)

# Servir carpeta de evidencias (Simulación Azure Blob Storage)
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")

# Silenciar 404 de favicon en navegadores
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# Dependencia para Autenticación en endpoints HTTP normales (X-API-Key o query param)
def verificar_api_key(
    x_api_key: Optional[str] = Header(None),
    api_key: Optional[str] = Query(None),
    token: Optional[str] = Query(None)
):
    key = x_api_key or api_key or token
    if key != API_KEY_SECRETO:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: API Key inválida o faltante. Incluya el encabezado 'X-API-Key: <token>' o el parámetro '?api_key=<token>'."
        )
    return key

@app.get("/")
async def get_dashboard():
    """Retorna el cliente web HTML estático para visualización en cabina."""
    index_file = os.path.join(BASE_DIR, "static", "index.html")
    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/flota/incidentes", dependencies=[Depends(verificar_api_key)])
def listar_incidentes(db: Session = Depends(models.get_db)):
    """
    Devuelve el historial en JSON manteniendo el formato requerido por la rúbrica:
    [
      {
        "vehiculo_id": "BUS-04",
        "evento": "MICROSUEÑO_DETECTADO",
        "duracion_seg": 1.8,
        "confianza_custom": 0.92,
        "evidencia_url": "/storage/evidencias/BUS-04/20261117_081522.jpg"
      }
    ]
    """
    incidentes = db.query(models.Incidente).order_by(models.Incidente.id.desc()).all()
    resultado = []
    for inc in incidentes:
        resultado.append({
            "vehiculo_id": inc.vehiculo_id,
            "evento": inc.evento,
            "duracion_seg": round(inc.duracion_seg, 2) if inc.duracion_seg else 0.0,
            "confianza_custom": round(inc.confianza_custom, 2) if inc.confianza_custom else 1.0,
            "evidencia_url": inc.evidencia_url
        })
    return resultado

# Control de cooldown por (vehiculo_id, evento) para evitar spam masivo de capturas por segundo
cooldown_alertas = {}

async def guardar_evidencia_y_bd(
    vehiculo_id: str, 
    evento: str, 
    frame, 
    confianza_custom: float,
    duracion_seg: float = 0.0
):
    """Guarda imagen emulando Azure Blob Storage y registra en SQLite"""
    ahora = datetime.now()
    clave_cooldown = (vehiculo_id, evento)
    
    # Cooldown de 2.5 segundos para no inundar el disco con fotos idénticas
    ultimo = cooldown_alertas.get(clave_cooldown)
    if ultimo and (ahora - ultimo).total_seconds() < 2.5:
        return None
    cooldown_alertas[clave_cooldown] = ahora

    # 1. Generar ruta estructurada /storage/evidencias/{vehiculo_id}/{timestamp}.jpg
    timestamp = ahora.strftime("%Y%m%d_%H%M%S")
    directorio_vehiculo = os.path.join(EVIDENCIAS_DIR, vehiculo_id)
    os.makedirs(directorio_vehiculo, exist_ok=True)
    
    filename = f"{timestamp}.jpg"
    filepath = os.path.join(directorio_vehiculo, filename)
    # URL pública uniforme para emulación de Blob Storage
    evidencia_url = f"/storage/evidencias/{vehiculo_id}/{filename}"
    
    # 2. Guardar imagen en disco de forma no bloqueante
    await asyncio.to_thread(cv2.imwrite, filepath, frame)
    
    # 3. Guardar en SQLite obteniendo una sesión temporal
    duracion_final = duracion_seg if duracion_seg > 0 else (1.5 if evento == "MICROSUEÑO_DETECTADO" else 0.0)
    db = next(models.get_db())
    try:
        nuevo_incidente = models.Incidente(
            vehiculo_id=vehiculo_id,
            evento=evento,
            duracion_seg=round(duracion_final, 2),
            confianza_custom=round(confianza_custom, 2),
            evidencia_url=evidencia_url
        )
        db.add(nuevo_incidente)
        db.commit()
    finally:
        db.close()
        
    print(f"[{vehiculo_id}] Alerta registrada críticamente: {evento} -> {evidencia_url}")
    return evidencia_url

@app.websocket("/ws/flota/{vehiculo_id}")
async def websocket_dms(
    websocket: WebSocket, 
    vehiculo_id: str, 
    token: Optional[str] = Query(None),
    api_key: Optional[str] = Query(None)
):
    # Capa de Seguridad para WebSockets: acepta encabezado X-API-Key o query param token / api_key
    auth_token = websocket.headers.get("x-api-key") or token or api_key
    if auth_token != API_KEY_SECRETO:
        print(f"[{vehiculo_id}] Intento de conexión rechazado: Token inválido ('{auth_token}')")
        await websocket.close(code=1008)  # Policy Violation (HTTP 401 equivalente en WebSockets)
        return

    await websocket.accept()
    print(f"[{vehiculo_id}] Vehículo conectado a la nube de monitoreo central.")

    try:
        while True:
            # Recibir telemetría del cliente web o edge
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
            except Exception:
                continue

            tipo = payload.get("tipo")
            imagen_b64 = payload.get("imagen")
            if not imagen_b64:
                continue

            imagen_bytes = base64.b64decode(imagen_b64)
            
            # Caso 1: El Edge detectó un microsueño localmente por MediaPipe FaceMesh
            if tipo == "evento_critico":
                np_arr = np.frombuffer(imagen_bytes, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                evento = payload.get("evento", "MICROSUEÑO_DETECTADO")
                duracion = float(payload.get("duracion_seg", 1.5))
                confianza = float(payload.get("confianza_custom", 1.0))
                
                await guardar_evidencia_y_bd(
                    vehiculo_id=vehiculo_id,
                    evento=evento,
                    frame=frame,
                    confianza_custom=confianza,
                    duracion_seg=duracion
                )
                
                # Confirmar recepción de alerta al cliente
                await websocket.send_json({
                    "alerta": True,
                    "evento": evento,
                    "duracion_seg": duracion,
                    "confianza": confianza
                })
            
            # Caso 2: Muestreo periódico para validación de YOLOv8 en Cloud
            elif tipo == "muestreo_yolo":
                # Inferencia delegada a hilo secundario para no bloquear concurrencia
                clase_nombre, confianza, frame = await asyncio.to_thread(
                    evaluar_conducta_yolo, imagen_bytes
                )
                
                if clase_nombre in ["uso_celular", "distraccion_lateral", "sin_conductor"]:
                    await guardar_evidencia_y_bd(
                        vehiculo_id=vehiculo_id,
                        evento=clase_nombre.upper(),
                        frame=frame,
                        confianza_custom=confianza,
                        duracion_seg=1.0
                    )
                    # Enviar alerta de vuelta al cliente para hacer sonar la alarma
                    await websocket.send_json({
                        "alerta": True, 
                        "evento": clase_nombre.upper(), 
                        "confianza": round(confianza, 2)
                    })
                else:
                    await websocket.send_json({
                        "alerta": False, 
                        "evento": "CONDUCCION_SEGURA", 
                        "confianza": round(confianza, 2)
                    })

    except WebSocketDisconnect:
        print(f"[{vehiculo_id}] Vehículo desconectado.")
