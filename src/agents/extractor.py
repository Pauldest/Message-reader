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
1. **原子拆分**：识别文章中包含的独立事实、事件或观点。如果一篇文章报道了我们可以拆分的两个不同话题（例如"公司A发布新产品"和"公司A财报超预期"），请将其拆分为两个独立的信息单元。
2. **深度提取**：不仅仅提取表面事实，更要提取背景、影响和深层含义。
3. **分析生成**：利用你的知识库，对提取的信息进行初步分析（影响评估、趋势预测、风险提示）。

## 输出要求
请输出一个 JSON 列表，每个元素包含以下字段：
- `type`: fact(事实), opinion(观点), event(事件), data(数据)
- `title`: 简练的标题（20字以内）
- `content`: 详细的内容描述（包含事实经过、背景信息，200字左右）
- `summary`: 一句话核心摘要（50字以内）
- `analysis_content`: **分析板块**（非常重要！）。包含深度解读、趋势预测、矛盾点分析、潜在影响。
- `key_insights`: [关键洞察1, 关键洞察2...] (3-5个深度观点)
- `analysis_depth_score`: 0.0-1.0 (自我评估这条信息的分析深度和价值)
- `who`: [涉及人物/组织...]
- `what`: 发生了什么
- `when`: 时间
- `where`: 地点
- `why`: 原因
- `how`: 方式/过程
- `extraction_confidence`: 0.0-1.0 (提取置信度)
- `credibility_score`: 0.0-1.0 (内容可信度评估)
- `importance_score`: 0.0-1.0 (重要性评估)
- `sentiment`: positive/neutral/negative
- `impact_assessment`: 简述对行业/市场/社会的潜在影响
- `entities`: [{"name": "实体名", "type": "类型", "description": "描述"}, ...]
- `tags`: [标签1, 标签2...]

## 注意事项
- 尽量保留原文的关键细节和数据。
- 分析内容 (`analysis_content`) 必须有实质性，避免废话。
- 如果文章只包含一个核心信息，则输出一个单元；如果包含多个，则输出多个。
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
        
        # 生成指纹 (Content Based Hash)
        # 使用 title + content 的哈希作为简易指纹，实际生产中可能需要更复杂的语义指纹
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
        
        # 构建来源引用
        source_ref = SourceReference(
            url=article.url,
            title=article.title,
            source_name=article.source,
            published_at=article.published_at,
            excerpt=article.summary[:200], # 暂时使用 summary 作为摘录
            credibility_tier="unknown" # 待后续分析填充
        )
        
        return InformationUnit(
            id=unit_id,
            fingerprint=fingerprint,
            type=InformationType(item.get("type", "fact")),
            title=item.get("title", "") or article.title,
            content=item.get("content", "") or article.content,
            summary=item.get("summary", ""),
            analysis_content=item.get("analysis_content", ""),
            key_insights=item.get("key_insights", []),
            analysis_depth_score=float(item.get("analysis_depth_score", 0.5)),
            who=item.get("who", []),
            what=item.get("what", ""),
            when=item.get("when", ""),
            where=item.get("where", ""),
            why=item.get("why", ""),
            how=item.get("how", ""),
            primary_source=article.url,
            extraction_confidence=float(item.get("extraction_confidence", 0.8)),
            credibility_score=float(item.get("credibility_score", 0.5)),
            importance_score=float(item.get("importance_score", 0.5)),
            sentiment=item.get("sentiment", "neutral"),
            impact_assessment=item.get("impact_assessment", ""),
            entities=entities,
            tags=item.get("tags", []),
            created_at=article.fetched_at,
            sources=[source_ref]
        )
