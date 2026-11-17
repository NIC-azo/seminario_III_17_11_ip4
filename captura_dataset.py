import cv2
import os

# Definir las clases y crear carpetas
clases = ['conduccion_segura', 'uso_celular', 'distraccion_lateral', 'sin_conductor']
base_dir = 'dataset_crudo'

for c in clases:
    os.makedirs(os.path.join(base_dir, c), exist_ok=True)

cap = cv2.VideoCapture(0)
print("Controles: [1] Segura | [2] Celular | [3] Distracción | [4] Vacío | [q] Salir")

contadores = {c: 0 for c in clases}

while True:
    ret, frame = cap.read()
    if not ret: break
    
    cv2.imshow('Captura de Dataset - FleetGuard', frame)
    key = cv2.waitKey(1) & 0xFF
    
    clase_idx = None
    if key == ord('1'): clase_idx = 0
    elif key == ord('2'): clase_idx = 1
    elif key == ord('3'): clase_idx = 2
    elif key == ord('4'): clase_idx = 3
    elif key == ord('q'): break
    
    if clase_idx is not None:
        clase_actual = clases[clase_idx]
        contadores[clase_actual] += 1
        filename = os.path.join(base_dir, clase_actual, f"{clase_actual}_{contadores[clase_actual]}.jpg")
        cv2.imwrite(filename, frame)
        print(f"Guardado: {filename} (Total: {contadores[clase_actual]})")

cap.release()
cv2.destroyAllWindows()