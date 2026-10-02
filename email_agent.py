"""
email_agent.py — Feature 8: Email sending.

Uses plain SMTP rather than a Gmail/Outlook OAuth SDK to avoid a heavy
new dependency, since app_bridge.py already has a lightweight pattern
for storing per-app credentials. Reads SMTP credentials from environment
variables so nothing sensitive is hardcoded or committed to the repo:

    ARGUS_SMTP_HOST      (default: smtp.gmail.com)
    ARGUS_SMTP_PORT      (default: 587)
    ARGUS_SMTP_USER      (your email address)
    ARGUS_SMTP_PASSWORD  (an app password, NOT your normal account password)

brain.py routes "send an email to X about Y" style requests here via
the "send_email" action.
"""

import os
import smtplib
import json
from email.mime.text import MIMEText
import ollama
import model_router

SMTP_HOST = os.environ.get("ARGUS_SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("ARGUS_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ARGUS_SMTP_USER")
SMTP_PASSWORD = os.environ.get("ARGUS_SMTP_PASSWORD")


def is_configured() -> bool:
    return bool(SMTP_USER and SMTP_PASSWORD)


def _parse_request(natural_language_request: str) -> dict:
    """Extracts recipient/subject/body from a natural-language request."""
    prompt = f"""
    Extract an email request into JSON with keys "to" (email address, may be a
    plain name if no address is given), "subject" (short subject line), and
    "body" (a short, clear email body written in a professional tone based on
    what the user described).
    Output ONLY valid JSON.

    Request: "{natural_language_request}"
    """
    try:
        response = ollama.chat(
            model=model_router.select_model("send_email"),
            messages=[{'role': 'system', 'content': prompt}],
            format='json'
        )
        return json.loads(response['message']['content'].strip())
    except Exception as e:
        print(f"[Email Parse Error]: {e}")
        return {}


def send_email(to_address: str, subject: str, body: str) -> str:
    if not is_configured():
        return ("I can't send that email yet, macha — SMTP credentials aren't set. "
                "Set ARGUS_SMTP_USER and ARGUS_SMTP_PASSWORD environment variables first.")

    if "@" not in to_address:
        return f"'{to_address}' doesn't look like a real email address, so I held off sending anything."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to_address

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [to_address], msg.as_string())
        return f"Sent, macha. Emailed {to_address} with subject '{subject}'."
    except Exception as e:
        print(f"[Email Send Error]: {e}")
        return "I hit a snag trying to send that email — check the SMTP credentials and network connection."


def handle_email_request(natural_language_request: str) -> str:
    """Entry point called by executor.py for the 'send_email' action."""
    try:
        import feature_toggles
        if not feature_toggles.is_enabled("calendar_email"):
            return "Calendar & Email is currently toggled off in the control center."
    except Exception:
        pass

    parsed = _parse_request(natural_language_request)
    to_address = parsed.get("to", "")
    subject = parsed.get("subject", "(no subject)")
    body = parsed.get("body", "")

    if not to_address:
        return "I couldn't figure out who to send that to, macha. Give me a clear recipient."

    return send_email(to_address, subject, body)
