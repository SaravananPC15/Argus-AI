import pyttsx3

def speak(text):
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    
    # Using your selected Voice 0
    engine.setProperty('voice', voices[0].id)
    engine.setProperty('rate', 160) 
    engine.setProperty('volume', 1.0) 
    
    print(f"\nArgus: {text}")
    engine.say(text)
    engine.runAndWait()