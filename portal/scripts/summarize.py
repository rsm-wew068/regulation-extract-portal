"""
Generate rich, structured per-document summaries (summary.txt style) and store
them in portal/summaries.json keyed by document id. The backend serves these;
the viewer displays them. Run after enrich.py.

Usage:
    .venv/bin/python portal/scripts/summarize.py            # summarize missing
    .venv/bin/python portal/scripts/summarize.py --force     # re-summarize all
    .venv/bin/python portal/scripts/summarize.py --limit 2   # smoke test
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

PORTAL_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PORTAL_DIR / ".env")

URL = os.environ["PAPERLESS_API_URL"].rstrip("/")
TOKEN = os.environ["PAPERLESS_API_TOKEN"]
HEADERS = {"Authorization": f"Token {TOKEN}"}
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "none").strip().lower()
LLM_API_KEY = os.environ.get("LLM_API_KEY", "").strip()
LLM_MODEL = os.environ.get("LLM_MODEL", "").strip()
OUT = PORTAL_DIR / "summaries.json"

STYLE = """\
2. Cabinets and Installation
Scope of Work (Trade Specific Conditions)
Contractor shall furnish and install all casework, moldings, and trim for kitchens, baths, linens, pantries, and utility rooms.
Finish:  All exposed hardwood surfaces must be pre-finished with stain and a minimum of two coats of Sherwin Williams (or equal) conversion varnish.
Material Thickness:  Drawer faces and face frames shall be 3/4" thick solid material. Stile and rail width must be 2" minimum to accommodate strip lighting.
Kitchen Requirements:  Include at least one 3-drawer bank. Islands/peninsulas must have finished ends; island sinks require a 2x6 internal pony-wall skinned with cabinet finish.
Construction Details:  Utilize 1x2 white nailer strips at upper cabinets and 1x4 white nailer strips at lower cabinets."""


def list_docs(client):
    page = 1
    while True:
        r = client.get(f"{URL}/api/documents/", params={"page": page, "page_size": 100}, timeout=60)
        r.raise_for_status()
        d = r.json()
        yield from d["results"]
        if not d.get("next"):
            return
        page += 1


def get_content(client, doc_id):
    r = client.get(f"{URL}/api/documents/{doc_id}/", timeout=120)
    r.raise_for_status()
    return r.json().get("content") or ""


def rich_summary(title, content):
    if LLM_PROVIDER not in ("openai", "anthropic") or not LLM_API_KEY:
        return None
    snippet = (content or "")[:8000]
    sys_prompt = "You write structured spec summaries of construction bid documents. Plain text only."
    user_prompt = (
        f"Document title: {title}\n\n"
        f"Content (first 8000 chars):\n{snippet}\n\n"
        f"Write a structured summary of THIS document in EXACTLY this style:\n{STYLE}\n\n"
        f"Rules: line 1 = trade + document type; line 2 = a one-sentence scope; "
        f"then 8-15 lines each formatted 'Label:  specific detail'. Extract the REAL "
        f"numbers, dimensions, brand names, and code/standard references from the document. "
        f"Skip generic boilerplate and signature lines. Plain text, no markdown, no preamble."
    )
    try:
        if LLM_PROVIDER == "openai":
            from openai import OpenAI
            model = LLM_MODEL or "gpt-4o-mini"
            resp = OpenAI(api_key=LLM_API_KEY).chat.completions.create(
                model=model,
                max_tokens=700,
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": user_prompt}],
            )
            return (resp.choices[0].message.content or "").strip()
        import anthropic
        model = LLM_MODEL or "claude-haiku-4-5-20251001"
        msg = anthropic.Anthropic(api_key=LLM_API_KEY).messages.create(
            model=model, max_tokens=700, system=sys_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(b.text for b in msg.content if hasattr(b, "text")).strip()
    except Exception as e:
        print(f"    LLM error: {e}")
        return None


def load_existing():
    if OUT.exists():
        try:
            return json.loads(OUT.read_text())
        except Exception:
            return {}
    return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    data = load_existing()
    done = skipped = errors = n = 0
    with httpx.Client(headers=HEADERS) as client:
        for doc in list_docs(client):
            if args.limit and n >= args.limit:
                break
            n += 1
            did = str(doc["id"])
            if not args.force and did in data:
                skipped += 1
                continue
            try:
                content = get_content(client, doc["id"])
                s = rich_summary(doc.get("title", ""), content)
                if s:
                    data[did] = s
                    done += 1
                    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
                    print(f"  #{doc['id']}  {doc.get('title','')[:45]}  ({len(s)} chars)")
                else:
                    errors += 1
            except Exception as e:
                errors += 1
                print(f"  #{doc['id']} ERROR: {e}")
            time.sleep(0.2)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nDONE  summarized={done}  skipped={skipped}  errors={errors}  total_in_file={len(data)}")


if __name__ == "__main__":
    main()
