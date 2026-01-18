# Data Models Design Document

## Module Overview

**Module Name**: Data Models
**Location**: `src/models/`
**Purpose**: Define all data structures used throughout the Message-reader system using Pydantic for validation and serialization.

**Key Features**:
- Type-safe data models with runtime validation
- Support for dual architecture (article-centric and information-centric)
- Rich domain models with business logic
- Automatic JSON serialization/deserialization
- Immutable data structures where appropriate
- Comprehensive entity relationship modeling

---

## File Structure

```
src/models/
├── __init__.py                   # Package exports
├── article.py                    # Article models (161 lines)
├── information.py                # Information unit models (174 lines)
├── entity.py                     # Entity models (114 lines)
├── agent.py                      # Agent workflow models (97 lines)
├── analysis.py                   # Analysis result models
└── telemetry.py                  # Telemetry models
```

**Lines of Code**: ~700 lines
**Complexity**: Medium (primarily data definitions with some business logic)

---

## Class Diagrams

### Article Models Hierarchy

```
┌────────────────────┐
│     Article        │  (Base model - minimal)
│                    │
│  - url             │
│  - title           │
│  - content         │
│  - source          │
│  - published_at    │
└──────────┬─────────┘
           │
           │ extends
           ▼
┌────────────────────┐
│  EnrichedArticle   │  (AI-analyzed - comprehensive)
│                    │
│  === Base Fields ===
│  + url, title...   │
│                    │
│  === Analysis ===  │
│  + who, what, when │
│  + entities        │
│  + timeline        │
│  + source_credibility│
│  + bias_analysis   │
│  + impact_analysis │
│  + recommendations │
│  + agent_traces    │
└────────────────────┘
```

### Information Models

```
┌─────────────────────┐
│  InformationUnit    │  (Atomic information)
│                     │
│  - id, fingerprint  │
│  - type: InformationType
│  - title, content   │
│  - summary          │
│                     │
│  === 5W1H ===      │
│  - who[]           │
│  - what, when      │
│  - where, why, how │
│                     │
│  === Sources ===   │
│  - sources[]       │◄──┐
│  - primary_source  │   │
│                     │   │
│  === Scores ===    │   │
│  - importance      │   │
│  - credibility     │   │
│  - value_score     │   │
└─────────────────────┘   │
                          │
            ┌─────────────┘
            │
┌───────────▼─────────┐
│  SourceReference    │
│                     │
│  - url              │
│  - title            │
│  - source_name      │
│  - published_at     │
│  - excerpt          │
│  - credibility_tier │
└─────────────────────┘
```

### Entity Models

```
┌─────────────────┐
│     Entity      │  (Knowledge graph node)
│                 │
│  - id           │
│  - canonical_name
│  - type: EntityType
│  - l3_root      │  (Top category)
│  - l2_sector    │  (Subcategory)
│  - mention_count│
└────────┬────────┘
         │
         │ has many
         ▼
┌─────────────────┐        ┌──────────────────┐
│  EntityMention  │◄───────│ InformationUnit  │
│                 │        │                  │
│  - entity_id    │        └──────────────────┘
│  - unit_id      │
│  - role         │
│  - sentiment    │
│  - state_delta  │
└─────────────────┘

┌─────────────────┐
│ EntityRelation  │  (Knowledge graph edge)
│                 │
│  - source_id    │───► Entity
│  - target_id    │───► Entity
│  - relation_type│
│  - strength     │
│  - evidence[]   │
└─────────────────┘
```

### Agent Models

```
┌─────────────────┐
│  AgentContext   │  (Passed between agents)
│                 │
│  - original_article
│  - cleaned_content
│  - extracted_5w1h
│  - entities     │
│  - analyst_reports
│  - traces[]    │◄──┐
│  - analysis_mode│   │
└─────────────────┘   │
                      │
        ┌─────────────┘
        │
┌───────▼──────┐
│  AgentTrace  │  (Audit trail)
│              │
│  - agent_name│
│  - timestamp │
│  - duration  │
│  - token_usage
│  - error     │
└──────────────┘
```

