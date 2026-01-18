# AI Module Design Document

## Module Overview

**Module Name**: AI Analysis Utilities
**Location**: `src/ai/`
**Purpose**: Provide legacy AI-powered article analysis capabilities including scoring, summarization, tagging, merging, and top pick selection.

**Note**: This module represents the **legacy article-centric architecture**. The modern multi-agent system is located in `src/agents/`. This module is simpler and faster but less sophisticated than the agent-based approach.

**Key Features**:
- Batch article scoring (1-10 scale)
- AI-powered summarization
- Hierarchical tag assignment
- Similar article merging
- Top pick selection with history awareness
- Fallback mechanisms for AI failures

---

## File Structure

```
src/ai/
├── __init__.py                   # Package exports
├── analyzer.py                   # ArticleAnalyzer class (400+ lines)
└── prompts.py                    # AI prompt templates (146 lines)
```

**Lines of Code**: ~550 lines
**Complexity**: Medium (simpler than agents, but still significant)

---

## Architecture Comparison

### Legacy AI Module (This Module) vs Modern Multi-Agent System

| Aspect | Legacy AI Module | Modern Multi-Agent |
|--------|------------------|-------------------|
| **Location** | `src/ai/` | `src/agents/` |
| **Architecture** | Single analyzer class | 10+ specialized agents |
| **Processing Unit** | Entire article | Atomic information units |
| **Analysis Depth** | Basic scoring + summary | 6-layer analysis |
| **Prompts** | 4 templates | 15+ specialized prompts |
| **Use Case** | Quick filtering | Deep intelligence |
| **Speed** | Fast (~1-2s/article) | Slower (~10-30s/article) |
| **Cost** | Low (1-2K tokens/article) | High (10-50K tokens/article) |

**When to use Legacy AI**:
- Quick content filtering
- Limited budget
- Simple summarization needs
- Historical compatibility

**When to use Multi-Agent**:
- Deep analysis required
- Entity tracking needed
- Knowledge graph building
- Maximum intelligence extraction

---

## Class Diagram

```
┌────────────────────────────────────────────────┐
│          ArticleAnalyzer                       │
│                                                │
│  - config: AIConfig                            │
│  - client: AsyncOpenAI                         │
│  - model: str                                  │
│  - max_tokens: int                             │
│  - temperature: float                          │
│                                                │
│  + analyze_batch()              ──────┐       │
│  - _analyze_batch()                   │       │
│  - _merge_similar_articles()          │       │
│  - _select_top_picks()                │       │
│  - _format_articles_for_prompt()      │       │
│  - _parse_json_response()             │       │
│  - _fallback_analyze()                │       │
└───────────────────────────────────────┴───────┘
                                        │
                                        │ uses
                                        ▼
                            ┌───────────────────┐
                            │  Prompt Templates │
                            │                   │
                            │ - SYSTEM_PROMPT   │
                            │ - FILTER_PROMPT   │
                            │ - TOP_SELECTION_  │
                            │   PROMPT          │
                            │ - MERGE_PROMPT    │
                            └───────────────────┘
```

---

## Key Components

### 1. ArticleAnalyzer (analyzer.py)

**Core class for legacy AI-powered article analysis.**

#### Initialization

```python
class ArticleAnalyzer:
    """Legacy article AI analyzer"""

    def __init__(self, config: AIConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.max_tokens = config.max_tokens
        self.temperature = config.temperature
```

**Configuration**:
```yaml
ai:
  provider: deepseek
  api_key: ${DEEPSEEK_API_KEY}
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  max_tokens: 8000
  temperature: 0.3
```

---

#### Key Method: analyze_batch()

**Three-step article analysis pipeline.**

```python
async def analyze_batch(
    self,
    articles: list[Article],
    top_pick_count: int = 5,
    batch_size: int = 20,
    recent_history: list[dict] = None
) -> list[AnalyzedArticle]:
    """
    Batch analyze articles with three steps:

    1. Score and summarize in batches
    2. Merge similar articles
    3. Select top picks (avoiding history duplication)

    Returns:
        List of AnalyzedArticle with scores, summaries, tags, and is_top_pick flags
    """
```

