import os
import sys
import requests
import json

# -------------------------------------
# CONFIGURATION
# -------------------------------------
API_KEY = "YOUR_GEMINI_API_KEY_HERE"

MODEL = "gemini-2.0-pro"  # Change if needed
CHUNK_SIZE_LINES = 1200   # Keep chunks small enough for Gemini

GENERATION_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"

PROMPT_TEMPLATE = """
You are an expert QA analyst, senior iOS engineer, and Jira triage specialist.

Process the following Jira tickets and output ONLY <tr> rows for an HTML table.
DO NOT include <html>, <table>, <body>, <head>, or any wrappers.
Only generate: <tr> ... </tr> for each ticket.

Extract for each ticket:
- Ticket Key
- Status (or Unknown)
- Category (Solvable Bug / Not a Bug / Needs More Details)
- Summary
- Reasoning
- Suggested Fix or Next Step
- Missing Details (blank if not applicable)
- Ticket Link

Output rows using this structure:

<tr>
  <td>Ticket Key</td>
  <td>Status</td>
  <td>Category</td>
  <td>Summary</td>
  <td>Reasoning</td>
  <td>Fix / Next Step</td>
  <td>Missing Details</td>
  <td><a href="LINK">Open</a></td>
</tr>

Now analyze this chunk:
"""


HTML_TEMPLATE = """
<html>
<head>
<meta charset="UTF-8">
<title>Jira Bug Analysis Report</title>
<style>
table {
  border-collapse: collapse;
  width: 100%;
  font-family: Arial, sans-serif;
}
th, td {
  border: 1px solid #ccc;
  padding: 8px;
  vertical-align: top;
}
tr:nth-child(even) { background: #f7f7f7; }
.category-solvable { background: #d9f7d9; }
.category-notbug { background: #ececec; }
.category-unclear { background: #fff8cc; }
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
  <th>Fix / Next Step</th>
  <th>Missing Details</th>
  <th>Link</th>
</tr>
{rows}
</table>
</body>
</html>
"""

# -------------------------------------
# FUNCTIONS
# -------------------------------------

def split_into_chunks(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()

    chunks = []
    for i in range(0, len(lines), CHUNK_SIZE_LINES):
        chunk = lines[i:i + CHUNK_SIZE_LINES]
        chunks.append("".join(chunk))

    return chunks


def call_gemini(prompt, chunk_text):
    """Call Gemini via REST API."""

    payload = {
        "contents": [{
            "parts": [{
                "text": prompt + "\n" + chunk_text
            }]
        }]
    }

    response = requests.post(
        GENERATION_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload)
    )

    if response.status_code != 200:
        print("❌ API Error:", response.text)
        return ""

    result = response.json()
    
    try:
        return result["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        print("⚠️ Warning: Unexpected API response format")
        return ""


def extract_rows(text):
    """Extract <tr> rows from model output."""
    rows = []
    for line in text.splitlines():
        if "<tr>" in line or "<td>" in line or "</tr>" in line:
            rows.append(line)
    return rows


def write_html(rows):
    html = HTML_TEMPLATE.format(rows="\n".join(rows))
    with open("jira_report.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("\n✅ Saved: jira_report.html")


# -------------------------------------
# MAIN EXECUTION
# -------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: python jira_analyzer.py jira_dump.txt")
        return

    input_file = sys.argv[1]

    print("\n📄 Splitting input file...")
    chunks = split_into_chunks(input_file)
    print(f"📦 Total chunks: {len(chunks)}")

    all_rows = []

    for idx, chunk_text in enumerate(chunks):
        print(f"\n🚀 Processing chunk {idx+1}/{len(chunks)} ...")

        output = call_gemini(PROMPT_TEMPLATE, chunk_text)

        if not output.strip():
            print("⚠️ Empty output from Gemini for this chunk.")
            continue

        rows = extract_rows(output)
        print(f"→ extracted rows: {len(rows)}")

        all_rows.extend(rows)

    print(f"\n🧩 Total rows collected: {len(all_rows)}")

    print("📄 Building final HTML...")
    write_html(all_rows)


if __name__ == "__main__":
    main()
