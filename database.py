from __future__ import annotations

import csv
import io
import re
import sqlite3
from pathlib import Path


PAGE_SIZE = 50
EXPORT_LIMIT = 100

DISPLAY_COLUMNS = [
    "Naam",
    "Ondernemingsnummer",
    "Postcode",
    "Provincie",
    "Boekjaar",
    "Datum einde boekjaar",
    "Bestandsnaam",
    "Winst/verlies van het boekjaar (9904)",
    "Winst/verlies vorig boekjaar (9904)",
    "Bedrijfswinst/-verlies (9901)",
    "Bedrijfswinst/-verlies vorig jaar (9901)",
    "Financiële opbrengsten totaal",
    "Financiële opbrengsten totaal vorig jaar",
    "Netto financieel resultaat",
    "Netto financieel resultaat vorig jaar",
    "Verhouding fin. opbrengsten / vorderingen",
    "Verhouding fin. opbrengsten / vorderingen vorig jaar",
    "Vorderingen op verbonden ondernemingen (9291)",
    "Vorderingen op verbonden ondernemingen vorig jaar (9291)",
    "Kosten van schulden (9461)",
    "Kosten van schulden vorig jaar (9461)",
    "Opbrengsten uit financiële vaste activa (9421)",
    "Opbrengsten uit financiële vaste activa vorig jaar (9421)",
    "Opbrengsten uit vlottende activa (9431)",
    "Opbrengsten uit vlottende activa vorig jaar (9431)",
    "Andere financiële opbrengsten (9441)",
    "Andere financiële opbrengsten vorig jaar (9441)",
]

def connect(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
    con.execute("PRAGMA query_only = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def filter_choices(db: Path) -> tuple[list[str], list[str]]:
    with connect(db) as con:
        years = [str(r[0]) for r in con.execute(
            'SELECT DISTINCT "Boekjaar" FROM "Data" '
            'WHERE "Boekjaar" IS NOT NULL ORDER BY 1 DESC'
        )]
        provinces = [r[0] for r in con.execute(
            'SELECT DISTINCT "Provincie" FROM "Data" '
            'WHERE "Provincie" IS NOT NULL ORDER BY 1'
        )]
    return ["Alle"] + years, ["Alle"] + provinces


def fts_expression(text: str) -> str:
    tokens = re.findall(r"\w+", text or "", flags=re.UNICODE)
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def build_query(search: str, year: str, province: str) -> tuple[str, list[object]]:
    joins: list[str] = []
    conditions: list[str] = []
    params: list[object] = []

    expression = fts_expression(search.strip())
    if expression:
        joins.append('JOIN "Data_fts" f ON f.rowid = d.rowid')
        conditions.append('"Data_fts" MATCH ?')
        params.append(expression)
    if year != "Alle":
        conditions.append('d."Boekjaar" = ?')
        params.append(int(year))
    if province != "Alle":
        conditions.append('d."Provincie" = ?')
        params.append(province)

    sql = 'FROM "Data" d '
    if joins:
        sql += " ".join(joins) + " "
    if conditions:
        sql += "WHERE " + " AND ".join(conditions)
    return sql, params


def build_order(sort_column: str, sort_direction: str) -> str:
    """Bouw een veilige ORDER BY voor sortering over de volledige databank."""
    if sort_column not in DISPLAY_COLUMNS:
        sort_column = "Naam"
    direction = "DESC" if sort_direction == "Aflopend" else "ASC"
    column = sort_column.replace('"', '""')
    parts = [
        f'CASE WHEN d."{column}" IS NULL OR CAST(d."{column}" AS TEXT) = \'\' '
        "THEN 1 ELSE 0 END ASC",
        f'd."{column}" COLLATE NOCASE {direction}',
    ]
    if sort_column != "Naam":
        parts.extend([
            'CASE WHEN d."Naam" IS NULL OR TRIM(d."Naam") = \'\' '
            "THEN 1 ELSE 0 END ASC",
            'd."Naam" COLLATE NOCASE ASC',
        ])
    if sort_column != "Boekjaar":
        parts.append('d."Boekjaar" DESC')
    parts.append("d.rowid ASC")
    return ", ".join(parts)


def fetch_page(
    db: Path,
    search: str,
    year: str,
    province: str,
    sort_column: str,
    sort_direction: str,
    page: int,
) -> tuple[list[dict[str, object]], int, int]:
    from_sql, params = build_query(search, year, province)
    select = ", ".join(f'd."{column}"' for column in DISPLAY_COLUMNS)
    order = build_order(sort_column, sort_direction)

    with connect(db) as con:
        total = con.execute("SELECT COUNT(*) " + from_sql, params).fetchone()[0]
        last_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(max(1, page), last_page)
        rows = con.execute(
            f"SELECT {select} {from_sql} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
    return [dict(zip(DISPLAY_COLUMNS, row)) for row in rows], total, last_page


def export_csv(
    db: Path,
    search: str,
    year: str,
    province: str,
    sort_column: str,
    sort_direction: str,
) -> tuple[bytes, int, bool]:
    from_sql, params = build_query(search, year, province)
    select = ", ".join(f'd."{column}"' for column in DISPLAY_COLUMNS)
    order = build_order(sort_column, sort_direction)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(DISPLAY_COLUMNS)

    with connect(db) as con:
        total = con.execute("SELECT COUNT(*) " + from_sql, params).fetchone()[0]
        rows = con.execute(
            f"SELECT {select} {from_sql} ORDER BY {order} LIMIT ?",
            [*params, EXPORT_LIMIT],
        )
        writer.writerows(rows)
    data = ("\ufeff" + output.getvalue()).encode("utf-8")
    return data, min(total, EXPORT_LIMIT), total > EXPORT_LIMIT
