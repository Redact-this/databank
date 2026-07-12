from __future__ import annotations

import faulthandler
import os
import platform
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import requests
import streamlit as st

from database import (
    DISPLAY_COLUMNS,
    NUMBER_COLUMNS,
    VALUE_FILTER_NONE,
    VALUE_FILTER_OPERATORS,
    export_csv,
    fetch_page,
    filter_choices,
    parse_number_filter_value,
)


DEFAULT_DATA_URL = (
    "https://huggingface.co/spaces/NBBJaarrekeningen/databank_test/"
    "resolve/main/data.zip?download=true"
)
DATA_URL = os.environ.get("DATA_URL", DEFAULT_DATA_URL)
DATA_DIR = Path("/tmp/jaarrekeningen")
ZIP_PATH = DATA_DIR / "data.zip"
DB_PATH = DATA_DIR / "data.db"


try:
    # Bij een native crash (zoals SIGSEGV) verschijnen de actieve Python-frames
    # in de Streamlit-log. Een gewone try/except kan zo'n crash niet opvangen.
    faulthandler.enable(all_threads=True)
except (AttributeError, OSError, RuntimeError):
    pass


def _rss_mb() -> float | None:
    """Lees het actuele procesgeheugen op Linux, indien beschikbaar."""
    status = Path("/proc/self/status")
    if not status.exists():
        return None
    try:
        for line in status.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except (OSError, ValueError, IndexError):
        return None
    return None


def _diagnose(event: str, **details: object) -> None:
    """Schrijf één compacte regel die onmiddellijk in de Cloud-log verschijnt."""
    velden = {
        "event": event,
        "pid": os.getpid(),
        "rss_mb": _rss_mb(),
        **details,
    }
    tekst = " ".join(f"{naam}={waarde!r}" for naam, waarde in velden.items())
    print(f"[diagnose] {tekst}", flush=True)


st.set_page_config(
    page_title="Jaarrekeningen Databank",
    page_icon="📊",
    layout="wide",
)

st.session_state.diagnostic_run = st.session_state.get("diagnostic_run", 0) + 1
_diagnose(
    "rerun_start",
    run=st.session_state.diagnostic_run,
    python=platform.python_version(),
    streamlit=st.__version__,
    pandas=pd.__version__,
    numpy=np.__version__,
    pyarrow=pa.__version__,
)