---

## Key Components

### 1. Article Models (article.py)

#### Base Article

```python
class Article(BaseModel):
    """Minimal article representation from RSS feed"""

    # Identity
    id: Optional[int] = None
    url: str

    # Content
    title: str
    content: str = ""
    summary: str = ""

    # Metadata
    source: str = ""
    category: str = ""
    author: str = ""
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.now)

    def __hash__(self):
        """Hash by URL for set operations"""
        return hash(self.url)

    def __eq__(self, other):
        """Equality by URL"""
        if isinstance(other, Article):
            return self.url == other.url
        return False
```

#### EnrichedArticle

```python
class EnrichedArticle(BaseModel):
    """
    Multi-agent analyzed article with 6 layers of insights:

    1. Basic Layer: 5W1H extraction
    2. Verification Layer: Credibility and bias analysis
    3. Deep Layer: Historical context and knowledge graph
    4. Sentiment Layer: Public and market sentiment
    5. Reasoning Layer: Impact analysis and risk warnings
    6. Action Layer: Decision recommendations
    """

    # === Base Information (inherited from Article) ===
    id: Optional[int] = None
    url: str
    title: str
    content: str = ""
    summary: str = ""
    source: str = ""
    category: str = ""
    author: str = ""
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.now)

    # === Layer 1: Basic Analysis (5W1H) ===
    who: list[str] = Field(default_factory=list)
    what: str = ""
    when: str = ""
    where: str = ""
    why: str = ""
    how: str = ""
    entities: list[Entity] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)

    # === Layer 2: Verification ===
    source_credibility: Optional[SourceCredibility] = None
    bias_analysis: Optional[BiasAnalysis] = None
    fact_check: Optional[FactCheckResult] = None
    clickbait_score: float = 0.0

    # === Layer 3: Deep Analysis ===
    historical_context: str = ""
    knowledge_graph: Optional[KnowledgeGraph] = None
    cross_language_comparison: dict = Field(default_factory=dict)

    # === Layer 4: Sentiment ===
    public_sentiment: Optional[SentimentAnalysis] = None
    market_sentiment: Optional[MarketSentiment] = None

    # === Layer 5: Reasoning ===
    impact_analysis: Optional[ImpactAnalysis] = None
    risk_warnings: list[RiskWarning] = Field(default_factory=list)

    # === Layer 6: Action ===
    recommendations: dict[str, list[str]] = Field(default_factory=dict)
    # Format: {"investor": [...], "general": [...], "business": [...]}

    # === Metadata ===
    overall_score: float = 0.0  # 1-10
    is_top_pick: bool = False
    ai_summary: str = ""
    tags: list[str] = Field(default_factory=list)
    analysis_timestamp: datetime = Field(default_factory=datetime.now)
    analysis_mode: str = "deep"
    agent_traces: list[AgentTrace] = Field(default_factory=list)

    @property
    def tags_display(self) -> str:
        """Display tags as hierarchy"""
        return " > ".join(self.tags) if self.tags else self.category

    def get_impact_summary(self) -> str:
        """Summarize impact analysis"""
        if not self.impact_analysis:
            return "No impact analysis"

        parts = []
        if self.impact_analysis.direct_impact:
            parts.append(f"Direct: {len(self.impact_analysis.direct_impact)}")
        if self.impact_analysis.second_order_impact:
            parts.append(f"2nd Order: {len(self.impact_analysis.second_order_impact)}")

        return " | ".join(parts)

    @classmethod
    def from_article(cls, article: Article) -> "EnrichedArticle":
        """Convert base article to enriched"""
        return cls(**article.dict())
```

---

### 2. Information Models (information.py)

#### InformationType Enum

```python
class InformationType(str, Enum):
    """Classification of information units"""
    FACT = "fact"         # Factual: announcements, statements, regulations
    OPINION = "opinion"   # Opinions: analysis, predictions, commentary
    EVENT = "event"       # Events: transactions, releases, partnerships
    DATA = "data"         # Data: financial data, market statistics
```

