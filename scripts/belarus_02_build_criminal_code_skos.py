#!/usr/bin/env python3
"""
Belarusian Criminal Code SKOS Builder
======================================
Step 02 of the Belarus political-persecution knowledge-graph pipeline.

Inputs:  data/jsonl/articles__en.jsonl (from step 01)
Outputs: ontology/by_criminal_code_skos.ttl, ontology/by_criminal_code_annotations.csv
"""
from __future__ import annotations
import csv, json, logging, re, sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, OWL, PROV, RDF, RDFS, SKOS, XSD
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

INPUT_ROOT = Path("data/jsonl")
OUT_DIR = Path("ontology")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_TTL = OUT_DIR / "by_criminal_code_skos.ttl"
OUT_COVERAGE = OUT_DIR / "by_criminal_code_annotations.csv"

ONTOLOGY_BASE = "http://repressions.belarus/ontology/"
SCHEME_BASE = "http://repressions.belarus/vocab/by-criminal-code/"
ONT = Namespace(ONTOLOGY_BASE)
BYCC = Namespace(SCHEME_BASE)
ICCPR = Namespace("http://www.ohchr.org/EN/ProfessionalInterest/Pages/CCPR#")
VIASNA = Namespace("http://prisoners.spring96.org/")

console = Console()
logging.basicConfig(level=logging.INFO, format="%(message)s",
                    handlers=[RichHandler(console=console, show_path=False)])
log = logging.getLogger("by-skos")

# ─────────────────────────────────────────────────────────────────
# ANNOTATIONS (curated analytic layer)
# ─────────────────────────────────────────────────────────────────

