#!/usr/bin/env python3
"""
Belarus BFO-aligned OWL A-Box Builder
=======================================
Step 03: T-Box schema + A-Box instances from Viasna data.
Merges with SKOS vocabulary from step 02.

Inputs:  data/jsonl/persecutions__en.jsonl, data/jsonl/persons__en.jsonl,
         data/jsonl/articles__en.jsonl, ontology/by_criminal_code_skos.ttl
Outputs: ontology/belarus_persecutions_tbox.ttl
         ontology/belarus_persecutions_abox.ttl
         ontology/belarus_persecutions_merged.ttl
"""
import csv, json, logging, re, sys
from datetime import datetime, timezone
from pathlib import Path
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, XSD
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

JSONL_DIR = Path("data/jsonl")
SKOS_PATH = Path("ontology/by_criminal_code_skos.ttl")
OUT_DIR = Path("ontology")
OUT_DIR.mkdir(parents=True, exist_ok=True)

BASE = "http://repressions.belarus/ontology/"
INST = "http://repressions.belarus/data/"
SCHEME = "http://repressions.belarus/vocab/by-criminal-code/"
ONT = Namespace(BASE)
DATA = Namespace(INST)
BYCC = Namespace(SCHEME)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
def slugify(s): return _SLUG_RE.sub("-", s.lower()).strip("-")[:120]

console = Console()
logging.basicConfig(level=logging.INFO, format="%(message)s",
                    handlers=[RichHandler(console=console, show_path=False)])
log = logging.getLogger("abox")


def load_jsonl(path):
    if not path.exists(): return []
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: records.append(json.loads(line))
    return records


def build_tbox() -> Graph:
    g = Graph()
    g.bind("", ONT); g.bind("owl", OWL); g.bind("rdfs", RDFS)
    g.bind("dcterms", DCTERMS); g.bind("prov", PROV)

    ont = URIRef(BASE.rstrip("/"))
    g.add((ont, RDF.type, OWL.Ontology))
    g.add((ont, DCTERMS.title, Literal("Belarus Political Persecution Ontology", lang="en")))
    g.add((ont, DCTERMS.created, Literal(datetime.now(timezone.utc).date().isoformat(), datatype=XSD.date)))
    g.add((ont, DCTERMS.source, URIRef("https://prisoners.spring96.org/")))

    classes = {
        ONT.Person: "Person", ONT.Persecution: "Persecution",
        ONT.ChargeArticle: "ChargeArticle", ONT.Location: "Location",
    }
    for cls, label in classes.items():
        g.add((cls, RDF.type, OWL.Class))
        g.add((cls, RDFS.label, Literal(label, lang="en")))

    obj_props = {
        ONT.hasCharge: ("has charge", ONT.Persecution, ONT.ChargeArticle),
        ONT.hasPerson: ("has person", ONT.Persecution, ONT.Person),
    }
    for prop, (label, domain, range_) in obj_props.items():
        g.add((prop, RDF.type, OWL.ObjectProperty))
        g.add((prop, RDFS.label, Literal(label, lang="en")))
        g.add((prop, RDFS.domain, domain)); g.add((prop, RDFS.range, range_))

    data_props = {
        ONT.personName: ("name", ONT.Person, XSD.string),
        ONT.personGender: ("gender", ONT.Person, XSD.string),
        ONT.personStatus: ("status", ONT.Person, XSD.string),
        ONT.arrestedDate: ("arrested date", ONT.Persecution, XSD.date),
        ONT.penalty: ("penalty", ONT.Persecution, XSD.string),
        ONT.prison: ("prison", ONT.Persecution, XSD.string),
        ONT.judge: ("judge", ONT.Persecution, XSD.string),
        ONT.chargeNotation: ("charge notation", ONT.ChargeArticle, XSD.string),
        ONT.clusters: ("clusters", ONT.Persecution, XSD.string),
        ONT.personImprisoned: ("imprisoned", ONT.Person, XSD.boolean),
        ONT.personDied: ("died", ONT.Person, XSD.string),
    }
    for prop, (label, domain, range_) in data_props.items():
        g.add((prop, RDF.type, OWL.DatatypeProperty))
        g.add((prop, RDFS.label, Literal(label, lang="en")))
        g.add((prop, RDFS.domain, domain)); g.add((prop, RDFS.range, range_))

    return g