#### InformationUnit

```python
class InformationUnit(BaseModel):
    """
    Atomic information unit - the core building block of
    the information-centric architecture.
    """

    # === Identity ===
    id: str  # Content-based hash
    fingerprint: str  # Semantic fingerprint for deduplication

    # === Core Content ===
    type: InformationType
    title: str  # Concise headline
    content: str  # Detailed content with facts and background
    summary: str = ""  # One-sentence summary

    # === Time Information ===
    event_time: Optional[str] = None  # When event occurred
    report_time: Optional[datetime] = None  # When reported
    time_sensitivity: str = "normal"  # urgent/normal/evergreen

    # === Deep Analysis ===
    analysis_content: str = ""  # Deep insights, trends, contradictions
    key_insights: List[str] = Field(default_factory=list)
    analysis_depth_score: float = 0.0  # 0-1

    # === 4D Value Assessment (0-10) ===
    information_gain: float = 5.0     # Breaks existing consensus?
    actionability: float = 5.0        # Guides specific decisions?
    scarcity: float = 5.0             # First-hand source?
    impact_magnitude: float = 5.0     # Breadth of affected entities

    # === HEX State Classification ===
    state_change_type: str = ""  # TECH/CAPITAL/REGULATION/ORG/RISK/SENTIMENT
    state_change_subtypes: List[str] = Field(default_factory=list)

    # === Three-Level Entity Anchoring ===
    entity_hierarchy: List[EntityAnchor] = Field(default_factory=list)

    # === 5W1H Structure ===
    who: List[str] = Field(default_factory=list)
    what: str = ""
    when: str = ""
    where: str = ""
    why: str = ""
    how: str = ""

    # === Source Tracing ===
    sources: List[SourceReference] = Field(default_factory=list)
    primary_source: str = ""
    extraction_confidence: float = 0.0

    # === Analysis Results ===
    credibility_score: float = 0.0
    importance_score: float = 0.0
    sentiment: str = "neutral"
    impact_assessment: str = ""

    # === Relations ===
    related_unit_ids: List[str] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)

    # === Extracted for Knowledge Graph ===
    extracted_entities: List[dict] = Field(default_factory=list)
    extracted_relations: List[dict] = Field(default_factory=list)

    # === Metadata ===
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    merged_count: int = 1
    is_sent: bool = False

    @property
    def value_score(self) -> float:
        """
        Comprehensive value score (0-10).

        Weights:
        - Information gain: 30%
        - Actionability: 25%
        - Scarcity: 20%
        - Impact magnitude: 25%
        """
        return (
            self.information_gain * 0.30 +
            self.actionability * 0.25 +
            self.scarcity * 0.20 +
            self.impact_magnitude * 0.25
        )

    @property
    def source_count(self) -> int:
        """Number of sources citing this information"""
        return len(self.sources)

    def merge_source(self, new_source: SourceReference):
        """Add source without duplicates"""
        if new_source not in self.sources:
            self.sources.append(new_source)
```

#### SourceReference

```python
class SourceReference(BaseModel):
    """Tracks original source of information"""

    url: str
    title: str
    source_name: str
    published_at: Optional[datetime] = None
    excerpt: str = ""
    credibility_tier: str = "unknown"

    def __eq__(self, other):
        return isinstance(other, SourceReference) and self.url == other.url

    def __hash__(self):
        return hash(self.url)
```

#### EntityAnchor

```python
class EntityAnchor(BaseModel):
    """Three-level entity hierarchy for retrieval"""

    l1_name: str              # Leaf entity (e.g., "DeepSeek", "NVIDIA")
    l1_role: str = "主角"     # Role: protagonist/supporting/mentioned
    l2_sector: str            # Subcategory (e.g., "基础模型", "AI芯片")
    l3_root: str              # Root category (e.g., "人工智能", "半导体")
    confidence: float = 0.8   # Classification confidence
```

---

### 3. Entity Models (entity.py)

#### EntityType and RelationType

