"""Detective Analyst - 关系侦探分析师"""

import time
from typing import Any
import structlog

from ..base import BaseAgent
from ...models.article import Article
from ...models.analysis import SimpleEntity, KnowledgeGraph, KnowledgeGraphNode, KnowledgeGraphEdge
from ...models.agent import AgentContext, AgentOutput
from ...services.llm import LLMService

logger = structlog.get_logger()


DETECTIVE_SYSTEM_PROMPT = """你是一位调查记者和关系分析专家，专门挖掘新闻中的隐藏关系和利益链条。

你的调查重点：
1. **人物关系**：文中人物之间有什么关联？（商业伙伴、竞争对手、上下级等）
2. **公司背景**：涉及的公司有什么背景？股东是谁？关联公司有哪些？
3. **利益链条**：谁从这个事件中直接或间接受益？谁受损？
4. **隐藏关联**：表面上无关的事物之间是否有隐藏联系？

你需要像侦探一样，发现表面信息背后的真相和关系网络。
如果没有足够的信息，请诚实说明，不要捏造事实。"""

DETECTIVE_ANALYSIS_PROMPT = """作为关系侦探，分析这篇新闻中的人物和利益关系：

【新闻标题】
{title}

【核心内容】
{summary}

【已识别的实体】
{entities}

【已知背景】
{background}

请从以下几个方面进行调查：

1. **实体关系映射**：这些实体之间有什么关系？
2. **利益分析**：谁是这个事件的受益者？谁可能受损？
3. **隐藏关联**：有没有表面上不明显但存在的关联？
4. **关键人物画像**：核心人物的背景和可能的动机

请按以下 JSON 格式返回：
```json
{{
  "entity_relationships": [
    {{
      "entity1": "实体A",
      "entity2": "实体B",
      "relationship": "关系类型（如：竞争对手、投资方、合作伙伴等）",
      "description": "关系描述",
      "confidence": 0.8
    }}
  ],
  "stakeholder_analysis": {{
    "beneficiaries": [
      {{"entity": "受益方", "benefit": "受益描述", "magnitude": "low/medium/high"}}
    ],
    "losers": [
      {{"entity": "受损方", "loss": "损失描述", "magnitude": "low/medium/high"}}
    ],
    "neutral_parties": [
      {{"entity": "中立方", "role": "角色描述"}}
    ]
  }},
  "hidden_connections": [
    {{
      "connection": "隐藏关联描述",
      "entities_involved": ["相关实体"],
      "significance": "重要性说明",
      "confidence": 0.6
    }}
  ],
  "key_player_profiles": [
    {{
      "name": "关键人物名",
      "role": "角色",
      "background": "背景简介",
      "possible_motivations": ["可能的动机"],
      "relationships": ["与其他实体的关系"]
    }}
  ],
  "knowledge_graph": {{
    "nodes": [
      {{"id": "node_1", "name": "实体名", "type": "PERSON/COMPANY/etc", "role": "角色"}}
    ],
    "edges": [
      {{"source": "node_1", "target": "node_2", "relation": "关系", "weight": 0.8}}
    ]
  }},
  "investigation_summary": "调查总结（一段话）"
}}
```"""


class DetectiveAnalyst(BaseAgent):
    """
    关系侦探分析师
    
    职责：
    1. 挖掘实体之间的关系
    2. 分析利益链条（谁受益、谁受损）
    3. 发现隐藏关联
    4. 构建详细的知识图谱
    """
    
    AGENT_NAME = "DetectiveAnalyst"
    SYSTEM_PROMPT = DETECTIVE_SYSTEM_PROMPT
    
    async def process(self, article: Article, context: AgentContext) -> AgentOutput:
        """进行关系调查分析"""
        start_time = time.time()
        self.log_start(article.title)
        
        total_tokens = {"prompt": 0, "completion": 0}
        
        # 格式化实体
        entities = context.entities or []
        entities_text = self._format_entities(entities)
        
        # 构建 prompt
        user_prompt = DETECTIVE_ANALYSIS_PROMPT.format(
            title=article.title,
            summary=context.extracted_5w1h.get("core_summary", article.summary[:500]),
            entities=entities_text,
            background=context.historical_context[:1000] if context.historical_context else "无额外背景",
        )
        
        # 调用 LLM
        result, token_usage = await self.invoke_llm(
            user_prompt=user_prompt,
            max_tokens=2500,
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
            input_summary=f"Article: {article.title}, {len(entities)} entities",
            output_summary=f"Found {len(analysis.get('entity_relationships', []))} relationships",
            duration=duration,
            token_usage=total_tokens,
        )
        
        self.log_complete(duration, f"Found {len(analysis.get('entity_relationships', []))} relationships")
        
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
        for e in entities[:15]:
            if hasattr(e, 'name'):
                lines.append(f"- {e.name} ({e.type}): {e.description}")
            elif isinstance(e, dict):
                lines.append(f"- {e.get('name', '')} ({e.get('type', '')}): {e.get('description', '')}")
        
        return "\n".join(lines) if lines else "无已识别实体"
    
    def _parse_analysis(self, result: dict) -> dict:
        """解析分析结果"""
        # 解析知识图谱
        kg_data = result.get("knowledge_graph", {})
        knowledge_graph = KnowledgeGraph()
        
        for node in kg_data.get("nodes", []):
            if isinstance(node, dict):
                knowledge_graph.nodes.append(KnowledgeGraphNode(
                    id=node.get("id", ""),
                    name=node.get("name", ""),
                    type=node.get("type", ""),
                    properties={"role": node.get("role", "")},
                ))
        
        for edge in kg_data.get("edges", []):
            if isinstance(edge, dict):
                knowledge_graph.edges.append(KnowledgeGraphEdge(
                    source=edge.get("source", ""),
                    target=edge.get("target", ""),
                    relation=edge.get("relation", ""),
                    properties={"weight": edge.get("weight", 1.0)},
                ))
        
        return {
            "entity_relationships": result.get("entity_relationships", []),
            "stakeholder_analysis": result.get("stakeholder_analysis", {}),
            "hidden_connections": result.get("hidden_connections", []),
            "key_player_profiles": result.get("key_player_profiles", []),
            "knowledge_graph": knowledge_graph,
            "investigation_summary": result.get("investigation_summary", ""),
        }
    
    def _fallback_analysis(self) -> dict:
        """降级分析"""
        return {
            "entity_relationships": [],
            "stakeholder_analysis": {},
            "hidden_connections": [],
            "key_player_profiles": [],
            "knowledge_graph": KnowledgeGraph(),
            "investigation_summary": "AI 分析不可用",
        }
