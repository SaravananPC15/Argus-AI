import os
import PyPDF2
import docx
import ollama

DOCS_DIR = "documents"

# Ensure the drop-zone exists
if not os.path.exists(DOCS_DIR):
    os.makedirs(DOCS_DIR)

def extract_text(filename):
    """Finds the file in the documents folder and extracts the raw text."""
    filepath = None
    # Look for a file that matches what the user asked for
    for file in os.listdir(DOCS_DIR):
        if filename.lower() in file.lower():
            filepath = os.path.join(DOCS_DIR, file)
            break
            
    if not filepath:
        return None, f"I couldn't find a document matching '{filename}' in my database."

    ext = os.path.splitext(filepath)[1].lower()
    text = ""

    try:
        if ext == ".pdf":
            with open(filepath, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                # Read up to the first 5 pages to prevent RAM overload
                for page in reader.pages[:5]:
                    text += page.extract_text() + "\n"
        elif ext == ".docx":
            doc = docx.Document(filepath)
            for para in doc.paragraphs:
                text += para.text + "\n"
        elif ext == ".txt":
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
        else:
            return None, "I do not have the decoders for that specific file format."
        
        # Truncate text if it is massive (keeping it under ~2000 words)
        words = text.split()
        if len(words) > 2000:
            text = " ".join(words[:2000]) + "... [Text truncated for memory safety]"

        return filepath, text
    except Exception as e:
        print(f"[Scribe Error] {e}")
        return None, "I encountered a physical error while trying to read the file."

def summarize_document(filename):
    """Extracts text and uses Llama 3.2 to summarize it."""
    filepath, text = extract_text(filename)
    
    if not filepath:
        return text # Returns the error message

    print(f"\n[Scribe] Successfully ingested: {filepath}")
    print("[Scribe] Synthesizing summary...\n")
    
    system_prompt = """
    You are Argus, a highly intelligent AI assistant.
    Read the provided document text and give a concise, high-level summary.
    Highlight the core subject, main arguments, and key takeaways.
    Keep your response conversational, as you will be speaking it out loud. Limit it to 3 to 4 sentences.
    """
    
    try:
        response = ollama.chat(model='llama3.2', messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': f"DOCUMENT TEXT:\n{text}"}
        ])
        return response['message']['content'].strip()
    except Exception as e:
        print(f"[Scribe AI Error] {e}")
        return "I read the document, but my cognitive core failed to summarize it."