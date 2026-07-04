#!/usr/bin/env python3
"""
Research every vendor in data/vendors.json using Google Gemini (free tier)
with Google Search grounding, and write back any updated fields.

Also runs two smaller passes:
  - Price alerts: checks each data/prices.json item's stored price(s) against
    what Gemini can find online today, and FLAGS (does not auto-edit) any
    vendor price that looks like it moved ~10% or more.
  - New-vendor discovery: asks Gemini to propose a small batch of Fashion
    District / LA-area vendors not already in the database, added as
    "unverified" entries for review.

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
PRICES_FILE = "data/prices.json"
NEW_VENDOR_BATCH = int(os.environ.get("NEW_VENDOR_BATCH", "4"))  # 3-5 per run
PRICE_ALERT_THRESHOLD = 0.10  # flag if price looks like it moved ~10%+

# Fields Gemini is allowed to change on existing vendors. Personal fields
# (rating, notes, parking_notes, price_notes, tags) are never touched.
UPDATABLE = [
    "address", "neighborhood", "phone", "email", "website", "instagram",
    "wholesale", "resale_permit_required", "min_order", "brands", "items",
    "hours", "status",
]

VENDOR_PROMPT = """You are verifying business information for a vendor database used by a
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

PRICE_PROMPT = """You are checking current pricing for a blank-apparel item at specific vendors, for
a Los Angeles custom-apparel business's price book. Use Google Search.

Item: {item} ({brand} {style})
Currently recorded vendor prices (vendor_id: price[-price_high], last checked):
{prices_list}

For each vendor_id listed, try to find its CURRENT price (or price range) for this item on the
vendor's own website or a public price list. Only report a price you found from a reasonably
reliable source — never guess or estimate.

Respond with ONLY a JSON object (no markdown fences):
{{
  "alerts": [
    {{"vendor_id": "...", "old_price": <number>, "new_price": <number>, "source": "short note on where you found it"}}
  ]
}}
Include an alert ONLY when the new price differs from the old price by roughly 10% or more.
If nothing changed or you couldn't verify a price, return {{"alerts": []}}."""

NEW_VENDOR_PROMPT = """You are expanding a vendor database for a Los Angeles custom-apparel business
(screen printing, embroidery, heat press, UV printing, vinyl cutting). The database already tracks
these vendors — do NOT suggest any of them again:
{existing_names}

Categories tracked: {categories}

Using Google Search, find up to {n} NEW vendors in the Los Angeles Fashion District or nearby areas
that would be relevant additions: blank apparel wholesalers, cap/hat suppliers, print supply shops,
embroidery/thread suppliers, trims & notions, or related services. Prefer vendors with some
verifiable web presence (address, phone, website, or reviews). Fewer than {n} is fine if you can't
verify more with confidence.

Respond with ONLY a JSON array (no markdown fences) of objects, each with these fields:
"name", "category" (must be one of the tracked categories above), "address", "phone", "website",
"wholesale" (one of "Wholesale only", "Wholesale + Retail", "Retail only", "Unknown"), "notes"
(why it's relevant / what you found). Leave a field as "" if you couldn't verify it. Never invent
data — if you can't find a real vendor, return fewer entries or an empty array."""


def call_gemini_text(prompt: str) -> str | None:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}"
        f":generateContent?key={API_KEY}"
    )
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
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
            return data["candidates"][0]["content"]["parts"][-1]["text"]
        except Exception as e:  # rate limits, transient errors
            wait = 30 * (attempt + 1)
            print(f"    attempt {attempt + 1} failed ({e}); retrying in {wait}s")
            time.sleep(wait)
    return None


def extract_json(text: str):
    if not text:
        return None
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or f"vendor-{int(time.time())}"


def research_vendors(db: dict, today: str) -> list[str]:
    changelog = []
    for vendor in db["vendors"]:
        if vendor.get("status") == "closed":
            continue
        print(f"Researching: {vendor['name']}")
        result = extract_json(call_gemini_text(
            VENDOR_PROMPT.format(vendor=json.dumps(vendor, indent=2), updatable=", ".join(UPDATABLE))
        ))
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
    return changelog


