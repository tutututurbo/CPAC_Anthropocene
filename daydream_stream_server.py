import requests
import asyncio
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

# =========================
# CONFIG
# =========================

DAYDREAM_API_KEY = "sk_4FFD4vzMSn4AEhjEAZJqDn9h7rAbaRG7vGjBazaesW6bMtr7yukcbzVmq4Pwofft"  # Metti la tua chiave
DAYDREAM_BASE_URL = "https://api.daydream.live/v1"

# =========================
# CREATE STREAM
# =========================

def create_stream(prompt):
    headers = {
        "Authorization": f"Bearer {DAYDREAM_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "prompt": prompt,
    }
    
    response = requests.post(
        f"{DAYDREAM_BASE_URL}/streams",
        headers=headers,
        json=payload,
        timeout=60
    )
    response.raise_for_status()
    return response.json()

# =========================
# WHIP CONNECTION
# =========================

async def send_webcam_to_whip(whip_url):
    pc = RTCPeerConnection()
    
    # Mac webcam - usa avfoundation
    # "0:none" = prima webcam, no audio
    # "default:none" = webcam default, no audio
    player = MediaPlayer('0:none', format='avfoundation', options={
        'video_size': '640x480',
        'framerate': '30'
    })
    
    if player.video:
        pc.addTrack(player.video)
        print("✅ Webcam found!")
    else:
        print("❌ No webcam video track")
        return None
    
    # Crea offer
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
    # Invia a WHIP endpoint
    headers = {
        "Content-Type": "application/sdp",
    }
    
    response = requests.post(
        whip_url,
        headers=headers,
        data=pc.localDescription.sdp,
        timeout=30
    )
    
    if response.status_code == 201:
        answer = RTCSessionDescription(sdp=response.text, type="answer")
        await pc.setRemoteDescription(answer)
        print("✅ Connected to Daydream!")
        return pc
    else:
        print(f"❌ WHIP error: {response.status_code}")
        print(response.text)
        return None

# =========================
# MAIN
# =========================

async def main():
    print("=" * 50)
    print("WEBCAM TO DAYDREAM")
    print("=" * 50)
    
    prompt = "cyberpunk style, neon lights, futuristic"
    print(f"\nCreating stream with prompt: {prompt}")
    
    # Crea stream
    stream_data = create_stream(prompt)
    
    stream_id = stream_data["id"]
    whip_url = stream_data["whip_url"]
    playback_id = stream_data["output_playback_id"]
    player_url = f"https://lvpr.tv?v={playback_id}"
    
    print(f"""
✅ Stream created!

Stream ID: {stream_id}
WHIP URL: {whip_url}

🌐 Watch output at:
{player_url}
""")
    
    print("Connecting webcam...")
    
    pc = await send_webcam_to_whip(whip_url)
    
    if pc:
        print("\n✅ Streaming! Open the player URL in your browser.")
        print("Press Ctrl+C to stop.\n")
        
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping...")
            await pc.close()

if __name__ == "__main__":
    asyncio.run(main())