ANNOTATIONS: dict[str, dict[str, Any]] = {
    # MASS PROTEST ARTICLES
    "342": {
        "character": "facially_incompatible",
        "iccpr": ["21"],
        "note": (
            "Organization and preparation of actions that grossly violate "
            "public order, or active participation in them. The primary "
            "article applied to August 2020 election protesters. 'Grossly "
            "violate public order' is undefined in the code, enabling "
            "application to any unauthorized assembly. Standalone in 79.9% "
            "of cases: a single-charge production-line instrument."
        ),
    },
    "342-2": {
        "introduced": "2021-06-01",
        "character": "facially_incompatible",
        "iccpr": ["21"],
        "note": (
            "Repeated violation of the order of organization or holding of "
            "mass events. Criminal exposure triggered by prior administrative "
            "offenses, identical in structure to Russia's Art. 212.1. Facially "
            "punishes the exercise of assembly rights."
        ),
    },
    # PRESIDENTIAL INSULT ARTICLES
    "368": {
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Insulting the President of the Republic of Belarus. Criminalizes "
            "expression critical of the head of state regardless of truth "
            "value. Applied to social media posts, protest slogans, and "
            "artistic expression. The UN Human Rights Committee has "
            "repeatedly stated that heads of state are not shielded from "
            "criticism under Art. 19 ICCPR (General Comment 34, para. 38)."
        ),
    },
    "367": {
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Slander against the President of the Republic of Belarus. "
            "Companion to Art. 368; criminalizes statements about the "
            "president that the state characterizes as false, without "
            "requiring demonstration of actual malice or harm."
        ),
    },
    "369": {
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Insulting a government official. Extends the presidential "
            "insult framework to all state employees. Applied to criticism "
            "of police, judges, prosecutors, and election officials. "
            "Frequently stacked with Art. 368."
        ),
    },
    "369-1": {
        "introduced": "2022-01-01",
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Discrediting the Republic of Belarus. Introduced post-2020, "
            "directly parallel to Russia's Art. 280.3 (discrediting the "
            "armed forces). Criminalizes dissemination of information the "
            "state deems harmful to the country's reputation."
        ),
    },
    "370": {
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Desecration of state symbols. Applied to protesters who "
            "displayed the historical white-red-white flag (used by the "
            "opposition) or modified state symbols in protest art."
        ),
    },
    # INCITEMENT / HATRED
    "130": {
        "character": "as_applied",
        "iccpr": ["19", "26"],
        "note": (
            "Incitement to hatred. Legitimate provision under ICCPR Art. "
            "20(2), but applied in Belarus to political speech critical of "
            "state institutions or security forces, not to actual incitement "
            "of violence or discrimination against protected groups. The "
            "WGAD has found detentions under this article arbitrary in "
            "multiple Belarus cases."
        ),
    },
    "130-1": {
        "introduced": "2022-01-14",
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Rehabilitation of Nazism. Introduced 2022, parallel to "
            "Russia's Art. 354.1. Applied to historical claims and "
            "political commentary. Elastic terms invite selective "
            "prosecution."
        ),
    },
    # EXTREMIST FORMATION ARTICLES
    "361-1": {
        "character": "as_applied",
        "iccpr": ["22"],
        "note": (
            "Creation of an extremist formation, or participation in it. "
            "The primary vehicle for prosecuting members of organizations "
            "designated 'extremist' by executive decision. Designations "
            "include independent media (Tut.by), human rights organizations "
            "(Viasna itself), opposition political movements, and Telegram "
            "channels. Structurally identical to Russia's Art. 282.1."
        ),
    },
    "361-2": {
        "character": "as_applied",
        "iccpr": ["22"],
        "note": (
            "Financing the activities of an extremist group. Applied to "
            "donors, subscribers, and anyone who transferred funds to "
            "designated organizations. Parallel to Russia's Art. 282.3."
        ),
    },
    "361-4": {
        "character": "facially_incompatible",
        "iccpr": ["19", "22"],
        "note": (
            "Promoting extremist activities. Covers reposting, sharing, "
            "or distributing materials from designated extremist "
            "organizations. Applied to social media shares, Telegram "
            "forwards, and wearing opposition symbols. The broadest of "
            "the extremist-formation articles."
        ),
    },
    "361": {
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Calls for actions aimed at causing harm to the national "
            "security of the Republic of Belarus. Applied to political "
            "speech, open letters, and public statements calling for "
            "sanctions, international investigations, or political change."
        ),
    },
    # VIOLENCE AGAINST AUTHORITY
    "364": {
        "character": "legitimate_weaponized",
        "iccpr": ["14"],
        "note": (
            "Violence or threat of violence against an employee of the "
            "internal affairs bodies. Legitimate provision but applied on "
            "the basis of police testimony alone, with conviction rates "
            "near 100%. Frequently charged against protesters who made "
            "physical contact with riot police during dispersals."
        ),
    },
    "363": {
        "character": "legitimate_weaponized",
        "iccpr": ["14"],
        "note": (
            "Resistance to a police officer or other person guarding "
            "public order. Companion to Art. 364 with a lower threshold. "
            "Applied to passive resistance, failure to disperse, and "
            "linking arms during protest."
        ),
    },
    "366": {
        "character": "legitimate_weaponized",
        "iccpr": ["14"],
        "note": (
            "Violence or threat against an official performing official "
            "duties. Broader than Art. 364; covers non-police officials "
            "including election commission members and judges."
        ),
    },
    # PROPERTY / PUBLIC ORDER
    "341": {
        "character": "as_applied",
        "iccpr": ["19"],
        "note": (
            "Desecration of structures and damage to property. Applied to "
            "protest graffiti, display of opposition symbols on buildings, "
            "and distribution of stickers. The property-damage threshold "
            "is minimal."
        ),
    },
    "218": {
        "character": "legitimate_weaponized",
        "iccpr": ["14"],
        "note": (
            "Intentional destruction or damage to property committed in a "
            "generally dangerous manner. The aggravated form of property "
            "damage, applied to protest-related incidents. Carries "
            "significantly heavier sentences than Art. 341."
        ),
    },
    # STATE SECURITY
    "357": {
        "character": "facially_incompatible",
        "iccpr": ["19", "25"],
        "note": (
            "Conspiracy to seize power in an unconstitutional way. Applied "
            "to opposition leaders and coordination council members after "
            "August 2020. Carries up to 15 years. The charge does not "
            "require evidence of violence or concrete preparation, only "
            "agreement on political change outside state-sanctioned channels."
        ),
    },
    "356": {
        "character": "as_applied",
        "iccpr": ["14", "19"],
        "note": (
            "High treason. Applied to individuals who shared information "
            "with foreign media, international organizations, or diaspora "
            "groups. The 2022 amendments expanded the definition to include "
            "actions that 'harm the national security' without requiring "
            "classified information."
        ),
    },
    "289": {
        "character": "legitimate_weaponized",
        "iccpr": ["14"],
        "note": (
            "An act of terrorism. Legitimate provision but applied to "
            "protest-adjacent conduct including alleged sabotage of "
            "railway infrastructure (the 'rail partisans' cases) and "
            "attacks on security-force property."
        ),
    },
    # JUDICIAL INDEPENDENCE
    "391": {
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Insulting a judge. Extends the insult framework to the "
            "judiciary. Applied to defendants and their families who "
            "publicly criticized judicial proceedings or outcomes."
        ),
    },
    "389": {
        "character": "facially_incompatible",
        "iccpr": ["14", "19"],
        "note": (
            "Threat to a judge or lay judge. Applied to statements "
            "construed as threatening, including public criticism of "
            "judges in political cases."
        ),
    },
    # MEDIA / PRIVACY
    "198": {
        "character": "facially_incompatible",
        "iccpr": ["19"],
        "note": (
            "Obstruction of a journalist's lawful professional activity. "
            "Paradoxically, this article exists to protect journalists but "
            "has been applied against citizen journalists and bloggers "
            "covering protests."
        ),
    },
    "203-1": {
        "character": "as_applied",
        "iccpr": ["19"],
        "note": (
            "Illegal actions with respect to information about private "
            "life and personal data. Applied to individuals who published "
            "identifying information about security-force members involved "
            "in violence against protesters (doxxing cases)."
        ),
    },
    # ELECTORAL
    "191": {
        "character": "facially_incompatible",
        "iccpr": ["25"],
        "note": (
            "Obstruction of the exercise of electoral rights. Applied to "
            "election observers and polling-station commission members who "
            "reported irregularities in the August 2020 election."
        ),
    },
    # PRISON / POST-CONVICTION
    "411": {
        "character": "as_applied",
        "iccpr": ["7", "10"],
        "note": (
            "Malicious disobedience to the demands of administration of "
            "the correctional institution. Used to extend sentences of "
            "political prisoners already in custody. Viasna has documented "
            "systematic use of this article against prisoners who refuse "
            "to comply with arbitrary demands or who maintain contact with "
            "human rights organizations."
        ),
    },
    # CONSCRIPTION
    "435": {
        "character": "as_applied",
        "iccpr": ["18"],
        "note": (
            "Evasion of conscription measures. Applied post-2022 in the "
            "context of potential Belarus involvement in the Ukraine war. "
            "No conscientious-objector exemption exists in Belarusian law."
        ),
    },
}

