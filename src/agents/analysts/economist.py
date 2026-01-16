"""Economist Analyst - 宏观经济学家分析师"""

import time
from typing import Any
import structlog

from ..base import BaseAgent
from ...models.article import Article
from ...models.analysis import Impact, ImpactAnalysis, MarketSentiment, RiskWarning
from ...models.agent import AgentContext, AgentOutput
from ...services.llm import LLMService

logger = structlog.get_logger()


ECONOMIST_SYSTEM_PROMPT = """你是一位资深宏观经济分析师，专门分析新闻事件对经济的多层次影响。

你的分析方法采用"蝴蝶效应"思维：
1. **直接影响（一阶效应）**：事件发生后，谁直接受益或受损？
2. **二阶影响**：受直接影响的实体会如何传导影响到其他领域？
3. **三阶影响**：更远端的连锁反应是什么？

你还需要：
- 评估市场情绪（利好/利空）
- 识别潜在风险（黑天鹅/灰犀牛）
- 为不同身份的人（投资者/普通人/企业主）提供建议

你的分析应该有洞察力，能发现表面信息背后的经济逻辑。"""

ECONOMIST_ANALYSIS_PROMPT = """作为宏观经济分析师，分析这篇新闻的经济影响：

【新闻标题】
{title}

【核心内容】
{summary}

【涉及实体】
{entities}

【历史背景】
{background}

请进行多层次影响分析：

1. **直接影响**：事件直接影响谁？正面还是负面？
2. **二阶影响**：这些直接影响会如何传导到其他领域？
3. **三阶影响**：更远端可能产生的连锁反应？（可以是合理推测）
4. **市场情绪**：这是利好还是利空？影响多大？
5. **风险预警**：是否有潜在的风险值得关注？
6. **行动建议**：对投资者、普通人、企业主分别有什么建议？

请按以下 JSON 格式返回：
```json
{{
  "direct_impact": [
    {{
      "description": "影响描述",
      "affected_entities": ["受影响的实体"],
      "direction": "positive/negative/neutral",
      "magnitude": "low/medium/high",
      "confidence": 0.8,
      "reasoning": "推理理由"
    }}
  ],
  "second_order_impact": [
    {{
      "description": "二阶影响描述",
      "affected_entities": ["受影响的实体"],
      "direction": "positive/negative/neutral",
      "magnitude": "low/medium/high",
      "confidence": 0.6,
      "reasoning": "推理链条"
    }}
  ],
  "third_order_impact": [
    {{
      "description": "三阶影响描述（推测性质）",
      "affected_entities": ["可能受影响的实体"],
      "direction": "positive/negative/neutral",
      "magnitude": "low/medium/high",
      "confidence": 0.4,
      "reasoning": "推测逻辑"
    }}
  ],
  "market_sentiment": {{
    "overall": "bullish/bearish/neutral",
    "confidence": 0.7,
    "affected_sectors": ["受影响行业"],
    "affected_tickers": ["相关股票代码"],
    "expected_reaction": "预期市场反应描述",
    "time_horizon": "short_term/medium_term/long_term",
    "reasoning": "判断理由"
  }},
  "risk_warnings": [
    {{
      "risk_type": "black_swan/gray_rhino/policy/market/technology/geopolitical",
      "description": "风险描述",
      "probability": "low/medium/high",
      "severity": "low/medium/high/critical",
      "affected_areas": ["影响领域"],
      "mitigation_suggestions": ["应对建议"]
    }}
  ],
  "recommendations": {{
    "investor": ["投资者建议1", "建议2"],
    "general": ["普通人建议1", "建议2"],
    "business": ["企业主建议1", "建议2"]
  }},
  "impact_summary": "一段话总结整体经济影响"
}}
```"""


