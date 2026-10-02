import pyaudio
import numpy as np
import wave
import time
import asyncio
import io
import os
import sys
import json
import soundfile as sf
import schedule

if os.name == 'nt':
    import winsound
else:
    winsound = None  # Feature 11: winsound is Windows-only; guarded in play_activation_chime()

# Import your existing intelligence modules
from voice_engine import whisper_model, tts_model
from brain import process_command
from executor import run_local_command
import safety
import voice_id

# --- MICROPHONE SETTINGS ---
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000

# CLAP DETECTION THRESHOLD
CLAP_THRESHOLD = 18000 
WAKE_WORD = "argus"

p = pyaudio.PyAudio()

def play_activation_chime():
    """Plays a sleek double-beep to let you know Argus is listening."""
    if winsound is not None:
        winsound.Beep(800, 150)
        winsound.Beep(1200, 200)
    else:
        print("\a", end="", flush=True)  # terminal bell fallback on macOS/Linux

def record_audio_slice(seconds=2.0, output_filename="audio_cache/wake_slice.wav"):
    """Records a quick slice of audio from the laptop microphone."""
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    frames = []
    
    for _ in range(0, int(RATE / CHUNK * seconds)):
        data = stream.read(CHUNK)
        frames.append(data)
        
    stream.stop_stream()
    stream.close()
    
    wf = wave.open(output_filename, 'wb')
    wf.setnchannels(CHANNELS)
    wf.setsampwidth(p.get_sample_size(FORMAT))
    wf.setframerate(RATE)
    wf.writeframes(b''.join(frames))
    wf.close()
    return output_filename

def play_neural_audio(text):
    """Generates and plays the human neural voice directly through laptop speakers."""
    try:
        audio_tensor = tts_model.apply_tts(text=text, speaker='en_16', sample_rate=48000)
        sf.write("audio_cache/local_response.wav", audio_tensor.numpy(), 48000)
        # Feature 11: mplay32 is a Windows-only utility; fall back to
        # afplay (macOS) or aplay (Linux) elsewhere.
        if os.name == 'nt':
            os.system('start /min mplay32 /play /close audio_cache\\local_response.wav')
        elif sys.platform == 'darwin':
            os.system('afplay audio_cache/local_response.wav')
        else:
            os.system('aplay audio_cache/local_response.wav')
    except Exception as e:
        print(f"[Audio Error]: {e}")

async def handle_active_command():
    """The sequence that runs immediately after the clap AND wake word are detected."""
    print("[Argus is Listening... Speak your command.]")
    
    command_file = record_audio_slice(seconds=5.0, output_filename="audio_cache/active_command.wav")
    
    tanglish_primer = "Hello macha, epdi irukka? What are you doing bro? Seri, let's start."
    transcription = whisper_model.transcribe(command_file, fp16=False, initial_prompt=tanglish_primer)["text"].strip()
    print(f"[Heard Command]: {transcription}")
    
    if len(transcription) > 2:
        decision = await process_command(transcription, is_stream=False)
        action = decision.get("action")
        target = decision.get("target")
        
        # Comprehensive Action Router (Updated with new protocols)
        valid_actions = [
            "open_app", "system_command", "vision_task", "room_awareness", 
            "read_file", "run_script", "deep_research", "read_clipboard", 
            "ghost_type", "connect_app", "schedule_task", "git_push",
            "calendar", "send_email", "castellan_enroll", "git_archeology",
            "dataset_synth", "multi_agent_council", "syntax_guardian_check",
            "log_digest", "mind_map_export", "scraping_vanguard",
            "synthetic_anchor", "auto_documentation", "self_dev_status"
        ]
        
        if action in valid_actions:
            if safety.is_risky(action, target):
                # Feature 7: only the enrolled owner's voice can confirm a
                # risky action. If nobody's enrolled yet, is_owner() fails
                # open and this is just the normal confirmation prompt.
                if not voice_id.is_owner(command_file):
                    play_neural_audio("That's a restricted action, and I don't recognize your voice as my primary user. Request denied.")
                    return
                play_neural_audio(safety.confirmation_prompt(action, target))
                confirm_file = record_audio_slice(seconds=3.0, output_filename="audio_cache/confirm_slice.wav")
                confirm_text = whisper_model.transcribe(confirm_file, fp16=False)["text"].strip()
                if not safety.is_confirmation(confirm_text):
                    play_neural_audio("Okay, cancelled. No changes made.")
                    return
            result = run_local_command(action, target)
            print(f"[Action Output]: {result}")
            play_neural_audio(result)
        elif action == "casual_chat":
            print(f"[Argus]: {target}")
            play_neural_audio(target)

