#!/usr/bin/env python3
"""
Research every vendor in data/vendors.json using Google Gemini (free tier)
with Google Search grounding, and write back any updated fields.

Run by .github/workflows/update-vendors.yml. Requires GEMINI_API_KEY env var
(free key from https://aistudio.google.com/apikey).
"""
import json
import os
import re
import sys
import time
import urllib.request

MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
API_KEY = os.environ.get("GEMINI_API_KEY")
DATA_FILE = "data/vendors.json"

# Fields Gemini is allowed to change. Personal fields (rating, notes,
# parking_notes, price_notes, tags) are never touched.
UPDATABLE = [
    "address", "neighborhood", "phone", "email", "website", "instagram",
    "wholesale", "resale_permit_required", "min_order", "brands", "items",
    "hours", "status",
]

PROMPT = """You are verifying business information for a vendor database used by a
Los Angeles custom-apparel business. Research this vendor online using Google Search.

Vendor (current data, may be outdated or incomplete):
{vendor}

Tasks:
1. Verify address, phone, website, instagram and hours. Fix anything that changed.
2. Determine if the business is still open. If permanently closed, set "status" to "closed".
   If you confirmed it exists and key info, set "status" to "active".
3. Look for updates about brands carried (e.g. Bella+Canvas, Gildan, Comfort Colors,
   Los Angeles Apparel), items sold, wholesale policy and minimum order.
4. Fill in empty fields ONLY when you find reliable information. Never invent data.

Respond with ONLY a JSON object (no markdown fences) containing:
- "changes": an object with ONLY the fields that should change, drawn from this list:
  {updatable}. Omit fields that are already correct. "brands" and "items" must be
  full replacement arrays. Use empty object {{}} if nothing changed.
- "summary": one sentence describing what changed, or "no changes".
- "confidence": "high", "medium" or "low".
Only include a change if you are confident; when in doubt, leave the field out."""


def call_gemini(vendor: dict) -> dict | None:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}"
        f":generateContent?key={API_KEY}"
    )
    body = {
        "contents": [{
            "parts": [{
                "text": PROMPT.format(
                    vendor=json.dumps(vendor, indent=2),
                    updatable=", ".join(UPDATABLE),
                )
            }]
        }],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.1},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            text = data["candidates"][0]["content"]["parts"][-1]["text"]
            # strip accidental code fences
            text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
            m = re.search(r"\{.*\}", text, re.S)
            return json.loads(m.group(0)) if m else None
        except Exception as e:  # rate limits, transient errors
            wait = 30 * (attempt + 1)
            print(f"    attempt {attempt + 1} failed ({e}); retrying in {wait}s")
            time.sleep(wait)
    return None


def main() -> None:
    if not API_KEY:
        sys.exit("GEMINI_API_KEY is not set. Add it as a repository secret.")

    with open(DATA_FILE) as f:
        db = json.load(f)

    today = time.strftime("%Y-%m-%d")
    changelog: list[str] = []

    for vendor in db["vendors"]:
        if vendor.get("status") == "closed":
            continue
        print(f"Researching: {vendor['name']}")
        result = call_gemini(vendor)
        if not result:
            print("    skipped (no usable response)")
            continue

        changes = result.get("changes") or {}
        confidence = result.get("confidence", "low")
        applied = []
        if confidence in ("high", "medium"):
            for field, value in changes.items():
                if field in UPDATABLE and value != vendor.get(field):
                    vendor[field] = value
                    applied.append(field)
        vendor["last_verified"] = today
        if applied:
            vendor["updated"] = today
            summary = result.get("summary", "")
            changelog.append(f"- **{vendor['name']}**: {summary} (fields: {', '.join(applied)})")
            print(f"    updated: {', '.join(applied)}")
        else:
            print("    no changes")
        time.sleep(10)  # stay well inside free-tier rate limits

    db["meta"]["updated"] = today
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        f.write("\n")

    # Summary for the PR body
    summary_text = (
        "## Auto-research results ({})\n\n{}".format(
            today, "\n".join(changelog) if changelog else "No changes found — all vendor info verified as current."
        )
    )
    with open("research_summary.md", "w") as f:
        f.write(summary_text + "\n")
    print(summary_text)


if __name__ == "__main__":
    main()
