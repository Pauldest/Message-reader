"""Information Store 单元测试

测试 src/storage/information_store.py
"""

import pytest
import tempfile
import os
from datetime import datetime

from src.storage.database import Database
from src.storage.information_store import InformationStore
from src.storage.vector_store import VectorStore
from src.models.information import (
    InformationUnit,
    InformationType,
    SourceReference,
)


class TestInformationStore:
    """InformationStore 测试"""
    
    def setup_method(self):
        """每个测试前创建临时数据库"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.db = Database(self.db_path)
        self.store = InformationStore(self.db)
    
    def teardown_method(self):
        """每个测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_unit(self, fingerprint: str = "fp-test", title: str = "测试标题") -> InformationUnit:
        """创建测试用的 InformationUnit"""
        return InformationUnit(
            id=f"id-{fingerprint}",
            fingerprint=fingerprint,
            type=InformationType.FACT,
            title=title,
            content="测试内容详情",
            summary="测试摘要",
            information_gain=7.0,
            actionability=6.0,
            scarcity=5.0,
            impact_magnitude=8.0,
        )
    
    def test_unit_exists_false_for_new(self):
        """测试不存在的单元返回 False"""
        exists = self.store.unit_exists("nonexistent-fingerprint")
        assert exists is False
    
    @pytest.mark.asyncio
    async def test_save_and_check_exists(self):
        """测试保存后检查存在"""
        unit = self._create_test_unit()
        await self.store.save_unit(unit)
        
        exists = self.store.unit_exists(unit.fingerprint)
        assert exists is True
    
    @pytest.mark.asyncio
    async def test_get_unit_by_id(self):
        """测试通过 ID 获取单元"""
        unit = self._create_test_unit()
        await self.store.save_unit(unit)
        
        retrieved = self.store.get_unit(unit.id)
        
        assert retrieved is not None
        assert retrieved.id == unit.id
        assert retrieved.title == unit.title
        assert retrieved.type == unit.type
    
    @pytest.mark.asyncio
    async def test_get_unit_by_fingerprint(self):
        """测试通过指纹获取单元"""
        unit = self._create_test_unit(fingerprint="unique-fp-123")
        await self.store.save_unit(unit)
        
        retrieved = self.store.get_unit_by_fingerprint("unique-fp-123")
        
        assert retrieved is not None
        assert retrieved.fingerprint == "unique-fp-123"
    
    def test_get_nonexistent_unit(self):
        """测试获取不存在的单元返回 None"""
        result = self.store.get_unit("nonexistent-id")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_save_unit_with_sources(self):
        """测试保存带来源的单元"""
        unit = self._create_test_unit()
        unit.sources = [
            SourceReference(
                url="https://source1.com",
                title="来源1",
                source_name="Source 1"
            ),
            SourceReference(
                url="https://source2.com",
                title="来源2",
                source_name="Source 2"
            )
        ]
        
        await self.store.save_unit(unit)
        
        retrieved = self.store.get_unit(unit.id)
        assert retrieved is not None
        assert len(retrieved.sources) == 2
    
    @pytest.mark.asyncio
    async def test_update_existing_unit(self):
        """测试更新已存在的单元"""
        unit = self._create_test_unit()
        await self.store.save_unit(unit)
        
        # 修改内容并再次保存
        unit.title = "更新后的标题"
        unit.importance_score = 9.0
        await self.store.save_unit(unit)
        
        retrieved = self.store.get_unit(unit.id)
        assert retrieved.title == "更新后的标题"
        assert retrieved.importance_score == 9.0
    
    @pytest.mark.asyncio
    async def test_get_unsent_units(self):
        """测试获取未发送单元"""
        # 创建并保存多个单元
        unit1 = self._create_test_unit(fingerprint="fp-1", title="单元1")
        unit2 = self._create_test_unit(fingerprint="fp-2", title="单元2")
        
        await self.store.save_unit(unit1)
        await self.store.save_unit(unit2)
        
        unsent = self.store.get_unsent_units(limit=10)
        assert len(unsent) == 2
    
    @pytest.mark.asyncio
    async def test_mark_units_sent(self):
        """测试标记单元已发送"""
        unit = self._create_test_unit()
        await self.store.save_unit(unit)
        
        # 标记已发送
        self.store.mark_units_sent([unit.id])
        
        # 应该不在未发送列表中
        unsent = self.store.get_unsent_units()
        assert len(unsent) == 0
    
    @pytest.mark.asyncio
    async def test_save_unit_with_entity_hierarchy(self):
        """测试保存带实体层级的单元"""
        from src.models.information import EntityAnchor
        
        unit = self._create_test_unit()
        unit.entity_hierarchy = [
            EntityAnchor(
                l1_name="OpenAI",
                l2_sector="基础模型",
                l3_root="人工智能"
            )
        ]
        
        await self.store.save_unit(unit)
        
        retrieved = self.store.get_unit(unit.id)
        assert retrieved is not None
        # 实体层级应该被序列化保存
    
    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Value dimensions (information_gain, etc.) not persisted in DB schema")
    async def test_save_unit_preserves_value_dimensions(self):
        """测试保存保留价值维度 - 目前 DB 中不保存这些字段"""
        unit = self._create_test_unit()
        unit.information_gain = 8.5
        unit.actionability = 7.5
        unit.scarcity = 6.5
        unit.impact_magnitude = 9.5
        
        await self.store.save_unit(unit)
        
        retrieved = self.store.get_unit(unit.id)
        assert retrieved.information_gain == 8.5
        assert retrieved.actionability == 7.5
        assert retrieved.scarcity == 6.5
        assert retrieved.impact_magnitude == 9.5