**Pipeline Flow**:
```
Input: List[Article]
    │
    ├─► Step 1: Batch Scoring & Summarization
    │       │
    │       ├─► Split into batches of 20
    │       ├─► Call _analyze_batch() for each
    │       ├─► LLM returns scores, summaries, tags
    │       └─► Filter: Keep only score >= 5.0
    │
    ├─► Step 2: Merge Similar Articles
    │       │
    │       ├─► Call _merge_similar_articles()
    │       ├─► LLM identifies same event/topic
    │       ├─► Keep highest-scored representative
    │       └─► Combine summaries
    │
    └─► Step 3: Select Top Picks
            │
            ├─► Call _select_top_picks()
            ├─► LLM selects N best articles
            ├─► Avoid duplicates with recent_history
            └─► Set is_top_pick = True
                │
                ▼
        Output: List[AnalyzedArticle]
```

**Implementation**:
```python
async def analyze_batch(self, articles, top_pick_count=5, batch_size=20, recent_history=None):
    if not articles:
        return []

    logger.info("analyzing_articles", count=len(articles))

    # Step 1: Batch scoring
    all_analyzed = []
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        analyzed = await self._analyze_batch(batch)
        all_analyzed.extend(analyzed)
        logger.info("batch_analyzed", batch=i // batch_size + 1, count=len(analyzed))

    # Sort by score
    all_analyzed.sort(key=lambda x: x.score, reverse=True)

    # Filter low-quality articles (< 5.0)
    qualified_articles = [a for a in all_analyzed if a.score >= 5]
    logger.info("qualified_articles", count=len(qualified_articles))

    if not qualified_articles:
        return all_analyzed

    # Step 2: Merge similar articles
    merged_articles = await self._merge_similar_articles(qualified_articles)
    logger.info("articles_merged", before=len(qualified_articles), after=len(merged_articles))

    # Step 3: Select top picks
    if len(merged_articles) > top_pick_count:
        top_indices = await self._select_top_picks(
            merged_articles,
            top_pick_count,
            recent_history=recent_history or []
        )
        for idx in top_indices:
            if 0 <= idx < len(merged_articles):
                merged_articles[idx].is_top_pick = True
    else:
        # Too few articles, all are top picks
        for article in merged_articles:
            article.is_top_pick = True

    logger.info("analysis_complete",
               total=len(merged_articles),
               top_picks=sum(1 for a in merged_articles if a.is_top_pick))

    return merged_articles
```

---

#### Step 1: _analyze_batch() - Scoring & Summarization

**Analyze a batch of articles (max 20) with LLM.**

```python
async def _analyze_batch(self, articles: list[Article]) -> list[AnalyzedArticle]:
    """Score and summarize a batch of articles"""
    # Format articles for prompt
    articles_text = self._format_articles_for_prompt(articles)

    prompt = FILTER_PROMPT.format(articles_text=articles_text)

    try:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        content = response.choices[0].message.content
        result = self._parse_json_response(content)

        if not result or "articles" not in result:
            logger.warning("invalid_ai_response", content=content[:200])
            return self._fallback_analyze(articles)

        analyzed = []
        for item in result["articles"]:
            idx = item.get("index", 0)
            if 0 <= idx < len(articles):
                article = articles[idx]
                # Get tags, fallback to category
                tags = item.get("tags", [])
                if not tags and article.category:
                    tags = [article.category]

                analyzed.append(AnalyzedArticle(
                    **article.model_dump(),
                    score=item.get("score", 5.0),
                    ai_summary=item.get("summary", ""),
                    reasoning=item.get("reasoning", ""),
                    tags=tags,
                ))

        return analyzed

    except Exception as e:
        logger.error("ai_analysis_failed", error=str(e))
        return self._fallback_analyze(articles)
```

**Input Format** (articles_text):
```
[0] 标题：GPT-5 将在2026年发布
来源：TechCrunch
内容：OpenAI CEO Sam Altman透露，GPT-5预计在2026年...

[1] 标题：Meta发布Llama 3
来源：The Verge
内容：Meta今天发布了Llama 3大语言模型...
```

**Expected LLM Output**:
```json
{
  "articles": [
    {
      "index": 0,
      "score": 8.5,
      "summary": "OpenAI计划2026年发布GPT-5，性能将大幅提升",
      "reasoning": "独家信息，行业影响力大",
      "tags": ["科技", "人工智能", "大语言模型", "GPT"]
    },
    {
      "index": 1,
      "score": 7.0,
      "summary": "Meta开源Llama 3模型，性能接近GPT-4",
      "reasoning": "重要行业动态，但信息较常规",
      "tags": ["科技", "人工智能", "大语言模型", "Llama"]
    }
  ]
}
```

