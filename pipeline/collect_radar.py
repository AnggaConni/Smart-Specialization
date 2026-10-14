#!/usr/bin/env python3
"""Build a source-attributed S3 Smart Specialization Radar JSON snapshot.

The frontend consumes data/radar-data.json. This collector uses public APIs and
keeps source status, publication dates, retrieval dates, limitations, and failures
visible. UN Comtrade is optional-key: unauthenticated preview data is limited.
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config" / "radar_sources.json"
OUTPUT = DATA_DIR / "radar-data.json"
USER_AGENT = (
    "S3-Smart-Specialization-Radar/1.0 "
    "(open-data research prototype; contact configured via S3_CONTACT_EMAIL)"
)
LOG = logging.getLogger("s3-radar")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")

OPENALEX_URL = "https://api.openalex.org/works"
CROSSREF_URL = "https://api.crossref.org/works"
COMTRADE_REPORTERS_URL = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"
WB_BASE = "https://api.worldbank.org/v2"
COMTRADE_SOURCE = "https://comtradeplus.un.org/"
GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WB_INDICATORS = {
    "gdp_usd": "NY.GDP.MKTP.CD",
    "gdp_per_capita_usd": "NY.GDP.PCAP.CD",
    "population": "SP.POP.TOTL",
    "trade_pct_gdp": "NE.TRD.GNFS.ZS",
}


def make_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4, connect=3, read=3, backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]), respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    email = os.getenv("S3_CONTACT_EMAIL", "").strip()
    session.headers.update({
        "User-Agent": USER_AGENT + (f"; mailto:{email}" if email else ""),
        "Accept": "application/json",
    })
    return session


def request_json(
    session: requests.Session,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 50,
) -> Any:
    response = session.get(url, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def as_iso3(value: Any) -> bool:
    return bool(re.fullmatch(r"[A-Z]{3}", str(value or "").strip().upper()))


def normalise_doi(value: Any) -> str:
    doi = str(value or "").strip().lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    return doi.strip()


def clean_text(value: Any, limit: int = 2000) -> str:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value if item)
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def reconstruct_abstract(inverted: Any, limit: int = 900) -> str:
    if not isinstance(inverted, dict):
        return ""
    words: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            try:
                words.append((int(pos), str(word)))
            except (TypeError, ValueError):
                continue
    if not words:
        return ""
    words.sort(key=lambda item: item[0])
    # Reconstruct positions without fabricating words; repeated positions are retained.
    text = " ".join(word for _, word in words)
    return clean_text(text, limit)


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def safe_date(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        parsed = date.fromisoformat(text)
        # Guard against malformed/future bibliographic dates (e.g. year 2121).
        if parsed.year < 1800 or parsed.year > date.today().year + 1:
            return None
        return parsed.isoformat()
    except ValueError:
        return None


def publication_date_from_crossref(item: dict[str, Any]) -> str | None:
    for key in ("published", "published-print", "published-online", "issued", "created"):
        part = item.get(key, {}).get("date-parts", [])
        if part and part[0]:
            pieces = part[0]
            try:
                year = int(pieces[0])
                if year < 1800 or year > date.today().year + 1:
                    continue
                month = int(pieces[1]) if len(pieces) > 1 else 1
                day = int(pieces[2]) if len(pieces) > 2 else 1
                return date(year, month, day).isoformat()
            except (TypeError, ValueError):
                continue
    return None


def openalex_record(work: dict[str, Any], topic: dict[str, str]) -> dict[str, Any] | None:
    title = clean_text(work.get("title"), 500)
    if not title:
        return None
    doi = normalise_doi(work.get("doi"))
    source_obj = (work.get("primary_location") or {}).get("source") or {}
    venue = clean_text(source_obj.get("display_name"), 200)
    doi_url = "https://doi.org/" + doi if doi else ""
    landing = (work.get("primary_location") or {}).get("landing_page_url") or doi_url or work.get("id", "")
    countries: set[str] = set()
    authors: list[str] = []
    for authorship in work.get("authorships") or []:
        author = (authorship.get("author") or {}).get("display_name")
        if author and len(authors) < 8:
            authors.append(clean_text(author, 120))
        for institution in authorship.get("institutions") or []:
            code = str(institution.get("country_code") or "").upper()
            if re.fullmatch(r"[A-Z]{2}", code):
                countries.add(code)
    abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
    raw_year = work.get("publication_year")
    try:
        publication_year = int(raw_year) if raw_year is not None else None
    except (TypeError, ValueError):
        publication_year = None
    if publication_year is not None and not (1800 <= publication_year <= date.today().year + 1):
        publication_year = None
    pubdate = safe_date(work.get("publication_date")) or (
        f"{publication_year:04d}-01-01" if publication_year is not None else None
    )
    return {
        "title": title,
        "doi": doi,
        "url": landing,
        "publication_date": pubdate,
        "year": int(pubdate[:4]) if pubdate else publication_year,
        "venue": venue,
        "publisher": "",
        "authors": authors,
        "abstract": abstract,
        "cited_by_count": int(work.get("cited_by_count") or 0),
        "data_sources": ["OpenAlex"],
        "source_urls": ["https://openalex.org/"],
        "sectors": [topic["sector"]],
        "queries": [topic["query"]],
        "author_country_iso2": sorted(countries),
        "record_type": "research",
    }


def crossref_record(item: dict[str, Any], topic: dict[str, str]) -> dict[str, Any] | None:
    titles = item.get("title") or []
    title = clean_text(titles[0] if titles else "", 500)
    if not title:
        return None
    doi = normalise_doi(item.get("DOI"))
    venue_items = item.get("container-title") or []
    venue = clean_text(venue_items[0] if venue_items else "", 200)
    link = clean_text(item.get("URL") or ("https://doi.org/" + doi if doi else ""), 1000)
    authors = []
    for author in item.get("author") or []:
        name = clean_text(" ".join(filter(None, [author.get("given"), author.get("family")])), 120)
        if name and len(authors) < 8:
            authors.append(name)
    pubdate = publication_date_from_crossref(item)
    abstract = clean_text(item.get("abstract"), 900)
    return {
        "title": title, "doi": doi, "url": link,
        "publication_date": pubdate,
        "year": int(pubdate[:4]) if pubdate else None,
        "venue": venue, "publisher": clean_text(item.get("publisher"), 200),
        "authors": authors, "abstract": abstract,
        "cited_by_count": int(item.get("is-referenced-by-count") or 0),
        "data_sources": ["Crossref"], "source_urls": ["https://api.crossref.org/"],
        "sectors": [topic["sector"]], "queries": [topic["query"]],
        "author_country_iso2": [], "record_type": "research",
    }


def signal_key(record: dict[str, Any]) -> str:
    doi = normalise_doi(record.get("doi"))
    if doi:
        return "doi:" + doi
    title = re.sub(r"[^a-z0-9]+", " ", str(record.get("title", "")).lower()).strip()
    year = str(record.get("year") or (record.get("publication_date") or "")[:4])
    return "title:" + title + ":" + year


def merge_signals(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for record in records:
        key = signal_key(record)
        if key.endswith("::") or key == "title::":
            continue
        current = merged.get(key)
        if current is None:
            current = dict(record)
            current["sectors"] = list(dict.fromkeys(record.get("sectors") or []))
            current["queries"] = list(dict.fromkeys(record.get("queries") or []))
            current["data_sources"] = list(dict.fromkeys(record.get("data_sources") or []))
            current["source_urls"] = list(dict.fromkeys(record.get("source_urls") or []))
            current["authors"] = list(dict.fromkeys(record.get("authors") or []))
            current["author_country_iso2"] = list(dict.fromkeys(record.get("author_country_iso2") or []))
            merged[key] = current
            continue
        for field in ("sectors", "queries", "data_sources", "source_urls", "authors", "author_country_iso2"):
            current[field] = list(dict.fromkeys((current.get(field) or []) + (record.get(field) or [])))
        if len(record.get("abstract") or "") > len(current.get("abstract") or ""):
            current["abstract"] = record["abstract"]
        if not current.get("venue") and record.get("venue"):
            current["venue"] = record["venue"]
        if not current.get("publisher") and record.get("publisher"):
            current["publisher"] = record["publisher"]
        if not current.get("url") and record.get("url"):
            current["url"] = record["url"]
        current["cited_by_count"] = max(int(current.get("cited_by_count") or 0), int(record.get("cited_by_count") or 0))
        current["publication_date"] = max(
            filter(None, [current.get("publication_date"), record.get("publication_date")]), default=None
        )
    today = date.today()
    out = []
    for record in merged.values():
        pubdate = safe_date(record.get("publication_date"))
        age_days = (today - date.fromisoformat(pubdate)).days if pubdate else 9999
        recency = 45 if age_days <= 90 else 35 if age_days <= 180 else 25 if age_days <= 365 else 10 if age_days <= 730 else 0
        citations = min(20, round(math.log1p(max(0, int(record.get("cited_by_count") or 0))) * 3))
        theme_coverage = min(20, max(0, len(record.get("sectors") or []) - 1) * 7 + max(0, len(record.get("queries") or []) - 1) * 3)
        abstract_bonus = 10 if record.get("abstract") else 0
        record["discovery_score"] = min(100, recency + citations + theme_coverage + abstract_bonus)
        record["publication_date"] = pubdate
        record["year"] = int(pubdate[:4]) if pubdate else record.get("year")
        record["id"] = key_id(record)
        record["summary"] = record.get("abstract") or (
            f"Bibliographic record discovered through the topic query: {(record.get('queries') or [''])[0]}."
        )
        record["evidence_note"] = (
            "Discovery score prioritises recency and bibliographic context; it is not a verified impact, risk, or investment score."
        )
        out.append(record)
    out.sort(key=lambda item: (item.get("publication_date") or "", item.get("discovery_score") or 0), reverse=True)
    return out[:600]


def key_id(record: dict[str, Any]) -> str:
    import hashlib
    return hashlib.sha1(signal_key(record).encode("utf-8")).hexdigest()[:16]


def fetch_research(session: requests.Session, config: dict[str, Any], since: str) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    all_records: list[dict[str, Any]] = []
    warnings: list[str] = []
    stats = {
        "openalex": {"name": "OpenAlex", "url": "https://openalex.org/", "status": "error", "records": 0, "requests_ok": 0},
        "crossref": {"name": "Crossref", "url": "https://www.crossref.org/", "status": "error", "records": 0, "requests_ok": 0},
    }
    email = os.getenv("S3_CONTACT_EMAIL", "").strip()
    topics = config.get("topics", [])
    for topic in topics:
        # OpenAlex provides bibliographic metadata and abstract inverted indexes.
        try:
            params: dict[str, Any] = {
                "search": topic["query"],
                "filter": f"from_publication_date:{since}",
                "sort": "publication_date:desc",
                "per-page": int(config.get("openalex_per_topic", 15)),
            }
            if email and "@" in email:
                params["mailto"] = email
            payload = request_json(session, OPENALEX_URL, params=params)
            results = payload.get("results", []) if isinstance(payload, dict) else []
            converted = [row for row in (openalex_record(item, topic) for item in results) if row]
            all_records.extend(converted)
            stats["openalex"]["requests_ok"] += 1
            stats["openalex"]["records"] += len(converted)
            stats["openalex"]["status"] = "ok"
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            warnings.append(f"OpenAlex query '{topic['query']}' failed: {exc}")
            LOG.warning("OpenAlex query failed (%s): %s", topic["query"], exc)
        time.sleep(0.15)

        # Crossref is a second metadata provider; duplicate DOIs are merged.
        try:
            params = {
                "query": topic["query"],
                "filter": f"from-pub-date:{since},type:journal-article",
                "rows": int(config.get("crossref_per_topic", 10)),
                "sort": "published",
                "order": "desc",
                "select": "DOI,title,URL,published,published-print,published-online,issued,created,container-title,author,publisher,type,is-referenced-by-count",
            }
            if config.get("crossref_mailto"):
                params["mailto"] = config["crossref_mailto"]
            contact = os.getenv("S3_CONTACT_EMAIL", "").strip()
            if contact:
                params["mailto"] = contact
            payload = request_json(session, CROSSREF_URL, params=params)
            items = (payload.get("message") or {}).get("items", []) if isinstance(payload, dict) else []
            converted = [row for row in (crossref_record(item, topic) for item in items) if row]
            all_records.extend(converted)
            stats["crossref"]["requests_ok"] += 1
            stats["crossref"]["records"] += len(converted)
            stats["crossref"]["status"] = "ok"
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            warnings.append(f"Crossref query '{topic['query']}' failed: {exc}")
            LOG.warning("Crossref query failed (%s): %s", topic["query"], exc)
        time.sleep(0.15)
    return merge_signals(all_records), stats, warnings


def latest_indicator(session: requests.Session, indicator: str) -> dict[str, dict[str, Any]]:
    url = f"{WB_BASE}/country/all/indicator/{indicator}"
    payload = request_json(session, url, params={"format": "json", "mrnev": 1, "per_page": 20000})
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        iso = str(row.get("countryiso3code") or "").upper()
        value = as_float(row.get("value"))
        year = str(row.get("date") or "")
        if not as_iso3(iso) or value is None:
            continue
        prior = result.get(iso)
        if prior is None or year > str(prior.get("year") or ""):
            result[iso] = {"value": value, "year": year}
    return result


def fetch_world_bank(session: requests.Session) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[str]]:
    warnings: list[str] = []
    status: dict[str, Any] = {
        "name": "World Bank Indicators API", "url": "https://api.worldbank.org/v2/",
        "status": "error", "countries": 0, "indicators": {},
    }
    try:
        payload = request_json(session, f"{WB_BASE}/country", params={"format": "json", "per_page": 400})
        rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list) else []
        countries: dict[str, dict[str, Any]] = {}
        for row in rows:
            iso = str(row.get("id") or "").upper()
            region = row.get("region") or {}
            if not as_iso3(iso) or region.get("value") == "Aggregates":
                continue
            coords = (as_float(row.get("latitude")), as_float(row.get("longitude")))
            countries[iso] = {
                "iso3": iso,
                "iso2": str(row.get("iso2Code") or "").upper(),
                "name": clean_text(row.get("name"), 150),
                "capital": clean_text(row.get("capitalCity"), 150),
                "latitude": coords[0] if coords[0] not in (None, 0.0) else None,
                "longitude": coords[1] if coords[1] not in (None, 0.0) else None,
                "coordinate_type": "World Bank capital reference point",
                "region": clean_text(region.get("value"), 100),
                "income_level": clean_text((row.get("incomeLevel") or {}).get("value"), 100),
                "indicators": {},
            }
        status["status"] = "ok"
    except (requests.RequestException, ValueError, TypeError) as exc:
        warnings.append(f"World Bank country registry failed: {exc}")
        LOG.warning("World Bank country registry failed: %s", exc)
        countries = {}

    for key, indicator in WB_INDICATORS.items():
        try:
            values = latest_indicator(session, indicator)
            for iso, item in values.items():
                if iso in countries:
                    countries[iso]["indicators"][key] = item
            status["indicators"][key] = {"indicator": indicator, "status": "ok", "countries": len(values)}
        except (requests.RequestException, ValueError, TypeError) as exc:
            warnings.append(f"World Bank indicator {indicator} failed: {exc}")
            status["indicators"][key] = {"indicator": indicator, "status": "error", "countries": 0}
            LOG.warning("World Bank indicator %s failed: %s", indicator, exc)
    status["countries"] = len(countries)
    if not countries:
        status["status"] = "error"
    return countries, status, warnings


def comtrade_years() -> list[int]:
    current = datetime.now(timezone.utc).year
    end_year = int(os.getenv("COMTRADE_END_YEAR", str(current - 2)))
    start_year = int(os.getenv("COMTRADE_START_YEAR", str(end_year - 3)))
    if start_year > end_year or end_year > current:
        raise ValueError("Invalid COMTRADE_START_YEAR / COMTRADE_END_YEAR range")
    if end_year - start_year > 7:
        raise ValueError("Trade collection range is limited to eight years per run")
    return list(range(start_year, end_year + 1))


COMTRADE_KEY_REJECTED = False


def fetch_comtrade_rows(
    session: requests.Session, reporter_code: int, year: int, api_key: str,
    max_records: int, product_codes: list[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    global COMTRADE_KEY_REJECTED
    use_auth = bool(api_key) and not COMTRADE_KEY_REJECTED
    params: dict[str, Any] = {
        "reporterCode": reporter_code,
        "flowCode": "M",
        "period": year,
        "maxrecords": max_records if use_auth else min(max_records, 500),
        "includeDesc": "true",
    }
    if product_codes:
        params["cmdCode"] = ",".join(product_codes[:20])
        # Leave partnerCode unset to retrieve partner-level import observations.
    else:
        params["partnerCode"] = 0
    if use_auth:
        try:
            payload = request_json(
                session, "https://comtradeapi.un.org/data/v1/get/C/A/HS",
                params=params, headers={"Ocp-Apim-Subscription-Key": api_key}, timeout=60,
            )
            mode = "live"
        except requests.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code not in (401, 403):
                raise
            # A stale/invalid stored key should not disable all trade collection.
            COMTRADE_KEY_REJECTED = True
            LOG.warning("Configured UN Comtrade key was rejected (HTTP %s); falling back to public preview.", status_code)
            payload = request_json(
                session, "https://comtradeapi.un.org/public/v1/preview/C/A/HS",
                params=params, headers=None, timeout=60,
            )
            mode = "preview-limited"
    else:
        payload = request_json(
            session, "https://comtradeapi.un.org/public/v1/preview/C/A/HS",
            params=params, headers=None, timeout=60,
        )
        mode = "preview-limited"
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise RuntimeError(f"Unexpected UN Comtrade response for reporter {reporter_code}, year {year}")
    return rows, mode


def classification_rank(row: dict[str, Any]) -> int:
    value = str(row.get("classificationCode") or "").upper()
    return int(value[1]) if len(value) == 2 and value.startswith("H") and value[1].isdigit() else -1


def build_trade_products(
    raw_by_market_year: dict[tuple[str, int], list[dict[str, Any]]],
    reporter_names: dict[str, str],
) -> list[dict[str, Any]]:
    dedup: dict[tuple[str, int, str], dict[str, Any]] = {}
    names: dict[str, str] = {}
    for (iso, year), rows in raw_by_market_year.items():
        for row in rows:
            raw_code = str(row.get("cmdCode") or "").strip()
            if not raw_code.isdigit() or len(raw_code) not in (5, 6):
                continue
            code = raw_code.zfill(6)
            value = as_float(row.get("primaryValue"))
            if value is None or value < 0:
                continue
            key = (iso, year, code)
            if key not in dedup or classification_rank(row) > classification_rank(dedup[key]):
                dedup[key] = row
            description = clean_text(row.get("cmdDesc") or row.get("cmdDescE"), 300)
            if description:
                names.setdefault(code, description)

    grouped: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for (iso, year, code), row in dedup.items():
        value = as_float(row.get("primaryValue"))
        if value is not None:
            grouped[(iso, code)][year] = value
    products: list[dict[str, Any]] = []
    for (iso, code), observations in grouped.items():
        series = [{"year": year, "import_value_usd": observations[year]} for year in sorted(observations)]
        if not series or not any(item["import_value_usd"] > 0 for item in series):
            continue
        latest = series[-1]
        previous = observations.get(latest["year"] - 1)
        yoy = (latest["import_value_usd"] / previous - 1) * 100 if previous is not None and previous > 0 else None
        positive = [point for point in series if point["import_value_usd"] > 0]
        cagr = None
        if len(positive) >= 2:
            interval = positive[-1]["year"] - positive[0]["year"]
            if interval > 0:
                cagr = (pow(positive[-1]["import_value_usd"] / positive[0]["import_value_usd"], 1 / interval) - 1) * 100
                if not math.isfinite(cagr):
                    cagr = None
        products.append({
            "id": f"{iso}-{code}", "market_iso3": iso,
            "market_name": reporter_names.get(iso, iso),
            "product_code": code, "product_name": names.get(code, f"HS {code}"),
            "latest_year": latest["year"], "latest_import_usd": latest["import_value_usd"],
            "previous_year": latest["year"] - 1 if previous is not None else None,
            "previous_import_usd": previous, "yoy_growth_pct": yoy,
            "cagr_pct": cagr, "series": series,
            "source_name": "UN Comtrade", "source_url": COMTRADE_SOURCE,
            "data_status": "reported import statistics; not retail sales",
        })
    # Limit the public JSON footprint while retaining each market's leading products.
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in products:
        by_market[item["market_iso3"]].append(item)
    limited: list[dict[str, Any]] = []
    per_market = int(os.getenv("S3_PRODUCTS_PER_MARKET", "150"))
    for iso, rows in by_market.items():
        limited.extend(sorted(rows, key=lambda r: (r["latest_year"], r["latest_import_usd"]), reverse=True)[:per_market])
    return sorted(limited, key=lambda r: r["latest_import_usd"], reverse=True)


def build_trade_flows(
    raw_rows: list[dict[str, Any]],
    buyer_iso3: str,
    buyer_name: str,
    requested_year: int,
    partner_code_to_iso: dict[str, str],
) -> list[dict[str, Any]]:
    dedup: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    for row in raw_rows:
        partner_code = str(row.get("partnerCode") or "").strip()
        supplier_iso = str(row.get("partnerISO") or row.get("partnerIso") or "").strip().upper()
        if not as_iso3(supplier_iso):
            supplier_iso = partner_code_to_iso.get(partner_code, "")
        if not as_iso3(supplier_iso) or supplier_iso in {"W00", "UNK"} or supplier_iso == buyer_iso3:
            continue
        code_raw = str(row.get("cmdCode") or "").strip()
        if not code_raw.isdigit() or len(code_raw) not in (5, 6):
            continue
        code = code_raw.zfill(6)
        value = as_float(row.get("primaryValue"))
        if value is None or value <= 0:
            continue
        try:
            year = int(row.get("period") or row.get("refYear") or requested_year)
        except (TypeError, ValueError):
            year = requested_year
        item = {
            "id": f"{supplier_iso}-{buyer_iso3}-{code}-{year}",
            "supplier_iso3": supplier_iso,
            "supplier_name": clean_text(row.get("partnerDesc") or row.get("partnerName") or supplier_iso, 150),
            "buyer_iso3": buyer_iso3, "buyer_name": buyer_name,
            "product_code": code,
            "product_name": clean_text(row.get("cmdDesc") or row.get("cmdDescE") or f"HS {code}", 300),
            "year": year, "import_value_usd": value,
            "quantity": as_float(row.get("qty")), "net_weight_kg": as_float(row.get("netWgt")),
            "source_name": "UN Comtrade", "source_url": COMTRADE_SOURCE,
            "flow_semantics": "Declared partner origin to reporting importer, based on the importer's report.",
        }
        key = (supplier_iso, buyer_iso3, code, year)
        if key not in dedup or value > dedup[key]["import_value_usd"]:
            dedup[key] = item
    return list(dedup.values())


def fetch_trade(
    session: requests.Session, config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[str]]:
    global COMTRADE_KEY_REJECTED
    COMTRADE_KEY_REJECTED = False
    api_key = os.getenv("UN_COMTRADE_API_KEY", "").strip() or os.getenv("COMTRADE_API_KEY", "").strip()
    status: dict[str, Any] = {
        "name": "UN Comtrade", "url": COMTRADE_SOURCE,
        "status": "error", "mode": "live" if api_key else "preview-limited",
        "markets_requested": 0, "market_year_requests_ok": 0, "flow_requests_ok": 0,
        "product_records": 0, "flow_records": 0, "api_key_configured": bool(api_key),
    }
    warnings: list[str] = []
    try:
        years = comtrade_years()
        reporters_payload = request_json(session, COMTRADE_REPORTERS_URL)
        reporter_rows = reporters_payload.get("results", []) if isinstance(reporters_payload, dict) else []
        reporters: dict[str, dict[str, Any]] = {}
        code_to_iso: dict[str, str] = {}
        for row in reporter_rows:
            iso = str(row.get("reporterCodeIsoAlpha3") or "").strip().upper()
            code = str(row.get("reporterCode") or "").strip()
            if as_iso3(iso) and code and not row.get("isGroup") and not row.get("entryExpiredDate"):
                reporters[iso] = {"code": int(code), "name": clean_text(row.get("reporterDesc") or row.get("text") or iso, 150)}
                code_to_iso[code] = iso
        selected = [iso.upper() for iso in config.get("markets", []) if iso.upper() in reporters]
        status["markets_requested"] = len(selected)
        unresolved = sorted(set(config.get("markets", [])) - set(selected))
        if unresolved:
            warnings.append("UN Comtrade reporter codes not resolved for: " + ", ".join(unresolved))
        raw_by_market_year: dict[tuple[str, int], list[dict[str, Any]]] = {}
        pause = max(0.0, float(os.getenv("S3_REQUEST_SLEEP_SECONDS", "0.15" if api_key else "0.7")))
        max_records = int(os.getenv("S3_COMTRADE_MAX_RECORDS", "12000" if api_key else "500"))
        successful_requests = 0
        for iso in selected:
            for year in years:
                try:
                    rows, mode = fetch_comtrade_rows(session, reporters[iso]["code"], year, api_key, max_records)
                    if mode != "live":
                        if api_key and COMTRADE_KEY_REJECTED:
                            status["api_key_auth"] = "rejected; public preview used"
                        api_key = ""
                        status["mode"] = "preview-limited"
                    raw_by_market_year[(iso, year)] = rows
                    successful_requests += 1
                    status["status"] = "ok"
                    LOG.info("UN Comtrade %s/%s: %d rows (%s)", iso, year, len(rows), mode)
                except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
                    warnings.append(f"UN Comtrade {iso}/{year} failed: {exc}")
                    LOG.warning("UN Comtrade %s/%s failed: %s", iso, year, exc)
                time.sleep(pause)
        products = build_trade_products(
            raw_by_market_year, {iso: reporters[iso]["name"] for iso in selected}
        )
        if successful_requests:
            status["market_year_requests_ok"] = successful_requests
            status["product_records"] = len(products)
        targets_by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for product in products:
            targets_by_market[product["market_iso3"]].append(product)
        flows: dict[str, dict[str, Any]] = {}
        target_limit = int(os.getenv("S3_FLOW_PRODUCTS_PER_MARKET", "4"))
        flow_max_records = int(os.getenv("S3_FLOW_MAX_RECORDS", "30000" if api_key else "500"))
        for iso, rows in targets_by_market.items():
            latest_year = max((row["latest_year"] for row in rows), default=None)
            targets = sorted(
                (row for row in rows if row["latest_year"] == latest_year),
                key=lambda row: row["latest_import_usd"], reverse=True,
            )[:max(1, target_limit)]
            if not targets or latest_year is None:
                continue
            try:
                partner_rows, flow_mode = fetch_comtrade_rows(
                    session, reporters[iso]["code"], int(latest_year), api_key, flow_max_records,
                    [row["product_code"] for row in targets],
                )
                if flow_mode != "live":
                    if api_key and COMTRADE_KEY_REJECTED:
                        status["api_key_auth"] = "rejected; public preview used"
                    api_key = ""
                    status["mode"] = "preview-limited"
                status["flow_requests_ok"] += 1
                allowed = {row["product_code"] for row in targets}
                for flow in build_trade_flows(partner_rows, iso, reporters[iso]["name"], int(latest_year), code_to_iso):
                    if flow["product_code"] in allowed:
                        flows[flow["id"]] = flow
                LOG.info("UN Comtrade flows %s/%s: %d retained edges", iso, latest_year, len(flows))
            except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
                warnings.append(f"UN Comtrade partner breakdown for {iso}/{latest_year} failed: {exc}")
                LOG.warning("UN Comtrade partner breakdown failed for %s: %s", iso, exc)
            time.sleep(pause)
        flow_list = sorted(flows.values(), key=lambda item: item["import_value_usd"], reverse=True)[:5000]
        status["flow_records"] = len(flow_list)
        if successful_requests == 0:
            status["status"] = "error"
        elif not api_key:
            status["status"] = "preview-limited"
        elif warnings:
            status["status"] = "partial"
        return products, flow_list, status, warnings
    except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
        warnings.append(f"UN Comtrade collector failed: {exc}")
        status["status"] = "error"
        LOG.exception("UN Comtrade collector failed")
        return [], [], status, warnings




def gdelt_date(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    return safe_date(raw)


def gdelt_url_key(value: str) -> str:
    from urllib.parse import urlsplit, urlunsplit
    try:
        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return ""
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))
    except ValueError:
        return ""


def fetch_gdelt_news(
    session: requests.Session, config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    """Discover source-linked news leads from GDELT DOC 2.0; never treat them as verified facts."""
    warnings: list[str] = []
    queries = config.get("news_queries", [])
    status: dict[str, Any] = {
        "name": "GDELT DOC 2.0",
        "url": "https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/",
        "endpoint": GDELT_DOC_URL,
        "status": "error",
        "queries_requested": len(queries),
        "queries_ok": 0,
        "records": 0,
        "window": "7 days",
        "authentication": "No API key required",
    }
    combined: dict[str, dict[str, Any]] = {}
    for topic in queries:
        query = clean_text(topic.get("query"), 500)
        if not query:
            continue
        try:
            payload = request_json(
                session,
                GDELT_DOC_URL,
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "maxrecords": min(50, max(1, int(config.get("gdelt_max_records_per_query", 30)))),
                    "timespan": "7d",
                    "sort": "HybridRel",
                },
                timeout=35,
            )
            articles = payload.get("articles", []) if isinstance(payload, dict) else []
            if not isinstance(articles, list):
                raise RuntimeError("Unexpected GDELT response shape: 'articles' is not a list")
            status["queries_ok"] += 1
            for article in articles:
                title = clean_text(article.get("title"), 500)
                url = gdelt_url_key(str(article.get("url") or ""))
                if not title or not url:
                    continue
                published = gdelt_date(article.get("seendate") or article.get("date"))
                source_country = clean_text(article.get("sourcecountry"), 100)
                record_id = key_id({"title": title, "url": url})
                sector = clean_text(topic.get("sector") or "Emerging Signals", 100)
                existing = combined.get(url)
                if existing is None:
                    combined[url] = {
                        "id": "news-" + record_id,
                        "title": title,
                        "url": url,
                        "publisher_domain": clean_text(article.get("domain"), 180),
                        "publication_date": published,
                        "language": clean_text(article.get("language"), 50),
                        "source_country": source_country,
                        "sectors": [sector],
                        "matched_queries": [query],
                        "data_source": "GDELT DOC 2.0",
                        "source_url": "https://www.gdeltproject.org/",
                        "record_type": "news-lead",
                        "summary": "",
                        "evidence_note": "Discovery lead only. Open and verify the publisher's original page before using it as evidence.",
                    }
                else:
                    existing["sectors"] = list(dict.fromkeys(existing["sectors"] + [sector]))
                    existing["matched_queries"] = list(dict.fromkeys(existing["matched_queries"] + [query]))
                    if not existing.get("source_country") and source_country:
                        existing["source_country"] = source_country
                    if not existing.get("publication_date") and published:
                        existing["publication_date"] = published
            time.sleep(max(0.25, float(config.get("gdelt_pause_seconds", 0.6))))
        except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
            warnings.append(f"GDELT query '{query}' failed: {exc}")
            LOG.warning("GDELT query failed (%s): %s", query, exc)

    today = date.today()
    news = list(combined.values())
    for item in news:
        published = safe_date(item.get("publication_date"))
        age = (today - date.fromisoformat(published)).days if published else 999
        # This is a freshness/relevance triage value, not a truth or impact score.
        item["freshness_score"] = max(0, 100 - min(100, age * 4)) if published else 0
        item["publication_date"] = published
    news.sort(key=lambda item: (item.get("publication_date") or "", item.get("freshness_score") or 0), reverse=True)
    news = news[:500]
    status["records"] = len(news)
    if status["queries_ok"] == 0 and queries:
        status["status"] = "error"
    elif warnings:
        status["status"] = "partial"
    else:
        status["status"] = "ok"
    return news, status, warnings


def load_previous() -> dict[str, Any]:
    try:
        if OUTPUT.exists():
            payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
    except (OSError, ValueError) as exc:
        LOG.warning("Could not load previous snapshot: %s", exc)
    return {}


def atomic_write(payload: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")
    temporary.replace(OUTPUT)


def main() -> int:
    config = load_config()
    previous = load_previous()
    session = make_session()
    today = date.today()
    since = (today - timedelta(days=int(config.get("lookback_days", 730)))).isoformat()
    warnings: list[str] = []
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")

    signals, research_status, research_warnings = fetch_research(session, config, since)
    warnings.extend(research_warnings)
    countries, wb_status, wb_warnings = fetch_world_bank(session)
    warnings.extend(wb_warnings)
    products, flows, trade_status, trade_warnings = fetch_trade(session, config)
    warnings.extend(trade_warnings)
    news, gdelt_status, gdelt_warnings = fetch_gdelt_news(session, config)
    warnings.extend(gdelt_warnings)

    sources_ok = any(item.get("status") in {"ok", "partial", "preview-limited"} for item in [research_status["openalex"], research_status["crossref"], wb_status, trade_status, gdelt_status])
    if not signals and previous.get("signals"):
        signals = previous["signals"]
        warnings.append("Research providers returned no new records; the previous signals snapshot was retained.")
        for key in ("openalex", "crossref"):
            if research_status[key]["status"] == "error":
                research_status[key]["status"] = "stale-fallback"
    if not countries and previous.get("countries"):
        countries = {item["iso3"]: item for item in previous["countries"] if item.get("iso3")}
        warnings.append("World Bank country context failed; the previous country snapshot was retained.")
        if wb_status["status"] == "error":
            wb_status["status"] = "stale-fallback"
    if not products and previous.get("trade_products"):
        products = previous["trade_products"]
        warnings.append("Trade product refresh failed; the previous trade product snapshot was retained.")
    if not flows and previous.get("trade_flows"):
        flows = previous["trade_flows"]
        warnings.append("Bilateral trade flow refresh failed or returned no rows; the previous flow snapshot was retained.")
    if gdelt_status["status"] == "error" and previous.get("news_signals"):
        news = previous["news_signals"]
        warnings.append("GDELT refresh failed; the previous news snapshot was retained.")
        gdelt_status["status"] = "stale-fallback"
    if not sources_ok and not previous:
        raise RuntimeError("All data providers failed and no previous snapshot exists; refusing to publish an empty snapshot.")

    # Add market names / capital coordinates for any reporting partners missing from the World Bank feed.
    all_trade_codes = set()
    for item in products:
        all_trade_codes.add(str(item.get("market_iso3") or "").upper())
    for item in flows:
        all_trade_codes.add(str(item.get("supplier_iso3") or "").upper())
        all_trade_codes.add(str(item.get("buyer_iso3") or "").upper())
    for iso in all_trade_codes:
        if not as_iso3(iso) or iso in countries:
            continue
        countries[iso] = {
            "iso3": iso, "iso2": "", "name": iso, "capital": "",
            "latitude": None, "longitude": None, "coordinate_type": "unknown",
            "region": "", "income_level": "", "indicators": {},
        }

    signal_source_count = len(signals)
    trade_mode = trade_status.get("mode") or "unknown"
    all_errors = [item for item in warnings if item]
    if trade_status.get("status") in {"error", "stale-fallback"} or research_status["openalex"]["status"] == "error" or research_status["crossref"]["status"] == "error":
        overall_status = "partial-refresh"
    elif trade_mode == "preview-limited":
        overall_status = "preview-limited-trade"
    else:
        overall_status = "fresh"

    payload = {
        "schema_version": "1.0.0",
        "meta": {
            "project": "S3 Smart Specialization Radar",
            "generated_at": generated,
            "lookback_start": since,
            "lookback_days": int(config.get("lookback_days", 730)),
            "refresh_cadence": "weekly",
            "status": overall_status,
            "limitations": [
                "Research records are bibliographic signals, not proof of regional demand or commercial impact.",
                "Trade values are reported import statistics, not retail sales, orders, revenue or profit.",
                "UN Comtrade preview mode is rate-limited and may return truncated coverage.",
                "World Bank coordinates are capital/reference points, not precise production or trade locations.",
                "Scores are exploratory triage aids and should not be read as investment recommendations.",
            ],
            "sources": [
                research_status["openalex"],
                research_status["crossref"],
                wb_status,
                trade_status,
                gdelt_status,
            ],
            "warnings": all_errors,
            "counts": {
                "signals": signal_source_count,
                "trade_products": len(products),
                "trade_flows": len(flows),
                "news_signals": len(news),
                "mapped_countries": sum(1 for item in countries.values() if item.get("latitude") is not None and item.get("longitude") is not None),
            },
        },
        "signals": signals,
        "trade_products": products,
        "trade_flows": flows,
        "news_signals": news,
        "countries": sorted(countries.values(), key=lambda item: item.get("name") or item.get("iso3") or ""),
    }
    atomic_write(payload)
    LOG.info(
        "Wrote radar snapshot: %d research signals, %d trade products, %d flows, %d news leads, %d countries; status=%s",
        len(signals), len(products), len(flows), len(news), len(countries), overall_status,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
