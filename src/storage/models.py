"""数据模型定义"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Article(BaseModel):
    """文章模型"""
    id: Optional[int] = None
    url: str
    title: str
    content: str = ""
    summary: str = ""
    source: str = ""
    category: str = ""
    author: str = ""
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.now)
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        if isinstance(other, Article):
            return self.url == other.url
        return False


class AnalyzedArticle(Article):
    """分析后的文章"""
    score: float = 0.0  # 1-10 分
    ai_summary: str = ""  # AI 生成的一句话摘要
    is_top_pick: bool = False  # 是否精选
    reasoning: str = ""  # AI 评判理由
    tags: list[str] = Field(default_factory=list)  # 多层级标签：从宏观到微观
    analyzed_at: datetime = Field(default_factory=datetime.now)
    
    @property
    def tags_display(self) -> str:
        """标签显示格式：宏观 > 中观 > 微观"""
        return " > ".join(self.tags) if self.tags else ""


class DigestArticle(BaseModel):
    """简报中的文章"""
    title: str
    url: str
    source: str
    category: str
    score: float
    summary: str
    reasoning: str = ""
    is_top_pick: bool = False
    tags: list[str] = Field(default_factory=list)  # 多层级标签
    event_time: str = ""  # 事件发生时间
    
    @property
    def tags_display(self) -> str:
        """标签显示格式"""
        return " > ".join(self.tags) if self.tags else self.category


class DailyDigest(BaseModel):
    """每日简报"""
    date: datetime
    top_picks: list[DigestArticle] = Field(default_factory=list)
    other_articles: list[DigestArticle] = Field(default_factory=list)
    low_value_articles: list[DigestArticle] = Field(default_factory=list)  # 低价值内容
    total_fetched: int = 0
    total_analyzed: int = 0
    total_filtered: int = 0
    
    @property
    def summary_stats(self) -> str:
        return f"今日抓取 {self.total_fetched} 篇，分析 {self.total_analyzed} 篇，精选 {len(self.top_picks)} 篇"