---

#### Step 2: _merge_similar_articles() - Deduplication

**Merge articles covering the same event or topic.**

```python
async def _merge_similar_articles(self, articles: list[AnalyzedArticle]) -> list[AnalyzedArticle]:
    """Merge similar articles covering same events"""
    if len(articles) <= 5:
        # Too few articles, no need to merge
        return articles

    articles_text = self._format_articles_for_prompt(articles)
    prompt = MERGE_PROMPT.format(articles_text=articles_text)

    try:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=self.max_tokens,
            temperature=0.2,  # Lower temperature for consistent merging
        )

        content = response.choices[0].message.content
        result = self._parse_json_response(content)

        if not result or "merged_groups" not in result:
            logger.warning("merge_failed_fallback")
            return articles

        # Build merged article list
        merged = []
        processed_indices = set()

        for group in result["merged_groups"]:
            rep_idx = group.get("representative_index")
            merged_indices = group.get("merged_indices", [])
            merged_summary = group.get("merged_summary", "")

            if rep_idx is None or rep_idx >= len(articles):
                continue

            # Mark all indices as processed
            processed_indices.update(merged_indices)

            # Use representative article
            rep_article = articles[rep_idx]

            # Update summary if merged multiple articles
            if len(merged_indices) > 1 and merged_summary:
                rep_article.ai_summary = merged_summary
                # Add merge metadata
                rep_article.merged_count = len(merged_indices)
                rep_article.merged_sources = [
                    articles[i].source for i in merged_indices
                    if i < len(articles)
                ]

            merged.append(rep_article)

        # Add any articles that weren't processed (safety fallback)
        for i, article in enumerate(articles):
            if i not in processed_indices:
                merged.append(article)
                logger.warning("article_not_merged", index=i, title=article.title)

        return merged

    except Exception as e:
        logger.error("merge_failed", error=str(e))
        return articles
```

**Example Merging**:

**Before**:
1. [9.0] OpenAI发布GPT-5 (TechCrunch)
2. [8.5] GPT-5性能测试报告 (The Verge)
3. [8.0] Sam Altman谈GPT-5开发 (Wired)
4. [7.0] Meta推出新AI芯片 (Reuters)

**After**:
1. [9.0] **Merged**: OpenAI发布GPT-5，多项性能测试显示提升明显 (merged_count=3, sources=[TechCrunch, The Verge, Wired])
2. [7.0] Meta推出新AI芯片 (独立事件)

---

#### Step 3: _select_top_picks() - Curation

**Select N most valuable articles, avoiding history duplication.**

```python
async def _select_top_picks(
    self,
    articles: list[AnalyzedArticle],
    count: int,
    recent_history: list[dict] = None
) -> list[int]:
    """
    Select top N articles with history awareness.

    Args:
        articles: Candidate articles (already scored and merged)
        count: Number of top picks to select
        recent_history: Recently sent article titles/summaries to avoid duplication

    Returns:
        List of selected article indices
    """
    articles_text = self._format_articles_for_prompt(articles)

    # Build history section
    history_section = ""
    if recent_history:
        history_text = "\n".join([
            f"- {item.get('title', '')} ({item.get('date', '')})"
            for item in recent_history[:20]  # Last 20 articles
        ])
        history_section = f"""
最近已发送的文章（避免选择相似主题）：
{history_text}
"""

    prompt = TOP_SELECTION_PROMPT.format(
        count=count,
        articles_text=articles_text,
        history_section=history_section
    )

    try:
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.3,
        )

        content = response.choices[0].message.content
        result = self._parse_json_response(content)

        if result and "top_picks" in result:
            selected = result["top_picks"]
            # Validate indices
            valid_indices = [i for i in selected if 0 <= i < len(articles)]
            logger.info("top_picks_selected",
                       requested=count,
                       selected=len(valid_indices),
                       reasoning=result.get("selection_reasoning", ""))
            return valid_indices[:count]
        else:
            logger.warning("top_selection_failed_fallback")
            # Fallback: select top N by score
            return list(range(min(count, len(articles))))

    except Exception as e:
        logger.error("top_selection_failed", error=str(e))
        # Fallback: select top N by score
        return list(range(min(count, len(articles))))
```