def build_abox() -> Graph:
    g = Graph()
    g.bind("", ONT); g.bind("data", DATA); g.bind("bycc", BYCC)
    g.bind("prov", PROV); g.bind("dcterms", DCTERMS)

    persecutions = load_jsonl(JSONL_DIR / "persecutions__en.jsonl")
    persons = load_jsonl(JSONL_DIR / "persons__en.jsonl")
    articles = load_jsonl(JSONL_DIR / "articles__en.jsonl")
    log.info("Loaded: %d persecutions, %d persons, %d articles",
             len(persecutions), len(persons), len(articles))

    # Articles
    seen_articles = set()
    for obj in articles:
        rec = obj.get("record", {})
        attrs = rec.get("attributes", {})
        notation = attrs.get("article_number", "")
        if not notation: continue
        slug = f"art_{slugify(notation)}"
        uri = BYCC[slug]
        if notation not in seen_articles:
            seen_articles.add(notation)
            g.add((uri, RDF.type, ONT.ChargeArticle))
            g.add((uri, ONT.chargeNotation, Literal(notation)))
            title = attrs.get("article_title", "")
            if title:
                g.add((uri, RDFS.label, Literal(title, lang="en")))

    # Persons
    seen_persons = set()
    for obj in persons:
        rec = obj.get("record", {})
        pid = rec.get("id", "")
        if not pid or pid in seen_persons: continue
        seen_persons.add(pid)
        attrs = rec.get("attributes", {})
        uri = DATA[f"person/{slugify(pid)}"]
        g.add((uri, RDF.type, ONT.Person))
        name = attrs.get("person_title", "")
        if name: g.add((uri, ONT.personName, Literal(name)))
        gender = attrs.get("person_gender_en", "")
        if gender: g.add((uri, ONT.personGender, Literal(gender)))
        status = attrs.get("person_status", "")
        if status: g.add((uri, ONT.personStatus, Literal(status)))
        if attrs.get("person_imprisoned"):
            g.add((uri, ONT.personImprisoned, Literal(True, datatype=XSD.boolean)))
        died = attrs.get("person_died")
        if died: g.add((uri, ONT.personDied, Literal(died)))

    # Persecutions
    n_persecutions = 0
    for obj in persecutions:
        rec = obj.get("record", {})
        pid = rec.get("id", "")
        if not pid: continue
        attrs = rec.get("attributes", {})
        refs = rec.get("references", {})

        pers_uri = DATA[f"persecution/{slugify(pid)}"]
        n_persecutions += 1
        g.add((pers_uri, RDF.type, ONT.Persecution))

        # Link to person
        person_uri = DATA[f"person/{slugify(pid)}"]
        g.add((pers_uri, ONT.hasPerson, person_uri))

        # Dates
        arrested = attrs.get("persecution_started", "")
        if arrested and len(arrested) >= 10:
            first_date = arrested.split(";")[0].strip()[:10]
            if len(first_date) == 10 and first_date.count("-") == 2:
                try:
                    g.add((pers_uri, ONT.arrestedDate, Literal(first_date, datatype=XSD.date)))
                except: pass

        # Attributes
        for field, prop in [("penalty", ONT.penalty), ("prison", ONT.prison),
                            ("judge", ONT.judge), ("clusters", ONT.clusters)]:
            val = attrs.get(field, "")
            if val: g.add((pers_uri, prop, Literal(val)))

        # Charges
        article_refs = refs.get("articles", [])
        person_articles = attrs.get("person_articles", [])
        charge_notations = set()
        for ref in article_refs:
            n = ref.get("article_number", "")
            if n: charge_notations.add(n)
        for art in person_articles:
            n = art.get("article_number", "")
            if n: charge_notations.add(n)
        for notation in charge_notations:
            slug = f"art_{slugify(notation)}"
            g.add((pers_uri, ONT.hasCharge, BYCC[slug]))

    log.info("A-Box: %d persecutions, %d persons, %d articles",
             n_persecutions, len(seen_persons), len(seen_articles))
    return g


def main():
    log.info("Step 03: Belarus A-Box builder")

    log.info("Building T-Box...")
    tbox = build_tbox()
    tbox_path = OUT_DIR / "belarus_persecutions_tbox.ttl"
    tbox.serialize(destination=str(tbox_path), format="turtle")
    log.info("T-Box: %s (%d triples)", tbox_path, len(tbox))

    log.info("Building A-Box...")
    abox = build_abox()
    abox_path = OUT_DIR / "belarus_persecutions_abox.ttl"
    abox.serialize(destination=str(abox_path), format="turtle")
    log.info("A-Box: %s (%d triples)", abox_path, len(abox))

    log.info("Merging T-Box + A-Box + SKOS...")
    merged = tbox + abox
    if SKOS_PATH.exists():
        skos = Graph()
        skos.parse(str(SKOS_PATH), format="turtle")
        merged += skos
        log.info("SKOS merged: %d triples", len(skos))
    else:
        log.warning("SKOS not found at %s", SKOS_PATH)

    merged_path = OUT_DIR / "belarus_persecutions_merged.ttl"
    merged.serialize(destination=str(merged_path), format="turtle")
    log.info("Merged: %s (%d triples)", merged_path, len(merged))

    t = Table(title="Belarus A-Box summary")
    t.add_column("component"); t.add_column("triples", justify="right")
    t.add_row("T-Box", str(len(tbox)))
    t.add_row("A-Box", str(len(abox)))
    t.add_row("SKOS", str(len(merged) - len(tbox) - len(abox)))
    t.add_row("Merged total", str(len(merged)))
    console.print(t)
    return 0

if __name__ == "__main__":
    sys.exit(main())
