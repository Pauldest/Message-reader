# Storage Layer Design Document

## Module Overview

**Module Name**: Storage Layer
**Location**: `src/storage/`
**Purpose**: Persistent data storage layer providing SQLite database management, vector search, information unit storage, entity knowledge graph storage, and telemetry data storage.

**Key Features**:
- Dual architecture support (article-centric and information-centric)
- Vector similarity search (ChromaDB or SQLite fallback)
- Entity relationship management (knowledge graph)
- AI telemetry tracking (JSONL + SQLite hybrid)
- Thread-safe database access
- Automatic cleanup and retention policies

---

## File Structure

```
src/storage/
├── __init__.py                  # Package exports
├── database.py                   # Core SQLite database (318 lines)
├── vector_store.py              # Vector similarity search (405 lines)
├── information_store.py         # Information unit persistence (322 lines)
├── entity_store.py              # Entity knowledge graph storage (789 lines)
├── telemetry_store.py           # AI call telemetry storage (370 lines)
└── models.py                     # Storage data models
```

**Lines of Code**: ~2,200 lines
**Complexity**: Medium-High (handles 5 distinct storage systems)

---

## Class Diagrams

### Core Storage Classes

```
┌─────────────────┐         ┌──────────────────┐
│   Database      │◄────────│ InformationStore │
│                 │         │                  │
│ - db_path       │         │ - db: Database   │
│ - _get_conn()   │         │ - vector_store   │
└────────┬────────┘         └──────────────────┘
         │
         │ uses
         ▼
┌─────────────────┐         ┌──────────────────┐
│  VectorStore    │         │  EntityStore     │
│                 │         │                  │
│ - _backend      │         │ - db: Database   │
│ - _collection   │         │ - _ensure_tables │
└─────────────────┘         └──────────────────┘
```

### Telemetry Storage

```
┌──────────────────┐
│ TelemetryStore   │
│                  │
│ - storage_path   │
│ - db_path        │
│ - _local         │◄───── Thread-local connection
│ - append()       │
│ - query()        │
│ - get_stats()    │
└──────────────────┘
```

---

## Key Components

### 1. Database (database.py)

**Core SQLite database management with dual architecture support.**

#### Responsibilities:
- Article storage (legacy architecture)
- Information unit storage (new architecture)
- Source reference tracking
- Transaction management
- Automatic schema migration

#### Key Tables:

**Articles Table** (Legacy):
```sql
CREATE TABLE articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    summary TEXT,
    source TEXT,
    category TEXT,
    author TEXT,
    published_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    score REAL DEFAULT 0,
    ai_summary TEXT,
    is_top_pick BOOLEAN DEFAULT FALSE,
    reasoning TEXT,
    tags TEXT,  -- JSON
    analyzed_at TIMESTAMP,
    sent_at TIMESTAMP
)
```

**Information Units Table** (New):
```sql
CREATE TABLE information_units (
    id TEXT PRIMARY KEY,
    fingerprint TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    summary TEXT,
    analysis_content TEXT,
    key_insights TEXT,  -- JSON array
    analysis_depth_score REAL DEFAULT 0,
    who TEXT,  -- JSON array
    what TEXT,
    when_time TEXT,
    where_place TEXT,
    why TEXT,
    how TEXT,
    primary_source TEXT,
    extraction_confidence REAL,
    credibility_score REAL,
    importance_score REAL,
    sentiment TEXT,
    impact_assessment TEXT,
    related_unit_ids TEXT,  -- JSON array
    entities TEXT,  -- JSON array
    tags TEXT,  -- JSON array
    merged_count INTEGER DEFAULT 1,
    is_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

#### Connection Management:
```python
def _get_conn(self) -> sqlite3.Connection:
    """Thread-safe connection factory"""
    conn = sqlite3.connect(str(self.db_path))
    conn.row_factory = sqlite3.Row  # Enable dict-like access
    return conn
```

---

### 2. VectorStore (vector_store.py)

**Semantic similarity search with automatic backend selection.**

#### Architecture:
```
VectorStore (Unified Interface)
    ├── ChromaDB Backend (preferred)
    │   └── Uses sentence-transformers embeddings
    └── SQLite Backend (fallback)
        └── Custom TF-IDF + cosine similarity
