"""Local news discovery for the Electoral Sentiment Tracker.

Collects article metadata from Google News RSS search feeds and the City of
Boroondara newsroom. It does not scrape or store full article text and does not
infer voter preferences. All discovered items enter an unreviewed queue.
"""
from __future__ import annotations

import csv
import hashlib
import html
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CANDIDATES_PATH = DATA_DIR / "kew_2026_candidates.csv"
ARTICLES_PATH = DATA_DIR / "news_articles.csv"
LOG_PATH = DATA_DIR / "news_collection_log.csv"

BOROONDARA_NEWS_URL = (
    "https://www.boroondara.vic.gov.au/your-council/news-and-media/boroondara-news"
)
BIG_BUILD_WORK_NOTICES_URL = (
    "https://bigbuild.vic.gov.au/library/north-east-link/work-notices"
)

# Google News is used as a discovery index, not treated as the original publisher.
# Each query is intentionally separate so feed coverage can be inspected.
GOOGLE_NEWS_QUERIES = [
    ("Kew and Boroondara", '"Kew" Boroondara Victoria Melbourne'),
    ("Kew East and Eastern Freeway", '"Kew East" "Eastern Freeway"'),
    ("Kew development and housing", '"Kew" (housing OR development OR planning) Victoria'),
    ("Kew local services", '"Kew" (school OR health OR transport OR recreation) Melbourne'),
    ("Boroondara local news", 'Boroondara (Kew OR Balwyn OR Camberwell OR Hawthorn)'),
    ("Eastsider News", 'site:eastsidernews.org.au (Kew OR Boroondara)'),
    ("Big Build Kew", 'site:bigbuild.vic.gov.au (Kew OR "Kew East")'),
    ("Boroondara Council news", 'site:boroondara.vic.gov.au Kew'),
]

FIELDS = [
    "article_id", "title", "publisher", "published_at", "source_url",
    "source_type", "collection_method", "feed_name", "feed_query", "summary",
    "geography_match", "geography_review", "issue_suggested", "issue_reviewed",
    "article_tone", "public_sentiment_evidence", "sentiment_target",
    "candidate_mentions_suggested", "candidate_mentions_reviewed",
    "candidate_evidence_type", "candidate_public_view_summary",
    "review_notes", "review_status", "first_seen_at", "last_seen_at",
]

ISSUES = [
    ("Planning and housing", ["housing", "development", "planning", "apartment", "residential", "rezoning", "vicroads", "denmark street"]),
    ("Transport and roads", ["transport", "bus", "train", "tram", "traffic", "parking", "road", "cycle", "cycling", "pedestrian", "freeway", "intersection"]),
    ("Construction and disruption", ["construction", "works notice", "works update", "noise", "dust", "north east link", "eastern freeway", "works"]),
    ("Environment and open space", ["tree", "trees", "greenway", "park", "reserve", "environment", "canopy", "waste", "recycling", "creek"]),
    ("Education", ["school", "education", "teacher", "student", "kindergarten", "early learning"]),
    ("Health and community services", ["health", "hospital", "medical", "aged care", "community service", "wellbeing"]),
    ("Sport and recreation", ["recreation", "sport", "pool", "aquatic", "fitness", "playground"]),
    ("Council and local services", ["council", "rates", "rubbish", "waste collection", "library", "local government"]),
    ("Crime and public safety", ["crime", "police", "safety", "crime", "emergency", "collision", "crash"]),
    ("Politics and election", ["election", "candidate", "campaign", "member for", "mp ", "parliament", "party"]),
]

