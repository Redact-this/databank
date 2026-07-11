from __future__ import annotations

import csv
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import gradio as gr


ROOT = Path(__file__).resolve().parent
DB = ROOT / "data.db"
ZIP = ROOT / "data.zip"
PAGE_SIZE = 50
EXPORT_LIMIT = 100

DISPLAY_COLUMNS = [
    "Naam",
    "Ondernemingsnummer",
    "Postcode",
    "Provincie",
    "Boekjaar",
    "Datum einde boekjaar",
    "Winst/verlies van het boekjaar (9904)",
    "Bedrijfswinst/-verlies (9901)",
    "Financiële opbrengsten totaal",
    "Netto financieel resultaat",
]

SORTS = {
    "Naam (A–Z)": 'd."Naam" COLLATE NOCASE ASC, d."Boekjaar" DESC',
    "Nieuwste boekjaar": 'd."Boekjaar" DESC, d."Naam" COLLATE NOCASE ASC',
    "Hoogste winst": 'd."Winst/verlies van het boekjaar (9904)" DESC',
    "Grootste verlies": 'd."Winst/verlies van het boekjaar (9904)" ASC',
    "Hoogste bedrijfsresultaat": 'd."Bedrijfswinst/-verlies (9901)" DESC',
}


def ensure_database() -> None:
    if DB.exists():
        return
    if not ZIP.exists():
        raise FileNotFoundError("Upload data.zip naast app.py.")
    with zipfile.ZipFile(ZIP) as archive:
        if "data.db" not in archive.namelist():
            raise RuntimeError("data.zip moet een bestand met de naam data.db bevatten.")
        archive.extract("data.db", ROOT)


