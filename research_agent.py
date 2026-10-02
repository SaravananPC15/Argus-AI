import os
from ddgs import DDGS  # duckduckgo_search was renamed to ddgs; kept consistent with search_engine.py
import requests
from bs4 import BeautifulSoup
import ollama
from fpdf import FPDF
import model_router

def run_deep_dive(topic):
    print(f"\n[Deep Dive Matrix] Initiating autonomous web extraction for: {topic}")
    
    # Ensure the vault exists to store the PDF
    os.makedirs("secure_vault", exist_ok=True)
    
    # 1. Search the Web (Silent execution)
    try:
        with DDGS() as ddgs:
            search_results = list(ddgs.text(topic, max_results=3))
    except Exception as e:
        print(f"[Search Error]: {e}")
        return "Macha, my external web ping failed. Check the network connection."

    if not search_results:
        return "I scoured the grid but couldn't find any actionable intel on that target."

    compiled_research = []
    
    # 2. Scrape and Summarize
    for res in search_results:
        url = res['href']
        title = res['title']
        print(f"[Scraping Target] {title}")
        
        try:
            # Fetch the page with a strict timeout so he doesn't hang
            page = requests.get(url, timeout=10)
            soup = BeautifulSoup(page.text, 'html.parser')
            
            # Extract paragraph text and cap it at 3000 chars to protect your 8GB RAM
            paragraphs = soup.find_all('p')
            text_content = " ".join([p.text for p in paragraphs])[:3000] 
            
            if len(text_content) > 100:
                print(f"[Brain] Processing intelligence from {url}...")
                prompt = f"You are a tactical analyst. Summarize this raw intel about '{topic}' into a single, highly dense, factual paragraph. Do not use conversational filler.\n\nRaw Intel:\n{text_content}"
                
                summary_response = ollama.chat(model=model_router.select_model("deep_research"), messages=[{'role': 'system', 'content': prompt}])
                compiled_research.append({
                    "title": title, 
                    "url": url, 
                    "summary": summary_response['message']['content'].strip()
                })
        except Exception as e:
            print(f"[Extraction Failed] {url} - Skipping to next target.")

    if not compiled_research:
        return "I breached the targets, but the data was encrypted or unreadable. Research failed."

    # 3. Compile the PDF Dossier
    print("[Deep Dive Matrix] Compiling final tactical dossier...")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=14, style="B")
    pdf.cell(200, 10, txt=f"ARGUS TACTICAL DOSSIER: {topic.upper()}", ln=True, align='C')
    pdf.ln(10)

    for item in compiled_research:
        pdf.set_font("Arial", style="B", size=12)
        # Encode/Decode trick to prevent Windows Unicode crashing during PDF generation
        clean_title = item['title'].encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 10, txt=f"SOURCE: {clean_title}")
        
        pdf.set_font("Arial", size=9)
        pdf.set_text_color(0, 0, 255) # Blue link
        pdf.multi_cell(0, 10, txt=item['url'])
        
        pdf.set_text_color(0, 0, 0) # Black text
        pdf.set_font("Arial", size=11)
        clean_summary = item['summary'].encode('latin-1', 'replace').decode('latin-1')
        pdf.multi_cell(0, 8, txt=clean_summary)
        pdf.ln(8)

    filename = f"secure_vault/Dossier_{topic.replace(' ', '_')[:15]}.pdf"
    pdf.output(filename)
    
    return f"Research complete, macha. The tactical dossier on {topic} has been generated and locked in your secure vault."