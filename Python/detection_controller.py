import cv2
import numpy as np
import argparse
from ultralytics import YOLO
from pythonosc import udp_client

# =========================
# 1. SETUP SYPHON (macOS Metal)
# =========================
SYPHON_AVAILABLE = False
try:
    from syphon.server import SyphonMetalServer
    import Metal
    SYPHON_AVAILABLE = True
    print("\n✅  Syphon Metal library found.")
except ImportError:
    print("\n⚠️  Syphon library not found. Running in OpenCV-only mode.")

class SyphonSender:
    def __init__(self, name="PythonSegmentation"):
        self.server = None
        self.device = None
        self.texture = None
        self.current_width = 0
        self.current_height = 0
        
        if SYPHON_AVAILABLE:
            try:
                self.device = Metal.MTLCreateSystemDefaultDevice()
                self.server = SyphonMetalServer(name, self.device)
                print(f"✅ Syphon Server started: {name}")
            except Exception as e:
                print(f"❌ Syphon init error: {e}")

    def send_frame(self, frame_bgr):
        if not self.server: return
        try:
            frame_bgra = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
            frame_bgra = cv2.flip(frame_bgra, 0)
            height, width = frame_bgra.shape[:2]
            
            if self.current_width != width or self.current_height != height:
                desc = Metal.MTLTextureDescriptor.texture2DDescriptorWithPixelFormat_width_height_mipmapped_(
                    Metal.MTLPixelFormatBGRA8Unorm, width, height, False)
                desc.setStorageMode_(Metal.MTLStorageModeManaged)
                desc.setUsage_(Metal.MTLTextureUsageShaderRead | Metal.MTLTextureUsageShaderWrite)
                self.texture = self.device.newTextureWithDescriptor_(desc)
                self.current_width = width
                self.current_height = height

            raw_bytes = frame_bgra.tobytes()
            region = Metal.MTLRegionMake2D(0, 0, width, height)
            self.texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
                region, 0, raw_bytes, width * 4)
            
            if hasattr(self.texture, 'buffer') and self.texture.buffer():
                 self.texture.didModifyRange_(Metal.NSMakeRange(0, self.texture.buffer().length()))

            self.server.publish_frame_texture(self.texture)
        except Exception:
            pass

# =========================
# 2. SETUP OSC (Network)
# =========================
# Configura i client OSC per TouchDesigner (Visual Logic) e SuperCollider (Audio)
parser = argparse.ArgumentParser()
parser.add_argument("--ip", default="127.0.0.1", help="The ip of the OSC server")
args = parser.parse_args()

# Client per TouchDesigner (Porta 12000 standard)
client_td = udp_client.SimpleUDPClient(args.ip, 12000)
# Client per SuperCollider (Porta 57120 standard)
client_sc = udp_client.SimpleUDPClient(args.ip, 57120)

print("\n📡 OSC Clients Ready -> TD:12000 | SC:57120")

# =========================
# 3. LOGICA ENTROPIA
# =========================
MAX_PERSONS = 6
INTERPOLATION_STEP = 0.05
current_entropy = 0.0

# --- CONFIGURAZIONE PERFORMANCE ---
FRAME_SKIP = 2   # Esegui AI solo 1 volta ogni 3 frame (Risparmio 66% CPU)
frame_counter = 0

# Carica modello su CPU
print("\n⚙️  Loading YOLO on CPU...\n")
# Usiamo il modello di segmentazione che fa TUTTO (rileva box + crea maschere)
model = YOLO("yolov8n-seg.pt")

# Setup Video
vid = cv2.VideoCapture(0)
vid.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
vid.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

syphon = SyphonSender("Anthropocene_Input")

# Variabili Cache (Per i frame in cui non calcoliamo l'AI)
last_polygons = []
last_person_count = 0
last_pos_array = [-1.0] * (MAX_PERSONS * 2)

def update_entropy(target, current):
    if current < target:
        return min(target, current + INTERPOLATION_STEP)
    elif current > target:
        return max(target, current - INTERPOLATION_STEP)
    return current

print("\n🚀 SYSTEM STARTED\n")

# =========================
# 4. MAIN LOOP
# =========================
while True:
    ret, frame = vid.read()
    if not ret: break

    # 1. INFERENZA AI (Solo ogni 3 frame)
    if frame_counter % (FRAME_SKIP + 1) == 0:
        # imgsz=320: Fondamentale per la CPU. 4x più veloce di 640.
        results = model(frame, conf=0.4, imgsz=320, classes=[0], device='cpu', verbose=False, retina_masks=True)
        result = results[0]
        
        last_polygons = []
        last_pos_array = []
        last_person_count = 0

        if result.boxes:
            last_person_count = len(result.boxes)
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxyn[0]
                last_pos_array.extend([(x1+x2).item()/2, (y1+y2).item()/2])
            
            if result.masks:
                for segment in result.masks.xy:
                    if len(segment) > 0:
                        last_polygons.append(segment.astype(np.int32))

        # Padding array
        if len(last_pos_array) < MAX_PERSONS * 2:
            last_pos_array.extend([-1.0] * (MAX_PERSONS * 2 - len(last_pos_array)))
        else:
            last_pos_array = last_pos_array[:MAX_PERSONS * 2]

    # 2. LOGICA CONTINUA
    current_entropy = update_entropy(last_person_count, current_entropy)
    final_entropy = round(current_entropy, 2)
    if final_entropy > MAX_PERSONS: final_entropy = MAX_PERSONS

    client_td.send_message("/coord", last_pos_array)
    client_td.send_message("/entropy_level", float(final_entropy))
    client_sc.send_message("/entropy_level", float(final_entropy))

    # 3. RENDERING IN-PLACE (Soft Blending)
    if last_polygons:
        # A. Maschera Nera
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, last_polygons, 255)
        
        # B. Blur (più forte qui per ammorbidire)
        mask = cv2.GaussianBlur(mask, (15, 15), 0) 
        
        # C. Conversione in Float per la matematica (0.0 a 1.0)
        # Questo crea un canale Alpha morbido
        alpha = mask.astype(float) / 255.0
        
        # D. FUSIONE MATEMATICA (Alpha Blending)
        # Pixel finale = (Video * alpha) + (Bianco * (1 - alpha))
        
        # Sfondo Bianco (255, 255, 255)
        white_bg = np.ones_like(frame, dtype=float) * 255.0
        frame_float = frame.astype(float)
        
        # Espandi alpha per avere 3 canali (H, W, 1) -> (H, W, 3) per moltiplicare col colore
        alpha_3ch = cv2.merge([alpha, alpha, alpha])
        
        # Il calcolo magico:
        blended = (frame_float * alpha_3ch) + (white_bg * (1.0 - alpha_3ch))
        
        # Riconverti in uint8 per Syphon
        frame = blended.astype(np.uint8)

    else:
        frame.fill(255)

    # 4. OUTPUT
    syphon.send_frame(frame)
    
    # Debug visivo ridotto al minimo (solo stampa console ogni 30 frame)
    if frame_counter % 30 == 0:
        print(f"FPS: Calculating... | People: {last_person_count} | Entropy: {final_entropy}", end="\r")

    # Commenta per risparmiare CPU, ma utile per debug visivo
    cv2.imshow('CPU Tracker (Low Res Analysis)', frame)
    
    frame_counter += 1
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Cleanup
if syphon.server: syphon.server.stop()
vid.release()
cv2.destroyAllWindows()