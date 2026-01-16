"""文章数据模型"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from .analysis import (
    Entity,
    SourceCredibility,
    BiasAnalysis,
    FactCheckResult,
    ImpactAnalysis,
    RiskWarning,
    SentimentAnalysis,
    MarketSentiment,
    KnowledgeGraph,
    TimelineEvent,
)
from .agent import AgentTrace


class Article(BaseModel):
    """基础文章模型"""
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
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        if isinstance(other, Article):
            return self.url == other.url
        return False


class EnrichedArticle(BaseModel):
    """
    经过多智能体分析的增强文章
    
    包含 6 个层面的深度洞察：
    1. 基础层：5W1H 信息提炼
    2. 验证层：可信度与立场分析
    3. 深度层：背景与关联
    4. 情绪层：舆情与市场情绪
    5. 推理层：影响分析与预测
    6. 行动层：决策建议
    """
    
    # === 基础信息 ===
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
    
    # === 基础层分析 (5W1H) ===
    who: list[str] = Field(default_factory=list)  # 涉及的人物/组织
    what: str = ""  # 发生了什么
    when: str = ""  # 时间
    where: str = ""  # 地点
    why: str = ""   # 原因
    how: str = ""   # 过程/方式
    entities: list[Entity] = Field(default_factory=list)  # 识别的实体
    timeline: list[TimelineEvent] = Field(default_factory=list)  # 时间线
    
    # === 验证层分析 ===
    source_credibility: Optional[SourceCredibility] = None
    bias_analysis: Optional[BiasAnalysis] = None
    fact_check: Optional[FactCheckResult] = None
    clickbait_score: float = 0.0  # 标题党评分 (0-1)
    
    # === 深度层分析 ===
    historical_context: str = ""  # 历史背景
    knowledge_graph: Optional[KnowledgeGraph] = None
    cross_language_comparison: dict = Field(default_factory=dict)
    
    # === 情绪层分析 ===
    public_sentiment: Optional[SentimentAnalysis] = None
    market_sentiment: Optional[MarketSentiment] = None
    
    # === 推理层分析 ===
    impact_analysis: Optional[ImpactAnalysis] = None
    risk_warnings: list[RiskWarning] = Field(default_factory=list)
    
    # === 行动层分析 ===
    recommendations: dict[str, list[str]] = Field(default_factory=dict)
    # 格式: {"investor": ["建议1", "建议2"], "general": [...], "business": [...]}
    
    # === 元数据 ===
    overall_score: float = 0.0  # 综合评分 (1-10)
    is_top_pick: bool = False
    ai_summary: str = ""  # AI 生成的核心摘要
    tags: list[str] = Field(default_factory=list)  # 多层级标签
    analysis_timestamp: datetime = Field(default_factory=datetime.now)
    analysis_mode: str = "deep"  # quick, standard, deep
    agent_traces: list[AgentTrace] = Field(default_factory=list)
    
    @property
    def tags_display(self) -> str:
        """标签显示格式"""
        return " > ".join(self.tags) if self.tags else self.category
    
    def get_impact_summary(self) -> str:
        """获取影响分析摘要"""
        if not self.impact_analysis:
            return "暂无影响分析"
        
        parts = []
        if self.impact_analysis.direct_impact:
            parts.append(f"直接影响: {len(self.impact_analysis.direct_impact)} 项")
        if self.impact_analysis.second_order_impact:
            parts.append(f"二阶影响: {len(self.impact_analysis.second_order_impact)} 项")
        if self.impact_analysis.third_order_impact:
            parts.append(f"三阶影响: {len(self.impact_analysis.third_order_impact)} 项")
        
        return " | ".join(parts) if parts else "暂无影响分析"
    
    def to_digest_format(self) -> dict:
        """转换为简报格式"""
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "score": self.overall_score,
            "summary": self.ai_summary,
            "tags": self.tags,
            "is_top_pick": self.is_top_pick,
            "impact_summary": self.get_impact_summary(),
            "recommendations": self.recommendations,
            "risk_warnings": [w.model_dump() for w in self.risk_warnings],
        }
    
    @classmethod
    def from_article(cls, article: Article) -> "EnrichedArticle":
        """从基础文章创建增强文章"""
        return cls(
            id=article.id,
            url=article.url,
            title=article.title,
            content=article.content,
            summary=article.summary,
            source=article.source,
            category=article.category,
            author=article.author,
            published_at=article.published_at,
            fetched_at=article.fetched_at,
        )