```python
class EntityType(str, Enum):
    """Types of entities in knowledge graph"""
    COMPANY = "COMPANY"
    PERSON = "PERSON"
    PRODUCT = "PRODUCT"
    ORG = "ORG"
    CONCEPT = "CONCEPT"
    LOCATION = "LOCATION"
    EVENT = "EVENT"

class RelationType(str, Enum):
    """Types of relationships between entities"""
    # Hierarchy
    PARENT_OF = "parent_of"
    SUBSIDIARY_OF = "subsidiary_of"

    # Parallel
    COMPETITOR = "competitor"
    PARTNER = "partner"
    PEER = "peer"

    # Dependency
    SUPPLIER = "supplier"
    CUSTOMER = "customer"
    INVESTOR = "investor"

    # Personnel
    CEO_OF = "ceo_of"
    FOUNDER_OF = "founder_of"
    EMPLOYEE_OF = "employee_of"
```

#### Entity

```python
class Entity(BaseModel):
    """Knowledge graph node"""

    id: str = Field(default_factory=lambda: f"entity_{uuid.uuid4().hex[:12]}")
    canonical_name: str
    type: EntityType

    # Three-level hierarchy
    l3_root: str = ""     # Top category
    l2_sector: str = ""   # Subcategory

    # Attributes
    attributes: Dict[str, Any] = Field(default_factory=dict)

    # Statistics
    mention_count: int = 0
    first_mentioned: Optional[datetime] = None
    last_mentioned: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
```

#### EntityMention

```python
class EntityMention(BaseModel):
    """Association between entity and information unit"""

    id: str = Field(default_factory=lambda: f"mention_{uuid.uuid4().hex[:12]}")
    entity_id: str
    unit_id: str

    role: str = "主角"  # protagonist/supporting/mentioned
    sentiment: str = "neutral"  # positive/neutral/negative

    # HEX state change
    state_dimension: str = ""  # TECH/CAPITAL/REGULATION/ORG/RISK/SENTIMENT
    state_delta: str = ""      # Change description

    event_time: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
```

#### EntityRelation

```python
class EntityRelation(BaseModel):
    """Knowledge graph edge"""

    id: str = Field(default_factory=lambda: f"rel_{uuid.uuid4().hex[:12]}")
    source_id: str
    target_id: str
    relation_type: RelationType

    strength: float = 1.0      # 0-1
    confidence: float = 0.8    # 0-1
    evidence_unit_ids: List[str] = Field(default_factory=list)

    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
```

#### ExtractedEntity (for AI output)

```python
class ExtractedEntity(BaseModel):
    """Entity extracted from text by AI"""

    name: str
    aliases: List[str] = Field(default_factory=list)
    type: str = "COMPANY"
    role: str = "主角"
    state_change: Optional[Dict[str, str]] = None
    # {"dimension": "TECH", "delta": "Released new model"}
```

---

### 4. Agent Models (agent.py)

#### AnalysisMode

```python
class AnalysisMode(str, Enum):
    """AI analysis depth modes"""
    QUICK = "quick"       # Basic scoring and summary only
    STANDARD = "standard" # Scoring + impact analysis
    DEEP = "deep"         # Full multi-agent analysis
```

#### AgentTrace

```python
class AgentTrace(BaseModel):
    """Audit trail for agent execution"""

    agent_name: str
    timestamp: datetime = Field(default_factory=datetime.now)
    input_summary: str = ""
    output_summary: str = ""
    duration_seconds: float = 0.0
    token_usage: dict = Field(default_factory=dict)
    error: Optional[str] = None

    def to_log_dict(self) -> dict:
        """Format for structured logging"""
        return {
            "agent": self.agent_name,
            "duration": f"{self.duration_seconds:.2f}s",
            "tokens": self.token_usage,
            "error": self.error,
        }
```

#### AgentContext

