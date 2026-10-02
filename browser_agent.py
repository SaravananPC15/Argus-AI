import asyncio
from playwright.async_api import async_playwright

async def execute_browser_automation(instruction_task, url="https://duckduckgo.com"):
    """Asynchronously opens a browser and executes search commands on a privacy-respecting engine."""
    print(f"[Browser Core] Initializing browser for task: '{instruction_task}'")
    
    async with async_playwright() as p:
        # Launch with flags to disable the "Chrome is being controlled by automated software" banner
        browser = await p.chromium.launch(headless=False, args=["--start-maximized", "--disable-blink-features=AutomationControlled"])
        
        # Inject a realistic human User-Agent string to bypass basic bot detectors
        context = await browser.new_context(
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            
            if "search" in instruction_task.lower():
                # Bulletproof locators for DuckDuckGo
                search_selectors = [
                    "input[name='q']",
                    "input[id='searchbox_input']",
                    "input[type='text']"
                ]
                
                input_field = None
                
                for selector in search_selectors:
                    loc = page.locator(selector).first
                    if await loc.is_visible():
                        input_field = loc
                        break
                
                if input_field:
                    search_query = instruction_task.lower().split("search for")[-1].strip()
                    
                    # Humanized typing speed
                    await input_field.click()
                    await input_field.type(search_query, delay=120)
                    await page.keyboard.press("Enter")
                    
                    print("[Browser Core] Search executed successfully.")
                    await page.wait_for_timeout(6000) 
                else:
                    print("[Browser Core Error] Argus could not locate the search bar visually.")
                    return "I opened the browser, but I couldn't find the search bar."
                    
            await browser.close()
            return "Browser automation task completed successfully."
            
        except Exception as e:
            await browser.close()
            return f"Browser automation encountered an error: {str(e)}"