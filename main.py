import asyncio
from ears import listen_to_user, calibrate_microphone
from brain import process_command
from hands import execute_action
from voice import speak

WAKE_WORDS = ["argus", "august", "august 18", "august 18th", "argos"]


async def main():
    calibrate_microphone()
    speak("System initializing. Argus is online and ready.")

    while True:
        print("\n--- Waiting for Wake Word ---")
        user_text = listen_to_user()

        if user_text:
            text_lower = user_text.lower()

            if "stop argus" in text_lower:
                speak("Shutting down all systems.")
                break

            if any(word in text_lower for word in WAKE_WORDS):

                # Security bypassed. Argus instantly answers anyone.
                speak("Yes?")

                print("\n--- Listening for your command ---")
                command_text = listen_to_user()

                if command_text:
                    # process_command is async (brain.py), so it must be awaited
                    decision = await process_command(command_text)
                    execute_action(decision)
                else:
                    speak("I didn't quite catch that.")


if __name__ == "__main__":
    asyncio.run(main())