```python
class AgentContext(BaseModel):
    """
    Shared context passed between agents in the pipeline.

    This enables agents to build upon each other's work.
    """

    # Original article
    original_article: Optional[Any] = None

    # Collector outputs
    cleaned_content: str = ""
    extracted_5w1h: dict = Field(default_factory=dict)

    # Librarian outputs
    entities: list[Any] = Field(default_factory=list)
    historical_context: str = ""
    knowledge_graph: Optional[Any] = None
    related_articles: list[dict] = Field(default_factory=list)

    # Analyst team outputs
    analyst_reports: dict[str, Any] = Field(default_factory=dict)
    # {"skeptic": {...}, "economist": {...}, "detective": {...}}

    # Configuration
    analysis_mode: AnalysisMode = AnalysisMode.DEEP

    # Audit trail
    traces: list[AgentTrace] = Field(default_factory=list)

    def add_trace(self, trace: AgentTrace):
        """Append execution trace"""
        self.traces.append(trace)

    def get_total_duration(self) -> float:
        """Total processing time across all agents"""
        return sum(t.duration_seconds for t in self.traces)

    def get_total_tokens(self) -> dict:
        """Total token usage across all agents"""
        total = {"prompt": 0, "completion": 0}
        for trace in self.traces:
            total["prompt"] += trace.token_usage.get("prompt", 0)
            total["completion"] += trace.token_usage.get("completion", 0)
        return total
```

#### AgentOutput

```python
class AgentOutput(BaseModel):
    """Standardized agent return value"""

    success: bool = True
    data: Any = None
    trace: Optional[AgentTrace] = None
    error: Optional[str] = None

    @classmethod
    def failure(cls, agent_name: str, error: str, duration: float = 0.0):
        """Create failure output"""
        return cls(
            success=False,
            error=error,
            trace=AgentTrace(
                agent_name=agent_name,
                duration_seconds=duration,
                error=error
            )
        )
```

---

## Usage Examples

### Working with Articles

```python
# Create base article
article = Article(
    url="https://example.com/ai-news",
    title="AI Breakthrough",
    content="Full article text...",
    source="TechCrunch",
    category="Technology"
)

# Convert to enriched for analysis
enriched = EnrichedArticle.from_article(article)

# After analysis
enriched.overall_score = 8.5
enriched.is_top_pick = True
enriched.ai_summary = "Major AI advancement..."
enriched.who = ["OpenAI", "Sam Altman"]
enriched.what = "Released GPT-5"

# Display formatted tags
print(enriched.tags_display)  # "Technology > AI > Large Language Models"
```

### Information Units

```python
# Create information unit
unit = InformationUnit(
    id="unit_abc123",
    fingerprint="semantic_hash_xyz",
    type=InformationType.EVENT,
    title="DeepSeek releases new model",
    content="Full details...",
    summary="DeepSeek launched DeepSeek-V3",

    # 5W1H
    who=["DeepSeek"],
    what="Released DeepSeek-V3 model",
    when="January 2026",
    where="China",
    why="Compete in AI market",
    how="Open source release",

    # Value assessment
    information_gain=8.5,
    actionability=7.0,
    scarcity=9.0,
    impact_magnitude=8.0,

    # Entity anchoring
    entity_hierarchy=[
        EntityAnchor(
            l1_name="DeepSeek",
            l1_role="主角",
            l2_sector="基础模型",
            l3_root="人工智能"
        )
    ]
)

# Check value score
print(f"Value score: {unit.value_score:.1f}/10")

# Add source
unit.merge_source(SourceReference(
    url="https://source.com/article",
    title="DeepSeek V3 Launch",
    source_name="TechNews"
))
```

### Entity Knowledge Graph

```python
# Create entity
entity = Entity(
    canonical_name="DeepSeek",
    type=EntityType.COMPANY,
    l3_root="人工智能",
    l2_sector="基础模型"
)

# Record mention
mention = EntityMention(
    entity_id=entity.id,
    unit_id="unit_123",
    role="主角",
    sentiment="positive",
    state_dimension="TECH",
    state_delta="Released new model"
)

# Create relationship
relation = EntityRelation(
    source_id=entity.id,
    target_id="entity_openai",
    relation_type=RelationType.COMPETITOR,
    strength=0.9,
    evidence_unit_ids=["unit_123", "unit_456"]
)
```

