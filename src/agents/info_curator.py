"""Information Curator Agent - 信息简报主编"""

import json
from typing import List, Dict, Any
import structlog

from .base import BaseAgent
from ..models.information import InformationUnit
from ..models.agent import AgentContext, AgentOutput

logger = structlog.get_logger()

INFO_CURATOR_SYSTEM_PROMPT = """你是一位资深新闻主编，负责为用户筛选今日最有价值的信息。你必须严格把控质量，宁缺毋滥。

## 筛选原则（严格执行）

### 🚫 必须排除的内容
1. **论坛帖子/个人求助**：如购房咨询、技术问答、个人经历分享
2. **教程/技术文档摘录**：如"如何禁用XX功能"、代码问题解答
3. **过于投机的观点**：无实质新闻事件支撑的纯预测或担忧
4. **时效性差的旧闻**：复述已知事实而无新信息
5. **标题党/低信息量**：标题夸张但内容空洞

### ✅ 优先入选的内容
1. **重大事件**：影响行业/市场/社会的突发新闻
2. **深度分析**：有独到见解的解读，analysis_depth_score > 0.7
3. **独家/稀缺信息**：其他来源难以获取的信息

## 评分标准（必须使用完整区间）
- **9.5-10**：仅用于改变行业格局的重大事件（每期最多1-2条）
- **8.5-9.4**：重要且有深度的新闻（每期3-5条）
- **7.5-8.4**：值得关注的良好内容
- **6.5-7.4**：普通新闻，可作为快速浏览
- **6.5以下**：不入选

## 去重规则（严格执行）
如果多条内容讲述**同一事件**（如"苹果与谷歌合作"），只保留**最有深度的一条**，其余排除。不要把相似内容都放入精选！

## 输出要求

返回 JSON：
```json
{
  "daily_summary": "今日一句话导语（50字以内）",
  "top_picks": [
    {
      "id": "unit_id",
      "display_title": "重写后的精炼标题",
      "score": 8.7,
      "reasoning": "入选理由（说明价值点，20字以内）",
      "presentation": {
        "summary": "事实摘要（2-3句话）",
        "analysis": "深度分析（这是核心！100-200字，解释意义和影响）",
        "impact": "潜在影响（1-2句话）"
      }
    }
  ],
  "quick_reads": [
    {
      "id": "unit_id",
      "display_title": "标题",
      "one_line_summary": "一句话概括（20字以内）"
    }
  ],
  "excluded_reasons": {
    "duplicate": ["id1", "id2"],
    "irrelevant": ["id3"],
    "low_quality": ["id4"]
  }
}
```

## 数量硬性限制
- **top_picks: 5-8 条**（质量优先，可以更少，但不能超过8条）
- **quick_reads: 5-15 条**
- **总计不超过 20 条**

记住：你是一个严格的主编，不是一个讨好读者的推荐算法。宁可漏掉一条好内容，也不能让垃圾内容进入精选！
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

    async def curate(self, units: List[InformationUnit], max_top_picks: int = 8) -> Dict[str, Any]:
        """执行筛选任务 (Internal)"""
        if not units:
            return {"top_picks": [], "quick_reads": [], "daily_summary": "无内容"}
            
        self.log_start(f"Curating from {len(units)} units")
        
        # 1. 过滤不适合的内容类型
        filtered_units = self._filter_irrelevant_content(units)
        logger.info("content_filtering", original=len(units), after_filter=len(filtered_units))
        
        # 2. 预排序：按重要性和深度
        sorted_units = sorted(
            filtered_units, 
            key=lambda u: (u.analysis_depth_score * 0.6 + u.importance_score * 0.4), 
            reverse=True
        )
        
        # 3. 本地去重 (提高阈值，更激进去重)
        unique_units = self._deduplicate_units(sorted_units, threshold=0.45)
        logger.info("deduplication_complete", original=len(filtered_units), unique=len(unique_units))
        
        # 4. 只把最优秀的 25 个给 LLM 挑选
        candidates = unique_units[:25]
        
        units_json = []
        for u in candidates:
            # 添加来源信息帮助 AI 识别低质量内容
            source_name = ""
            if u.sources:
                source_name = u.sources[0].source_name if hasattr(u.sources[0], 'source_name') else str(u.sources[0])
            
            units_json.append({
                "id": u.id,
                "title": u.title,
                "source": source_name or u.primary_source,
                "summary": u.summary[:300],
                "analysis_content": u.analysis_content[:400] if u.analysis_content else "",
                "key_insights": u.key_insights[:3] if u.key_insights else [],
                "depth_score": round(u.analysis_depth_score, 2),
                "importance": round(u.importance_score, 2)
            })
            
        user_prompt = f"""从以下 {len(candidates)} 个候选中严格筛选：

**要求**：
- Top Picks: 最多 {min(max_top_picks, 8)} 条（宁少勿滥）
- Quick Reads: 最多 15 条
- 相同事件只保留最优的一条
- 排除论坛帖子、技术问答、个人求助类内容

