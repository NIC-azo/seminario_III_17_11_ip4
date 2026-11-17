"""
Script de Entrenamiento - FleetGuard DMS (Custom Vision con YOLOv8)
Clasificación de 4 conductas de riesgo en cabina:
1. conduccion_segura
2. uso_celular
3. distraccion_lateral
4. sin_conductor
"""

import os
import shutil
import random
from ultralytics import YOLO

def preparar_dataset(dataset_origen="dataset_crudo", dataset_destino="dataset_yolo", split_ratio=0.8):
    """
    Divide el dataset crudo en train y val para entrenamiento YOLOv8-cls
    """
    clases = ['conduccion_segura', 'uso_celular', 'distraccion_lateral', 'sin_conductor']
    
    if not os.path.exists(dataset_origen):
        print(f"[AVISO] Carpeta '{dataset_origen}' no encontrada. Usando estructura existente.")
        return dataset_origen

    for split in ['train', 'val']:
        for c in clases:
            os.makedirs(os.path.join(dataset_destino, split, c), exist_ok=True)

    print("Organizando imágenes en splits train/val...")
    for c in clases:
        ruta_clase = os.path.join(dataset_origen, c)
        if not os.path.exists(ruta_clase):
            continue
        archivos = [f for f in os.listdir(ruta_clase) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        random.shuffle(archivos)
        
        corte = int(len(archivos) * split_ratio)
        train_files = archivos[:corte]
        val_files = archivos[corte:]

        for f in train_files:
            shutil.copy(os.path.join(ruta_clase, f), os.path.join(dataset_destino, 'train', c, f))
        for f in val_files:
            shutil.copy(os.path.join(ruta_clase, f), os.path.join(dataset_destino, 'val', c, f))

    print("Dataset preparado exitosamente.")
    return dataset_destino

def entrenar_modelo():
    dataset_dir = preparar_dataset()
    print("Iniciando entrenamiento del modelo Custom Vision con YOLOv8...")
    
    # Modelo base ligero ideal para Edge / Cloud inferencia rápida
    model = YOLO('yolov8n-cls.pt')
    
    # Entrenar por 25 épocas con tamaño de imagen 320 para alta velocidad de inferencia
    model.train(
        data=dataset_dir,
        epochs=25,
        imgsz=320,
        batch=16,
        workers=2,
        name='fleetguard_dms'
    )
    
    # Copiar el mejor modelo a la carpeta server/
    best_path = os.path.join('runs', 'classify', 'fleetguard_dms', 'weights', 'best.pt')
    if os.path.exists(best_path):
        os.makedirs('server', exist_ok=True)
        shutil.copy(best_path, os.path.join('server', 'best.pt'))
        print("¡Modelo entrenado 'best.pt' guardado exitosamente en server/best.pt!")
    else:
        print("Entrenamiento completado.")

if __name__ == "__main__":
    entrenar_modelo()
