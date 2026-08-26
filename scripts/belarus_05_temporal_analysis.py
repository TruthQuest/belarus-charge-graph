#!/usr/bin/env python3
"""
Belarus Temporal Dynamics of Political Persecution Charging
============================================================
Step 05: year-by-year analysis, sliding window, structural break detection.

Candidate breaks:
  2020  August election protests (mass arrest wave)
  2021  Post-protest sustained repression
  2022  Ukraine war, new extremist articles
  2023  Continued tightening

Input:  export.csv
Output: analysis/05_temporal_results.json, 05_yearly_summary.csv, 05_break_tests.csv
"""
from __future__ import annotations
import argparse, csv, json, logging, re, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any
import networkx as nx
import numpy as np
try:
    import community as community_louvain
except ImportError:
    print("ERROR: pip install python-louvain"); sys.exit(1)
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

ART_NUM_RE = re.compile(r'Art\.\s*(\d+(?:-\d+)?)')
MIN_YEAR = 2020
CANDIDATE_BREAKS = [2020, 2021, 2022, 2023]
WINDOW_SIZE = 2
LOUVAIN_RES = 1.0
PERMUTATION_ITERS = 500
OUT_DIR = Path("analysis")

PROTEST_ARTICLES = {"342", "342-2"}
SPEECH_ARTICLES = {"368", "369", "367", "369-1", "370"}
EXTREMIST_ARTICLES = {"361-1", "361-2", "361-4", "130", "130-1"}

console = Console()
OUT_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(message)s",
    handlers=[RichHandler(console=console, show_path=False),
              logging.FileHandler(OUT_DIR / "05_temporal.log", encoding="utf-8")])
log = logging.getLogger("temporal")

def parse_arts(raw): return [m.group(1) for m in ART_NUM_RE.finditer(raw)] if raw else []

