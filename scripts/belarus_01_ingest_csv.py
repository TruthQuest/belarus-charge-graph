#!/usr/bin/env python3
"""
Viasna Belarus Political Prisoner CSV Ingester
===============================================
Step 01 of the Belarus political-persecution knowledge-graph pipeline.
Consumes the public CSV export from Viasna (prisoners.spring96.org)
and produces JSONL output for steps 02-06.

Input:  export.csv (Viasna export)
Output: data/jsonl/*.jsonl, data/raw/*, data/manifest.json
"""
from __future__ import annotations
import csv, hashlib, json, logging, os, re, shutil, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

OUT_ROOT = Path("data")
RAW_DIR = OUT_ROOT / "raw"
JSONL_DIR = OUT_ROOT / "jsonl"
MANIFEST_PATH = OUT_ROOT / "manifest.json"

# Article number extraction: "Art. 342", "Art. 361-4", "Art. 130-1"
ART_NUM_RE = re.compile(r'Art\.\s*(\d+(?:-\d+)?)')
# Full article text: "Art. 342 of the Criminal Code — Description"
ART_FULL_RE = re.compile(r'(Art\.\s*\d+(?:-\d+)?(?:\s+of the Criminal Code)?(?:\s*[—–-]\s*.+)?)')

_SLUG_RE = re.compile(r"[^a-z0-9]+")
def slugify(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-")[:120]

console = Console()
logging.basicConfig(level=logging.INFO, format="%(message)s",
                    handlers=[RichHandler(console=console, show_path=False)])
log = logging.getLogger("viasna-ingest")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1<<16), b""): h.update(chunk)
    return h.hexdigest()

