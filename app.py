#!/usr/bin/env python3
"""Small web app that searches Oracle custom-import model docs."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from fnmatch import fnmatch
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


ROOT_DOC_URL = "https://docs.oracle.com/en-us/iaas/Content/generative-ai/imported-models.htm"
CACHE_TTL_SECONDS = 60 * 60 * 6
HTTP_TIMEOUT_SECONDS = 20
USER_AGENT = "customimport-model-browser/0.1 (+https://docs.oracle.com/)"
STATIC_DIR = Path(__file__).parent / "static"
MAX_CRAWL_PAGES = 64


def normalize_space(value: str) -> str:
    """Collapse repeated whitespace to a single space."""
    return " ".join(value.replace("\xa0", " ").split())


def build_huggingface_url(model_id: str) -> str:
    """Return a Hugging Face model URL when the model id looks valid."""
    cleaned = normalize_space(model_id)
    if "/" not in cleaned or cleaned.lower() == "unknown":
        return ""
    return f"https://huggingface.co/{cleaned}"


def fetch_html(url: str) -> str:
    """Fetch one HTML page from Oracle docs."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8", errors="replace")


@dataclass
class TableRow:
    """One parsed docs table row plus the nearest heading context."""

    heading: str
    cells: list[str]


class OracleDocsParser(HTMLParser):
    """Extract anchors, headings, and table rows from Oracle docs HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.page_title = ""
        self.current_heading = ""
        self.anchors: list[dict[str, str]] = []
        self.table_rows: list[TableRow] = []

        self._heading_tag = ""
        self._heading_parts: list[str] = []
        self._anchor_href = ""
        self._anchor_parts: list[str] = []
        self._in_table = False
        self._row_cells: list[str] = []
        self._cell_parts: list[str] = []
        self._table_heading = ""
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key: value or "" for key, value in attrs}
        if tag in {"h1", "h2", "h3", "h4"}:
            self._heading_tag = tag
            self._heading_parts = []
        elif tag == "a":
            self._anchor_href = attr_map.get("href", "")
            self._anchor_parts = []
        elif tag == "table":
            self._in_table = True
            self._table_heading = self.current_heading
        elif tag == "tr" and self._in_table:
            self._row_cells = []
        elif tag in {"td", "th"} and self._in_table:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._heading_tag:
            self._heading_parts.append(data)
        if self._anchor_href:
            self._anchor_parts.append(data)
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._heading_tag and self._heading_tag:
            heading = normalize_space("".join(self._heading_parts))
            if heading:
                self.current_heading = heading
                if tag == "h1" and not self.page_title:
                    self.page_title = heading
            self._heading_tag = ""
            self._heading_parts = []
            return

        if tag == "a" and self._anchor_href:
            text = normalize_space("".join(self._anchor_parts))
            if text:
                self.anchors.append(
                    {
                        "href": self._anchor_href,
                        "text": text,
                        "heading": self.current_heading,
                    }
                )
            self._anchor_href = ""
            self._anchor_parts = []
            return

        if tag in {"td", "th"} and self._in_cell:
            cell_text = normalize_space("".join(self._cell_parts))
            self._row_cells.append(cell_text)
            self._cell_parts = []
            self._in_cell = False
            return

        if tag == "tr" and self._in_table:
            cleaned_cells = [cell for cell in self._row_cells if cell]
            if cleaned_cells:
                self.table_rows.append(TableRow(heading=self._table_heading, cells=cleaned_cells))
            self._row_cells = []
            return

        if tag == "table":
            self._in_table = False
            self._table_heading = ""


def parse_html_document(html: str) -> OracleDocsParser:
    """Parse one Oracle docs HTML document."""
    parser = OracleDocsParser()
    parser.feed(html)
    parser.close()
    return parser


def normalize_title_as_family(title: str) -> str:
    """Turn a page title into a compact family label."""
    cleaned = normalize_space(title)
    cleaned = re.sub(r"^Supported\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+Models?$", "", cleaned, flags=re.IGNORECASE)
    return cleaned or title


def is_imported_model_docs_page(candidate_url: str, root_url: str) -> bool:
    """Return True when a URL is another imported-model docs page under the same Oracle docs tree."""
    parsed_candidate = urlparse(candidate_url)
    parsed_root = urlparse(root_url)
    if parsed_candidate.netloc != parsed_root.netloc:
        return False
    path = parsed_candidate.path.lower()
    if "/iaas/content/generative-ai/" not in path:
        return False
    if not path.endswith(".htm"):
        return False
    basename = Path(path).name
    if basename == "imported-models.htm":
        return True
    if not basename.startswith("imported-"):
        return False
    if basename == "managing-imported-models.htm":
        return False
    return basename.endswith("-models.htm")


def extract_child_page_links(page_url: str, parser: OracleDocsParser, root_url: str) -> list[str]:
    """Extract additional imported-model docs links from one page."""
    seen: set[str] = set()
    links: list[str] = []
    for anchor in parser.anchors:
        href = anchor["href"]
        if not href:
            continue
        absolute = urljoin(page_url, href)
        if not is_imported_model_docs_page(absolute, root_url):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append(absolute)
    return links


def crawl_imported_model_pages(root_url: str) -> list[dict[str, Any]]:
    """Recursively crawl imported-model docs pages reachable from the root page."""
    queue = [root_url]
    visited: set[str] = set()
    pages: list[dict[str, Any]] = []

    while queue and len(visited) < MAX_CRAWL_PAGES:
        current_url = queue.pop(0)
        if current_url in visited:
            continue
        visited.add(current_url)

        html = fetch_html(current_url)
        parser = parse_html_document(html)
        title = parser.page_title or Path(urlparse(current_url).path).stem
        pages.append(
            {
                "url": current_url,
                "page_title": title,
                "family_name": normalize_title_as_family(title),
                "parser": parser,
            }
        )

        for child_url in extract_child_page_links(current_url, parser, root_url):
            if child_url not in visited and child_url not in queue:
                queue.append(child_url)
    return pages


def row_is_header(row: TableRow) -> bool:
    """Return True when a row looks like the header of a supported-models table."""
    joined = " ".join(row.cells).lower()
    return "hugging face model id" in joined and "model capability" in joined


def extract_models_from_page(page: dict[str, Any]) -> dict[str, Any]:
    """Extract supported imported models from one crawled Oracle docs page."""
    family_name = page["family_name"]
    family_url = page["url"]
    parser: OracleDocsParser = page["parser"]
    tables: list[dict[str, Any]] = []
    active_table: dict[str, Any] | None = None
    for row in parser.table_rows:
        if row_is_header(row):
            active_table = {"heading": row.heading, "headers": row.cells, "rows": []}
            tables.append(active_table)
            continue
        if active_table and len(row.cells) >= 2:
            active_table["rows"].append(row)

    models: list[dict[str, str]] = []
    seen_rows: set[tuple[str, str, str, str]] = set()
    if tables:
        for table in tables:
            for row in table["rows"]:
                model_id = row.cells[0] if len(row.cells) >= 1 else ""
                capability = row.cells[1] if len(row.cells) >= 2 else ""
                shape = row.cells[2] if len(row.cells) >= 3 else ""
                if not model_id:
                    continue
                dedupe_key = (
                    normalize_space(model_id).lower(),
                    normalize_space(capability).lower(),
                    normalize_space(shape).lower(),
                    normalize_space(table["heading"] or parser.page_title or family_name).lower(),
                )
                if dedupe_key in seen_rows:
                    continue
                seen_rows.add(dedupe_key)
                models.append(
                    {
                        "family": family_name,
                        "section": table["heading"] or parser.page_title or family_name,
                        "model_id": model_id,
                        "capability": capability,
                        "recommended_shape": shape,
                        "huggingface_url": build_huggingface_url(model_id),
                    }
                )
    else:
        seen_fallback: set[str] = set()
        for anchor in parser.anchors:
            model_id = anchor["text"]
            href = anchor["href"]
            if "huggingface.co" not in href.lower():
                continue
            if "/" not in model_id or model_id in seen_fallback:
                continue
            seen_fallback.add(model_id)
            models.append(
                {
                    "family": family_name,
                    "section": parser.page_title or family_name,
                    "model_id": model_id,
                    "capability": "Unknown",
                    "recommended_shape": "Unknown",
                    "huggingface_url": build_huggingface_url(model_id),
                }
            )

    return {
        "name": family_name,
        "url": family_url,
        "page_title": parser.page_title or family_name,
        "model_count": len(models),
        "models": models,
    }


def tokenize_search_text(value: str) -> list[str]:
    """Split search text into normalized tokens."""
    tokens = re.split(r"[^a-z0-9]+", value.lower())
    return [token for token in tokens if token]


def normalize_token(token: str) -> str:
    """Apply a lightweight normalization for fuzzy and relative-word matching."""
    lowered = re.sub(r"[^a-z0-9]+", "", token.lower())
    for suffix in ("ings", "ing", "ers", "ies", "ied", "ed", "es", "s"):
        if len(lowered) > 4 and lowered.endswith(suffix):
            if suffix == "ies":
                return lowered[:-3] + "y"
            return lowered[: -len(suffix)]
    return lowered


def build_search_index(family: dict[str, Any], model: dict[str, str]) -> dict[str, Any]:
    """Create searchable text and tokens for one model row."""
    raw_text = " ".join(
        [
            family.get("name", ""),
            family.get("page_title", ""),
            family.get("url", ""),
            model.get("section", ""),
            model.get("model_id", ""),
            model.get("capability", ""),
            model.get("recommended_shape", ""),
        ]
    ).lower()
    raw_tokens = tokenize_search_text(raw_text)
    normalized_tokens = [normalize_token(token) for token in raw_tokens]
    return {
        "raw_text": raw_text,
        "raw_tokens": raw_tokens,
        "normalized_tokens": [token for token in normalized_tokens if token],
    }


def term_matches_index(term: str, search_index: dict[str, Any]) -> bool:
    """Return True when one query term matches the searchable index."""
    raw_text = search_index["raw_text"]
    raw_tokens: list[str] = search_index["raw_tokens"]
    normalized_tokens: list[str] = search_index["normalized_tokens"]

    if "*" in term or "?" in term:
        wildcard = term.lower()
        if fnmatch(raw_text, f"*{wildcard}*"):
            return True
        return any(fnmatch(token, wildcard) or fnmatch(token, f"*{wildcard}*") for token in raw_tokens)

    lowered = term.lower()
    normalized = normalize_token(lowered)

    if lowered in raw_text or normalized in raw_text:
        return True

    for token in raw_tokens:
        if lowered == token or token.startswith(lowered) or lowered.startswith(token):
            return True

    for token in normalized_tokens:
        if not token:
            continue
        if normalized == token or token.startswith(normalized) or normalized.startswith(token):
            return True
        if len(normalized) >= 4 and SequenceMatcher(None, normalized, token).ratio() >= 0.78:
            return True

    return False


def search_matches(query_terms: list[str], family: dict[str, Any], model: dict[str, str]) -> bool:
    """Return True when a family or model matches all query terms."""
    search_index = build_search_index(family, model)
    return all(term_matches_index(term, search_index) for term in query_terms)


def filter_catalog(catalog: dict[str, Any], query: str) -> dict[str, Any]:
    """Filter the full catalog down to one search result set."""
    normalized_query = normalize_space(query).lower()
    if not normalized_query:
        return catalog

    query_terms = normalized_query.split()
    filtered_families: list[dict[str, Any]] = []
    flat_models: list[dict[str, str]] = []
    for family in catalog["families"]:
        matching_models = [model for model in family["models"] if search_matches(query_terms, family, model)]
        family_index = build_search_index(
            family,
            {
                "section": family.get("page_title", ""),
                "model_id": family.get("name", ""),
                "capability": "",
                "recommended_shape": "",
            },
        )
        family_matches = all(term_matches_index(term, family_index) for term in query_terms)
        if not matching_models and not family_matches:
            continue
        copied_family = dict(family)
        copied_family["models"] = matching_models if matching_models else family["models"]
        copied_family["model_count"] = len(copied_family["models"])
        filtered_families.append(copied_family)
        flat_models.extend(copied_family["models"])

    return {
        **catalog,
        "query": normalized_query,
        "family_count": len(filtered_families),
        "model_count": len(flat_models),
        "families": filtered_families,
        "models": flat_models,
    }


class OracleImportedModelCatalog:
    """Cache and serve the Oracle imported-model catalog."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cached_at = 0.0
        self._catalog: dict[str, Any] | None = None

    def get_catalog(self, *, refresh: bool = False) -> dict[str, Any]:
        """Return a cached catalog or fetch a fresh one."""
        with self._lock:
            is_fresh = self._catalog and (time.time() - self._cached_at) < CACHE_TTL_SECONDS
            if self._catalog and is_fresh and not refresh:
                return self._catalog

        crawled_pages = crawl_imported_model_pages(ROOT_DOC_URL)

        families: list[dict[str, Any]] = []
        all_models: list[dict[str, str]] = []
        global_seen_models: set[tuple[str, str, str]] = set()
        for page in crawled_pages:
            if page["url"] == ROOT_DOC_URL:
                continue
            try:
                family_payload = extract_models_from_page(page)
            except Exception as exc:  # pragma: no cover - network and site-shape failures are runtime concerns.
                family_payload = {
                    "name": page["family_name"],
                    "url": page["url"],
                    "page_title": page["page_title"],
                    "model_count": 0,
                    "models": [],
                    "error": str(exc),
                }
            unique_family_models: list[dict[str, str]] = []
            for model in family_payload["models"]:
                global_key = (
                    normalize_space(model.get("model_id", "")).lower(),
                    normalize_space(model.get("capability", "")).lower(),
                    normalize_space(model.get("recommended_shape", "")).lower(),
                )
                if not global_key[0] or global_key in global_seen_models:
                    continue
                global_seen_models.add(global_key)
                unique_family_models.append(model)
            family_payload["models"] = unique_family_models
            family_payload["model_count"] = len(unique_family_models)
            if family_payload["model_count"] == 0:
                continue
            families.append(family_payload)
            all_models.extend(family_payload["models"])

        catalog = {
            "source_url": ROOT_DOC_URL,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "page_count": len(families),
            "crawled_pages": [
                {
                    "title": family["page_title"],
                    "url": family["url"],
                }
                for family in families
            ],
            "family_count": len(families),
            "model_count": len(all_models),
            "families": families,
            "models": all_models,
        }
        with self._lock:
            self._catalog = catalog
            self._cached_at = time.time()
        return catalog


