"""Entity Store - 实体知识图谱存储服务"""

import json
import structlog
from datetime import datetime
from typing import Optional, List, Dict, Any

from ..models.entity import (
    Entity, EntityAlias, EntityMention, EntityRelation,
    EntityType, RelationType, ExtractedEntity, ExtractedRelation
)

logger = structlog.get_logger()


class EntityStore:
    """实体存储服务 - 管理实体、别名、提及和关系"""
    
    def __init__(self, db):
        """
        Args:
            db: Database 实例
        """
        self.db = db
        self._ensure_tables()
    
    def _ensure_tables(self):
        """确保实体相关表存在"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            # 1. 实体表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    type TEXT,
                    l3_root TEXT,
                    l2_sector TEXT,
                    attributes TEXT,
                    mention_count INTEGER DEFAULT 0,
                    first_mentioned TIMESTAMP,
                    last_mentioned TIMESTAMP,
                    created_at TIMESTAMP
                )
            """)
            
            # 2. 别名表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_aliases (
                    alias TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    is_primary BOOLEAN DEFAULT 0,
                    source TEXT,
                    created_at TIMESTAMP,
                    FOREIGN KEY(entity_id) REFERENCES entities(id)
                )
            """)
            
            # 索引
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_aliases_entity ON entity_aliases(entity_id)")
            
            # 3. 提及表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_mentions (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    unit_id TEXT NOT NULL,
                    role TEXT,
                    sentiment TEXT,
                    state_dimension TEXT,
                    state_delta TEXT,
                    event_time TIMESTAMP,
                    created_at TIMESTAMP,
                    FOREIGN KEY(entity_id) REFERENCES entities(id)
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mentions_entity ON entity_mentions(entity_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mentions_unit ON entity_mentions(unit_id)")
            
            # 4. 关系表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS entity_relations (
                    id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT,
                    strength REAL,
                    confidence REAL,
                    evidence_unit_ids TEXT,
                    valid_from TIMESTAMP,
                    valid_to TIMESTAMP,
                    created_at TIMESTAMP,
                    FOREIGN KEY(source_id) REFERENCES entities(id),
                    FOREIGN KEY(target_id) REFERENCES entities(id)
                )
            """)
            
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_source ON entity_relations(source_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_relations_target ON entity_relations(target_id)")
            
            conn.commit()
    
    # ==================== 实体管理 ====================
    
    def register_entity(self, entity: Entity) -> Entity:
        """注册新实体"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO entities 
                (id, canonical_name, type, l3_root, l2_sector, attributes, 
                 mention_count, first_mentioned, last_mentioned, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entity.id,
                entity.canonical_name,
                entity.type.value if isinstance(entity.type, EntityType) else entity.type,
                entity.l3_root,
                entity.l2_sector,
                json.dumps(entity.attributes),
                entity.mention_count,
                entity.first_mentioned,
                entity.last_mentioned,
                entity.created_at,
            ))
            conn.commit()
        
        logger.debug("entity_registered", entity_id=entity.id, name=entity.canonical_name)
        return entity
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """获取实体"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM entities WHERE id = ?", (entity_id,))
            row = cursor.fetchone()
            
        if not row:
            return None
            
        return self._row_to_entity(row)
    
    def get_entity_by_name(self, name: str) -> Optional[Entity]:
        """通过名称获取实体（先查别名表）"""
        entity_id = self.resolve_alias(name)
        if entity_id:
            return self.get_entity(entity_id)
        return None
    
    def _row_to_entity(self, row) -> Entity:
        """将数据库行转换为 Entity 对象"""
        return Entity(
            id=row[0],
            canonical_name=row[1],
            type=EntityType(row[2]) if row[2] in EntityType.__members__ else EntityType.COMPANY,
            l3_root=row[3] or "",
            l2_sector=row[4] or "",
            attributes=json.loads(row[5]) if row[5] else {},
            mention_count=row[6] or 0,
            first_mentioned=row[7],
            last_mentioned=row[8],
            created_at=row[9] or datetime.now(),
        )
    
    # ==================== 别名管理 ====================
    
    def add_alias(self, alias: str, entity_id: str, is_primary: bool = False, source: str = "ai"):
        """添加别名"""
        normalized_alias = alias.strip().lower()
        
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO entity_aliases 
                (alias, entity_id, is_primary, source, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (normalized_alias, entity_id, is_primary, source, datetime.now()))
            conn.commit()
        
        logger.debug("alias_added", alias=normalized_alias, entity_id=entity_id)
    
    def resolve_alias(self, alias: str) -> Optional[str]:
        """别名解析 - 返回实体ID"""
        normalized = alias.strip().lower()
        
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            # 精确匹配
            cursor.execute(
                "SELECT entity_id FROM entity_aliases WHERE alias = ?",
                (normalized,)
            )
            row = cursor.fetchone()
            
            if row:
                return row[0]
            
            # 模糊匹配
            cursor.execute(
                "SELECT entity_id FROM entity_aliases WHERE alias LIKE ? LIMIT 1",
                (f"%{normalized}%",)
            )
            row = cursor.fetchone()
            
            return row[0] if row else None
    
    def get_aliases(self, entity_id: str) -> List[str]:
        """获取实体的所有别名"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT alias FROM entity_aliases WHERE entity_id = ?",
                (entity_id,)
            )
            return [row[0] for row in cursor.fetchall()]
    
    # ==================== 提及管理 ====================
    
    def record_mention(self, mention: EntityMention) -> EntityMention:
        """记录实体提及"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO entity_mentions
                (id, entity_id, unit_id, role, sentiment, state_dimension, 
                 state_delta, event_time, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                mention.id,
                mention.entity_id,
                mention.unit_id,
                mention.role,
                mention.sentiment,
                mention.state_dimension,
                mention.state_delta,
                mention.event_time,
                mention.created_at,
            ))
            
            # 更新实体统计
            cursor.execute("""
                UPDATE entities SET 
                    mention_count = mention_count + 1,
                    last_mentioned = ?,
                    first_mentioned = COALESCE(first_mentioned, ?)
                WHERE id = ?
            """, (datetime.now(), datetime.now(), mention.entity_id))
            
            conn.commit()
        
        logger.debug("mention_recorded", mention_id=mention.id, entity_id=mention.entity_id)
        return mention
    
    def get_mentions_by_entity(
        self, 
        entity_id: str, 
        limit: int = 100,
        state_dimensions: List[str] = None
    ) -> List[EntityMention]:
        """获取实体的所有提及"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM entity_mentions WHERE entity_id = ?"
            params = [entity_id]
            
            if state_dimensions:
                placeholders = ",".join("?" * len(state_dimensions))
                query += f" AND state_dimension IN ({placeholders})"
                params.extend(state_dimensions)
            
            query += " ORDER BY event_time DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            return [self._row_to_mention(row) for row in cursor.fetchall()]
    
    def get_mentions_by_unit(self, unit_id: str) -> List[EntityMention]:
        """获取信息单元的所有实体提及"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM entity_mentions WHERE unit_id = ?",
                (unit_id,)
            )
            return [self._row_to_mention(row) for row in cursor.fetchall()]
    
    def _row_to_mention(self, row) -> EntityMention:
        return EntityMention(
            id=row[0],
            entity_id=row[1],
            unit_id=row[2],
            role=row[3] or "主角",
            sentiment=row[4] or "neutral",
            state_dimension=row[5] or "",
            state_delta=row[6] or "",
            event_time=row[7],
            created_at=row[8] or datetime.now(),
        )
    
    # ==================== 关系管理 ====================
    
    def add_relation(self, relation: EntityRelation) -> EntityRelation:
        """添加实体关系"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            # 检查是否已存在相同关系
            cursor.execute("""
                SELECT id, evidence_unit_ids FROM entity_relations 
                WHERE source_id = ? AND target_id = ? AND relation_type = ?
            """, (relation.source_id, relation.target_id, relation.relation_type.value))
            
            existing = cursor.fetchone()
            
            if existing:
                # 更新现有关系，合并 evidence
                existing_evidence = json.loads(existing[1]) if existing[1] else []
                new_evidence = list(set(existing_evidence + relation.evidence_unit_ids))
                
                cursor.execute("""
                    UPDATE entity_relations SET 
                        evidence_unit_ids = ?,
                        strength = ?,
                        confidence = ?
                    WHERE id = ?
                """, (json.dumps(new_evidence), relation.strength, relation.confidence, existing[0]))
                relation.id = existing[0]
            else:
                # 插入新关系
                cursor.execute("""
                    INSERT INTO entity_relations
                    (id, source_id, target_id, relation_type, strength, confidence,
                     evidence_unit_ids, valid_from, valid_to, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    relation.id,
                    relation.source_id,
                    relation.target_id,
                    relation.relation_type.value,
                    relation.strength,
                    relation.confidence,
                    json.dumps(relation.evidence_unit_ids),
                    relation.valid_from,
                    relation.valid_to,
                    relation.created_at,
                ))
            
            conn.commit()
        
        logger.debug("relation_added", 
                    source=relation.source_id, 
                    target=relation.target_id, 
                    type=relation.relation_type.value)
        return relation
    
    def get_relations(
        self, 
        entity_id: str, 
        direction: str = "both"
    ) -> List[EntityRelation]:
        """获取实体的所有关系"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            if direction == "outgoing":
                cursor.execute(
                    "SELECT * FROM entity_relations WHERE source_id = ?",
                    (entity_id,)
                )
            elif direction == "incoming":
                cursor.execute(
                    "SELECT * FROM entity_relations WHERE target_id = ?",
                    (entity_id,)
                )
            else:
                cursor.execute(
                    "SELECT * FROM entity_relations WHERE source_id = ? OR target_id = ?",
                    (entity_id, entity_id)
                )
            
            return [self._row_to_relation(row) for row in cursor.fetchall()]
    
    def _row_to_relation(self, row) -> EntityRelation:
        return EntityRelation(
            id=row[0],
            source_id=row[1],
            target_id=row[2],
            relation_type=RelationType(row[3]) if row[3] in [e.value for e in RelationType] else RelationType.PEER,
            strength=row[4] or 1.0,
            confidence=row[5] or 0.8,
            evidence_unit_ids=json.loads(row[6]) if row[6] else [],
            valid_from=row[7],
            valid_to=row[8],
            created_at=row[9] or datetime.now(),
        )
    
    # ==================== 高级查询 ====================
    
    def search_entities(self, query: str, limit: int = 10) -> List[Entity]:
        """搜索实体（通过别名）"""
        normalized = query.strip().lower()
        
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT e.* FROM entities e
                JOIN entity_aliases a ON e.id = a.entity_id
                WHERE a.alias LIKE ?
                ORDER BY e.mention_count DESC
                LIMIT ?
            """, (f"%{normalized}%", limit))
            
            return [self._row_to_entity(row) for row in cursor.fetchall()]
    
    def get_entity_timeline(
        self, 
        entity_id: str,
        start_date: datetime = None,
        end_date: datetime = None,
        state_dimensions: List[str] = None,
        limit: int = 50
    ) -> List[Dict]:
        """获取实体时间线"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            query = """
                SELECT m.*, u.title, u.summary 
                FROM entity_mentions m
                JOIN information_units u ON m.unit_id = u.id
                WHERE m.entity_id = ?
            """
            params = [entity_id]
            
            if start_date:
                query += " AND m.event_time >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND m.event_time <= ?"
                params.append(end_date)
            
            if state_dimensions:
                placeholders = ",".join("?" * len(state_dimensions))
                query += f" AND m.state_dimension IN ({placeholders})"
                params.extend(state_dimensions)
            
            query += " ORDER BY m.event_time DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    "mention_id": row[0],
                    "event_time": row[7],
                    "dimension": row[5],
                    "delta": row[6],
                    "unit_title": row[9] if len(row) > 9 else "",
                    "unit_summary": row[10] if len(row) > 10 else "",
                })
            
            return results
    
    def get_entity_network(self, entity_id: str, depth: int = 1) -> Dict:
        """获取实体关系网络"""
        entity = self.get_entity(entity_id)
        if not entity:
            return {}
        
        relations = self.get_relations(entity_id)
        
        # 获取关联实体
        related_entity_ids = set()
        for rel in relations:
            if rel.source_id != entity_id:
                related_entity_ids.add(rel.source_id)
            if rel.target_id != entity_id:
                related_entity_ids.add(rel.target_id)
        
        related_entities = []
        for rel_id in related_entity_ids:
            rel_entity = self.get_entity(rel_id)
            if rel_entity:
                related_entities.append(rel_entity)
        
        return {
            "entity": entity,
            "relations": relations,
            "related_entities": related_entities
        }
    
    # ==================== 从提取结果处理 ====================
    
    def process_extracted_entities(
        self, 
        unit_id: str,
        entities: List[ExtractedEntity],
        relations: List[ExtractedRelation] = None,
        event_time: datetime = None
    ):
        """处理从文本中提取的实体和关系"""
        entity_id_map = {}  # name -> entity_id
        
        for ext_entity in entities:
            # 1. 检查是否已存在
            existing_id = self.resolve_alias(ext_entity.name)
            
            if existing_id:
                entity_id = existing_id
            else:
                # 2. 创建新实体
                entity = Entity(
                    canonical_name=ext_entity.name,
                    type=EntityType(ext_entity.type) if ext_entity.type in EntityType.__members__ else EntityType.COMPANY,
                )
                self.register_entity(entity)
                entity_id = entity.id
                
                # 3. 添加别名
                self.add_alias(ext_entity.name, entity_id, is_primary=True)
                for alias in ext_entity.aliases:
                    self.add_alias(alias, entity_id)
            
            entity_id_map[ext_entity.name] = entity_id
            
            # 4. 记录提及
            state_change = ext_entity.state_change or {}
            mention = EntityMention(
                entity_id=entity_id,
                unit_id=unit_id,
                role=ext_entity.role,
                state_dimension=state_change.get("dimension", ""),
                state_delta=state_change.get("delta", ""),
                event_time=event_time,
            )
            self.record_mention(mention)
        
        # 5. 处理关系
        if relations:
            for ext_rel in relations:
                source_id = entity_id_map.get(ext_rel.source) or self.resolve_alias(ext_rel.source)
                target_id = entity_id_map.get(ext_rel.target) or self.resolve_alias(ext_rel.target)
                
                if source_id and target_id:
                    rel_type = ext_rel.relation.upper()
                    if rel_type in [e.value.upper() for e in RelationType]:
                        relation = EntityRelation(
                            source_id=source_id,
                            target_id=target_id,
                            relation_type=RelationType(rel_type.lower()),
                            evidence_unit_ids=[unit_id],
                        )
                        self.add_relation(relation)
        
        return entity_id_map
    
    # ==================== 统计 ====================
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM entities")
            entity_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM entity_aliases")
            alias_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM entity_mentions")
            mention_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM entity_relations")
            relation_count = cursor.fetchone()[0]
            
            return {
                "entities": entity_count,
                "aliases": alias_count,
                "mentions": mention_count,
                "relations": relation_count,
            }

    # ==================== 日报增强功能 ====================
    
    def get_hot_entities(self, days: int = 7, limit: int = 10) -> List[Dict]:
        """
        获取热点实体及其趋势变化
        
        Returns:
            [{"entity": Entity, "recent_count": int, "previous_count": int, "trend": "up/down/stable", "change_pct": float}]
        """
        from datetime import timedelta
        
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            now = datetime.now()
            recent_start = now - timedelta(days=days)
            previous_start = now - timedelta(days=days * 2)
            
            # 获取近期热门实体
            cursor.execute("""
                SELECT e.id, e.canonical_name, e.type, 
                       COUNT(m.id) as recent_count,
                       e.mention_count as total_count
                FROM entities e
                JOIN entity_mentions m ON e.id = m.entity_id
                WHERE m.created_at >= ?
                GROUP BY e.id
                ORDER BY recent_count DESC
                LIMIT ?
            """, (recent_start, limit))
            
            hot_entities = []
            for row in cursor.fetchall():
                entity_id = row[0]
                
                # 查询上一周期的提及次数
                cursor.execute("""
                    SELECT COUNT(*) FROM entity_mentions
                    WHERE entity_id = ? AND created_at >= ? AND created_at < ?
                """, (entity_id, previous_start, recent_start))
                previous_count = cursor.fetchone()[0]
                
                recent_count = row[3]
                
                # 计算趋势
                if previous_count == 0:
                    trend = "new" if recent_count > 0 else "stable"
                    change_pct = 100.0 if recent_count > 0 else 0.0
                else:
                    change_pct = ((recent_count - previous_count) / previous_count) * 100
                    if change_pct > 20:
                        trend = "up"
                    elif change_pct < -20:
                        trend = "down"
                    else:
                        trend = "stable"
                
                entity = self.get_entity(entity_id)
                if entity:
                    hot_entities.append({
                        "entity": entity,
                        "recent_count": recent_count,
                        "previous_count": previous_count,
                        "trend": trend,
                        "change_pct": round(change_pct, 1)
                    })
            
            return hot_entities
    
    def get_related_units_by_entity(self, entity_id: str, exclude_unit_ids: List[str] = None, limit: int = 5) -> List[Dict]:
        """
        获取与指定实体相关的其他文章
        
        Args:
            entity_id: 实体 ID
            exclude_unit_ids: 要排除的文章 ID 列表（已在精选中的）
            limit: 返回数量
            
        Returns:
            [{"unit_id": str, "title": str, "summary": str, "role": str}]
        """
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            exclude_clause = ""
            params = [entity_id]
            
            if exclude_unit_ids:
                placeholders = ",".join("?" * len(exclude_unit_ids))
                exclude_clause = f"AND m.unit_id NOT IN ({placeholders})"
                params.extend(exclude_unit_ids)
            
            params.append(limit)
            
            cursor.execute(f"""
                SELECT m.unit_id, u.title, u.summary, m.role
                FROM entity_mentions m
                JOIN information_units u ON m.unit_id = u.id
                WHERE m.entity_id = ? {exclude_clause}
                ORDER BY m.created_at DESC
                LIMIT ?
            """, params)
            
            results = []
            for row in cursor.fetchall():
                results.append({
                    "unit_id": row[0],
                    "title": row[1],
                    "summary": row[2][:100] if row[2] else "",
                    "role": row[3] or "相关"
                })
            
            return results
    
    def get_entities_for_units(self, unit_ids: List[str]) -> Dict[str, List[Entity]]:
        """
        获取多个信息单元涉及的实体
        
        Returns:
            {unit_id: [Entity, ...]}
        """
        with self.db._get_conn() as conn:
            cursor = conn.cursor()
            
            result = {}
            for unit_id in unit_ids:
                cursor.execute("""
                    SELECT DISTINCT e.* FROM entities e
                    JOIN entity_mentions m ON e.id = m.entity_id
                    WHERE m.unit_id = ?
                    ORDER BY e.mention_count DESC
                    LIMIT 5
                """, (unit_id,))
                
                entities = [self._row_to_entity(row) for row in cursor.fetchall()]
                result[unit_id] = entities
            
            return result
