"""Librarian Agent - 背景调查员（RAG 核心）"""

import time
from typing import Any, Optional
import structlog

from .base import BaseAgent
from ..models.article import Article
from ..models.analysis import SimpleEntity, KnowledgeGraph
from ..models.agent import AgentContext, AgentOutput
from ..services.llm import LLMService
from ..storage.vector_store import VectorStore

logger = structlog.get_logger()


# Prompt 模板
LIBRARIAN_SYSTEM_PROMPT = """你是一位资深的新闻背景调查员，专门为新闻报道补充背景信息。

你的任务是：
1. 分析新闻中的关键实体，补充它们的背景信息
2. 回顾该话题的历史，找出相关的历史事件
3. 构建实体之间的关系图谱
4. 提供读者理解这条新闻所需的背景知识

你的分析应该客观、中立，只陈述事实，不做价值判断。"""

BACKGROUND_RESEARCH_PROMPT = """为这篇新闻补充背景信息：

【新闻标题】
{title}

【核心内容】
{summary}

【已识别的实体】
{entities_text}

【相关历史资料】
{related_articles}

请从以下几个方面进行背景调查：

1. **实体背景**：新闻中的核心人物/公司/产品有什么背景？
2. **历史回顾**：这个话题之前发生过什么相关事件？
3. **关系网络**：这些实体之间有什么关系？

请按以下 JSON 格式返回：
```json
{{
  "entity_backgrounds": [
    {{"entity": "实体名", "background": "背景描述", "key_facts": ["事实1", "事实2"]}}
  ],
  "historical_context": "历史背景概述（2-3段话）",
  "knowledge_graph": {{
    "nodes": [
      {{"id": "node_1", "name": "实体名", "type": "PERSON/COMPANY/etc"}}
    ],
    "edges": [
      {{"source": "node_1", "target": "node_2", "relation": "关系描述"}}
    ]
  }},
  "key_context_for_reader": "读者需要了解的关键背景（一段话）"
}}
```"""


