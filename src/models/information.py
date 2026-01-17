"""Information Unit Models - 信息为中心架构的核心模型"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from .analysis import Entity


class InformationType(str, Enum):
    """信息单元类型"""
    FACT = "fact"         # 事实类：公告、声明、法规
    OPINION = "opinion"   # 观点类：分析、预测、评论
    EVENT = "event"       # 事件类：交易、发布、合作
    DATA = "data"         # 数据类：财务数据、市场统计


class StateChangeType(str, Enum):
    """HEX 状态改变类型 - 六维分类"""
    TECH = "TECH"               # 🧬 技术与产品突变
    CAPITAL = "CAPITAL"         # 💰 资本与市场流动
    REGULATION = "REGULATION"   # ⚖️ 规则与环境约束
    ORG = "ORG"                  # 👔 组织与人事重组
    RISK = "RISK"               # ⚠️ 风险与危机事件
    SENTIMENT = "SENTIMENT"     # 🗣️ 共识与情绪转向


# L3 母实体预设列表 (Root Entities)
ROOT_ENTITIES = [
    # 科技
    "人工智能",
    "半导体芯片",
    "消费电子",
    "云计算与数据中心",
    "软件与开发工具",
    "区块链与加密货币",
    "网络安全",
    # 互联网
    "电商与零售",
    "社交媒体",
    "游戏与娱乐",
    "内容与流媒体",
    # 传统行业
    "金融与银行",
    "汽车与出行",
    "能源与环境",
    "医疗与生物科技",
    "制造与工业",
    # 宏观
    "宏观经济",
    "地缘政治",
]


class EntityAnchor(BaseModel):
    """三级实体锚定 - 用于层级检索"""
    l1_name: str              # 叶子实体 (DeepSeek, NVIDIA)
    l1_role: str = "主角"     # 角色: 主角/配角/提及
    l2_sector: str            # 细分领域 (基础模型, AI芯片)
    l3_root: str              # 母实体 (人工智能, 半导体芯片)
    confidence: float = 0.8   # 归类置信度


class SourceReference(BaseModel):
    """来源引用 - 追踪信息的原始出处"""
    url: str
    title: str
    source_name: str
    published_at: Optional[datetime] = None
    excerpt: str = ""                    # 相关摘录
    credibility_tier: str = "unknown"    # 信源可信度等级
    
    def __eq__(self, other):
        if isinstance(other, SourceReference):
            return self.url == other.url
        return False
        
    def __hash__(self):
        return hash(self.url)


class InformationUnit(BaseModel):
    """信息单元 - 发送给用户的最小数据单位"""
    
    # === 唯一标识 ===
    id: str                          # 基于内容的哈希 ID
    fingerprint: str                 # 语义指纹（用于去重）
    
    # === 核心内容 ===
    type: InformationType            # 信息类型
    title: str                       # 信息标题（简洁）
    content: str                     # 信息内容（详细，包含事实与背景）
    summary: str = ""                # 一句话核心摘要
    
    # === 时间信息 ===
    event_time: Optional[str] = None       # 事件发生时间（如"2026年1月15日"）
    report_time: Optional[datetime] = None # 报道/发布时间
    time_sensitivity: str = "normal"       # 时效性: urgent/normal/evergreen
    
    # === 深度分析 (增强版) ===
    analysis_content: str = ""       # 专属分析板块：包含深度解读、趋势预测、矛盾点分析
    key_insights: List[str] = Field(default_factory=list)  # 关键洞察
    analysis_depth_score: float = 0.0 # 分析深度评分 (0-1) 用于筛选
    
    # === 4维价值评估 (0-10) ===
    information_gain: float = 5.0     # 信息增量：是否打破已知共识
    actionability: float = 5.0        # 行动指导性：是否能指导具体决策
    scarcity: float = 5.0             # 稀缺性：是否为一手信源
    impact_magnitude: float = 5.0     # 影响范围：涉及实体的权重
    
    # === HEX 状态分类 ===
    state_change_type: str = ""       # 主分类: TECH/CAPITAL/REGULATION/ORG/RISK/SENTIMENT
    state_change_subtypes: List[str] = Field(default_factory=list)  # 子分类: ["产品发布", "版本迭代"]
    
    # === 三级实体锚定 ===
    entity_hierarchy: List[EntityAnchor] = Field(default_factory=list)  # 支持多实体多归属
    
    # === 5W1H 结构化 ===
    who: List[str] = Field(default_factory=list)
    what: str = ""
    when: str = ""
    where: str = ""
    why: str = ""
    how: str = ""
    
    # === 来源追溯 ===
    sources: List[SourceReference] = Field(default_factory=list)
    primary_source: str = ""         # 主要来源 URL
    extraction_confidence: float = 0.0
    
    # === 分析结果 ===
    credibility_score: float = 0.0
    importance_score: float = 0.0
    sentiment: str = "neutral"       # positive/neutral/negative
    impact_assessment: str = ""
    
    # === 关联信息 ===
    related_unit_ids: List[str] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    
    # === 元数据 ===
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    merged_count: int = 1            # 合并了多少条相似信息
    is_sent: bool = False            # 是否已发送过
    
    @property
    def value_score(self) -> float:
        """综合价值评分 (0-10): 四维加权平均"""
        # 权重: 信息增量 30%, 行动指导 25%, 稀缺性 20%, 影响范围 25%
        return (
            self.information_gain * 0.30 +
            self.actionability * 0.25 +
            self.scarcity * 0.20 +
            self.impact_magnitude * 0.25
        )
    
    @property
    def source_count(self) -> int:
        return len(self.sources)
    
    def merge_source(self, new_source: SourceReference):
        """添加新的来源引用"""
        for source in self.sources:
            if source.url == new_source.url:
                return
        self.sources.append(new_source)
