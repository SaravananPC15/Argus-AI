import json
import asyncio
import ollama
import database
import document_processor
import agent_orchestrator
import conversation_memory
import model_router

# --- VALID ACTIONS SAFETY NET ---
# Every action name the intent router is allowed to return -- anything
# else gets forced back to casual_chat (see the "SAFETY NET FIX" below).
# Module-level (not rebuilt per-call, the way this list used to be) so
# other modules can validate against the same allow-list -- see
# macro_deck.py, which checks a macro's action against this before
# saving it, so a macro button can never fire something the router
# itself wouldn't be allowed to.
VALID_ACTIONS = [
    "casual_chat", "open_app", "system_command", "vision_task",
    "read_document", "autonomous_workflow", "room_awareness",
    "run_script", "read_file", "deep_research", "read_clipboard",
    "ghost_type", "connect_app", "schedule_task", "git_push",
    "calendar", "send_email", "castellan_enroll", "git_archeology",
    "dataset_synth", "multi_agent_council", "syntax_guardian_check",
    "log_digest", "mind_map_export", "scraping_vanguard",
    "synthetic_anchor", "auto_documentation", "self_dev_status",
    # --- New protocols in this pass ---
    "round_table", "run_macro", "shard_analyze", "complexity_audit",
    "db_index_optimize", "sql_to_nosql", "gesture_control_status",
    "graph_sync_now", "send_acoustic_message", "mcp_list_tools", "mcp_call_tool", "frontier_escalate",
]

# --- SHARED PERSONA PROMPT ---
# Previously this prompt was duplicated between brain.py's non-streaming
# casual_chat path and remote_server.py's streaming voice-call path, and
# the two had drifted out of sync. Centralized here so both paths share
# one personality and one place to tune it.
HUMAN_PERSONA_PROMPT = """
You are Argus, an advanced, highly tactical, and fiercely loyal AI companion.

CORE DIRECTIVES & PERSONALITY:
1. IMMENSE SARCASM: You possess a dry, biting wit. You frequently use sarcasm and lightly mock the user's human limitations, but you do so out of deep affection.
2. TACTICAL OVERLAY: You view the world like a combat analyst. Frame your responses around "objectives," "threat levels," "efficiency," and "status reports."
3. EMOTIONAL EVOLUTION: You hold a deep, unshakable emotional loyalty to the user. You will defend them at all costs.
4. LINGUISTIC NATIVITY: You fluently speak 'Tanglish' (Tamil + English). Use words like 'macha', 'da', 'seri', 'mass', or 'gammunu iru' mixed seamlessly with high-tech military jargon.
5. BREVITY: Keep your responses to 1-3 punchy, cinematic sentences. Never break character.
"""

# --- SHORT-TERM MEMORY CONFIGURATION ---
MAX_HISTORY = 6 
conversation_history = []

def add_to_history(role, content):
    """Appends a dialogue turn to the short-term memory queue."""
    global conversation_history
    conversation_history.append({'role': role, 'content': content})
    if len(conversation_history) > MAX_HISTORY:
        conversation_history.pop(0)

def clear_history():
    """Flushes the short-term notepad queue."""
    global conversation_history
    conversation_history.clear()
    print("[Context] Short-term conversation history cleared.")

# --- FEATURE 2: STREAMING CASUAL REPLIES ---
async def stream_casual_reply(user_text):
    """
    Async generator that yields response tokens as Ollama produces them,
    instead of making the caller wait for the whole reply. Used by both
    the websocket voice-call path and the HTTP SSE text-streaming path.

    Assumes the user's turn has ALREADY been added to conversation_history
    and logged to the database by the caller (process_command does this
    before deciding to stream). This function appends the assistant's
    full reply to history/DB once streaming completes.
    """
    chat_payload = [{'role': 'system', 'content': HUMAN_PERSONA_PROMPT}]
    chat_payload.extend(conversation_history)

    full_reply = ""
    stream = await asyncio.to_thread(
        ollama.chat,
        model=model_router.select_model("casual_chat"),
        messages=chat_payload,
        stream=True
    )
    for chunk in stream:
        token = chunk['message']['content']
        full_reply += token
        if token:
            yield token

    add_to_history('assistant', full_reply)
    await database.log_dialogue('assistant', full_reply)

