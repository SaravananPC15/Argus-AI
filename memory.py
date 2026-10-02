import json
import os
import ollama

MEMORY_FILE = "memory.json"

def load_memories():
    """Opens the filing cabinet and reads all saved facts."""
    if not os.path.exists(MEMORY_FILE):
        return []
    with open(MEMORY_FILE, "r") as f:
        return json.load(f)

def save_memory(fact):
    """Writes a new fact to the filing cabinet."""
    memories = load_memories()
    memories.append(fact)
    with open(MEMORY_FILE, "w") as f:
        json.dump(memories, f, indent=4)

def ask_memory(question):
    """Reads all memories and uses the LLM to answer the user's question."""
    memories = load_memories()
    if not memories:
        return "My memory banks are currently empty."

    # Turn the list of memories into one giant block of text
    memory_text = "\n".join(memories)
    
    # We create a highly restrictive prompt just for the Librarian
    system_prompt = f"""
    You are a strict data retrieval AI. 
    Answer the user's question using ONLY the provided FACTS.
    If the exact answer is not explicitly written in the FACTS below, you MUST output exactly this phrase: "I do not have a memory of that."
    Do not use outside knowledge. Do not guess. Do not make up answers.
    
    FACTS:
    {memory_text}
    """ 
    try:
        response = ollama.chat(model='llama3.2', messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': question}
        ])
        return response['message']['content'].strip()
    except Exception as e:
        print(f"[Memory Error] {e}")
        return "I encountered an error accessing my memory core."