```

#### Backend Selection Logic:
```python
try:
    import chromadb
    self._backend = "chromadb"
    # Use production-grade vector DB
except ImportError:
    self._backend = "sqlite"
    # Use custom implementation
```

#### SQLite Vector Store Features:
- **Hash trick embedding**: MD5-based feature hashing
- **N-gram extraction**: Character 2-gram and 3-gram features
- **L2 normalization**: Normalized 256-d vectors
- **Cosine similarity**: Efficient similarity computation

#### Embedding Algorithm (SQLite):
```python
def _compute_embedding(self, text: str, dim: int = 256) -> list[float]:
    # 1. Extract word-level features
    words = text.lower().split()
    features = words[:200]

    # 2. Extract character n-grams
    for i in range(len(text) - 1):
        features.append(text[i:i+2])  # 2-gram
    for i in range(len(text) - 2):
        features.append(text[i:i+3])  # 3-gram

    # 3. Hash to fixed dimension
    vector = [0.0] * dim
    for feature in features:
        hash_val = int(hashlib.md5(feature.encode()).hexdigest(), 16)
        idx = hash_val % dim
        sign = 1 if (hash_val // dim) % 2 == 0 else -1
        vector[idx] += sign * 1.0

    # 4. L2 normalization
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm > 0 else vector
```

---

### 3. InformationStore (information_store.py)

**Information-centric architecture storage layer.**

#### Core Operations:
```python
class InformationStore:
    async def save_unit(self, unit: InformationUnit)
    async def find_similar_units(self, unit, threshold=0.65) -> List[InformationUnit]
    def get_unsent_units(self, limit=100) -> List[InformationUnit]
    def mark_units_sent(self, unit_ids: List[str])
```

#### Semantic Deduplication:
```python
async def find_similar_units(self, unit: InformationUnit, threshold: float = 0.65):
    """Vector search + fingerprint matching"""
    query = f"{unit.title} {unit.summary} {' '.join(unit.key_insights[:3])}"
    results = await self.vector_store.search(query, top_k=3)

    similar_units = []
    for r in results:
        if r["id"] != unit.id and r.get("score", 0) >= threshold:
            existing_unit = self.get_unit(r["id"])
            if existing_unit:
                similar_units.append(existing_unit)

    return similar_units
```

---

### 4. EntityStore (entity_store.py)

**Knowledge graph storage for entity tracking.**

#### Entity Relationship Model:
```
┌─────────────┐        ┌────────────────┐        ┌─────────────┐
│   Entity    │───────>│ EntityMention  │<───────│ Information │
│             │        │                │        │    Unit     │
│ - id        │        │ - entity_id    │        │             │
│ - name      │        │ - unit_id      │        └─────────────┘
│ - type      │        │ - role         │
│ - l3_root   │        │ - sentiment    │
└──────┬──────┘        │ - state_delta  │
       │               └────────────────┘
       │
       │ has many
       ▼
┌──────────────┐
│ EntityAlias  │
│              │
│ - alias      │  (Primary Key)
│ - entity_id  │
│ - is_primary │
└──────────────┘
```

#### Three-Level Hierarchy:
- **L1 (Leaf)**: Specific entity (e.g., "DeepSeek", "NVIDIA")
- **L2 (Sector)**: Subcategory (e.g., "基础模型", "AI芯片")
- **L3 (Root)**: Top category (e.g., "人工智能", "半导体芯片")

#### Key Tables:

**Entities**:
```sql
CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    type TEXT,  -- COMPANY/PERSON/PRODUCT/ORG/CONCEPT/LOCATION/EVENT
    l3_root TEXT,
    l2_sector TEXT,
    attributes TEXT,  -- JSON
    mention_count INTEGER DEFAULT 0,
    first_mentioned TIMESTAMP,
    last_mentioned TIMESTAMP,
    created_at TIMESTAMP
)
```

**Entity Mentions**:
```sql
CREATE TABLE entity_mentions (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    unit_id TEXT NOT NULL,
    role TEXT,  -- 主角/配角/提及
    sentiment TEXT,  -- positive/neutral/negative
    state_dimension TEXT,  -- TECH/CAPITAL/REGULATION/ORG/RISK/SENTIMENT
    state_delta TEXT,  -- Change description
    event_time TIMESTAMP,
    created_at TIMESTAMP,
    FOREIGN KEY(entity_id) REFERENCES entities(id)
)
```

**Entity Relations**:
```sql
CREATE TABLE entity_relations (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT,  -- parent_of/competitor/partner/supplier...
    strength REAL,
    confidence REAL,
    evidence_unit_ids TEXT,  -- JSON array
    valid_from TIMESTAMP,
    valid_to TIMESTAMP,
    created_at TIMESTAMP,
    FOREIGN KEY(source_id) REFERENCES entities(id),
    FOREIGN KEY(target_id) REFERENCES entities(id)
)
```

#### Advanced Queries:

**Hot Entity Trend Analysis**:
```python
def get_hot_entities(self, days: int = 7, limit: int = 10) -> List[Dict]:
    """
    Returns:
        [{
            "entity": Entity,
            "recent_count": int,
            "previous_count": int,
            "trend": "up/down/stable/new",
            "change_pct": float
        }]
    """
    now = datetime.now()
    recent_start = now - timedelta(days=days)
    previous_start = now - timedelta(days=days * 2)

    # Get entities with most mentions in recent period
    # Compare with previous period to calculate trend
