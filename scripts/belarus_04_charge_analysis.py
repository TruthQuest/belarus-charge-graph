#!/usr/bin/env python3
"""
Belarus Charge Co-occurrence and Regime Analysis
=================================================
Step 04 of the Belarus political-persecution knowledge-graph pipeline.

Hypotheses:
  H1  Regime shift: does charge structure differ before/after Aug 2020?
  H2  Art. 342 isolation: is the mass-protest charge standalone or stacked?
  H3  Speech cluster: do Arts. 368, 369, 367 form a distinct community?
  H4  Extremist-formation cluster: do Arts. 361-1, 361-2, 361-4, 130 cluster?
  H5  Charge stacking: does mean charge count differ pre/post 2020?

Input:  export.csv (Viasna)
Output: analysis/04_results.json, 04_charge_communities.csv, etc.
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
from scipy import stats
try:
    import community as community_louvain
except ImportError:
    print("ERROR: pip install python-louvain"); sys.exit(1)
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

ART_NUM_RE = re.compile(r'Art\.\s*(\d+(?:-\d+)?)')
PROTEST_DATE = "2020-08-09"  # Election day
PROTEST_YEAR = 2020

# Analyst hypothesized clusters
PROTEST_ARTICLES = frozenset({"342", "342-2"})
SPEECH_ARTICLES = frozenset({"368", "369", "367", "369-1", "370"})
EXTREMIST_ARTICLES = frozenset({"361-1", "361-2", "361-4", "130", "130-1"})
STREET_ARTICLES = frozenset({"342", "363", "364", "341"})

STABILITY_SEEDS = 100
PERMUTATION_ITERS = 1000
DEFAULT_RESOLUTION = 1.0
MIN_COOCCURRENCE = 2
OUT_DIR = Path("analysis")

console = Console()
OUT_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(message)s",
    handlers=[RichHandler(console=console, show_path=False),
              logging.FileHandler(OUT_DIR / "04_analysis.log", encoding="utf-8")])
log = logging.getLogger("charge-analysis")

def parse_articles_from_field(raw: str) -> list[str]:
    return [m.group(1) for m in ART_NUM_RE.finditer(raw)] if raw else []

def load_csv(path: Path) -> list[dict[str, Any]]:
    records = []
    skipped = 0
    with path.open("r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            articles = parse_articles_from_field(row.get("articles", ""))
            if not articles: skipped += 1; continue
            arrested = row.get("arrested", "").strip()
            year = int(arrested[:4]) if arrested and len(arrested) >= 4 and arrested[:4].isdigit() else None
            if arrested and not arrested[:4].isdigit(): arrested = None
            is_pre = None
            if arrested: is_pre = arrested < PROTEST_DATE
            elif year:
                if year < PROTEST_YEAR: is_pre = True
                elif year > PROTEST_YEAR: is_pre = False
            records.append({
                "id": row.get("id", ""),
                "name": row.get("name", ""),
                "articles": articles,
                "year": year,
                "date": arrested,
                "is_pre": is_pre,
                "status": row.get("status", ""),
                "gender": row.get("gender", ""),
                "clusters": row.get("clusters", ""),
                "penalty": row.get("penalty", ""),
                "imprisoned": row.get("status", "") == "imprisoned",
            })
    log.info("Loaded %d records (%d skipped: no articles)", len(records), skipped)
    return records

def build_graph(records, min_weight=MIN_COOCCURRENCE):
    G = nx.Graph()
    for r in records:
        unique = list(set(r["articles"]))
        for c in unique:
            if c not in G: G.add_node(c, count=0, pre_count=0, post_count=0)
            G.nodes[c]["count"] += 1
            if r["is_pre"] is True: G.nodes[c]["pre_count"] += 1
            elif r["is_pre"] is False: G.nodes[c]["post_count"] += 1
        for c1, c2 in combinations(unique, 2):
            if G.has_edge(c1, c2): G[c1][c2]["weight"] += 1
            else: G.add_edge(c1, c2, weight=1)
    to_rm = [(u,v) for u,v,d in G.edges(data=True) if d["weight"] < min_weight]
    G.remove_edges_from(to_rm)
    G.remove_nodes_from(list(nx.isolates(G)))
    log.info("Graph: %d nodes, %d edges (pruned %d < %d)", G.number_of_nodes(), G.number_of_edges(), len(to_rm), min_weight)
    return G

def _quick_graph(recs):
    G = nx.Graph()
    for r in recs:
        u = list(set(r["articles"]))
        for c in u:
            if c not in G: G.add_node(c, count=0)
            G.nodes[c]["count"] += 1
        for c1, c2 in combinations(u, 2):
            if G.has_edge(c1, c2): G[c1][c2]["weight"] += 1
            else: G.add_edge(c1, c2, weight=1)
    return G

def run_louvain(G, resolution=DEFAULT_RESOLUTION, seed=42):
    if G.number_of_nodes() < 2: return {}, 0.0, 0
    part = community_louvain.best_partition(G, weight="weight", resolution=resolution, random_state=seed)
    mod = community_louvain.modularity(part, G, weight="weight")
    return part, mod, len(set(part.values()))

def h1_regime_shift(records, n_perms):
    log.info("H1: Regime shift at Aug 2020 (%d perms)", n_perms)
    dated = [r for r in records if r["is_pre"] is not None]
    pre = [r for r in dated if r["is_pre"]]
    post = [r for r in dated if not r["is_pre"]]
    G_pre, G_post = _quick_graph(pre), _quick_graph(post)
    _, mod_pre, n_pre = run_louvain(G_pre)
    _, mod_post, n_post = run_louvain(G_post)
    obs_diff = abs(mod_pre - mod_post)
    null_diffs = []
    for _ in range(n_perms):
        labels = np.random.permutation([r["is_pre"] for r in dated])
        pre_s = [r for r, l in zip(dated, labels) if l]
        post_s = [r for r, l in zip(dated, labels) if not l]
        if len(pre_s) < 10 or len(post_s) < 10: continue
        _, m1, _ = run_louvain(_quick_graph(pre_s))
        _, m2, _ = run_louvain(_quick_graph(post_s))
        null_diffs.append(abs(m1 - m2))
    p = (sum(1 for d in null_diffs if d >= obs_diff) + 1) / (len(null_diffs) + 1)
    arts_pre = set(a for r in pre for a in r["articles"])
    arts_post = set(a for r in post for a in r["articles"])
    return {
        "n_pre": len(pre), "n_post": len(post),
        "modularity_pre": round(mod_pre, 4), "modularity_post": round(mod_post, 4),
        "modularity_diff": round(obs_diff, 4), "p_value": round(p, 4),
        "n_communities_pre": n_pre, "n_communities_post": n_post,
        "mean_arts_pre": round(np.mean([len(r["articles"]) for r in pre]), 3),
        "mean_arts_post": round(np.mean([len(r["articles"]) for r in post]), 3),
        "articles_only_post": sorted(arts_post - arts_pre),
    }

def h2_342_isolation(G, partition, records):
    log.info("H2: Art. 342 isolation")
    results = {}
    for art in sorted(PROTEST_ARTICLES | SPEECH_ARTICLES):
        if art not in G: results[art] = {"present": False}; continue
        with_art = [r for r in records if art in r["articles"]]
        standalone = sum(1 for r in with_art if len(r["articles"]) == 1)
        neighbors = {n: G[art][n]["weight"] for n in G.neighbors(art)}
        top_n = sorted(neighbors.items(), key=lambda x: -x[1])[:5]
        results[art] = {
            "present": True, "community": partition.get(art, -1),
            "total": len(with_art), "standalone": standalone,
            "standalone_pct": round(standalone / len(with_art) * 100, 1) if with_art else 0,
            "top_cooccurrences": [{"article": n, "count": w} for n, w in top_n],
        }
    return results

def h5_stacking(records):
    log.info("H5: Charge stacking intensity")
    pre = [r for r in records if r["is_pre"] is True]
    post = [r for r in records if r["is_pre"] is False]
    pre_c = [len(r["articles"]) for r in pre]
    post_c = [len(r["articles"]) for r in post]
    if pre_c and post_c:
        u, p = stats.mannwhitneyu(pre_c, post_c, alternative="two-sided")
    else: u, p = None, None
    return {
        "pre_mean": round(np.mean(pre_c), 3) if pre_c else None,
        "post_mean": round(np.mean(post_c), 3) if post_c else None,
        "pre_n": len(pre_c), "post_n": len(post_c),
        "mann_whitney_U": float(u) if u else None,
        "mann_whitney_p": float(p) if p else None,
    }

def compute_metrics(G, partition):
    dc = nx.degree_centrality(G)
    bc = nx.betweenness_centrality(G, weight="weight")
    cc = nx.clustering(G, weight="weight")
    rows = []
    for n in sorted(G.nodes()):
        cl = "protest" if n in PROTEST_ARTICLES else ("speech" if n in SPEECH_ARTICLES else ("extremist" if n in EXTREMIST_ARTICLES else "other"))
        rows.append({
            "article": n, "count": G.nodes[n].get("count",0),
            "pre_count": G.nodes[n].get("pre_count",0), "post_count": G.nodes[n].get("post_count",0),
            "community": partition.get(n,-1), "analyst_cluster": cl,
            "degree": G.degree(n), "weighted_degree": G.degree(n, weight="weight"),
            "degree_centrality": round(dc[n],6), "betweenness_centrality": round(bc[n],6),
            "clustering_coefficient": round(cc[n],6),
        })
    return sorted(rows, key=lambda r: -r["weighted_degree"])

def classify_persons(records, partition):
    rows = []
    for r in records:
        comms = [partition.get(a) for a in r["articles"] if a in partition]
        comms = [c for c in comms if c is not None]
        dominant = Counter(comms).most_common(1)[0][0] if comms else -1
        rows.append({
            "id": r["id"], "name": r["name"], "articles": ",".join(r["articles"]),
            "n_articles": len(r["articles"]), "year": r["year"], "pre": r["is_pre"],
            "community": dominant, "status": r["status"], "clusters": r["clusters"],
        })
    return rows

def export_cooccurrence(G, path):
    nodes = sorted(G.nodes())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([""] + nodes)
        for n1 in nodes:
            row = [n1]
            for n2 in nodes:
                if n1 == n2: row.append(G.nodes[n1].get("count",0))
                elif G.has_edge(n1, n2): row.append(G[n1][n2]["weight"])
                else: row.append(0)
            w.writerow(row)

def summarize_communities(partition, G):
    comms = defaultdict(list)
    for n, c in partition.items(): comms[c].append(n)
    summary = {}
    for cid in sorted(comms):
        members = sorted(comms[cid], key=lambda n: -G.nodes[n].get("count",0))
        total = sum(G.nodes[n].get("count",0) for n in members)
        summary[str(cid)] = {
            "n_articles": len(members), "total_persecutions": total,
            "top_5": [{"article": n, "count": G.nodes[n].get("count",0)} for n in members[:5]],
            "all_members": members,
        }
    return summary

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=Path, nargs="?", default=Path("export.csv"))
    parser.add_argument("--permutations", type=int, default=PERMUTATION_ITERS)
    parser.add_argument("--resolution", type=float, default=DEFAULT_RESOLUTION)
    parser.add_argument("--min-cooccurrence", type=int, default=MIN_COOCCURRENCE)
    args = parser.parse_args()
    if not args.csv_path.exists(): log.error("Not found: %s", args.csv_path); return 2

    log.info("Step 04: Belarus charge analysis")
    records = load_csv(args.csv_path)
    G = build_graph(records, min_weight=args.min_cooccurrence)
    partition, modularity, n_comm = run_louvain(G, resolution=args.resolution)
    log.info("Louvain: %d communities, Q=%.4f", n_comm, modularity)

    comm_summary = summarize_communities(partition, G)
    for cid, info in comm_summary.items():
        top = ", ".join(f"{t['article']}({t['count']})" for t in info["top_5"][:3])
        log.info("  C%s: %d arts, %d pers. Top: %s", cid, info["n_articles"], info["total_persecutions"], top)

    h1 = h1_regime_shift(records, args.permutations)
    log.info("H1: mod_diff=%.4f, p=%.4f", h1["modularity_diff"], h1["p_value"])

    h2 = h2_342_isolation(G, partition, records)
    for art in ["342", "368", "369", "130"]:
        info = h2.get(art, {})
        if info.get("present"):
            log.info("H2 %s: standalone=%d/%d (%.1f%%), comm=%d", art, info["standalone"], info["total"], info["standalone_pct"], info["community"])

    h5 = h5_stacking(records)
    log.info("H5: pre=%.2f, post=%.2f, p=%s", h5["pre_mean"] or 0, h5["post_mean"] or 0, f"{h5['mann_whitney_p']:.4f}" if h5["mann_whitney_p"] else "N/A")

    metrics = compute_metrics(G, partition)
    classifications = classify_persons(records, partition)
    export_cooccurrence(G, OUT_DIR / "04_cooccurrence_matrix.csv")

    # Check cluster coherence
    h3_speech = {partition.get(a) for a in SPEECH_ARTICLES if a in partition} - {None}
    h4_ext = {partition.get(a) for a in EXTREMIST_ARTICLES if a in partition} - {None}

    results = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus": {"total": len(records), "total_persons": len({r["id"] for r in records}), "total_articles": len(set(a for r in records for a in r["articles"]))},
        "graph": {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "density": round(nx.density(G),6)},
        "primary_louvain": {"resolution": args.resolution, "n_communities": n_comm, "modularity": round(modularity,6)},
        "communities": comm_summary,
        "H1_regime_shift": h1,
        "H2_isolation": h2,
        "H3_speech_cluster": {"articles": list(SPEECH_ARTICLES), "communities": sorted(h3_speech), "single_community": len(h3_speech) == 1},
        "H4_extremist_cluster": {"articles": list(EXTREMIST_ARTICLES), "communities": sorted(h4_ext), "single_community": len(h4_ext) == 1},
        "H5_stacking": h5,
    }

    (OUT_DIR / "04_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (OUT_DIR / "04_charge_communities.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=metrics[0].keys()); w.writeheader(); w.writerows(metrics)
    with (OUT_DIR / "04_person_regime.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=classifications[0].keys()); w.writeheader(); w.writerows(classifications)

    t = Table(title="Belarus charge analysis")
    t.add_column("metric"); t.add_column("value", justify="right")
    t.add_row("records", str(len(records)))
    t.add_row("graph nodes", str(G.number_of_nodes()))
    t.add_row("communities", str(n_comm))
    t.add_row("modularity", f"{modularity:.4f}")
    t.add_row("H1 regime shift p", f"{h1['p_value']:.4f}")
    t.add_row("H5 stacking pre/post", f"{h5['pre_mean']:.2f} / {h5['post_mean']:.2f}")
    console.print(t)
    return 0

if __name__ == "__main__":
    sys.exit(main())
