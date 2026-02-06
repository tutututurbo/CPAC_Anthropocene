import cv2
import time
import asyncio
import requests
import numpy as np
import threading
import queue
import argparse
from ultralytics import YOLO
from av import VideoFrame
from aiortc import RTCPeerConnection, RTCSessionDescription, VideoStreamTrack

# =========================
# SYPHON METAL SETUP
# =========================

SYPHON_AVAILABLE = False

try:
    from syphon.server import SyphonMetalServer
    import Metal
    SYPHON_AVAILABLE = True
    print("✅ Syphon Metal imported")
except ImportError as e:
    print(f"⚠️ Syphon import error: {e}")

# =========================
# CONFIG
# =========================

DAYDREAM_API_KEY = "sk_4FFD4vzMSn4AEhjEAZJqDn9h7rAbaRG7vGjBazaesW6bMtr7yukcbzVmq4Pwofft"
DAYDREAM_BASE_URL = "https://api.daydream.live/v1"

FRAME_WIDTH = 640
FRAME_HEIGHT = 480
SYPHON_INPUT_SERVER = "SegmentedInput"
SYPHON_OUTPUT_SERVER = "DaydreamOutput"

# ENTROPY CONFIG (From detection.py)
MAX_PERSONS = 6
INTERPOLATION_STEP = 0.05

# =========================
# ENTROPY LOGIC
# =========================

def compute_entropy_level(old, new):
    if old == new:
        return new
    elif new > old:
        return old + INTERPOLATION_STEP
    else:
        return old - INTERPOLATION_STEP

# =========================
# SYPHON SENDER
# =========================

class SyphonSender:
    def __init__(self, name="SyphonOutput"):
        self.name = name
        self.server = None
        self.device = None
        self.texture = None
        self.current_width = 0
        self.current_height = 0
        
        if not SYPHON_AVAILABLE:
            return
        
        try:
            self.device = Metal.MTLCreateSystemDefaultDevice()
            self.server = SyphonMetalServer(name, self.device)
            print(f"✅ Syphon server ready: {name}")
        except Exception as e:
            print(f"❌ Syphon init error: {e}")
    
    def _ensure_texture(self, width, height):
        if self.texture and self.current_width == width and self.current_height == height:
            return True
        try:
            desc = Metal.MTLTextureDescriptor.texture2DDescriptorWithPixelFormat_width_height_mipmapped_(
                Metal.MTLPixelFormatBGRA8Unorm, width, height, False
            )
            desc.setStorageMode_(Metal.MTLStorageModeManaged)
            desc.setUsage_(Metal.MTLTextureUsageShaderRead | Metal.MTLTextureUsageShaderWrite)
            self.texture = self.device.newTextureWithDescriptor_(desc)
            self.current_width = width
            self.current_height = height
            return True
        except Exception as e:
            return False
    
    def send_frame_bgr(self, frame_bgr):
        if not self.server: return
        try:
            frame_bgra = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
            frame_bgra = cv2.flip(frame_bgra, 0)
            height, width = frame_bgra.shape[:2]
            if not self._ensure_texture(width, height): return
            
            raw_bytes = frame_bgra.tobytes()
            region = Metal.MTLRegionMake2D(0, 0, width, height)
            self.texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
                region, 0, raw_bytes, width * 4
            )
            if hasattr(self.texture, 'buffer') and self.texture.buffer():
                 self.texture.didModifyRange_(Metal.NSMakeRange(0, self.texture.buffer().length()))
            self.server.publish_frame_texture(self.texture)
        except Exception: pass 

# =========================
# PREVIEW & OUTPUT MANAGER
# =========================

class CV2Output:
    def __init__(self, name):
        self.name = name
    def send_frame_bgr(self, frame):
        cv2.imshow(self.name, frame)

class OutputManager:
    def __init__(self, name):
        self.name = name
        self.syphon = SyphonSender(name) if SYPHON_AVAILABLE else None
        self.preview = CV2Output(f"Preview: {name}")
    
    def process(self, frame):
        if self.syphon: self.syphon.send_frame_bgr(frame)
        self.preview.send_frame_bgr(frame)
    
    def stop(self):
        if self.syphon and self.syphon.server:
            try: self.syphon.server.stop()
            except: pass
        cv2.destroyWindow(self.name)

# =========================
# INPUT TRACK (Webcam + YOLO + Entropy)
# =========================

