import cv2
import time
import asyncio
import requests
import numpy as np
import threading
import queue
import ctypes
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


# =========================
# SYPHON SENDER (Safe Bytes Version)
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
            # Create texture with BGRA8Unorm (Native Apple format)
            # We use BGRA because it matches the raw bytes we will send
            desc = Metal.MTLTextureDescriptor.texture2DDescriptorWithPixelFormat_width_height_mipmapped_(
                Metal.MTLPixelFormatBGRA8Unorm, width, height, False
            )
            
            # Managed mode is the most stable for CPU -> GPU uploads
            desc.setStorageMode_(Metal.MTLStorageModeManaged)
            desc.setUsage_(Metal.MTLTextureUsageShaderRead | Metal.MTLTextureUsageShaderWrite)
            
            self.texture = self.device.newTextureWithDescriptor_(desc)
            self.current_width = width
            self.current_height = height
            print(f"📐 Texture Recreated: {width}x{height}")
            return True
        except Exception as e:
            print(f"Texture error: {e}")
            return False
    
    def send_frame_bgr(self, frame_bgr):
        if not self.server:
            return
        
        try:
            # 1. Convert BGR -> BGRA
            # Adding the Alpha channel ensures 4 bytes per pixel alignment
            frame_bgra = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2BGRA)
            
            # 2. Flip Vertically
            frame_bgra = cv2.flip(frame_bgra, 0)
            
            height, width = frame_bgra.shape[:2]
            
            if not self._ensure_texture(width, height):
                return
            
            # 3. SAFETY STEP: Convert to immutable bytes
            # This copies the data to a safe location, preventing the SegFault
            raw_bytes = frame_bgra.tobytes()
            
            # 4. Upload
            region = Metal.MTLRegionMake2D(0, 0, width, height)
            bytes_per_row = width * 4
            
            self.texture.replaceRegion_mipmapLevel_withBytes_bytesPerRow_(
                region, 
                0, 
                raw_bytes, # Pass bytes object directly
                bytes_per_row
            )
            
            # 5. Synchronize (Required for Managed Mode)
            # This tells the GPU the CPU is done writing
            if hasattr(self.texture, 'buffer') and self.texture.buffer():
                 self.texture.didModifyRange_(Metal.NSMakeRange(0, self.texture.buffer().length()))

            # 6. Publish
            self.server.publish_frame_texture(self.texture)
            
        except Exception:
            pass 

# =========================
# PREVIEW WINDOW
# =========================

class CV2Output:
    def __init__(self, name):
        self.name = name
    
    def send_frame_bgr(self, frame):
        cv2.imshow(self.name, frame)

# =========================
# COMBINED OUTPUT MANAGER
# =========================

class OutputManager:
    def __init__(self, name):
        self.name = name
        self.syphon = SyphonSender(name) if SYPHON_AVAILABLE else None
        self.preview = CV2Output(f"Preview: {name}")
    
    def process(self, frame):
        if self.syphon:
            self.syphon.send_frame_bgr(frame)
        self.preview.send_frame_bgr(frame)
    
    def stop(self):
        if self.syphon and self.syphon.server:
            try: self.syphon.server.stop()
            except: pass
        cv2.destroyWindow(self.name)


# =========================
# INPUT TRACK (Webcam + YOLO -> Queue)
# =========================

class SegmentationVideoTrack(VideoStreamTrack):
    kind = "video"
    
    def __init__(self, queue_ref):
        super().__init__()
        self.queue_ref = queue_ref
        print("Loading YOLOv8...")
        self.model = YOLO("yolov8n-seg.pt")
        self.vid = cv2.VideoCapture(0)
        self.vid.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
        self.vid.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
        print("✅ Webcam ready")
    
    async def recv(self):
        pts, time_base = await self.next_timestamp()
        ret, frame = self.vid.read()
        
        if not ret:
            frame = np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 3), dtype=np.uint8)
        else:
            results = self.model(frame, conf=0.3, verbose=False, retina_masks=True)
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
# OUTPUT RECEIVER (HLS -> Queue)
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
    print("  DAYDREAM → SYPHON → TOUCHDESIGNER (SAFE BYTES)")
    print("============================================================")
    
    input_queue = queue.Queue(maxsize=2)
    output_queue = queue.Queue(maxsize=2)
    
    input_manager = OutputManager(SYPHON_INPUT_SERVER)
    output_manager = OutputManager(SYPHON_OUTPUT_SERVER)
    
    prompt = "cyberpunk neon lights futuristic"
    print(f"\n🎨 Prompt: {prompt}")
    
    try:
        r = requests.post(
            f"{DAYDREAM_BASE_URL}/streams",
            headers={"Authorization": f"Bearer {DAYDREAM_API_KEY}"},
            json={"prompt": prompt}, timeout=15
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"❌ API Error: {e}")
        return

    print(f"\n🌐 https://lvpr.tv?v={data['output_playback_id']}")
    
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

    receiver = DaydreamHLSReceiver(data['output_playback_id'], output_queue)
    receiver.start()
    
    print("\n✅ RUNNING! Ctrl+C to stop\n")
    
    try:
        while True:
            try:
                while not input_queue.empty():
                    input_manager.process(input_queue.get_nowait())
            except queue.Empty: pass

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
        receiver.stop()
        track.stop()
        input_manager.stop()
        output_manager.stop()
        await pc.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    asyncio.run(main())