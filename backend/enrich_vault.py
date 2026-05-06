"""Vault enrichment script.

Two operations, safe to run repeatedly:

  1. Seed entity files — writes one .md file per Timebeat product and
     glossary term into vault/knowledge/entities/. These are the [[wikilink]]
     targets that make the Obsidian graph work.

  2. Retrofit learning files — scans every existing file in vault/calls/
     and vault/lead/ and injects [[wikilinks]] for any detected entities,
     then updates the products[] and tags[] frontmatter fields.

Run: python3 enrich_vault.py
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent
sys.path.insert(0, str(BACKEND_DIR))

from agents.calls.routes import GLOSSARY, PRODUCTS
from agents.shared.vault import (
    CALLS_DIR,
    ENTITIES_DIR,
    LEAD_DIR,
    retrofit_all_learning_files,
    write_entity,
)


# ---------------------------------------------------------------------------
# Step 1: Seed product entity files
# ---------------------------------------------------------------------------

def seed_products() -> int:
    written = 0
    for p in PRODUCTS:
        name = p["name"]
        entity_type = "product"
        tags = []

        # Derive tags from product characteristics
        ptype = p.get("type", "").lower()
        if "hardware" in ptype:
            tags.append("hardware")
        if "software" in ptype:
            tags.append("software")
        if "pcie" in ptype or "pcie" in p.get("tagline", "").lower():
            tags.append("pcie")

        use_cases = p.get("use_cases", [])
        for uc in use_cases:
            uc_lower = uc.lower()
            if "5g" in uc_lower or "telecom" in uc_lower:
                tags.append("5g")
            if "trading" in uc_lower or "hft" in uc_lower:
                tags.append("hft")
            if "defence" in uc_lower or "defense" in uc_lower:
                tags.append("defence")
            if "hyperscale" in uc_lower or "cloud" in uc_lower:
                tags.append("hyperscale")
            if "data centre" in uc_lower or "data center" in uc_lower:
                tags.append("data-centre")
        tags = list(dict.fromkeys(tags))  # deduplicate, preserve order

        description = f"""# {name}

**Type:** {p.get("type", "")}
**Tagline:** {p.get("tagline", "")}

{p.get("description", "")}

**Specs:** {", ".join(p.get("specs", []))}

**Ideal customer:** {p.get("ideal_customer", "")}

**Use cases:** {", ".join(p.get("use_cases", []))}

**Competitive angle:** {p.get("competitive_angle", "")}"""

        write_entity(
            title=name,
            entity_type=entity_type,
            description=description,
            tags=tags,
        )
        print(f"  [product] {name}")
        written += 1
    return written


# ---------------------------------------------------------------------------
# Step 2: Seed glossary term entity files
# ---------------------------------------------------------------------------

def seed_glossary() -> int:
    written = 0
    for g in GLOSSARY:
        term = g["term"]
        # Strip any parenthetical abbreviation from the title for cleaner entity name
        # e.g. "TaaS (Time as a Service)" → keep as-is, it's the canonical form
        entity_type = "protocol" if g.get("protocol", "N/A") != "N/A" else "term"
        products_refs = g.get("products", [])
        protocol = g.get("protocol", "")

        tags = []
        if protocol and protocol != "N/A":
            tags.append(protocol.lower().replace(" ", "-").replace("/", "-"))
        for prod in products_refs:
            tags.append(prod.lower().replace(" ", "-"))
        tags = list(dict.fromkeys(tags))

        products_line = (
            f"\n\n**Associated Timebeat products:** {', '.join(f'[[{p}]]' for p in products_refs)}"
            if products_refs
            else ""
        )
        protocol_line = f"\n\n**Protocol:** {protocol}" if protocol and protocol != "N/A" else ""

        description = f"""# {term}

{g.get("definition", "")}{protocol_line}{products_line}"""

        write_entity(
            title=term,
            entity_type=entity_type,
            description=description,
            tags=tags,
        )
        print(f"  [term]    {term}")
        written += 1
    return written


# ---------------------------------------------------------------------------
# Step 3: Retrofit existing learning files
# ---------------------------------------------------------------------------

def retrofit() -> int:
    calls_files = list(CALLS_DIR.glob("*.md"))
    lead_files = list(LEAD_DIR.glob("*.md"))
    total = len(calls_files) + len(lead_files)
    print(f"  Scanning {total} learning files...")
    modified = retrofit_all_learning_files()
    return modified


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=== Vault Enrichment ===\n")

    print("[1] Seeding product entity files...")
    p_count = seed_products()
    print(f"    → {p_count} product(s) written\n")

    print("[2] Seeding glossary term entity files...")
    g_count = seed_glossary()
    print(f"    → {g_count} term(s) written\n")

    print("[3] Retrofitting existing learning files with [[wikilinks]]...")
    r_count = retrofit()
    print(f"    → {r_count} file(s) updated\n")

    print(f"=== Done. {p_count + g_count} entity files seeded, {r_count} learnings enriched ===")
    print(f"    Open backend/vault/ in Obsidian to see the knowledge graph.")


if __name__ == "__main__":
    main()
