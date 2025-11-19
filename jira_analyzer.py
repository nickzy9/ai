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
# GEMINI PROMPT: JSON-ONLY WITH TAGS
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
- Respond with an array of objects: one per ticket.

Each JSON object must look like:

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

If link is missing, construct:
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
# EXTRACT TICKETS USING NEW RULE:
# Line contains 'Jira' + next line starts with [G7APP-xxxxx]
# --------------------------------------------------------
def extract_tickets(text):
    pattern = r"(?m)^.*Jira.*\n\[G7APP-\d+\]"
    matches = list(re.finditer(pattern, text))

    tickets = []
    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end].strip()
        tickets.append(block)

    return tickets


# --------------------------------------------------------
# CHUNK TICKETS
# --------------------------------------------------------
def chunk_tickets(tickets):
    chunks = []
    for i in range(0, len(tickets), TICKETS_PER_CHUNK):
        joined = "\n\n---\n\n".join(tickets[i:i + TICKETS_PER_CHUNK])
        chunks.append(joined)
    return chunks


# --------------------------------------------------------
# CALL GEMINI (returns raw text)
# --------------------------------------------------------
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
        print("❌ Network error:", e)
        return None

    if response.status_code != 200:
        print("❌ API Error:", response.text[:300])
        return None

    try:
        return response.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return None


# --------------------------------------------------------
# SAFE JSON EXTRACTION: extract JSON between <JSON> tags
# --------------------------------------------------------
def extract_json(raw_text):
    if raw_text is None:
        return None

    raw = raw_text.strip()

    start = raw.find("<JSON>")
    end = raw.find("</JSON>")

    if start == -1 or end == -1:
        print("❌ No <JSON> tags found.")
        return None

    json_block = raw[start + len("<JSON>") : end].strip()

    try:
        return json.loads(json_block)
    except json.JSONDecodeError as e:
        print("❌ JSON decode error:", e)
        print("⚠️ Raw JSON block failed:", json_block[:200])
        return None


# --------------------------------------------------------
# GENERATE HTML FROM JSONL
# --------------------------------------------------------
def generate_html(jsonl_path, output_path):
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
  <td>{obj.get('ticket_key','')}</td>
  <td>{obj.get('status','')}</td>
  <td>{obj.get('category','')}</td>
  <td>{obj.get('summary','')}</td>
  <td>{obj.get('reasoning','')}</td>
  <td>{obj.get('fix','')}</td>
  <td>{obj.get('missing_details','')}</td>
  <td><a href="{obj.get('link','')}">Open</a></td>
</tr>
"""

    html += """
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

    text_path = sys.argv[1]
    raw_text = read_text(text_path)

    print("🔍 Extracting ticket blocks...")
    tickets = extract_tickets(raw_text)
    print(f"📦 Total tickets found: {len(tickets)}")

    chunks = chunk_tickets(tickets)
    print(f"✂️ Chunk count: {len(chunks)}")

    jsonl_path = "jira_results.jsonl"
    jsonl_file = open(jsonl_path, "w", encoding="utf-8")

    for idx, chunk in enumerate(chunks):
        print(f"\n🚀 Processing chunk {idx + 1}/{len(chunks)}")

        raw = call_gemini(chunk)
        json_data = extract_json(raw)

        if json_data is None:
            print("⚠️ Skipping chunk due to JSON error.")
            continue

        jsonl_file.write(json.dumps({
            "chunk": idx,
            "results": json_data
        }) + "\n")

    jsonl_file.close()
    print("📁 JSONL saved:", jsonl_path)

    print("\n🧱 Generating HTML...")
    generate_html(jsonl_path, "jira_report.html")

    print("\n🎉 DONE!")


if __name__ == "__main__":
    main()
