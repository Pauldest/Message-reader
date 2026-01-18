"""Collector Agent - 信息收集和初步处理"""

import time
from typing import Any
import structlog

from .base import BaseAgent
from ..models.article import Article
from ..models.analysis import SimpleEntity, TimelineEvent
from ..models.agent import AgentContext, AgentOutput
from ..services.llm import LLMService

logger = structlog.get_logger()


# Prompt 模板
COLLECTOR_SYSTEM_PROMPT = """你是一位专业的新闻编辑助手，负责对新闻进行初步分析和信息提取。

你的任务是：
1. 提取新闻的 5W1H（Who, What, When, Where, Why, How）
2. 识别新闻中的关键实体（人物、公司、产品、地点等）
3. 如果新闻涉及多个时间点的事件，梳理时间线
4. 生成一句话核心摘要

请确保提取的信息准确、客观，不添加任何主观判断。"""

EXTRACT_5W1H_PROMPT = """分析这篇新闻，提取结构化信息：

【新闻标题】
{title}

【新闻来源】
{source}

【新闻内容】
{content}

请严格按照以下 JSON 格式返回：
```json
{{
  "who": ["涉及的人物或组织列表"],
  "what": "发生了什么事（一句话概括）",
  "when": "时间（具体日期或时间段，如果文中未明确提及则填'未明确'）",
  "where": "地点（如果文中未明确提及则填'未明确'）",
  "why": "事件发生的原因或背景",
  "how": "事件的过程或方式",
  "core_summary": "一句话核心摘要（不超过50字）",
  "entities": [
    {{"name": "实体名", "type": "PERSON/COMPANY/PRODUCT/LOCATION/LAW/EVENT/TECHNOLOGY", "description": "简短描述"}}
  ],
  "timeline": [
    {{"time": "时间点", "event": "发生了什么", "importance": "high/normal/low"}}
  ],
  "tags": ["标签1", "标签2", "标签3"]
}}
```

注意：
1. entities 应包含所有重要的实体，type 必须是以上类型之一
2. timeline 只在新闻涉及多个时间点时填写，否则留空数组
3. tags 应该是 2-4 个从宏观到微观的标签，如 ["科技", "人工智能", "大语言模型"]"""


class CollectorAgent(BaseAgent):
    """
    信息收集员 Agent
    
    职责：
    1. 清洗文章内容
    2. 提取 5W1H 信息
    3. 识别关键实体
    4. 梳理时间线
    5. 生成核心摘要
    """
    
    AGENT_NAME = "Collector"
    SYSTEM_PROMPT = COLLECTOR_SYSTEM_PROMPT
    
    async def process(self, article: Article, context: AgentContext) -> AgentOutput:
        """处理文章，提取基础信息"""
        start_time = time.time()
        self.log_start(article.title)
        
        total_tokens = {"prompt": 0, "completion": 0}
        
        # 清洗内容
        cleaned_content = self._clean_content(article.content)
        
        # 构建 prompt
        user_prompt = EXTRACT_5W1H_PROMPT.format(
            title=article.title,
            source=article.source,
            content=cleaned_content[:3000],  # 限制长度
        )
        
        # 调用 LLM
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=2000,
            temperature=0.2,
            json_mode=True,
        )
        
        total_tokens["prompt"] += token_usage.get("prompt", 0)
        total_tokens["completion"] += token_usage.get("completion", 0)
        
        # 解析结果
        if result:
            extracted = self._parse_extraction_result(result)
        else:
            extracted = self._fallback_extraction(article)
        
        # 更新上下文
        context.cleaned_content = cleaned_content
        context.extracted_5w1h = extracted
        context.entities = extracted.get("entities", [])
        
        duration = time.time() - start_time
        
        # 创建追踪
        trace = self.create_trace(
            input_summary=f"Article: {article.title}",
            output_summary=f"Extracted 5W1H, {len(extracted.get('entities', []))} entities",
            duration=duration,
            token_usage=total_tokens,
        )
        
        self.log_complete(duration, f"{len(extracted.get('entities', []))} entities extracted")
        
        return AgentOutput(
            success=True,
            data=extracted,
            trace=trace,
        )
    
    def _clean_content(self, content: str) -> str:
        """清洗文章内容"""
        import re
        
        if not content:
            return ""
        
        # 移除 HTML 标签
        content = re.sub(r'<[^>]+>', '', content)
        
        # 移除多余空白
        content = re.sub(r'\s+', ' ', content)
        
        # 移除常见的无用内容
        noise_patterns = [
            r'点击阅读原文.*',
            r'关注我们.*',
            r'扫码关注.*',
            r'分享到微信.*',
            r'责任编辑.*',
            r'来源：.*(?=\n|$)',
        ]
        for pattern in noise_patterns:
            content = re.sub(pattern, '', content, flags=re.IGNORECASE)
        
        return content.strip()
    
    def _parse_extraction_result(self, result: dict) -> dict:
        """解析 LLM 返回的提取结果"""
        # 解析实体
        entities = []
        for e in result.get("entities", []):
            if isinstance(e, dict) and "name" in e:
                entities.append(Entity(
                    name=e.get("name", ""),
                    type=e.get("type", "UNKNOWN"),
                    description=e.get("description", ""),
                ))
        
        # 解析时间线
        timeline = []
        for t in result.get("timeline", []):
            if isinstance(t, dict) and "time" in t:
                timeline.append(TimelineEvent(
                    time=t.get("time", ""),
                    event=t.get("event", ""),
                    importance=t.get("importance", "normal"),
                ))
        
        return {
            "who": result.get("who", []),
            "what": result.get("what", ""),
            "when": result.get("when", ""),
            "where": result.get("where", ""),
            "why": result.get("why", ""),
            "how": result.get("how", ""),
            "core_summary": result.get("core_summary", ""),
            "entities": entities,
            "timeline": timeline,
            "tags": result.get("tags", []),
        }
    
    def _fallback_extraction(self, article: Article) -> dict:
        """降级提取（不使用 AI）"""
        return {
            "who": [],
            "what": article.title,
            "when": "",
            "where": "",
            "why": "",
            "how": "",
            "core_summary": article.summary[:100] if article.summary else article.title,
            "entities": [],
            "timeline": [],
            "tags": [article.category] if article.category else [],
        }
