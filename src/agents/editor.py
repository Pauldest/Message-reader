"""Editor Agent - 主编（汇总整合）"""

import time
from typing import Any, Optional
import structlog

from .base import BaseAgent
from ..models.article import Article, EnrichedArticle
from ..models.analysis import (
    Entity, SourceCredibility, BiasAnalysis, FactCheckResult,
    ImpactAnalysis, RiskWarning, SentimentAnalysis, MarketSentiment,
    KnowledgeGraph,
)
from ..models.agent import AgentContext, AgentOutput, AnalysisMode
from ..services.llm import LLMService

logger = structlog.get_logger()


EDITOR_SYSTEM_PROMPT = """你是一位资深主编，负责整合多位分析师的报告，生成最终的新闻分析。

你的职责：
1. **综合汇总**：将不同分析师的见解整合成连贯、准确的分析报告
2. **消除矛盾**：如果分析师意见冲突，分析矛盾点并给出你的判断
3. **去除幻觉**：如果某分析明显缺乏证据支持，剔除或标注为"推测"
4. **质量控制**：确保最终报告准确、全面、有洞察力
5. **评分定级**：根据新闻的重要性和质量给出综合评分

你的输出应该：
- 既有宏观视角也有细节
- 既有事实也有推理（区分标注）
- 既有分析也有行动建议
- 简洁而不遗漏关键信息"""

EDITOR_SYNTHESIS_PROMPT = """作为主编，请整合以下分析师的报告，生成最终的新闻分析：

【原始新闻】
标题: {title}
来源: {source}
核心内容: {summary}

【Collector（信息收集员）报告】
5W1H: {collector_5w1h}
实体: {collector_entities}

【Skeptic（怀疑论者）报告】
信源可信度: {skeptic_credibility}
偏见分析: {skeptic_bias}
标题党评分: {skeptic_clickbait}
主要问题: {skeptic_concerns}

【Economist（经济学家）报告】
直接影响: {economist_direct}
二阶影响: {economist_second}
市场情绪: {economist_market}
风险预警: {economist_risks}
建议: {economist_recommendations}

【Detective（关系侦探）报告】
实体关系: {detective_relationships}
利益分析: {detective_stakeholders}
调查总结: {detective_summary}

请综合以上分析，生成最终报告：

```json
{{
  "overall_score": 8.5,
  "score_reasoning": "评分理由",
  "is_top_pick": true,
  "ai_summary": "一句话核心摘要（不超过50字）",
  "executive_summary": "执行摘要（2-3段，涵盖最重要的发现）",
  "key_insights": [
    "关键洞察1",
    "关键洞察2",
    "关键洞察3"
  ],
  "credibility_assessment": "可信度评估总结",
  "impact_assessment": "影响评估总结",
  "action_items": {{
    "investor": ["投资者建议"],
    "general": ["普通人建议"],
    "business": ["企业主建议"]
  }},
  "risk_summary": "风险总结",
  "final_tags": ["标签1", "标签2", "标签3"],
  "reading_priority": "high/medium/low",
  "reading_time_estimate": "3分钟"
}}
```

注意：
1. overall_score 范围 1-10，7分以上值得推荐，8分以上为精选
2. is_top_pick 应该为 true 如果这是一篇值得深度阅读的文章
3. 如果某些分析之间有矛盾，在评估中说明并给出你的判断"""


