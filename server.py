"""
Kapture Finance — Mock Collections Webhook Server
---------------------------------------------------
Implements the 5 tools defined in tool_definitions.json / HLD Section 4:
  - verify_customer
  - log_promise_to_pay
  - send_payment_link
  - escalate_to_agent
  - mark_disposition

This is a MOCK backend: no real database, no real SMS/WhatsApp is sent.
It exists to prove the tool-calling mechanism works end-to-end and to
enforce the auth gate described in the HLD (Section 2 / 5): downstream
tools refuse to run for a call session that hasn't been verified yet.

Run locally:
    pip install fastapi uvicorn
    uvicorn server:app --reload --port 3000

Then expose it publicly for Vapi with:
    ngrok http 3000

Point Vapi's tool webhook URL at:
    https://<your-ngrok-subdomain>.ngrok-free.app/webhook
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
import random
import json

app = FastAPI(title="Kapture Finance Mock Collections Webhook")

# ---------------------------------------------------------------------------
# In-memory "database" — resets every time you restart the server.
# Keyed by Vapi's call ID, which is included on every tool-call webhook.
# This is what enforces the auth gate at the server level, independent
# of whatever the LLM believes happened (see HLD Section 2).
# ---------------------------------------------------------------------------
verified_sessions: dict[str, bool] = {}

# Accepted verification codes for the mock customer (Rahul Sharma, ACC-88392).
# In a real system this would be a lookup against the loan management DB.
VALID_CODES = {"1234", "1995"}


def mask_name(name: str) -> str:
    """PII masking for logs, per HLD Section 5 (e.g. 'Rahul Sharma' -> 'Rahul S****')."""
    parts = name.split(" ")
    if len(parts) < 2:
        return name
    first, last = parts[0], parts[-1]
    return f"{first} {last[0]}{'*' * max(len(last) - 1, 3)}"


def log_event(tool_name: str, call_id: str, payload: dict, result: dict) -> None:
    """Console logging only — never logs the raw verification code, per HLD Section 5."""
    safe_payload = {k: v for k, v in payload.items() if k != "verification_code"}
    print(f"[{datetime.now(timezone.utc).isoformat()}] {tool_name} "
          f"call_id={call_id} in={safe_payload} out={result}")


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    message = body.get("message", {})

    # Vapi sends several message types (status updates, transcripts, etc.)
    # We only act on tool-calls; everything else is just acknowledged.
    if message.get("type") != "tool-calls":
        return JSONResponse({"status": "acknowledged"})

    call_id = message.get("call", {}).get("id", "unknown-call")
    tool_calls = message.get("toolCalls", [])
    results = []

    for tool_call in tool_calls:
        fn = tool_call["function"]
        name = fn["name"]
        args = fn.get("arguments", {})
        # Vapi sometimes sends arguments as a JSON string rather than a dict
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        tool_call_id = tool_call["id"]

        result = handle_tool(name, args, call_id)
        log_event(name, call_id, args, result)

        results.append({
            "toolCallId": tool_call_id,
            "result": json.dumps(result),
        })

    return JSONResponse({"results": results})


def handle_tool(name: str, args: dict, call_id: str) -> dict:
    if name == "verify_customer":
        return tool_verify_customer(args, call_id)

    # mark_disposition is intentionally exempt from the auth gate below.
    # Per HLD Section 6 (Fair Collections Norms), a Do-Not-Call request must
    # be honored immediately, even if it happens before verification —
    # and a WRONG_PERSON or failed-verification call also needs to be
    # logged even though that session was never verified. Every OTHER
    # tool (payment/negotiation actions) stays behind the gate.
    if name == "mark_disposition":
        return tool_mark_disposition(args)

    # Every tool below this line requires a verified session first —
    # this is the server-side enforcement of the AUTH_PENDING -> AUTHENTICATED
    # gate described in HLD Section 2. The LLM's instructions alone are not
    # trusted; the server checks independently.
    if not verified_sessions.get(call_id):
        return {
            "success": False,
            "error": "UNVERIFIED_SESSION",
            "message": "Customer must pass verify_customer before this action is permitted.",
        }

    if name == "log_promise_to_pay":
        return tool_log_promise_to_pay(args)
    if name == "send_payment_link":
        return tool_send_payment_link(args)
    if name == "escalate_to_agent":
        return tool_escalate_to_agent(args)

    return {"success": False, "error": "UNKNOWN_TOOL", "message": f"No handler for '{name}'"}


def tool_verify_customer(args: dict, call_id: str) -> dict:
    code = str(args.get("verification_code", "")).strip()
    verified = code in VALID_CODES
    verified_sessions[call_id] = verified
    return {
        "verified": verified,
        "customer_name": mask_name("Rahul Sharma") if verified else None,
        "message": "Identity verified successfully." if verified else "Verification failed. Incorrect code.",
    }


def tool_log_promise_to_pay(args: dict) -> dict:
    return {
        "success": True,
        "ptp_id": f"PTP-{random.randint(1000, 9999)}",
        "confirmed_date": args.get("ptp_date"),
        "amount": args.get("amount"),
    }


def tool_send_payment_link(args: dict) -> dict:
    channel = args.get("channel", "SMS")
    return {
        "success": True,
        "message": f"Payment link sent via {channel} to the registered mobile number.",
    }


def tool_escalate_to_agent(args: dict) -> dict:
    return {
        "success": True,
        "ticket_id": f"ESC-{random.randint(1000, 9999)}",
        "reason": args.get("reason"),
    }


def tool_mark_disposition(args: dict) -> dict:
    return {
        "success": True,
        "disposition_logged": args.get("status"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
async def health_check():
    """Quick manual check that the server is up: visit http://localhost:3000/ in a browser."""
    return {"status": "Kapture Mock Collections Webhook Server is running"}