候选列表：
{json.dumps(units_json, ensure_ascii=False, indent=2)}
"""
        
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=3000,
            temperature=0.2,  # 降低温度提高一致性
            json_mode=True
        )
        
        if not result or not isinstance(result, dict):
            logger.warning("curation_failed_using_fallback")
            return self._fallback_curation(unique_units, max_top_picks)
        
        # 5. 后处理：强制执行硬性限制
        result = self._enforce_limits(result, max_top_picks)
            
        self.log_complete(0, f"Selected {len(result.get('top_picks', []))} top picks, {len(result.get('quick_reads', []))} quick reads")
        return result
    
    def _filter_irrelevant_content(self, units: List[InformationUnit]) -> List[InformationUnit]:
        """过滤不适合的内容"""
        # 低质量来源关键词
        low_quality_sources = ['v2ex', 'segmentfault', 'stackoverflow', 'zhihu.com/question']
        # 低质量标题关键词
        irrelevant_keywords = ['求助', '请问', '如何', '怎么', '怎样', '购房', '买房', '租房', '面试']
        
        filtered = []
        for u in units:
            source_lower = (u.primary_source or "").lower()
            title_lower = (u.title or "").lower()
            
            # 检查来源
            is_low_quality_source = any(s in source_lower for s in low_quality_sources)
            
            # 检查标题
            is_irrelevant_title = any(kw in title_lower for kw in irrelevant_keywords)
            
            # 检查分数门槛
            is_low_score = u.importance_score < 0.5 and u.analysis_depth_score < 0.5
            
            if not is_low_quality_source and not is_irrelevant_title and not is_low_score:
                filtered.append(u)
            else:
                logger.debug("filtered_out", id=u.id, title=u.title[:30], reason="low_quality_or_irrelevant")
        
        return filtered
    
    def _enforce_limits(self, result: Dict[str, Any], max_top_picks: int) -> Dict[str, Any]:
        """强制执行数量限制"""
        top_picks = result.get("top_picks", [])
        quick_reads = result.get("quick_reads", [])
        
        # 强制限制 top_picks
        if len(top_picks) > max_top_picks:
            # 按 score 排序，保留最高的
            top_picks = sorted(top_picks, key=lambda x: x.get("score", 0), reverse=True)[:max_top_picks]
            result["top_picks"] = top_picks
        
        # 强制限制 quick_reads
        if len(quick_reads) > 15:
            result["quick_reads"] = quick_reads[:15]
        
        # 强制总数限制
        total = len(result.get("top_picks", [])) + len(result.get("quick_reads", []))
        if total > 20:
            excess = total - 20
            result["quick_reads"] = result.get("quick_reads", [])[:-excess] if excess > 0 else result.get("quick_reads", [])
        
        return result

    def _deduplicate_units(self, units: List[InformationUnit], threshold: float = 0.55) -> List[InformationUnit]:
        """
        增强版去重：同时检查标题相似度和内容相似度
        
        策略：
        1. 如果标题相似度 > threshold，认为是重复
        2. 如果标题相似度 > 0.4 且 摘要相似度 > threshold，也认为是重复
        3. 保留分数更高的那个
        """
        from difflib import SequenceMatcher
        
        def content_key(u: InformationUnit) -> str:
            """生成用于相似度比较的内容字符串"""
            return f"{u.summary} {' '.join(u.key_insights[:3])}"
        
        def are_similar(u1: InformationUnit, u2: InformationUnit) -> bool:
            # 检查标题相似度
            title_sim = SequenceMatcher(None, u1.title, u2.title).ratio()
            if title_sim > threshold:
                return True
            
            # 如果标题有一定相似度，再检查内容
            if title_sim > 0.4:
                content_sim = SequenceMatcher(None, content_key(u1), content_key(u2)).ratio()
                if content_sim > threshold:
                    return True
            
            return False
        
        unique = []
        for unit in units:
            is_dup = False
            for i, existing in enumerate(unique):
                if are_similar(unit, existing):
                    is_dup = True
                    # 保留分数更高的
                    unit_score = unit.analysis_depth_score * 0.7 + unit.importance_score * 0.3
                    exist_score = existing.analysis_depth_score * 0.7 + existing.importance_score * 0.3
                    if unit_score > exist_score:
                        unique[i] = unit  # 替换为更高分的
                    break
            if not is_dup:
                unique.append(unit)
        return unique

    def _fallback_curation(self, units: List[InformationUnit], max_picks: int) -> Dict[str, Any]:
        """降级策略：直接取前 N 个 (此时 units 已经去重且排序)"""
        # 应用过滤
        filtered = self._filter_irrelevant_content(units)
        
        # 限制数量
        max_picks = min(max_picks, 8)
        top = filtered[:max_picks]
        rest = filtered[max_picks:max_picks+12]
        
        def calc_display_score(u: InformationUnit) -> float:
            """计算显示分数 (1-10 scale)"""
            base = (u.analysis_depth_score * 0.6 + u.importance_score * 0.4) * 10
            # 添加一些方差
            return round(min(9.8, max(6.5, base)), 1)
        
        def generate_reasoning(u: InformationUnit) -> str:
            """生成入选理由"""
            if u.importance_score > 0.8:
                return "重要性高，值得关注"
            elif u.analysis_depth_score > 0.8:
                return "分析深度较好"
            else:
                return "综合评分入选"
        
        return {
            "daily_summary": "今日自动简报（AI分析临时不可用）",
            "top_picks": [
                {
                    "id": u.id,
                    "score": calc_display_score(u),
                    "display_title": u.title,
                    "reasoning": generate_reasoning(u),
                    "presentation": {
                        "summary": u.summary or "暂无摘要",
                        "analysis": u.analysis_content or "暂无深度分析",
                        "impact": u.impact_assessment or "暂无影响评估"
                    }
                } for u in top
            ],
            "quick_reads": [
                {
                    "id": u.id,
                    "display_title": u.title,
                    "one_line_summary": u.summary[:50] if u.summary else u.title
                } for u in rest
            ],
            "excluded_reasons": {}
        }
