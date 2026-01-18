# Core Modules Design Document

## Module Overview

**Module Name**: Core System Components
**Location**: `src/` (root-level modules)
**Purpose**: Provide foundational infrastructure including configuration management, RSS feed management, task scheduling, and main service orchestration.

**Core Files**:
- `config.py` - Configuration management
- `feeds.py` - RSS feed manager
- `scheduler.py` - Task scheduling
- `main.py` - Main service entry point

**Key Features**:
- Type-safe configuration with Pydantic
- Environment variable expansion
- YAML-based feed management
- Cron-style task scheduling
- Service lifecycle management
- Graceful shutdown handling

---

## File Structure

```
src/
├── config.py                     # Configuration management (200+ lines)
├── feeds.py                      # RSS feed manager (150+ lines)
├── scheduler.py                  # Task scheduler (120+ lines)
└── main.py                       # Main service (800+ lines)
```

**Lines of Code**: ~1,270 lines (core infrastructure)
**Complexity**: Medium-High (orchestrates entire system)

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     RSSReaderService                          │
│                        (main.py)                              │
│                                                               │
│  ┌────────────┐  ┌────────────┐  ┌─────────────────┐       │
│  │ Config     │  │ FeedManager│  │  Scheduler      │       │
│  │ (config)   │  │ (feeds)    │  │  (scheduler)    │       │
│  └──────┬─────┘  └──────┬─────┘  └────────┬────────┘       │
│         │                │                  │                 │
│         └────────────────┴──────────────────┘                 │
│                          │                                    │
│         ┌────────────────┴──────────────────┐                │
│         │                                    │                │
│    ┌────▼────┐  ┌──────────┐  ┌────────────▼─────┐         │
│    │Database │  │Fetcher   │  │Orchestrator       │         │
│    │         │  │          │  │(Multi-Agent)      │         │
│    └─────────┘  └──────────┘  └───────────────────┘         │
│         │                                    │                 │
│    ┌────▼────┐  ┌──────────┐  ┌────────────▼─────┐         │
│    │InfoStore│  │EntityStore│  │EmailSender       │         │
│    └─────────┘  └───────────┘  └──────────────────┘         │
└──────────────────────────────────────────────────────────────┘
           │
           ▼
    ┌──────────────┐
    │  Lifecycle   │
    │  Management  │
    │              │
    │ - start()    │
    │ - run_once() │
    │ - stop()     │
    └──────────────┘
```

---

## 1. Configuration Module (config.py)

### Purpose
Centralized configuration management with type safety, environment variable expansion, and YAML loading.

### Class Hierarchy

```
┌───────────────────┐
│   BaseModel       │  (Pydantic)
└─────────┬─────────┘
          │
          ├──► AIConfig
          ├──► EmailConfig
          ├──► ScheduleConfig
          ├──► FilterConfig
          ├──► LoggingConfig
          ├──► StorageConfig
          ├──► TelemetryConfig
          ├──► FeedSource
          └──► AppConfig  (contains all above)
```

### Configuration Models

#### AIConfig
```python
class AIConfig(BaseModel):
    """AI service configuration"""
    provider: str = "deepseek"
    api_key: str = ""
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com/v1"
    max_tokens: int = 4096
    temperature: float = 0.3
```

#### EmailConfig
```python
class EmailConfig(BaseModel):
    """Email configuration"""
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    use_ssl: bool = True
    username: str = ""
    password: str = ""
    from_addr: str = ""
    from_name: str = "AI 阅读助手"
    to_addrs: list[str] = Field(default_factory=list)
```

#### ScheduleConfig
```python
class ScheduleConfig(BaseModel):
    """Schedule configuration"""
    fetch_interval: str = "2h"
    digest_times: list[str] = Field(default_factory=lambda: ["09:00", "21:00"])
    timezone: str = "Asia/Shanghai"
```

#### FilterConfig
```python
class FilterConfig(BaseModel):
    """Filter configuration"""
    top_pick_count: int = 5
    min_score: float = 5.0
    max_articles_per_digest: int = 100
