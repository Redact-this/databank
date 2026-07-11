from __future__ import annotations

import os
import zipfile
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from database import (
    DISPLAY_COLUMNS,
    export_csv,
    fetch_page,
    filter_choices,
)


DEFAULT_DATA_URL = (
    "https://huggingface.co/spaces/NBBJaarrekeningen/databank_test/"
    "resolve/main/data.zip?download=true"
)
DATA_URL = os.environ.get("DATA_URL", DEFAULT_DATA_URL)
DATA_DIR = Path("/tmp/jaarrekeningen")
ZIP_PATH = DATA_DIR / "data.zip"
DB_PATH = DATA_DIR / "data.db"

st.set_page_config(
    page_title="Jaarrekeningen Databank",
    page_icon="📊",
    layout="wide",
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


st.title("📊 Jaarrekeningen Databank")
st.write(
    "Zoek in financiële kerncijfers uit Belgische jaarrekeningen. "
    "Bedragen zijn in euro. Controleer belangrijke cijfers bij de oorspronkelijke NBB-bron."
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

years, provinces = filter_choices(db)

if "page" not in st.session_state:
    st.session_state.page = 1
filter_defaults = {
    "search": "",
    "year": "Alle",
    "province": "Alle",
    "sort_column": "Naam",
    "sort_direction": "Oplopend",
}
stored_filters = st.session_state.get("filters", {})
st.session_state.filters = {
    key: stored_filters.get(key, default) for key, default in filter_defaults.items()
}
if st.session_state.filters["year"] not in years:
    st.session_state.filters["year"] = "Alle"
if st.session_state.filters["province"] not in provinces:
    st.session_state.filters["province"] = "Alle"

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
    submitted = st.form_submit_button("Zoeken", type="primary")

if submitted:
    st.session_state.filters = {
        "search": search,
        "year": year,
        "province": province,
        "sort_column": sort_column,
        "sort_direction": sort_direction,
    }
    st.session_state.page = 1

active = st.session_state.filters
rows, total, last_page = fetch_page(db, **active, page=st.session_state.page)
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
st.dataframe(
    frame,
    hide_index=True,
    use_container_width=True,
    column_config={
        column: st.column_config.NumberColumn(column, format="%.2f")
        for column in number_columns
    },
)

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
        csv_data, exported, truncated = export_csv(db, **active)
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