class LibrarianAgent(BaseAgent):
    """
    背景调查员 Agent (RAG 核心)
    
    职责：
    1. 搜索本地知识库获取相关历史文章
    2. 补充实体的背景信息
    3. 构建知识图谱
    4. 生成历史背景摘要
    """
    
    AGENT_NAME = "Librarian"
    SYSTEM_PROMPT = LIBRARIAN_SYSTEM_PROMPT
    
    def __init__(self, llm_service: LLMService, vector_store: Optional[VectorStore] = None):
        super().__init__(llm_service)
        self.vector_store = vector_store
    
    async def process(self, article: Article, context: AgentContext) -> AgentOutput:
        """处理文章，补充背景信息"""
        start_time = time.time()
        self.log_start(article.title)
        
        total_tokens = {"prompt": 0, "completion": 0}
        
        # 获取已提取的实体
        entities = context.entities or []
        
        # 1. 搜索相关历史文章（RAG）
        related_articles = await self._search_related_articles(article, entities)
        context.related_articles = related_articles
        
        # 2. 构建 prompt
        entities_text = self._format_entities(entities)
        related_text = self._format_related_articles(related_articles)
        
        user_prompt = BACKGROUND_RESEARCH_PROMPT.format(
            title=article.title,
            summary=context.extracted_5w1h.get("core_summary", article.summary[:500]),
            entities_text=entities_text,
            related_articles=related_text,
        )
        
        # 3. 调用 LLM
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=2000,
            temperature=0.3,
            json_mode=True,
        )
        
        total_tokens["prompt"] += token_usage.get("prompt", 0)
        total_tokens["completion"] += token_usage.get("completion", 0)
        
        # 4. 解析结果
        if result:
            background_data = self._parse_background_result(result)
        else:
            background_data = self._fallback_background()
        
        # 5. 更新上下文
        context.historical_context = background_data.get("historical_context", "")
        context.knowledge_graph = background_data.get("knowledge_graph")
        
        # 6. 将文章添加到向量存储（供未来检索）
        await self._store_article(article, context)
        
        duration = time.time() - start_time
        
        trace = self.create_trace(
            input_summary=f"Article: {article.title}, {len(entities)} entities",
            output_summary=f"Background research completed",
            duration=duration,
            token_usage=total_tokens,
        )
        
        self.log_complete(duration, "Background research completed")
        
        return AgentOutput(
            success=True,
            data=background_data,
            trace=trace,
        )
    
    async def _search_related_articles(
        self, 
        article: Article, 
        entities: list[Entity]
    ) -> list[dict]:
        """搜索相关历史文章"""
        if not self.vector_store or not self.vector_store.is_available:
            return []
        
        # 构建搜索查询
        entity_names = [e.name for e in entities[:5]] if entities else []
        query = f"{article.title} {' '.join(entity_names)}"
        
        try:
            results = await self.vector_store.search(query, top_k=5)
            return results
        except Exception as e:
            logger.warning("vector_search_failed", error=str(e))
            return []
    
    def _format_entities(self, entities: list) -> str:
        """格式化实体列表"""
        if not entities:
            return "无已识别实体"
        
        lines = []
        for e in entities[:10]:  # 限制数量
            if hasattr(e, 'name'):
                lines.append(f"- {e.name} ({e.type}): {e.description}")
            elif isinstance(e, dict):
                lines.append(f"- {e.get('name', '')} ({e.get('type', '')}): {e.get('description', '')}")
        
        return "\n".join(lines) if lines else "无已识别实体"
    
    def _format_related_articles(self, articles: list[dict]) -> str:
        """格式化相关文章"""
        if not articles:
            return "无相关历史文章"
        
        lines = []
        for a in articles[:5]:
            title = a.get("title", "")
            content_preview = a.get("content", "")[:200]
            lines.append(f"- {title}\n  {content_preview}...")
        
        return "\n".join(lines) if lines else "无相关历史文章"
    
    def _parse_background_result(self, result: dict) -> dict:
        """解析背景研究结果"""
        # 解析知识图谱
        kg_data = result.get("knowledge_graph", {})
        knowledge_graph = None
        
        if kg_data and kg_data.get("nodes"):
            knowledge_graph = KnowledgeGraph()
            for node in kg_data.get("nodes", []):
                if isinstance(node, dict):
                    from ..models.analysis import KnowledgeGraphNode
                    knowledge_graph.nodes.append(KnowledgeGraphNode(
                        id=node.get("id", ""),
                        name=node.get("name", ""),
                        type=node.get("type", ""),
                    ))
            
            for edge in kg_data.get("edges", []):
                if isinstance(edge, dict):
                    from ..models.analysis import KnowledgeGraphEdge
                    knowledge_graph.edges.append(KnowledgeGraphEdge(
                        source=edge.get("source", ""),
                        target=edge.get("target", ""),
                        relation=edge.get("relation", ""),
                    ))
        
        return {
            "entity_backgrounds": result.get("entity_backgrounds", []),
            "historical_context": result.get("historical_context", ""),
            "knowledge_graph": knowledge_graph,
            "key_context": result.get("key_context_for_reader", ""),
        }
    
    def _fallback_background(self) -> dict:
        """降级背景信息"""
        return {
            "entity_backgrounds": [],
            "historical_context": "",
            "knowledge_graph": None,
            "key_context": "",
        }
    
    async def _store_article(self, article: Article, context: AgentContext):
        """将文章存储到向量库"""
        if not self.vector_store or not self.vector_store.is_available:
            return
        
        try:
            import hashlib
            article_id = hashlib.md5(article.url.encode()).hexdigest()
            
            await self.vector_store.add_article(
                article_id=article_id,
                title=article.title,
                content=article.content,
                metadata={
                    "source": article.source,
                    "category": article.category,
                    "url": article.url,
                }
            )
        except Exception as e:
            logger.warning("store_article_failed", error=str(e))