@st.cache_resource(show_spinner=False)
def prepare_database(url: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        return DB_PATH

    partial = ZIP_PATH.with_suffix(".zip.part")
    try:
        with requests.get(url, stream=True, timeout=(30, 600)) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
        partial.replace(ZIP_PATH)
        with zipfile.ZipFile(ZIP_PATH) as archive:
            if "data.db" not in archive.namelist():
                raise RuntimeError("data.zip bevat geen bestand met de naam data.db.")
            archive.extract("data.db", DATA_DIR)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise
    return DB_PATH


st.title("📊 Databank")
st.write(
)

try:
    with st.spinner("Databank wordt klaargemaakt… Dit kan bij de eerste start even duren."):
        db = prepare_database(DATA_URL)
except Exception as error:
    st.error("De databank kon niet worden geladen.")
    st.code(DATA_URL)
    st.info(
        "Controleer of de publieke Hugging Face Dataset-repository bestaat en "
        "of data.zip in de hoofdmap staat."
    )
    st.exception(error)
    st.stop()

filter_start = time.perf_counter()
_diagnose("filter_choices_start", run=st.session_state.diagnostic_run)
years, provinces = filter_choices(db)
_diagnose(
    "filter_choices_done",
    run=st.session_state.diagnostic_run,
    seconds=round(time.perf_counter() - filter_start, 3),
)

if "page" not in st.session_state:
    st.session_state.page = 1
filter_defaults = {
    "search": "",
    "year": "Alle",
    "province": "Alle",
    "sort_column": "Naam",
    "sort_direction": "Oplopend",
    "value_filter_column": VALUE_FILTER_NONE,
    "value_filter_operator": "Niet leeg",
    "value_filter_value": "",
}
stored_filters = st.session_state.get("filters", {})
st.session_state.filters = {
    key: stored_filters.get(key, default) for key, default in filter_defaults.items()
}
if st.session_state.filters["year"] not in years:
    st.session_state.filters["year"] = "Alle"
if st.session_state.filters["province"] not in provinces:
    st.session_state.filters["province"] = "Alle"
value_filter_columns = [VALUE_FILTER_NONE, *NUMBER_COLUMNS]
if st.session_state.filters["value_filter_column"] not in value_filter_columns:
    st.session_state.filters["value_filter_column"] = VALUE_FILTER_NONE
if st.session_state.filters["value_filter_operator"] not in VALUE_FILTER_OPERATORS:
    st.session_state.filters["value_filter_operator"] = "Niet leeg"

with st.form("search_form"):
    col1, col2, col3, col4, col5 = st.columns([3, 1, 1.5, 2, 1.2])
    with col1:
        search = st.text_input(
            "Bedrijfsnaam, ondernemingsnummer of postcode",
            value=st.session_state.filters["search"],
            placeholder="Bijvoorbeeld: bakkerij, 0123.456.789 of 9000",
        )
    with col2:
        year = st.selectbox(
            "Boekjaar", years, index=years.index(st.session_state.filters["year"])
        )
    with col3:
        province = st.selectbox(
            "Provincie",
            provinces,
            index=provinces.index(st.session_state.filters["province"]),
        )
    with col4:
        sort_column = st.selectbox(
            "Sorteer volledige databank op",
            DISPLAY_COLUMNS,
            index=DISPLAY_COLUMNS.index(st.session_state.filters["sort_column"]),
        )
    with col5:
        directions = ["Oplopend", "Aflopend"]
        sort_direction = st.selectbox(
            "Volgorde",
            directions,
            index=directions.index(st.session_state.filters["sort_direction"]),
        )

    st.markdown("**Optionele waardefilter**")
    value_col, operator_col, amount_col = st.columns([2.5, 2, 2])
    with value_col:
        value_filter_column = st.selectbox(
            "Filter op financiële kolom",
            value_filter_columns,
            index=value_filter_columns.index(
                st.session_state.filters["value_filter_column"]
            ),
        )
    with operator_col:
        value_filter_operator = st.selectbox(
            "Voorwaarde",
            VALUE_FILTER_OPERATORS,
            index=VALUE_FILTER_OPERATORS.index(
                st.session_state.filters["value_filter_operator"]
            ),
        )
    with amount_col:
        value_filter_value = st.text_input(
            "Bedrag",
            value=st.session_state.filters["value_filter_value"],
            placeholder="Bijvoorbeeld: 100000 of 59,89",
            help="Bij 'Niet leeg' wordt dit bedrag genegeerd.",
        )

    submitted = st.form_submit_button("Zoeken", type="primary")

if submitted:
    filter_error = None
    if value_filter_column == VALUE_FILTER_NONE:
        value_filter_operator = "Niet leeg"
        value_filter_value = ""
    elif value_filter_operator == "Niet leeg":
        value_filter_value = ""
    else:
        try:
            parse_number_filter_value(value_filter_value)
        except ValueError as error:
            filter_error = str(error)

    if filter_error:
        st.error(filter_error)
    else:
        st.session_state.filters = {
            "search": search,
            "year": year,
            "province": province,
            "sort_column": sort_column,
            "sort_direction": sort_direction,
            "value_filter_column": value_filter_column,
            "value_filter_operator": value_filter_operator,
            "value_filter_value": value_filter_value,
        }
        st.session_state.page = 1

active = st.session_state.filters
fetch_start = time.perf_counter()
_diagnose(
    "fetch_page_start",
    run=st.session_state.diagnostic_run,
    year=active["year"],
    province=active["province"],
    sort_column=active["sort_column"],
    sort_direction=active["sort_direction"],
    value_filter_column=active["value_filter_column"],
    value_filter_operator=active["value_filter_operator"],
    value_filter_has_amount=bool(active["value_filter_value"]),
    search_length=len(active["search"]),
    page=st.session_state.page,
)
rows, total, last_page = fetch_page(db, **active, page=st.session_state.page)
_diagnose(
    "fetch_page_done",
    run=st.session_state.diagnostic_run,
    seconds=round(time.perf_counter() - fetch_start, 3),
    rows=len(rows),
    total=total,
    last_page=last_page,
)
st.session_state.page = min(st.session_state.page, last_page)
st.markdown(
    f"**{total:,} resultaten** — pagina {st.session_state.page} van {last_page}".replace(",", ".")
)
st.caption(
    "De sortering hierboven geldt voor alle resultaten. Een klik op een tabelkop "
    "herschikt alleen de 50 rijen van de huidige pagina."
)

frame = pd.DataFrame(rows, columns=DISPLAY_COLUMNS)
text_columns = {
    "Naam",
    "Ondernemingsnummer",
    "Postcode",
    "Provincie",
    "Boekjaar",
    "Datum einde boekjaar",
    "Bestandsnaam",
}
number_columns = [column for column in DISPLAY_COLUMNS if column not in text_columns]

# Houd het schema bij elke rerun identiek. Zo krijgt de Arrow-serialisatie niet
# afwisselend object-, integer- en floatkolommen naargelang de gekozen pagina.
for column in text_columns:
    frame[column] = frame[column].astype("string")
for column in number_columns:
    frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("float64")

_diagnose(
    "dataframe_render_start",
    run=st.session_state.diagnostic_run,
    rows=len(frame),
    columns=len(frame.columns),
    frame_kb=round(frame.memory_usage(index=True, deep=True).sum() / 1024, 1),
)
st.dataframe(
    frame,
    hide_index=True,
    width="stretch",
    column_config={
        column: st.column_config.NumberColumn(column, format="%.2f")
        for column in number_columns
    },
)
_diagnose("dataframe_render_done", run=st.session_state.diagnostic_run)

previous, next_col, spacer = st.columns([1, 1, 6])
with previous:
    if st.button("← Vorige", disabled=st.session_state.page <= 1):
        st.session_state.page -= 1
        st.rerun()
with next_col:
    if st.button("Volgende →", disabled=st.session_state.page >= last_page):
        st.session_state.page += 1
        st.rerun()

st.subheader("Resultaten exporteren")
st.caption(
    "De CSV bevat maximaal de eerste 100 resultaten volgens de gekozen filters en sortering."
)
if st.button("Maak CSV van deze selectie"):
    with st.spinner("CSV wordt aangemaakt…"):
        export_start = time.perf_counter()
        _diagnose("export_start", run=st.session_state.diagnostic_run)
        csv_data, exported, truncated = export_csv(db, **active)
        _diagnose(
            "export_done",
            run=st.session_state.diagnostic_run,
            seconds=round(time.perf_counter() - export_start, 3),
            rows=exported,
            truncated=truncated,
        )
    st.session_state.csv_data = csv_data
    st.session_state.csv_note = (
        f"{exported:,} rijen geëxporteerd.".replace(",", ".")
        + (" Verfijn de filters om alle resultaten te exporteren." if truncated else "")
    )

if "csv_data" in st.session_state:
    st.download_button(
        "Download CSV",
        data=st.session_state.csv_data,
        file_name="jaarrekeningen.csv",
        mime="text/csv",
    )
    st.caption(st.session_state.csv_note)