class SegmentationVideoTrack(VideoStreamTrack):
    kind = "video"
    
    def __init__(self, queue_ref):
        super().__init__()
        self.queue_ref = queue_ref
        print("Loading YOLOv8-seg...")
        self.model = YOLO("yolov8n-seg.pt")
        self.vid = cv2.VideoCapture(0)
        self.vid.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        self.vid.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        print("✅ Webcam ready")
        
        # Entropy State
        self.n_old = 0.0
        self.current_entropy = 0.0
    
    def get_entropy(self):
        """Thread-safe getter for the current entropy level"""
        return self.current_entropy

    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ret, frame = self.vid.read()
        
        if not ret:
            frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
        else:
            # Run inference
            results = self.model(frame, conf=0.3, verbose=False, retina_masks=True)
            
            # --- Entropy Calculation ---
            n_new = 0
            if results[0].boxes:
                # Count boxes where class is 0 (person)
                for box in results[0].boxes:
                    if int(box.cls.item()) == 0:
                        n_new += 1
            
            # Smooth the entropy
            entropy = compute_entropy_level(self.n_old, n_new)
            entropy = round(entropy, 2)
            if entropy > MAX_PERSONS: entropy = MAX_PERSONS
            
            # Update state
            self.n_old = entropy
            self.current_entropy = entropy
            # ---------------------------

            # --- Segmentation Visualization ---
            mask = np.zeros(frame.shape[:2], dtype=np.uint8)
            if results[0].masks:
                for segment in results[0].masks.xy:
                    if len(segment) > 0:
                        cv2.fillPoly(mask, [segment.astype(np.int32)], 255)
                frame = cv2.bitwise_and(frame, frame, mask=mask)
            else:
                frame = np.zeros_like(frame)

        if not self.queue_ref.full():
            try: self.queue_ref.put_nowait(frame)
            except queue.Full: pass
            
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        video_frame = VideoFrame.from_ndarray(frame_rgb, format="rgb24")
        video_frame.pts = pts
        video_frame.time_base = time_base
        return video_frame

    def stop(self):
        self.vid.release()

# =========================
# PROMPT MANAGER (Dynamic Updates)
# =========================
class PromptManager:
    def __init__(self, stream_id):
        self.stream_id = stream_id
        self.last_entropy_tier = -1
        self.running = True
        
        # Mapping Entropy Levels (1-6) to your Anthropocene prompts
        self.level_prompts = {
            1: "Wild animals, Deer, Wolf, Bear, Eagle, Organic, feral, majestic, fur, feathers, nature, forest, 8k, highly detailed, NO humans, NO technology, NO clothing",
            
            2: "Primitive Homo Sapiens, Tribal mud paint, animal skin clothing, rough stone tools, unkempt hair, Survivalist, raw, intense gaze, prehistoric atmosphere, cinematic lighting",
            
            3: "Pre-industrial humans, Woven fabrics, tunics, early victorian attire, simple metal tools, Structured, labor-focused, harmonious with land, historical, painting style",
            
            4: "Contemporary humans, 21st century, Hoodies, suits, denim, smartphones, headphones, Distracted, anxious, urban, fast-paced, modern photography, street style",
            
            5: "Near-future humans, Cyber-prep, Tech-wear fashion, glowing accessories, AR visors, metallic fabric accents, High-tech, clean, synthetic overlay, futurism",
            
            6: "Post-human Cyborgs, Exposed wiring, chrome limbs, neon circuitry on skin, robotic eyes, heavy modification, Dystopian, glitched, aggressive, artificial, cyberpunk, sci-fi"
        }
    
    def get_prompt_for_entropy(self, entropy):
        # 1. Convert float entropy to integer level
        # We ensure the level is at least 1 (even if entropy is 0) and max 6
        level = int(round(entropy))
        if level < 1: level = 1
        if level > 6: level = 6
        
        return self.level_prompts.get(level, self.level_prompts[1])

    async def run(self, track_ref):
        print("🧠 Anthropocene Engine Started...")
        while self.running:
            try:
                current_entropy = track_ref.get_entropy()
                
                # Determine current "tier" (Level 1-6)
                current_tier = int(round(current_entropy))
                if current_tier < 1: current_tier = 1
                if current_tier > 6: current_tier = 6
                
                # Update only if the integer level changes
                if current_tier != self.last_entropy_tier:
                    new_prompt = self.get_prompt_for_entropy(current_entropy)
                    print(f"⚡ Level {current_tier} [Entropy: {current_entropy:.2f}] | Prompt: {new_prompt[:50]}...")
                    
                    try:
                        url = f"{DAYDREAM_BASE_URL}/streams/{self.stream_id}"
                        payload = {"prompt": new_prompt}
                        
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, lambda: requests.patch(
                            url,
                            headers={"Authorization": f"Bearer {DAYDREAM_API_KEY}"},
                            json=payload,
                            timeout=5
                        ))
                        self.last_entropy_tier = current_tier
                        
                    except Exception as e:
                        print(f"⚠️ Failed to update prompt: {e}")
                
                # Check every 0.5 seconds for snappier transitions
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"Error in prompt manager: {e}")
                await asyncio.sleep(1.0)

    def stop(self):
        self.running = False

