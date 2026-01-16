"""SQLite 数据库操作"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import structlog

from .models import Article, AnalyzedArticle

logger = structlog.get_logger()


class Database:
    """SQLite 数据库管理"""
    
    def __init__(self, db_path: str = "data/articles.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """初始化数据库表"""
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT,
                    summary TEXT,
                    source TEXT,
                    category TEXT,
                    author TEXT,
                    published_at TIMESTAMP,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    score REAL DEFAULT 0,
                    ai_summary TEXT,
                    is_top_pick BOOLEAN DEFAULT FALSE,
                    reasoning TEXT,
                    tags TEXT,
                    analyzed_at TIMESTAMP,
                    sent_at TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles(fetched_at)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_articles_sent_at ON articles(sent_at)
            """)
            
            conn.commit()
        
        logger.info("database_initialized", path=str(self.db_path))
    
    def article_exists(self, url: str) -> bool:
        """检查文章是否已存在"""
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM articles WHERE url = ?",
                (url,)
            )
            return cursor.fetchone() is not None
    
    def save_article(self, article: Article) -> int:
        """保存文章"""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                INSERT OR REPLACE INTO articles 
                (url, title, content, summary, source, category, author, published_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article.url,
                article.title,
                article.content,
                article.summary,
                article.source,
                article.category,
                article.author,
                article.published_at,
                article.fetched_at,
            ))
            conn.commit()
            return cursor.lastrowid
    
    def save_analyzed_article(self, article: AnalyzedArticle) -> int:
        """保存分析后的文章"""
        with self._get_conn() as conn:
            # 将 tags 列表序列化为 JSON
            tags_json = json.dumps(article.tags, ensure_ascii=False) if article.tags else None
            
            cursor = conn.execute("""
                INSERT OR REPLACE INTO articles 
                (url, title, content, summary, source, category, author, published_at, fetched_at,
                 score, ai_summary, is_top_pick, reasoning, tags, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                article.url,
                article.title,
                article.content,
                article.summary,
                article.source,
                article.category,
                article.author,
                article.published_at,
                article.fetched_at,
                article.score,
                article.ai_summary,
                article.is_top_pick,
                article.reasoning,
                tags_json,
                article.analyzed_at,
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_unsent_articles(self, limit: int = 100) -> list[AnalyzedArticle]:
        """获取未发送的已分析文章"""
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT * FROM articles 
                WHERE analyzed_at IS NOT NULL AND sent_at IS NULL
                ORDER BY score DESC, analyzed_at DESC
                LIMIT ?
            """, (limit,))
            
            rows = cursor.fetchall()
            return [self._row_to_analyzed_article(row) for row in rows]
    
    def mark_articles_sent(self, urls: list[str]):
        """标记文章已发送"""
        with self._get_conn() as conn:
            now = datetime.now()
            for url in urls:
                conn.execute(
                    "UPDATE articles SET sent_at = ? WHERE url = ?",
                    (now, url)
                )
            conn.commit()
    
    def get_recent_sent_articles(self, days: int = 3, limit: int = 50) -> list[dict]:
        """获取最近几天已发送的文章摘要（用于跨日去重）"""
        cutoff_date = datetime.now() - timedelta(days=days)
        with self._get_conn() as conn:
            cursor = conn.execute("""
                SELECT title, ai_summary, tags, sent_at FROM articles 
                WHERE sent_at IS NOT NULL AND sent_at > ?
                ORDER BY sent_at DESC
                LIMIT ?
            """, (cutoff_date, limit))
            
            rows = cursor.fetchall()
            result = []
            for row in rows:
                tags = []
                if row["tags"]:
                    try:
                        tags = json.loads(row["tags"])
                    except json.JSONDecodeError:
                        pass
                result.append({
                    "title": row["title"],
                    "summary": row["ai_summary"] or "",
                    "tags": tags,
                })
            return result
    
    def cleanup_old_articles(self, retention_days: int = 30):
        """清理旧文章"""
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        with self._get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM articles WHERE fetched_at < ?",
                (cutoff_date,)
            )
            conn.commit()
            logger.info("cleaned_old_articles", deleted_count=cursor.rowcount)
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._get_conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
            analyzed = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE analyzed_at IS NOT NULL"
            ).fetchone()[0]
            sent = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE sent_at IS NOT NULL"
            ).fetchone()[0]
            
            return {
                "total": total,
                "analyzed": analyzed,
                "sent": sent,
            }
    
    def _row_to_analyzed_article(self, row: sqlite3.Row) -> AnalyzedArticle:
        """将数据库行转换为 AnalyzedArticle"""
        # 解析 tags JSON
        tags = []
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
            except json.JSONDecodeError:
                tags = []
        
        return AnalyzedArticle(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            content=row["content"] or "",
            summary=row["summary"] or "",
            source=row["source"] or "",
            category=row["category"] or "",
            author=row["author"] or "",
            published_at=row["published_at"],
            fetched_at=row["fetched_at"],
            score=row["score"] or 0.0,
            ai_summary=row["ai_summary"] or "",
            is_top_pick=bool(row["is_top_pick"]),
            reasoning=row["reasoning"] or "",
            tags=tags,
            analyzed_at=row["analyzed_at"],
        )