```

#### StorageConfig
```python
class StorageConfig(BaseModel):
    """Storage configuration"""
    database_path: str = "data/articles.db"
    article_retention_days: int = 30
```

#### TelemetryConfig
```python
class TelemetryConfig(BaseModel):
    """Telemetry configuration"""
    enabled: bool = True
    storage_path: str = "data/telemetry"
    retention_days: int = 30
    max_content_length: int = 10000
```

#### AppConfig (Root)
```python
class AppConfig(BaseModel):
    """Application configuration"""
    ai: AIConfig = Field(default_factory=AIConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    filter: FilterConfig = Field(default_factory=FilterConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    feeds: list[FeedSource] = Field(default_factory=list)
```

### Key Functions

#### Environment Variable Expansion
```python
def _expand_env_vars(value):
    """Recursively expand environment variables"""
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        return value
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value
```

**Usage**:
```yaml
ai:
  api_key: ${DEEPSEEK_API_KEY}  # Expands to value of DEEPSEEK_API_KEY env var
```

#### Configuration Loading
```python
def get_config(reload: bool = False) -> AppConfig:
    """Get global configuration (singleton pattern)"""
    global _config

    if _config is None or reload:
        config_path = Path(__file__).parent.parent / "config" / "config.yaml"

        if not config_path.exists():
            logger.warning("config_not_found", path=str(config_path))
            _config = AppConfig()
        else:
            with open(config_path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}

            # Expand environment variables
            expanded_data = _expand_env_vars(raw_data)

            # Load feeds from separate file
            feeds_path = config_path.parent / "feeds.yaml"
            if feeds_path.exists():
                with open(feeds_path, "r", encoding="utf-8") as f:
                    feeds_data = yaml.safe_load(f) or {}
                expanded_data["feeds"] = feeds_data.get("feeds", [])

            _config = AppConfig(**expanded_data)

        logger.info("config_loaded", has_api_key=bool(_config.ai.api_key))

    return _config
```

**Features**:
- Singleton pattern (cached after first load)
- Environment variable expansion
- Separate feeds file loading
- Graceful fallback to defaults

---

## 2. Feed Manager (feeds.py)

### Purpose
Manage RSS feed subscriptions with CRUD operations and YAML persistence.

### FeedManager Class

```python
class FeedManager:
    """RSS feed manager"""

    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self.config_dir = Path(config_dir)
        self.feeds_path = self.config_dir / "feeds.yaml"

        # Auto-copy from example if missing
        if not self.feeds_path.exists():
            example_path = self.config_dir / "feeds.example.yaml"
            if example_path.exists():
                import shutil
                shutil.copy(example_path, self.feeds_path)
```

### Key Methods

#### list_feeds()
```python
def list_feeds(self) -> list[FeedSource]:
    """List all RSS feeds"""
    feeds_data = self._load_feeds()
    return [FeedSource(**f) for f in feeds_data]
```

#### add_feed()
```python
def add_feed(self, name: str, url: str, category: str = "未分类") -> bool:
    """Add a new RSS feed"""
    feeds = self._load_feeds()

    # Check for duplicates
    for feed in feeds:
        if feed.get("url") == url:
            print(f"❌ Feed already exists: {feed.get('name')}")
            return False

    # Add new feed
    feeds.append({
        "name": name,
        "url": url,
        "category": category,
        "enabled": True,
    })

    self._save_feeds(feeds)
    print(f"✅ Added feed: {name}")
    return True
```

#### remove_feed()
```python
def remove_feed(self, identifier: str) -> bool:
    """Remove feed by name or URL"""
    feeds = self._load_feeds()
    original_count = len(feeds)

    # Match by name or URL
    feeds = [
        f for f in feeds
        if f.get("name") != identifier and f.get("url") != identifier
    ]

    if len(feeds) == original_count:
        print(f"❌ Feed not found: {identifier}")
        return False

    self._save_feeds(feeds)
    print(f"✅ Removed feed: {identifier}")
    return True
```

#### enable_feed() / disable_feed()
```python
def enable_feed(self, identifier: str) -> bool:
    """Enable a feed"""
    return self._toggle_feed(identifier, enabled=True)

def disable_feed(self, identifier: str) -> bool:
    """Disable a feed"""
    return self._toggle_feed(identifier, enabled=False)

def _toggle_feed(self, identifier: str, enabled: bool) -> bool:
    """Toggle feed enabled status"""
    feeds = self._load_feeds()
    modified = False

    for feed in feeds:
        if feed.get("name") == identifier or feed.get("url") == identifier:
            feed["enabled"] = enabled
            modified = True
            break

    if not modified:
        print(f"❌ Feed not found: {identifier}")
        return False

    self._save_feeds(feeds)
    status = "enabled" if enabled else "disabled"
    print(f"✅ Feed {status}: {identifier}")
    return True
```

#### validate_feed()
```python
async def validate_feed(self, url: str) -> bool:
    """Validate if RSS feed URL is accessible and parseable"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.error("feed_validation_failed", url=url, status=resp.status)
                    return False

                content = await resp.text()
                feed = feedparser.parse(content)

                if feed.bozo:  # Parsing error
                    logger.error("feed_parse_failed", url=url, error=feed.bozo_exception)
                    return False

                logger.info("feed_validated", url=url, entries=len(feed.entries))
                return True

    except Exception as e:
        logger.error("feed_validation_error", url=url, error=str(e))
        return False
```

---

## 3. Scheduler (scheduler.py)

### Purpose
Manage periodic tasks using APScheduler with cron-style and interval triggers.

### Scheduler Class

```python
class Scheduler:
    """Task scheduler"""

    def __init__(self, config: ScheduleConfig):
        self.config = config
        self.scheduler = AsyncIOScheduler(timezone=config.timezone)
        self._fetch_job_id = "rss_fetch"
        self._digest_job_prefix = "daily_digest"
```

### Key Methods

#### add_fetch_job()
```python
def add_fetch_job(self, func: Callable[[], Awaitable[None]]):
    """Add RSS fetch task with interval trigger"""
    interval = self._parse_interval(self.config.fetch_interval)

    self.scheduler.add_job(
        func,
        IntervalTrigger(**interval),
        id=self._fetch_job_id,
        name="RSS Fetch Task",
        replace_existing=True,
    )

    logger.info("fetch_job_added", interval=self.config.fetch_interval)
```

**Example**: `fetch_interval: "2h"` → Runs every 2 hours

#### add_digest_job()
```python
def add_digest_job(self, func: Callable[[], Awaitable[None]]):
    """Add daily digest task (supports multiple times)"""
    digest_times = self.config.digest_times

    for i, time_str in enumerate(digest_times):
        hour, minute = self._parse_time(time_str)
        job_id = f"{self._digest_job_prefix}_{i}"

        # Determine edition (morning/afternoon/evening)
        edition = "早报" if hour < 12 else ("午报" if hour < 18 else "晚报")

        self.scheduler.add_job(
            func,
            CronTrigger(hour=hour, minute=minute),
            id=job_id,
            name=f"Daily Digest - {edition}",
            replace_existing=True,
        )

        logger.info("digest_job_added", time=time_str, edition=edition)
```

**Example**: `digest_times: ["09:00", "21:00"]` → Morning @ 9am, Evening @ 9pm

#### Utility Parsers

**Interval Parser**:
```python
def _parse_interval(self, interval_str: str) -> dict:
    """
    Parse interval string like '2h', '30m', '1d'

    Returns: {"hours": 2} or {"minutes": 30} or {"days": 1}
    """
    match = re.match(r'^(\d+)([smhd])$', interval_str.lower())
    if not match:
        raise ValueError(f"Invalid interval format: {interval_str}")

    value = int(match.group(1))
    unit = match.group(2)

    unit_map = {
        's': 'seconds',
        'm': 'minutes',
        'h': 'hours',
        'd': 'days',
    }

    return {unit_map[unit]: value}
```

**Time Parser**:
```python
def _parse_time(self, time_str: str) -> tuple[int, int]:
    """
    Parse time string like '07:00'

    Returns: (hour, minute)
    """
    parts = time_str.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format: {time_str}")

    hour = int(parts[0])
    minute = int(parts[1])

    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"Invalid time value: {time_str}")

    return hour, minute
```

---

## 4. Main Service (main.py)

### Purpose
Central service orchestrator managing the entire application lifecycle.

### RSSReaderService Class

```python
class RSSReaderService:
    """RSS Reader Service (Multi-Agent Version)"""

    def __init__(
        self,
        config: AppConfig,
        analysis_mode: str = "deep",
        concurrency: int = 5,
        progress_tracker=None
    ):
        self.config = config
        self.concurrency = concurrency
        self.progress_tracker = progress_tracker

        # Parse analysis mode
        self.analysis_mode = AnalysisMode(analysis_mode)

        # Initialize components
        self.db = Database(config.storage.database_path)
        self.rss_parser = RSSParser()
        self.content_extractor = ContentExtractor()

        # Multi-agent orchestrator
        self.orchestrator = AnalysisOrchestrator(config, progress_tracker=progress_tracker)

        self.email_sender = EmailSender(config.email)
        self.scheduler = Scheduler(config.schedule)

        # Initialize telemetry service
        AITelemetry.initialize(
            enabled=config.telemetry.enabled,
            storage_path=config.telemetry.storage_path,
            retention_days=config.telemetry.retention_days,
            max_content_length=config.telemetry.max_content_length,
        )

        # Running state
        self._running = False

        # Initialize information store with vector store
        self.info_store = InformationStore(self.db, vector_store=self.orchestrator.vector_store)
        self.orchestrator.set_information_store(self.info_store)

        # Initialize entity store (knowledge graph)
        from .storage.entity_store import EntityStore
        self.entity_store = EntityStore(self.db)
        self.orchestrator.set_entity_store(self.entity_store)

        logger.info("service_initialized", analysis_mode=self.analysis_mode.value)
```

### Key Methods

#### fetch_and_analyze()
```python
async def fetch_and_analyze(self, limit: int = None):
    """
    Fetch and analyze articles

    Args:
        limit: Limit number of articles to analyze (for testing)
    """
    logger.info("starting_fetch_cycle", mode=self.analysis_mode.value, limit=limit)

    if self.progress_tracker:
        await self.progress_tracker.start_operation("开始抓取和分析...")

    try:
        # 1. Fetch RSS feeds
        if self.progress_tracker:
            await self.progress_tracker.set_phase(
                phase=ProgressPhase.FETCHING_RSS,
                message="正在从订阅源获取文章列表..."
            )

        articles = await self.rss_parser.fetch_all(self.config.feeds)

        if not articles:
            logger.info("no_new_articles")
            return

        # 2. Filter existing articles
        new_articles = [a for a in articles if not self.db.article_exists(a.url)]

        if not new_articles:
            logger.info("all_articles_exist", total=len(articles))
            return

        logger.info("new_articles_found", count=len(new_articles))

        # 3. Apply limit (for testing)
        if limit and limit > 0:
            new_articles = new_articles[:limit]

        # 4. Extract content
        if self.progress_tracker:
            await self.progress_tracker.set_phase(
                phase=ProgressPhase.EXTRACTING_CONTENT,
                message="正在提取文章正文..."
            )

        articles_with_content = await self.content_extractor.extract_all(new_articles)

        # 5. Analyze articles (multi-agent)
        if self.progress_tracker:
            await self.progress_tracker.set_phase(
                phase=ProgressPhase.ANALYZING,
                message="正在分析文章..."
            )

        # Information-centric processing
        all_units = []
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process_one(article):
            async with semaphore:
                units = await self.orchestrator.process_article_information_centric(article)
                return units

        tasks = [process_one(article) for article in articles_with_content]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_units.extend(result)

        logger.info("analysis_complete", total_units=len(all_units))

        if self.progress_tracker:
            await self.progress_tracker.finish()

    except Exception as e:
        logger.error("fetch_and_analyze_failed", error=str(e))
        if self.progress_tracker:
            await self.progress_tracker.finish(error=str(e))
        raise
```

#### send_digest()
```python
async def send_digest(self, dry_run: bool = False):
    """
    Generate and send daily digest email

    Args:
        dry_run: If True, generate digest but don't send email
    """
    logger.info("generating_digest", dry_run=dry_run)

    if self.progress_tracker:
        await self.progress_tracker.set_phase(
            phase=ProgressPhase.SENDING_DIGEST,
            message="正在生成每日简报..."
        )

    # 1. Fetch information units
    units = self.info_store.get_recent_units(days=1, limit=100)

    if not units:
        logger.info("no_units_for_digest")
        return

    # 2. Curate top picks
    from .agents.info_curator import InformationCuratorAgent
    from .services.llm import LLMService

    llm = LLMService(self.config.ai)
    curator = InformationCuratorAgent(llm)

    digest_content = await curator.curate_digest(units, max_picks=10)

    # 3. Send email
    if not dry_run:
        await self.email_sender.send_digest(digest_content)
        logger.info("digest_sent")
    else:
        logger.info("digest_dry_run", content_length=len(str(digest_content)))

    if self.progress_tracker:
        await self.progress_tracker.finish()
```

#### Lifecycle Methods

**run_once()**:
```python
async def run_once(self, limit: int = None, dry_run: bool = False):
    """Run one complete cycle (fetch + analyze + optionally send)"""
    await self.fetch_and_analyze(limit=limit)

    if not dry_run:
        await self.send_digest()
```

**start()**:
```python
def start(self):
    """Start scheduled service"""
    self.scheduler.add_fetch_job(self.fetch_and_analyze)
    self.scheduler.add_digest_job(self.send_digest)
    self.scheduler.start()

    logger.info("service_started")

    self._running = True

    # Block until stopped
    try:
        while self._running:
            asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("keyboard_interrupt")
        self.stop()
```

**stop()**:
```python
def stop(self):
    """Stop service gracefully"""
    logger.info("stopping_service")
    self._running = False
    self.scheduler.stop()
    logger.info("service_stopped")
```

---

## Data Flow: Complete Cycle

```
┌─────────────────────────────────────────────────────────────┐
│                   RSSReaderService.run_once()                │
└───────────────────────────┬─────────────────────────────────┘
                            │
            ┌───────────────┴────────────────┐
            │                                │
            ▼                                ▼
    ┌──────────────┐               ┌──────────────┐
    │ Fetch RSS    │               │ Send Digest  │
    │ Feeds        │               │              │
    └──────┬───────┘               └───────▲──────┘
           │                               │
           ▼                               │
    ┌──────────────┐                      │
    │ Filter New   │                      │
    │ Articles     │                      │
    └──────┬───────┘                      │
           │                               │
           ▼                               │
    ┌──────────────┐                      │
    │ Extract      │                      │
    │ Content      │                      │
    └──────┬───────┘                      │
           │                               │
           ▼                               │
    ┌──────────────┐                      │
    │ Multi-Agent  │                      │
    │ Analysis     │                      │
    └──────┬───────┘                      │
           │                               │
           ▼                               │
    ┌──────────────┐                      │
    │ Information  │                      │
    │ Unit         │──────────────────────┘
    │ Extraction   │   (stored for digest)
    └──────────────┘
```

---

## CLI Interface

### Entry Point (main.py)
```python
def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(description="RSS AI Reader with Multi-Agent Analysis")

    parser.add_argument("--once", action="store_true", help="Run once then exit")
    parser.add_argument("--limit", type=int, help="Limit number of articles (for testing)")
    parser.add_argument("--dry-run", action="store_true", help="Don't send emails")
    parser.add_argument("--mode", choices=["quick", "standard", "deep"], default="deep")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent analysis tasks")

    args = parser.parse_args()

    # Load config
    config = get_config()

    # Initialize service
    service = RSSReaderService(
        config,
        analysis_mode=args.mode,
        concurrency=args.concurrency
    )

    # Run
    if args.once:
        asyncio.run(service.run_once(limit=args.limit, dry_run=args.dry_run))
    else:
        service.start()
```

**Usage Examples**:
```bash
# Run scheduled service
python -m src.main

# Run once for testing
python -m src.main --once --limit 10 --dry-run

# Quick mode with higher concurrency
python -m src.main --once --mode quick --concurrency 10
```

---

## Design Patterns Used

### 1. Singleton Pattern
- **get_config()**: Cached configuration instance

### 2. Façade Pattern
- **RSSReaderService**: Simplifies complex subsystem interactions

### 3. Strategy Pattern
- **AnalysisMode**: Different analysis strategies (QUICK, STANDARD, DEEP)

### 4. Observer Pattern
- **ProgressTracker**: Observes service operations, broadcasts updates

### 5. Dependency Injection
- **All components**: Injected via constructor parameters

---

## Error Handling

### Graceful Degradation
```python
try:
    await self.fetch_and_analyze()
except Exception as e:
    logger.error("fetch_failed", error=str(e))
    # Don't crash, continue to next cycle
```

### Signal Handling
```python
import signal

def signal_handler(sig, frame):
    logger.info("received_signal", signal=sig)
    service.stop()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
```

---

## Testing Strategy

### Unit Tests
```python
def test_config_loading():
    config = get_config(reload=True)
    assert config.ai.model == "deepseek-chat"

def test_feed_manager():
    manager = FeedManager()
    assert manager.add_feed("Test", "https://example.com/feed", "Tech")
    feeds = manager.list_feeds()
    assert len(feeds) > 0

def test_scheduler_interval_parsing():
    scheduler = Scheduler(ScheduleConfig())
    assert scheduler._parse_interval("2h") == {"hours": 2}
    assert scheduler._parse_interval("30m") == {"minutes": 30}
```

### Integration Tests
```python
@pytest.mark.asyncio
async def test_full_pipeline():
    config = get_config()
    service = RSSReaderService(config)

    await service.run_once(limit=5, dry_run=True)
    # Verify articles analyzed
```

---

## Configuration Examples

### config.yaml
```yaml
ai:
  provider: deepseek
  api_key: ${DEEPSEEK_API_KEY}
  model: deepseek-chat
  base_url: https://api.deepseek.com/v1
  max_tokens: 8000
  temperature: 0.3

email:
  smtp_host: smtp.qq.com
  smtp_port: 465
  use_ssl: true
  username: ${EMAIL_USERNAME}
  password: ${EMAIL_PASSWORD}
  from_addr: ${EMAIL_FROM}
  from_name: "AI Reading Assistant"
  to_addrs:
    - user@example.com

schedule:
  fetch_interval: "2h"
  digest_times: ["09:00", "21:00"]
  timezone: "Asia/Shanghai"

filter:
  top_pick_count: 5
  min_score: 5.0
  max_articles_per_digest: 100

storage:
  database_path: "data/articles.db"
  article_retention_days: 30

telemetry:
  enabled: true
  storage_path: "data/telemetry"
  retention_days: 30
```

### feeds.yaml
```yaml
feeds:
  - name: TechCrunch
    url: https://techcrunch.com/feed/
    category: Tech
    enabled: true

  - name: Hacker News
    url: https://news.ycombinator.com/rss
    category: Tech
    enabled: true
```

---

## Summary

The Core modules provide **foundational infrastructure** for the Message-reader system:

**Strengths**:
- ✅ Type-safe configuration with Pydantic
- ✅ Environment variable expansion
- ✅ Flexible RSS feed management
- ✅ Robust task scheduling
- ✅ Graceful lifecycle management
- ✅ Signal handling
- ✅ Progress tracking integration

**Key Features**:
- 🎯 Centralized configuration
- 🎯 YAML-based feed management
- 🎯 Cron-style scheduling
- 🎯 Multi-mode analysis support
- 🎯 Async/await throughout
- 🎯 CLI interface

**Best Practices**:
- Singleton pattern for config
- Dependency injection
- Graceful error handling
- Comprehensive logging
- Testable design

These core modules form the **backbone** of the entire system, orchestrating all other components into a cohesive, production-ready application.
