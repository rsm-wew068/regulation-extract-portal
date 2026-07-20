"""
Classify each document's PDF as Text / Mixed / Images by inspecting the actual
file with PyMuPDF — does it embed sizable raster images (visual content the
text layer doesn't capture)?

- Images : >=1 page has a raster image covering >=30% of the page (scanned sheet,
           full-page photo, rasterized plan). Paperless text won't capture these.
- Mixed  : has raster images but none large (logos / small figures).
- Text   : no raster images (pure vector + text).

Writes the result to a 'Source' custom field.

Usage:
    .venv/bin/python portal/scripts/classify.py --limit 5    # smoke test
    .venv/bin/python portal/scripts/classify.py --dry-run    # analyze all, write nothing
    .venv/bin/python portal/scripts/classify.py              # analyze + write Source
"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import fitz  # PyMuPDF
import httpx
from dotenv import load_dotenv

PORTAL_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PORTAL_DIR / ".env")

URL = os.environ["PAPERLESS_API_URL"].rstrip("/")
TOKEN = os.environ["PAPERLESS_API_TOKEN"]
H = {"Authorization": f"Token {TOKEN}"}
FIELD_NAME = "Source"
MIN_IMAGE_AREA_RATIO = 0.30  # image covers >=30% of page => real image content


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


def ensure_field(client):
    r = client.get(f"{URL}/api/custom_fields/", timeout=30)
    r.raise_for_status()
    for f in r.json()["results"]:
        if f["name"] == FIELD_NAME:
            return f["id"]
    r = client.post(
        f"{URL}/api/custom_fields/",
        headers={**H, "Content-Type": "application/json"},
        json={"name": FIELD_NAME, "data_type": "string"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def analyze(pdf_bytes):
    """Return (page_count, big_image_pages, total_images)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    big = 0
    total = 0
    pages = doc.page_count
    for page in doc:
        page_area = abs(page.rect.width * page.rect.height) or 1
        imgs = page.get_images(full=True)
        total += len(imgs)
        page_has_big = False
        for img in imgs:
            xref = img[0]
            try:
                rects = page.get_image_rects(xref)
            except Exception:
                rects = []
            for r in rects:
                if abs(r.width * r.height) / page_area >= MIN_IMAGE_AREA_RATIO:
                    page_has_big = True
                    break
            if page_has_big:
                break
        if page_has_big:
            big += 1
    doc.close()
    return pages, big, total


def classify(big, total):
    if big >= 1:
        return "Images"
    if total > 0:
        return "Mixed"
    return "Text"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="analyze all, write nothing")
    ap.add_argument("--limit", type=int, default=0, help="max docs (0 = all)")
    args = ap.parse_args()

    counts = {"Text": 0, "Mixed": 0, "Images": 0}
    n = 0
    with httpx.Client(headers=H) as c:
        fid = None if args.dry_run else ensure_field(c)
        for doc in list_docs(c):
            if args.limit and n >= args.limit:
                break
            n += 1
            try:
                r = c.get(f"{URL}/api/documents/{doc['id']}/download/", timeout=180)
                r.raise_for_status()
                pages, big, total = analyze(r.content)
                cat = classify(big, total)
            except Exception as e:
                print(f"  #{doc['id']} ERROR: {e}")
                continue
            counts[cat] += 1
            if not args.dry_run:
                # merge: Paperless replaces the whole custom_fields list on PATCH
                current = {it["field"]: it.get("value") for it in doc.get("custom_fields", [])}
                current[fid] = cat
                c.patch(
                    f"{URL}/api/documents/{doc['id']}/",
                    headers={**H, "Content-Type": "application/json"},
                    json={"custom_fields": [{"field": k, "value": v} for k, v in current.items()]},
                    timeout=60,
                )
            print(f"  #{doc['id']:>3} [{cat:<6}] pages={pages:>3} big_img_pages={big:>2} imgs={total:>3}  {doc.get('title','')[:40]}")
            time.sleep(0.05)

    print(f"\nclassification ({n} processed):", counts)


if __name__ == "__main__":
    main()