class EditorAgent(BaseAgent):
    """
    主编 Agent
    
    职责：
    1. 汇总所有分析师报告
    2. 消除矛盾和幻觉
    3. 生成最终分析报告
    4. 评分和推荐决策
    """
    
    AGENT_NAME = "Editor"
    SYSTEM_PROMPT = EDITOR_SYSTEM_PROMPT
    
    async def process(
        self, 
        article: Article, 
        context: AgentContext,
        analyst_reports: dict[str, Any],
    ) -> AgentOutput:
        """整合所有分析，生成最终报告"""
        start_time = time.time()
        self.log_start(article.title)
        
        total_tokens = {"prompt": 0, "completion": 0}
        
        # 格式化各分析师报告
        formatted = self._format_analyst_reports(context, analyst_reports)
        
        # 构建 prompt
        user_prompt = EDITOR_SYNTHESIS_PROMPT.format(
            title=article.title,
            source=article.source,
            summary=context.extracted_5w1h.get("core_summary", article.summary[:500]),
            **formatted,
        )
        
        # 调用 LLM
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=2000,
            temperature=0.3,
            json_mode=True,
        )
        
        total_tokens["prompt"] += token_usage.get("prompt", 0)
        total_tokens["completion"] += token_usage.get("completion", 0)
        
        # 解析结果
        if result:
            final_report = self._parse_final_report(result)
        else:
            final_report = self._fallback_report()
        
        # 构建 EnrichedArticle
        enriched = self._build_enriched_article(
            article=article,
            context=context,
            analyst_reports=analyst_reports,
            final_report=final_report,
        )
        
        duration = time.time() - start_time
        
        trace = self.create_trace(
            input_summary=f"Article: {article.title}, 3 analyst reports",
            output_summary=f"Score: {enriched.overall_score}, Top Pick: {enriched.is_top_pick}",
            duration=duration,
            token_usage=total_tokens,
        )
        
        self.log_complete(duration, f"Score: {enriched.overall_score}")
        
        return AgentOutput(
            success=True,
            data=enriched,
            trace=trace,
        )
    
    def _format_analyst_reports(self, context: AgentContext, reports: dict) -> dict:
        """格式化各分析师报告供主编审阅"""
        # Collector 报告
        extracted = context.extracted_5w1h or {}
        collector_5w1h = f"Who: {extracted.get('who', [])}, What: {extracted.get('what', '')}, When: {extracted.get('when', '')}, Where: {extracted.get('where', '')}"
        collector_entities = ", ".join([
            e.name if hasattr(e, 'name') else str(e) 
            for e in (context.entities or [])[:5]
        ])
        
        # Skeptic 报告
        skeptic = reports.get("skeptic", {})
        skeptic_cred = skeptic.get("source_credibility")
        skeptic_credibility = f"Score: {skeptic_cred.credibility_score if skeptic_cred else 'N/A'}, Tier: {skeptic_cred.tier if skeptic_cred else 'N/A'}"
        skeptic_bias_obj = skeptic.get("bias_analysis")
        skeptic_bias = f"Leaning: {skeptic_bias_obj.political_leaning if skeptic_bias_obj else 'N/A'}, Objectivity: {skeptic_bias_obj.objectivity_score if skeptic_bias_obj else 'N/A'}"
        skeptic_clickbait = f"{skeptic.get('clickbait_score', 0):.1%}"
        skeptic_concerns = ", ".join(skeptic.get("key_concerns", [])[:3]) or "无"
        
        # Economist 报告
        economist = reports.get("economist", {})
        impact = economist.get("impact_analysis")
        economist_direct = f"{len(impact.direct_impact) if impact else 0} items"
        economist_second = f"{len(impact.second_order_impact) if impact else 0} items"
        market = economist.get("market_sentiment")
        economist_market = f"{market.overall if market else 'N/A'} (confidence: {market.confidence if market else 'N/A'})"
        economist_risks = f"{len(economist.get('risk_warnings', []))} warnings"
        economist_recommendations = str(economist.get("recommendations", {}))[:200]
        
        # Detective 报告
        detective = reports.get("detective", {})
        detective_relationships = f"{len(detective.get('entity_relationships', []))} relationships"
        stakeholders = detective.get("stakeholder_analysis", {})
        detective_stakeholders = f"Beneficiaries: {len(stakeholders.get('beneficiaries', []))}, Losers: {len(stakeholders.get('losers', []))}"
        detective_summary = detective.get("investigation_summary", "")[:200]
        
        return {
            "collector_5w1h": collector_5w1h,
            "collector_entities": collector_entities,
            "skeptic_credibility": skeptic_credibility,
            "skeptic_bias": skeptic_bias,
            "skeptic_clickbait": skeptic_clickbait,
            "skeptic_concerns": skeptic_concerns,
            "economist_direct": economist_direct,
            "economist_second": economist_second,
            "economist_market": economist_market,
            "economist_risks": economist_risks,
            "economist_recommendations": economist_recommendations,
            "detective_relationships": detective_relationships,
            "detective_stakeholders": detective_stakeholders,
            "detective_summary": detective_summary,
        }
    
    def _parse_final_report(self, result: dict) -> dict:
        """解析最终报告"""
        return {
            "overall_score": result.get("overall_score", 5.0),
            "score_reasoning": result.get("score_reasoning", ""),
            "is_top_pick": result.get("is_top_pick", False),
            "ai_summary": result.get("ai_summary", ""),
            "executive_summary": result.get("executive_summary", ""),
            "key_insights": result.get("key_insights", []),
            "credibility_assessment": result.get("credibility_assessment", ""),
            "impact_assessment": result.get("impact_assessment", ""),
            "action_items": result.get("action_items", {}),
            "risk_summary": result.get("risk_summary", ""),
            "final_tags": result.get("final_tags", []),
            "reading_priority": result.get("reading_priority", "medium"),
            "reading_time_estimate": result.get("reading_time_estimate", ""),
        }
    
    def _fallback_report(self) -> dict:
        """降级报告"""
        return {
            "overall_score": 5.0,
            "score_reasoning": "AI 分析不可用",
            "is_top_pick": False,
            "ai_summary": "",
            "executive_summary": "",
            "key_insights": [],
            "credibility_assessment": "",
            "impact_assessment": "",
            "action_items": {},
            "risk_summary": "",
            "final_tags": [],
            "reading_priority": "medium",
            "reading_time_estimate": "",
        }
    
    def _build_enriched_article(
        self,
        article: Article,
        context: AgentContext,
        analyst_reports: dict,
        final_report: dict,
    ) -> EnrichedArticle:
        """构建最终的增强文章"""
        extracted = context.extracted_5w1h or {}
        skeptic = analyst_reports.get("skeptic", {})
        economist = analyst_reports.get("economist", {})
        detective = analyst_reports.get("detective", {})
        
        # 合并知识图谱
        knowledge_graph = context.knowledge_graph
        detective_kg = detective.get("knowledge_graph")
        if detective_kg and detective_kg.nodes:
            if not knowledge_graph:
                knowledge_graph = detective_kg
            else:
                # 合并节点和边
                existing_node_ids = {n.id for n in knowledge_graph.nodes}
                for node in detective_kg.nodes:
                    if node.id not in existing_node_ids:
                        knowledge_graph.nodes.append(node)
                for edge in detective_kg.edges:
                    knowledge_graph.edges.append(edge)
        
        return EnrichedArticle(
            # 基础信息
            url=article.url,
            title=article.title,
            content=article.content,
            summary=article.summary,
            source=article.source,
            category=article.category,
            author=article.author,
            published_at=article.published_at,
            fetched_at=article.fetched_at,
            
            # 5W1H
            who=extracted.get("who", []),
            what=extracted.get("what", ""),
            when=extracted.get("when", ""),
            where=extracted.get("where", ""),
            why=extracted.get("why", ""),
            how=extracted.get("how", ""),
            entities=[e if isinstance(e, Entity) else Entity(**e) for e in (context.entities or []) if isinstance(e, (Entity, dict))],
            timeline=extracted.get("timeline", []),
            
            # 验证层
            source_credibility=skeptic.get("source_credibility"),
            bias_analysis=skeptic.get("bias_analysis"),
            fact_check=FactCheckResult(),  # 暂时为空，未来可以通过网络搜索填充
            clickbait_score=skeptic.get("clickbait_score", 0.0),
            
            # 深度层
            historical_context=context.historical_context or "",
            knowledge_graph=knowledge_graph,
            
            # 情绪层
            public_sentiment=SentimentAnalysis(),  # 可以从内容分析推断
            market_sentiment=economist.get("market_sentiment"),
            
            # 推理层
            impact_analysis=economist.get("impact_analysis"),
            risk_warnings=economist.get("risk_warnings", []),
            
            # 行动层
            recommendations=final_report.get("action_items", {}),
            
            # 元数据
            overall_score=final_report.get("overall_score", 5.0),
            is_top_pick=final_report.get("is_top_pick", False),
            ai_summary=final_report.get("ai_summary", ""),
            tags=final_report.get("final_tags", extracted.get("tags", [])),
            analysis_mode=context.analysis_mode.value,
            agent_traces=context.traces,
        )