**Selection Criteria** (from prompt):
1. **Information Value**: New knowledge, insights, cognitive shifts
2. **Timeliness**: Important breaking news
3. **Depth Quality**: Unique analysis and deep thinking
4. **Actionability**: Guides decisions or actions
5. **Diversity**: Avoid topic redundancy
6. **History Avoidance**: Don't select topics recently sent

---

### 2. Prompt Templates (prompts.py)

**Carefully engineered prompts for consistent LLM behavior.**

#### SYSTEM_PROMPT - Strict Editor Persona

```python
SYSTEM_PROMPT = """你是一位严厉的编辑，任务是帮助用户筛选真正有价值的内容，打破信息茧房。

你的评判标准非常严格：

❌ 低分内容（1-4分）：
- 标题党：夸张标题，内容空洞
- 软文广告：变相推销产品或服务
- 旧闻翻炒：无新信息，炒冷饭
- 低信息密度：废话太多，干货太少
- 情绪煽动：制造焦虑恐惧，无实质内容
- 抄袭搬运：缺乏原创见解

✅ 高分内容（7-10分）：
- 原创深度分析：有独到见解和深入思考
- 独家信息/数据：提供独特的信息源
- 实用技术教程：可操作性强,能学到东西
- 行业趋势洞察：对未来发展有前瞻性判断
- 优质信息整理：虽非原创但整理有价值

中等内容（5-6分）：
- 有一定价值但不够突出
- 信息质量中等

请用中文回复。"""
```

**Design Philosophy**:
- **Strict Standards**: Fight information cocoon, promote quality
- **Clear Rubric**: 3-tier scoring system (1-4, 5-6, 7-10)
- **Specific Examples**: Anti-clickbait, anti-soft-ads, anti-reheated-news
- **Value-Oriented**: Prioritize original insights, exclusive data, practical tutorials

---

#### FILTER_PROMPT - Scoring & Tagging

```python
FILTER_PROMPT = """请分析以下文章列表，为每篇文章：
1. 打分（1-10分）
2. 给出一句话核心摘要
3. 分配多层级标签（从宏观到微观，2-4个层级）

文章列表：
{articles_text}

【标签层级说明】
标签应从宏观到微观，反映文章的分类体系。例如：
- ["科技", "人工智能", "大语言模型", "GPT"]
- ["商业", "创业", "融资"]
- ["技术", "编程", "Python", "Web开发"]
- ["生活", "效率", "时间管理"]
- ["财经", "投资", "股票", "A股"]

常用一级标签：科技、技术、商业、财经、产品、设计、生活、职场、教育、健康

请严格按照以下 JSON 格式返回结果，不要添加任何其他内容：
```json
{
  "articles": [
    {
      "index": 0,
      "score": 7.5,
      "summary": "一句话概括文章核心观点",
      "reasoning": "给这个分数的简短理由",
      "tags": ["一级标签", "二级标签", "三级标签"]
    }
  ]
}
```

注意：
1. index 对应文章在列表中的位置（从0开始）
2. score 为 1-10 的浮点数，请严格评分
3. summary 必须是一句话，不超过50字
4. reasoning 简短说明打分理由
5. tags 为 2-4 个层级的标签数组，从宏观到微观排列"""
```

**Key Features**:
- Hierarchical tagging (macro → micro)
- Concise summaries (max 50 chars)
- Scoring justification
- Strict JSON format enforcement

---

#### MERGE_PROMPT - Article Deduplication

```python
MERGE_PROMPT = """请分析以下已评分的文章列表，找出报道同一事件或讨论同一话题的文章，并将它们合并。

文章列表：
{articles_text}

【合并规则】
1. 多篇文章报道同一新闻事件 → 合并为一条，保留最高分作为代表
2. 多篇文章讨论同一技术/产品 → 合并为一条，保留分析最深入的
3. 不同角度、不同事件的文章 → 不合并，各自保留
4. 合并后的文章应该生成一个综合摘要

请返回合并结果，严格按照 JSON 格式：
```json
{
  "merged_groups": [
    {
      "representative_index": 0,
      "merged_indices": [0, 5, 12],
      "merged_summary": "综合多篇报道的核心摘要",
      "merge_reason": "这3篇文章都在报道同一事件"
    },
    {
      "representative_index": 3,
      "merged_indices": [3],
      "merged_summary": "保持原摘要",
      "merge_reason": "独立话题，无需合并"
    }
  ]
}
```

注意：
1. representative_index 是合并后保留的代表文章索引
2. merged_indices 包含被合并的所有文章索引（包括代表文章）
3. 如果文章主题独立，merged_indices 就只包含它自己
4. 每篇文章只能出现在一个 merged_group 中
5. 所有文章都必须被分配到某个 merged_group"""
```