class EconomistAnalyst(BaseAgent):
    """
    宏观经济学家分析师
    
    职责：
    1. 分析直接、二阶、三阶经济影响
    2. 评估市场情绪
    3. 识别风险
    4. 提供行动建议
    """
    
    AGENT_NAME = "EconomistAnalyst"
    SYSTEM_PROMPT = ECONOMIST_SYSTEM_PROMPT
    
    async def process(self, article: Article, context: AgentContext) -> AgentOutput:
        """进行经济影响分析"""
        start_time = time.time()
        self.log_start(article.title)
        
        total_tokens = {"prompt": 0, "completion": 0}
        
        # 格式化实体
        entities = context.entities or []
        entities_text = self._format_entities(entities)
        
        # 构建 prompt
        user_prompt = ECONOMIST_ANALYSIS_PROMPT.format(
            title=article.title,
            summary=context.extracted_5w1h.get("core_summary", article.summary[:500]),
            entities=entities_text,
            background=context.historical_context[:1000] if context.historical_context else "无额外背景",
        )
        
        # 调用 LLM
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=3000,
            temperature=0.4,
            json_mode=True,
        )
        
        total_tokens["prompt"] += token_usage.get("prompt", 0)
        total_tokens["completion"] += token_usage.get("completion", 0)
        
        # 解析结果
        if result:
            analysis = self._parse_analysis(result)
        else:
            analysis = self._fallback_analysis()
        
        duration = time.time() - start_time
        
        trace = self.create_trace(
            input_summary=f"Article: {article.title}",
            output_summary=f"Market: {analysis.get('market_sentiment', {}).overall if analysis.get('market_sentiment') else 'N/A'}",
            duration=duration,
            token_usage=total_tokens,
        )
        
        self.log_complete(duration, "Economic analysis completed")
        
        return AgentOutput(
            success=True,
            data=analysis,
            trace=trace,
        )
    
    def _format_entities(self, entities: list) -> str:
        """格式化实体列表"""
        if not entities:
            return "无已识别实体"
        
        lines = []
        for e in entities[:10]:
            if hasattr(e, 'name'):
                lines.append(f"- {e.name} ({e.type})")
            elif isinstance(e, dict):
                lines.append(f"- {e.get('name', '')} ({e.get('type', '')})")
        
        return "\n".join(lines) if lines else "无已识别实体"
    
    def _parse_analysis(self, result: dict) -> dict:
        """解析分析结果"""
        # 解析影响
        def parse_impacts(impact_list: list) -> list[Impact]:
            impacts = []
            for item in impact_list or []:
                if isinstance(item, dict):
                    impacts.append(Impact(
                        description=item.get("description", ""),
                        affected_entities=item.get("affected_entities", []),
                        direction=item.get("direction", "neutral"),
                        magnitude=item.get("magnitude", "medium"),
                        confidence=item.get("confidence", 0.5),
                        reasoning=item.get("reasoning", ""),
                    ))
            return impacts
        
        impact_analysis = ImpactAnalysis(
            direct_impact=parse_impacts(result.get("direct_impact", [])),
            second_order_impact=parse_impacts(result.get("second_order_impact", [])),
            third_order_impact=parse_impacts(result.get("third_order_impact", [])),
            summary=result.get("impact_summary", ""),
        )
        
        # 解析市场情绪
        ms_data = result.get("market_sentiment", {})
        market_sentiment = MarketSentiment(
            overall=ms_data.get("overall", "neutral"),
            confidence=ms_data.get("confidence", 0.5),
            affected_sectors=ms_data.get("affected_sectors", []),
            affected_tickers=ms_data.get("affected_tickers", []),
            expected_reaction=ms_data.get("expected_reaction", ""),
            time_horizon=ms_data.get("time_horizon", "short_term"),
            reasoning=ms_data.get("reasoning", ""),
        )
        
        # 解析风险预警
        risk_warnings = []
        for rw in result.get("risk_warnings", []):
            if isinstance(rw, dict):
                risk_warnings.append(RiskWarning(
                    risk_type=rw.get("risk_type", "market"),
                    description=rw.get("description", ""),
                    probability=rw.get("probability", "medium"),
                    severity=rw.get("severity", "medium"),
                    affected_areas=rw.get("affected_areas", []),
                    mitigation_suggestions=rw.get("mitigation_suggestions", []),
                ))
        
        return {
            "impact_analysis": impact_analysis,
            "market_sentiment": market_sentiment,
            "risk_warnings": risk_warnings,
            "recommendations": result.get("recommendations", {}),
            "impact_summary": result.get("impact_summary", ""),
        }
    
    def _fallback_analysis(self) -> dict:
        """降级分析"""
        return {
            "impact_analysis": ImpactAnalysis(),
            "market_sentiment": MarketSentiment(),
            "risk_warnings": [],
            "recommendations": {},
            "impact_summary": "AI 分析不可用",
        }
