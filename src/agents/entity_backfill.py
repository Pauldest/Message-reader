"""Entity Backfill Agent - 历史数据回填助手"""

import json
import asyncio
from typing import List, Dict
import structlog

from .base import BaseAgent
from ..models.information import InformationUnit
from ..models.entity import ExtractedEntity, ExtractedRelation
from ..models.agent import AgentOutput
from ..storage.entity_store import EntityStore
from ..storage.information_store import InformationStore

logger = structlog.get_logger()

BACKFILL_SYSTEM_PROMPT = """你是一个实体关系提取专家。
请分析输入的一段文本（包含标题和内容），提取其中涉及的实体（Entity）以及实体之间的关系（Relation）。

## 提取目标

1. **实体 (Entities)**
   - 提取文中出现的关键实体：公司(COMPANY)、人物(PERSON)、产品(PRODUCT)、机构(ORG)、概念(CONCEPT)
   - 识别实体的别名（简称、中文名、英文名）
   - 识别实体在文中的角色（主角/配角/提及）
   - 识别实体的状态变化（如有）

2. **关系 (Relations)**
   - 提取实体之间的关系，如：competitor(竞争), partner(合作), supplier(供应), customer(客户), investor(投资), ceo_of(CEO), founder_of(创始人) 等
   - 提取支撑该关系的原文证据

## 输出格式 (JSON)

```json
{
  "entities_mentioned": [
    {
      "name": "标准名称",
      "aliases": ["别名1", "别名2"],
      "type": "COMPANY",
      "role": "主角",
      "state_change": {"dimension": "TECH", "delta": "发布新产品"} // 可选
    }
  ],
  "entity_relations": [
    {
      "source": "实体A",
      "target": "实体B",
      "relation": "competitor",
      "evidence": "原文片段..."
    }
  ]
}
```

注意：
- JSON 必须合法
- 如果没有明显实体或关系，返回空列表
"""

class EntityBackfillAgent(BaseAgent):
    """
    负责扫描现有的 information_units，提取实体并填充到 entity_store
    """
    
    AGENT_NAME = "EntityBackfill"
    SYSTEM_PROMPT = BACKFILL_SYSTEM_PROMPT
    
    def __init__(self, llm_service, info_store: InformationStore, entity_store: EntityStore):
        super().__init__(llm_service)
        self.info_store = info_store
        self.entity_store = entity_store

    async def process(self, input_data: dict, context: dict) -> AgentOutput:
        """满足 BaseAgent 抽象方法要求，但实际不使用"""
        return AgentOutput.success(self.name, "EntityBackfillAgent uses run() instead of process()")
        
    async def run(self, limit: int = 100):
        """运行回填任务"""
        logger.info("backfill_started", limit=limit)
        
        # 1. 获取需要处理的单元
        units = self._get_pending_units(limit)
        logger.info("found_pending_units", count=len(units))
        
        if not units:
            logger.info("backfill_completed_no_units")
            return
        
        # 2. 逐个处理
        success_count = 0
        for unit in units:
            try:
                await self.process_unit(unit)
                success_count += 1
            except Exception as e:
                logger.error("backfill_unit_failed", unit_id=unit.id, error=str(e))
                
        logger.info("backfill_completed", success=success_count, total=len(units))
        
    def _get_pending_units(self, limit: int) -> List[InformationUnit]:
        """获取未进行实体提取的单元"""
        with self.info_store.db._get_conn() as conn:
            # 查询未处理过实体提取的单元
            cursor = conn.execute("""
                SELECT * FROM information_units
                WHERE entity_processed = FALSE OR entity_processed IS NULL
                ORDER BY created_at DESC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            return [self.info_store._row_to_unit(row) for row in rows]
            
    async def process_unit(self, unit: InformationUnit):
        """处理单个单元"""
        logger.debug("processing_unit", title=unit.title)
        
        user_prompt = f"""
        标题: {unit.title}
        摘要: {unit.summary}
        内容:
        {unit.content[:2000]}
        """
        
        try:
            result, token_usage = await self.invoke_llm(
                user_prompt=user_prompt,
                json_mode=True
            )
            
            if not result:
                logger.warning("llm_returned_empty", unit_id=unit.id)
                return
            
            # 解析结果
            extracted_entities = [
                ExtractedEntity(
                    name=e.get("name", ""),
                    aliases=e.get("aliases", []),
                    type=e.get("type", "COMPANY"),
                    role=e.get("role", "主角"),
                    state_change=e.get("state_change"),
                ) for e in result.get("entities_mentioned", []) if e.get("name")
            ]
            
            extracted_relations = [
                ExtractedRelation(
                    source=r.get("source", ""),
                    target=r.get("target", ""),
                    relation=r.get("relation", "peer"),
                    evidence=r.get("evidence", ""),
                ) for r in result.get("entity_relations", []) if r.get("source")
            ]
            
            # 存入 EntityStore
            if extracted_entities:
                self.entity_store.process_extracted_entities(
                    unit_id=unit.id,
                    entities=extracted_entities,
                    relations=extracted_relations,
                    event_time=None # 使用默认时间或从 content 解析
                )
                logger.debug("processed_entities", count=len(extracted_entities), unit_id=unit.id)
            else:
                # 即使没有实体，也标记为已处理，避免无限循环
                logger.info("no_entities_found", unit_id=unit.id)

            # 标记为已处理
            self._mark_unit_processed(unit.id)

        except Exception as e:
            logger.error("backfill_process_error", unit_id=unit.id, error=str(e))

    def _mark_unit_processed(self, unit_id: str):
        """标记信息单元为已处理实体提取"""
        with self.info_store.db._get_conn() as conn:
            conn.execute("""
                UPDATE information_units
                SET entity_processed = TRUE, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (unit_id,))
            conn.commit()
