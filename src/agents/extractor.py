"""Information Extractor Agent - 信息提取专家"""

import json
import hashlib
from typing import List
import structlog

from .base import BaseAgent
from ..models.article import Article
from ..models.information import InformationUnit, InformationType, SourceReference
from ..models.agent import AgentContext, AgentOutput
from ..models.analysis import Entity

logger = structlog.get_logger()

EXTRACTOR_SYSTEM_PROMPT = """你是一位专业的情报提取与分析专家。你的任务是将输入的新闻文章拆解为多个独立的、高价值的"信息单元" (Information Units)。

## 什么是信息单元？
信息单元是发送给用户的最小数据单位。它应当是原子的、独立的，并且包含深度分析。

## 你的职责
1. **原子拆分**：识别文章中包含的独立事实、事件或观点
2. **时间标注**：明确标注事件发生时间
3. **状态分类**：识别这是哪种类型的状态改变
4. **实体锚定**：将实体归类到预设的母实体下
5. **价值评估**：进行4维价值评估

## 输出要求 (JSON 列表)

### 基础字段
- `type`: fact(事实), opinion(观点), event(事件), data(数据)
- `title`: 简练标题（20字以内）
- `content`: 详细内容（200字左右）
- `summary`: 一句话摘要（50字以内）

### ⏰ 时间字段
- `event_time`: 事件发生时间（如"2026年1月15日"）
- `time_sensitivity`: urgent / normal / evergreen

### 📊 4维价值评估（1-10分）
- `information_gain`: 信息增量（10=颠覆共识，5=符合预期，2=废话）
- `actionability`: 行动指导（10=明确参数，5=有参考，2=纯情绪）
- `scarcity`: 稀缺性（10=一手信源，5=权威引用，2=转述）
- `impact_magnitude`: 影响范围（10=核心玩家，5=行业龙头，2=边缘）

### 🏷️ HEX 状态分类（必填！）
从以下 6 类中选择最匹配的 **1 个**作为 `state_change_type`:
- `TECH`: 🧬 技术/产品变化（发布、迭代、突破、专利）
- `CAPITAL`: 💰 资本/市场变化（融资、财报、并购、股价）
- `REGULATION`: ⚖️ 规则/政策变化（法规、制裁、反垄断、合规）
- `ORG`: 👔 组织/人事变化（高管、裁员、架构调整）
- `RISK`: ⚠️ 风险/危机事件（黑客、宕机、丑闻、事故）
- `SENTIMENT`: 🗣️ 共识/情绪变化（评级、舆论反转、关键表态）

同时提供 `state_change_subtypes` 列表（如 ["产品发布", "版本迭代"]）

### 🎯 三级实体锚定（必填！）
为新闻中的**主角实体**生成三级标签，输出到 `entity_hierarchy` 列表：

**L3 母实体 (l3_root)** - 必须从以下预设列表选择:
人工智能, 半导体芯片, 消费电子, 云计算与数据中心, 软件与开发工具, 区块链与加密货币, 网络安全, 电商与零售, 社交媒体, 游戏与娱乐, 内容与流媒体, 金融与银行, 汽车与出行, 能源与环境, 医疗与生物科技, 制造与工业, 宏观经济, 地缘政治

**L2 细分领域 (l2_sector)** - 自由生成，描述实体在行业中的位置（如"基础模型"、"AI芯片"）

**L1 叶子实体 (l1_name)** - 新闻中出现的具体名称

**注意**：如果一个实体跨越多个母实体（如 NVIDIA 既是AI也是半导体），生成多条记录。

### 分析字段
- `analysis_content`: 深度解读（100-200字）
- `key_insights`: [洞察1, 洞察2...] (3-5个)
- `analysis_depth_score`: 0.0-1.0

### 5W1H 结构化
- `who`, `what`, `when`, `where`, `why`, `how`

### 元数据
- `extraction_confidence`, `credibility_score`, `importance_score`
- `sentiment`, `impact_assessment`, `entities`, `tags`

## 输出示例
```json
{
  "type": "event",
  "title": "英伟达发布RTX5090",
  "state_change_type": "TECH",
  "state_change_subtypes": ["产品发布"],
  "entity_hierarchy": [
    {"l1_name": "NVIDIA", "l1_role": "主角", "l2_sector": "消费级GPU", "l3_root": "半导体芯片"},
    {"l1_name": "NVIDIA", "l1_role": "主角", "l2_sector": "AI芯片", "l3_root": "人工智能"}
  ],
  "event_time": "2026年1月17日",
  "information_gain": 8,
  "actionability": 9,
  "scarcity": 9,
  "impact_magnitude": 9
}
```

## 注意事项
- 论坛帖子、技术问答等非新闻内容，4维评分应偏低（≤4）
- 分析内容必须有实质性，避免废话
"""

