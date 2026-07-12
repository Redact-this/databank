

## Data

De toepassing downloadt bij de eerste start automatisch:

`https://huggingface.co/spaces/NBBJaarrekeningen/databank_test/resolve/main/data.zip`

De bestaande Hugging Face Space `NBBJaarrekeningen/databank_test` wordt dus als
bestandsopslag gebruikt. De Space-repository moet publiek zijn en `data.zip`
moet in de hoofdmap staan. De Hugging Face-runtime zelf hoeft niet te werken.

Een andere URL kan in Streamlit onder **App settings → Secrets** worden
ingesteld:

```toml
DATA_URL = "https://huggingface.co/datasets/EIGENAAR/REPOSITORY/resolve/main/data.zip?download=true"
```

## Publiceren

1. Ga naar https://share.streamlit.io en meld je aan met GitHub.
2. Kies **Create app** en selecteer `Redact-this/databank`.
3. Branch: `main`.
4. Main file path: `app.py`.
5. Klik **Deploy**.

De databank staat niet op GitHub en telt dus niet mee voor de GitHub-
bestandslimiet.
