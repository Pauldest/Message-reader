"""Models 单元测试

测试 src/models/ 下的 Pydantic 模型
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.models.article import Article, EnrichedArticle
from src.models.information import (
    InformationUnit,
    InformationType,
    SourceReference,
    EntityAnchor,
    StateChangeType,
    ROOT_ENTITIES,
)


class TestArticle:
    """Article 模型测试"""
    
    def test_article_creation(self):
        """测试文章创建"""
        article = Article(
            url="https://example.com/test",
            title="测试文章标题",
            content="这是测试内容",
            source="测试来源"
        )
        
        assert article.url == "https://example.com/test"
        assert article.title == "测试文章标题"
        assert article.content == "这是测试内容"
        assert article.source == "测试来源"
    
    def test_article_default_values(self):
        """测试默认值"""
        article = Article(url="https://example.com", title="Title")
        
        assert article.content == ""
        assert article.summary == ""
        assert article.category == ""
        assert article.author == ""
        assert article.id is None
        assert article.fetched_at is not None
    
    def test_article_hash_and_equality(self):
        """测试哈希和相等性 - 基于 URL"""
        a1 = Article(url="https://example.com/1", title="Title 1")
        a2 = Article(url="https://example.com/1", title="Different Title")
        a3 = Article(url="https://example.com/2", title="Title 1")
        
        # 相同 URL 应该相等
        assert a1 == a2
        assert hash(a1) == hash(a2)
        
        # 不同 URL 不相等
        assert a1 != a3
        assert hash(a1) != hash(a3)
    
    def test_article_not_equal_to_non_article(self):
        """测试与非 Article 对象比较"""
        article = Article(url="https://example.com", title="Title")
        assert article != "not an article"
        assert article != {"url": "https://example.com"}


class TestEnrichedArticle:
    """EnrichedArticle 模型测试"""
    
    def test_from_article(self):
        """测试从 Article 创建 EnrichedArticle"""
        article = Article(
            url="https://example.com/test",
            title="原始标题",
            content="原始内容",
            source="来源"
        )
        
        enriched = EnrichedArticle.from_article(article)
        
        assert enriched.url == article.url
        assert enriched.title == article.title
        assert enriched.content == article.content
        assert enriched.source == article.source
    
    def test_tags_display_with_tags(self):
        """测试有标签时的显示"""
        enriched = EnrichedArticle(
            url="https://example.com",
            title="Title",
            tags=["科技", "人工智能", "GPT"]
        )
        
        assert enriched.tags_display == "科技 > 人工智能 > GPT"
    
    def test_tags_display_empty_uses_category(self):
        """测试无标签时使用分类"""
        enriched = EnrichedArticle(
            url="https://example.com",
            title="Title",
            category="财经"
        )
        
        assert enriched.tags_display == "财经"
    
    def test_to_digest_format(self):
        """测试转换为简报格式"""
        enriched = EnrichedArticle(
            url="https://example.com",
            title="测试标题",
            source="测试来源",
            overall_score=8.5,
            ai_summary="AI 生成摘要",
            tags=["科技"],
            is_top_pick=True
        )
        
        digest = enriched.to_digest_format()
        
        assert digest["title"] == "测试标题"
        assert digest["url"] == "https://example.com"
        assert digest["score"] == 8.5
        assert digest["is_top_pick"] is True
        assert "summary" in digest


class TestSourceReference:
    """SourceReference 模型测试"""
    
    def test_source_reference_creation(self):
        """测试来源引用创建"""
        source = SourceReference(
            url="https://example.com/article",
            title="文章标题",
            source_name="Example News"
        )
        
        assert source.url == "https://example.com/article"
        assert source.title == "文章标题"
        assert source.source_name == "Example News"
        assert source.credibility_tier == "unknown"
    
    def test_source_reference_equality(self):
        """测试来源引用相等性 - 基于 URL"""
        s1 = SourceReference(url="https://example.com/1", title="Title 1", source_name="Source")
        s2 = SourceReference(url="https://example.com/1", title="Different", source_name="Other")
        s3 = SourceReference(url="https://example.com/2", title="Title 1", source_name="Source")
        
        assert s1 == s2
        assert s1 != s3
    
    def test_source_reference_hash(self):
        """测试来源引用哈希"""
        s1 = SourceReference(url="https://example.com/1", title="Title", source_name="Source")
        s2 = SourceReference(url="https://example.com/1", title="Other", source_name="Other")
        
        assert hash(s1) == hash(s2)
    
    def test_source_reference_not_equal_to_non_source(self):
        """测试与非 SourceReference 对象比较"""
        source = SourceReference(url="https://example.com", title="Title", source_name="Source")
        assert source != "not a source"


class TestEntityAnchor:
    """EntityAnchor 模型测试"""
    
    def test_entity_anchor_creation(self):
        """测试实体锚点创建"""
        anchor = EntityAnchor(
            l1_name="OpenAI",
            l2_sector="基础模型",
            l3_root="人工智能"
        )
        
        assert anchor.l1_name == "OpenAI"
        assert anchor.l2_sector == "基础模型"
        assert anchor.l3_root == "人工智能"
    
    def test_entity_anchor_default_values(self):
        """测试默认值"""
        anchor = EntityAnchor(
            l1_name="Test",
            l2_sector="Sector",
            l3_root="Root"
        )
        
        assert anchor.l1_role == "主角"
        assert anchor.confidence == 0.8


class TestInformationUnit:
    """InformationUnit 模型测试"""
    
    def test_information_unit_creation(self):
        """测试信息单元创建"""
        unit = InformationUnit(
            id="test-id-123",
            fingerprint="fp-abc",
            type=InformationType.FACT,
            title="测试信息标题",
            content="详细内容描述"
        )
        
        assert unit.id == "test-id-123"
        assert unit.fingerprint == "fp-abc"
        assert unit.type == InformationType.FACT
        assert unit.title == "测试信息标题"
    
    def test_value_score_calculation(self):
        """测试价值评分计算"""
        unit = InformationUnit(
            id="test",
            fingerprint="fp",
            type=InformationType.EVENT,
            title="Test",
            content="Content",
            information_gain=8.0,
            actionability=7.0,
            scarcity=6.0,
            impact_magnitude=9.0
        )
        
        # 权重: 信息增量 30%, 行动指导 25%, 稀缺性 20%, 影响范围 25%
        expected = 8.0 * 0.30 + 7.0 * 0.25 + 6.0 * 0.20 + 9.0 * 0.25
        assert unit.value_score == expected
    
    def test_value_score_default_values(self):
        """测试默认值下的价值评分"""
        unit = InformationUnit(
            id="test",
            fingerprint="fp",
            type=InformationType.DATA,
            title="Test",
            content="Content"
        )
        
        # 默认所有维度都是 5.0
        assert unit.value_score == 5.0
    
    def test_source_count(self):
        """测试来源计数"""
        unit = InformationUnit(
            id="test",
            fingerprint="fp",
            type=InformationType.FACT,
            title="Test",
            content="Content",
            sources=[
                SourceReference(url="https://a.com", title="A", source_name="A"),
                SourceReference(url="https://b.com", title="B", source_name="B"),
            ]
        )
        
        assert unit.source_count == 2
    
    def test_merge_source_new(self):
        """测试添加新来源"""
        unit = InformationUnit(
            id="test",
            fingerprint="fp",
            type=InformationType.FACT,
            title="Test",
            content="Content"
        )
        
        new_source = SourceReference(
            url="https://new.com",
            title="New Source",
            source_name="New"
        )
        
        unit.merge_source(new_source)
        
        assert unit.source_count == 1
        assert unit.sources[0].url == "https://new.com"
    
    def test_merge_source_duplicate(self):
        """测试添加重复来源 - 应该被忽略"""
        source = SourceReference(url="https://existing.com", title="Existing", source_name="E")
        
        unit = InformationUnit(
            id="test",
            fingerprint="fp",
            type=InformationType.FACT,
            title="Test",
            content="Content",
            sources=[source]
        )
        
        # 尝试添加相同 URL 的来源
        duplicate = SourceReference(url="https://existing.com", title="Different", source_name="D")
        unit.merge_source(duplicate)
        
        # 应该仍然只有一个来源
        assert unit.source_count == 1


class TestInformationType:
    """InformationType 枚举测试"""
    
    def test_information_types(self):
        """测试信息类型枚举值"""
        assert InformationType.FACT.value == "fact"
        assert InformationType.OPINION.value == "opinion"
        assert InformationType.EVENT.value == "event"
        assert InformationType.DATA.value == "data"


class TestStateChangeType:
    """StateChangeType 枚举测试"""
    
    def test_state_change_types(self):
        """测试状态改变类型枚举值"""
        assert StateChangeType.TECH.value == "TECH"
        assert StateChangeType.CAPITAL.value == "CAPITAL"
        assert StateChangeType.REGULATION.value == "REGULATION"
        assert StateChangeType.ORG.value == "ORG"
        assert StateChangeType.RISK.value == "RISK"
        assert StateChangeType.SENTIMENT.value == "SENTIMENT"


class TestRootEntities:
    """ROOT_ENTITIES 常量测试"""
    
    def test_root_entities_not_empty(self):
        """测试根实体列表非空"""
        assert len(ROOT_ENTITIES) > 0
    
    def test_root_entities_contains_expected(self):
        """测试包含关键实体"""
        assert "人工智能" in ROOT_ENTITIES
        assert "半导体芯片" in ROOT_ENTITIES
        assert "宏观经济" in ROOT_ENTITIES