def check_price_alerts(db: dict) -> list[str]:
    alerts_log = []
    try:
        with open(PRICES_FILE) as f:
            pb = json.load(f)
    except FileNotFoundError:
        print("No price book found — skipping price alerts.")
        return alerts_log

    vendor_name = {v["id"]: v["name"] for v in db["vendors"]}

    for item in pb.get("items", []):
        prices = item.get("prices") or []
        if not prices:
            continue
        print(f"Checking price: {item['item']}")
        prices_list = "\n".join(
            f"- {p['vendor_id']}: ${p['price']}"
            + (f"-${p['price_high']}" if p.get("price_high") else "")
            + f" (last checked {p.get('updated', 'unknown')})"
            for p in prices
        )
        result = extract_json(call_gemini_text(
            PRICE_PROMPT.format(item=item["item"], brand=item.get("brand", ""), style=item.get("style", ""), prices_list=prices_list)
        ))
        for alert in (result or {}).get("alerts", []) if result else []:
            try:
                old_p, new_p = float(alert["old_price"]), float(alert["new_price"])
            except (KeyError, TypeError, ValueError):
                continue
            if old_p <= 0 or abs(new_p - old_p) / old_p < PRICE_ALERT_THRESHOLD:
                continue
            vname = vendor_name.get(alert.get("vendor_id"), alert.get("vendor_id", "unknown vendor"))
            direction = "up" if new_p > old_p else "down"
            alerts_log.append(
                f"- **{item['item']}** at **{vname}**: was ${old_p:.2f}, now looks {direction} to "
                f"${new_p:.2f} ({alert.get('source', 'no source given')}) — verify before updating the Price Book."
            )
            print(f"    price alert: {vname} {old_p} -> {new_p}")
        time.sleep(10)
    return alerts_log


def discover_new_vendors(db: dict, today: str) -> list[str]:
    log = []
    categories = db["meta"].get("categories", [])
    existing_names = ", ".join(v["name"] for v in db["vendors"])
    print(f"Discovering up to {NEW_VENDOR_BATCH} new vendors...")
    result = extract_json(call_gemini_text(
        NEW_VENDOR_PROMPT.format(existing_names=existing_names, categories=", ".join(categories), n=NEW_VENDOR_BATCH)
    ))
    if not isinstance(result, list):
        print("    no usable candidates")
        return log

    existing_ids = {v["id"] for v in db["vendors"]}
    for cand in result[:NEW_VENDOR_BATCH]:
        name = (cand.get("name") or "").strip()
        if not name:
            continue
        vid = slugify(name)
        while vid in existing_ids:
            vid += "-2"
        existing_ids.add(vid)
        vendor = {
            "id": vid,
            "name": name,
            "category": cand.get("category") if cand.get("category") in categories else (categories[0] if categories else "Other"),
            "address": cand.get("address", ""),
            "neighborhood": "Fashion District",
            "phone": cand.get("phone", ""),
            "email": "",
            "website": cand.get("website", ""),
            "instagram": "",
            "contact_person": "",
            "wholesale": cand.get("wholesale") or "Unknown",
            "resale_permit_required": False,
            "min_order": "",
            "brands": [],
            "items": [],
            "hours": "",
            "price_notes": "",
            "parking_notes": "",
            "rating": 0,
            "tags": ["auto-discovered"],
            "notes": cand.get("notes", ""),
            "status": "unverified",
            "last_verified": today,
            "added": today,
        }
        db["vendors"].append(vendor)
        log.append(f"- **{name}** ({vendor['category']}): {vendor['notes'] or 'proposed by auto-discovery'}")
        print(f"    proposed: {name}")
    return log


def main() -> None:
    if not API_KEY:
        sys.exit("GEMINI_API_KEY is not set. Add it as a repository secret.")

    with open(DATA_FILE) as f:
        db = json.load(f)

    today = time.strftime("%Y-%m-%d")

    vendor_changelog = research_vendors(db, today)
    price_alerts = check_price_alerts(db)
    new_vendor_log = discover_new_vendors(db, today)

    db["meta"]["updated"] = today
    with open(DATA_FILE, "w") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
        f.write("\n")

    sections = [f"## Auto-research results ({today})", ""]
    sections.append("\n".join(vendor_changelog) if vendor_changelog else "No vendor field changes found — all verified as current.")
    sections += ["", "## Price alerts", ""]
    sections.append("\n".join(price_alerts) if price_alerts else "No price changes of 10%+ detected on tracked items.")
    sections += ["", "## New vendor candidates", ""]
    sections.append("\n".join(new_vendor_log) if new_vendor_log else "No new vendor candidates found this run.")
    summary_text = "\n".join(sections)

    with open("research_summary.md", "w") as f:
        f.write(summary_text + "\n")
    print(summary_text)


if __name__ == "__main__":
    main()
