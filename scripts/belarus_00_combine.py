#!/usr/bin/env python3
"""
Belarus Step 00: Combine and deduplicate Viasna CSV exports.
Merges multiple export files, deduplicates by ID, and writes
a single clean CSV for the pipeline.

Usage: python belarus_00_combine.py export.csv export2.csv
Output: data/belarus_combined.csv
"""
import csv, logging, sys
from pathlib import Path
from collections import Counter
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

OUT = Path("data/belarus_combined.csv")
OUT.parent.mkdir(exist_ok=True)

console = Console()
logging.basicConfig(level=logging.INFO, format="%(message)s",
                    handlers=[RichHandler(console=console, show_path=False)])
log = logging.getLogger("combine")


def main():
    if len(sys.argv) < 2:
        log.error("Usage: python belarus_00_combine.py file1.csv file2.csv [file3.csv ...]")
        return 2

    all_rows = {}
    status_counts = Counter()
    file_counts = {}

    for path_str in sys.argv[1:]:
        path = Path(path_str)
        if not path.exists():
            log.error("Not found: %s", path)
            return 2

        with path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            n_new = 0
            n_dup = 0
            for row in reader:
                rid = row.get("id", "").strip()
                if not rid:
                    continue
                status = row.get("status", "").strip()
                if rid in all_rows:
                    # Keep the version with more data (prefer active/former over np)
                    existing_status = all_rows[rid].get("status", "")
                    if status in ("active", "former") and existing_status not in ("active", "former"):
                        all_rows[rid] = row
                    n_dup += 1
                else:
                    all_rows[rid] = row
                    n_new += 1

        file_counts[path.name] = {"new": n_new, "duplicates": n_dup}
        log.info("Loaded %s: %d new, %d duplicates", path.name, n_new, n_dup)

    # Count statuses
    for row in all_rows.values():
        status_counts[row.get("status", "")] += 1

    # Count articles
    has_articles = sum(1 for row in all_rows.values() if row.get("articles", "").strip())

    # Collect ALL fieldnames from all files
    all_fieldnames = []
    for path_str in sys.argv[1:]:
        with Path(path_str).open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for fn in reader.fieldnames:
                if fn and fn not in all_fieldnames:
                    all_fieldnames.append(fn)

    # Write combined CSV
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=all_fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in all_rows.values():
            clean = {k: v for k, v in row.items() if k is not None}
            w.writerow(clean)

    log.info("Written: %s", OUT)

    t = Table(title="Belarus combined dataset")
    t.add_column("metric"); t.add_column("count", justify="right")
    t.add_row("total records (deduplicated)", str(len(all_rows)))
    t.add_row("with articles", str(has_articles))
    for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
        label = {"active": "active (currently imprisoned)", "former": "former (released)", "np": "np (not political / other)"}.get(status, status)
        t.add_row(f"  status: {label}", str(count))
    for fname, counts in file_counts.items():
        t.add_row(f"  from {fname}", f"{counts['new']} new, {counts['duplicates']} dup")
    console.print(t)

    return 0


if __name__ == "__main__":
    sys.exit(main())