ensure_database()


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro&immutable=1", uri=True)
    con.execute("PRAGMA query_only = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def choices() -> tuple[list[str], list[str]]:
    with connect() as con:
        years = [str(r[0]) for r in con.execute(
            'SELECT DISTINCT "Boekjaar" FROM "Data" '
            'WHERE "Boekjaar" IS NOT NULL ORDER BY 1 DESC'
        )]
        provinces = [r[0] for r in con.execute(
            'SELECT DISTINCT "Provincie" FROM "Data" '
            'WHERE "Provincie" IS NOT NULL ORDER BY 1'
        )]
    return ["Alle"] + years, ["Alle"] + provinces


YEARS, PROVINCES = choices()


def fts_expression(text: str) -> str:
    # FTS5-prefixzoekopdracht; leestekens in ondernemingsnummers zijn veilig.
    tokens = re.findall(r"\w+", text, flags=re.UNICODE)
    return " AND ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def build_query(search: str, year: str, province: str) -> tuple[str, list[object]]:
    joins = []
    conditions = []
    params: list[object] = []

    expression = fts_expression((search or "").strip())
    if expression:
        joins.append('JOIN "Data_fts" f ON f.rowid = d.rowid')
        conditions.append('"Data_fts" MATCH ?')
        params.append(expression)
    if year and year != "Alle":
        conditions.append('d."Boekjaar" = ?')
        params.append(int(year))
    if province and province != "Alle":
        conditions.append('d."Provincie" = ?')
        params.append(province)

    sql = 'FROM "Data" d '
    if joins:
        sql += " ".join(joins) + " "
    if conditions:
        sql += "WHERE " + " AND ".join(conditions)
    return sql, params


def format_cell(value: object, column: str) -> object:
    if value is None:
        return ""
    if column in DISPLAY_COLUMNS[6:] and isinstance(value, (int, float)):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return value


def fetch_page(search: str, year: str, province: str, sort: str, page: int):
    page = max(1, int(page or 1))
    from_sql, params = build_query(search, year, province)
    select = ", ".join(f'd."{c}"' for c in DISPLAY_COLUMNS)
    order = SORTS.get(sort, SORTS["Naam (A–Z)"])

    with connect() as con:
        total = con.execute("SELECT COUNT(*) " + from_sql, params).fetchone()[0]
        last_page = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        page = min(page, last_page)
        rows = con.execute(
            f"SELECT {select} {from_sql} ORDER BY {order} LIMIT ? OFFSET ?",
            [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()

    shown = [[format_cell(value, DISPLAY_COLUMNS[i]) for i, value in enumerate(row)] for row in rows]
    status = f"**{total:,} resultaten** — pagina {page} van {last_page}".replace(",", ".")
    return shown, status, page


def new_search(search: str, year: str, province: str, sort: str):
    return fetch_page(search, year, province, sort, 1)


def previous_page(search: str, year: str, province: str, sort: str, page: int):
    return fetch_page(search, year, province, sort, max(1, int(page) - 1))


def next_page(search: str, year: str, province: str, sort: str, page: int):
    return fetch_page(search, year, province, sort, int(page) + 1)


def export_csv(search: str, year: str, province: str, sort: str):
    from_sql, params = build_query(search, year, province)
    select = ", ".join(f'd."{c}"' for c in DISPLAY_COLUMNS)
    order = SORTS.get(sort, SORTS["Naam (A–Z)"])
    with connect() as con:
        total = con.execute("SELECT COUNT(*) " + from_sql, params).fetchone()[0]
        rows = con.execute(
            f"SELECT {select} {from_sql} ORDER BY {order} LIMIT ?",
            [*params, EXPORT_LIMIT],
        )
        temp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", prefix="jaarrekeningen_",
            encoding="utf-8-sig", newline="", delete=False,
        )
        with temp:
            writer = csv.writer(temp, delimiter=";")
            writer.writerow(DISPLAY_COLUMNS)
            writer.writerows(rows)
    note = f"CSV aangemaakt met {min(total, EXPORT_LIMIT):,} rijen.".replace(",", ".")
    if total > EXPORT_LIMIT:
        note += f" Verfijn je filters om onder de limiet van {EXPORT_LIMIT:,} rijen te komen.".replace(",", ".")
    return temp.name, note


CSS = """
.gradio-container { max-width: 1500px !important; }
.intro { max-width: 950px; }
.result-table { font-size: 0.9rem; }
"""

with gr.Blocks(title="Jaarrekeningen Databank", css=CSS) as demo:
    gr.Markdown(
        "# 📊 Jaarrekeningen Databank\n"
        "Zoek in financiële kerncijfers uit Belgische jaarrekeningen. "
        "Bedragen zijn in euro. Controleer belangrijke cijfers bij de oorspronkelijke NBB-bron.",
        elem_classes="intro",
    )
    page_state = gr.State(1)
    with gr.Row():
        search_box = gr.Textbox(
            label="Bedrijfsnaam, ondernemingsnummer of postcode",
            placeholder="Bijvoorbeeld: bakkerij, 0123.456.789 of 9000",
            scale=3,
        )
        year_box = gr.Dropdown(YEARS, value="Alle", label="Boekjaar")
        province_box = gr.Dropdown(PROVINCES, value="Alle", label="Provincie")
        sort_box = gr.Dropdown(list(SORTS), value="Naam (A–Z)", label="Sortering")
    with gr.Row():
        search_button = gr.Button("Zoeken", variant="primary")
        reset_button = gr.Button("Filters wissen")
    status = gr.Markdown()
    table = gr.Dataframe(
        headers=DISPLAY_COLUMNS,
        value=[],
        interactive=False,
        wrap=True,
        elem_classes="result-table",
    )
    with gr.Row():
        previous_button = gr.Button("← Vorige")
        next_button = gr.Button("Volgende →")
    gr.Markdown("### Resultaten exporteren\nDe CSV bevat maximaal 100.000 rijen. Verfijn de filters voor grotere selecties.")
    export_button = gr.Button("Maak CSV van deze selectie")
    export_file = gr.File(label="CSV downloaden", interactive=False)
    export_status = gr.Markdown()

    filters = [search_box, year_box, province_box, sort_box]
    outputs = [table, status, page_state]
    search_button.click(new_search, filters, outputs)
    search_box.submit(new_search, filters, outputs)
    previous_button.click(previous_page, [*filters, page_state], outputs)
    next_button.click(next_page, [*filters, page_state], outputs)
    export_button.click(export_csv, filters, [export_file, export_status])
    reset_button.click(
        lambda: ("", "Alle", "Alle", "Naam (A–Z)"),
        outputs=filters,
    ).then(new_search, filters, outputs)
    demo.load(new_search, filters, outputs)

if __name__ == "__main__":
    demo.launch(ssr_mode=False)
