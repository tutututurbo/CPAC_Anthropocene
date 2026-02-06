import cv2
import time
import numpy as np
from ultralytics import YOLO

# --- CONFIGURAZIONE SEMPLIFICATA ---
# Carica direttamente il modello dalla cartella corrente
# Assicurati che "yolov8n-seg.pt" sia accanto a questo script
model = YOLO("yolov8n-seg.pt")

# Cerchiamo l'ID della classe "person" (solitamente è 0)
# Questo serve per dire al modello di ignorare tutto il resto
target_class_id = 0 # Default standard COCO
if hasattr(model, 'names'):
    for k, v in model.names.items():
        if v == 'person':
            target_class_id = k
            break

print(f"Modello caricato. ID classe Persona: {target_class_id}")

# Setup Video
vid = cv2.VideoCapture(0)
vid.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
vid.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

prev_time = 0

while True:
    ret, frame = vid.read()
    if not ret:
        break
    
    frame_original = frame.copy()

    # 1. INFERENZA
    # classes=[target_class_id] filtra solo le persone
    results = model(
        frame, 
        conf=0.3, 
        iou=0.5, 
        classes=[target_class_id], 
        imgsz=640, 
        verbose=False,
        retina_masks=True
    )

    # 2. CREAZIONE MASCHERA COMULATIVA
    # Creiamo una maschera nera vuota
    combined_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    
    result = results[0]

    if result.masks is not None:
        # Iteriamo su tutti i segmenti (persone) trovati
        for segment in result.masks.xy:
            if len(segment) > 0:
                poly = segment.astype(np.int32)
                # "Disegniamo" la persona in bianco (255) sulla maschera
                cv2.fillPoly(combined_mask, [poly], 255)

        # 3. APPLICAZIONE MASCHERA CON SFONDO BIANCO
        # Crea uno sfondo bianco
        white_bg = np.ones_like(frame, dtype=np.uint8) * 255

        # Copia solo la persona sullo sfondo bianco
        frame = white_bg.copy()
        frame[combined_mask == 255] = frame_original[combined_mask == 255]
    else:
        # Nessuna persona trovata -> frame nero
        frame = np.zeros_like(frame)

    # Calcolo FPS
    curr_time = time.time()
    fps = 1 / (curr_time - prev_time) if prev_time > 0 else 0
    prev_time = curr_time

    # Display info
    cv2.putText(frame, f"FPS: {fps:.2f}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    cv2.putText(frame, "Q per uscire", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    
    cv2.imshow('Segmentation Only', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

vid.release()
cv2.destroyAllWindows()