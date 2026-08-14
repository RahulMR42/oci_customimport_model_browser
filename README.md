# Oracle Custom Import Model Browser

This is a small standalone web app that crawls Oracle Generative AI imported-model documentation, extracts supported model rows, and exposes them through a searchable website.

It is intentionally scoped to Oracle imported-model documentation only:

- Root page: `https://docs.oracle.com/en-us/iaas/Content/generative-ai/imported-models.htm`
- Imported-model family pages discovered dynamically from that root page

## Current Scope

The app does not search the open web. It only:

1. Fetches the Oracle imported-model landing page
2. Recursively follows Oracle imported-model subpages under the same Generative AI docs path
3. Extracts model table rows from those pages
4. Filters and displays the results in the browser

Pages that do not produce at least one extracted model row are not shown in the UI.

## What It Does

- Fetches Oracle's imported-model catalog pages on the server side
- Recursively crawls imported-model subpages linked from the Oracle root page
- Extracts model families and supported imported-model rows
- Displays only pages that contain at least one extracted model
- Lets you search by family, model ID, capability, or recommended shape
- Supports wildcard queries such as `qwen*` and looser relative-term matches such as `llma` for `llama`
- Shows the crawled Oracle subpage list in the UI so coverage is visible
- Removes duplicate model entries and adds a Hugging Face link for each model id when available
- Lets you switch the UI between `grey` and `dark` themes
- Caches results in memory for six hours unless you hit refresh
- Requires a login before serving the application or model API
- Avoids npm and third-party Python dependencies

## Search Behavior

The search box supports:

- Exact substring matching
- Prefix matching
- Wildcards such as `qwen*`, `*vision*`, or `meta-*`
- Lightweight fuzzy and relative-word matching such as `llma` -> `llama`

Search runs against:

- Family/page title
- Oracle docs page URL
- Table section heading
- Model ID
- Capability text
- Recommended shape

## UI Behavior

The browser UI includes:

- A single search bar shared across the Oracle imported-model catalog
- A `Refresh from Oracle Docs` action to bypass the in-memory cache
- Theme switching between `grey` and `dark`
- A `Crawled Oracle subpages` section so you can verify which Oracle pages produced model results
- One card per imported-model family page
- A Hugging Face link for each model when the extracted model ID looks like a valid Hugging Face repo path

## API

The app serves one JSON API endpoint:

- `GET /api/models`

Query parameters:

- `q`: optional search query
- `refresh=1`: force a fresh crawl instead of using the cached catalog

Example:

```text
http://127.0.0.1:8080/api/models?q=qwen*&refresh=1
```

Response fields include:

- `source_url`
- `generated_at`
- `page_count`
- `crawled_pages`
- `family_count`
- `model_count`
- `families`
- `models`

## Project Files

- `app.py`: HTTP server, Oracle crawler, extraction logic, search filtering, and JSON API
- `static/index.html`: page structure
- `static/app.js`: browser-side rendering, theme toggle, and search interaction
- `static/styles.css`: UI styling
- `start.sh`: local launcher
- `requirements.txt`: stable dependency entry point, currently standard-library only

## Run

Preferred:

```bash
cd /Users/rahulmr/LocalMaster/GENAI/my_genai/codex/customimport
bash start.sh
```

Manual:

```bash
cd /Users/rahulmr/LocalMaster/GENAI/my_genai/codex/customimport
python3 app.py
```

The launcher:

- creates `.venv` if needed
- upgrades `pip`
- installs `requirements.txt`
- starts the local server

Then open:

```text
http://127.0.0.1:8080
```

Optional environment variables:

```bash
PORT=8090 HOST=0.0.0.0 python3 app.py
```

### Login credentials

The app requires a username and password. Configure them with environment variables:

```bash
APP_USER_NAME=my-user APP_PASSWORD='My-Strong-Passphrase!' python3 app.py
```

- `APP_USER_NAME` defaults to `oci` when unset or empty.
- `APP_PASSWORD` is generated as a complex 16-character value when unset or empty.
- A generated password is printed once to the application console at startup; save it from the logs before signing in.
- The `GET /api/health` endpoint remains unauthenticated for container health checks.

If you prefer to bootstrap the virtual environment yourself:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

## Notes And Limitations

- The scraper depends on the Oracle docs HTML structure. If Oracle changes the page layout, extraction logic in `app.py` may need adjustment.
- Search is intentionally basic and limited to the imported-model docs content, not the open web.
- Query matching supports exact, prefix, wildcard, and lightweight fuzzy token matching.
- Duplicate rows are removed before rendering, using model ID plus capability plus recommended shape as the effective uniqueness key.
- Pages with no extracted models are intentionally filtered out of both the page list and the family card list.
- Some family pages may temporarily fail to load or parse. The UI shows those failures inline per family instead of hiding them.