```

**Entity Timeline**:
```python
def get_entity_timeline(
    self,
    entity_id: str,
    start_date: datetime = None,
    end_date: datetime = None,
    state_dimensions: List[str] = None,
    limit: int = 50
) -> List[Dict]:
    """Get chronological mentions with context"""
```

---

### 5. TelemetryStore (telemetry_store.py)

**Hybrid storage for AI call tracking (JSONL + SQLite).**

#### Design Rationale:
- **JSONL files**: Complete message storage (daily sharded)
- **SQLite index**: Fast querying and aggregation
- **Thread-local connections**: Thread safety

#### Storage Structure:
```
data/telemetry/
├── telemetry.db           # SQLite index
├── 2026-01-15.jsonl      # Daily shard
├── 2026-01-16.jsonl
└── 2026-01-17.jsonl
```

#### Append Operation:
```python
def append(self, record: AICallRecord):
    # 1. Write to JSONL (daily shard)
    date_str = record.timestamp.strftime("%Y-%m-%d")
    jsonl_file = self.storage_path / f"{date_str}.jsonl"

    with open(jsonl_file, "a", encoding="utf-8") as f:
        f.write(record.to_json() + "\n")

    # 2. Write index to SQLite
    with self._conn:
        self._conn.execute("""
            INSERT OR REPLACE INTO ai_calls
            (call_id, timestamp, call_type, model, agent_name, ...)
            VALUES (?, ?, ?, ?, ?, ...)
        """, ...)
```

#### Query with Full Record Reconstruction:
```python
def get_full_record(self, call_id: str) -> Optional[AICallRecord]:
    # 1. Query index for file location
    cursor = self._conn.execute(
        "SELECT jsonl_file FROM ai_calls WHERE call_id = ?", (call_id,)
    )
    row = cursor.fetchone()

    # 2. Read from JSONL file
    with open(jsonl_file, "r") as f:
        for line in f:
            if call_id in line:
                return AICallRecord.from_json(line.strip())
```

---

## API/Interface Documentation

### Database Class

#### Core Methods

```python
class Database:
    def __init__(self, db_path: str = "data/articles.db")

    # Article Operations (Legacy)
    def article_exists(self, url: str) -> bool
    def save_article(self, article: Article) -> int
    def save_analyzed_article(self, article: AnalyzedArticle) -> int
    def get_unsent_articles(self, limit: int = 100) -> list[AnalyzedArticle]
    def mark_articles_sent(self, urls: list[str])
    def get_recent_sent_articles(self, days: int = 3, limit: int = 50) -> list[dict]

    # Maintenance
    def cleanup_old_articles(self, retention_days: int = 30)
    def get_stats(self) -> dict
```

**Example Usage**:
```python
db = Database("data/articles.db")