### Agent Pipeline

```python
# Initialize context
context = AgentContext(
    original_article=article,
    analysis_mode=AnalysisMode.DEEP
)

# Agent 1: Collector
collector_output = await collector_agent.process(context)
context.extracted_5w1h = collector_output.data
context.add_trace(collector_output.trace)

# Agent 2: Librarian
librarian_output = await librarian_agent.process(context)
context.entities = librarian_output.data
context.add_trace(librarian_output.trace)

# Final statistics
print(f"Total duration: {context.get_total_duration():.2f}s")
print(f"Total tokens: {context.get_total_tokens()}")
```

---

## Design Patterns

### 1. Value Object Pattern

Immutable data structures with value equality:
```python
@dataclass(frozen=True)
class SourceReference:
    url: str
    title: str

    def __eq__(self, other):
        return self.url == other.url
```

### 2. Builder Pattern (via Pydantic)

```python
# Pydantic provides automatic builder
article = Article(
    url="...",
    title="...",
    # Other fields get defaults
)
```

### 3. Factory Pattern

```python
@classmethod
def from_article(cls, article: Article) -> "EnrichedArticle":
    """Factory method for conversion"""
    return cls(**article.dict())
```

### 4. Composite Pattern

```python
class EnrichedArticle:
    # Composed of multiple analysis types
    source_credibility: Optional[SourceCredibility]
    bias_analysis: Optional[BiasAnalysis]
    impact_analysis: Optional[ImpactAnalysis]
```

---

## Validation and Constraints

### Pydantic Validators

```python
class InformationUnit(BaseModel):
    importance_score: float = Field(ge=0.0, le=10.0)  # 0-10 range

    @validator('type')
    def validate_type(cls, v):
        if v not in InformationType:
            raise ValueError(f"Invalid type: {v}")
        return v

    @validator('sources')
    def validate_sources(cls, v):
        if not v:
            raise ValueError("At least one source required")
        return v
```

### Custom Validation

```python
@property
def value_score(self) -> float:
    """Computed field with validation"""
    score = (
        self.information_gain * 0.30 +
        self.actionability * 0.25 +
        self.scarcity * 0.20 +
        self.impact_magnitude * 0.25
    )
    return max(0.0, min(10.0, score))  # Clamp to 0-10
```

---

## Serialization

### JSON Export

```python
# Automatic with Pydantic
article_json = article.json()
article_dict = article.dict()

# Custom serialization
article_dict = article.dict(
    exclude={'id', 'internal_field'},
    exclude_none=True
)
```

### Database Models

```python
# Convert to storage model
def to_db_record(self) -> dict:
    return {
        "url": self.url,
        "title": self.title,
        "tags": json.dumps(self.tags),  # Serialize list
        "analysis": json.dumps(self.impact_analysis.dict())
    }
```

---

## Best Practices

### 1. Use Type Hints

```python
entities: List[Entity] = Field(default_factory=list)
published_at: Optional[datetime] = None
```

### 2. Provide Defaults

```python
created_at: datetime = Field(default_factory=datetime.now)
tags: List[str] = Field(default_factory=list)  # Not []!
```

### 3. Validate Inputs

```python
@validator('url')
def validate_url(cls, v):
    if not v.startswith('http'):
        raise ValueError('URL must start with http')
    return v
```

### 4. Computed Properties

```python
@property
def value_score(self) -> float:
    """Calculate on demand"""
    return self._compute_value()
```

---

## Summary

The Models layer provides:

1. **Type Safety**: Pydantic ensures runtime validation
2. **Dual Architecture**: Supports both article and information-centric flows
3. **Rich Domain Logic**: Business logic embedded in models
4. **Knowledge Graph**: Comprehensive entity relationship modeling
5. **Audit Trail**: Agent execution tracking
6. **Flexibility**: Easy serialization and conversion

These models form the foundation of the entire Message-reader system, ensuring data consistency and type safety throughout.
