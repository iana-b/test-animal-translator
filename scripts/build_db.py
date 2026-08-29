#!/usr/bin/env python3
"""Сборка запрашиваемой базы SQLite из data/knowledge.

JSON остаётся источником правды: он читается глазами и виден в диффах. База —
производная форма, удобная для запросов поперёк видов.

    python3 scripts/build_db.py            собрать data/knowledge.db
    python3 scripts/build_db.py --demo     собрать и выполнить примеры запросов
    python3 scripts/build_db.py --check    убедиться, что база не отстала от JSON
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = ROOT / "data" / "knowledge"
DB_PATH = ROOT / "data" / "knowledge.db"

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE species (
    slug                 TEXT PRIMARY KEY,
    name_ru              TEXT NOT NULL,
    name_en              TEXT,
    scientific_name      TEXT NOT NULL,
    engine               TEXT NOT NULL,
    engine_note_ru       TEXT NOT NULL,
    research_maturity_ru TEXT
);

CREATE TABLE sources (
    species_slug        TEXT NOT NULL REFERENCES species(slug) ON DELETE CASCADE,
    source_id           TEXT NOT NULL,
    authors             TEXT NOT NULL,
    year                INTEGER NOT NULL,
    title               TEXT NOT NULL,
    journal             TEXT NOT NULL,
    doi                 TEXT,
    url                 TEXT,
    licence             TEXT NOT NULL,
    evidence_grade      TEXT NOT NULL
                        CHECK (evidence_grade IN ('strong', 'moderate', 'limited')),
    open_access_kind    TEXT CHECK (open_access_kind IN ('pmc', 'url', 'publisher')),
    open_access_ref     TEXT,
    sample_ru           TEXT NOT NULL,
    gives_ru            TEXT NOT NULL,
    correction_doi      TEXT,
    correction_what_ru  TEXT,
    PRIMARY KEY (species_slug, source_id)
);

CREATE TABLE myths (
    myth_id      INTEGER PRIMARY KEY,
    species_slug TEXT NOT NULL REFERENCES species(slug) ON DELETE CASCADE,
    claim_ru     TEXT NOT NULL,
    reality_ru   TEXT NOT NULL
);

CREATE TABLE myth_sources (
    myth_id      INTEGER NOT NULL REFERENCES myths(myth_id) ON DELETE CASCADE,
    species_slug TEXT NOT NULL,
    source_id    TEXT NOT NULL,
    PRIMARY KEY (myth_id, source_id),
    FOREIGN KEY (species_slug, source_id)
        REFERENCES sources(species_slug, source_id) ON DELETE CASCADE
);

CREATE TABLE input_fields (
    species_slug TEXT NOT NULL REFERENCES species(slug) ON DELETE CASCADE,
    field_id     TEXT NOT NULL,
    position     INTEGER NOT NULL,
    label_ru     TEXT NOT NULL,
    type         TEXT NOT NULL,
    required     INTEGER NOT NULL DEFAULT 0,
    hint_ru      TEXT,
    example_ru   TEXT,
    PRIMARY KEY (species_slug, field_id)
);

CREATE TABLE input_options (
    species_slug TEXT NOT NULL,
    field_id     TEXT NOT NULL,
    position     INTEGER NOT NULL,
    value        TEXT NOT NULL,
    label_ru     TEXT NOT NULL,
    PRIMARY KEY (species_slug, field_id, value),
    FOREIGN KEY (species_slug, field_id)
        REFERENCES input_fields(species_slug, field_id) ON DELETE CASCADE
);

CREATE TABLE contexts (
    species_slug  TEXT NOT NULL REFERENCES species(slug) ON DELETE CASCADE,
    context_id    TEXT NOT NULL,
    label_ru      TEXT NOT NULL,
    definition_ru TEXT NOT NULL,
    n             INTEGER NOT NULL,
    PRIMARY KEY (species_slug, context_id)
);

CREATE TABLE context_reliability (
    species_slug       TEXT NOT NULL,
    context_id         TEXT NOT NULL,
    recall             REAL NOT NULL,
    kappa              REAL NOT NULL,
    better_than_random INTEGER NOT NULL,
    p_ru               TEXT NOT NULL,
    PRIMARY KEY (species_slug, context_id),
    FOREIGN KEY (species_slug, context_id)
        REFERENCES contexts(species_slug, context_id) ON DELETE CASCADE
);

CREATE TABLE confusion (
    species_slug      TEXT NOT NULL,
    true_context      TEXT NOT NULL,
    predicted_context TEXT NOT NULL,
    share             REAL NOT NULL,
    PRIMARY KEY (species_slug, true_context, predicted_context),
    FOREIGN KEY (species_slug, true_context)
        REFERENCES contexts(species_slug, context_id) ON DELETE CASCADE
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX idx_sources_year        ON sources(year);
CREATE INDEX idx_sources_grade       ON sources(evidence_grade);
CREATE INDEX idx_sources_access      ON sources(open_access_kind);
CREATE INDEX idx_confusion_predicted ON confusion(predicted_context);
"""

