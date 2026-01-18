# Fetcher Module Design Document

## Module Overview

**Module Name**: Fetcher (RSS and Content Extraction)
**Location**: `src/fetcher/`
**Purpose**: Fetch RSS feeds concurrently and extract full article content from web pages.

**Key Features**:
- Concurrent RSS feed fetching with configurable limits
- Support for RSS and Atom formats
- Full-text content extraction using trafilatura
- Automatic retry and error handling
- Timezone-aware datetime handling
- Configurable timeouts and semaphore-based concurrency control

---

## File Structure

```
src/fetcher/
├── __init__.py                   # Package exports
├── rss_parser.py                 # RSS/Atom parser (173 lines)
└── content_extractor.py          # Full-text extractor (102 lines)
```

**Lines of Code**: 275 lines
**Complexity**: Medium (handles network I/O and parsing)

---

## Class Diagrams

### Fetcher Architecture

```
┌───────────────────────┐
│    RSSParser          │
│                       │
│  - timeout            │
│  - max_concurrent     │
│  - _semaphore         │
│                       │
│  + fetch_all()        │──┐
│  - _fetch_feed()      │  │
│  - _parse_feed()      │  │
│  - _entry_to_article()│  │
└───────────────────────┘  │
                           │
            ┌──────────────┘
            │
            │ produces
            ▼
      ┌──────────┐
      │ Article  │
      │          │
      │ - url    │
      │ - title  │
      │ - summary│
      └──────────┘
            │
            │ enriched by
            ▼
┌───────────────────────┐
│  ContentExtractor     │
│                       │
│  - timeout            │
│  - max_concurrent     │
│  - _semaphore         │
│  - _executor          │ (ThreadPool)
│                       │
│  + extract_all()      │
│  - _extract_article() │
│  - _extract_text()    │ (trafilatura)
└───────────────────────┘
```

### Concurrent Processing Flow

```
fetch_all(feeds)
    │
    ├─► Semaphore(max_concurrent=10)
    │
    ├───► Task 1: _fetch_feed(feed1) ──┐
    ├───► Task 2: _fetch_feed(feed2)   │
    ├───► Task 3: _fetch_feed(feed3)   │ Parallel
    ├───► ...                          │ execution
    └───► Task N: _fetch_feed(feedN) ──┘
              │
              └─► gather(*tasks) ──► [Article, Article, ...]
```

---

## Key Components

### 1. RSSParser (rss_parser.py)

**Concurrent RSS feed fetcher with intelligent parsing.**

#### Initialization

```python
class RSSParser:
    """
    RSS/Atom feed parser with concurrent fetching.

    Features:
    - Parallel feed fetching with semaphore control
    - Support for RSS 2.0 and Atom formats
    - Automatic timezone normalization to UTC
    - 6-month article filtering
    - Duplicate URL detection
    """

    def __init__(self, timeout: int = 30, max_concurrent: int = 10):
        """
        Initialize parser.

        Args:
            timeout: HTTP request timeout in seconds
            max_concurrent: Maximum concurrent feed fetches
        """
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
```

#### Main Fetch Method

```python
async def fetch_all(self, feeds: list[FeedSource]) -> list[Article]:
    """
    Fetch all enabled feeds concurrently.

    Args:
        feeds: List of FeedSource configurations

    Returns:
        Deduplicated list of Article objects

    Example:
        >>> parser = RSSParser(timeout=30, max_concurrent=10)
        >>> articles = await parser.fetch_all(config.feeds)
        >>> print(f"Fetched {len(articles)} unique articles")
    """
    enabled_feeds = [f for f in feeds if f.enabled]

    logger.info("fetching_feeds", count=len(enabled_feeds))

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=self.timeout)
    ) as session:
        tasks = [
            self._fetch_feed(session, feed)
            for feed in enabled_feeds
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect articles and handle errors
    articles = []
    for feed, result in zip(enabled_feeds, results):
        if isinstance(result, Exception):
            logger.error("feed_fetch_failed",
                       feed=feed.name,
                       error=str(result))
        else:
            articles.extend(result)
            logger.info("feed_fetched",
                      feed=feed.name,
                      count=len(result))

    # Deduplicate by URL
    unique_articles = list({a.url: a for a in articles}.values())

    logger.info("fetch_complete",
               total=len(unique_articles),
               sources=len(enabled_feeds))

    return unique_articles
```

#### Individual Feed Fetching

