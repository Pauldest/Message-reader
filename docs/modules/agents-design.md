# Agents Module Design Document

## Module Overview

**Location**: `src/agents/`

**Purpose**: Multi-agent AI system for intelligent article analysis and information extraction

**Architecture**: Specialized agents with defined responsibilities, coordinated by an orchestrator

**Key Innovation**: Dual processing flows (article-centric legacy + information-centric modern)

---

## Module Structure

```
agents/
├── base.py              # BaseAgent abstract class (143 lines)
├── orchestrator.py      # AnalysisOrchestrator - workflow coordinator (521 lines)
├── collector.py         # CollectorAgent - 5W1H extractor (211 lines)
├── librarian.py         # LibrarianAgent - RAG researcher (261 lines)
├── editor.py            # EditorAgent - synthesis & formatting (183 lines)
├── curator.py           # CuratorAgent - content selector (245 lines)
├── extractor.py         # InformationExtractorAgent - unit extractor (340 lines)
├── merger.py            # InformationMergerAgent - deduplication (156 lines)
├── info_curator.py      # InformationCuratorAgent - digest editor (298 lines)
├── entity_backfill.py   # EntityBackfillAgent - entity normalizer (127 lines)
├── trace_manager.py     # TraceManager - audit trail manager (189 lines)
└── analysts/
    ├── skeptic.py       # SkepticAnalyst - fact checker (234 lines)
    ├── economist.py     # EconomistAnalyst - economic analyst (198 lines)
    └── detective.py     # DetectiveAnalyst - investigator (187 lines)
```

---

## Core Components

### 1. BaseAgent (base.py)

#### Class Diagram

```
┌─────────────────────────────────────┐
│          BaseAgent (ABC)             │
├─────────────────────────────────────┤
│ + AGENT_NAME: str                   │
│ + SYSTEM_PROMPT: str                │
│ + llm: LLMService                   │
├─────────────────────────────────────┤
│ + __init__(llm_service)             │
│ + process(input, context)* abstract│
│ + invoke_llm(...)                   │
│ + create_trace(...)                 │
│ + build_messages(...)               │
└─────────────────────────────────────┘
           △
           │ inherits
   ┌───────┴───────┬───────────┬─────────────┬──────────────┐
   │               │           │             │              │
CollectorAgent  LibrarianAgent EditorAgent  CuratorAgent  ExtractorAgent
```

#### Key Methods

**`async def process(input_data: Any, context: AgentContext) -> AgentOutput`**
- **Abstract method** - must be implemented by subclasses
- **Input**: Article or partial analysis result + shared context
- **Output**: AgentOutput with success status, data, trace, and token usage
- **Pattern**: Template Method Pattern

**`async def invoke_llm(...) -> tuple[Any, dict]`**
- **Purpose**: Unified LLM invocation with automatic telemetry
- **Features**:
  - Automatic agent name tagging for telemetry
  - JSON mode support
  - Token usage tracking
  - Error propagation
- **Implementation**:
```python
async def invoke_llm(
    self,
    user_prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    json_mode: bool = False,
) -> tuple[Any, dict]:
    from ..services.telemetry import AITelemetry
    AITelemetry.set_agent(self.name)

    system = system_prompt or self.SYSTEM_PROMPT
    messages = self.llm.build_messages(system, user_prompt)

    if json_mode:
        result, usage = await self.llm.chat_json(messages, ...)
    else:
        result, usage = await self.llm.chat(messages, ...)

    return result, usage
```

**`def create_trace(...) -> AgentTrace`**
- **Purpose**: Create audit trail record
- **Data**: Agent name, timestamp, I/O summary, duration, token usage, errors
- **Storage**: Collected in AgentContext, persisted by TraceManager

---

### 2. AnalysisOrchestrator (orchestrator.py)

#### Responsibilities

1. **Workflow Coordination**: Manage agent execution order and dependencies
2. **Mode Selection**: Support QUICK, STANDARD, DEEP analysis modes
3. **Dual Flow Support**: Route to article-centric or information-centric processing
4. **Resource Management**: Initialize and manage all agents, stores, and services
5. **Progress Tracking**: Update progress tracker for UI display

#### Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                 AnalysisOrchestrator                         │
├──────────────────────────────────────────────────────────────┤
│ Components:                                                  │
│  • LLMService                                               │
│  • VectorStore (ChromaDB or SQLite)                         │
│  • TraceManager                                             │
│  • ProgressTracker                                          │
│                                                              │
│ Agents:                                                      │
│  • CollectorAgent                                           │
│  • LibrarianAgent                                           │
│  • EditorAgent                                              │
│  • Analysts: {skeptic, economist, detective}                │
│  • InformationExtractorAgent                                │
│  • InformationMergerAgent                                   │
│                                                              │
│ Stores:                                                      │
│  • InformationStore (optional, set via setter)              │
│  • EntityStore (optional, set via setter)                   │
└──────────────────────────────────────────────────────────────┘
```

#### Key Methods

##### **`async def analyze_article(article, mode) -> EnrichedArticle`** (Legacy Flow)

**Flow Diagram**:
```
Article
  │
  ├─→ [QUICK Mode]
  │    └─→ Collector → EnrichedArticle (basic only)
  │
  ├─→ [STANDARD Mode]
  │    └─→ Collector → Librarian → Editor → EnrichedArticle
  │
  └─→ [DEEP Mode]
       └─→ Collector → Librarian → Analysts (parallel) → Editor → EnrichedArticle
```

**Implementation Steps**:
1. Start trace session (if TraceManager enabled)
2. Create AgentContext
3. Execute mode-specific analysis:
   - **QUICK**: Collector only → Basic scoring
   - **STANDARD**: Collector → Librarian → Editor (no analysts)
   - **DEEP**: Full pipeline with all 3 analyst agents in parallel
4. Save final result and trace
5. Return EnrichedArticle

**Code Example**:
```python
async def analyze_article(self, article: Article, mode: AnalysisMode = AnalysisMode.DEEP) -> EnrichedArticle:
    if self.trace_manager:
        self.trace_manager.start_session(article.url, article.title)

    context = AgentContext(original_article=article, analysis_mode=mode)

    try:
        if mode == AnalysisMode.QUICK:
            enriched = await self._quick_analysis(article, context)
        elif mode == AnalysisMode.STANDARD:
            enriched = await self._standard_analysis(article, context)
        else:  # DEEP
            enriched = await self._deep_analysis(article, context)

        if self.trace_manager:
            self.trace_manager.save_final_result(enriched)
            self.trace_manager.end_session()

        return enriched
    except Exception as e:
        logger.error("analysis_failed", error=str(e))
        return EnrichedArticle.from_article(article)
```

##### **`async def process_article_information_centric(article) -> list[InformationUnit]`** (Modern Flow)

**Flow Diagram**:
```
Article
  │
  ├─→ [Optional] Consultant Analysts (parallel)
  │    ├─→ SkepticAnalyst
  │    ├─→ EconomistAnalyst
  │    └─→ DetectiveAnalyst
  │    └─→ Store in AgentContext.analyst_reports
  │
  ├─→ InformationExtractorAgent
  │    └─→ InformationUnit[] (with 4D scores + HEX classification)
  │
  └─→ For each unit:
       ├─→ Check exact fingerprint (MD5 of title+content)
       │    └─→ If match: InformationMergerAgent.merge() → Update
       │
       ├─→ If not found: Vector similarity search (threshold=0.6)
       │    ├─→ If similar found: Merge with existing
       │    └─→ If no similar: Save as new
       │
       └─→ Extract entities & relations → EntityStore
            ├─→ Entity disambiguation
            ├─→ Alias management
            └─→ Mention tracking