class TestInformationStoreWithVectorStore:
    """带向量存储的 InformationStore 测试"""
    
    def setup_method(self):
        """创建带向量存储的 store"""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.vector_path = os.path.join(self.temp_dir, "vectors")
        
        self.db = Database(self.db_path)
        self.vector_store = VectorStore(self.vector_path)
        self.store = InformationStore(self.db, vector_store=self.vector_store)
    
    def teardown_method(self):
        """清理"""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def _create_test_unit(self, fingerprint: str, title: str, content: str) -> InformationUnit:
        return InformationUnit(
            id=f"id-{fingerprint}",
            fingerprint=fingerprint,
            type=InformationType.FACT,
            title=title,
            content=content,
        )
    
    @pytest.mark.asyncio
    async def test_find_similar_units_no_results(self):
        """测试空库时没有相似结果"""
        unit = self._create_test_unit("fp-1", "测试", "内容")
        
        similar = await self.store.find_similar_units(unit, threshold=0.5)
        assert similar == []
    
    @pytest.mark.asyncio
    async def test_find_similar_units_with_data(self):
        """测试有数据时查找相似单元"""
        # 保存一些单元
        unit1 = self._create_test_unit(
            "fp-ai-1",
            "OpenAI 发布 GPT-5",
            "OpenAI 今日宣布发布新一代大语言模型 GPT-5，性能大幅提升。"
        )
        unit2 = self._create_test_unit(
            "fp-ai-2",
            "谷歌更新 Gemini",
            "谷歌发布 Gemini 2.0 版本，在多模态能力上有显著进步。"
        )
        unit3 = self._create_test_unit(
            "fp-finance",
            "美联储加息",
            "美联储宣布加息 25 个基点，市场反应平稳。"
        )
        
        await self.store.save_unit(unit1)
        await self.store.save_unit(unit2)
        await self.store.save_unit(unit3)
        
        # 查询 AI 相关的相似单元
        query_unit = self._create_test_unit(
            "fp-query",
            "GPT 新版本发布",
            "关于 GPT 大语言模型的最新版本发布消息。"
        )
        
        similar = await self.store.find_similar_units(query_unit, threshold=0.3, top_k=3)
        
        # 应该找到相似的 AI 相关单元
        assert len(similar) > 0