DEMO_QUERIES = [
    ("Источники со свободным полным текстом",
     """SELECT species_slug, source_id, year, open_access_kind
          FROM sources
         WHERE open_access_kind IS NOT NULL
         ORDER BY species_slug, year"""),
    ("Контексты собаки, которые по звуку не отличаются от случайных",
     """SELECT c.label_ru, r.recall, r.kappa, r.p_ru
          FROM context_reliability r
          JOIN contexts c ON c.species_slug = r.species_slug
                         AND c.context_id  = r.context_id
         WHERE r.better_than_random = 0
         ORDER BY r.recall DESC"""),
    ("С чем чаще всего путают каждый контекст",
     """SELECT t.label_ru AS истинный, p.label_ru AS принят_за, f.share
          FROM confusion f
          JOIN contexts t ON t.species_slug = f.species_slug
                         AND t.context_id  = f.true_context
          JOIN contexts p ON p.species_slug = f.species_slug
                         AND p.context_id  = f.predicted_context
         WHERE f.true_context <> f.predicted_context
           AND f.share = (SELECT MAX(share) FROM confusion x
                           WHERE x.species_slug = f.species_slug
                             AND x.true_context = f.true_context
                             AND x.predicted_context <> x.true_context)
         ORDER BY f.share DESC"""),
    ("Сколько источников на вид и какой доли из них доступен полный текст",
     """SELECT s.name_ru,
               COUNT(*)                                    AS всего,
               SUM(src.open_access_kind IS NOT NULL)       AS открытых,
               MIN(src.year) || '–' || MAX(src.year)       AS годы
          FROM sources src
          JOIN species s ON s.slug = src.species_slug
         GROUP BY s.slug
         ORDER BY всего DESC"""),
    ("Статьи с опубликованными поправками",
     """SELECT source_id, year, title, correction_doi
          FROM sources
         WHERE correction_doi IS NOT NULL"""),
]


def knowledge_files() -> list[Path]:
    return sorted(KNOWLEDGE_DIR.glob("*.json"))


def checksum() -> str:
    """Отпечаток исходных файлов: по нему видно, отстала ли база."""
    digest = hashlib.sha256()
    for path in knowledge_files():
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _open_access(source: dict) -> tuple[str | None, str | None]:
    info = source.get("open_access")
    if not info:
        return None, None
    if info["kind"] == "pmc":
        return "pmc", info["id"]
    if info["kind"] == "url":
        return "url", info["url"]
    return "publisher", info["note_ru"]