```

**Key Features**:
1. **Fingerprint Deduplication**: MD5 hash of `title+content` for O(1) exact match
2. **Semantic Deduplication**: Vector similarity search (cosine > 0.6)
3. **Multi-Source Merging**: Merge information from multiple sources
4. **Knowledge Graph Integration**: Automatic entity extraction and relationship mapping
5. **Consultant-Augmented Extraction**: Optional analyst reports enhance extraction quality

**Implementation**:
```python
async def process_article_information_centric(self, article: Article) -> list[InformationUnit]:
    context = AgentContext(original_article=article, analysis_mode=AnalysisMode.DEEP)

    # 0. Optional consultant phase
    if context.analysis_mode == AnalysisMode.DEEP:
        analyst_names = ["skeptic", "economist", "detective"]
        tasks = [self.analysts[name].safe_process(article, context) for name in analyst_names]
        results = await asyncio.gather(*tasks)

        analyst_results = {}
        for name, result in zip(analyst_names, results):
            analyst_results[name] = result.data
            context.add_trace(result.trace)
        context.analyst_reports = analyst_results

    # 1. Extract information units
    units = await self.extractor.extract(article, context)

    final_units = []
    for unit in units:
        # 2. Check exact fingerprint match
        existing = self.info_store.get_unit_by_fingerprint(unit.fingerprint)
        if existing:
            merged = await self.merger.merge([existing, unit])
            await self.info_store.save_unit(merged)
            final_units.append(merged)
            continue

        # 3. Semantic similarity search
        similar_units = await self.info_store.find_similar_units(unit, threshold=0.6, top_k=3)
        if similar_units:
            all_to_merge = similar_units + [unit]
            merged = await self.merger.merge(all_to_merge)
            merged.id = similar_units[0].id
            merged.fingerprint = similar_units[0].fingerprint
            await self.info_store.save_unit(merged)
            final_units.append(merged)
        else:
            # Completely new unit
            await self.info_store.save_unit(unit)
            final_units.append(unit)

        # 4. Process entities & relations for knowledge graph
        if self.entity_store and (unit.extracted_entities or unit.extracted_relations):
            extracted_entities = [ExtractedEntity(**e) for e in unit.extracted_entities]
            extracted_relations = [ExtractedRelation(**r) for r in unit.extracted_relations]

            entity_id_map = self.entity_store.process_extracted_entities(
                unit_id=unit.id,
                entities=extracted_entities,
                relations=extracted_relations,
                event_time=unit.event_time,
            )

    return final_units
```

---

### 3. CollectorAgent (collector.py)

#### Purpose
Extract basic structured information from raw articles (5W1H + entities + timeline)

#### System Prompt (Excerpt)
```
You are an information collector for a news analysis system.

Your task:
1. Extract 5W1H from the article
2. Identify key entities (people, companies, products, locations)
3. Build event timeline (if multi-event article)
4. Generate core summary

Output JSON format:
{
  "who": ["entity1", "entity2", ...],
  "what": "main event description",
  "when": "2026-01-15 or relative time",
  "where": "location",
  "why": "causes/motivations",
  "how": "process/methods",
  "entities": [
    {"name": "...", "type": "PERSON|COMPANY|PRODUCT|...", "description": "..."},
    ...
  ],
  "timeline": [
    {"time": "...", "event": "...", "impact": "..."},
    ...
  ],
  "core_summary": "One-sentence summary"
}
```

#### Key Methods

**`_clean_content(content: str) -> str`**
- **Purpose**: Remove HTML tags, extra whitespace, and noise
- **Techniques**:
  - Regex: Remove `<tags>`, `\s+`, boilerplate patterns
  - Noise patterns: "点击阅读原文", "关注我们", "责任编辑", etc.
- **Output**: Clean plain text

**`_parse_extraction_result(result: dict) -> dict`**
- **Purpose**: Parse and validate LLM JSON output
- **Validation**:
  - Ensure required fields exist (who, what, when, where, why, how)
  - Validate entity types
  - Normalize date formats
- **Fallback**: Return default structure if parsing fails

---

### 4. LibrarianAgent (librarian.py)

#### Purpose
RAG (Retrieval-Augmented Generation) researcher - searches local knowledge base for related historical articles and provides background context

#### Key Feature: RAG Implementation

**`async def _search_related_articles(article, entities) -> list[dict]`**
```python
async def _search_related_articles(self, article: Article, entities: list[Entity]) -> list[dict]:
    if not self.vector_store or not self.vector_store.is_available:
        return []

    # Build search query from title + entity names
    entity_names = [e.name for e in entities[:5]] if entities else []
    query = f"{article.title} {' '.join(entity_names)}"

    try:
        results = await self.vector_store.search(query, top_k=5)
        return results
    except Exception as e:
        logger.warning("vector_search_failed", error=str(e))
        return []
