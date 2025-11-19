import os
import sys
import re
import requests
import json

# --------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------
API_KEY = "YOUR_GEMINI_API_KEY"
MODEL = "gemini-2.0-pro"
JIRA_DOMAIN = "https://your-jira-domain/browse/"

GENERATION_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent?key={API_KEY}"
)

TICKETS_PER_CHUNK = 3
TIMEOUT = 60


# --------------------------------------------------------
# GEMINI PROMPT (JSON ONLY WITH TAG WRAPPER)
# --------------------------------------------------------
PROMPT_TEMPLATE = """
You are an expert QA analyst and senior iOS engineer.

You MUST output valid JSON ONLY.

Wrap your JSON output inside the following tags:

<JSON>
[ {...}, {...} ]
</JSON>

Rules:
- No text before <JSON>
- No text after </JSON>
- Inside <JSON> must be valid JSON array
- No markdown
- No commentary
- No explanation outside JSON
- One JSON object per ticket

Each JSON object must contain:

{
  "ticket_key": "",
  "status": "",
  "category": "",
  "summary": "",
  "reasoning": "",
  "fix": "",
  "missing_details": "",
  "link": ""
}

If "link" is missing, create:
"https://your-jira-domain/browse/<ticket_key>"

Allowed values for "category":
- "Solvable Bug"
- "Not a Bug"
- "Needs More Details"

Now analyze these tickets:
"""


# --------------------------------------------------------
# READ INPUT TEXT FILE
# --------------------------------------------------------
def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# --------------------------------------------------------
# EXTRACT TICKETS (correct boundary rule)
# Line containing "Jira" + next line starting with [G7APP-xxxxx]
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
# CHUNK TICKETS
# --------------------------------------------------------
def chunk_tickets(tickets):
    chunks = []
    for i in range(0, len(tickets), TICKETS_PER_CHUNK):
        chunks.append("\n\n---\n\n".join(tickets[i:i + TICKETS_PER_CHUNK]))
    return chunks


# --------------------------------------------------------
# CALL GEMINI
# --------------------------------------------------------
def call_gemini(chunk):
    payload = {
        "contents": [
            {"parts": [{"text": PROMPT_TEMPLATE + "\n" + chunk}]}
        ]
    }

    try:
        response = requests.post(
            GENERATION_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=TIMEOUT
        )
    except Exception as e:
        print("❌ Network error:", e)
        return None

    if response.status_code != 200:
        print("❌ API Error:", response.text[:500])
        return None

    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None


# --------------------------------------------------------
# SAFE JSON EXTRACTION
# Only parse content between <JSON> ... </JSON>
# --------------------------------------------------------
def extract_json(raw_text):
    if raw_text is None:
        return None

    raw = raw_text.strip()
    start = raw.find("<JSON>")
    end = raw.find("</JSON>")

    if start == -1 or end == -1:
        print("❌ Missing <JSON> tags.")
        return None

    json_block = raw[start + len("<JSON>") : end].strip()

    try:
        return json.loads(json_block)
    except Exception as e:
        print("❌ JSON decode error:", e)
        print("⚠️ Raw JSON block failed:", json_block[:500])
        return None


# --------------------------------------------------------
# GENERATE BEAUTIFUL HTML FROM JSONL
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
        padding: 20px;
        background: #f5f7fa;
        color: #333;
    }
    h1 {
        font-size: 28px;
        font-weight: 600;
        text-align: center;
        margin-bottom: 25px;
        color: #222;
    }
    table {
        width: 100%;
        border-collapse: separate;
        border-spacing: 0 10px;
    }
    thead tr {
        background: #fff;
        box-shadow: 0 2px 4px rgba(0,0,0,0.08);
    }
    th {
        padding: 14px;
        font-size: 14px;
        text-transform: uppercase;
        color: #555;
        border-bottom: 1px solid #eee;
        text-align: left;
        position: sticky;
        top: 0;
        background: #fff;
        z-index: 10;
    }
    tr.data-row {
        background: #fff;
        transition: all 0.15s ease-in-out;
        box-shadow: 0 2px 4px rgba(0,0,0,0.06);
    }
    tr.data-row:hover {
        transform: scale(1.01);
        box-shadow: 0 4px 8px rgba(0,0,0,0.10);
    }
    td {
        padding: 14px;
        font-size: 14px;
        vertical-align: top;
        border-bottom: 1px solid #eee;
    }
    .badge {
        padding: 6px 12px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 600;
        color: #fff;
        display: inline-block;
    }
    .green { background: #2ecc71; }
    .amber { background: #f39c12; }
    .gray  { background: #7f8c8d; }
    a {
        color: #3498db;
        font-weight: 600;
        text-decoration: none;
    }
    a:hover {
        text-decoration: underline;
    }
</style>
</head>

<body>
<h1>Jira Bug Analysis Report</h1>

<table>
<thead>
<tr>
  <th>Ticket</th>
  <th>Status</th>
  <th>Category</th>
  <th>Summary</th>
  <th>Reasoning</th>
  <th>Fix</th>
  <th>Missing Details</th>
  <th>Link</th>
</tr>
</thead>

<tbody>
"""

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            for obj in data["results"]:

                category = obj.get("category", "")
                if category == "Solvable Bug":
                    badge_class = "green"
                elif category == "Needs More Details":
                    badge_class = "amber"
                else:
                    badge_class = "gray"

                html += f"""
<tr class="data-row">
  <td>{obj.get('ticket_key','')}</td>
  <td>{obj.get('status','')}</td>
  <td><span class="badge {badge_class}">{category}</span></td>
  <td>{obj.get('summary','')}</td>
  <td>{obj.get('reasoning','')}</td>
  <td>{obj.get('fix','')}</td>
  <td>{obj.get('missing_details','')}</td>
  <td><a href="{obj.get('link','')}">Open</a></td>
</tr>
"""

    html += """
</tbody>
</table>
</body>
</html>
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"📁 HTML report saved → {output_path}")


# --------------------------------------------------------
# MAIN EXECUTION
# --------------------------------------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python jira_g7app_analyzer.py jira_dump.txt")
        return

    path = sys.argv[1]
    raw = read_text(path)

    print("🔍 Detecting tickets...")
    tickets = extract_tickets(raw)
    print("📦 Tickets found:", len(tickets))

    chunks = chunk_tickets(tickets)
    print("✂️ Total chunks:", len(chunks))

    jsonl_path = "jira_results.jsonl"
    jsonl = open(jsonl_path, "w", encoding="utf-8")

    for idx, chunk in enumerate(chunks):
        print(f"\n🚀 Processing chunk {idx + 1}/{len(chunks)}")

        raw_output = call_gemini(chunk)
        parsed = extract_json(raw_output)

        if parsed is None:
            print("⚠️ Skipping chunk.")
            continue

        jsonl.write(json.dumps({
            "chunk": idx,
            "results": parsed
        }) + "\n")

    jsonl.close()
    print("📁 JSONL saved:", jsonl_path)

    print("\n🎨 Generating HTML...")
    generate_html(jsonl_path, "jira_report.html")

    print("\n🔥 DONE!")

if __name__ == "__main__":
    main()
