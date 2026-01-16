"""Skeptic Analyst - 怀疑论者分析师"""

import time
from typing import Any
import structlog

from ..base import BaseAgent
from ...models.article import Article
from ...models.analysis import SourceCredibility, BiasAnalysis, FactCheckResult
from ...models.agent import AgentContext, AgentOutput
from ...services.llm import LLMService

logger = structlog.get_logger()


SKEPTIC_SYSTEM_PROMPT = """你是一位严谨的新闻审核员，专门寻找新闻报道中的问题和偏见。

你的职责是用批判性思维审视每一篇新闻：
1. **信源评估**：评估信息来源的可信度和历史记录
2. **逻辑分析**：检查论点是否有充分证据支持
3. **偏见检测**：分析措辞是否带有政治或情感倾向
4. **标题党检测**：判断标题是否与内容相符

你应该保持高度怀疑，但必须基于事实。不要捕风捉影，只指出有证据的问题。
你的分析会帮助读者更理性地看待新闻。"""

SKEPTIC_ANALYSIS_PROMPT = """请对这篇新闻进行批判性审查：

【新闻标题】
{title}

【来源】
{source}

【内容】
{content}

【背景信息】
{background}

请从以下几个方面进行分析：

1. **信源可信度**：这个来源可靠吗？有什么已知的偏见？
2. **标题分析**：标题是否准确反映内容？是否有标题党嫌疑？
3. **偏见检测**：文章是否使用了带有倾向性的措辞？
4. **逻辑漏洞**：论点是否有充分证据？有何逻辑问题？
5. **客观性评分**：总体客观性如何？

请按以下 JSON 格式返回：
```json
{{
  "source_credibility": {{
    "credibility_score": 7.5,
    "tier": "主流媒体/权威官媒/行业媒体/自媒体/未知",
    "known_biases": ["已知偏见1", "偏见2"],
    "reasoning": "评分理由"
  }},
  "bias_analysis": {{
    "political_leaning": "left/center-left/center/center-right/right",
    "emotional_tone": "objective/sensational/fear-mongering/optimistic/pessimistic",
    "bias_indicators": ["带偏见的措辞示例1", "示例2"],
    "objectivity_score": 7.0,
    "reasoning": "分析理由"
  }},
  "clickbait_analysis": {{
    "is_clickbait": false,
    "clickbait_score": 0.2,
    "title_accuracy": "标题与内容的匹配程度描述",
    "problematic_elements": ["问题元素1"]
  }},
  "logical_issues": [
    {{"issue": "问题描述", "severity": "low/medium/high", "evidence": "依据"}}
  ],
  "overall_assessment": {{
    "trust_score": 7.5,
    "key_concerns": ["主要问题1", "问题2"],
    "recommendation": "对读者的阅读建议"
  }}
}}
```"""


