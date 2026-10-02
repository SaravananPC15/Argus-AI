import speech_recognition as sr

recognizer = sr.Recognizer()
recognizer.dynamic_energy_threshold = False

def calibrate_microphone():
    """Runs exactly once at system startup to profile room noise."""
    with sr.Microphone() as source:
        print("Calibrating background noise for 2 seconds... Please remain quiet.")
        recognizer.adjust_for_ambient_noise(source, duration=2)
        print(f"Calibration complete. Energy threshold set to: {recognizer.energy_threshold}")

def listen_to_user():
    """Listens instantly without recalibrating."""
    with sr.Microphone() as source:
        # Static filter
        recognizer.energy_threshold = 1500 
        
        print("Listening...")
        try:
            audio_data = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            
            text = recognizer.recognize_whisper(audio_data, model="base", language="english")
            clean_text = text.strip()
            
            if not clean_text:
                return None
                
            print(f"Heard: {clean_text}")
            return clean_text
            
        except sr.WaitTimeoutError:
            return None 
        except sr.UnknownValueError:
            return None
        except Exception:
            return None