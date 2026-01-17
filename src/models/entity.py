"""Entity Models - 实体知识图谱数据模型"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid


class EntityType(str, Enum):
    """实体类型"""
    COMPANY = "COMPANY"       # 公司
    PERSON = "PERSON"         # 人物
    PRODUCT = "PRODUCT"       # 产品
    ORG = "ORG"               # 组织/机构
    CONCEPT = "CONCEPT"       # 概念
    LOCATION = "LOCATION"     # 地点
    EVENT = "EVENT"           # 事件


class RelationType(str, Enum):
    """关系类型"""
    # 层级关系
    PARENT_OF = "parent_of"          # A 包含 B
    SUBSIDIARY_OF = "subsidiary_of"  # A 是 B 的子公司
    
    # 并列关系
    COMPETITOR = "competitor"        # 竞争对手
    PARTNER = "partner"              # 合作伙伴
    PEER = "peer"                    # 同行
    
    # 依赖关系
    SUPPLIER = "supplier"            # A 是 B 的供应商
    CUSTOMER = "customer"            # A 是 B 的客户
    INVESTOR = "investor"            # A 投资了 B
    
    # 人物关系
    CEO_OF = "ceo_of"                # A 是 B 的CEO
    FOUNDER_OF = "founder_of"        # A 创立了 B
    EMPLOYEE_OF = "employee_of"      # A 在 B 工作


class Entity(BaseModel):
    """实体 - 知识图谱的节点"""
    id: str = Field(default_factory=lambda: f"entity_{uuid.uuid4().hex[:12]}")
    canonical_name: str              # 标准名称
    type: EntityType                 # 类型
    l3_root: str = ""                # L3母实体
    l2_sector: str = ""              # L2领域
    attributes: Dict[str, Any] = Field(default_factory=dict)
    
    # 统计
    mention_count: int = 0
    first_mentioned: Optional[datetime] = None
    last_mentioned: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)


class EntityAlias(BaseModel):
    """实体别名"""
    alias: str                       # 别名（作为主键）
    entity_id: str                   # 关联的实体ID
    is_primary: bool = False         # 是否为主名称
    source: str = "ai"               # 来源: ai/manual
    created_at: datetime = Field(default_factory=datetime.now)


class EntityMention(BaseModel):
    """实体提及 - 实体与信息单元的关联"""
    id: str = Field(default_factory=lambda: f"mention_{uuid.uuid4().hex[:12]}")
    entity_id: str                   # 关联的实体ID
    unit_id: str                     # 关联的信息单元ID
    
    role: str = "主角"               # 主角/配角/提及
    sentiment: str = "neutral"       # positive/neutral/negative
    state_dimension: str = ""        # TECH/CAPITAL/REGULATION/ORG/RISK/SENTIMENT
    state_delta: str = ""            # 变化描述
    
    event_time: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)


class EntityRelation(BaseModel):
    """实体关系 - 知识图谱的边"""
    id: str = Field(default_factory=lambda: f"rel_{uuid.uuid4().hex[:12]}")
    source_id: str                   # 源实体ID
    target_id: str                   # 目标实体ID
    relation_type: RelationType
    
    strength: float = 1.0            # 关系强度 (0-1)
    confidence: float = 0.8          # 置信度
    evidence_unit_ids: List[str] = Field(default_factory=list)
    
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)


class ExtractedEntity(BaseModel):
    """从文本中提取的实体信息（用于Extractor输出）"""
    name: str                        # 原文中的名称
    aliases: List[str] = Field(default_factory=list)  # 可能的别名
    type: str = "COMPANY"            # 类型
    role: str = "主角"               # 角色
    state_change: Optional[Dict[str, str]] = None  # {"dimension": "TECH", "delta": "..."}


class ExtractedRelation(BaseModel):
    """从文本中提取的关系信息"""
    source: str                      # 源实体名
    target: str                      # 目标实体名
    relation: str                    # 关系类型
    evidence: str = ""               # 支撑该关系的原文片段