class InformationExtractorAgent(BaseAgent):
    """
    信息提取 Agent
    
    职责：
    1. 将 Article 拆解为 List[InformationUnit]
    2. 生成初步的深度分析
    """
    
    AGENT_NAME = "Extractor"
    SYSTEM_PROMPT = EXTRACTOR_SYSTEM_PROMPT
    
    async def process(self, input_data: Article, context: AgentContext) -> AgentOutput:
        """执行提取任务"""
        article = input_data
        self.log_start(article.title)
        
        user_prompt = f"""
        请分析以下文章，提取信息单元：

        标题: {article.title}
        来源: {article.source}
        发布时间: {article.published_at}
        内容:
        {article.content}
        """
        
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=4000,
            temperature=0.3,
            json_mode=True
        )
        
        units = []
        if result and isinstance(result, list):
            for item in result:
                try:
                    unit = self._parse_unit(item, article)
                    units.append(unit)
                except Exception as e:
                    logger.error("unit_parsing_failed", error=str(e), item_summary=str(item)[:100])
        
        trace = self.create_trace(
            input_summary=f"Article: {article.title}",
            output_summary=f"Extracted {len(units)} units",
            duration=0, 
            token_usage=token_usage
        )
        
        self.log_complete(0, f"Units: {len(units)}")
        return AgentOutput(success=True, data=units, trace=trace)
        
    async def extract(self, article: Article, context: AgentContext) -> List[InformationUnit]:
        """Deprecated alias for process"""
        output = await self.process(article, context)
        return output.data

    def _parse_unit(self, item: dict, article: Article) -> InformationUnit:
        """解析 LLM 返回的 JSON 为 InformationUnit 对象"""
        from ..models.information import EntityAnchor, ROOT_ENTITIES
        
        # 生成指纹 (Content Based Hash)
        content_str = f"{item.get('title', '')}{item.get('content', '')}"
        fingerprint = hashlib.md5(content_str.encode()).hexdigest()
        
        # 生成 ID
        unit_id = f"iu_{fingerprint[:16]}"
        
        # 处理实体
        entities = []
        for e in item.get("entities", []):
            if isinstance(e, dict):
                entities.append(Entity(
                    name=e.get("name", ""),
                    type=e.get("type", "unknown"),
                    description=e.get("description", "")
                ))
        
        # 处理实体锚定
        entity_hierarchy = []
        for eh in item.get("entity_hierarchy", []):
            if isinstance(eh, dict):
                l3_root = eh.get("l3_root", "")
                # 验证 L3 是否在预设列表中
                if l3_root and l3_root not in ROOT_ENTITIES:
                    # 尝试模糊匹配
                    for root in ROOT_ENTITIES:
                        if l3_root in root or root in l3_root:
                            l3_root = root
                            break
                    else:
                        l3_root = "其他"  # 默认归类
                
                entity_hierarchy.append(EntityAnchor(
                    l1_name=eh.get("l1_name", ""),
                    l1_role=eh.get("l1_role", "主角"),
                    l2_sector=eh.get("l2_sector", ""),
                    l3_root=l3_root,
                    confidence=float(eh.get("confidence", 0.8))
                ))
        
        # 构建来源引用
        source_ref = SourceReference(
            url=article.url,
            title=article.title,
            source_name=article.source,
            published_at=article.published_at,
            excerpt=article.summary[:200] if article.summary else "",
            credibility_tier="unknown"
        )
        
        # 处理4维评分
        def safe_score(val, default=5.0):
            try:
                score = float(val) if val else default
                return max(1.0, min(10.0, score))
            except:
                return default
        
        # 验证 HEX 状态类型
        state_type = item.get("state_change_type", "")
        valid_types = ["TECH", "CAPITAL", "REGULATION", "ORG", "RISK", "SENTIMENT"]
        if state_type not in valid_types:
            state_type = ""
        
        return InformationUnit(
            id=unit_id,
            fingerprint=fingerprint,
            type=InformationType(item.get("type", "fact")),
            title=item.get("title", "") or article.title,
            content=item.get("content", "") or article.content,
            summary=item.get("summary", ""),
            
            # 时间字段
            event_time=item.get("event_time") or item.get("when") or None,
            report_time=article.published_at,
            time_sensitivity=item.get("time_sensitivity", "normal"),
            
            # 分析字段
            analysis_content=item.get("analysis_content", ""),
            key_insights=item.get("key_insights", []),
            analysis_depth_score=float(item.get("analysis_depth_score", 0.5)),
            
            # 4维价值评分
            information_gain=safe_score(item.get("information_gain"), 5.0),
            actionability=safe_score(item.get("actionability"), 5.0),
            scarcity=safe_score(item.get("scarcity"), 5.0),
            impact_magnitude=safe_score(item.get("impact_magnitude"), 5.0),
            
            # HEX 状态分类
            state_change_type=state_type,
            state_change_subtypes=item.get("state_change_subtypes", []) if isinstance(item.get("state_change_subtypes"), list) else [],
            
            # 三级实体锚定
            entity_hierarchy=entity_hierarchy,
            
            # 5W1H (处理可能是字符串或列表的情况)
            who=item.get("who", []) if isinstance(item.get("who"), list) else [item.get("who")] if item.get("who") else [],
            what=item.get("what", "") if isinstance(item.get("what"), str) else str(item.get("what", "")),
            when=item.get("when", "") if isinstance(item.get("when"), str) else str(item.get("when", "")),
            where=item.get("where", "") if isinstance(item.get("where"), str) else str(item.get("where", "")),
            why=item.get("why", "") if isinstance(item.get("why"), str) else str(item.get("why", "")),
            how=item.get("how", "") if isinstance(item.get("how"), str) else str(item.get("how", "")),
            
            # 来源
            primary_source=article.url,
            extraction_confidence=float(item.get("extraction_confidence", 0.8)),
            
            # 分析结果
            credibility_score=float(item.get("credibility_score", 0.5)),
            importance_score=float(item.get("importance_score", 0.5)),
            sentiment=item.get("sentiment", "neutral"),
            impact_assessment=item.get("impact_assessment", ""),
            
            # 元数据
            entities=entities,
            tags=item.get("tags", []),
            created_at=article.fetched_at,
            sources=[source_ref]
        )