```

**Query Construction Strategy**:
- Combine article title + top 5 entity names
- Leverages entity-based relevance for better matches
- Top-K retrieval (default 5 articles)

**`async def _store_article(article, context)`**
- **Purpose**: Index current article for future retrieval
- **When**: After analysis completes
- **Data**: Title + cleaned content + metadata (source, date, etc.)

#### Output
- **historical_context**: Narrative summary of related historical events
- **knowledge_graph**: Entity-relation graph from related articles
- **related_articles**: List of similar articles with metadata

---

### 5. InformationExtractorAgent (extractor.py)

#### Purpose
Decompose articles into atomic information units with multi-dimensional value assessment

#### Key Innovation: Consultant-Augmented Extraction

**Architecture**:
```
Article + Optional[AnalystReports]
  │
  ├─→ Build comprehensive prompt with analyst insights
  │
  ├─→ LLM extracts atomic information units
  │
  └─→ For each unit:
       ├─→ Compute fingerprint (MD5 of title+content)
       ├─→ Parse 4D value scores (information_gain, actionability, scarcity, impact_magnitude)
       ├─→ Classify HEX state change type (TECH, CAPITAL, REGULATION, ORG, RISK, SENTIMENT)
       ├─→ Anchor to 3-level entity hierarchy (L3 root → L2 sector → L1 leaf)
       ├─→ Extract entities & relations for knowledge graph
       └─→ Build SourceReference
```

#### Key Methods

**`_parse_unit(item: dict, article: Article) -> InformationUnit`**

**Fingerprint Generation**:
```python
content_str = f"{item.get('title', '')}{item.get('content', '')}"
fingerprint = hashlib.md5(content_str.encode()).hexdigest()
unit_id = f"iu_{fingerprint[:16]}"
```

**Entity Hierarchy Validation**:
```python
l3_root = eh.get("l3_root", "")
if l3_root and l3_root not in ROOT_ENTITIES:
    # Fuzzy match against preset ROOT_ENTITIES
    for root in ROOT_ENTITIES:
        if l3_root in root or root in l3_root:
            l3_root = root
            break
    else:
        l3_root = "其他"  # Default category
```

**4D Score Normalization**:
```python
def safe_score(val, default=5.0):
    try:
        score = float(val) if val is not None else default
        if score <= 1.0 and score > 0:  # Detect 0-1 scale
            score *= 10
        return max(1.0, min(10.0, score))
    except:
        return default
```
- **Auto-detection**: Handles both 0-1 and 0-10 scales
- **Clamping**: Ensures scores are in [1.0, 10.0] range

**HEX State Validation**:
```python
state_type = item.get("state_change_type", "")
valid_types = ["TECH", "CAPITAL", "REGULATION", "ORG", "RISK", "SENTIMENT"]
if state_type not in valid_types:
    state_type = ""
```

---

### 6. InformationMergerAgent (merger.py)

#### Purpose
Merge duplicate information units from multiple sources while preserving source traceability

#### Algorithm

**Input**: List of similar InformationUnits (typically 2-4)

**Process**:
1. **Select Primary**: Use unit with highest `value_score` as base
2. **Merge Content**:
   - Concatenate unique sentences (avoid duplication)
   - Combine key insights (deduplicate)
   - Merge entity lists
3. **Aggregate Scores**: Weighted average based on source credibility
4. **Combine Sources**: Append all SourceReferences
5. **Update Metadata**: Increment `merged_count`, update timestamps

**Code Example**:
```python
async def merge(self, units: list[InformationUnit]) -> InformationUnit:
    if len(units) == 1:
        return units[0]

    # 1. Select primary unit (highest value score)
    primary = max(units, key=lambda u: u.value_score)

    # 2. Merge content
    all_content = set()
    for unit in units:
        sentences = self._split_sentences(unit.content)
        all_content.update(sentences)
    merged_content = " ".join(sorted(all_content))

    # 3. Aggregate scores (weighted by credibility)
    total_weight = sum(u.scarcity for u in units)
    merged_info_gain = sum(u.information_gain * u.scarcity for u in units) / total_weight
    merged_actionability = sum(u.actionability * u.scarcity for u in units) / total_weight
    merged_scarcity = max(u.scarcity for u in units)  # Max credibility
    merged_impact = max(u.impact_magnitude for u in units)  # Max impact

    # 4. Combine sources
    all_sources = []
    for unit in units:
        all_sources.extend(unit.sources)

    # 5. Build merged unit
    merged = InformationUnit(
        id=primary.id,
        fingerprint=primary.fingerprint,
        content=merged_content,
        information_gain=merged_info_gain,
        actionability=merged_actionability,
        scarcity=merged_scarcity,
        impact_magnitude=merged_impact,
        sources=all_sources,
        merged_count=len(units),
        # ... other fields from primary
    )

    return merged
