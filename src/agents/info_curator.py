"""Information Curator Agent - 信息简报主编"""

import json
from typing import List, Dict, Any
import structlog

from .base import BaseAgent
from ..models.information import InformationUnit
from ..models.agent import AgentContext, AgentOutput

logger = structlog.get_logger()

INFO_CURATOR_SYSTEM_PROMPT = """你是一位洞察力极强的简报主编。你的任务是从一组"信息单元"中筛选出最有价值的内容，为用户生成一份高质量的日报。

## 筛选标准（优先级递减）
1. **分析深度**：优先选择 `analysis_depth_score` 高的内容。用户想看深度解读，不仅仅是事实陈述。
2. **重要性**：对行业、市场或社会有重大影响的事件。
3. **时效性**：最新发生的重要信息。

## 你的工作流程
1. **阅读与评估**：阅读所有输入的信息单元。
2. **遴选 Top Picks**：选出 3-5 个最重要的信息单元作为"深度精选"。对于这些条目，**必须**完整展示其分析内容。
3. **遴选 Quick Reads**：选出 5-10 个次重要的信息作为"快速浏览"。

## 输出要求
请输出一个 JSON 对象：
```json
{
  "daily_summary": "今日简报导语（100字以内，概述今日重点趋势）",
  "top_picks": [
    {
       "id": "original_unit_id",
       "display_title": "重写后的吸引人标题",
       "reasoning": "入选理由",
       "score": 9.5,
       "presentation": {
           "summary": "简明扼要的事实摘要",
           "analysis": "深度分析内容（这是重点！请确保篇幅占比超过50%，整合 key_insights 和 analysis_content）",
           "impact": "一句话影响评估"
       }
    }
  ],
  "quick_reads": [
    {
       "id": "original_unit_id",
       "display_title": "标题",
       "one_line_summary": "一句话摘要"
    }
  ],
  "excluded_count": 12
}
```

## 注意事项
- "深度精选"的内容必须经过润色，使其阅读体验极佳。
- **分析部分是核心**。不要只罗列事实，要告诉用户这就意味着什么，未来会怎样。
"""

class InformationCuratorAgent(BaseAgent):
    """
    信息简报 Agent
    
    职责：
    1. 从 InformationUnit 列表中筛选 Top Picks
    2. 生成强调"分析"的展示内容
    """
    
    AGENT_NAME = "InfoCurator"
    SYSTEM_PROMPT = INFO_CURATOR_SYSTEM_PROMPT
    
    async def process(self, input_data: List[InformationUnit], context: AgentContext = None, max_top_picks: int = 5) -> AgentOutput:
        """执行筛选任务"""
        units = input_data
        result = await self.curate(units, max_top_picks)
        return AgentOutput(success=True, data=result, trace=None)

    async def curate(self, units: List[InformationUnit], max_top_picks: int = 5) -> Dict[str, Any]:
        """执行筛选任务 (Internal)"""
        if not units:
            return {"top_picks": [], "quick_reads": [], "daily_summary": "无内容"}
            
        self.log_start(f"Curating from {len(units)} units")
        
        # 1. 预排序：按重要性和深度
        sorted_units = sorted(
            units, 
            key=lambda u: (u.analysis_depth_score * 0.7 + u.importance_score * 0.3), 
            reverse=True
        )
        
        # 2. 本地去重 (Deduplication)
        unique_units = self._deduplicate_units(sorted_units)
        logger.info("deduplication_complete", original=len(units), unique=len(unique_units))
        
        candidates = unique_units[:20]  # 只把最优秀的 20 个给 LLM 挑选
        
        units_json = []
        for u in candidates:
            units_json.append({
                "id": u.id,
                "title": u.title,
                "summary": u.summary,
                "analysis_content": u.analysis_content[:500], # 截断以节省 token
                "key_insights": u.key_insights,
                "depth_score": u.analysis_depth_score,
                "importance": u.importance_score
            })
            
        user_prompt = f"""
        从以下候选列表中选出 {max_top_picks} 个精选内容作为 Top Picks，其余适合的内容作为 Quick Reads。
        
        候选列表：
        {json.dumps(units_json, ensure_ascii=False, indent=2)}
        """
        
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=2500,
            temperature=0.3,
            json_mode=True
        )
        
        if not result or not isinstance(result, dict):
            # Fallback
            logger.warning("curation_failed_using_fallback")
            return self._fallback_curation(unique_units, max_top_picks)
            
        self.log_complete(0, f"Selected {len(result.get('top_picks', []))} top picks")
        return result

    def _deduplicate_units(self, units: List[InformationUnit], threshold: float = 0.6) -> List[InformationUnit]:
        """基于标题相似度的简单去重 (保留分数高的)"""
        from difflib import SequenceMatcher
        
        unique = []
        for unit in units:
            is_dup = False
            for existing in unique:
                similarity = SequenceMatcher(None, unit.title, existing.title).ratio()
                if similarity > threshold:
                    is_dup = True
                    break
            if not is_dup:
                unique.append(unit)
        return unique

    def _fallback_curation(self, units: List[InformationUnit], max_picks: int) -> Dict[str, Any]:
        """降级策略：直接取前 N 个 (此时 units 已经去重且排序)"""
        top = units[:max_picks]
        rest = units[max_picks:max_picks+10]
        
        return {
            "daily_summary": "今日自动生成的简报（AI分析临时不可用，使用评分排序）",
            "top_picks": [
                {
                    "id": u.id,
                    "score": round(u.analysis_depth_score * 10, 1),
                    "display_title": u.title,
                    "reasoning": f"Score: {u.analysis_depth_score:.1f}",
                    "presentation": {
                        "summary": u.summary,
                        "analysis": u.analysis_content or "暂无深度分析",
                        "impact": u.impact_assessment or "暂无影响评估"
                    }
                } for u in top
            ],
            "quick_reads": [
                {
                    "id": u.id,
                    "display_title": u.title,
                    "one_line_summary": u.summary
                } for u in rest
            ],
            "excluded_count": max(0, len(units) - len(top) - len(rest))
        }