```python
async def _fetch_feed(
    self,
    session: aiohttp.ClientSession,
    feed: FeedSource
) -> list[Article]:
    """
    Fetch and parse a single RSS feed.

    Uses semaphore to limit concurrent requests.

    Args:
        session: aiohttp client session
        feed: Feed configuration

    Returns:
        List of Article objects from this feed
    """
    async with self._semaphore:
        try:
            async with session.get(feed.url) as response:
                if response.status != 200:
                    logger.warning("feed_http_error",
                                  feed=feed.name,
                                  status=response.status)
                    return []

                content = await response.text()
                return self._parse_feed(content, feed)

        except asyncio.TimeoutError:
            logger.warning("feed_timeout", feed=feed.name)
            return []
        except Exception as e:
            logger.error("feed_error", feed=feed.name, error=str(e))
            return []
```

#### Feed Parsing

```python
def _parse_feed(self, content: str, feed: FeedSource) -> list[Article]:
    """
    Parse RSS/Atom XML content.

    Uses feedparser library which handles both RSS and Atom.

    Args:
        content: Raw XML content
        feed: Feed metadata

    Returns:
        List of parsed articles (max 6 months old)
    """
    from datetime import timedelta

    parsed = feedparser.parse(content)
    articles = []

    # Only keep articles from last 6 months
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=180)

    for entry in parsed.entries:
        try:
            article = self._entry_to_article(entry, feed)
            if article:
                # Filter old articles
                if article.published_at and article.published_at < cutoff_date:
                    continue
                articles.append(article)
        except Exception as e:
            logger.warning("entry_parse_error",
                         feed=feed.name,
                         error=str(e))

    return articles
```

#### Entry to Article Conversion

```python
def _entry_to_article(self, entry, feed: FeedSource) -> Optional[Article]:
    """
    Convert RSS entry to Article object.

    Handles various RSS/Atom field variations and normalizes datetimes.

    Args:
        entry: feedparser entry dict
        feed: Feed metadata

    Returns:
        Article object or None if required fields missing
    """
    # Extract URL (required)
    url = entry.get("link", "")
    if not url:
        return None

    # Extract title (required)
    title = entry.get("title", "").strip()
    if not title:
        return None

    # Extract summary/description
    summary = ""
    if hasattr(entry, "summary"):
        summary = entry.summary
    elif hasattr(entry, "description"):
        summary = entry.description

    # Extract full content (if available)
    content = ""
    if hasattr(entry, "content"):
        content = entry.content[0].get("value", "")

    # Extract and normalize published date
    published_at = None
    for date_field in ["published", "updated", "created"]:
        if hasattr(entry, date_field):
            try:
                date_str = getattr(entry, date_field)
                dt = date_parser.parse(date_str)

                # Normalize to UTC
                if dt.tzinfo is None:
                    # Assume UTC if naive
                    dt = dt.replace(tzinfo=timezone.utc)
                else:
                    dt = dt.astimezone(timezone.utc)

                published_at = dt
                break
            except:
                pass

    # Extract author
    author = ""
    if hasattr(entry, "author"):
        author = entry.author
    elif hasattr(entry, "author_detail"):
        author = entry.author_detail.get("name", "")

    return Article(
        url=url,
        title=title,
        content=content or summary,
        summary=summary,
        source=feed.name,
        category=feed.category,
        author=author,
        published_at=published_at,
        fetched_at=datetime.now(timezone.utc),
    )
```

---

### 2. ContentExtractor (content_extractor.py)

**Full-text content extraction using trafilatura.**

#### Initialization

```python
class ContentExtractor:
    """
    Article content extractor using trafilatura.

    Features:
    - Parallel content extraction with semaphore
    - ThreadPool for CPU-bound trafilatura calls
    - Automatic fallback to original summary on failure
    - Skip extraction for articles with sufficient content
    """

    def __init__(self, timeout: int = 15, max_concurrent: int = 5):
        """
        Initialize extractor.

        Args:
            timeout: HTTP request timeout
            max_concurrent: Maximum concurrent extractions
        """
        self.timeout = timeout
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
```

#### Batch Extraction

```python
async def extract_all(self, articles: list[Article]) -> list[Article]:
    """
    Extract full content for a batch of articles.

    Args:
        articles: List of Article objects

    Returns:
        Same articles with enriched content

    Example:
        >>> extractor = ContentExtractor(timeout=15, max_concurrent=5)
        >>> enriched = await extractor.extract_all(articles)
    """
    logger.info("extracting_content", count=len(articles))

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=self.timeout)
    ) as session:
        tasks = [
            self._extract_article(session, article)
            for article in articles
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    extracted = []
    for article, result in zip(articles, results):
        if isinstance(result, Exception):
            logger.warning("extraction_failed",
                         url=article.url,
                         error=str(result))
            # Use original article on failure
            extracted.append(article)
        else:
            extracted.append(result)

    logger.info("extraction_complete", count=len(extracted))
    return extracted
```

#### Single Article Extraction

