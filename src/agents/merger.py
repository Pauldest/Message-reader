"""Information Merger Agent - 信息整合专家"""

import json
from typing import List
import structlog

from .base import BaseAgent
from ..models.information import InformationUnit, InformationType, SourceReference
from ..models.agent import AgentContext, AgentOutput

logger = structlog.get_logger()

MERGER_SYSTEM_PROMPT = """你是一位信息整合与分析专家。你的任务是将多个来源关于同一主题的"信息单元"合并为一个最完整、最准确、最具有深度的版本。

## 你的目标
创建一个单一的、权威的信息单元，它集合了所有输入单元的优点，同时消除了冗余。

## 核心职责
1. **事实整合**：综合所有输入中的事实细节。如果来源A提供了时间，来源B提供了地点，合并后的版本应包含两者。
2. **冲突处理**：如果不同来源存在事实冲突（例如数据、日期不一致），请在内容中明确指出冲突，并说明各个来源的说法。
3. **深度分析升级**：不要简单拼接分析内容。请重新组织 `analysis_content`，将不同角度的观点融合为一篇连贯的深度分析。优先保留有洞察力、前瞻性的观点。
4. **元数据优化**：
    - 重新评估 `credibility_score`（多源验证通常应提高可信度）。
    - 重新评估 `analysis_depth_score`（内容越丰富，深度应越高）。

## 输出要求
请输出一个 JSON 对象（与单个 InformationUnit 结构兼容）：
- `type`: 保持一致
- `title`: 最准确、最吸引人的标题
- `content`: 综合后的详细内容（包含事实冲突说明）
- `summary`: 综合摘要
- `analysis_content`: **融合后的深度分析**
- `key_insights`: [整合后的关键洞察...]
- `analysis_depth_score`: 0.0-1.0
- `who`, `what`, `when`, `where`, `why`, `how`: 综合后的 5W1H
- `credibility_score`: 重新评估的分数
- `importance_score`: 重新评估的分数
- `impact_assessment`: 综合影响评估
- `sentiment`: 综合情绪
- `entities`: 合并去重后的实体列表
- `tags`: 合并去重后的标签列表

## 注意
- 输入给你的是一组 JSON 格式的信息单元。
- 请忽略 `sources` 和 `id` 字段的合并，这部分由系统处理。专注于内容层面的合并。
"""

class InformationMergerAgent(BaseAgent):
    """
    信息整合 Agent
    
    职责：
    1. 合并多个相似的 InformationUnit
    2. 解决冲突，提升分析深度
    """
    
    AGENT_NAME = "Merger"
    SYSTEM_PROMPT = MERGER_SYSTEM_PROMPT
    
    async def process(self, input_data: List[InformationUnit], context: AgentContext = None) -> AgentOutput:
        """执行合并任务"""
        units = input_data
        if not units:
            raise ValueError("No units to merge")
            
        merged_unit = await self.merge(units)
        return AgentOutput(success=True, data=merged_unit, trace=None)

    async def merge(self, units: List[InformationUnit]) -> InformationUnit:
        """执行合并任务 (Internal)"""
        if not units:
            raise ValueError("No units to merge")
        
        if len(units) == 1:
            return units[0]
            
        # 选取基础单元（通常是第一个或者最长的一个）
        base_unit = units[0]
        self.log_start(f"Merging {len(units)} units based on {base_unit.title}")
        
        # 准备 Prompt 输入
        units_json = []
        for u in units:
            units_json.append({
                "title": u.title,
                "content": u.content,
                "analysis_content": u.analysis_content,
                "key_insights": u.key_insights,
                "source_count": u.source_count,
                "credibility": u.credibility_score
            })
            
        user_prompt = f"""
        请合并以下 {len(units)} 个信息单元：
        
        {json.dumps(units_json, ensure_ascii=False, indent=2)}
        """
        
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=2000,
            temperature=0.2, # 降低温度以保证准确性
            json_mode=True
        )
        
        merged_unit = base_unit # Fallback
        
        if result and isinstance(result, dict):
            try:
                # 重新构建 InformationUnit，保留 base_unit 的 ID 和 Fingerprint (或者生成新的？)
                # 策略：保留 ID，更新内容。Sources 将在外部合并。
                merged_unit = base_unit.model_copy(update={
                    "title": result.get("title", base_unit.title),
                    "content": result.get("content", base_unit.content),
                    "summary": result.get("summary", base_unit.summary),
                    "analysis_content": result.get("analysis_content", base_unit.analysis_content),
                    "key_insights": result.get("key_insights", base_unit.key_insights),
                    "analysis_depth_score": float(result.get("analysis_depth_score", base_unit.analysis_depth_score)),
                    "who": result.get("who", base_unit.who),
                    "what": result.get("what", base_unit.what),
                    "when": result.get("when", base_unit.when),
                    "where": result.get("where", base_unit.where),
                    "why": result.get("why", base_unit.why),
                    "how": result.get("how", base_unit.how),
                    "credibility_score": float(result.get("credibility_score", base_unit.credibility_score)),
                    "importance_score": float(result.get("importance_score", base_unit.importance_score)),
                    "impact_assessment": result.get("impact_assessment", base_unit.impact_assessment),
                    "sentiment": result.get("sentiment", base_unit.sentiment),
                    # entities 和 tags 简单合并去重
                    "tags": list(set(base_unit.tags + result.get("tags", []))),
                    "merged_count": sum(u.merged_count for u in units) # 累加合并计数
                })
                
                # 合并 Entities (需要更复杂的逻辑，这里简化处理：优先使用新结果， fallback 到旧的)
                # TODO: 实体去重
                
            except Exception as e:
                logger.error("merge_parsing_failed", error=str(e))
        
        # 合并所有 Sources
        all_sources = []
        seen_urls = set()
        for u in units:
            for s in u.sources:
                if s.url not in seen_urls:
                    all_sources.append(s)
                    seen_urls.add(s.url)
        merged_unit.sources = all_sources
        
        self.log_complete(0, f"Merged into unit: {merged_unit.title}")
        return merged_unit