async def start_ambient_listener():
    """The continuous background loop monitoring room volume and background alarms."""
    print("========================================")
    print("ARGUS AMBIENT MATRIX: ONLINE")
    print("1. Clap loudly near the laptop.")
    print("2. Immediately say 'Argus'.")
    print("========================================")
    
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
    
    try:
        while True:
            # --- REAL-TIME CHRONOS SCHEDULER POLLING ---
            schedule.run_pending()
            
            chronos_path = "audio_cache/chronos_trigger.txt"
            if os.path.exists(chronos_path):
                try:
                    with open(chronos_path, 'r') as f:
                        trigger_cmd = f.read().strip()
                    os.remove(chronos_path)  # Flush immediately to prevent loops
                    
                    print(f"\n[CHRONOS OVERRIDE] Autonomous Time-Triggered Sequence Initiated...")
                    play_activation_chime()
                    
                    stream.stop_stream()
                    
                    # Route the dead-drop command directly into the brain
                    decision = await process_command(trigger_cmd, is_stream=False)
                    action = decision.get("action")
                    target = decision.get("target")
                    
                    valid_actions = [
                        "open_app", "system_command", "vision_task", "room_awareness", 
                        "read_file", "run_script", "deep_research", "read_clipboard", 
                        "ghost_type", "connect_app", "schedule_task", "git_push",
                        "calendar", "send_email", "castellan_enroll", "git_archeology",
                        "dataset_synth", "multi_agent_council", "syntax_guardian_check",
                        "log_digest", "mind_map_export", "scraping_vanguard",
                        "synthetic_anchor", "auto_documentation", "self_dev_status"
                    ]
                    
                    if action in valid_actions:
                        result = run_local_command(action, target)
                        print(f"[Chronos Output]: {result}")
                        play_neural_audio(result)
                    elif action == "casual_chat":
                        play_neural_audio(target)
                        
                    print("\n[Chronos sequence complete. Returning to Ambient Standby...]")
                    stream.start_stream()
                except Exception as e:
                    print(f"[Chronos Trigger Error]: {e}")
            # -------------------------------------------

            # --- REAL-TIME BACKGROUND SECURITY SCAN POLLING ---
            alert_path = "audio_cache/security_alert.json"
            if os.path.exists(alert_path):
                try:
                    with open(alert_path, 'r') as f:
                        alert_data = json.load(f)
                    os.remove(alert_path)
                    print("\n[CRITICAL OVERRIDE] Broadcasting External Security Alert...")
                    play_activation_chime()
                    play_neural_audio(alert_data["alert"])
                except Exception as e:
                    print(f"[Alert Read Error]: {e}")
            # -------------------------------------------
            
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)
            
            peak_volume = np.max(np.abs(audio_data))
            
            if peak_volume > CLAP_THRESHOLD:
                print("\n[Acoustic Spike Detected! Listening for wake word...]")
                
                wake_file = record_audio_slice(seconds=2.0, output_filename="audio_cache/wake_check.wav")
                
                tanglish_primer = "Hello macha, epdi irukka? What are you doing bro? Seri, let's start."
                text = whisper_model.transcribe(wake_file, fp16=False, initial_prompt=tanglish_primer)["text"].lower()
                
                if WAKE_WORD in text:
                    print(f"[Wake Word Confirmed: '{text}']")
                    play_activation_chime()
                    
                    stream.stop_stream()
                    await handle_active_command()
                    
                    print("\n[Returning to Ambient Standby...]")
                    stream.start_stream()
                else:
                    print(f"[False alarm. Heard: '{text}']")
                
            await asyncio.sleep(0.01)
            
    except KeyboardInterrupt:
        print("\n[Shutting down Ambient Matrix...]")
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    import database
    asyncio.run(database.init_db())
    asyncio.run(start_ambient_listener())