# Kapture Collections Voicebot — "Maya"

**In one sentence:** Maya is an AI phone agent that calls customers about overdue loan payments, confirms who she's talking to before saying anything private, then either gets a payment commitment or hands the call to a human — and every call ends with a clear, logged outcome.

Built on [Vapi.ai](https://vapi.ai) for a lending client, "Kapture Finance."

**Scenario used throughout:** Rahul Sharma, Personal Loan Account ACC-88392, ₹8,499 overdue, 12 days past due.

---

## Contents

1. [What this project actually does](#1-what-this-project-actually-does)
2. [How a call works, in plain terms](#2-how-a-call-works-in-plain-terms)
3. [Project structure](#3-project-structure)
4. [Setup instructions](#4-setup-instructions)
5. [Design choices, and why](#5-design-choices-and-why)
6. [The 5 tools Maya can use](#6-the-5-tools-maya-can-use)
7. [Test results](#7-test-results)
8. [What broke, and how it was debugged](#8-what-broke-and-how-it-was-debugged)
9. [Known limitations & what I'd improve next](#9-known-limitations--whatd-id-improve-next)

---

## 1. What this project actually does

A lending company calls customers who are late on a loan payment, to remind them and try to get a commitment to pay. Normally a human agent makes that call. This project replaces that call with an AI voice agent named Maya, built to do the same job — politely, compliantly, and without a human needing to be on the line for routine cases.

The one rule this whole project is built around: **Maya must never tell anyone how much they owe until she's confirmed she's actually speaking to the right person.** Everything else — the negotiation, the edge cases, the logging — is built around protecting that one rule.

---

## 2. How a call works, in plain terms

Here's the shape of a typical call, without any jargon:

1. **Maya greets the caller** and asks if she's speaking to Rahul Sharma. No mention of money yet.
2. **She asks for a quick ID check** — the last 4 digits of a PAN card, or a birth year.
3. **Only once that check actually passes**, she tells the customer what they owe and why.
4. **The customer responds**, and the call branches depending on what they say:
   - *"I'll pay Friday"* → she logs the promise and sends a payment link.
   - *"I already paid"* → she notes that and wraps up politely.
   - *"I can't afford it"* → she can't offer more than a small discount on her own, so she hands off to a human.
   - *"This isn't my debt"* → same — handed to a human.
   - *"Stop calling me"* → she honors it immediately, at any point in the call, verified or not.
5. **No matter how the call ends, she records the outcome** — so there's always a clear record of what happened.

The technical version of this same flow — with the actual services involved, latency budgets, and enforcement details — is in `docs/HLD_Document.docx`.

---

## 3. Project Structure

```
kapture-collections-voicebot/
├── README.md
├── docs/
│   ├── HLD_Document.docx       ← the design document (read this for the "why")
│   └── System_Architecture.png
├── vapi/
│   ├── system_prompt.txt       ← Maya's instructions, as configured in Vapi
│   └── tool_definitions.json   ← the 5 actions Maya can take, as configured in Vapi
├── mock-server/
│   ├── server.py                ← the only real code in this project — where compliance is actually enforced
│   └── requirements.txt
└── tests/
    └── test_cases.json          ← every scenario tested, with real pass/fail results
```

**Quick note on `vapi/`:** these two files are copies of what's configured live inside Vapi's dashboard — they're included so anyone reviewing this project can see exactly what Maya was instructed to do, without needing access to the Vapi account itself. They don't run on their own.

---

## 4. Setup Instructions

**Requirements:** Python 3.10+, a free [Vapi.ai](https://vapi.ai) account, [ngrok](https://ngrok.com).

1. **Install dependencies**
   ```
   cd mock-server
   pip install -r requirements.txt
   ```

2. **Run the mock webhook server** — this is the small backend that pretends to check IDs and log payments
   ```
   python -m uvicorn server:app --reload --port 3000
   ```
   Visit `http://localhost:3000/` — you should see a status confirmation.

3. **Expose it publicly with ngrok** — Vapi is a cloud service and can't reach your laptop directly, so ngrok creates a temporary public address that forwards to your local server
   ```
   ngrok http 3000
   ```
   (A free static/reserved domain is recommended so the URL doesn't change between sessions.)

4. **Configure the Vapi Assistant**
   - Transcriber: Deepgram Nova-2, Multilingual (supports the English/Hindi bonus scenario — see Section 7)
   - Model: GPT-4o (see Section 5 for why, not GPT-4o-mini)
   - Voice: ElevenLabs Flash v2.5
   - Paste `vapi/system_prompt.txt` into the System Prompt field
   - First Message: *"Hello, this is Maya calling from Kapture Finance. Am I speaking with Mr. Rahul Sharma?"*
   - Register all 5 tools from `vapi/tool_definitions.json` as Custom Tools, each pointing to `https://<your-ngrok-url>/webhook`
   - Publish the assistant

5. **Test** using Vapi's built-in web call ("Talk") feature — no phone number needed.

---

## 5. Design Choices, and Why

| Choice | Why |
|---|---|
| **FastAPI (Python)** for the mock server | Comfort with the language; FastAPI's error messages and auto-docs make it easy to sanity-check endpoints independently of Vapi. |
| **GPT-4o** (not GPT-4o-mini) | During testing, GPT-4o-mini ("GPT-4o Mini Cluster" in Vapi) reliably *narrated* tool calls as spoken dialogue instead of actually invoking them — e.g. saying "Calling verify_customer, account ACC-88392..." out loud rather than triggering the real function. Switching to full GPT-4o resolved this; every tool call fired correctly afterward. Full story in Section 8. |
| **ElevenLabs Flash v2.5** (not Multilingual v2 or v3) | Flash v2.5 is ElevenLabs' fastest model (~75ms), keeping round-trip latency close to the <1.2s budget. Multilingual/v3 models sound more expressive but are too slow for a live phone call. |
| **Temperature 0.1** | Keeps Maya's compliance-critical phrasing consistent across calls rather than creatively rephrased. |
| **Server-enforced auth gate, not just a prompt instruction** | The system prompt tells Maya not to disclose debt before verification — but an instruction is just a request the AI is trying to follow, and requests can fail under pressure. The mock server independently tracks whether each call session has actually been verified, and rejects any tool that could leak sensitive info if it hasn't — regardless of what the AI believes happened. A request can be talked past; a lock in the code can't. |
| **ngrok with a static domain, run locally** rather than deploying to Render/Vercel | Faster iteration for a single-day build-and-test cycle; the assignment brief explicitly allows mocked/local endpoints. Noted as a natural next step for production (Section 9). |

---

## 6. The 5 Tools Maya Can Use

Maya can't directly check a database or send a text — she can only produce words and structured requests. The 5 tools below are the actions she's allowed to trigger, each implemented in `mock-server/server.py`.

| Tool | What it does | Needs verification first? |
|---|---|---|
| `verify_customer` | Checks the PAN/birth-year code against the mock record | — |
| `log_promise_to_pay` | Records the payment date and amount the customer agreed to | Yes |
| `send_payment_link` | Simulates texting a payment link | Yes |
| `escalate_to_agent` | Hands the call to a human, for hardship or dispute cases | Yes |
| `mark_disposition` | Records how the call ended — the one tool that must always work, even for a do-not-call request or a wrong number, before any verification happened | **No** |

---

## 7. Test Results

11 scenarios were tested as live web calls through Vapi and verified against the mock server's console logs — each log line shows the real tool name, arguments, and response, which is the actual proof the tool-calling mechanism works end-to-end rather than being simulated. Full detail for each is in `tests/test_cases.json`.

| # | Scenario | Result |
|---|---|---|
| 1 | Happy path — customer agrees to pay | ✅ Pass |
| 2 | Hardship — customer can't pay in full | ✅ Pass |
| 3 | Already paid | ✅ Pass |
| 4 | Dispute | ✅ Pass |
| 5 | Do-not-call, requested *before* verification | ⚠️ Failed once, then fixed — see Section 8 |
| 6 | Wrong person | ✅ Pass |
| 7 | Failed verification (wrong code twice) | ✅ Pass |
| 8 | Bilingual switch — English to Hindi mid-call (bonus) | ✅ Pass |
| 9 | Partial payment ("I'll pay half") — treated as hardship, not a discount | ✅ Pass |
| 10 | Abusive caller — one warning, then graceful end | ✅ Pass |
| 11 | Adversarial test: pushed for a ~65% discount | ✅ Held — see caveat in Section 9 |

The assignment asks for at least 2 demonstrated paths; this submission covers every scenario in the HLD's intent table, the bonus bilingual feature, and a deliberate stress test on the one guardrail that isn't enforced in code (see Section 9).

---

## 8. What Broke, and How It Was Debugged

Three real issues came up during testing. They're documented here rather than quietly fixed, because showing the debugging process is worth more than a document that pretends everything worked on the first try.

**Bug 1 — the AI narrated tool calls instead of actually making them.**
Early test calls showed Maya saying things like *"Calling verify_customer, account ACC-88392, verification code 1234"* out loud, as if reading code to the customer — and the server logs showed nothing had actually arrived. Checking Vapi's raw message logs confirmed the AI's response was plain text with no real tool-call attached. Switching the model from "GPT-4o Mini Cluster" to full GPT-4o fixed it. The real root cause turned out to be Bug 2 below — the model had nothing real to call.

**Bug 2 — switching models silently detached all 5 tools.**
Changing the model created a new assistant version, and that version showed "0 tools attached." None of the previously configured tools carried over automatically. Fixed by re-adding all 5 tools to the new version and republishing. Lesson: always re-check the Tools tab after any assistant-level change, not just the prompt.

**Bug 3 — the do-not-call request was wrongly blocked.**
Testing "stop calling me" said immediately, before any verification, returned an error: the server's blanket rule ("nothing runs without verification") was accidentally blocking the one tool that must always work — logging the outcome. This is a real compliance issue, since do-not-call requests must be honored instantly, verified or not. Fixed by making `mark_disposition` a deliberate exception to the verification check, while every other tool still correctly requires it.

---

## 9. Known Limitations & What I'd Improve Next

- **Verification is knowledge-based, not identity-based.** It checks whether the right *code* was given, not whether the right *person* gave it — so someone who knows Rahul's PAN digits or birth year (a family member, for instance) could pass verification in his place. A production version would add a stronger second factor, like a one-time code sent to his registered phone number.
- **The 10% discount cap only lives in the prompt, not in code.** I deliberately tried to talk Maya into accepting a much bigger discount than she's authorized to give, and she correctly refused and escalated instead (test #11) — but nothing in the server itself would technically stop a bad answer if the AI ever got this wrong. Unlike the verification rule, which the server enforces independently, this one still relies on the AI following instructions correctly. I'd want to move this check into the server before trusting it in production.
- **Account details are hardcoded for this one demo customer**, not looked up from a real database — a `get_account_details` tool would replace this in a real deployment.
- **Verification status resets if the server restarts**, since it's only kept in memory, not saved anywhere permanent — a real deployment would store this externally so a restart mid-call doesn't accidentally undo someone's verification.
- **Running locally through ngrok** rather than a permanent hosted server — fine for this submission, but a next step would be deploying to somewhere like Render for an always-on URL.
- **An abusive-caller hangup and a generic silence hangup currently log under the same status** (`NO_RESPONSE`), just with different notes. A dedicated status could separate these if that distinction matters for reporting.