# Check if article exists
if not db.article_exists(article.url):
    db.save_article(article)

# Get unsent articles
articles = db.get_unsent_articles(limit=50)

# Mark as sent
db.mark_articles_sent([a.url for a in articles])
```

---

### VectorStore Class

```python
class VectorStore:
    def __init__(self, persist_dir: str = "data/vector_store")

    @property
    def is_available(self) -> bool

    async def add_article(
        self,
        article_id: str,
        title: str,
        content: str,
        metadata: Optional[dict] = None,
    )

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: Optional[dict] = None,
    ) -> list[dict]

    async def get_recent_articles(self, limit: int = 20) -> list[dict]
    def get_stats(self) -> dict
    async def clear()
```

**Example Usage**:
```python
vector_store = VectorStore()

# Add article
await vector_store.add_article(
    article_id="article_123",
    title="AI Breakthrough",
    content="Full text...",
    metadata={"source": "TechCrunch"}
)

# Semantic search
results = await vector_store.search(
    query="artificial intelligence progress",
    top_k=5
)

for r in results:
    print(f"{r['title']} (score: {r['score']:.2f})")
```

---

### InformationStore Class

```python
class InformationStore:
    def __init__(self, db: Database, vector_store: VectorStore = None)

    # Existence Checks
    def unit_exists(self, fingerprint: str) -> bool
    def get_unit_by_fingerprint(self, fingerprint: str) -> Optional[InformationUnit]
    def get_unit(self, unit_id: str) -> Optional[InformationUnit]

    # Save and Update
    async def save_unit(self, unit: InformationUnit)

    # Similarity Search
    async def find_similar_units(
        self,
        unit: InformationUnit,
        threshold: float = 0.65,
        top_k: int = 3
    ) -> List[InformationUnit]

    # Digest Generation
    def get_unsent_units(self, limit: int = 100) -> List[InformationUnit]
    def mark_units_sent(self, unit_ids: List[str])
```

**Example Usage**:
```python
info_store = InformationStore(db, vector_store)

# Save unit
unit = InformationUnit(...)
await info_store.save_unit(unit)

# Find duplicates
similar = await info_store.find_similar_units(unit, threshold=0.7)
if similar:
    print(f"Found {len(similar)} similar units")

# Get unsent for digest
unsent = info_store.get_unsent_units(limit=50)
```

---

### EntityStore Class

```python
class EntityStore:
    def __init__(self, db: Database)

    # Entity Management
    def register_entity(self, entity: Entity) -> Entity
    def get_entity(self, entity_id: str) -> Optional[Entity]
    def get_entity_by_name(self, name: str) -> Optional[Entity]
    def search_entities(self, query: str, limit: int = 10) -> List[Entity]

    # Alias Management
    def add_alias(self, alias: str, entity_id: str, is_primary: bool = False)
    def resolve_alias(self, alias: str) -> Optional[str]
    def get_aliases(self, entity_id: str) -> List[str]

    # Mention Tracking
    def record_mention(self, mention: EntityMention) -> EntityMention
    def get_mentions_by_entity(self, entity_id: str, limit: int = 100) -> List[EntityMention]
    def get_mentions_by_unit(self, unit_id: str) -> List[EntityMention]

    # Relationship Management
    def add_relation(self, relation: EntityRelation) -> EntityRelation
    def get_relations(self, entity_id: str, direction: str = "both") -> List[EntityRelation]

    # Advanced Queries
    def get_hot_entities(self, days: int = 7, limit: int = 10) -> List[Dict]
    def get_entity_timeline(...) -> List[Dict]
    def get_entity_network(self, entity_id: str, depth: int = 1) -> Dict
    def get_entity_daily_mentions(self, entity_ids: List[str] = None, days: int = 7) -> Dict[str, Dict[str, int]]

    # Batch Processing
    def process_extracted_entities(
        self,
        unit_id: str,
        entities: List[ExtractedEntity],
        relations: List[ExtractedRelation] = None,
        event_time: datetime = None
    )
```

**Example Usage**:
```python
entity_store = EntityStore(db)

