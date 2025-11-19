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

MAX_TICKETS_PER_CHUNK = 5  # Safe number to avoid context issues

PROMPT_TEMPLATE = """
You are an expert QA analyst, senior iOS engineer, and Jira triage specialist.

Process the following Jira tickets and output ONLY <tr> rows for an HTML table.
DO NOT include <html>, <body>, <table> or <head> tags.

Extract:
- Ticket Key
- Status
- Category (Solvable Bug / Not a Bug / Needs More Details)
- Summary
- Reasoning
- Suggested Fix
- Missing Details
- Ticket Link

Output one <tr> per ticket:

<tr>
  <td>TicketKey</td>
  <td>Status</td>
  <td>Category</td>
  <td>Summary</td>
  <td>Reasoning</td>
  <td>Fix</td>
  <td>Missing</td>
  <td><a href="LINK">Open</a></td>
</tr>

Now analyze this chunk:
"""

HTML_HEADER = """
<html>
<head>
<title>Jira Bug Analysis</title>
<style>
table {{ border-collapse: collapse; width: 100%; }}
td, th {{ border: 1px solid #ccc; padding: 8px; vertical-align: top; }}
tr:nth-child(even) {{ background: #f7f7f7; }}
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

HTML_FOOTER = """
</table>
</body>
</html>
"""


# ----------------------------
# Read text file
# ----------------------------
def read_text(text_file):
    with open(text_file, "r", encoding="utf-8") as f:
        return f.read()


# ----------------------------
# Extract tickets (safe boundaries)
# ----------------------------
def extract_tickets(text):
    pattern = r"([A-Z]{2,12}-\d+)"  # Jira ID format: ABC-1234
    matches = list(re.finditer(pattern, text))
    tickets = []

    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        tickets.append(text[start:end].strip())

    return tickets


# ----------------------------
# Chunk tickets (not lines)
# ----------------------------
def chunk_tickets(tickets):
    chunks = []
    for i in range(0, len(tickets), MAX_TICKETS_PER_CHUNK):
        chunk = "\n\n---\n\n".join(tickets[i:i + MAX_TICKETS_PER_CHUNK])
        chunks.append(chunk)
    return chunks


# ----------------------------
# Gemini API call
# ----------------------------
def call_gemini(chunk):
    payload = {
        "contents": [
            {"parts": [{"text": PROMPT_TEMPLATE + "\n" + chunk}]}
        ]
    }

    resp = requests.post(
        GENERATION_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload)
    )

    if resp.status_code != 200:
        print("❌ API Error:", resp.text)
        return ""

    try:
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return ""


# ----------------------------
# Extract HTML rows
# ----------------------------
def extract_rows(text):
    rows = []
    for line in text.splitlines():
        if "<tr>" in line or "<td>" in line or "</tr>" in line:
            rows.append(line)
    return rows


# ----------------------------
# Main Logic (streaming safe)
# ----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python jira_text_analyzer_streaming.py jira_dump.txt")
        return

    input_file = sys.argv[1]

    raw_text = read_text(input_file)

    tickets = extract_tickets(raw_text)
    print(f"📦 Tickets found: {len(tickets)}")

    chunks = chunk_tickets(tickets)
    print(f"📦 Processing chunks: {len(chunks)}")

    # ---- STREAMED OUTPUT FILES ----
    json_file = open("jira_results.jsonl", "w", encoding="utf-8")
    html_file = open("jira_report.html", "w", encoding="utf-8")

    # Write HTML header once
    html_file.write(HTML_HEADER)

    # Process each chunk
    for idx, chunk in enumerate(chunks):
        print(f"\n🚀 Processing chunk {idx + 1}/{len(chunks)}...")

        output = call_gemini(chunk)
        rows = extract_rows(output)

        print(f"→ Extracted rows: {len(rows)}")

        # Write JSON safely line-by-line
        json_file.write(json.dumps({
            "chunk_index": idx,
            "raw_output": output,
            "rows": rows
        }) + "\n")

        # Append rows to HTML file
        for row in rows:
            html_file.write(row + "\n")

    # Close HTML on completion
    html_file.write(HTML_FOOTER)

    json_file.close()
    html_file.close()

    print("\n✅ Done!")
    print("📁 JSON saved → jira_results.jsonl")
    print("📁 HTML saved → jira_report.html")


if __name__ == "__main__":
    main()
