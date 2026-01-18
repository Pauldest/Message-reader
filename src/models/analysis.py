"""分析结果数据模型"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class SimpleEntity(BaseModel):
    """识别的简单实体 (用于分析输出，避免与 entity.Entity 冲突)"""
    name: str
    type: str  # PERSON, COMPANY, PRODUCT, LOCATION, LAW, EVENT, etc.
    description: str = ""
    related_entities: list[str] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    """时间线事件"""
    time: str
    event: str
    importance: str = "normal"  # low, normal, high


class SourceCredibility(BaseModel):
    """信源可信度"""
    source_name: str
    credibility_score: float = 5.0  # 0-10
    tier: str = "未知"  # "权威官媒", "主流媒体", "行业媒体", "自媒体", "未知"
    historical_accuracy: str = ""
    known_biases: list[str] = Field(default_factory=list)
    reasoning: str = ""


class BiasAnalysis(BaseModel):
    """立场/偏见分析"""
    political_leaning: str = "center"  # left, center-left, center, center-right, right
    emotional_tone: str = "objective"  # objective, sensational, fear-mongering, optimistic, pessimistic
    bias_indicators: list[str] = Field(default_factory=list)  # 偏见措辞示例
    objectivity_score: float = 5.0  # 0-10, 10 为最客观
    reasoning: str = ""


class FactCheckResult(BaseModel):
    """事实核查结果"""
    verification_status: str = "unverified"  # verified, disputed, unverified, single_source
    corroborating_sources: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    notes: str = ""


class Impact(BaseModel):
    """单个影响"""
    description: str
    affected_entities: list[str] = Field(default_factory=list)
    direction: str = "neutral"  # positive, negative, neutral
    magnitude: str = "medium"   # low, medium, high
    confidence: float = 0.5
    reasoning: str = ""


class ImpactAnalysis(BaseModel):
    """影响分析（多层次）"""
    direct_impact: list[Impact] = Field(default_factory=list)  # 直接影响
    second_order_impact: list[Impact] = Field(default_factory=list)  # 二阶影响
    third_order_impact: list[Impact] = Field(default_factory=list)  # 三阶影响
    summary: str = ""


class RiskWarning(BaseModel):
    """风险预警"""
    risk_type: str  # black_swan, gray_rhino, policy, market, technology, geopolitical
    description: str
    probability: str = "medium"  # low, medium, high
    severity: str = "medium"     # low, medium, high, critical
    affected_areas: list[str] = Field(default_factory=list)
    mitigation_suggestions: list[str] = Field(default_factory=list)


class SentimentAnalysis(BaseModel):
    """情绪分析"""
    overall_sentiment: str = "neutral"  # very_negative, negative, neutral, positive, very_positive
    sentiment_score: float = 0.0  # -1.0 to 1.0
    emotions: dict[str, float] = Field(default_factory=dict)  # {"fear": 0.3, "anger": 0.2, ...}
    key_phrases: list[str] = Field(default_factory=list)  # 关键情绪短语
    reasoning: str = ""


class MarketSentiment(BaseModel):
    """市场情绪（财经相关）"""
    overall: str = "neutral"  # bullish, bearish, neutral
    confidence: float = 0.5
    affected_sectors: list[str] = Field(default_factory=list)
    affected_tickers: list[str] = Field(default_factory=list)
    expected_reaction: str = ""  # 预期市场反应描述
    time_horizon: str = "short_term"  # short_term, medium_term, long_term
    reasoning: str = ""


class KnowledgeGraphNode(BaseModel):
    """知识图谱节点"""
    id: str
    name: str
    type: str
    properties: dict = Field(default_factory=dict)


class KnowledgeGraphEdge(BaseModel):
    """知识图谱边"""
    source: str  # 源节点 ID
    target: str  # 目标节点 ID
    relation: str  # 关系类型
    properties: dict = Field(default_factory=dict)


class KnowledgeGraph(BaseModel):
    """知识图谱"""
    nodes: list[KnowledgeGraphNode] = Field(default_factory=list)
    edges: list[KnowledgeGraphEdge] = Field(default_factory=list)
    
    def add_entity(self, entity: Entity) -> str:
        """添加实体节点"""
        node_id = f"{entity.type}_{entity.name}".replace(" ", "_")
        self.nodes.append(KnowledgeGraphNode(
            id=node_id,
            name=entity.name,
            type=entity.type,
            properties={"description": entity.description}
        ))
        return node_id
    
    def add_relation(self, source_id: str, target_id: str, relation: str):
        """添加关系边"""
        self.edges.append(KnowledgeGraphEdge(
            source=source_id,
            target=target_id,
            relation=relation
        ))
    
    def to_mermaid(self) -> str:
        """转换为 Mermaid 图表格式"""
        lines = ["graph LR"]
        for node in self.nodes:
            lines.append(f'    {node.id}["{node.name}"]')
        for edge in self.edges:
            lines.append(f'    {edge.source} -->|{edge.relation}| {edge.target}')
        return "\n".join(lines)