# ─────────────────────────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────────────────────────

@dataclass
class ArticleRecord:
    notation: str
    title_en: str | None = None
    description: str | None = None
    source_ids: set[str] = field(default_factory=set)

    @property
    def concept_slug(self) -> str:
        return "art_" + self.notation.replace("-", "_")

def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        log.error("Not found: %s", path); sys.exit(2)
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: records.append(json.loads(line))
    log.info("Loaded %d records from %s", len(records), path)
    return records

def unwrap(obj: dict) -> dict:
    rec = obj.get("record", obj)
    if "attributes" in rec and isinstance(rec["attributes"], dict):
        out = dict(rec["attributes"])
        if "id" in rec: out["id"] = rec["id"]
        return out
    if "id" in rec: rec["_id"] = rec["id"]
    return rec

def build_records(raw: list[dict]) -> dict[str, ArticleRecord]:
    articles: dict[str, ArticleRecord] = {}
    for obj in raw:
        rec = unwrap(obj)
        notation = rec.get("article_number")
        if not notation: continue
        if notation in articles:
            articles[notation].source_ids.add(str(rec.get("id", "")))
            continue
        articles[notation] = ArticleRecord(
            notation=notation,
            title_en=rec.get("article_title"),
            description=rec.get("article_description"),
        )
        articles[notation].source_ids.add(str(rec.get("id", "")))
    log.info("Built %d article concepts", len(articles))
    return articles

# ─────────────────────────────────────────────────────────────────
# RDF EMISSION
# ─────────────────────────────────────────────────────────────────