# Register new entity
entity = Entity(canonical_name="DeepSeek", type=EntityType.COMPANY)
entity_store.register_entity(entity)
entity_store.add_alias("深度求索", entity.id)

# Find entity by alias
entity_id = entity_store.resolve_alias("deepseek")

# Track mention
mention = EntityMention(
    entity_id=entity_id,
    unit_id="unit_123",
    role="主角",
    state_dimension="TECH",
    state_delta="发布新模型"
)
entity_store.record_mention(mention)

# Get hot trends
hot = entity_store.get_hot_entities(days=7, limit=10)
for item in hot:
    print(f"{item['entity'].canonical_name}: {item['trend']} ({item['change_pct']}%)")
```

---

### TelemetryStore Class

```python
class TelemetryStore:
    def __init__(
        self,
        storage_path: str = "data/telemetry",
        retention_days: int = 30,
    )

    # Append
    def append(self, record: AICallRecord)

    # Query
    def query(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        session_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        call_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]

    def get_full_record(self, call_id: str) -> Optional[AICallRecord]

    # Statistics
    def get_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        session_id: Optional[str] = None,
    ) -> TelemetryStats

    # Maintenance
    def cleanup_old_records(self) -> int
    def export_jsonl(self, output_path: str, ...) -> int
    def list_sessions(self, limit: int = 20) -> list[dict]
```

**Example Usage**:
```python
store = TelemetryStore()

# Record a call
record = AICallRecord(
    call_type="chat",
    model="deepseek-chat",
    messages=[...],
    response="...",
    token_usage={"prompt": 100, "completion": 200},
    duration_ms=1500
)
store.append(record)

# Query recent calls
records = store.query(
    agent_name="CollectorAgent",
    limit=20
)

# Get statistics
stats = store.get_stats(start_time=datetime.now() - timedelta(days=7))
print(f"Total calls: {stats.total_calls}")
print(f"Total tokens: {stats.total_tokens}")
print(f"Error rate: {stats.error_rate:.1f}%")
```

---

## Data Flow

### Article-Centric Flow (Legacy)

```
┌──────────┐
│ Article  │
└────┬─────┘
     │
     ▼
┌────────────────┐
│   Database     │
│  save_article  │
└────┬───────────┘
     │
     ▼
┌─────────────────┐
│  VectorStore    │
│  add_article    │
└─────────────────┘
```

### Information-Centric Flow (New)

```
┌─────────────────┐
│ InformationUnit │
└────┬────────────┘
     │
     ▼
┌────────────────────┐
│ InformationStore   │
│  - save_unit       │◄────┐
│  - find_similar    │     │
└────┬───────────────┘     │
     │                     │
     ├──────────────────┐  │
     │                  │  │
     ▼                  ▼  │
┌──────────┐      ┌──────────────┐
│ Database │      │ VectorStore  │
│          │      │ (for search) │
└──────────┘      └──────────────┘
                        │
                        └─ Similarity feedback
```

### Entity Processing Flow

```
┌──────────────────┐
│ ExtractedEntity  │
└────┬─────────────┘
     │
     ▼
┌────────────────┐
│  EntityStore   │
│                │
│  1. Register   │───────────┐
│  2. Add Alias  │           │
│  3. Record     │           │
│     Mention    │           │
└────────────────┘           │
                             ▼
                     ┌───────────────┐
                     │   Database    │
                     │               │
                     │ - entities    │
                     │ - aliases     │
                     │ - mentions    │
                     │ - relations   │
                     └───────────────┘
```

### Telemetry Flow

```
┌───────────────┐
│ AI Call       │
└───┬───────────┘
    │
    ▼
┌──────────────────┐
│ TelemetryStore   │
│                  │
│  append()        │
└───┬──────────────┘
    │
    ├─────────────────────┬──────────────────┐
    │                     │                  │
    ▼                     ▼                  ▼
