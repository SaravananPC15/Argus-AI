import asyncio
from brain import process_command
from hands import execute_action

print("=== Argus Text Diagnostic Mode ===")
print("Type 'exit' to quit.\n")

while True:
    # 1. Get input from your keyboard instead of the microphone
    user_text = input("You: ")

    if user_text.lower() in ['exit', 'quit', 'stop']:
        print("Shutting down diagnostic mode.")
        break

    if user_text.strip():
        # 2. Feed your text directly into the Brain
        # process_command is async (brain.py), so it must be run via asyncio
        decision = asyncio.run(process_command(user_text))

        # 3. Feed the Brain's JSON directly into the Hands
        execute_action(decision)
