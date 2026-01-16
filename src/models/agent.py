"""Agent 相关数据模型"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


class AnalysisMode(str, Enum):
    """分析模式"""
    QUICK = "quick"       # 快速模式：仅基础评分和摘要
    STANDARD = "standard" # 标准模式：评分 + 影响分析
    DEEP = "deep"         # 深度模式：完整多智能体分析


class AgentTrace(BaseModel):
    """Agent 分析痕迹（用于调试和透明度）"""
    agent_name: str
    timestamp: datetime = Field(default_factory=datetime.now)
    input_summary: str = ""
    output_summary: str = ""
    duration_seconds: float = 0.0
    token_usage: dict = Field(default_factory=dict)  # {"prompt": 100, "completion": 200}
    error: Optional[str] = None
    
    def to_log_dict(self) -> dict:
        """转换为日志格式"""
        return {
            "agent": self.agent_name,
            "duration": f"{self.duration_seconds:.2f}s",
            "tokens": self.token_usage,
            "error": self.error,
        }


class AgentContext(BaseModel):
    """Agent 上下文（在 Agent 之间传递）"""
    # 原始文章
    original_article: Optional[Any] = None
    
    # Collector 输出
    cleaned_content: str = ""
    extracted_5w1h: dict = Field(default_factory=dict)
    
    # Librarian 输出
    entities: list[Any] = Field(default_factory=list)
    historical_context: str = ""
    knowledge_graph: Optional[Any] = None
    related_articles: list[dict] = Field(default_factory=list)
    
    # 分析师团队输出
    analyst_reports: dict[str, Any] = Field(default_factory=dict)
    # {"skeptic": {...}, "economist": {...}, "detective": {...}}
    
    # 配置
    analysis_mode: AnalysisMode = AnalysisMode.DEEP
    
    # 元数据
    traces: list[AgentTrace] = Field(default_factory=list)
    
    def add_trace(self, trace: AgentTrace):
        """添加分析痕迹"""
        self.traces.append(trace)
    
    def get_total_duration(self) -> float:
        """获取总耗时"""
        return sum(t.duration_seconds for t in self.traces)
    
    def get_total_tokens(self) -> dict:
        """获取总 token 使用"""
        total = {"prompt": 0, "completion": 0}
        for trace in self.traces:
            total["prompt"] += trace.token_usage.get("prompt", 0)
            total["completion"] += trace.token_usage.get("completion", 0)
        return total


class AgentOutput(BaseModel):
    """Agent 输出"""
    success: bool = True
    data: Any = None
    trace: Optional[AgentTrace] = None
    error: Optional[str] = None
    
    @classmethod
    def failure(cls, agent_name: str, error: str, duration: float = 0.0) -> "AgentOutput":
        """创建失败输出"""
        return cls(
            success=False,
            error=error,
            trace=AgentTrace(
                agent_name=agent_name,
                duration_seconds=duration,
                error=error
            )
        )
