"""遥测数据存储层 - JSONL + SQLite"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Iterator
import threading
import structlog

from ..models.telemetry import AICallRecord, TelemetryStats

logger = structlog.get_logger()


class TelemetryStore:
    """
    遥测数据存储
    
    - JSONL 文件：按日期分片存储完整记录
    - SQLite：索引存储用于查询
    """
    
    def __init__(
        self, 
        storage_path: str = "data/telemetry",
        retention_days: int = 30,
    ):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.retention_days = retention_days
        
        # SQLite 连接（线程安全）
        self.db_path = self.storage_path / "telemetry.db"
        self._local = threading.local()
        
        # 初始化数据库
        self._init_db()
    
    @property
    def _conn(self) -> sqlite3.Connection:
        """获取线程本地的数据库连接"""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn
    
    def _init_db(self):
        """初始化数据库表"""
        with self._conn:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS ai_calls (
                    call_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    call_type TEXT NOT NULL,
                    model TEXT,
                    agent_name TEXT,
                    session_id TEXT,
                    duration_ms INTEGER,
                    prompt_tokens INTEGER,
                    completion_tokens INTEGER,
                    total_tokens INTEGER,
                    error TEXT,
                    jsonl_file TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # 创建索引
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp ON ai_calls(timestamp)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session ON ai_calls(session_id)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent ON ai_calls(agent_name)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_call_type ON ai_calls(call_type)
            """)
    
    def append(self, record: AICallRecord):
        """
        追加一条记录
        
        1. 写入当日 JSONL 文件
        2. 写入 SQLite 索引
        """
        # 确定 JSONL 文件名
        date_str = record.timestamp.strftime("%Y-%m-%d")
        jsonl_file = self.storage_path / f"{date_str}.jsonl"
        
        # 写入 JSONL（追加模式）
        with open(jsonl_file, "a", encoding="utf-8") as f:
            f.write(record.to_json() + "\n")
        
        # 写入 SQLite 索引
        with self._conn:
            self._conn.execute("""
                INSERT OR REPLACE INTO ai_calls 
                (call_id, timestamp, call_type, model, agent_name, session_id,
                 duration_ms, prompt_tokens, completion_tokens, total_tokens,
                 error, jsonl_file)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.call_id,
                record.timestamp.isoformat(),
                record.call_type,
                record.model,
                record.agent_name,
                record.session_id,
                record.duration_ms,
                record.token_usage.get("prompt", 0),
                record.token_usage.get("completion", 0),
                record.token_usage.get("total", 0),
                record.error,
                str(jsonl_file),
            ))
        
        logger.debug(
            "telemetry_recorded",
            call_id=record.call_id[:8],
            call_type=record.call_type,
            agent=record.agent_name,
        )
    
    def query(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        session_id: Optional[str] = None,
        agent_name: Optional[str] = None,
        call_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        """
        查询记录（仅返回索引信息，不含完整 messages）
        """
        query = "SELECT * FROM ai_calls WHERE 1=1"
        params = []
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())
        
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        
        if agent_name:
            query += " AND agent_name = ?"
            params.append(agent_name)
        
        if call_type:
            query += " AND call_type = ?"
            params.append(call_type)
        
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cursor = self._conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def get_full_record(self, call_id: str) -> Optional[AICallRecord]:
        """
        获取完整记录（从 JSONL 文件中读取）
        """
        # 先查询索引获取文件位置
        cursor = self._conn.execute(
            "SELECT jsonl_file, timestamp FROM ai_calls WHERE call_id = ?",
            (call_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        
        jsonl_file = Path(row["jsonl_file"])
        if not jsonl_file.exists():
            return None
        
        # 从 JSONL 文件中查找
        with open(jsonl_file, "r", encoding="utf-8") as f:
            for line in f:
                if call_id in line:
                    try:
                        record = AICallRecord.from_json(line.strip())
                        if record.call_id == call_id:
                            return record
                    except:
                        continue
        
        return None
    
    def get_stats(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        session_id: Optional[str] = None,
    ) -> TelemetryStats:
        """
        获取统计信息
        """
        query = """
            SELECT 
                COUNT(*) as total_calls,
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(duration_ms) as total_duration_ms,
                SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) as error_count,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time
            FROM ai_calls WHERE 1=1
        """
        params = []
        
        if start_time:
            query += " AND timestamp >= ?"
            params.append(start_time.isoformat())
        
        if end_time:
            query += " AND timestamp <= ?"
            params.append(end_time.isoformat())
        
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        
        cursor = self._conn.execute(query, params)
        row = cursor.fetchone()
        
        stats = TelemetryStats(
            total_calls=row["total_calls"] or 0,
            total_prompt_tokens=row["total_prompt_tokens"] or 0,
            total_completion_tokens=row["total_completion_tokens"] or 0,
            total_tokens=row["total_tokens"] or 0,
            total_duration_ms=row["total_duration_ms"] or 0,
            error_count=row["error_count"] or 0,
            start_time=datetime.fromisoformat(row["start_time"]) if row["start_time"] else None,
            end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
        )
        
        # 按类型分组
        where_clause = "WHERE 1=1"
        if start_time:
            where_clause += f" AND timestamp >= '{start_time.isoformat()}'"
        if end_time:
            where_clause += f" AND timestamp <= '{end_time.isoformat()}'"
        if session_id:
            where_clause += f" AND session_id = '{session_id}'"
        
        for field, attr in [
            ("call_type", "calls_by_type"),
            ("agent_name", "calls_by_agent"),
            ("model", "calls_by_model"),
        ]:
            cursor = self._conn.execute(f"""
                SELECT {field}, COUNT(*) as count 
                FROM ai_calls {where_clause}
                GROUP BY {field}
            """)
            setattr(stats, attr, {
                row[field] or "unknown": row["count"] 
                for row in cursor.fetchall()
            })
        
        return stats
    
    def cleanup_old_records(self) -> int:
        """
        清理过期记录
        
        Returns:
            删除的记录数
        """
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        cutoff_str = cutoff.strftime("%Y-%m-%d")
        
        # 删除旧的 JSONL 文件
        deleted_files = 0
        for jsonl_file in self.storage_path.glob("*.jsonl"):
            if jsonl_file.name < f"{cutoff_str}.jsonl":
                jsonl_file.unlink()
                deleted_files += 1
        
        # 删除数据库中的旧记录
        with self._conn:
            cursor = self._conn.execute(
                "DELETE FROM ai_calls WHERE timestamp < ?",
                (cutoff.isoformat(),)
            )
            deleted_rows = cursor.rowcount
        
        logger.info(
            "telemetry_cleanup",
            deleted_files=deleted_files,
            deleted_rows=deleted_rows,
            cutoff=cutoff_str,
        )
        
        return deleted_rows
    
    def export_jsonl(
        self,
        output_path: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """
        导出记录到 JSONL 文件
        """
        # 确定要读取的 JSONL 文件
        start_date = start_time.strftime("%Y-%m-%d") if start_time else "0000-00-00"
        end_date = end_time.strftime("%Y-%m-%d") if end_time else "9999-99-99"
        
        count = 0
        with open(output_path, "w", encoding="utf-8") as out:
            for jsonl_file in sorted(self.storage_path.glob("*.jsonl")):
                file_date = jsonl_file.stem
                if start_date <= file_date <= end_date:
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            # 检查时间范围
                            try:
                                record = json.loads(line)
                                ts = datetime.fromisoformat(record["timestamp"])
                                if start_time and ts < start_time:
                                    continue
                                if end_time and ts > end_time:
                                    continue
                                out.write(line)
                                count += 1
                            except:
                                continue
        
        return count
    
    def list_sessions(self, limit: int = 20) -> list[dict]:
        """列出最近的 session"""
        cursor = self._conn.execute("""
            SELECT 
                session_id,
                MIN(timestamp) as start_time,
                MAX(timestamp) as end_time,
                COUNT(*) as call_count,
                SUM(total_tokens) as total_tokens
            FROM ai_calls
            WHERE session_id IS NOT NULL
            GROUP BY session_id
            ORDER BY start_time DESC
            LIMIT ?
        """, (limit,))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def close(self):
        """关闭数据库连接"""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