def load_csv(path):
    recs = []
    with path.open("r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            arts = parse_arts(row.get("articles",""))
            if not arts: continue
            arrested = row.get("arrested","").strip()
            year = int(arrested[:4]) if arrested and arrested[:4].isdigit() else None
            recs.append({"articles": arts, "year": year, "date": arrested if arrested and arrested[:4].isdigit() else None,
                         "gender": row.get("gender",""), "status": row.get("status",""), "clusters": row.get("clusters","")})
    return recs

def build_graph(recs, min_w=1):
    G = nx.Graph()
    for r in recs:
        u = list(set(r["articles"]))
        for c in u:
            if c not in G: G.add_node(c, count=0)
            G.nodes[c]["count"] += 1
        for c1, c2 in combinations(u, 2):
            if G.has_edge(c1, c2): G[c1][c2]["weight"] += 1
            else: G.add_edge(c1, c2, weight=1)
    if min_w > 1:
        rm = [(u,v) for u,v,d in G.edges(data=True) if d["weight"] < min_w]
        G.remove_edges_from(rm); G.remove_nodes_from(list(nx.isolates(G)))
    return G

def louvain(G):
    if G.number_of_nodes() < 2: return {}, 0.0, 0
    p = community_louvain.best_partition(G, weight="weight", resolution=LOUVAIN_RES, random_state=42)
    return p, community_louvain.modularity(p, G, weight="weight"), len(set(p.values()))

def yearly_analysis(recs):
    by_year = defaultdict(list)
    for r in recs:
        if r["year"] and r["year"] >= MIN_YEAR: by_year[r["year"]].append(r)
    rows, parts = [], {}
    first_seen = {}
    for year in sorted(by_year):
        data = by_year[year]
        n = len(data)
        all_arts = Counter()
        for r in data:
            for a in r["articles"]:
                all_arts[a] += 1
                if a not in first_seen: first_seen[a] = year
        new = [a for a, y in first_seen.items() if y == year]
        art_counts = [len(r["articles"]) for r in data]
        G = build_graph(data)
        part, mod, nc = louvain(G)
        parts[year] = part
        rows.append({
            "year": year, "n_persecutions": n, "n_articles_used": len(all_arts),
            "n_new_articles": len(new), "new_articles": ",".join(sorted(new)),
            "mean_articles_per_case": round(np.mean(art_counts), 3),
            "single_charge_pct": round(sum(1 for c in art_counts if c == 1) / n * 100, 1),
            "n_communities": nc, "modularity": round(mod, 4),
            "graph_nodes": G.number_of_nodes(), "graph_edges": G.number_of_edges(),
            "top5_articles": ",".join(f"{a}({c})" for a, c in all_arts.most_common(5)),
            "pct_female": round(sum(1 for r in data if r["gender"] == "female") / n * 100, 1),
        })
    return rows, parts

def test_break(recs, break_year, n_perms):
    dated = [r for r in recs if r["year"] and r["year"] >= MIN_YEAR]
    pre = [r for r in dated if r["year"] < break_year]
    post = [r for r in dated if r["year"] >= break_year]
    if len(pre) < 20 or len(post) < 20:
        return {"break_year": break_year, "skipped": True}
    G1, G2 = build_graph(pre), build_graph(post)
    _, m1, n1 = louvain(G1)
    _, m2, n2 = louvain(G2)
    obs = abs(m1 - m2)
    nulls = []
    years = np.array([r["year"] for r in dated])
    for _ in range(n_perms):
        sy = np.random.permutation(years)
        p_s = [r for r, y in zip(dated, sy) if y < break_year]
        q_s = [r for r, y in zip(dated, sy) if y >= break_year]
        if len(p_s) < 10 or len(q_s) < 10: continue
        _, a, _ = louvain(build_graph(p_s))
        _, b, _ = louvain(build_graph(q_s))
        nulls.append(abs(a - b))
    p = (sum(1 for d in nulls if d >= obs) + 1) / (len(nulls) + 1)
    return {
        "break_year": break_year, "n_pre": len(pre), "n_post": len(post),
        "modularity_pre": round(m1, 4), "modularity_post": round(m2, 4),
        "modularity_diff": round(obs, 4), "modularity_p_value": round(p, 4),
        "n_communities_pre": n1, "n_communities_post": n2,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path, nargs="?", default=Path("export.csv"))
    parser.add_argument("--permutations", type=int, default=PERMUTATION_ITERS)
    args = parser.parse_args()
    if not args.csv_path.exists(): log.error("Not found: %s", args.csv_path); return 2

    log.info("Step 05: Belarus temporal dynamics")
    recs = load_csv(args.csv_path)
    log.info("Loaded %d records", len(recs))

    yearly_rows, yearly_parts = yearly_analysis(recs)
    for yr in yearly_rows:
        log.info("  %d: n=%d, arts=%d, mean_stack=%.2f, single=%.1f%%, comms=%d, Q=%.3f",
                 yr["year"], yr["n_persecutions"], yr["n_articles_used"],
                 yr["mean_articles_per_case"], yr["single_charge_pct"],
                 yr["n_communities"], yr["modularity"])

    break_results = []
    for by in CANDIDATE_BREAKS:
        log.info("  Testing break at %d...", by)
        result = test_break(recs, by, args.permutations)
        if not result.get("skipped"):
            log.info("    mod_diff=%.4f, p=%.4f", result["modularity_diff"], result["modularity_p_value"])
        break_results.append(result)

    # Write outputs
    if yearly_rows:
        with (OUT_DIR / "05_yearly_summary.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=yearly_rows[0].keys()); w.writeheader(); w.writerows(yearly_rows)

    bfields = ["break_year","n_pre","n_post","modularity_pre","modularity_post","modularity_diff","modularity_p_value","n_communities_pre","n_communities_post"]
    with (OUT_DIR / "05_break_tests.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=bfields, extrasaction="ignore"); w.writeheader(); w.writerows(break_results)

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_records": len(recs), "yearly_summary": yearly_rows,
        "structural_breaks": break_results,
        "most_significant_break": min((b for b in break_results if not b.get("skipped")), key=lambda b: b["modularity_p_value"], default=None),
    }
    (OUT_DIR / "05_temporal_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    t = Table(title="Belarus structural break tests")
    t.add_column("break year"); t.add_column("mod diff", justify="right"); t.add_column("p", justify="right")
    for b in break_results:
        if b.get("skipped"): continue
        t.add_row(str(b["break_year"]), f"{b['modularity_diff']:.4f}", f"{b['modularity_p_value']:.4f}")
    console.print(t)

    t2 = Table(title="Belarus yearly summary")
    t2.add_column("year"); t2.add_column("n", justify="right"); t2.add_column("mean arts", justify="right")
    t2.add_column("single %", justify="right"); t2.add_column("comms", justify="right"); t2.add_column("Q", justify="right")
    for yr in yearly_rows:
        t2.add_row(str(yr["year"]), str(yr["n_persecutions"]), f"{yr['mean_articles_per_case']:.2f}",
                   f"{yr['single_charge_pct']:.1f}", str(yr["n_communities"]), f"{yr['modularity']:.3f}")
    console.print(t2)
    return 0

if __name__ == "__main__":
    sys.exit(main())