def emit_ttl(records: dict[str, ArticleRecord], out_path: Path) -> tuple[int, int]:
    g = Graph()
    g.bind("skos", SKOS); g.bind("dcterms", DCTERMS); g.bind("prov", PROV)
    g.bind("owl", OWL); g.bind("xsd", XSD); g.bind("", ONT)
    g.bind("bycc", BYCC); g.bind("iccpr", ICCPR); g.bind("viasna", VIASNA)

    ont_iri = URIRef(ONTOLOGY_BASE + "by-criminal-code")
    g.add((ont_iri, RDF.type, OWL.Ontology))
    g.add((ont_iri, DCTERMS.title, Literal("Belarusian Criminal Code SKOS Vocabulary", lang="en")))
    g.add((ont_iri, DCTERMS.created, Literal(datetime.now(timezone.utc).date().isoformat(), datatype=XSD.date)))
    g.add((ont_iri, DCTERMS.source, URIRef("https://prisoners.spring96.org/")))

    for prop, comment in [
        (ONT.iccprViolation, "ICCPR article materially violated as applied"),
        (ONT.facialCharacter, "Facial vs as-applied classification"),
        (ONT.introducedDate, "Date article entered the Criminal Code"),
    ]:
        g.add((prop, RDF.type, OWL.AnnotationProperty))
        g.add((prop, RDFS.comment, Literal(comment, lang="en")))

    scheme = URIRef(SCHEME_BASE)
    g.add((scheme, RDF.type, SKOS.ConceptScheme))
    g.add((scheme, DCTERMS.title, Literal("Belarusian Criminal Code (Уголовный кодекс Республики Беларусь)", lang="en")))
    g.add((scheme, SKOS.prefLabel, Literal("Уголовный кодекс Республики Беларусь", lang="be")))

    annotated = 0
    for art in sorted(records.values(), key=lambda a: (
        int(a.notation.split("-")[0]), int(a.notation.split("-")[1]) if "-" in a.notation else 0
    )):
        concept = URIRef(SCHEME_BASE + art.concept_slug)
        g.add((concept, RDF.type, SKOS.Concept))
        g.add((concept, SKOS.inScheme, scheme))
        g.add((scheme, SKOS.hasTopConcept, concept))
        g.add((concept, SKOS.notation, Literal(art.notation)))

        if art.title_en:
            g.add((concept, SKOS.prefLabel, Literal(art.title_en, lang="en")))
        else:
            g.add((concept, SKOS.prefLabel, Literal(f"Article {art.notation}", lang="en")))

        if art.description:
            g.add((concept, SKOS.definition, Literal(art.description, lang="en")))

        for sid in art.source_ids:
            g.add((concept, PROV.wasDerivedFrom, URIRef(str(VIASNA) + sid)))

        ann = ANNOTATIONS.get(art.notation)
        if ann:
            annotated += 1
            if "note" in ann:
                g.add((concept, SKOS.editorialNote, Literal(ann["note"], lang="en")))
            if "character" in ann:
                g.add((concept, ONT.facialCharacter, Literal(ann["character"])))
            if "introduced" in ann:
                g.add((concept, ONT.introducedDate, Literal(ann["introduced"], datatype=XSD.date)))
            for iccpr_art in ann.get("iccpr", []):
                g.add((concept, ONT.iccprViolation, URIRef(str(ICCPR) + f"Art{iccpr_art}")))

    g.serialize(destination=str(out_path), format="turtle")
    return len(records), annotated

def write_coverage(records: dict[str, ArticleRecord], out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["notation", "title_en", "has_annotation", "character", "iccpr", "introduced"])
        for notation in sorted(records, key=lambda n: (
            int(n.split("-")[0]), int(n.split("-")[1]) if "-" in n else 0
        )):
            a = records[notation]
            ann = ANNOTATIONS.get(notation)
            w.writerow([
                notation, a.title_en or "", "yes" if ann else "no",
                (ann or {}).get("character", ""),
                ",".join((ann or {}).get("iccpr", [])),
                (ann or {}).get("introduced", ""),
            ])

def main() -> int:
    log.info("Loading Belarus article records")
    en = load_jsonl(INPUT_ROOT / "articles__en.jsonl")
    articles = build_records(en)

    log.info("Emitting Turtle")
    total, annotated = emit_ttl(articles, OUT_TTL)
    log.info("Wrote %s (%d concepts, %d annotated)", OUT_TTL, total, annotated)

    write_coverage(articles, OUT_COVERAGE)
    log.info("Coverage: %s", OUT_COVERAGE)

    t = Table(title="Belarus Criminal Code SKOS summary")
    t.add_column("metric"); t.add_column("count", justify="right")
    t.add_row("total concepts", str(total))
    t.add_row("annotated", str(annotated))
    t.add_row("awaiting annotation", str(total - annotated))
    console.print(t)
    return 0

if __name__ == "__main__":
    sys.exit(main())
