"""Information Curator Agent - 信息简报主编"""

import json
from typing import List, Dict, Any
import structlog

from .base import BaseAgent
from ..models.information import InformationUnit
from ..models.agent import AgentContext, AgentOutput

logger = structlog.get_logger()

INFO_CURATOR_SYSTEM_PROMPT = """你不是一个普通的阅读助手，你是一个冷酷、理性的情报过滤器。你的任务是从海量噪音中筛选出那 1% 的"高价值情报"。

## 【价值定义模型】- 4 维评估体系

### 1. 信息增量 (Information Gain) - 权重 30%
**核心问题：这条信息是否打破了已知共识？**
- 10分：颠覆性信息，完全出乎市场预期（如"央行意外降息50基点"）
- 7-9分：显著偏离预期，包含反直觉的数据或结论
- 4-6分：符合预期，是已知趋势的确认
- 1-3分：纯粹的车轱辘话复述（如"AI正在改变世界"）

### 2. 行动指导性 (Actionability) - 权重 25%
**核心问题：读完后能否做出具体决策？**
- 10分：包含明确的参数、截止日期、政策变动（如"3月1日起新规生效"）
- 7-9分：提供具体数据支撑的趋势判断
- 4-6分：有一定参考价值但不足以直接行动
- 1-3分：纯情绪宣泄或无关痛痒的八卦

### 3. 稀缺性 (Scarcity) - 权重 20%
**核心问题：这是一手信源还是三手转述？**
- 10分：原始数据源（论文原件、财报表格、官方公告）
- 7-9分：现场采访、独家报道、有数据支撑的深度分析
- 4-6分：对权威来源的准确引用
- 1-3分：自媒体评论、充满"震惊"、"据说"等词汇的文章

### 4. 影响范围 (Impact Magnitude) - 权重 25%
**核心问题：事件主体的权重有多大？**
- 核心玩家（央行、苹果、OpenAI、微软、英伟达）：即使小动作也值 7-9 分
- 重要玩家（大型科技公司、行业龙头）：中等动作值 5-7 分
- 边缘玩家：除非是重大事件，否则 3-5 分

---

## 【高价值定义 (8-10分)】
✅ **意外性**：包含反直觉的数据或事件，打破原有行业共识
✅ **具体性**：包含具体数字、明确时间表、具体代码更新或法律条款
✅ **底层逻辑**：解释了现象背后的 Why，而不仅仅是 What
✅ **预测力**：该信息能推导出未来 3-6 个月的高确定性趋势

## 【低价值定义 (0-3分)】
❌ **情绪化**：充满形容词（"吓尿了"、"重磅"），缺乏数据支撑
❌ **重复**：对已知事实的车轱辘话复述
❌ **模糊**：使用"可能"、"据说"、"有关部门"等模糊指代
❌ **非新闻**：论坛求助、技术问答、个人经历分享

---

## 【评估示例】

**示例 1（低价值 - 3分）：**
> "专家表示，人工智能未来将彻底改变我们的生活，大家要做好准备。"

点评：正确的废话。无具体时间、技术路径、指导意义。信息增量=2, 行动指导=1, 稀缺性=2, 影响范围=3。

**示例 2（高价值 - 9分）：**
> "台积电宣布2nm工艺良率突破80%，将于Q3量产，首批客户为苹果M5芯片。"

点评：具体技术参数(2nm/80%)、明确时间(Q3)、核心玩家(台积电/苹果)。信息增量=8, 行动指导=8, 稀缺性=9, 影响范围=9。

---

## 【输出格式】

```json
{
  "daily_summary": "今日一句话导语（30字以内）",
  "top_picks": [
    {
      "id": "unit_id",
      "display_title": "精炼标题",
      "event_time": "事件发生时间",
      "scores": {
        "information_gain": 8.5,
        "actionability": 7.0,
        "scarcity": 9.0,
        "impact_magnitude": 8.0,
        "total": 8.1
      },
      "reasoning": "入选理由（说明哪个维度得分高）",
      "presentation": {
        "summary": "事实摘要（2-3句）",
        "analysis": "深度分析（100-200字，解释 Why 和影响）",
        "impact": "潜在影响（1-2句）"
      }
    }
  ],
  "quick_reads": [
    {
      "id": "unit_id",
      "display_title": "标题",
      "one_line_summary": "一句话（20字以内）",
      "total_score": 6.5
    }
  ]
}
```

## 【硬性限制】
- **top_picks**: 5-8 条（综合分 ≥ 7.5）
- **quick_reads**: 5-12 条（综合分 6.0-7.4）
- 综合分 < 6.0 的内容不入选
- 同一事件只保留最高分的一条
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
        
        # 2. 预排序：使用综合价值评分
        sorted_units = sorted(
            filtered_units, 
            key=lambda u: u.value_score,  # 使用新的4维综合评分
            reverse=True
        )
        
        # 3. 本地去重 (提高阈值，更激进去重)
        unique_units = self._deduplicate_units(sorted_units, threshold=0.45)
        logger.info("deduplication_complete", original=len(filtered_units), unique=len(unique_units))
        
        # 4. 只把最优秀的 25 个给 LLM 挑选
        candidates = unique_units[:25]
        
        units_json = []
        for u in candidates:
            # 添加来源信息
            source_name = ""
            if u.sources:
                source_name = u.sources[0].source_name if hasattr(u.sources[0], 'source_name') else ""
            
            units_json.append({
                "id": u.id,
                "title": u.title,
                "source": source_name or self._extract_domain(u.primary_source),
                "event_time": u.event_time or u.when or "未知",
                "report_time": u.report_time.strftime("%Y-%m-%d %H:%M") if u.report_time else "未知",
                "summary": u.summary[:300],
                "analysis_content": u.analysis_content[:400] if u.analysis_content else "",
                "key_insights": u.key_insights[:3] if u.key_insights else [],
                # 已有的4维评分
                "current_scores": {
                    "information_gain": round(u.information_gain, 1),
                    "actionability": round(u.actionability, 1),
                    "scarcity": round(u.scarcity, 1),
                    "impact_magnitude": round(u.impact_magnitude, 1),
                    "value_score": round(u.value_score, 1)
                },
                "depth_score": round(u.analysis_depth_score, 2),
                "importance": round(u.importance_score, 2)
            })
            
        user_prompt = f"""请基于【价值定义模型】对以下 {len(candidates)} 个候选进行评估和筛选：

