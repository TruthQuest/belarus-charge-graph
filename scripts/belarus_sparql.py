#!/usr/bin/env python3
"""
SPARQL queries against the merged Belarus knowledge graph.
Demonstrates the A-Box + SKOS payoff.

Usage: python belarus_sparql.py
"""
import logging, sys
from pathlib import Path
from rdflib import Graph
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

logging.disable(logging.WARNING)
console = Console()
logging.basicConfig(level=logging.INFO, format="%(message)s",
                    handlers=[RichHandler(console=console, show_path=False)])
log = logging.getLogger("sparql")

MERGED = Path("ontology/belarus_persecutions_merged.ttl")

QUERIES = {
    "Prosecutions by ICCPR article violated": """
        PREFIX ont: <http://repressions.belarus/ontology/>
        PREFIX iccpr: <http://www.ohchr.org/EN/ProfessionalInterest/Pages/CCPR#>

        SELECT ?iccpr_article (COUNT(DISTINCT ?persecution) AS ?n_prosecutions)
        WHERE {
            ?persecution a ont:Persecution ;
                         ont:hasCharge ?charge .
            ?charge ont:iccprViolation ?iccpr_article .
        }
        GROUP BY ?iccpr_article
        ORDER BY DESC(?n_prosecutions)
    """,

    "Top 10 charges with facial character": """
        PREFIX ont: <http://repressions.belarus/ontology/>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

        SELECT ?notation ?character (COUNT(DISTINCT ?pers) AS ?n)
        WHERE {
            ?pers a ont:Persecution ;
                  ont:hasCharge ?charge .
            ?charge skos:notation ?notation ;
                    ont:facialCharacter ?character .
        }
        GROUP BY ?notation ?character
        ORDER BY DESC(?n)
        LIMIT 10
    """,

    "Persons under facially incompatible statutes": """
        PREFIX ont: <http://repressions.belarus/ontology/>

        SELECT (COUNT(DISTINCT ?person) AS ?n_persons)
        WHERE {
            ?pers a ont:Persecution ;
                  ont:hasPerson ?person ;
                  ont:hasCharge ?charge .
            ?charge ont:facialCharacter "facially_incompatible" .
        }
    """,

    "Currently imprisoned under facially incompatible charges": """
        PREFIX ont: <http://repressions.belarus/ontology/>

        SELECT (COUNT(DISTINCT ?person) AS ?n_imprisoned)
        WHERE {
            ?pers a ont:Persecution ;
                  ont:hasPerson ?person ;
                  ont:hasCharge ?charge .
            ?person ont:personImprisoned true .
            ?charge ont:facialCharacter "facially_incompatible" .
        }
    """,

    "Charges by type (facially incompatible vs as-applied vs weaponized)": """
        PREFIX ont: <http://repressions.belarus/ontology/>

        SELECT ?character (COUNT(DISTINCT ?pers) AS ?n_prosecutions) (COUNT(DISTINCT ?charge) AS ?n_articles)
        WHERE {
            ?pers a ont:Persecution ;
                  ont:hasCharge ?charge .
            ?charge ont:facialCharacter ?character .
        }
        GROUP BY ?character
        ORDER BY DESC(?n_prosecutions)
    """,

    "Persons prosecuted under Art. 342 who are still imprisoned": """
        PREFIX ont: <http://repressions.belarus/ontology/>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

        SELECT (COUNT(DISTINCT ?person) AS ?n)
        WHERE {
            ?pers a ont:Persecution ;
                  ont:hasPerson ?person ;
                  ont:hasCharge ?charge .
            ?charge skos:notation "342" .
            ?person ont:personImprisoned true .
        }
    """,

    "Persons charged under BOTH protest (342) AND speech (368/369) articles": """
        PREFIX ont: <http://repressions.belarus/ontology/>
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>

        SELECT (COUNT(DISTINCT ?person) AS ?n_dual_regime)
        WHERE {
            ?pers1 a ont:Persecution ;
                   ont:hasPerson ?person ;
                   ont:hasCharge ?c1 .
            ?c1 skos:notation "342" .

            ?pers2 a ont:Persecution ;
                   ont:hasPerson ?person ;
                   ont:hasCharge ?c2 .
            ?c2 skos:notation ?n2 .
            FILTER(?n2 IN ("368", "369", "367"))
        }
    """,
}


def main():
    if not MERGED.exists():
        log.error("Run steps 01-03 first: %s not found", MERGED)
        return 2

    log.info("Loading merged knowledge graph...")
    g = Graph()
    g.parse(str(MERGED), format="turtle")
    log.info("Loaded: %d triples", len(g))

    for title, query in QUERIES.items():
        log.info("\n--- %s ---", title)
        try:
            results = list(g.query(query))
            if not results:
                log.info("  (no results)")
                continue

            t = Table(title=title)
            for var in results[0].labels:
                t.add_column(str(var), justify="right" if str(var).startswith("n") else "left")
            for row in results:
                t.add_row(*[str(v).split("#")[-1] if "#" in str(v) else str(v) for v in row])
            console.print(t)
        except Exception as e:
            log.error("  Query failed: %s", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
