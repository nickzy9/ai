import os
import sys
import re
import requests
import json

# --------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------
API_KEY = "YOUR_GEMINI_API_KEY_HERE"
MODEL = "gemini-2.0-pro"
JIRA_DOMAIN = "https://your-jira-domain/browse/"  # e.g. "https://jira.yourcompany.com/browse/"

GENERATION_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent?key={API_KEY}"
)

TICKETS_PER_CHUNK = 3
TIMEOUT = 60


# --------------------------------------------------------
# GEMINI PROMPT (MAX DETAIL, DEV-GRADE FIXES)
# --------------------------------------------------------
PROMPT_TEMPLATE = """
You are a principal-level iOS engineer and QA triage lead working on a complex medical / telemetry app
(similar to Dexcom G7), with architecture including:

- iOS app (Swift / SwiftUI, MVVM, coordinators)
- AppCore / SDK layers for business logic
- Bluetooth / GATT / sensor communication
- Notification & alert pipeline (local + push)
- Data logging / bulk logging flows
- Watch / companion app flows
- Error handling, queues, and state machines

You will receive one or more Jira tickets in plain text. For EACH ticket you must:

1) Understand the bug deeply.
2) Decide if it is:
   - "Solvable Bug"
   - "Not a Bug"
   - "Needs More Details"
3) Provide detailed, senior-engineer-level analysis and fix guidance.

You MUST output valid JSON ONLY, wrapped like this:

<JSON>
[ {...}, {...} ]
</JSON>

NO text before <JSON>.
NO text after </JSON>.
Inside <JSON> must be a valid JSON ARRAY.

Each ticket must be represented as ONE JSON object with this exact shape:

{
  "ticket_key": "",
  "status": "",
  "category": "",   // "Solvable Bug", "Not a Bug", or "Needs More Details"
  "summary": "",    // 1–2 sentence summary of the issue
  "root_cause": [   // bullet-style reasoning of the likely root cause
    "..."
  ],
  "reasoning": [    // why you classified it that way (triage reasoning)
    "..."
  ],
  "fix_recommendation": [   // concrete, developer-grade action items
    "..."
  ],
  "risk": [         // possible regressions or risk areas
    "..."
  ],
  "missing_details": [      // only if category is 'Needs More Details' OR if something is unclear
    "..."
  ],
  "link": ""        // Jira link; if missing, construct with the ticket key
}

Rules and expectations:

- Think like a senior dev reviewing Jira for implementation.
- "root_cause" is technical: e.g. wrong state machine transition, stale cache, race between alert clear and schedule, missing guard for nil, etc.
- "fix_recommendation" must be actionable and specific. Wherever possible mention:
    - which layer (e.g. AppCore, SDK, view model, notification scheduler, logging service)
    - what condition or branch to adjust
    - whether to add guards / debouncing / queueing
    - whether to add or update unit tests and integration tests
- "risk" should mention possible side-effects and areas to regression-test (e.g. other flows using same service, related alerts, watch flows, bulk logging behavior).
- "missing_details" should list EXACT things needed: logs, screenshots, reproduction steps, build number, OS version, watch/phone pairing state, etc.
- If you believe something is "Not a Bug", clearly explain in "reasoning" why the behavior is expected or spec-compliant.
- If you select "Needs More Details", still try to infer as much as possible from the ticket, but list clearly what is blocking you.
- Always return an ARRAY: [ { ... }, { ... } ] even if there is only 1 ticket in the chunk.
- Do NOT use markdown. Do NOT add any prose outside the JSON.

Now analyze these tickets:
"""


# --------------------------------------------------------
# READ INPUT TEXT FILE
# --------------------------------------------------------
def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------
# EXTRACT TICKETS
# Ticket begins at:
#   any line containing "Jira"
# followed by
#   next line starting with [G7APP-xxxxx]
# --------------------------------------------------------
def extract_tickets(text):
    pattern = r"(?m)^.*Jira.*\n\[G7APP-\d+\]"
    matches = list(re.finditer(pattern, text))

    tickets = []
    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        tickets.append(text[start:end].strip())

    return tickets


# --------------------------------------------------------
# CHUNK TICKETS (3 per chunk)
# --------------------------------------------------------
def chunk_tickets(tickets):
    chunks = []
    for i in range(0, len(tickets), TICKETS_PER_CHUNK):
        joined = "\n\n---\n\n".join(tickets[i: i + TICKETS_PER_CHUNK])
        chunks.append(joined)
    return chunks


# --------------------------------------------------------
# CALL GEMINI
# --------------------------------------------------------
def call_gemini(chunk_text):
    if not chunk_text:
        return None

    payload = {
        "contents": [
            {"parts": [{"text": PROMPT_TEMPLATE + "\n" + chunk_text}]}
        ]
    }

    try:
        response = requests.post(
            GENERATION_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=TIMEOUT,
        )
    except Exception as e:
        print("❌ Network error:", e)
        return None

    if response.status_code != 200:
        print("❌ API Error:", response.text[:500])
        return None

    try:
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return text
    except Exception:
        print("❌ Unexpected response shape from Gemini.")
        return None


# --------------------------------------------------------
# EXTRACT JSON BETWEEN <JSON> ... </JSON>
# --------------------------------------------------------
def extract_json(raw_text):
    if raw_text is None:
        return None

    raw = raw_text.strip()
    start = raw.find("<JSON>")
    end = raw.find("</JSON>")

    if start == -1 or end == -1:
        print("❌ Missing <JSON> tags in Gemini response.")
        return None

    json_block = raw[start + len("<JSON>"): end].strip()

    try:
        data = json.loads(json_block)
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception as e:
        print("❌ JSON decode error:", e)
        print("⚠️ Raw JSON block that failed:\n", json_block[:500])
        return None