def write_jsonl(records: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in records: f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log.info("  wrote %d records to %s", len(records), path.name)

def symlink_ru(en_path: Path) -> None:
    ru = Path(str(en_path).replace("__en.", "__ru."))
    if ru.exists() or ru.is_symlink(): ru.unlink()
    ru.symlink_to(en_path.name)

def parse_articles(raw: str) -> list[dict[str, str]]:
    """Parse 'Art. 342 ...; Art. 368 ...' into structured records."""
    results = []
    if not raw: return results
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    for p in parts:
        m = ART_NUM_RE.search(p)
        if m:
            num = m.group(1)
            # Extract description after the dash
            desc_m = re.search(r'[—–-]\s*(.+)', p)
            desc = desc_m.group(1).strip() if desc_m else None
            results.append({
                "notation": num,
                "full_text": p.strip(),
                "description": desc,
            })
    return results

def extract_articles(rows: list[dict[str, str]]) -> list[dict]:
    seen: dict[str, dict] = {}
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        parsed = parse_articles(row.get("articles", ""))
        for art in parsed:
            n = art["notation"]
            if n in seen: continue
            seen[n] = {
                "_collection": "articles", "_language": "en",
                "_source": "viasna_csv", "_fetched_at": now,
                "record": {
                    "id": f"art-{n}",
                    "type": "article",
                    "attributes": {
                        "article_number": n,
                        "article_title": art["full_text"],
                        "article_description": art["description"],
                    },
                },
            }
    return list(seen.values())

def extract_persons(rows: list[dict[str, str]]) -> list[dict]:
    seen: dict[str, dict] = {}
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        pid = row.get("id", "").strip()
        if not pid or pid in seen: continue
        parsed = parse_articles(row.get("articles", ""))
        person_articles = [{"article_number": a["notation"]} for a in parsed]
        seen[pid] = {
            "_collection": "persons", "_language": "en",
            "_source": "viasna_csv", "_fetched_at": now,
            "record": {
                "id": pid,
                "type": "person",
                "attributes": {
                    "person_title": row.get("name", "").strip() or f"Person {pid}",
                    "person_gender_en": row.get("gender", "").strip(),
                    "person_imprisoned": row.get("status", "").strip() in ("imprisoned", "active"),
                    "person_persecuted": True,
                    "person_birthday": row.get("birthday", "").strip() or None,
                    "person_status": row.get("status", "").strip(),
                    "person_articles": person_articles,
                    "person_clusters": row.get("clusters", "").strip() or None,
                    "person_penalty": row.get("penalty", "").strip() or None,
                    "person_prison": row.get("prison", "").strip() or None,
                    "person_died": row.get("died", "").strip() or None,
                    "person_fake_terrorist_list": row.get("fake_terrorist_list", "").strip() or None,
                },
                "references": {"persecutions": [{"id": pid}]},
            },
        }
    return list(seen.values())

def extract_persecutions(rows: list[dict[str, str]]) -> list[dict]:
    records = []
    now = datetime.now(timezone.utc).isoformat()
    for row in rows:
        pid = row.get("id", "").strip()
        if not pid: continue
        parsed = parse_articles(row.get("articles", ""))
        article_refs = [{"id": f"art-{a['notation']}", "article_number": a["notation"]} for a in parsed]
        arrested = row.get("arrested", "").strip()
        year = arrested[:4] if arrested and len(arrested) >= 4 and arrested[:4].isdigit() else None
        records.append({
            "_collection": "persecutions", "_language": "en",
            "_source": "viasna_csv", "_fetched_at": now,
            "record": {
                "id": pid,
                "type": "persecution",
                "attributes": {
                    "persecution_title": f"Persecution of {row.get('name','').strip() or 'Person ' + pid}",
                    "persecution_started": arrested if arrested and not arrested.startswith("rele") else None,
                    "persecution_started_year": year,
                    "persecution_imprisoned": row.get("status", "").strip() in ("imprisoned", "active"),
                    "persecution_actual": row.get("status", "").strip() in ("imprisoned", "active", "serving"),
                    "person_articles": [{"article_number": a["notation"]} for a in parsed],
                    "status": row.get("status", "").strip(),
                    "penalty": row.get("penalty", "").strip() or None,
                    "prison": row.get("prison", "").strip() or None,
                    "judge": row.get("judge", "").strip() or None,
                    "clusters": row.get("clusters", "").strip() or None,
                    "verdict_date": row.get("verdict_date", "").strip() or None,
                    "release_date": row.get("release_date", "").strip() or None,
                    "died": row.get("died", "").strip() or None,
                },
                "references": {"articles": article_refs},
            },
        })
    return records

def main() -> int:
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("export.csv")
    if not csv_path.exists():
        log.error("CSV not found: %s", csv_path)
        return 2

    log.info("Viasna Belarus CSV ingest")
    log.info("  Input: %s", csv_path.resolve())

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    JSONL_DIR.mkdir(parents=True, exist_ok=True)

    raw_copy = RAW_DIR / csv_path.name
    shutil.copy2(csv_path, raw_copy)
    source_hash = sha256_file(raw_copy)
    (RAW_DIR / f"{csv_path.name}.sha256").write_text(source_hash + "\n")

    with csv_path.open("r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    log.info("  Loaded %d rows", len(rows))

    articles = extract_articles(rows)
    write_jsonl(articles, JSONL_DIR / "articles__en.jsonl")
    symlink_ru(JSONL_DIR / "articles__en.jsonl")

    persons = extract_persons(rows)
    write_jsonl(persons, JSONL_DIR / "persons__en.jsonl")
    symlink_ru(JSONL_DIR / "persons__en.jsonl")

    persecutions = extract_persecutions(rows)
    write_jsonl(persecutions, JSONL_DIR / "persecutions__en.jsonl")
    symlink_ru(JSONL_DIR / "persecutions__en.jsonl")

    # Empty stubs
    for coll in ["cities","locations","criminal_cases","protest_events",
                 "evaluations","sentences","restraint_measures","imprisonments"]:
        for lang in ("en","ru"):
            stub = JSONL_DIR / f"{coll}__{lang}.jsonl"
            if not stub.exists(): stub.write_text("")

    manifest = {
        "source": str(csv_path.resolve()), "source_sha256": source_hash,
        "source_type": "viasna_csv", "row_count": len(rows),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "entity_counts": {"articles": len(articles), "persons": len(persons), "persecutions": len(persecutions)},
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    t = Table(title="Belarus CSV ingest summary")
    t.add_column("entity"); t.add_column("count", justify="right")
    t.add_row("CSV rows", str(len(rows)))
    t.add_row("articles", str(len(articles)))
    t.add_row("persons", str(len(persons)))
    t.add_row("persecutions", str(len(persecutions)))
    console.print(t)
    return 0

if __name__ == "__main__":
    sys.exit(main())