---

#### TOP_SELECTION_PROMPT - Curated Picks

```python
TOP_SELECTION_PROMPT = """从以下已评分的文章中，选出 {count} 篇最值得花时间深度阅读的文章。

已评分文章：
{articles_text}

{history_section}

选择标准（按重要性排序）：
1. 信息价值：能否带来新知识、新洞察、或改变认知
2. 时效性：是否是需要及时了解的重要信息
3. 深度质量：是否有独到分析和深入思考
4. 可操作性：是否能指导实际行动或决策
5. 多样性：避免选择主题过于相似的文章
6. 避免重复：不要选择与"最近已发送的文章"主题相同或高度相似的内容

请返回选中文章的索引列表，严格按照 JSON 格式：
```json
{
  "top_picks": [0, 3, 5, 7, 12],
  "selection_reasoning": "简要说明选择理由"
}
```

注意：返回的索引必须存在于文章列表中。"""
```

---

## Utility Methods

### _format_articles_for_prompt()

```python
def _format_articles_for_prompt(self, articles: list[Article | AnalyzedArticle]) -> str:
    """Format articles for LLM prompt"""
    formatted = []
    for i, article in enumerate(articles):
        text = f"[{i}] 标题：{article.title}\n来源：{article.source}\n"

        # Add score and summary if available (for AnalyzedArticle)
        if hasattr(article, 'score'):
            text += f"评分：{article.score}\n"
        if hasattr(article, 'ai_summary') and article.ai_summary:
            text += f"摘要：{article.ai_summary}\n"

        # Add content preview (first 500 chars)
        if article.content:
            preview = article.content[:500] + "..." if len(article.content) > 500 else article.content
            text += f"内容：{preview}\n"

        formatted.append(text)

    return "\n".join(formatted)
```

### _parse_json_response()

```python
def _parse_json_response(self, content: str) -> dict | None:
    """
    Parse JSON from LLM response, handling markdown code blocks.

    Handles formats:
    - ```json\n{...}\n```
    - ```\n{...}\n```
    - {...}
    """
    try:
        # Remove markdown code blocks
        json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = content

        # Remove any leading/trailing whitespace
        json_str = json_str.strip()

        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.error("json_parse_failed", error=str(e), content=content[:200])
        return None
    except Exception as e:
        logger.error("parse_error", error=str(e))
        return None
```

### _fallback_analyze()

```python
def _fallback_analyze(self, articles: list[Article]) -> list[AnalyzedArticle]:
    """
    Fallback analysis when AI fails.

    Returns articles with:
    - Default score: 5.0
    - Summary: First 100 chars of content
    - Tags: [category] if available
    """
    logger.warning("using_fallback_analysis", count=len(articles))

    analyzed = []
    for article in articles:
        summary = article.content[:100] + "..." if article.content else article.title
        tags = [article.category] if article.category else []

        analyzed.append(AnalyzedArticle(
            **article.model_dump(),
            score=5.0,
            ai_summary=summary,
            reasoning="AI分析失败，使用默认评分",
            tags=tags,
        ))

    return analyzed
```

---

## Data Models

### Article (Input)

```python
from pydantic import BaseModel

class Article(BaseModel):
    url: str
    title: str
    content: Optional[str] = None
    summary: Optional[str] = None
    source: str
    category: Optional[str] = None
    published_at: Optional[datetime] = None
```

### AnalyzedArticle (Output)

```python
class AnalyzedArticle(Article):
    """Article with AI analysis results"""
    score: float  # 1-10
    ai_summary: str
    reasoning: str
    tags: list[str] = []
    is_top_pick: bool = False

    # Optional merge metadata
    merged_count: int = 1
    merged_sources: list[str] = []
```

---

## Error Handling Strategy

### LLM API Failures

```python
try:
    response = await self.client.chat.completions.create(...)
    content = response.choices[0].message.content
    result = self._parse_json_response(content)

    if not result:
        logger.warning("invalid_response")
        return self._fallback_analyze(articles)

    return process_result(result)

except Exception as e:
    logger.error("llm_api_failed", error=str(e))
    return self._fallback_analyze(articles)
```