┌──────────┐      ┌────────────┐    ┌──────────────┐
│ JSONL    │      │ SQLite     │    │ WebSocket    │
│ (full)   │      │ (index)    │    │ (real-time)  │
└──────────┘      └────────────┘    └──────────────┘
```

---

## Design Patterns

### 1. **Repository Pattern**
Each store class acts as a repository for its domain objects:
- `Database`: Article repository
- `InformationStore`: Information unit repository
- `EntityStore`: Entity and relationship repository

### 2. **Factory Pattern**
Database connections use factory pattern:
```python
def _get_conn(self) -> sqlite3.Connection:
    """Connection factory"""
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    return conn
```

### 3. **Strategy Pattern**
VectorStore backend selection:
```python
if chromadb_available:
    backend = ChromaDBStrategy()
else:
    backend = SQLiteStrategy()
```

### 4. **Singleton Pattern** (Thread-Local Variant)
TelemetryStore uses thread-local connections:
```python
@property
def _conn(self) -> sqlite3.Connection:
    if not hasattr(self._local, "conn"):
        self._local.conn = sqlite3.connect(...)
    return self._local.conn
```

### 5. **Bridge Pattern**
InformationStore bridges database and vector store:
```python
class InformationStore:
    def __init__(self, db: Database, vector_store: VectorStore):
        self.db = db
        self.vector_store = vector_store
```

---

## Dependencies

### Internal Dependencies
```python
from .models import Article, AnalyzedArticle, DailyDigest
from ..models.information import InformationUnit, SourceReference
from ..models.entity import Entity, EntityMention, EntityRelation
from ..models.telemetry import AICallRecord, TelemetryStats
```

### External Dependencies
- **sqlite3**: Standard library (database)
- **chromadb**: Optional (vector search)
- **structlog**: Logging
- **pydantic**: Data validation
- **hashlib**: Hash functions
- **pathlib**: Path handling
- **threading**: Thread-local storage

---

## Error Handling

### Strategy: Graceful Degradation

#### Database Errors
```python
def save_article(self, article: Article) -> int:
    try:
        with self._get_conn() as conn:
            cursor = conn.execute(...)
            conn.commit()
            return cursor.lastrowid
    except sqlite3.IntegrityError as e:
        # Article already exists
        logger.warning("article_duplicate", url=article.url)
        return -1
    except Exception as e:
        logger.error("save_article_failed", error=str(e))
        raise
```

#### VectorStore Fallback
```python
try:
    import chromadb
    self._backend = "chromadb"
except Exception as e:
    logger.warning("chromadb_unavailable", error=str(e))
    self._backend = "sqlite"
```

#### Telemetry Non-Blocking
```python
def append(self, record: AICallRecord):
    try:
        # Write to storage
        ...
    except Exception as e:
        logger.error("telemetry_write_failed", error=str(e))
        # Don't raise - telemetry failures should not break main flow
```

---

## Performance Considerations

### 1. **Connection Pooling**
- Each store maintains its own connection strategy
- Database uses context manager for automatic cleanup
- TelemetryStore uses thread-local connections

### 2. **Indexing Strategy**
```sql
-- Article lookup
CREATE INDEX idx_articles_url ON articles(url);
CREATE INDEX idx_articles_fetched_at ON articles(fetched_at);
CREATE INDEX idx_articles_sent_at ON articles(sent_at);

-- Information units
CREATE INDEX idx_info_fingerprint ON information_units(fingerprint);
CREATE INDEX idx_info_created ON information_units(created_at);
CREATE INDEX idx_info_score ON information_units(importance_score);

-- Entity mentions
CREATE INDEX idx_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX idx_mentions_unit ON entity_mentions(unit_id);

-- Entity relations
CREATE INDEX idx_relations_source ON entity_relations(source_id);
CREATE INDEX idx_relations_target ON entity_relations(target_id);
```

### 3. **Batch Operations**
```python
# Batch insert for performance
def mark_units_sent(self, unit_ids: List[str]):
    placeholders = ",".join(["?"] * len(unit_ids))
    conn.execute(
        f"UPDATE information_units SET is_sent = 1 WHERE id IN ({placeholders})",
        unit_ids
    )
```

### 4. **Query Optimization**
```python
# Use LIMIT to prevent loading large datasets
def get_unsent_units(self, limit: int = 100):
    cursor = conn.execute("""
        SELECT * FROM information_units
        WHERE is_sent = 0
        ORDER BY COALESCE(when_time, created_at) DESC
        LIMIT ?
    """, (limit,))
