"""AI 遥测服务 - 单例模式"""

import time
import threading
from typing import Optional
from contextvars import ContextVar
import structlog

from ..models.telemetry import AICallRecord, TelemetryStats
from ..storage.telemetry_store import TelemetryStore

logger = structlog.get_logger()

# 上下文变量：当前 session 和 agent
_current_session: ContextVar[Optional[str]] = ContextVar("current_session", default=None)
_current_agent: ContextVar[Optional[str]] = ContextVar("current_agent", default=None)


class AITelemetry:
    """
    AI 遥测服务（单例模式）
    
    用于记录每一个 AI 调用的 input/output
    """
    
    _instance: Optional["AITelemetry"] = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        enabled: bool = True,
        storage_path: str = "data/telemetry",
        retention_days: int = 30,
        max_content_length: int = 10000,
    ):
        if self._initialized:
            return
        
        self.enabled = enabled
        self.max_content_length = max_content_length
        self.store = TelemetryStore(
            storage_path=storage_path,
            retention_days=retention_days,
        ) if enabled else None
        
        self._initialized = True
        logger.info("telemetry_initialized", enabled=enabled, path=storage_path)
    
    @classmethod
    def get_instance(cls) -> "AITelemetry":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def initialize(
        cls,
        enabled: bool = True,
        storage_path: str = "data/telemetry",
        retention_days: int = 30,
        max_content_length: int = 10000,
    ) -> "AITelemetry":
        """初始化遥测服务"""
        return cls(
            enabled=enabled,
            storage_path=storage_path,
            retention_days=retention_days,
            max_content_length=max_content_length,
        )
    
    # ========== 上下文管理 ==========
    
    @staticmethod
    def set_session(session_id: Optional[str]):
        """设置当前 session ID"""
        _current_session.set(session_id)
    
    @staticmethod
    def get_session() -> Optional[str]:
        """获取当前 session ID"""
        return _current_session.get()
    
    @staticmethod
    def set_agent(agent_name: Optional[str]):
        """设置当前 agent 名称"""
        _current_agent.set(agent_name)
    
    @staticmethod
    def get_agent() -> Optional[str]:
        """获取当前 agent 名称"""
        return _current_agent.get()
    
    # ========== 记录方法 ==========
    
    def record(self, record: AICallRecord):
        """记录一条 AI 调用"""
        if not self.enabled or not self.store:
            return
        
        # 自动填充上下文
        if record.session_id is None:
            record.session_id = self.get_session()
        if record.agent_name is None:
            record.agent_name = self.get_agent()
        
        # 截断过长内容
        self._truncate_content(record)
        
        # 写入存储
        try:
            self.store.append(record)
        except Exception as e:
            logger.error("telemetry_record_failed", error=str(e))
    
    def record_chat(
        self,
        model: str,
        messages: list[dict],
        response: str,
        token_usage: dict,
        duration_ms: int,
        retry_count: int = 0,
        error: Optional[str] = None,
        caller: str = "",
    ):
        """记录一次 Chat 调用"""
        record = AICallRecord(
            call_type="chat",
            model=model,
            messages=messages,
            parameters={},
            response=response,
            token_usage=token_usage,
            duration_ms=duration_ms,
            retry_count=retry_count,
            error=error,
            caller=caller,
        )
        self.record(record)
    
    def record_chat_json(
        self,
        model: str,
        messages: list[dict],
        response: str,
        parsed_json: Optional[dict],
        token_usage: dict,
        duration_ms: int,
        retry_count: int = 0,
        error: Optional[str] = None,
        caller: str = "",
    ):
        """记录一次 JSON Chat 调用"""
        record = AICallRecord(
            call_type="chat_json",
            model=model,
            messages=messages,
            parameters={},
            response=response,
            parsed_json=parsed_json,
            token_usage=token_usage,
            duration_ms=duration_ms,
            retry_count=retry_count,
            error=error,
            caller=caller,
        )
        self.record(record)
    
    def record_embedding(
        self,
        model: str,
        input_text: str,
        dimensions: int,
        duration_ms: int,
        error: Optional[str] = None,
        caller: str = "",
    ):
        """记录一次 Embedding 调用"""
        record = AICallRecord(
            call_type="embedding",
            model=model,
            messages=[{"role": "input", "content": input_text[:1000]}],  # 截断
            response=f"[{dimensions} dimensions]",
            token_usage={"prompt": 0, "completion": 0, "total": 0},
            duration_ms=duration_ms,
            error=error,
            caller=caller,
        )
        self.record(record)
    
    # ========== 查询方法 ==========
    
    def query(self, **kwargs) -> list[dict]:
        """查询记录"""
        if not self.enabled or not self.store:
            return []
        return self.store.query(**kwargs)
    
    def get_stats(self, **kwargs) -> TelemetryStats:
        """获取统计信息"""
        if not self.enabled or not self.store:
            return TelemetryStats()
        return self.store.get_stats(**kwargs)
    
    def get_full_record(self, call_id: str) -> Optional[AICallRecord]:
        """获取完整记录"""
        if not self.enabled or not self.store:
            return None
        return self.store.get_full_record(call_id)
    
    def list_sessions(self, limit: int = 20) -> list[dict]:
        """列出 session"""
        if not self.enabled or not self.store:
            return []
        return self.store.list_sessions(limit)
    
    # ========== 维护方法 ==========
    
    def cleanup(self) -> int:
        """清理过期记录"""
        if not self.enabled or not self.store:
            return 0
        return self.store.cleanup_old_records()
    
    def export(self, output_path: str, **kwargs) -> int:
        """导出记录"""
        if not self.enabled or not self.store:
            return 0
        return self.store.export_jsonl(output_path, **kwargs)
    
    # ========== 辅助方法 ==========
    
    def _truncate_content(self, record: AICallRecord):
        """截断过长内容"""
        max_len = self.max_content_length
        
        # 截断 messages
        for msg in record.messages:
            if "content" in msg and isinstance(msg["content"], str):
                if len(msg["content"]) > max_len:
                    msg["content"] = msg["content"][:max_len] + f"... [truncated, total {len(msg['content'])} chars]"
        
        # 截断 response
        if len(record.response) > max_len:
            record.response = record.response[:max_len] + f"... [truncated, total {len(record.response)} chars]"


# 便捷函数
def get_telemetry() -> AITelemetry:
    """获取遥测服务实例"""
    return AITelemetry.get_instance()