### JSON Parsing Failures

```python
try:
    result = json.loads(json_str)
except json.JSONDecodeError:
    # Try removing code blocks
    json_match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1))
    else:
        return None
```

### Graceful Degradation

**Philosophy**: Partial results are better than no results.

- **AI unavailable**: Use `_fallback_analyze()` with default scores
- **Merge fails**: Keep all articles unmerged
- **Top pick selection fails**: Select top N by score

---

## Performance Considerations

### Batch Processing

- Process 20 articles per LLM call
- Reduces API overhead
- Faster than individual calls
- Lower cost (batch tokens shared)

### Token Optimization

```python
# Limit content preview
preview = article.content[:500] + "..." if len(article.content) > 500 else article.content
```

### Temperature Tuning

- **Scoring**: `temperature=0.3` (consistent scores)
- **Merging**: `temperature=0.2` (deterministic grouping)
- **Selection**: `temperature=0.3` (balanced diversity)

---

## Testing Strategy

### Unit Tests

```python
@pytest.mark.asyncio
async def test_analyze_batch():
    mock_config = AIConfig(
        api_key="test-key",
        model="gpt-4",
        max_tokens=4000,
        temperature=0.3
    )

    analyzer = ArticleAnalyzer(mock_config)

    # Mock LLM response
    with patch.object(analyzer.client.chat.completions, 'create') as mock_create:
        mock_create.return_value = MockResponse(
            content='{"articles": [{"index": 0, "score": 8.0, "summary": "Test", "reasoning": "Good", "tags": ["Tech"]}]}'
        )

        articles = [Article(url="https://test.com", title="Test", content="Content", source="Test Source")]
        results = await analyzer.analyze_batch(articles, top_pick_count=1)

        assert len(results) == 1
        assert results[0].score == 8.0
        assert results[0].is_top_pick == True
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_full_pipeline_with_real_llm():
    """Test with real LLM API (requires API key)"""
    config = get_config()
    analyzer = ArticleAnalyzer(config.ai)

    articles = load_test_articles()  # 30 test articles
    results = await analyzer.analyze_batch(articles, top_pick_count=5)

    assert len(results) > 0
    assert sum(1 for a in results if a.is_top_pick) == 5
    assert all(a.score >= 5.0 for a in results)
```

---

## Migration Path

### From Legacy AI to Modern Multi-Agent

```python
# Legacy approach
from src.ai.analyzer import ArticleAnalyzer
analyzer = ArticleAnalyzer(config.ai)
results = await analyzer.analyze_batch(articles)

# Modern multi-agent approach
from src.agents.orchestrator import AnalysisOrchestrator
orchestrator = AnalysisOrchestrator(llm_service, vector_store)
enriched = await orchestrator.analyze_article(article, mode=AnalysisMode.DEEP)
```

**When to migrate**:
- Need deeper analysis (6-layer vs basic)
- Want entity extraction and knowledge graph
- Require cross-article intelligence
- Cost is less important than quality

---

## Dependencies

### Internal
- `src/config.py`: AIConfig
- `src/models/article.py`: Article, AnalyzedArticle

### External
- `openai`: AsyncOpenAI client
- `pydantic`: Data validation
- `structlog`: Logging
- `json`, `re`: Parsing

---

## Configuration

```yaml
ai:
  provider: deepseek
  api_key: ${DEEPSEEK_API_KEY}
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  max_tokens: 8000
  temperature: 0.3

  # Batch settings
  batch_size: 20  # Articles per LLM call

  # Filtering
  min_score: 5.0  # Filter threshold

  # Top picks
  top_pick_count: 5
```

---

## Summary

The AI module provides a **fast, cost-effective legacy approach** to article analysis:

**Strengths**:
- ✅ Simple and fast (1-2s per article)
- ✅ Low cost (1-2K tokens per article)
- ✅ Batch processing for efficiency
- ✅ Robust fallback mechanisms
- ✅ History-aware duplication avoidance

**Limitations**:
- ❌ Less sophisticated than multi-agent
- ❌ No entity extraction or knowledge graph
- ❌ No cross-article intelligence
- ❌ Single-pass analysis (no reflection)

**Best Use Cases**:
- Quick content filtering
- Budget-constrained deployments
- Simple newsletter curation
- Legacy compatibility

For advanced use cases, consider migrating to the **modern multi-agent system** in `src/agents/`.