```

---

### 7. CuratorAgent (curator.py)

#### Purpose
Intelligent selection of articles/information units for daily digest

#### Strategy

**Input**: List of EnrichedArticles or InformationUnits

**Output**:
```json
{
  "top_picks": [Article/Unit, ...],      // 3-10 must-read items
  "quick_reads": [Article/Unit, ...],    // 10-30 worth-scanning items
  "excluded": [Article/Unit, ...],       // Low-value items
  "daily_summary": "Overall summary text"
}
```

**Selection Criteria**:
1. **Value Score**: Overall score ≥ 8.0 for top picks, ≥ 5.0 for quick reads
2. **Diversity**: Avoid redundancy, ensure topic variety
3. **Timeliness**: Prefer recent events
4. **Impact**: Prioritize high-impact entities

**AI-Powered Curation**:
```python
async def curate(self, articles: list[EnrichedArticle], max_articles: int = 50) -> dict:
    if len(articles) <= 10:
        return self._simple_selection(articles)  # Fallback

    # Build article summary for AI curation
    articles_summary = self._format_articles_for_selection(articles)

    user_prompt = CURATOR_SELECTION_PROMPT.format(
        total_count=len(articles),
        articles_summary=articles_summary,
    )

    result, token_usage = await self.invoke_llm(
        user_prompt=user_prompt,
        max_tokens=3000,
        temperature=0.3,
        json_mode=True,
    )

    if result:
        selection = self._parse_selection(result, articles, max_articles)
    else:
        selection = self._simple_selection(articles)

    return selection
```

**Fallback Logic** (when AI unavailable):
```python
def _simple_selection(self, articles: list[EnrichedArticle]) -> dict:
    sorted_articles = sorted(articles, key=lambda x: x.overall_score, reverse=True)

    top_picks = []
    quick_reads = []

    for a in sorted_articles:
        if a.overall_score >= 8.0 and len(top_picks) < 5:
            top_picks.append(a)
        elif a.overall_score >= 5.0 and len(quick_reads) < 20:
            quick_reads.append(a)

    return {"top_picks": top_picks, "quick_reads": quick_reads, "excluded": []}
```

---

### 8. Analyst Agents (analysts/)

#### Architecture
```
                    ┌─────────────────┐
                    │   BaseAgent     │
                    └────────▲────────┘
                             │
               ┌─────────────┼─────────────┐
               │             │             │
       ┌───────┴────┐  ┌────┴──────┐  ┌───┴────────┐
       │ Skeptic    │  │ Economist │  │ Detective  │
       │ Analyst    │  │ Analyst   │  │ Analyst    │
       └────────────┘  └───────────┘  └────────────┘
```

#### SkepticAnalyst

**Purpose**: Critical analysis and fact-checking

**Output Schema**:
```json
{
  "source_credibility": {
    "score": 7.5,
    "tier": "mainstream_media",
    "strengths": ["established publisher", "verified sources"],
    "weaknesses": ["potential conflicts of interest"]
  },
  "bias_analysis": {
    "political_bias": "center",
    "emotional_bias": "neutral",
    "detected_biases": ["mild optimism bias"]
  },
  "fact_check": {
    "verifiable_claims": ["claim1", "claim2"],
    "unverified_claims": ["claim3"],
    "contradictions": []
  },
  "clickbait_score": 2.5,
  "logical_flaws": []
}
```

#### EconomistAnalyst

**Purpose**: Economic impact and market analysis

**Output Schema**:
```json
{
  "economic_impact": {
    "direct_impact": [{
      "entity": "Company A",
      "aspect": "revenue",
      "direction": "positive",
      "magnitude": 7.0,
      "reasoning": "..."
    }],
    "second_order_impact": [...],
    "third_order_impact": [...]
  },
  "market_sentiment": {
    "overall": "bullish",
    "confidence": 0.8
  },
  "investment_implications": ["implication1", "implication2"]
}
```

#### DetectiveAnalyst

**Purpose**: Hidden connections and pattern recognition

**Output Schema**:
```json
{
  "connections": [
    {
      "entity1": "Company A",
      "entity2": "Person B",
      "relation": "ceo_of",
      "evidence": "..."
    }
  ],
  "patterns": ["pattern1", "pattern2"],
  "background_findings": ["finding1", "finding2"]
}
```

---

## Data Flow Patterns

### Pattern 1: Sequential Pipeline (Legacy Flow)

```
┌────────┐    ┌───────────┐    ┌───────────┐    ┌─────────┐
│Collect │ => │ Librarian │ => │ Analysts  │ => │ Editor  │
│ Agent  │    │   Agent   │    │ (parallel)│    │  Agent  │
└────────┘    └───────────┘    └───────────┘    └─────────┘
     │             │                  │               │
     └─────────────┴──────────────────┴───────────────┘
                          │
                   AgentContext
            (shared state, traces, token usage)
