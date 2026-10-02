import ollama

print("Connecting to Ollama server...")
print("Downloading qwen2.5:0.5b (This might take a minute or two, please wait...)")

try:
    # This tells the Python library to download the model directly
    ollama.pull('qwen2.5:0.5b')
    print("Download complete! The model is ready to use.")
except Exception as e:
    print(f"An error occurred: {e}")