def build(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA)

    myth_counter = 0
    for path in knowledge_files():
        kb = json.loads(path.read_text(encoding="utf-8"))
        slug = kb["slug"]

        connection.execute(
            "INSERT INTO species VALUES (?, ?, ?, ?, ?, ?, ?)",
            (slug, kb["name_ru"], kb.get("name_en"), kb["scientific_name"],
             kb["engine"], kb["engine_note_ru"], kb.get("research_maturity_ru")))

        for source in kb["sources"]:
            kind, ref = _open_access(source)
            correction = source.get("correction") or {}
            connection.execute(
                "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (slug, source["id"], source["authors"], source["year"], source["title"],
                 source["journal"], source.get("doi"), source.get("url"),
                 source["licence"], source["evidence_grade"], kind, ref,
                 source["sample_ru"], source["gives_ru"],
                 correction.get("doi"), correction.get("what_ru")))

        for myth in kb["myths"]:
            myth_counter += 1
            connection.execute("INSERT INTO myths VALUES (?, ?, ?, ?)",
                               (myth_counter, slug, myth["claim_ru"], myth["reality_ru"]))
            for source_id in myth["source_ids"]:
                connection.execute("INSERT INTO myth_sources VALUES (?, ?, ?)",
                                   (myth_counter, slug, source_id))

        for position, field in enumerate(kb["input_schema"]):
            connection.execute(
                "INSERT INTO input_fields VALUES (?,?,?,?,?,?,?,?)",
                (slug, field["id"], position, field["label_ru"], field["type"],
                 int(bool(field.get("required"))), field.get("hint_ru"),
                 field.get("example_ru")))
            for option_position, option in enumerate(field.get("options", [])):
                connection.execute(
                    "INSERT INTO input_options VALUES (?,?,?,?,?)",
                    (slug, field["id"], option_position, option["value"], option["label_ru"]))

        for context in kb.get("contexts", []):
            connection.execute("INSERT INTO contexts VALUES (?,?,?,?,?)",
                               (slug, context["id"], context["label_ru"],
                                context["definition_ru"], context["n"]))

        reliability = kb.get("reliability", {}).get("per_context", {})
        for context_id, stats in reliability.items():
            connection.execute(
                "INSERT INTO context_reliability VALUES (?,?,?,?,?,?)",
                (slug, context_id, stats["recall"], stats["kappa"],
                 int(stats["better_than_random"]), stats["p_ru"]))

        for true_context, row in kb.get("confusion_matrix", {}).get("rows", {}).items():
            for predicted, share in row.items():
                connection.execute("INSERT INTO confusion VALUES (?,?,?,?)",
                                   (slug, true_context, predicted, share))

    connection.executemany(
        "INSERT INTO meta VALUES (?, ?)",
        [("built_at", datetime.now(timezone.utc).isoformat(timespec="seconds")),
         ("source_checksum", checksum()),
         ("source_files", ", ".join(p.name for p in knowledge_files()))])
    connection.commit()
    return connection


def demo(connection: sqlite3.Connection) -> None:
    for title, query in DEMO_QUERIES:
        print(f"\n\033[1m{title}\033[0m")
        cursor = connection.execute(query)
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        widths = [max(len(str(c)), *(len(str(r[i])) for r in rows)) if rows else len(str(c))
                  for i, c in enumerate(columns)]
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(columns, widths)))
        print("  " + "  ".join("-" * w for w in widths))
        for row in rows:
            print("  " + "  ".join(str(v).ljust(w) for v, w in zip(row, widths)))


def check() -> int:
    if not DB_PATH.exists():
        print("База не собрана: запустите scripts/build_db.py")
        return 1
    with sqlite3.connect(DB_PATH) as connection:
        stored = connection.execute(
            "SELECT value FROM meta WHERE key = 'source_checksum'").fetchone()
    if not stored or stored[0] != checksum():
        print("База отстала от data/knowledge: пересоберите scripts/build_db.py")
        return 1
    print("База соответствует базе знаний")
    return 0


def main() -> None:
    if "--check" in sys.argv:
        raise SystemExit(check())

    connection = build()
    counts = {
        table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("species", "sources", "myths", "myth_sources",
                      "input_fields", "input_options", "contexts",
                      "context_reliability", "confusion")
    }
    print(f"Собрано: {DB_PATH.relative_to(ROOT)}")
    for table, count in counts.items():
        print(f"  {table:20s} {count:4d}")

    if "--demo" in sys.argv:
        demo(connection)
    connection.close()


if __name__ == "__main__":
    main()
