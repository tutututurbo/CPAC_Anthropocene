import cv2
import time
import numpy as np
from ultralytics import YOLO

# =========================
# 1. SETUP SYPHON (Metal)
# =========================
SYPHON_AVAILABLE = False
try:
    from syphon.server import SyphonMetalServer
    import Metal
    SYPHON_AVAILABLE = True
    print("✅ Syphon Metal library found.")
except ImportError:
    print("⚠️ Syphon library not found. Running in OpenCV-only mode.")
    print("   (To fix: pip install syphon-python pyobjc-framework-Metal)")

class SyphonSender:
    def __init__(self, name="PythonSegmentation"):
        self.name = name
        self.server = None
        self.device = None
        self.texture = None
        self.current_width = 0
        self.current_height = 0
        
        if SYPHON_AVAILABLE:
            try:
                # Inizializza il dispositivo Metal di default (GPU)
                self.device = Metal.MTLCreateSystemDefaultDevice()
                self.server = SyphonMetalServer(name, self.device)
                print(f"✅ Syphon Server started: {name}")
            except Exception as e:
                print(f"❌ Syphon init error: {e}")
                self.server = None

    def _ensure_texture(self, width, height):
        """Ricrea la texture solo se le dimensioni cambiano."""
        if self.texture and self.current_width == width and self.current_height == height:
            return True
        
        try:
            # Crea descrittore texture BGRA (formato nativo Apple)
            desc = Metal.MTLTextureDescriptor.texture2DDescriptorWithPixelFormat_width_height_mipmapped_(
                Metal.MTLPixelFormatBGRA8Unorm, width, height, False
            )
            desc.setStorageMode_(Metal.MTLStorageModeManaged)
            # Usage: Shader Read (per Syphon) + Shader Write (per noi che ci scriviamo sopra)
            desc.setUsage_(Metal.MTLTextureUsageShaderRead | Metal.MTLTextureUsageShaderWrite)
            
            self.texture = self.device.newTextureWithDescriptor_(desc)
            self.current_width = width
            self.current_height = height
            return True
        except Exception as e:
            print(f"Texture creation error: {e}")
            return False

    def send_frame(self, frame_bgr):
        """Converte frame OpenCV BGR e lo invia a Syphon."""
        if not self.server:
            return

        try:
            # OpenCV usa BGR, Metal/Syphon preferisce BGRA
            frame_bgra = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
            
            # Ribaltiamo verticalmente perché le coordinate texture sono invertite tra OpenCV e OpenGL/Metal
            frame_bgra = cv2.flip(frame_bgra, 0)

            height, width = frame_bgra.shape[:2]
            
            if not self._ensure_texture(width, height):
                return

            # Copia i raw bytes nella texture
            raw_bytes = frame_bgra.tobytes()
            region = Metal.MTLRegionMake2D(0, 0, width, height)
            bytes_per_row = width * 4
            
            self.texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
                region, 0, raw_bytes, bytes_per_row
            )
            
            # Sincronizzazione CPU -> GPU (necessaria per Managed Mode)
            if hasattr(self.texture, 'buffer') and self.texture.buffer():
                 self.texture.didModifyRange_(Metal.NSMakeRange(0, self.texture.buffer().length()))

            # Pubblica il frame
            self.server.publish_frame_texture(self.texture)
            
        except Exception as e:
            # Silenzia errori occasionali per non bloccare il loop
            pass


# =========================
# 2. CONFIGURAZIONE YOLO
# =========================
model = YOLO("yolov8n-seg.pt")

target_class_id = 0
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

# =========================
# 3. INIZIALIZZAZIONE SYPHON
# =========================
syphon_sender = SyphonSender("PythonSegmentation") # Nome che vedrai in TD

prev_time = 0

print("\n🚀 In streaming su Syphon... (Premi Q per uscire)\n")

while True:
    ret, frame = vid.read()
    if not ret:
        break
    
    frame_original = frame.copy()

    # --- INFERENZA ---
    results = model(
        frame, 
        conf=0.3, 
        iou=0.5, 
        classes=[target_class_id], 
        imgsz=640, 
        verbose=False,
        retina_masks=True
    )

    # --- CREAZIONE MASCHERA ---
    combined_mask = np.zeros(frame.shape[:2], dtype=np.uint8)
    result = results[0]

    if result.masks is not None:
        for segment in result.masks.xy:
            if len(segment) > 0:
                poly = segment.astype(np.int32)
                cv2.fillPoly(combined_mask, [poly], 255)

        # Sfondo Bianco
        white_bg = np.ones_like(frame, dtype=np.uint8) * 255
        frame = white_bg.copy()
        
        # Copia persona su sfondo bianco
        # (Opzionale: puoi sfumare i bordi qui se necessario)
        frame[combined_mask == 255] = frame_original[combined_mask == 255]
    else:
        # Nessuna persona:
        # Nota: Nel tuo script originale mettevi sfondo NERO qui (np.zeros_like).
        # Se vuoi coerenza (sempre bianco), cambia in: frame = np.ones_like(frame) * 255
        frame = np.zeros_like(frame) 

    # --- INVIO A SYPHON ---
    syphon_sender.send_frame(frame)

    # --- VISUALIZZAZIONE LOCALE ---
    curr_time = time.time()
    fps = 1 / (curr_time - prev_time) if prev_time > 0 else 0
    prev_time = curr_time

    cv2.imshow('Segmentation Only', frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Cleanup
if syphon_sender.server:
    syphon_sender.server.stop()
vid.release()
cv2.destroyAllWindows()