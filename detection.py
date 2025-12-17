from ultralytics import YOLO
from pythonosc import udp_client
import argparse

n_of_persons = 0
pos_array = []

# Load a model
model = YOLO("yolo11n.pt")  # load an official model

# Predict with the model
results = model(source=0, stream=True, show=True)  # predict on Webcam

# setup OSC communication
parser = argparse.ArgumentParser()
parser.add_argument("--ip", default="127.0.0.1",
help="The ip of the OSC server")
parser.add_argument("--port", type=int, default=12000,
help="The port the OSC server is listening on")
args = parser.parse_args()

client = udp_client.SimpleUDPClient(args.ip, args.port)

# Access the results
for result in results:
    for box in result.boxes:
        if int(box.cls.item()) == 0:
            n_of_persons+=1
            x1, y1, x2, y2 = result.boxes.xyxyn[0]
            x = (x1 + x2) / 2
            y = (y1 + y2) / 2
            
    client.send_message("coord", (x.item(), y.item()))
    client.send_message("n_of_persons", int(n_of_persons))

    n_of_persons = 0
    pos_array = []