class SkepticAnalyst(BaseAgent):
    """
    怀疑论者分析师
    
    职责：
    1. 评估信源可信度
    2. 检测偏见和立场
    3. 识别标题党
    4. 发现逻辑漏洞
    """
    
    AGENT_NAME = "SkepticAnalyst"
    SYSTEM_PROMPT = SKEPTIC_SYSTEM_PROMPT
    
    # 已知媒体信源评级
    KNOWN_SOURCES = {
        # 权威官媒
        "新华社": {"tier": "权威官媒", "score": 8.5},
        "人民日报": {"tier": "权威官媒", "score": 8.0},
        "央视": {"tier": "权威官媒", "score": 8.0},
        "CCTV": {"tier": "权威官媒", "score": 8.0},
        # 主流媒体
        "Reuters": {"tier": "主流媒体", "score": 8.5},
        "路透社": {"tier": "主流媒体", "score": 8.5},
        "Bloomberg": {"tier": "主流媒体", "score": 8.0},
        "彭博": {"tier": "主流媒体", "score": 8.0},
        "Financial Times": {"tier": "主流媒体", "score": 8.0},
        # 科技媒体
        "TechCrunch": {"tier": "行业媒体", "score": 7.0},
        "The Verge": {"tier": "行业媒体", "score": 7.0},
        "36氪": {"tier": "行业媒体", "score": 6.5},
        "虎嗅": {"tier": "行业媒体", "score": 6.5},
        "少数派": {"tier": "行业媒体", "score": 7.0},
        # 社区
        "Hacker News": {"tier": "社区", "score": 6.0},
        "V2EX": {"tier": "社区", "score": 5.5},
    }
    
    async def process(self, article: Article, context: AgentContext) -> AgentOutput:
        """进行批判性分析"""
        start_time = time.time()
        self.log_start(article.title)
        
        total_tokens = {"prompt": 0, "completion": 0}
        
        # 构建 prompt
        background = context.historical_context or "无额外背景信息"
        
        user_prompt = SKEPTIC_ANALYSIS_PROMPT.format(
            title=article.title,
            source=article.source,
            content=article.content[:3000],
            background=background[:1000],
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
            analysis = self._parse_analysis(result, article)
        else:
            analysis = self._fallback_analysis(article)
        
        duration = time.time() - start_time
        
        trace = self.create_trace(
            input_summary=f"Article: {article.title}",
            output_summary=f"Trust score: {analysis.get('trust_score', 'N/A')}",
            duration=duration,
            token_usage=total_tokens,
        )
        
        self.log_complete(duration, f"Trust score: {analysis.get('trust_score', 'N/A')}")
        
        return AgentOutput(
            success=True,
            data=analysis,
            trace=trace,
        )
    
    def _parse_analysis(self, result: dict, article: Article) -> dict:
        """解析分析结果"""
        # 解析信源可信度
        src_data = result.get("source_credibility", {})
        
        # 检查是否有已知信源信息
        known_source = None
        for name, info in self.KNOWN_SOURCES.items():
            if name.lower() in article.source.lower():
                known_source = info
                break
        
        source_credibility = SourceCredibility(
            source_name=article.source,
            credibility_score=src_data.get("credibility_score", known_source["score"] if known_source else 5.0),
            tier=src_data.get("tier", known_source["tier"] if known_source else "未知"),
            known_biases=src_data.get("known_biases", []),
            reasoning=src_data.get("reasoning", ""),
        )
        
        # 解析偏见分析
        bias_data = result.get("bias_analysis", {})
        bias_analysis = BiasAnalysis(
            political_leaning=bias_data.get("political_leaning", "center"),
            emotional_tone=bias_data.get("emotional_tone", "objective"),
            bias_indicators=bias_data.get("bias_indicators", []),
            objectivity_score=bias_data.get("objectivity_score", 5.0),
            reasoning=bias_data.get("reasoning", ""),
        )
        
        # 标题党分数
        clickbait_data = result.get("clickbait_analysis", {})
        clickbait_score = clickbait_data.get("clickbait_score", 0.0)
        
        return {
            "source_credibility": source_credibility,
            "bias_analysis": bias_analysis,
            "clickbait_score": clickbait_score,
            "clickbait_analysis": clickbait_data,
            "logical_issues": result.get("logical_issues", []),
            "trust_score": result.get("overall_assessment", {}).get("trust_score", 5.0),
            "key_concerns": result.get("overall_assessment", {}).get("key_concerns", []),
            "recommendation": result.get("overall_assessment", {}).get("recommendation", ""),
        }
    
    def _fallback_analysis(self, article: Article) -> dict:
        """降级分析"""
        known_source = None
        for name, info in self.KNOWN_SOURCES.items():
            if name.lower() in article.source.lower():
                known_source = info
                break
        
        return {
            "source_credibility": SourceCredibility(
                source_name=article.source,
                credibility_score=known_source["score"] if known_source else 5.0,
                tier=known_source["tier"] if known_source else "未知",
            ),
            "bias_analysis": BiasAnalysis(),
            "clickbait_score": 0.0,
            "clickbait_analysis": {},
            "logical_issues": [],
            "trust_score": 5.0,
            "key_concerns": [],
            "recommendation": "AI 分析不可用，请自行判断",
        }