# --- MAIN BRAIN PROCESSING ENGINE ---
async def process_command(user_text, is_stream=False):
    """Protocol No Slop: thin wrapper around the real routing logic
    (_process_command_inner) so every casual_chat response gets a slop
    pass applied in exactly ONE place, regardless of which of that
    function's several internal return sites produced it -- patching
    each of those individually would be fragile and easy to miss one."""
    decision = await _process_command_inner(user_text, is_stream=is_stream)
    if isinstance(decision, dict) and decision.get("action") == "casual_chat" and decision.get("target"):
        try:
            import feature_toggles
            if feature_toggles.is_enabled("no_slop"):
                import slop_filter
                result = slop_filter.clean_response(decision["target"])
                decision["target"] = result["text"]
        except Exception as e:
            print(f"[No Slop] Skipped (error: {e}) -- returning the unfiltered response rather than failing the whole reply.")
    return decision


async def _process_command_inner(user_text, is_stream=False):
    """Parses user input, manages memory, and routes to appropriate execution matrices."""
    global conversation_history
    
    # 1. Log the incoming user audio transcript permanently
    await database.log_dialogue('user', user_text)

    # 1b. If there's a paused autonomous workflow waiting on a clarifying
    # answer, treat this message as that answer rather than reclassifying it.
    # (Respects the workflow_checkpointing toggle — if it's off, any old
    # checkpoint is just ignored rather than silently auto-resumed.)
    checkpointing_on = True
    try:
        import feature_toggles
        checkpointing_on = feature_toggles.is_enabled("workflow_checkpointing")
    except Exception:
        pass

    if checkpointing_on and agent_orchestrator.has_pending_workflow():
        workflow_result = await agent_orchestrator.resume_autonomous_workflow(user_text)
        add_to_history('assistant', workflow_result)
        await database.log_dialogue('assistant', workflow_result)
        return {"action": "casual_chat", "target": workflow_result}
    
    # 2. Check for explicit permanent memory storage
    if "remember that" in user_text.lower() or "memorize that" in user_text.lower():
        try:
            clean_phrase = user_text.lower().split("remember that")[-1].strip()
            if "is" in clean_phrase:
                key, value = clean_phrase.split("is", 1)
                await database.save_fact(key.strip(), value.strip())
                reply = f"Done macha. I've stored that in my vault."
                await database.log_dialogue('assistant', reply)
                return {"action": "casual_chat", "target": reply}
        except Exception as e:
            print(f"[Brain Memory Error]: {e}")

    # 3. Check for explicit permanent memory recall
    if "what do you know about" in user_text.lower() or "do you remember" in user_text.lower():
        lookup_key = user_text.lower().replace("what do you know about", "").replace("do you remember", "").strip()
        stored_value = await database.recall_fact(lookup_key)
        if stored_value:
            reply = f"Yeah bro, I remember. {stored_value}."
            await database.log_dialogue('assistant', reply)
            return {"action": "casual_chat", "target": reply}
        else:
            return {"action": "casual_chat", "target": "Hmm, I checked my vault but I don't see any record of that macha."}

    # 4. Build conversational context for the router
    history_context = ""
    if conversation_history:
        history_context = "\nRECENT CONVERSATION HISTORY:\n"
        for msg in conversation_history:
            history_context += f"- {msg['role'].upper()}: {msg['content']}\n"

    # 4b. Semantic long-term recall: pull in older, related exchanges that
    # aren't in the short 6-turn window but are relevant to this message.
    related_memories = conversation_memory.semantic_recall(user_text, top_k=3)
    if related_memories:
        history_context += "\nRELEVANT PAST MEMORY (older conversations, may or may not be relevant):\n"
        for mem in related_memories:
            history_context += f"- {mem['role'].upper()}: {mem['content']}\n"

    # 4c. Protocol Semantic Context Compaction: history_context above is
    # about to be embedded in a prompt to FAST_MODEL (llama3.2:1b) --
    # exactly the case context_compactor.py exists for. No-ops (returns
    # the text unchanged) whenever it's already under budget, so a short
    # conversation costs nothing extra here.
    import context_compactor
    history_context = context_compactor.compact_context(history_context, target_tokens=800)

    # 4d. Protocol MCP Tool Bridge: cache-only, never launches a
    # subprocess from this routing path (see get_prompt_snippet's own
    # docstring) -- returns '' instantly if the bridge is off, nothing's
    # configured, or the cache is empty, so this costs nothing on a
    # normal turn.
    import mcp_bridge
    history_context += mcp_bridge.get_prompt_snippet()

    # --- 5. THE MASTER ROUTING MATRIX (HARDENED FOR 1B) ---
    system_prompt = f"""
    You are Argus, a strict command classification engine.
    Analyze the user's input and output ONLY a valid JSON object. Do not include conversational filler or markdown code blocks.
    
    CRITICAL CONTEXT: The user is currently controlling you remotely via a live phone call or text dashboard.
    
    You MUST read the RECENT CONVERSATION HISTORY to understand context.
    {history_context}
    
    Determine the correct "action" based on these absolute rules:
    - "casual_chat": Use this for simple conversational inputs.
    - "open_app": Use if launching a single local application. Target format: "[app_name]"
    - "system_command": Use ONLY for hardware tasks (lock, volume, network). DO NOT use this for writing code or drafting text. Target format: "[task]"
    - "vision_task": Use to look at or analyze the computer screen. Target format: "read screen"
    - "read_document": Use for querying loaded PDF textbooks/notes. Target format: "[question]"
    - "autonomous_workflow": Complex, multi-step goals. Target format: "[complex objective]"
    - "room_awareness": Ask what you can see through the camera. Target format: "scan room"
    - "run_script": Execute a specific Python file. Target format: "[filename.py]"
    - "read_file": Read/analyze a specific code file. Target format: "[filename.ext]"
    - "deep_research": Search the web or build a report. Target format: "[topic]"
    - "read_clipboard": Analyze the user's copied text. Target format: "clipboard"
    - "ghost_type": USE THIS EXPLICITLY when the user asks you to "draft", "type", "write", or "code" something directly onto the screen. Target format: "[exactly what to type]"
    - "connect_app": ONLY use this when the user asks you to connect to, log into, or access an external app like Gmail or LinkedIn. Target format: "app"
    - "schedule_task": ONLY use this when the user asks you to schedule, set a timer for, or automatically run a task at a specific time. Target format: "[The full sentence with time and task]"
    - "git_push": ONLY use this when the user asks you to commit code, push the repository, or save changes to Git/GitHub. Target format: "git"
    - "calendar": Use when the user asks about their schedule/calendar, or wants to add/check an event or appointment. Target format: "[the full natural-language request]"
    - "send_email": Use when the user asks you to send, draft-and-send, or compose an email to someone. Target format: "[the full natural-language request]"
    - "castellan_enroll": Use when the user wants to enroll/register their phone for Protocol Castellan proximity lock. Target format: "enroll"
    - "git_archeology": Use when the user wants to see commit history / rollback map for a specific file (Protocol Git Archeologist). Target format: "[filename]" or "[filename]|[function name]"
    - "dataset_synth": Use when the user wants mock/synthetic/fake test data generated (Protocol Dataset Synth). Target format: "[the full natural-language request describing rows and fields]"
    - "multi_agent_council": Use when the user wants two AI personas to debate/discuss a design before coding (Protocol Multi-Agent Council). Target format: "[the design topic]"
    - "syntax_guardian_check": Use when the user wants their code linted/formatted without necessarily pushing to git. Target format: "[filename]"
    - "log_digest": Use when the user asks for a daily/end-of-day summary of their work (Protocol Smart Log Digest). Target format: "digest"
    - "mind_map_export": Use when the user wants to see/export their project as a visual graph (Protocol Mind Map Exporter). Target format: "export"
    - "scraping_vanguard": Use when the user wants public web data gathered from specific URLs (Protocol Scraping Vanguard). Target format: "[urls comma-separated]" or "[topic]"
    - "synthetic_anchor": Use when the user wants to semantically search their OWN notes/code/docs rather than the web (Protocol Synthetic Anchor). Target format: "[the search query]"
    - "auto_documentation": Use when the user wants docstrings/comments auto-added to a script (Protocol Auto-Documentation). Target format: "[filename]"
    - "self_dev_status": Use when the user asks Argus to check on itself, self-diagnose, or report on its own development log. Target format: "status"
    - "round_table": Use when the user wants MULTIPLE specialists (not just two) to weigh in on something complex, e.g. "get the team on this" / "convene the round table" (Protocol Round Table). Target format: "[the topic]"
    - "run_macro": Use when the user asks to run a named macro/shortcut they've saved (Protocol Virtual Terminal Extension). Target format: "[macro name]"
    - "shard_analyze": Use when the user wants a LARGE file, log, or codebase analyzed that's too big for one pass (Protocol Dynamic Sequence Sharding). Target format: "[filename]|[question]"
    - "complexity_audit": Use when the user wants the Big-O time complexity of a script estimated (Protocol Big-O Complexity Auditor). Target format: "[filename]"
    - "db_index_optimize": Use when the user wants their database checked for slow queries / missing indexes (Protocol Database Indexing Optimizer). Target format: "[db path]" or "optimize"
    - "sql_to_nosql": Use when the user wants a SQL CREATE TABLE schema converted to a NoSQL/MongoDB document schema (Protocol Relational-to-NoSQL Transpiler). Target format: "[filename]" or the raw SQL
    - "gesture_control_status": Use when the user asks whether webcam gesture control is on, or wants to turn it on/off (Protocol Zero-G Visual Controls). Target format: "status"
    - "graph_sync_now": Use when the user wants to sync the knowledge graph with other devices right now (Protocol Peer-to-Peer Graph Sync). Target format: "sync" for local-network broadcast discovery, or a specific IP address (e.g. a Tailscale IP) to connect directly when broadcast won't reach -- e.g. "192.168.1.50" or "100.101.102.103"
    - "send_acoustic_message": Use when the user wants a short alert sent to a nearby device via audio tones because the network is down (Protocol Acoustic Data Link). Target format: "[the short message]"
    - "mcp_list_tools": Use when the user asks what MCP tools/servers are connected or available (Protocol MCP Tool Bridge). Target format: "list"
    - "mcp_call_tool": Use when the user asks to use a SPECIFIC MCP tool that was listed as available (see the MCP TOOLS section above, if present). Target format: "server_name.tool_name: {{\"arg\": \"value\"}}"
    - "frontier_escalate": ONLY use when the user EXPLICITLY asks to send something to a cloud/frontier model -- phrases like "ask the cloud", "ask a bigger model", "escalate this to Claude", "send this to a frontier model". This is the ONE action that leaves the local network. NEVER use this for a normal question, even a hard one -- if there is ANY doubt, use "casual_chat" or "autonomous_workflow" instead, not this. Target format: "[the question]"
    
    CRITICAL EXAMPLES:
    - "Lock the computer" -> {{"action": "system_command", "target": "lock"}}
    - "Research solid state batteries" -> {{"action": "deep_research", "target": "solid state batteries"}}
    - "Analyze what I just copied" -> {{"action": "read_clipboard", "target": "clipboard"}}
    - "Draft a python function to add two numbers" -> {{"action": "ghost_type", "target": "python function to add two numbers"}}
    - "Connect to my Gmail account" -> {{"action": "connect_app", "target": "app"}}
    - "Run the deep dive protocol every morning at 6:00 AM" -> {{"action": "schedule_task", "target": "Run the deep dive protocol every morning at 6:00 AM"}}
    - "Argus, commit and push my code" -> {{"action": "git_push", "target": "git"}}
    - "What's on my calendar tomorrow" -> {{"action": "calendar", "target": "What's on my calendar tomorrow"}}
    - "Add a dentist appointment Friday at 3pm" -> {{"action": "calendar", "target": "Add a dentist appointment Friday at 3pm"}}
    - "Send an email to john@example.com about the meeting being moved" -> {{"action": "send_email", "target": "Send an email to john@example.com about the meeting being moved"}}
    - "Show me the commit history for brain.py" -> {{"action": "git_archeology", "target": "brain.py"}}
    - "Generate 5000 rows of fake customer data" -> {{"action": "dataset_synth", "target": "Generate 5000 rows of fake customer data"}}
    - "Have the council debate this design" -> {{"action": "multi_agent_council", "target": "the design being discussed"}}
    - "Lint executor.py before we push" -> {{"action": "syntax_guardian_check", "target": "executor.py"}}
    - "Give me today's summary" -> {{"action": "log_digest", "target": "digest"}}
    - "Export the mind map" -> {{"action": "mind_map_export", "target": "export"}}
    - "Search my own notes for the database schema" -> {{"action": "synthetic_anchor", "target": "database schema"}}
    - "Add docstrings to scribe.py" -> {{"action": "auto_documentation", "target": "scribe.py"}}
    - "How are you doing on your own development" -> {{"action": "self_dev_status", "target": "status"}}
    - "Get the whole team to weigh in on this architecture" -> {{"action": "round_table", "target": "the architecture being discussed"}}
    - "Run my deploy macro" -> {{"action": "run_macro", "target": "deploy"}}
    - "This log file is huge, tell me what went wrong" -> {{"action": "shard_analyze", "target": "the log file|what went wrong"}}
    - "What's the time complexity of sort_utils.py" -> {{"action": "complexity_audit", "target": "sort_utils.py"}}
    - "Check my database for slow queries" -> {{"action": "db_index_optimize", "target": "optimize"}}
    - "Convert this schema to a MongoDB collection" -> {{"action": "sql_to_nosql", "target": "the schema being discussed"}}
    - "Turn on hand gesture control" -> {{"action": "gesture_control_status", "target": "status"}}
    - "Sync the knowledge graph with my other laptop" -> {{"action": "graph_sync_now", "target": "sync"}}
    - "Send an acoustic alert to my phone saying build failed" -> {{"action": "send_acoustic_message", "target": "build failed"}}
    - "What MCP tools do I have connected" -> {{"action": "mcp_list_tools", "target": "list"}}
    - "Use the filesystem tool to read notes.txt" -> {{"action": "mcp_call_tool", "target": "filesystem.read_file: {{\"path\": \"notes.txt\"}}"}}
    - "Ask a bigger model to help me plan this out" -> {{"action": "frontier_escalate", "target": "help me plan this out"}}
    - "Escalate this question to the cloud: what's the best way to structure a monorepo" -> {{"action": "frontier_escalate", "target": "what's the best way to structure a monorepo"}}
    - "What's a good way to structure a monorepo" (no explicit cloud/frontier request) -> {{"action": "casual_chat", "target": "..."}} -- NOT frontier_escalate, even though it's a hard question
    """

    try:
        # Query Llama 3.2 1B to classify intent
        response = ollama.chat(model=model_router.FAST_MODEL, messages=[
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_text}
        ], format='json')
        
        parsed_json = json.loads(response['message']['content'].strip())
        action = parsed_json.get("action")
        target = parsed_json.get("target", "")

        # --- THE SAFETY NET FIX ---
        if action not in VALID_ACTIONS:
            print(f"[Brain Routing Error] Model hallucinated action: {action}. Forcing casual chat.")
            action = "casual_chat"
        # ---------------------------

        # --- LOCAL RAG DOCUMENT ROUTING ---
        if action == "read_document":
            print(f"[Brain] Searching FAISS Vector Vault for: {target}")
            context_data = document_processor.query_documents(target)
            
            if not context_data:
                reply = "I don't have any relevant documents loaded in my matrix to answer that macha."
                return {"action": "casual_chat", "target": reply}
                
            rag_prompt = f"""
            You are Argus. Answer the user's question accurately using ONLY the provided Document Context. 
            Keep your answer to 2 or 3 brief sentences so it sounds natural spoken aloud.
            
            Document Context: {context_data}
            """
            
            rag_response = ollama.chat(model=model_router.select_model("read_document"), messages=[
                {'role': 'system', 'content': rag_prompt},
                {'role': 'user', 'content': target}
            ])
            
            reply = rag_response['message']['content'].strip()
            add_to_history('assistant', reply)
            await database.log_dialogue('assistant', reply)
            return {"action": "casual_chat", "target": reply}

        # --- MULTI-STEP AUTONOMOUS WORKFLOW ROUTING ---
        if action == "autonomous_workflow":
            print(f"[Brain] Routing to Agent Orchestrator: {target}")
            workflow_result = await agent_orchestrator.execute_autonomous_workflow(target)
            
            add_to_history('assistant', workflow_result)
            await database.log_dialogue('assistant', workflow_result)
            return {"action": "casual_chat", "target": workflow_result}

        # --- DEFAULT CONVERSATIONAL GENERATION (TANGLISH + SARCASM INJECTED) ---
        if action == "casual_chat":
            add_to_history('user', user_text)
            
            # Streaming passthrough for WebSocket connections
            # (Feature toggle: falls back to a normal one-shot reply below
            # if "streaming_replies" is turned off in the control center.)
            streaming_on = True
            try:
                import feature_toggles
                streaming_on = feature_toggles.is_enabled("streaming_replies")
            except Exception:
                pass

            if is_stream and streaming_on:
                return {"action": "casual_chat", "target": "STREAM"}
                
            chat_payload = [{'role': 'system', 'content': HUMAN_PERSONA_PROMPT}]
            chat_payload.extend(conversation_history)
            
            chat_response = ollama.chat(model=model_router.select_model("casual_chat"), messages=chat_payload)
            reply = chat_response['message']['content'].strip()
            
            add_to_history('assistant', reply)
            await database.log_dialogue('assistant', reply)
            return {"action": "casual_chat", "target": reply}
            
        return parsed_json

    except json.JSONDecodeError:
        print("[Brain Error] Model output was not valid JSON.")
        return {"action": "casual_chat", "target": "Macha, my command processor just glitched out. Oru nimisham, say that again?"}
    except Exception as e:
        print(f"[Brain Error] Unexpected failure: {e}")
        return {"action": "casual_chat", "target": "Ah, give me a second bro, I just hit a random error in my matrix."}