```python
async def _extract_article(
    self,
    session: aiohttp.ClientSession,
    article: Article
) -> Article:
    """
    Extract content for a single article.

    Skips extraction if article already has >500 chars.

    Args:
        session: aiohttp session
        article: Article to extract

    Returns:
        Article with extracted content
    """
    async with self._semaphore:
        # Skip if already has good content
        if len(article.content) > 500:
            return article

        try:
            # Fetch HTML
            async with session.get(article.url) as response:
                if response.status != 200:
                    return article

                html = await response.text()

                # Extract text in thread pool (trafilatura is CPU-bound)
                loop = asyncio.get_event_loop()
                content = await loop.run_in_executor(
                    self._executor,
                    self._extract_text,
                    html
                )

                if content:
                    article.content = content

                return article

        except asyncio.TimeoutError:
            logger.debug("extraction_timeout", url=article.url)
            return article
        except Exception as e:
            logger.debug("extraction_error", url=article.url, error=str(e))
            return article
```

#### Trafilatura Extraction

```python
def _extract_text(self, html: str) -> Optional[str]:
    """
    Extract clean text from HTML using trafilatura.

    trafilatura automatically:
    - Removes navigation, ads, footers
    - Preserves main content structure
    - Handles various website layouts

    Args:
        html: Raw HTML content

    Returns:
        Extracted text or None if extraction fails
    """
    try:
        text = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,  # Use fallback methods if needed
        )
        return text
    except Exception:
        return None
```

#### Cleanup

```python
def close(self):
    """Shutdown thread pool executor"""
    self._executor.shutdown(wait=False)
```

---

## API Documentation

### RSSParser

```python
class RSSParser:
    def __init__(self, timeout: int = 30, max_concurrent: int = 10)

    async def fetch_all(self, feeds: list[FeedSource]) -> list[Article]
```

**Usage**:
```python
from src.fetcher import RSSParser
from src.config import get_config

config = get_config()
parser = RSSParser(timeout=30, max_concurrent=10)

# Fetch all configured feeds
articles = await parser.fetch_all(config.feeds)

print(f"Fetched {len(articles)} articles from {len(config.feeds)} sources")
```

---

### ContentExtractor

```python
class ContentExtractor:
    def __init__(self, timeout: int = 15, max_concurrent: int = 5)

    async def extract_all(self, articles: list[Article]) -> list[Article]

    def close()
```

**Usage**:
```python
from src.fetcher import ContentExtractor

extractor = ContentExtractor(timeout=15, max_concurrent=5)

# Extract full content
enriched_articles = await extractor.extract_all(articles)

# Cleanup when done
extractor.close()
```

---

## Data Flow

### Complete Fetch Pipeline

```
Config.feeds[]
     │
     ▼
RSSParser.fetch_all()
     │
     ├─► HTTP GET feed1.xml ──┐
     ├─► HTTP GET feed2.xml   │ Concurrent
     └─► HTTP GET feedN.xml ──┘
              │
              ├─► feedparser.parse()
              │
              └─► [Article(summary only), ...]
                        │
                        ▼
              ContentExtractor.extract_all()
                        │
                        ├─► HTTP GET article1 ──┐
                        ├─► HTTP GET article2   │ Concurrent
                        └─► HTTP GET articleN ──┘
                                  │
                                  ├─► trafilatura.extract()
                                  │   (in ThreadPool)
                                  │
                                  └─► [Article(full content), ...]
```

### Error Handling Flow

```
fetch_feed()
    │
    ├─► Success ──► [Articles]
    │
    ├─► HTTP Error ──► Log + Return []
    │
    ├─► Timeout ──► Log + Return []
    │
    └─► Exception ──► Log + Return []
                            │
                            └─► gather() collects all results
                                  │
                                  └─► Filter out empty lists
```

---

## Design Patterns

### 1. Semaphore Pattern (Concurrency Control)

```python
self._semaphore = asyncio.Semaphore(max_concurrent)

async def _fetch_feed(self, ...):
    async with self._semaphore:
        # Only max_concurrent tasks run simultaneously
        ...
```

### 2. Executor Pattern (CPU-Bound Tasks)

```python
self._executor = ThreadPoolExecutor(max_workers=5)

loop = asyncio.get_event_loop()
result = await loop.run_in_executor(
    self._executor,
    cpu_bound_function,
    args
)
```

### 3. Facade Pattern

RSSParser provides simple interface hiding complexity:
```python
articles = await parser.fetch_all(feeds)
# Hides: HTTP, parsing, error handling, concurrency
```

---

## Performance Considerations

### 1. Concurrent Limits

```python
# Too high: May overwhelm servers or hit rate limits
max_concurrent=50  # Bad

# Too low: Slow fetching
max_concurrent=1  # Bad

# Balanced
max_concurrent=10  # Good for RSS
max_concurrent=5   # Good for content extraction
```

### 2. Timeout Configuration

```python
# RSS feeds: Usually fast
timeout=30  # Sufficient

# Content extraction: May be slow for large pages
timeout=15  # Balance between speed and success rate
```

