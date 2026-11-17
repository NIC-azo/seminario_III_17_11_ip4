import os
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, Header, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import asyncio

import models
from ai_engine import analizar_frame_sincrono

# Variables de entorno
API_KEY_SECRETO = os.getenv("API_KEY", "fleetguard_token_secreto_2026")

app = FastAPI(title="FleetGuard DMS - Central Server")

# Dependencia para Autenticación (Requisito de Seguridad)
def verificar_api_key(x_api_key: str = Header(None)):
    if x_api_key != API_KEY_SECRETO:
        raise HTTPException(status_code=401, detail="Unauthorized: API Key inválida o faltante")
    return x_api_key

@app.get("/")
def health_check():
    return {"status": "FleetGuard Server OK"}

@app.post("/flota/analizar", dependencies=[Depends(verificar_api_key)])
async def analizar_flujo(file: UploadFile = File(...)):
    """
    Recibe un frame por red, lo procesa sin bloquear el Event Loop (asyncio.to_thread)
    y devuelve la telemetría en tiempo real.
    """
    image_bytes = await file.read()
    
    # Delegar la inferencia pesada a un hilo secundario
    resultado = await asyncio.to_thread(analizar_frame_sincrono, image_bytes)
    
    if "error" in resultado:
        return JSONResponse(status_code=400, content=resultado)
        
    return resultado

@app.post("/flota/alerta", dependencies=[Depends(verificar_api_key)])
async def registrar_alerta(
    vehiculo_id: str = Form(...),
    evento: str = Form(...),
    duracion_seg: float = Form(...),
    confianza_custom: float = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(models.get_db)
):
    """
    Cuando el Cliente Edge confirma un microsueño (>1.5s) o infracción, 
    llama aquí para guardar la evidencia (Azure Blob Storage simulado) y base de datos.
    """
    # 1. Generar ruta estructurada
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    directorio = f"./storage/evidencias/{vehiculo_id}"
    os.makedirs(directorio, exist_ok=True)
    
    file_path = f"{directorio}/{timestamp}.jpg"
    
    # 2. Guardar imagen en disco
    image_bytes = await file.read()
    with open(file_path, "wb") as f:
        f.write(image_bytes)
        
    # URL virtual para devolver en la API
    evidencia_url = f"/storage/evidencias/{vehiculo_id}/{timestamp}.jpg"
    
    # 3. Guardar en SQLite
    nuevo_incidente = models.Incidente(
        vehiculo_id=vehiculo_id,
        evento=evento,
        duracion_seg=duracion_seg,
        confianza_custom=confianza_custom,
        evidencia_url=evidencia_url
    )
    db.add(nuevo_incidente)
    db.commit()
    db.refresh(nuevo_incidente)
    
    return {"mensaje": "Alerta registrada críticamente", "id_bd": nuevo_incidente.id}

@app.get("/flota/incidentes", dependencies=[Depends(verificar_api_key)])
def listar_incidentes(db: Session = Depends(models.get_db)):
    """
    Devuelve el JSON exacto solicitado en los requerimientos obligatorios.
    """
    incidentes = db.query(models.Incidente).order_by(models.Incidente.id.desc()).all()
    resultado = []
    
    for inc in incidentes:
        resultado.append({
            "vehiculo_id": inc.vehiculo_id,
            "evento": inc.evento,
            "duracion_seg": inc.duracion_seg,
            "confianza_custom": inc.confianza_custom,
            "evidencia_url": inc.evidencia_url
        })
        
    return resultado