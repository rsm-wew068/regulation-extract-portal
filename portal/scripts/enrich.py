"""
Enrich Paperless-ngx documents with Abstract + Trade custom fields.

- Abstract: a short summary (Claude Haiku / OpenAI when LLM_API_KEY is set;
  otherwise the first ~300 chars of the document text).
- Trade: one of a fixed taxonomy (LLM if available, else guessed from the title).

Idempotent: documents that already have an Abstract are skipped unless --force.

Run from the project venv:
    .venv/bin/python portal/scripts/enrich.py            # enrich missing only
    .venv/bin/python portal/scripts/enrich.py --force     # re-enrich everything
    .venv/bin/python portal/scripts/enrich.py --limit 5   # smoke test
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

PORTAL_DIR = Path(__file__).resolve().parent.parent  # portal/
load_dotenv(PORTAL_DIR / ".env")

PAPERLESS_API_URL = os.environ["PAPERLESS_API_URL"].rstrip("/")
PAPERLESS_API_TOKEN = os.environ["PAPERLESS_API_TOKEN"]
ABSTRACT_FIELD_ID = int(os.environ["ABSTRACT_FIELD_ID"])
TRADE_FIELD_ID = int(os.environ["TRADE_FIELD_ID"])
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "none").strip().lower()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()

TRADES = [
    "Cabinetry", "Electrical", "Plumbing", "HVAC", "Framing", "Roofing",
    "Drywall", "Insulation", "Concrete/Foundation", "Flooring", "Paint",
    "Landscaping", "Doors & Windows", "Hardware", "Fire Protection",
    "Stucco", "Excavation/Grading", "Site/Civil", "Other",
]
_TRADE_LOOKUP = {t.lower(): t for t in TRADES}

HEADERS = {"Authorization": f"Token {PAPERLESS_API_TOKEN}"}


def list_documents(client: httpx.Client):
    page = 1
    while True:
        r = client.get(
            f"{PAPERLESS_API_URL}/api/documents/",
            params={"page": page, "page_size": 100},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        yield from data["results"]
        if not data.get("next"):
            return
        page += 1


def cf_value(doc: dict, field_id: int):
    for item in doc.get("custom_fields", []):
        if item.get("field") == field_id:
            return item.get("value")
    return None


def get_content(client: httpx.Client, doc_id: int) -> str:
    r = client.get(f"{PAPERLESS_API_URL}/api/documents/{doc_id}/", timeout=120)
    r.raise_for_status()
    return r.json().get("content") or ""


def set_custom_fields(client: httpx.Client, doc: dict, abstract: str, trade: str):
    # Paperless REPLACES the entire custom_fields list on PATCH (not merge), so
    # include every existing field to avoid wiping others (e.g. Source).
    current = {it["field"]: it.get("value") for it in doc.get("custom_fields", [])}
    current[ABSTRACT_FIELD_ID] = abstract
    current[TRADE_FIELD_ID] = trade
    payload = {"custom_fields": [{"field": k, "value": v} for k, v in current.items()]}
    r = client.patch(
        f"{PAPERLESS_API_URL}/api/documents/{doc["id"]}/",
        headers={**HEADERS, "Content-Type": "application/json"},
        json=payload,
        timeout=60,
    )
    r.raise_for_status()


def guess_trade(text: str) -> str:
    t = (text or "").lower()
    rules = [
        ("cabinet", "Cabinetry"), ("countertop", "Cabinetry"), ("mirror", "Cabinetry"),
        ("med cab", "Cabinetry"),
        ("elect", "Electrical"), ("solar", "Electrical"), ("technology", "Electrical"),
        ("fire alarm", "Fire Protection"),
        ("plumb", "Plumbing"), ("hvac", "HVAC"), ("sheetmetal", "HVAC"),
        ("frame", "Framing"), ("lumber", "Framing"),
        ("roof", "Roofing"), ("drywall", "Drywall"),
        ("insulat", "Insulation"), ("fire stop", "Fire Protection"),
        ("concrete", "Concrete/Foundation"), ("foundation", "Concrete/Foundation"),
        ("floor", "Flooring"), ("paint", "Paint"),
        ("landscape", "Landscaping"), ("window", "Doors & Windows"),
        ("door", "Doors & Windows"), ("hardware", "Hardware"),
        ("sprinkler", "Fire Protection"), ("fire", "Fire Protection"),
        ("stucco", "Stucco"), ("excavat", "Excavation/Grading"), ("grade", "Excavation/Grading"),
        ("drainage", "Site/Civil"), ("civil", "Site/Civil"), ("site", "Site/Civil"),
        ("plan", "Site/Civil"), ("irrigation", "Site/Civil"), ("survey", "Site/Civil"),
        ("deck", "Site/Civil"),
    ]
    for kw, cat in rules:
        if kw in t:
            return cat
    return "Other"


def _parse_json_obj(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def llm_abstract_trade(title: str, content: str):
    if LLM_PROVIDER not in ("anthropic", "openai") or not LLM_API_KEY:
        return None
    snippet = (content or "")[:6000]
    sys_prompt = ("You analyze construction bid documents (Scope of Work / Specifications). "
                  "Reply with ONLY a JSON object, no prose.")
    user_prompt = (
        f"Document title: {title}\n\n"
        f"Content (first 6000 chars):\n{snippet}\n\n"
        f"Return JSON: {{\"abstract\": string (a concise description of what this document "
        f"covers, AT MOST 120 characters), \"trade\": string}}. `trade` MUST be exactly one of: "
        f"{', '.join(TRADES)}."
    )
    try:
        if LLM_PROVIDER == "anthropic":
            import anthropic
            model = LLM_MODEL or "claude-haiku-4-5-20251001"
            msg = anthropic.Anthropic(api_key=LLM_API_KEY).messages.create(
                model=model, max_tokens=300, system=sys_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = "".join(b.text for b in msg.content if hasattr(b, "text"))
        else:  # openai
            from openai import OpenAI
            model = LLM_MODEL or "gpt-4o-mini"
            resp = OpenAI(api_key=LLM_API_KEY).chat.completions.create(
                model=model, max_tokens=300,
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": user_prompt}],
            )
            raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"    LLM error, using fallback: {e}", file=sys.stderr)
        return None
    parsed = _parse_json_obj(raw)
    if not parsed:
        return None
    abstract = _truncate(parsed.get("abstract") or "", 128)
    trade = _TRADE_LOOKUP.get((parsed.get("trade") or "").strip().lower(), "Other")
    if not abstract:
        return None
    return abstract, trade


def _truncate(s: str, limit: int = 128) -> str:
    """Paperless string custom fields are capped at 128 chars."""
    s = (s or "").strip().replace("\n", " ")
    s = re.sub(r"\s+", " ", s)
    if len(s) <= limit:
        return s
    cut = s[: limit - 1].rsplit(" ", 1)[0].rstrip(".,;:!?-—")
    return (cut or s[: limit - 1]) + "…"


def fallback(title: str, content: str):
    text = (content or "").strip()
    abstract = _truncate(text or title or "(no content)", 128)
    return abstract, guess_trade(title or "")


def main():
    ap = argparse.ArgumentParser(description="Enrich Paperless docs with Abstract + Trade.")
    ap.add_argument("--force", action="store_true", help="re-enrich docs that already have an Abstract")
    ap.add_argument("--limit", type=int, default=0, help="max docs to process (0 = all)")
    args = ap.parse_args()

    provider = LLM_PROVIDER if (LLM_PROVIDER in ("anthropic", "openai") and LLM_API_KEY) else "fallback"
    print(f"provider={provider}  abstract_field={ABSTRACT_FIELD_ID}  trade_field={TRADE_FIELD_ID}")

    done = skipped = errors = processed = 0
    with httpx.Client(headers=HEADERS) as client:
        for doc in list_documents(client):
            processed += 1
            if args.limit and processed > args.limit:
                break
            doc_id = doc["id"]
            title = doc.get("title", "") or ""
            if not args.force and cf_value(doc, ABSTRACT_FIELD_ID):
                skipped += 1
                continue
            try:
                content = get_content(client, doc_id)
                res = llm_abstract_trade(title, content)
                abstract, trade = res if res else fallback(title, content)
                set_custom_fields(client, doc, abstract, trade)
                done += 1
                print(f"  #{doc_id:>3} [{trade:<20}] {title[:50]}")
            except Exception as e:
                errors += 1
                print(f"  #{doc_id:>3} ERROR: {e}", file=sys.stderr)
            time.sleep(0.15)

    print(f"\nDONE  enriched={done}  skipped={skipped}  errors={errors}")


if __name__ == "__main__":
    main()
