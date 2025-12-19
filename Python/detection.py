from ultralytics import YOLO
from pythonosc import udp_client
import argparse

MAX_PERSONS = 6

INTERPOLATION_STEP = 0.05
def compute_entropy_level(old, new):
    if old == new:
        return new
    elif new>old:
        return old + INTERPOLATION_STEP
    else:
        return old - INTERPOLATION_STEP

n_old = 0
n_new = 0
pos_array = []

# Load a model
model = YOLO("yolo11n.pt")  # load an official model

# Predict with the model
results = model(source=0, stream=True, show=True)  # predict on Webcam

# Setup OSC communication
parser = argparse.ArgumentParser()
parser.add_argument("--ip", default="127.0.0.1",
help="The ip of the OSC server")
parser.add_argument("--port", type=int, default=12000,
help="The port the OSC server is listening on")
args = parser.parse_args()

client = udp_client.SimpleUDPClient(args.ip, args.port)

parser_scd = argparse.ArgumentParser()
parser_scd.add_argument("--ip", default="127.0.0.1",
help="The ip of the OSC server")
parser_scd.add_argument("--port", type=int, default=57120,
help="The port the OSC server is listening on")
args_scd = parser_scd.parse_args()

client_scd = udp_client.SimpleUDPClient(args_scd.ip, args_scd.port)

# Loop on the predictions
for result in results:
    for box in result.boxes:
        if int(box.cls.item()) == 0:
            x1, y1, x2, y2 = box.xyxyn[0]
            x = (x1 + x2) / 2
            y = (y1 + y2) / 2
            pos_array.append(x.item())  
            pos_array.append(y.item()) 
            
            n_new+=1
            
    # Smoothing of entropy level
    entropy_level = compute_entropy_level(new=n_new, old=n_old)   
    entropy_level = round(entropy_level, 2) 
    if entropy_level > MAX_PERSONS: entropy_level = MAX_PERSONS
    
    # Padding of pos array
    if len(pos_array) < MAX_PERSONS *  2:
        pos_array.extend([-1.0] * (MAX_PERSONS *  2 - len(pos_array)))
    else:
        pos_array = pos_array[:MAX_PERSONS *  2]  
        
    # Sending OSC message  
    client.send_message("/coord", pos_array)
    client.send_message("/entropy_level", float(entropy_level))

     
    client_scd.send_message("/entropy_level", float(entropy_level))
    print(entropy_level)

    # Update state values
    n_old = entropy_level
    n_new = 0
    pos_array = []
