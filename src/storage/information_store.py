"""Information Store - 信息单元持久化存储"""

import json
import sqlite3
from typing import Optional, List, Dict
from datetime import datetime
import structlog

from .database import Database
from .vector_store import VectorStore
from ..models.information import InformationUnit, SourceReference, InformationType

logger = structlog.get_logger()


class InformationStore:
    """信息单元存储管理"""
    
    def __init__(self, db: Database, vector_store: VectorStore = None):
        self.db = db
        self.vector_store = vector_store

    
    def unit_exists(self, fingerprint: str) -> bool:
        """检查信息单元是否已存在（通过指纹）"""
        with self.db._get_conn() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM information_units WHERE fingerprint = ?",
                (fingerprint,)
            )
            return cursor.fetchone() is not None
    
    def get_unit_by_fingerprint(self, fingerprint: str) -> Optional[InformationUnit]:
        """通过指纹获取信息单元"""
        with self.db._get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM information_units WHERE fingerprint = ?",
                (fingerprint,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            unit = self._row_to_unit(row)
            
            # 加载来源
            sources = self._get_sources(conn, fingerprint)
            unit.sources = sources
            
            return unit
            
    def get_unit(self, unit_id: str) -> Optional[InformationUnit]:
        """通过 ID 获取信息单元"""
        with self.db._get_conn() as conn:
            cursor = conn.execute(
                "SELECT * FROM information_units WHERE id = ?",
                (unit_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            unit = self._row_to_unit(row)
            
            # 加载来源
            sources = self._get_sources(conn, unit.fingerprint)
            unit.sources = sources
            
            return unit
    
    def save_unit(self, unit: InformationUnit):
        """保存或更新信息单元"""
        with self.db._get_conn() as conn:
            # 1. 保存主体信息
            self._save_unit_record(conn, unit)
            
            # 2. 保存来源引用 (先删除旧的再插入，或者只插入新的？)
            # 策略：删除该单元的所有旧来源，重新插入当前的 sources 列表
            conn.execute(
                "DELETE FROM source_references WHERE unit_fingerprint = ?",
                (unit.fingerprint,)
            )
            
            for source in unit.sources:
                self._save_source_record(conn, unit.fingerprint, source)
                
            conn.commit()
        
        # 3. 同步更新向量存储（用于语义搜索）
        if self.vector_store:
            import asyncio
            try:
                # 构建搜索文本：标题 + 摘要 + 关键洞察
                search_text = f"{unit.title} {unit.summary} {' '.join(unit.key_insights)}"
                asyncio.get_event_loop().run_until_complete(
                    self.vector_store.add_article(
                        article_id=unit.id,
                        title=unit.title,
                        content=search_text,
                        metadata={
                            "fingerprint": unit.fingerprint,
                            "type": unit.type.value,
                            "importance": unit.importance_score
                        }
                    )
                )
            except RuntimeError:
                # 如果没有事件循环，创建一个临时的
                asyncio.run(
                    self.vector_store.add_article(
                        article_id=unit.id,
                        title=unit.title,
                        content=search_text,
                        metadata={
                            "fingerprint": unit.fingerprint,
                            "type": unit.type.value,
                            "importance": unit.importance_score
                        }
                    )
                )
            except Exception as e:
                logger.warning("vector_store_update_failed", error=str(e))
    
    async def find_similar_units(self, unit: InformationUnit, threshold: float = 0.65, top_k: int = 3) -> List[InformationUnit]:
        """
        使用向量相似度搜索找到与给定单元语义相似的已存在单元
        
        Args:
            unit: 待比较的信息单元
            threshold: 相似度阈值 (0-1)，超过此值视为相似
            top_k: 返回最相似的前 k 个结果
            
        Returns:
            相似的 InformationUnit 列表
        """
        if not self.vector_store:
            logger.debug("vector_store_not_available_for_similarity_search")
            return []
        
        # 构建搜索查询
        query = f"{unit.title} {unit.summary} {' '.join(unit.key_insights[:3])}"
        
        try:
            results = await self.vector_store.search(query, top_k=top_k)
            
            similar_units = []
            for r in results:
                # 跳过自身
                if r["id"] == unit.id:
                    continue
                    
                # 检查相似度阈值
                if r.get("score", 0) >= threshold:
                    existing_unit = self.get_unit(r["id"])
                    if existing_unit:
                        similar_units.append(existing_unit)
                        logger.info(
                            "similar_unit_found",
                            new_title=unit.title[:30],
                            existing_title=existing_unit.title[:30],
                            score=r["score"]
                        )
            
            return similar_units
            
        except Exception as e:
            logger.warning("similarity_search_failed", error=str(e))
            return []

            
    def _save_unit_record(self, conn: sqlite3.Connection, unit: InformationUnit):
        """保存信息单元记录"""
        columns = [
            "id", "fingerprint", "type", "title", "content", "summary",
            "analysis_content", "key_insights", "analysis_depth_score",
            "who", "what", "when_time", "where_place", "why", "how",
            "primary_source", "extraction_confidence", "credibility_score",
            "importance_score", "sentiment", "impact_assessment",
            "related_unit_ids", "entities", "tags", "merged_count", "is_sent",
            "updated_at"
        ]
        
        values = [
            unit.id,
            unit.fingerprint,
            unit.type.value,
            unit.title,
            unit.content,
            unit.summary,
            unit.analysis_content,
            json.dumps(unit.key_insights, ensure_ascii=False),
            unit.analysis_depth_score,
            json.dumps(unit.who, ensure_ascii=False),
            unit.what,
            unit.when,
            unit.where,
            unit.why,
            unit.how,
            unit.primary_source,
            unit.extraction_confidence,
            unit.credibility_score,
            unit.importance_score,
            unit.sentiment,
            unit.impact_assessment,
            json.dumps(unit.related_unit_ids, ensure_ascii=False),
            json.dumps([e.model_dump() for e in unit.entities], ensure_ascii=False),
            json.dumps(unit.tags, ensure_ascii=False),
            unit.merged_count,
            unit.is_sent,
            datetime.now()
        ]
        
        placeholders = ",".join(["?"] * len(columns))
        sql = f"""
            INSERT OR REPLACE INTO information_units ({",".join(columns)}, created_at)
            VALUES ({placeholders}, COALESCE((SELECT created_at FROM information_units WHERE id=?), CURRENT_TIMESTAMP))
        """
        # 添加 id 到参数列表末尾用于子查询
        values.append(unit.id)
        
        conn.execute(sql, values)

    def _save_source_record(self, conn: sqlite3.Connection, fingerprint: str, source: SourceReference):
        """保存来源记录"""
        conn.execute("""
            INSERT INTO source_references 
            (unit_fingerprint, url, title, source_name, published_at, excerpt, credibility_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            fingerprint,
            source.url,
            source.title,
            source.source_name,
            source.published_at,
            source.excerpt,
            source.credibility_tier
        ))

    def _get_sources(self, conn: sqlite3.Connection, fingerprint: str) -> List[SourceReference]:
        """获取来源列表"""
        cursor = conn.execute(
            "SELECT * FROM source_references WHERE unit_fingerprint = ?",
            (fingerprint,)
        )
        sources = []
        for row in cursor.fetchall():
            sources.append(SourceReference(
                url=row["url"],
                title=row["title"],
                source_name=row["source_name"],
                published_at=row["published_at"],
                excerpt=row["excerpt"],
                credibility_tier=row["credibility_tier"]
            ))
        return sources

    def get_unsent_units(self, limit: int = 100) -> List[InformationUnit]:
        """获取未发送的信息单元"""
        with self.db._get_conn() as conn:
            cursor = conn.execute("""
                SELECT * FROM information_units 
                WHERE is_sent = 0
                ORDER BY analysis_depth_score DESC, importance_score DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            units = []
            for row in rows:
                unit = self._row_to_unit(row)
                # Load sources
                unit.sources = self._get_sources(conn, unit.fingerprint)
                units.append(unit)
            return units

    def mark_units_sent(self, unit_ids: List[str]):
        """标记信息单元已发送"""
        with self.db._get_conn() as conn:
            now = datetime.now()
            placeholders = ",".join(["?"] * len(unit_ids))
            conn.execute(
                f"UPDATE information_units SET is_sent = 1, updated_at = ? WHERE id IN ({placeholders})",
                (now, *unit_ids)
            )
            conn.commit()
    
    def _row_to_unit(self, row: sqlite3.Row) -> InformationUnit:
        """将数据库行转换为对象"""
        def parse_json(field_name: str, default=None):
            val = row[field_name]
            if not val:
                return default or []
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return default or []

        entities_data = parse_json("entities")
        from ..models.analysis import Entity  # 延迟导入避免循环依赖
        entities = [Entity(**e) for e in entities_data]

        return InformationUnit(
            id=row["id"],
            fingerprint=row["fingerprint"],
            type=InformationType(row["type"]),
            title=row["title"],
            content=row["content"] or "",
            summary=row["summary"] or "",
            analysis_content=row["analysis_content"] or "",
            key_insights=parse_json("key_insights"),
            analysis_depth_score=row["analysis_depth_score"] or 0.0,
            who=parse_json("who"),
            what=row["what"] or "",
            when=row["when_time"] or "",  # 注意字段名映射
            where=row["where_place"] or "",
            why=row["why"] or "",
            how=row["how"] or "",
            primary_source=row["primary_source"] or "",
            extraction_confidence=row["extraction_confidence"] or 0.0,
            credibility_score=row["credibility_score"] or 0.0,
            importance_score=row["importance_score"] or 0.0,
            sentiment=row["sentiment"] or "",
            impact_assessment=row["impact_assessment"] or "",
            related_unit_ids=parse_json("related_unit_ids"),
            entities=entities,
            tags=parse_json("tags"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            merged_count=row["merged_count"],
            is_sent=bool(row["is_sent"]),
            sources=[] # 调用者负责填充
        )
