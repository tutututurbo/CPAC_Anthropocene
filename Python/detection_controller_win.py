import os
# Disattiva le HW transforms di Media Foundation (evita l'errore MSMF -1072875772).
# DEVE stare prima di "import cv2".
os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"

import cv2
import numpy as np
import argparse
from ultralytics import YOLO
from pythonosc import udp_client

# =========================
# 1. SETUP SPOUT (Windows, equivalente di Syphon)
# =========================
# pip install SpoutGL PyOpenGL
SPOUT_AVAILABLE = False
try:
    import SpoutGL
    from OpenGL import GL
    SPOUT_AVAILABLE = True
    print("\n✅  SpoutGL library found.")
except ImportError:
    print("\n⚠️  SpoutGL not found (pip install SpoutGL PyOpenGL). Running in OpenCV-only mode.")

# Se in TouchDesigner l'immagine arriva capovolta, metti True (o usa un Flip TOP in TD)
SPOUT_FLIP = False

# True  -> invia la persona con canale ALPHA trasparente (premoltiplicato): in TD usa Composite "Over"
# False -> invia la persona su sfondo bianco opaco (comportamento originale)
SEND_ALPHA = True


class SpoutSender:
    def __init__(self, name="PythonSegmentation"):
        self.name = name
        self.sender = None
        if SPOUT_AVAILABLE:
            try:
                self.sender = SpoutGL.SpoutSender()
                self.sender.setSenderName(name)
                print(f"✅ Spout Sender started: {name}")
            except Exception as e:
                print(f"❌ Spout init error: {e}")
                self.sender = None

    def send_rgba(self, frame_rgba):
        """Invia un frame RGBA uint8 (H, W, 4). Ordine canali RGBA = niente tinta blu in TD."""
        if not self.sender:
            return
        try:
            frame_rgba = np.ascontiguousarray(frame_rgba)
            h, w = frame_rgba.shape[:2]
            self.sender.sendImage(frame_rgba, w, h, GL.GL_RGBA, SPOUT_FLIP, 0)
            self.sender.setFrameSync(self.name)
        except Exception as e:
            print(f"\n❌ Spout send error: {e}")

    def stop(self):
        if self.sender:
            try:
                self.sender.releaseSender()
            except Exception:
                pass


# =========================
# 2. SETUP OSC (Network)
# =========================
# Configura i client OSC per TouchDesigner (Visual Logic) e SuperCollider (Audio)
parser = argparse.ArgumentParser()
parser.add_argument("--ip", default="127.0.0.1", help="The ip of the OSC server")
parser.add_argument("--cam", type=int, default=0, help="Indice webcam preferito")
parser.add_argument("--no-preview", action="store_true", help="Disattiva la finestra OpenCV")
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


# =========================
# SETUP VIDEO (robusto su Windows)
# =========================
def open_camera(preferred_index=0, width=640, height=480):
    # Prova prima DirectShow (più stabile su Windows), poi MSMF, su più indici
    indices = [preferred_index] + [i for i in (0, 1, 2) if i != preferred_index]
    for backend, bname in [(cv2.CAP_DSHOW, "DSHOW"), (cv2.CAP_MSMF, "MSMF")]:
        for idx in indices:
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            ok, _ = cap.read()
            if ok:
                print(f"📷 Camera OK -> index {idx}, backend {bname}")
                return cap
            cap.release()
    raise RuntimeError(
        "Nessuna camera disponibile. È forse aperta da un'altra app "
        "(TouchDesigner Video Device In, Teams, OBS...)?"
    )


vid = open_camera(args.cam)

spout = SpoutSender("Anthropocene_Input")

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
fail_count = 0
try:
    while True:
        ret, frame = vid.read()
        if not ret:
            fail_count += 1
            if fail_count > 30:  # ~1 s di errori consecutivi -> riapri la camera
                print("\n⚠️  Camera persa, riconnessione...")
                vid.release()
                vid = open_camera(args.cam)
                fail_count = 0
            continue
        fail_count = 0

        # 1. INFERENZA AI (Solo ogni 3 frame)
        if frame_counter % (FRAME_SKIP + 1) == 0:
            # imgsz=320: Fondamentale per la CPU. 4x più veloce di 640.
            results = model(frame, conf=0.4, imgsz=320, classes=[0], device='cpu',
                            verbose=False, retina_masks=True)
            result = results[0]

            last_polygons = []
            last_pos_array = []
            last_person_count = 0

            if result.boxes:
                last_person_count = len(result.boxes)
                for box in result.boxes:
                    x1, y1, x2, y2 = box.xyxyn[0]
                    last_pos_array.extend([(x1 + x2).item() / 2, (y1 + y2).item() / 2])

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
        if final_entropy > MAX_PERSONS:
            final_entropy = MAX_PERSONS

        client_td.send_message("/coord", last_pos_array)
        client_td.send_message("/entropy_level", float(final_entropy))
        client_sc.send_message("/entropy_level", float(final_entropy))

        # 3. RENDERING (Soft Blending)
        # A. Maschera (vuota se nessuna persona)
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        if last_polygons:
            cv2.fillPoly(mask, last_polygons, 255)
            # B. Blur per bordi morbidi
            mask = cv2.GaussianBlur(mask, (15, 15), 0)

        # C. Alpha morbido 0..1 (float32: più veloce di float64)
        alpha = (mask.astype(np.float32) / 255.0)[..., None]  # (H, W, 1)
        frame_f = frame.astype(np.float32)

        # D. Persona premoltiplicata (RGB * alpha): è il formato che TD si aspetta
        person = (frame_f * alpha).astype(np.uint8)

        if SEND_ALPHA:
            out_rgba = cv2.cvtColor(person, cv2.COLOR_BGR2RGBA)
            out_rgba[..., 3] = mask
        else:
            # Persona su bianco opaco: Video * alpha + Bianco * (1 - alpha)
            on_white = (frame_f * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
            out_rgba = cv2.cvtColor(on_white, cv2.COLOR_BGR2RGBA)

        # Preview locale sempre su bianco (più leggibile della trasparenza)
        frame = (frame_f * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)

        # 4. OUTPUT
        spout.send_rgba(out_rgba)

        # Debug visivo ridotto al minimo (solo stampa console ogni 30 frame)
        if frame_counter % 30 == 0:
            print(f"People: {last_person_count} | Entropy: {final_entropy}    ", end="\r")

        frame_counter += 1

        if not args.no_preview:
            cv2.imshow('CPU Tracker (Low Res Analysis)', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
except KeyboardInterrupt:
    pass
finally:
    # Cleanup
    spout.stop()
    vid.release()
    cv2.destroyAllWindows()