```

**Context Evolution**:
1. **After Collector**: `context.extracted_5w1h`, `context.entities`
2. **After Librarian**: `context.historical_context`, `context.related_articles`
3. **After Analysts**: `context.analyst_reports` = {skeptic: {...}, economist: {...}, detective: {...}}
4. **After Editor**: Final `EnrichedArticle` with all layers

### Pattern 2: Extract-Merge-Store (Modern Flow)

```
        ┌──────────┐
        │ Article  │
        └─────┬────┘
              │
    ┌─────────┴─────────┐
    │  Extractor Agent  │ (with optional analyst reports)
    └─────────┬─────────┘
              │
       List[InformationUnit]
              │
              ▼
    ┌─────────────────────┐
    │ For each unit:      │
    │ 1. Fingerprint check│
    │ 2. Semantic search  │
    │ 3. Merge if similar │
    │ 4. Extract entities │
    └─────────┬───────────┘
              │
      ┌───────┴────────┐
      │                │
      ▼                ▼
┌──────────┐    ┌────────────┐
│  InfoStore│    │ EntityStore│
└──────────┘    └────────────┘
```

---

## Design Patterns Used

### 1. Template Method Pattern
- **BaseAgent.process()**: Abstract method enforces consistent interface
- **Subclasses**: Implement specific processing logic

### 2. Strategy Pattern
- **Analysis Modes**: QUICK, STANDARD, DEEP
- **Different strategies**: Different agent combinations

### 3. Chain of Responsibility
- **Agent Pipeline**: Each agent processes and passes to next
- **Context Object**: Carries state through chain

### 4. Observer Pattern
- **TraceManager**: Observes agent executions, records traces
- **ProgressTracker**: Observes progress, updates UI

### 5. Façade Pattern
- **AnalysisOrchestrator**: Simplifies complex multi-agent coordination

### 6. Command Pattern
- **AgentOutput**: Encapsulates result of agent execution

---

## Error Handling Strategy

### Agent-Level Failures
```python
try:
    result = await agent.process(article, context)
    context.add_trace(result.trace)
    return result.data
except Exception as e:
    logger.error("agent_failed", agent=agent.name, error=str(e))
    # Return default/empty result, don't stop pipeline
    return default_output
```

### Orchestrator-Level Failures
```python
try:
    enriched = await self._deep_analysis(article, context)
    return enriched
except Exception as e:
    logger.error("analysis_failed", error=str(e))
    # Fallback: return minimal EnrichedArticle from raw article
    return EnrichedArticle.from_article(article)
```

**Philosophy**: **Graceful degradation** - partial results better than no results

---

## Performance Considerations

### Parallelization
- **Analyst agents**: Run in parallel using `asyncio.gather()`
- **Information unit processing**: Concurrent with semaphore

### Token Optimization
- **Content truncation**: Limit article content to ~3000-20000 chars per agent
- **Selective agent invocation**: QUICK mode uses fewer agents

### Caching
- **Vector store**: Caches embeddings
- **Entity store**: Caches canonical entity names and aliases

---

## Testing Strategy

### Unit Tests
- Test each agent in isolation with mock LLMService
- Verify output schema compliance
- Test error handling (LLM failures, malformed outputs)

### Integration Tests
- Test orchestrator workflows (QUICK, STANDARD, DEEP modes)
- Test information-centric flow end-to-end
- Verify context propagation

### Example Test
```python
@pytest.mark.asyncio
async def test_collector_agent_extraction():
    mock_llm = MockLLMService()
    collector = CollectorAgent(mock_llm)

    article = Article(
        url="https://example.com/test",
        title="Test Article",
        content="AI company announces new model..."
    )

    context = AgentContext(original_article=article)
    result = await collector.process(article, context)

    assert result.success
    assert "who" in result.data
    assert "entities" in result.data
    assert len(result.data["entities"]) > 0