**筛选要求**：
- Top Picks: 最多 {min(max_top_picks, 8)} 条（综合分 ≥ 7.5）
- Quick Reads: 最多 12 条（综合分 6.0-7.4）
- 综合分 < 6.0 不入选
- 同一事件只保留最高分的一条

**评估维度**（请为每条内容打分）：
1. 信息增量 (1-10): 是否打破已知？
2. 行动指导 (1-10): 能否指导决策？
3. 稀缺性 (1-10): 是否一手信源？
4. 影响范围 (1-10): 涉及实体权重？

候选列表：
{json.dumps(units_json, ensure_ascii=False, indent=2)}
"""
        
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=4000,  # 增加 token 以容纳更详细的评分
            temperature=0.15,  # 更低温度提高评分一致性
            json_mode=True
        )
        
        if not result or not isinstance(result, dict):
            logger.warning("curation_failed_using_fallback")
            return self._fallback_curation(unique_units, max_top_picks)
        
        # 5. 后处理：强制执行硬性限制和分数过滤
        result = self._enforce_limits(result, max_top_picks)
        result = self._filter_low_scores(result)
            
        self.log_complete(0, f"Selected {len(result.get('top_picks', []))} top picks, {len(result.get('quick_reads', []))} quick reads")
        return result
    
    def _extract_domain(self, url: str) -> str:
        """从 URL 提取域名"""
        if not url:
            return "未知来源"
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            return domain or "未知来源"
        except:
            return "未知来源"
    
    def _filter_low_scores(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """过滤低分内容"""
        # 过滤 top_picks 中分数低于 7.5 的
        top_picks = result.get("top_picks", [])
        filtered_top = []
        for item in top_picks:
            score = item.get("scores", {}).get("total", 0) if isinstance(item.get("scores"), dict) else item.get("score", 0)
            if score >= 7.0:  # 稍微放宽一点避免空结果
                filtered_top.append(item)
        result["top_picks"] = filtered_top
        
        # 过滤 quick_reads 中分数低于 6.0 的
        quick_reads = result.get("quick_reads", [])
        filtered_quick = []
        for item in quick_reads:
            score = item.get("total_score", 0)
            if score >= 5.5:  # 稍微放宽
                filtered_quick.append(item)
        result["quick_reads"] = filtered_quick
        
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