```

### 5. **Vector Search Optimization**
- ChromaDB: Production-grade optimizations
- SQLite: Limit search space to recent 100 articles

---

## Testing Strategy

### Unit Tests
```python
# Test database operations
def test_article_exists():
    db = Database(":memory:")
    article = Article(url="https://test.com", title="Test")
    db.save_article(article)
    assert db.article_exists(article.url)

# Test vector similarity
async def test_vector_search():
    store = VectorStore(persist_dir="/tmp/test_vector")
    await store.add_article("1", "AI News", "Content about AI")
    results = await store.search("artificial intelligence", top_k=5)
    assert len(results) > 0
```

### Integration Tests
```python
# Test information store with vector store
async def test_info_store_deduplication():
    db = Database(":memory:")
    vector_store = VectorStore(persist_dir="/tmp/test")
    info_store = InformationStore(db, vector_store)

    unit1 = InformationUnit(title="AI Breakthrough", ...)
    await info_store.save_unit(unit1)

    unit2 = InformationUnit(title="AI Breakthrough News", ...)
    similar = await info_store.find_similar_units(unit2, threshold=0.7)

    assert len(similar) > 0
    assert similar[0].id == unit1.id
```

### Performance Tests
```python
# Test batch operations
def test_batch_insert_performance():
    db = Database(":memory:")
    articles = [Article(...) for _ in range(1000)]

    start = time.time()
    for article in articles:
        db.save_article(article)
    duration = time.time() - start

    assert duration < 5.0  # Should complete in < 5 seconds
```

---

## Extension Points

### 1. **Custom Vector Backend**
```python
class CustomVectorStore(VectorStore):
    def __init__(self, backend_config):
        self._backend = "custom"
        self._client = CustomVectorDB(backend_config)

    async def search(self, query: str, top_k: int = 5):
        # Custom implementation
        pass
```

### 2. **Database Schema Migration**
```python
def _migrate_schema_v2(self):
    """Add new columns for enhanced features"""
    with self._get_conn() as conn:
        conn.execute("ALTER TABLE articles ADD COLUMN new_field TEXT")
```

### 3. **Custom Entity Types**
```python
# Extend EntityType enum
class ExtendedEntityType(EntityType):
    INSTITUTION = "INSTITUTION"
    TECHNOLOGY = "TECHNOLOGY"
```

### 4. **Telemetry Backends**
```python
class CloudTelemetryStore(TelemetryStore):
    def append(self, record):
        # Send to cloud service
        await self.cloud_client.send(record)
```

---

## Best Practices

### 1. **Always Use Context Managers**
```python
with self._get_conn() as conn:
    # Automatic commit on success, rollback on error
    conn.execute(...)
```

### 2. **JSON Field Handling**
```python
# Always handle JSON parsing errors
def _parse_json_field(self, value: str, default=None):
    if not value:
        return default or []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        logger.warning("json_parse_error", field=value[:50])
        return default or []
```

### 3. **Thread Safety**
```python
# Use thread-local storage for connections
self._local = threading.local()

@property
def _conn(self):
    if not hasattr(self._local, "conn"):
        self._local.conn = self._create_connection()
    return self._local.conn
```

### 4. **Graceful Cleanup**
```python
def cleanup_old_articles(self, retention_days: int = 30):
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    with self._get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM articles WHERE fetched_at < ?",
            (cutoff_date,)
        )
        logger.info("cleanup_complete", deleted_count=cursor.rowcount)
```

---

## Summary

The Storage Layer is a well-architected data persistence system that supports both legacy and modern architectures. Key strengths:

1. **Dual Architecture Support**: Seamlessly supports both article-centric and information-centric processing
2. **Vector Search Flexibility**: Automatic fallback from ChromaDB to SQLite
3. **Knowledge Graph Integration**: Comprehensive entity tracking and relationship management
4. **Telemetry Excellence**: Hybrid JSONL + SQLite design for both completeness and performance
5. **Thread Safety**: Proper handling of concurrent access
6. **Graceful Degradation**: Non-critical failures don't break the system

The layer serves as the foundation for the entire Message-reader system, providing reliable, efficient, and flexible data storage.
