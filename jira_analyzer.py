import os
import sys
import re
import pdfplumber
import requests
import json

API_KEY = "YOUR_GEMINI_API_KEY"
MODEL = "gemini-2.0-pro"
GENERATION_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={API_KEY}"

MAX_TICKETS_PER_CHUNK = 5  # Adjust based on size

PROMPT_TEMPLATE = """
You are an expert QA analyst, senior iOS engineer, and Jira triage specialist.

Process the following Jira tickets and output ONLY <tr> rows for an HTML table.
DO NOT include <html>, <body>, or <table> tags.

Extract:
- Ticket Key
- Status
- Category (Solvable Bug / Not a Bug / Needs More Details)
- Summary
- Reasoning
- Suggested Fix
- Missing Details
- Ticket Link

Output per ticket:

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

HTML_TEMPLATE = """
<html>
<head>
<title>Jira Bug Analysis</title>
<style>
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: 8px; }
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
{rows}
</table>
</body>
</html>
"""

# ----------------------------
# PDF → Text
# ----------------------------
def pdf_to_text(pdf_file):
    text = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + "\n\n"
    return text


# ----------------------------
# Extract ticket blocks using regex
# ----------------------------
def extract_tickets(text):
    # Regex finds ticket keys like "ABC-123"
    pattern = r"([A-Z]{2,10}-\d+)"
    matches = list(re.finditer(pattern, text))

    tickets = []

    for i in range(len(matches)):
        start = matches[i].start()
        end = matches[i+1].start() if i+1 < len(matches) else len(text)

        ticket_text = text[start:end].strip()
        tickets.append(ticket_text)

    return tickets


# ----------------------------
# Chunk tickets safely
# ----------------------------
def chunk_tickets(tickets):
    chunks = []
    for i in range(0, len(tickets), MAX_TICKETS_PER_CHUNK):
        chunk = "\n\n---\n\n".join(tickets[i:i + MAX_TICKETS_PER_CHUNK])
        chunks.append(chunk)
    return chunks


# ----------------------------
# Call Gemini REST API
# ----------------------------
def call_gemini(chunk):
    payload = {
        "contents": [{
            "parts": [{
                "text": PROMPT_TEMPLATE + "\n" + chunk
            }]
        }]
    }

    resp = requests.post(
        GENERATION_URL,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload)
    )

    if resp.status_code != 200:
        print("❌ API error:", resp.text)
        return ""

    data = resp.json()

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except:
        return ""


# ----------------------------
# Extract <tr> rows
# ----------------------------
def extract_rows(text):
    rows = []
    for line in text.splitlines():
        if "<tr>" in line or "<td>" in line or "</tr>" in line:
            rows.append(line)
    return rows


# ----------------------------
# Main Function
# ----------------------------
def main():
    if len(sys.argv) < 2:
        print("Usage: python jira_pdf_analyzer.py file.pdf")
        return

    pdf_file = sys.argv[1]

    print("📄 Extracting text from PDF...")
    raw_text = pdf_to_text(pdf_file)

    print("🔍 Detecting tickets...")
    tickets = extract_tickets(raw_text)
    print(f"📦 Total tickets found: {len(tickets)}")

    print("✂️ Splitting into chunks...")
    chunks = chunk_tickets(tickets)
    print(f"📦 Total chunks: {len(chunks)}")

    all_rows = []

    for idx, chunk in enumerate(chunks):
        print(f"\n🚀 Processing chunk {idx+1}/{len(chunks)}...")
        output = call_gemini(chunk)
        rows = extract_rows(output)
        print(f"→ Extracted rows: {len(rows)}")
        all_rows.extend(rows)

    print("\n🧩 Building final HTML...")
    html = HTML_TEMPLATE.format(rows="\n".join(all_rows))

    with open("jira_report.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("✅ Done! Saved as jira_report.html")


if __name__ == "__main__":
    main()