# --------------------------------------------------------
# HELPER: ARRAY -> <li> LIST HTML
# --------------------------------------------------------
def list_to_html(items):
    if not items:
        return "<li>-</li>"
    safe_items = []
    for it in items:
        if it is None:
            continue
        safe_items.append(str(it))
    if not safe_items:
        return "<li>-</li>"
    return "".join(f"<li>{entry}</li>" for entry in safe_items)


# --------------------------------------------------------
# GENERATE MODERN CARD-STYLE HTML FROM JSONL
# --------------------------------------------------------
def generate_html(jsonl_path, output_path):
    html = """
<html>
<head>
<title>Jira Bug Analysis Report</title>
<style>
    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial;
        margin: 0;
        padding: 30px;
        background: #f0f2f5;
        color: #333;
    }
    h1 {
        font-size: 32px;
        text-align: center;
        margin-bottom: 30px;
        color: #222;
    }
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
        gap: 20px;
    }
    .card {
        background: #fff;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 4px 10px rgba(0,0,0,0.08);
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .card:hover {
        transform: translateY(-4px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.12);
    }
    .ticket-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }
    .ticket-key {
        font-size: 18px;
        font-weight: 700;
        color: #2c3e50;
    }
    .badge {
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        color: #fff;
    }
    .green { background: #27ae60; }
    .amber { background: #f39c12; }
    .gray  { background: #7f8c8d; }
    .status {
        font-size: 13px;
        color: #555;
        margin-bottom: 4px;
    }
    .summary {
        font-size: 15px;
        margin-bottom: 8px;
        color: #333;
    }
    .section-title {
        font-size: 13px;
        font-weight: 700;
        margin-top: 14px;
        margin-bottom: 4px;
        color: #444;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }
    ul {
        margin-top: 4px;
        padding-left: 20px;
    }
    ul li {
        margin-bottom: 4px;
        line-height: 1.4;
        font-size: 14px;
    }
    a {
        color: #3498db;
        text-decoration: none;
        font-weight: 600;
    }
    a:hover {
        text-decoration: underline;
    }
</style>
</head>

<body>
<h1>Jira Bug Analysis Report</h1>

<div class="grid">
"""

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            results = data.get("results", [])
            for obj in results:
                ticket_key = obj.get("ticket_key", "")
                status = obj.get("status", "")
                category = obj.get("category", "")
                summary = obj.get("summary", "")

                root_cause = obj.get("root_cause", [])
                reasoning = obj.get("reasoning", [])
                fix = obj.get("fix_recommendation", [])
                risk = obj.get("risk", [])
                missing = obj.get("missing_details", [])
                link = obj.get("link") or (JIRA_DOMAIN + ticket_key if ticket_key else "#")

                if category == "Solvable Bug":
                    badge_class = "green"
                elif category == "Needs More Details":
                    badge_class = "amber"
                else:
                    badge_class = "gray"

                html += f"""
<div class="card">
  <div class="ticket-header">
    <a href="{link}" class="ticket-key" target="_blank" rel="noopener noreferrer">{ticket_key}</a>
    <span class="badge {badge_class}">{category}</span>
  </div>
  <div class="status">Status: {status}</div>
  <div class="summary">{summary}</div>

  <div class="section-title">Root Cause</div>
  <ul>
    {list_to_html(root_cause)}
  </ul>

  <div class="section-title">Reasoning</div>
  <ul>
    {list_to_html(reasoning)}
  </ul>

  <div class="section-title">Fix Recommendation</div>
  <ul>
    {list_to_html(fix)}
  </ul>

  <div class="section-title">Risk</div>
  <ul>
    {list_to_html(risk)}
  </ul>

  <div class="section-title">Missing Details</div>
  <ul>
    {list_to_html(missing)}
  </ul>
</div>
"""

    html += """
</div> <!-- grid -->
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"📁 HTML report saved → {output_path}")


# --------------------------------------------------------
# MAIN
# --------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python jira_g7app_analyzer.py jira_dump.txt")
        return

    input_path = sys.argv[1]
    raw_text = read_text(input_path)

    print("🔍 Extracting tickets...")
    tickets = extract_tickets(raw_text)
    print("📦 Tickets found:", len(tickets))

    if not tickets:
        print("⚠️ No tickets detected. Check the format / regex.")
        return

    chunks = chunk_tickets(tickets)
    print("✂️ Chunks to process:", len(chunks))

    jsonl_path = "jira_results.jsonl"
    jsonl_file = open(jsonl_path, "w", encoding="utf-8")

    for idx, chunk in enumerate(chunks):
        print(f"\n🚀 Processing chunk {idx + 1}/{len(chunks)}")
        raw_output = call_gemini(chunk)
        parsed = extract_json(raw_output)

        if parsed is None:
            print("⚠️ Skipping this chunk due to JSON issues.")
            continue

        jsonl_file.write(json.dumps({
            "chunk": idx,
            "results": parsed
        }) + "\n")

    jsonl_file.close()
    print("📁 JSONL saved →", jsonl_path)

    print("\n🎨 Generating HTML dashboard...")
    generate_html(jsonl_path, "jira_report.html")

    print("\n✅ DONE. Open 'jira_report.html' in your browser.")


if __name__ == "__main__":
    main()
