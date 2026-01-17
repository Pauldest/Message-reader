"""AI 遥测数据模型"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Any
import uuid
import json


@dataclass
class AICallRecord:
    """
    AI 调用记录
    
    记录每一次 LLM/Embedding 调用的完整信息
    """
    # 基本标识
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    
    # 调用类型
    call_type: str = "chat"  # "chat" | "chat_json" | "embedding"
    model: str = ""
    
    # 输入
    messages: list[dict] = field(default_factory=list)
    parameters: dict = field(default_factory=dict)  # max_tokens, temperature, etc.
    
    # 输出
    response: str = ""
    parsed_json: Optional[dict] = None  # 如果是 JSON 调用
    
    # 性能指标
    duration_ms: int = 0
    token_usage: dict = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})
    retry_count: int = 0
    error: Optional[str] = None
    
    # 上下文
    session_id: Optional[str] = None   # TraceManager session ID
    agent_name: Optional[str] = None   # 调用的 Agent 名称
    caller: str = ""                   # 调用来源（模块名）
    
    def to_dict(self) -> dict:
        """转换为字典（用于 JSON 序列化）"""
        data = asdict(self)
        # 转换 datetime 为 ISO 格式
        data["timestamp"] = self.timestamp.isoformat()
        return data
    
    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)
    
    @classmethod
    def from_dict(cls, data: dict) -> "AICallRecord":
        """从字典创建"""
        # 转换 timestamp
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)
    
    @classmethod
    def from_json(cls, json_str: str) -> "AICallRecord":
        """从 JSON 字符串创建"""
        return cls.from_dict(json.loads(json_str))


@dataclass
class TelemetryStats:
    """遥测统计"""
    total_calls: int = 0
    total_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_duration_ms: int = 0
    error_count: int = 0
    
    # 按类型分组
    calls_by_type: dict = field(default_factory=dict)
    calls_by_agent: dict = field(default_factory=dict)
    calls_by_model: dict = field(default_factory=dict)
    
    # 时间范围
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    @property
    def avg_duration_ms(self) -> float:
        """平均调用时长"""
        return self.total_duration_ms / self.total_calls if self.total_calls > 0 else 0
    
    @property
    def error_rate(self) -> float:
        """错误率"""
        return self.error_count / self.total_calls if self.total_calls > 0 else 0
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "total_calls": self.total_calls,
            "total_tokens": self.total_tokens,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_duration_ms": self.total_duration_ms,
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "error_count": self.error_count,
            "error_rate": round(self.error_rate * 100, 2),
            "calls_by_type": self.calls_by_type,
            "calls_by_agent": self.calls_by_agent,
            "calls_by_model": self.calls_by_model,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
        }