LOCAL_SUBURBS = [
    "kew east", "north balwyn", "balwyn north", "balwyn", "deepdene",
    "camberwell", "canterbury", "hawthorn east", "hawthorn", "surrey hills",
    "ashburton", "glen iris",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value: str, limit: int = 650) -> str:
    if not value:
        return ""
    text = BeautifulSoup(html.unescape(value), "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return ""


def _issue_suggestion(text: str) -> str:
    lowered = text.casefold()
    for issue, terms in ISSUES:
        if any(term in lowered for term in terms):
            return issue
    return "Other / unclassified"


def _geography_match(text: str, publisher: str, source_url: str) -> str:
    lowered = text.casefold()
    domain = urlparse(source_url).netloc.casefold()
    local_publisher = any(
        host in domain
        for host in ("boroondara.vic.gov.au", "eastsidernews.org.au", "bigbuild.vic.gov.au")
    )
    if "kew east" in lowered or "north balwyn" in lowered:
        return "Kew-area context"
    if re.search(r"\bkew\b", lowered) and (
        local_publisher
        or any(term in lowered for term in ("victoria", "melbourne", "boroondara"))
    ):
        return "Kew mention — verify"
    if "boroondara" in lowered or "boroondara.vic.gov.au" in domain:
        return "Boroondara-wide context"
    if any(suburb in lowered for suburb in LOCAL_SUBURBS):
        return "Nearby suburb — verify"
    return "Uncertain — review location"


def _candidate_names() -> list[str]:
    if not CANDIDATES_PATH.exists():
        return []
    try:
        with CANDIDATES_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
            return [
                row.get("candidate_name", "").strip()
                for row in csv.DictReader(handle)
                if row.get("candidate_name", "").strip()
            ]
    except (OSError, csv.Error):
        return []


def _candidate_mentions(text: str) -> list[str]:
    lowered = text.casefold()
    return [name for name in _candidate_names() if name.casefold() in lowered]


def _candidate_searches() -> list[tuple[str, str]]:
    return [
        (f"Candidate search — {name}", f'"{name}" (Kew OR Boroondara OR Victoria)')
        for name in _candidate_names()
    ]


def _article_id(title: str, publisher: str, published_at: str, source_url: str) -> str:
    basis = "|".join([
        re.sub(r"\W+", " ", title.casefold()).strip(),
        publisher.casefold(),
        published_at[:10],
        source_url.split("?")[0],
    ])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


def _make_record(
    title: str,
    publisher: str,
    published_at: str,
    source_url: str,
    summary: str,
    source_type: str,
    collection_method: str,
    feed_name: str = "",
    feed_query: str = "",
) -> dict:
    title = _clean_text(title, 250)
    publisher = _clean_text(publisher, 120) or urlparse(source_url).netloc
    summary = _clean_text(summary, 650)
    combined = f"{title} {summary} {publisher} {source_url}"
    now = _now()
    return {
        "article_id": _article_id(title, publisher, published_at, source_url),
        "title": title,
        "publisher": publisher,
        "published_at": published_at,
        "source_url": source_url,
        "source_type": source_type,
        "collection_method": collection_method,
        "feed_name": feed_name,
        "feed_query": feed_query,
        "summary": summary,
        "geography_match": _geography_match(combined, publisher, source_url),
        "geography_review": "Unreviewed",
        "issue_suggested": _issue_suggestion(combined),
        "issue_reviewed": "",
        "article_tone": "Not assessed",
        "public_sentiment_evidence": "Not assessed",
        "sentiment_target": "",
        "candidate_mentions_suggested": " | ".join(_candidate_mentions(combined)),
        "candidate_mentions_reviewed": "",
        "candidate_evidence_type": "Not assessed",
        "candidate_public_view_summary": "",
        "review_notes": "",
        "review_status": "Needs review",
        "first_seen_at": now,
        "last_seen_at": now,
    }


def _fetch_google_news(query: str, feed_name: str, days: int, session: requests.Session):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    full_query = f"{query} after:{cutoff}"
    url = "https://news.google.com/rss/search?" + urlencode({
        "q": full_query,
        "hl": "en-AU",
        "gl": "AU",
        "ceid": "AU:en",
    })
    response = session.get(url, timeout=(8, 20))
    response.raise_for_status()

    root = ET.fromstring(response.content)
    items = []
    for item in root.findall(".//item")[:30]:
        title = item.findtext("title", default="")
        link = item.findtext("link", default="")
        published = _parse_date(item.findtext("pubDate", default=""))
        description = item.findtext("description", default="")
        source_node = item.find("source")
        publisher = source_node.text.strip() if source_node is not None and source_node.text else ""
        summary = _clean_text(description)
        if not title or not link:
            continue
        items.append(_make_record(
            title=title,
            publisher=publisher,
            published_at=published,
            source_url=link,
            summary=summary,
            source_type="News article discovery",
            collection_method="Google News RSS",
            feed_name=feed_name,
            feed_query=full_query,
        ))
    return items


def _fetch_boroondara_news(session: requests.Session):
    response = session.get(BOROONDARA_NEWS_URL, timeout=(8, 20))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    items = []
    seen = set()
    prefix = "/your-council/news-and-media/boroondara-news/"

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        absolute_url = urljoin(BOROONDARA_NEWS_URL, href)
        path = urlparse(absolute_url).path
        title = anchor.get_text(" ", strip=True)
        if prefix not in path or not title or len(title) < 8 or absolute_url in seen:
            continue
        seen.add(absolute_url)

        parent = anchor.find_parent(["article", "li"])
        if parent is None:
            parent = anchor.parent
        context = parent.get_text(" ", strip=True) if parent else title
        date_match = re.search(
            r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b", context
        )
        published = ""
        if date_match:
            try:
                published = datetime.strptime(
                    date_match.group(1), "%d %B %Y"
                ).replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
            except ValueError:
                try:
                    published = datetime.strptime(
                        date_match.group(1), "%d %b %Y"
                    ).replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
                except ValueError:
                    published = ""

        items.append(_make_record(
            title=title,
            publisher="City of Boroondara",
            published_at=published,
            source_url=absolute_url,
            summary=context,
            source_type="Local government news",
            collection_method="Boroondara newsroom index",
            feed_name="City of Boroondara newsroom",
            feed_query="Direct newsroom listing",
        ))
    return items


def _fetch_big_build_notices(session: requests.Session):
    """Collect directly linked Kew/Kew East work notices from the Big Build index."""
    response = session.get(BIG_BUILD_WORK_NOTICES_URL, timeout=(8, 20))
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    items = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        absolute_url = urljoin(BIG_BUILD_WORK_NOTICES_URL, href)
        path = urlparse(absolute_url).path.casefold()
        title = anchor.get_text(" ", strip=True)
        if (
            "/work-notices/" not in path
            or path.rstrip("/") == urlparse(BIG_BUILD_WORK_NOTICES_URL).path.rstrip("/")
            or "kew" not in (path + " " + title.casefold())
            or absolute_url in seen
            or len(title) < 8
        ):
            continue
        seen.add(absolute_url)
        parent = anchor.find_parent(["article", "li"])
        if parent is None:
            parent = anchor.parent
        context = parent.get_text(" ", strip=True) if parent else title
        date_match = re.search(
            r"\\b(\\d{1,2}\\s+[A-Za-z]{3,9}\\s+\\d{4})\\b", context
        )
        published = ""
        if date_match:
            for date_format in ("%d %B %Y", "%d %b %Y"):
                try:
                    published = datetime.strptime(
                        date_match.group(1), date_format
                    ).replace(tzinfo=timezone.utc).isoformat(timespec="seconds")
                    break
                except ValueError:
                    continue
        items.append(_make_record(
            title=title,
            publisher="Victoria's Big Build",
            published_at=published,
            source_url=absolute_url,
            summary=context,
            source_type="Official infrastructure notice",
            collection_method="Big Build work notices index",
            feed_name="Victoria's Big Build work notices",
            feed_query="Direct index links matching Kew or Kew East",
        ))
    return items


def _read_existing(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        existing = {}
        for row in reader:
            if row.get("article_id"):
                # Keep reviewer decisions already made in the app.
                existing[row["article_id"]] = {field: row.get(field, "") for field in FIELDS}
        return existing


def _write_csv_atomic(path: Path, records: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="", dir=path.parent, delete=False
    ) as temp:
        writer = csv.DictWriter(temp, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)
        temp_path = Path(temp.name)
    temp_path.replace(path)


def collect_news(output_path: str | Path = ARTICLES_PATH, days: int = 120) -> dict:
    """Fetch the configured news feeds and merge new metadata into the local CSV."""
    output_path = Path(output_path)
    existing = _read_existing(output_path)
    now = _now()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "ElectoralSentimentResearch/0.1 (public RSS metadata collector)"
    })

    discovered = []
    errors = []
    successes = 0
    queries = GOOGLE_NEWS_QUERIES + _candidate_searches()
    for feed_name, query in queries:
        try:
            results = _fetch_google_news(query, feed_name, days, session)
            discovered.extend(results)
            successes += 1
        except (requests.RequestException, ET.ParseError, ValueError) as exc:
            errors.append(f"{feed_name}: {type(exc).__name__}: {exc}")

    try:
        council_items = _fetch_boroondara_news(session)
        discovered.extend(council_items)
        successes += 1
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"City of Boroondara newsroom: {type(exc).__name__}: {exc}")

    try:
        big_build_items = _fetch_big_build_notices(session)
        discovered.extend(big_build_items)
        successes += 1
    except (requests.RequestException, ValueError) as exc:
        errors.append(f"Victoria's Big Build work notices: {type(exc).__name__}: {exc}")

    def natural_key(record):
        return (
            re.sub(r"\W+", " ", record.get("title", "").casefold()).strip(),
            record.get("publisher", "").casefold().strip(),
            (record.get("published_at", "") or "")[:10],
        )

    # Avoid duplicate rows when an item is found by both a publisher page and RSS.
    existing_natural = {natural_key(record): article_id for article_id, record in existing.items()}
    new_count = 0
    for record in discovered:
        article_id = record["article_id"]
        natural = natural_key(record)
        if article_id not in existing and natural in existing_natural:
            article_id = existing_natural[natural]
            record["article_id"] = article_id

        if article_id in existing:
            old = existing[article_id]
            old["last_seen_at"] = now
            # Refresh discovery metadata, but preserve direct publisher URLs and all review fields.
            for field in ("title", "publisher", "published_at", "source_type",
                          "collection_method", "feed_name", "feed_query", "summary",
                          "geography_match", "issue_suggested"):
                old[field] = record[field]
            old_domain = urlparse(old.get("source_url", "")).netloc.casefold()
            new_domain = urlparse(record.get("source_url", "")).netloc.casefold()
            if new_domain and (not new_domain.endswith("google.com")):
                old["source_url"] = record["source_url"]
        else:
            existing[article_id] = record
            existing_natural[natural] = article_id
            new_count += 1

    records = sorted(
        existing.values(),
        key=lambda row: row.get("published_at") or row.get("first_seen_at") or "",
        reverse=True,
    )
    _write_csv_atomic(output_path, records, FIELDS)

    log_exists = LOG_PATH.exists()
    with LOG_PATH.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["collected_at", "feeds_attempted", "feeds_succeeded",
                                "items_discovered", "new_items", "errors"]
        )
        if not log_exists:
            writer.writeheader()
        writer.writerow({
            "collected_at": now,
            "feeds_attempted": len(queries) + 2,
            "feeds_succeeded": successes,
            "items_discovered": len(discovered),
            "new_items": new_count,
            "errors": " | ".join(errors),
        })

    return {
        "feeds_attempted": len(queries) + 2,
        "feeds_succeeded": successes,
        "items_discovered": len(discovered),
        "new_items": new_count,
        "total_items": len(records),
        "errors": errors,
    }
