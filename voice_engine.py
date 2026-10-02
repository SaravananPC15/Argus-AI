import soundfile as sf
import os
import base64
import torch
import whisper

print("[Voice Engine] Booting Neural Acoustic Models. Please wait...")

# 1. Load Whisper (The Ears)
whisper_model = whisper.load_model("base")

# 2. Load Silero TTS (The Human Mouth)
# This will download the offline voice model the first time you run it.
device = torch.device('cpu')
tts_model, _ = torch.hub.load(repo_or_dir='snakers4/silero-models',
                              model='silero_tts',
                              language='en',
                              speaker='v3_en')

def transcribe_audio(file_path):
    """Converts the audio file received from the phone into text."""
    try:
        # --- TANGLISH PRIMER INJECTED HERE ---
        tanglish_primer = "Hello macha, epdi irukka? What are you doing bro? Seri, let's start."
        result = whisper_model.transcribe(file_path, initial_prompt=tanglish_primer)
        return result['text'].strip()
    except Exception as e:
        print(f"[Whisper Error]: {e}")
        return ""

def generate_speech_base64(text, output_filename="audio_cache/response.wav"):
    """Generates hyper-realistic human speech using neural networking."""
    try:
        # Clean text for the voice model (remove asterisks or weird symbols)
        clean_text = text.replace("*", "").replace("#", "")
        
        # 'en_16' and 'en_14' are excellent, deep male human voices in Silero.
        sample_rate = 48000
        speaker = 'en_16' 
        
        # Generate the audio tensor
        audio_tensor = tts_model.apply_tts(text=clean_text,
                                           speaker=speaker,
                                           sample_rate=sample_rate)
        
        # Save to a physical .wav file using soundfile
        sf.write(output_filename, audio_tensor.numpy(), 48000, format='WAV')
        
        # Encode for web streaming to your phone
        with open(output_filename, "rb") as audio_file:
            encoded_string = base64.b64encode(audio_file.read()).decode('utf-8')
            return encoded_string
            
    except Exception as e:
        print(f"[Neural TTS Error]: {e}")
        return None