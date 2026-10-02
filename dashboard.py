import streamlit as st
import psutil
import time
import asyncio
import threading
import queue
import os

from brain import process_command, clear_history, stream_casual_reply
from hands import execute_action
import safety
import audit
import notifier
import document_processor
import calendar_agent

# --- 1. CORE UI CONFIGURATION ---
st.set_page_config(
    page_title="Argus | Core Matrix",
    page_icon="👁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Force Dark Mode aesthetic via custom CSS injection
st.markdown("""
    <style>
    .stApp { background-color: #0E1117; }
    .stTextInput input { border: 1px solid #4A4A4A; background-color: #1E1E1E; color: #FFFFFF; }
    .status-text { font-family: 'Courier New', Courier, monospace; color: #00FF00; }
    </style>
""", unsafe_allow_html=True)

st.title("ARGUS // Orchestration Matrix")
st.markdown("### Single-Device Autonomous Powerhouse")
st.divider()


# --- FEATURE 2 HELPER: bridge brain.py's async generator into a sync
# generator so st.write_stream (which expects a plain iterable) can
# consume it and render tokens as they arrive. ---
def sync_stream_from_async(async_gen_func, *args, **kwargs):
    q = queue.Queue()
    SENTINEL = object()

    def runner():
        async def consume():
            try:
                async for item in async_gen_func(*args, **kwargs):
                    q.put(item)
            except Exception as e:
                q.put(f"[stream error: {e}]")
            finally:
                q.put(SENTINEL)
        asyncio.run(consume())

    threading.Thread(target=runner, daemon=True).start()
    while True:
        item = q.get()
        if item is SENTINEL:
            break
        yield item


# --- 2. HARDWARE TELEMETRY (SIDEBAR) ---
with st.sidebar:
    st.header("System Telemetry")

    # Real-time hardware pulls
    cpu_usage = psutil.cpu_percent(interval=0.1)
    ram = psutil.virtual_memory()

    st.metric("CPU Utilization", f"{cpu_usage}%")
    st.progress(cpu_usage / 100)

    st.metric("Memory (RAM)", f"{ram.percent}%", f"{ram.used // (1024**3)}GB / {ram.total // (1024**3)}GB")
    st.progress(ram.percent / 100)

    st.divider()

    st.header("Agentic Cores")
    st.markdown('<p class="status-text">🟢 Llama 3.2 (Reasoning)</p>', unsafe_allow_html=True)
    st.markdown('<p class="status-text">🟢 Whisper (Acoustic)</p>', unsafe_allow_html=True)
    st.markdown('<p class="status-text">🟢 SQLite/JSON (Memory)</p>', unsafe_allow_html=True)
    st.markdown('<p class="status-text">🟢 DuckDuckGo (Scraper)</p>', unsafe_allow_html=True)

    st.divider()

    # --- FEATURE 5: Proactive notifications ---
    st.header("🔔 Alerts")
    if "alert_offset" not in st.session_state:
        st.session_state.alert_offset = 0
    new_alerts, st.session_state.alert_offset = notifier.drain_new_alerts(st.session_state.alert_offset)
    if "seen_alerts" not in st.session_state:
        st.session_state.seen_alerts = []
    st.session_state.seen_alerts = (st.session_state.seen_alerts + new_alerts)[-10:]
    if st.session_state.seen_alerts:
        for alert in reversed(st.session_state.seen_alerts):
            icon = {"critical": "🔴", "warning": "🟡"}.get(alert.get("level"), "🔵")
            st.markdown(f"{icon} **{alert.get('source')}**: {alert.get('message')}")
    else:
        st.caption("No alerts yet. overwatch/aegis/security_warden will show up here.")

    st.divider()
    if st.button("Flush Context Queue", use_container_width=True):
        clear_history()
        st.success("Short-term memory wiped.")


# --- 3. SESSION STATE FOR CHAT + FEATURE 4 CONFIRMATION STATE ---
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_confirmation" not in st.session_state:
    st.session_state.pending_confirmation = None  # {"action":..., "target":...}


# --- 4. MAIN INTERFACE: TABS ---
tab_chat, tab_library, tab_calendar, tab_audit = st.tabs(
    ["💬 Console", "📚 Document Library", "📅 Calendar", "🧾 Audit Log"]
)

# ======================= TAB: CHAT CONSOLE =======================
with tab_chat:
    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("Console Interface")

        # Render the chat history
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        last_decision_json = None

        # --- FEATURE 4: if a risky action is pending, this input is the confirmation ---
        if st.session_state.pending_confirmation:
            pending = st.session_state.pending_confirmation
            st.warning(safety.confirmation_prompt(pending["action"], pending["target"]))
            colc1, colc2 = st.columns(2)
            with colc1:
                if st.button("✅ Confirm", use_container_width=True):
                    result = execute_action({"action": pending["action"], "target": pending["target"]})
                    st.session_state.messages.append({"role": "assistant", "content": f"Confirmed. Executed `{pending['action']}`."})
                    st.session_state.pending_confirmation = None
                    st.rerun()
            with colc2:
                if st.button("❌ Cancel", use_container_width=True):
                    st.session_state.messages.append({"role": "assistant", "content": "Cancelled. No changes made."})
                    st.session_state.pending_confirmation = None
                    st.rerun()

        # Input field for commands
        elif prompt := st.chat_input("Enter a command or query..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Classifying intent..."):
                    # process_command is async (brain.py); is_stream=True lets
                    # casual_chat replies come back as a streaming sentinel.
                    decision_json = asyncio.run(process_command(prompt, is_stream=True))
                    last_decision_json = decision_json
                    action = decision_json.get("action")
                    target = decision_json.get("target")

                if action == "casual_chat" and target == "STREAM":
                    # --- FEATURE 2: real token-by-token streaming ---
                    response_text = st.write_stream(
                        sync_stream_from_async(stream_casual_reply, prompt)
                    )
                elif action == "casual_chat":
                    response_text = target
                    st.markdown(response_text)
                elif safety.is_risky(action, target):
                    # --- FEATURE 4: gate risky actions behind confirmation ---
                    st.session_state.pending_confirmation = {"action": action, "target": target}
                    response_text = f"⚠️ Awaiting confirmation for `{action}` → `{target}`"
                    st.warning(response_text)
                else:
                    execute_action(decision_json)
                    response_text = f"**Action Triggered:** `{action}`\n\n**Target:** {target}"
                    st.markdown(response_text)

                st.session_state.messages.append({"role": "assistant", "content": response_text})
                if action != "casual_chat" or target != "STREAM":
                    st.rerun()

    with col2:
        st.subheader("Live Router Data")
        st.info("Watch this panel to see exactly how the classifier routes your commands in real-time.")
        if last_decision_json:
            st.json(last_decision_json)
        elif st.session_state.pending_confirmation:
            st.json(st.session_state.pending_confirmation)
        else:
            st.caption("Send a command to see its routing JSON here.")

# ======================= TAB: DOCUMENT LIBRARY (Feature 10) =======================
with tab_library:
    st.subheader("📚 RAG Document Library")
    st.caption("Upload PDFs here to make them queryable via voice/text 'read_document' commands.")

    uploaded_pdf = st.file_uploader("Upload a PDF", type=["pdf"])
    if uploaded_pdf is not None:
        if st.button("Ingest this PDF"):
            os.makedirs("documents", exist_ok=True)
            dest_path = os.path.join("documents", uploaded_pdf.name)
            with open(dest_path, "wb") as f:
                f.write(uploaded_pdf.getbuffer())
            with st.spinner(f"Chunking and embedding {uploaded_pdf.name}..."):
                success = document_processor.ingest_pdf(dest_path)
            if success:
                st.success(f"Ingested {uploaded_pdf.name} into the RAG library.")
            else:
                st.error("Ingestion failed — check the terminal logs for details.")

    st.divider()
    st.markdown("**Ingested documents:**")
    docs = document_processor.list_ingested_documents()
    if not docs:
        st.caption("No documents ingested yet.")
    else:
        for d in reversed(docs):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(d["ingested_at"]))
            st.markdown(f"- **{d['filename']}** — {d['chunk_count']} chunks — ingested {ts}")

# ======================= TAB: CALENDAR (Feature 8) =======================
with tab_calendar:
    st.subheader("📅 Calendar")
    events = calendar_agent.list_events()
    if not events:
        st.caption("No events scheduled. Try asking Argus: \"add a dentist appointment Friday at 3pm\".")
    else:
        for e in events:
            st.markdown(f"- **{e['title']}** — {e['when']}")

# ======================= TAB: AUDIT LOG (Feature 12) =======================
with tab_audit:
    st.subheader("🧾 Action Audit Log")
    st.caption("Every action Argus has actually executed, across every interface (voice, text, remote).")
    if st.button("Refresh"):
        st.rerun()
    actions = audit.get_recent_actions(limit=100)
    if not actions:
        st.caption("No actions logged yet.")
    else:
        for a in actions:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a["timestamp"]))
            st.markdown(f"**{ts}** — `{a['action']}`({a['target']}) → {a['result']}")
