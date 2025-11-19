import os
import sys
import re
import requests
import json

# ----------------------------
# CONFIG
# ----------------------------
API_KEY = "YOUR_GEMINI_API_KEY"
MODEL = "gemini-2.0-pro"

GENERATION_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"
)

TICKETS_PER_CHUNK = 3
TIMEOUT = 60

# JSON-only Gemini prompt
PROMPT_TEMPLATE = """
You are an expert QA analyst and senior iOS engineer.

I will give you one or more Jira tickets.

For each ticket, return JSON ONLY.
No HTML. No markdown. No commentary.

Output must be STRICTLY valid JSON array:
[
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
]

"category" must be one of:
- "Solvable Bug"
- "Not a Bug"
- "Needs More Details"

Construct "link" as:
"https://your-jira-domain/browse/<ticket_key>"
if the link is missing.

Now analyze these tickets:
"""

# ----------------------------
# Read Text
# ----------------------------
def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

# ----------------------------
# Detect Tickets (New Regex)
# ----------------------------
def extract_tickets(text):
    # Ticket begins where a line contains "Jira"
    # followed by next line starting with [G7APP-xxxxx]
    pattern = r"(?m)^.*Jira.*\n\[G7APP-\d+\]"
    matches = list(re.finditer(pattern, text))
    tickets = []

    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        tickets.append(block)

    return tickets

# ----------------------------
# Chunk Tickets
# ----------------------------
def chunk_tickets(tickets):
    chunks = []
    for i in range(0, len(tickets), TICKETS_PER_CHUNK):
        chunks.append("\n\n---\n\n".join(tickets[i:i + TICKETS_PER_CHUNK]))
    return chunks

# ----------------------------
# Call Gemini (JSON response)
# ----------------------------
def call_gemini(chunk):
    payload = {
        "contents": [
            { "parts": [{ "text": PROMPT_TEMPLATE + "\n" + chunk }] }
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
        print("❌ Request error:", e)
        return None

    if response.status_code != 200:
        print("❌ API Error:", response.text[:300])
        return None

    try:
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)   # Gemini must return valid JSON
    except Exception as e:
        print("⚠️ JSON parse error:", e)
        print("Raw output:", response.text[:500])
        return None

# ----------------------------
# Generate HTML from JSON
# ----------------------------
def generate_html(jsonl_path, output_html):
    html = """
<html>
<head>
<title>Jira Bug Report</title>
<style>
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 8px; vertical-align: top; }
tr:nth-child(even) { background: #f7f7f7; }
</style>
</head>
<body>
<h1>Jira Bug Analysis Report</h1>
<table>
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
"""

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            for obj in data["results"]:
                html += f"""
<tr>
  <td>{obj['ticket_key']}</td>
  <td>{obj['status']}</td>
  <td>{obj['category']}</td>
  <td>{obj['summary']}</td>
  <td>{obj['reasoning']}</td>
  <td>{obj['fix']}</td>
  <td>{obj['missing_details']}</td>
  <td><a href="{obj['link']}">Open</a></td>
</tr>
"""

    html += """
</table>
</body>
</html>
"""

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"📁 HTML report saved: {output_html}")

# ----------------------------
# MAIN
# ----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python jira_g7app_json_analyzer.py jira_dump.txt")
        return

    input_file = sys.argv[1]

    print("📄 Loading text...")
    raw_text = read_text(input_file)

    print("🔍 Extracting ticket boundaries...")
    tickets = extract_tickets(raw_text)
    print(f"📦 Tickets found: {len(tickets)}")

    chunks = chunk_tickets(tickets)
    print(f"✂️ Chunks: {len(chunks)}")

    jsonl_path = "jira_results.jsonl"
    jsonl = open(jsonl_path, "w", encoding="utf-8")

    for idx, chunk in enumerate(chunks):
        print(f"\n🚀 Processing chunk {idx + 1}/{len(chunks)}")

        results = call_gemini(chunk)
        if results is None:
            print("⚠️ Skipping chunk.")
            continue

        jsonl.write(json.dumps({ "chunk": idx, "results": results }) + "\n")

    jsonl.close()
    print("📁 JSONL saved:", jsonl_path)

    print("\n🧱 Generating HTML...")
    generate_html(jsonl_path, "jira_report.html")

    print("\n🎉 DONE!")


if __name__ == "__main__":
    main()