CATALOG = OracleImportedModelCatalog()


class AppHandler(SimpleHTTPRequestHandler):
    """Serve the static frontend and the model-search API."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802 - required by the stdlib handler interface
        parsed = urlparse(self.path)
        if parsed.path == "/api/models":
            self._handle_models_api(parsed.query)
            return
        super().do_GET()

    def _handle_models_api(self, raw_query: str) -> None:
        params = parse_qs(raw_query)
        query = params.get("q", [""])[0]
        refresh = params.get("refresh", ["0"])[0] in {"1", "true", "yes"}
        try:
            catalog = CATALOG.get_catalog(refresh=refresh)
            payload = filter_catalog(catalog, query)
            self._write_json(200, payload)
        except Exception as exc:  # pragma: no cover - network and site-shape failures are runtime concerns.
            self._write_json(
                502,
                {
                    "error": "Failed to fetch the Oracle imported-model catalog.",
                    "detail": str(exc),
                    "source_url": ROOT_DOC_URL,
                },
            )

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: Any) -> None:
        """Print concise access logs."""
        print(f"[http] {self.address_string()} - {format % args}")


def main() -> None:
    """Start the local web server."""
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer((host, port), AppHandler)
    print(f"Serving Oracle custom-import browser on http://{host}:{port}")
    print(f"Source: {ROOT_DOC_URL}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
