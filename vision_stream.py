import cv2
import json
import time
import os
from ultralytics import YOLO

# Load the nano model (downloads automatically on first run, ~6MB)
print("[Optical Sensor] Booting YOLOv8n matrix...")
model = YOLO('yolov8n.pt')

VISION_LOG_PATH = "audio_cache/current_vision.json"
os.makedirs("audio_cache", exist_ok=True)

def start_visual_sweep():
    """Continuous 1-FPS background loop to monitor room objects."""
    print("[Optical Sensor] Accessing primary camera...")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("[Optical Sensor Error] Could not connect to the webcam.")
        return

    print("========================================")
    print("ARGUS OPTICAL MATRIX: ONLINE")
    print("Running at 1 Frame Per Second. Press CTRL+C to exit.")
    print("========================================")

    try:
        while True:
            # Clear the buffer and grab a fresh frame
            ret, frame = cap.read()
            if not ret:
                time.sleep(1)
                continue
                
            # Run the lightweight inference
            results = model.predict(frame, verbose=False)
            
            # Extract the names of the detected objects
            detected_objects = []
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    object_name = model.names[class_id]
                    detected_objects.append(object_name)
            
            # Count the occurrences of each object (e.g., {"person": 2, "cell phone": 1})
            object_counts = {}
            for obj in detected_objects:
                object_counts[obj] = object_counts.get(obj, 0) + 1
                
            # Write the current room state to the cache file
            with open(VISION_LOG_PATH, 'w') as f:
                json.dump(object_counts, f)
                
            # Sleep for 1 second to keep CPU usage extremely low
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n[Optical Sensor] Shutting down visual matrix.")
    finally:
        cap.release()
        
if __name__ == "__main__":
    start_visual_sweep()