### 3. ThreadPool for CPU-Bound

```python
# trafilatura parsing is CPU-intensive
# Running in thread pool prevents blocking event loop
await loop.run_in_executor(self._executor, trafilatura.extract, html)
```

### 4. Content Length Check

```python
# Skip extraction if already have good content
if len(article.content) > 500:
    return article  # Skip HTTP request
```

---

## Error Handling

### Graceful Degradation

```python
# RSS fetch failure: Skip feed, continue with others
if isinstance(result, Exception):
    logger.error("feed_fetch_failed", ...)
    # Don't raise - other feeds can still succeed

# Content extraction failure: Use summary
except Exception as e:
    logger.debug("extraction_error", ...)
    return article  # Original article with summary
```

### Timeout Handling

```python
async with aiohttp.ClientSession(
    timeout=aiohttp.ClientTimeout(total=self.timeout)
) as session:
    # Automatic timeout after self.timeout seconds
```

---

## Testing Strategy

### Unit Tests

```python
def test_entry_to_article():
    feed = FeedSource(name="Test", url="...", category="Tech")

    entry = {
        "link": "https://test.com",
        "title": "Test Article",
        "summary": "Summary",
        "published": "2026-01-15T10:00:00Z"
    }

    parser = RSSParser()
    article = parser._entry_to_article(entry, feed)

    assert article.url == "https://test.com"
    assert article.title == "Test Article"
    assert article.source == "Test"

async def test_content_extraction():
    extractor = ContentExtractor()

    html = "<html><body><p>Main content here</p></body></html>"
    content = extractor._extract_text(html)

    assert "Main content" in content
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_full_fetch_pipeline():
    config = get_config()

    # Limit to 1 feed for testing
    test_feeds = [config.feeds[0]]

    parser = RSSParser()
    articles = await parser.fetch_all(test_feeds)

    assert len(articles) > 0

    extractor = ContentExtractor()
    enriched = await extractor.extract_all(articles[:5])

    assert all(len(a.content) > len(a.summary) for a in enriched)

    extractor.close()
```

---

## Extension Points

### 1. Custom Parsers

```python
class CustomRSSParser(RSSParser):
    def _entry_to_article(self, entry, feed):
        article = super()._entry_to_article(entry, feed)

        # Add custom field extraction
        if hasattr(entry, 'custom_field'):
            article.custom_data = entry.custom_field

        return article
```

### 2. Alternative Extractors

```python
class ReadabilityExtractor(ContentExtractor):
    def _extract_text(self, html: str) -> str:
        # Use readability instead of trafilatura
        from readability import Document
        doc = Document(html)
        return doc.summary()
```

### 3. Caching

```python
class CachedContentExtractor(ContentExtractor):
    def __init__(self, *args, cache_dir="cache", **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_dir = Path(cache_dir)

    async def _extract_article(self, session, article):
        # Check cache first
        cache_key = hashlib.md5(article.url.encode()).hexdigest()
        cache_file = self.cache_dir / cache_key

        if cache_file.exists():
            article.content = cache_file.read_text()
            return article

        # Extract and cache
        article = await super()._extract_article(session, article)
        cache_file.write_text(article.content)
        return article
```

---

## Best Practices

### 1. Always Set Timeouts

```python
# Good
async with aiohttp.ClientSession(timeout=ClientTimeout(total=30)):
    ...

# Bad - no timeout, may hang forever
async with aiohttp.ClientSession():
    ...
```

### 2. Use Semaphores for Rate Limiting

```python
# Good - prevents overwhelming servers
async with self._semaphore:
    await fetch()

# Bad - all requests fire at once
await fetch()  # No rate limiting
```

### 3. Clean Up Resources

```python
# Good
try:
    extractor = ContentExtractor()
    await extractor.extract_all(articles)
finally:
    extractor.close()

# Or use context manager if available
```

### 4. Log but Don't Crash

```python
# Good
try:
    article = self._parse_entry(entry)
    articles.append(article)
except Exception as e:
    logger.warning("parse_error", error=str(e))
    # Continue processing other entries

# Bad
article = self._parse_entry(entry)  # May crash entire batch
```

---

## Summary

The Fetcher module provides robust, production-ready RSS fetching and content extraction:

**Key Strengths**:
1. **Concurrent Processing**: Efficient parallel fetching with semaphore control
2. **Error Resilience**: Graceful handling of failures without crashing
3. **Format Support**: Handles both RSS and Atom feeds
4. **Content Extraction**: Uses battle-tested trafilatura library
5. **Resource Management**: Proper cleanup and thread pool handling
6. **Performance**: Smart skipping, timeouts, and concurrency limits

The module is the entry point for all article data, ensuring reliable and efficient data collection from diverse RSS sources.
