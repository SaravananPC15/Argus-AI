import ollama
from ddgs import DDGS  # <-- The updated import

def search_web(query, max_results=3):
    """Searches the web securely and returns a summary of the top results."""
    print(f"[Web Search] Searching for: '{query}'")
    try:
        with DDGS() as ddgs:
            # The new ddgs syntax
            results = list(ddgs.text(query, max_results=max_results))
            
        if not results:
            print("[Search Engine Debug] DuckDuckGo returned 0 results. (Possible rate limit block)")
            return "I searched the web but couldn't find any relevant information."
            
        search_snippets = []
        for i, r in enumerate(results, 1):
            # Using .get() prevents crashes if a field is missing
            search_snippets.append(f"Result {i}: {r.get('title', '')} - {r.get('body', '')}")
            
        print(f"[Search Engine Debug] Successfully fetched {len(results)} live snippets.")
        return "\n\n".join(search_snippets)
        
    except Exception as e:
        print(f"[Search Error] {e}")
        return "I encountered an error while trying to search the web."

# ... keep ai_summarize_search exactly the same ...
def ai_summarize_search(question, search_results):
    """Uses Llama 3.2 to synthesize search results into a natural spoken answer."""
    system_prompt = f"""
    You are Argus, a helpful AI assistant. 
    Answer the user's question using the real-time search results provided below.
    Synthesize the facts into a concise, direct, and conversational answer (2-4 sentences max).
    Speak naturally as an assistant. Do not use phrases like "According to the text" or "Based on the search results".
    
    SEARCH RESULTS:
    {search_results}
    """
    try:
        response = ollama.chat(model='llama3.2', messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': question}
        ])
        return response['message']['content'].strip()
    except Exception as e:
        print(f"[Synthesis Error] {e}")
        return "I found information on the web, but failed to synthesize the answer."