```

---

## Extension Points

### Adding a New Agent

1. **Create agent file**: `src/agents/new_agent.py`
2. **Inherit from BaseAgent**:
```python
class NewAgent(BaseAgent):
    AGENT_NAME = "NewAgent"
    SYSTEM_PROMPT = "You are a..."

    async def process(self, input_data, context):
        # Implementation
        result, usage = await self.invoke_llm(...)
        return AgentOutput(success=True, data=result, trace=...)
```
3. **Register in orchestrator**: Add to `AnalysisOrchestrator.__init__()`
4. **Update workflow**: Integrate into pipeline (e.g., add to `_deep_analysis()`)

### Adding a New Analysis Mode

1. **Define in models/agent.py**:
```python
class AnalysisMode(str, Enum):
    CUSTOM = "custom"
```
2. **Implement in orchestrator**:
```python
async def _custom_analysis(self, article, context):
    # Custom agent combination
    pass
```
3. **Route in `analyze_article()`**

---

## Dependencies

### Internal
- `src/models/`: Article, InformationUnit, Entity, AgentContext, AgentOutput, AgentTrace
- `src/services/llm.py`: LLMService
- `src/services/telemetry.py`: AITelemetry
- `src/storage/`: VectorStore, InformationStore, EntityStore

### External
- `asyncio`: Async execution
- `hashlib`: Fingerprint generation
- `json`, `re`: Data parsing
- `time`, `datetime`: Timing and timestamps

---

## Configuration

### Agent-Specific Settings (Future)
```yaml
agents:
  collector:
    max_content_length: 3000
  librarian:
    rag_top_k: 5
  extractor:
    max_output_tokens: 8000
    temperature: 0.3
  analysts:
    enabled: ["skeptic", "economist", "detective"]
```

---

## Metrics & Observability

### Telemetry
- Every LLM call recorded with agent name
- Token usage tracked per agent
- Duration measured per agent

### Traces
- Complete audit trail saved to disk
- JSON format for easy analysis
- Includes input/output summaries

### Logging
```python
logger.info("agent_started", agent=agent.name, article_id=article.id)
logger.info("agent_completed", agent=agent.name, duration=duration, tokens=token_usage)
logger.error("agent_failed", agent=agent.name, error=str(e))
```

---

## Future Enhancements

### 1. Agent Orchestration Strategies
- **Sequential**: Current implementation
- **Parallel-All**: All agents run independently, editor merges
- **Conditional**: Agent selection based on article type

### 2. Agent Learning
- Store successful extraction patterns
- Fine-tune prompts based on feedback

### 3. Agent Specialization
- Domain-specific agents (sports, finance, tech)
- Language-specific agents

### 4. Agent Collaboration
- Agents can query each other
- Consensus mechanisms for conflicting analyses

---

## Summary

The agents module implements a sophisticated multi-agent AI system with:

**Strengths**:
- ✅ Clean abstraction with BaseAgent
- ✅ Flexible orchestration supporting multiple workflows
- ✅ Dual architecture (legacy + modern)
- ✅ Graceful degradation on failures
- ✅ Complete observability via traces
- ✅ Extensible design for new agents

**Innovations**:
- 🎯 Information-centric processing with atomic units
- 🎯 Consultant-augmented extraction
- 🎯 Multi-source merging with fingerprint deduplication
- 🎯 RAG integration for context-aware analysis

**Best Practices**:
- Template Method pattern for consistent interface
- Strategy pattern for analysis modes
- Chain of Responsibility for pipelines
- Comprehensive error handling
- Full telemetry integration

This module is the **core intelligence** of the Message-reader system, transforming raw articles into structured, analyzed, and actionable information.