# =========================
# OUTPUT RECEIVER (HLS)
# =========================

class DaydreamHLSReceiver:
    def __init__(self, playback_id, queue_ref):
        self.playback_id = playback_id
        self.queue_ref = queue_ref
        self.running = False
        self.thread = None
    
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
    
    def _loop(self):
        hls_url = f"https://livepeercdn.studio/hls/{self.playback_id}/index.m3u8"
        print(f"📺 HLS: {hls_url}")
        time.sleep(3)
        cap = None
        import os
        os.environ["OPENCV_LOG_LEVEL"] = "SILENT"
        
        while self.running:
            try:
                if cap is None or not cap.isOpened():
                    cap = cv2.VideoCapture(hls_url)
                    if not cap.isOpened():
                        time.sleep(2)
                        continue
                    print("✅ HLS Connected!")

                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.1)
                    if cap: cap.release(); cap = None
                    continue
                
                if not self.queue_ref.full():
                    self.queue_ref.put(frame)
                time.sleep(0.01)
            except Exception:
                time.sleep(1)
                if cap: cap.release(); cap = None

    def stop(self):
        self.running = False

# =========================
# MAIN
# =========================

async def main():
    print("============================================================")
    print("  DAYDREAM (DYNAMIC ENTROPY) → SYPHON")
    print("============================================================")
    
    input_queue = queue.Queue(maxsize=2)
    output_queue = queue.Queue(maxsize=2)
    
    input_manager = OutputManager(SYPHON_INPUT_SERVER)
    output_manager = OutputManager(SYPHON_OUTPUT_SERVER)
    
    # Initial Prompt
    initial_prompt = "ROLE: You are a generative visual engine for an installation named Anthropocene. Your output is strictly controlled by an 'Entropy Level' variable ranging from 1 to 6.\n\nOBJECTIVE: Generate the FOREGROUND subject (living entity) corresponding to the current evolutionary stage. The background is provided by a separate stream; focus only on the subject's integration into the scene. OBJECTIVE: Generate the FOREGROUND subject (living entity) corresponding to the current evolutionary stage. The background is provided by a separate stream; focus only on the subject's integration into the scene.";

    
    # 1. Create Stream
    try:
        r = requests.post(
            f"{DAYDREAM_BASE_URL}/streams",
            headers={"Authorization": f"Bearer {DAYDREAM_API_KEY}"},
            json={"prompt": initial_prompt}, timeout=15
        )
        r.raise_for_status()
        data = r.json()
        stream_id = data.get("id") # Capture ID for updates
        print(f"✅ Stream Created ID: {stream_id}")
    except Exception as e:
        print(f"❌ API Error: {e}")
        return

    print(f"\n🌐 https://lvpr.tv?v={data['output_playback_id']}")
    
    # 2. Setup WebRTC
    pc = RTCPeerConnection()
    track = SegmentationVideoTrack(queue_ref=input_queue)
    pc.addTrack(track)
    
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    try:
        r = requests.post(data["whip_url"], 
                         headers={"Content-Type": "application/sdp"}, 
                         data=pc.localDescription.sdp,
                         timeout=10)
        if r.status_code == 201:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=r.text, type="answer"))
            print("✅ WHIP connected!")
        else:
            print(f"❌ WHIP Failed: {r.status_code}")
            return
    except Exception as e:
        print(f"❌ WHIP Connection Error: {e}")
        return

    # 3. Start HLS Receiver
    receiver = DaydreamHLSReceiver(data['output_playback_id'], output_queue)
    receiver.start()
    
    # 4. Start Prompt Manager (Dynamic Entropy Updates)
    prompt_manager = PromptManager(stream_id)
    # Run prompt manager as a background task
    prompt_task = asyncio.create_task(prompt_manager.run(track))
    
    print("\n✅ RUNNING! Ctrl+C to stop\n")
    
    try:
        while True:
            # Display Input
            try:
                while not input_queue.empty():
                    input_manager.process(input_queue.get_nowait())
            except queue.Empty: pass

            # Display Output
            try:
                while not output_queue.empty():
                    output_manager.process(output_queue.get_nowait())
            except queue.Empty: pass

            await asyncio.sleep(0.001)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            
    except KeyboardInterrupt:
        pass
    finally:
        print("\n🛑 Stopping...")
        prompt_manager.stop()
        receiver.stop()
        track.stop()
        input_manager.stop()
        output_manager.stop()
        await pc.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    asyncio.run(main())