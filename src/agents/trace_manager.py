"""追踪管理器 - 保存分析过程的中间产物"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
import structlog

logger = structlog.get_logger()


class TraceManager:
    """
    管理分析过程的追踪数据
    
    将每个 Agent 的中间产物保存为 JSON 文件，便于：
    - 调试和问题排查
    - 审查分析质量
    - 复现分析结果
    """
    
    def __init__(self, trace_dir: str = "data/traces"):
        self.trace_dir = Path(trace_dir)
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        self._current_session_id: Optional[str] = None
        self._current_session_dir: Optional[Path] = None
    
    def start_session(self, article_url: str, article_title: str) -> str:
        """
        开始一个新的追踪会话
        
        Args:
            article_url: 文章 URL
            article_title: 文章标题
            
        Returns:
            session_id: 会话 ID
        """
        # 生成会话 ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        url_hash = hashlib.md5(article_url.encode()).hexdigest()[:8]
        self._current_session_id = f"{timestamp}_{url_hash}"
        
        # 创建会话目录
        self._current_session_dir = self.trace_dir / self._current_session_id
        self._current_session_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存会话元数据
        metadata = {
            "session_id": self._current_session_id,
            "article_url": article_url,
            "article_title": article_title,
            "start_time": datetime.now().isoformat(),
            "agents": [],
        }
        self._save_json("_metadata.json", metadata)
        
        logger.info(
            "trace_session_started",
            session_id=self._current_session_id,
            path=str(self._current_session_dir),
        )
        
        return self._current_session_id
    
    def save_agent_output(
        self,
        agent_name: str,
        input_data: Any,
        output_data: Any,
        duration_seconds: float,
        token_usage: dict,
        error: Optional[str] = None,
    ):
        """
        保存单个 Agent 的输出
        
        Args:
            agent_name: Agent 名称
            input_data: 输入数据
            output_data: 输出数据
            duration_seconds: 耗时
            token_usage: Token 使用情况
            error: 错误信息（如有）
        """
        if not self._current_session_dir:
            logger.warning("trace_no_active_session")
            return
        
        # 构建追踪数据
        trace_data = {
            "agent": agent_name,
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": duration_seconds,
            "token_usage": token_usage,
            "error": error,
            "input": self._serialize(input_data),
            "output": self._serialize(output_data),
        }
        
        # 保存到文件
        filename = f"{len(list(self._current_session_dir.glob('*.json')))}_{agent_name}.json"
        self._save_json(filename, trace_data)
        
        # 更新元数据
        self._update_metadata(agent_name, duration_seconds, token_usage, error)
        
        logger.debug(
            "agent_trace_saved",
            agent=agent_name,
            file=filename,
        )
    
    def save_final_result(self, enriched_article: Any):
        """保存最终分析结果"""
        if not self._current_session_dir:
            return
        
        self._save_json("_final_result.json", self._serialize(enriched_article))
        
        # 更新元数据
        metadata_path = self._current_session_dir / "_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            metadata["end_time"] = datetime.now().isoformat()
            metadata["completed"] = True
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    def end_session(self) -> Optional[Path]:
        """结束追踪会话，返回会话目录路径"""
        session_dir = self._current_session_dir
        
        if session_dir:
            logger.info(
                "trace_session_ended",
                session_id=self._current_session_id,
                path=str(session_dir),
            )
        
        self._current_session_id = None
        self._current_session_dir = None
        
        return session_dir
    
    def get_session_summary(self) -> dict:
        """获取当前会话摘要"""
        if not self._current_session_dir:
            return {}
        
        metadata_path = self._current_session_dir / "_metadata.json"
        if metadata_path.exists():
            with open(metadata_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    
    def _save_json(self, filename: str, data: Any):
        """保存 JSON 文件"""
        if not self._current_session_dir:
            return
        
        filepath = self._current_session_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    
    def _update_metadata(
        self, 
        agent_name: str, 
        duration: float, 
        tokens: dict,
        error: Optional[str],
    ):
        """更新会话元数据"""
        if not self._current_session_dir:
            return
        
        metadata_path = self._current_session_dir / "_metadata.json"
        if not metadata_path.exists():
            return
        
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)
        
        metadata["agents"].append({
            "name": agent_name,
            "duration_seconds": duration,
            "token_usage": tokens,
            "error": error,
            "timestamp": datetime.now().isoformat(),
        })
        
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    def _serialize(self, obj: Any) -> Any:
        """将对象序列化为可 JSON 化的格式"""
        if obj is None:
            return None
        
        # Pydantic 模型
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        
        # 字典
        if isinstance(obj, dict):
            return {k: self._serialize(v) for k, v in obj.items()}
        
        # 列表
        if isinstance(obj, list):
            return [self._serialize(item) for item in obj]
        
        # 基本类型
        if isinstance(obj, (str, int, float, bool)):
            return obj
        
        # datetime
        if isinstance(obj, datetime):
            return obj.isoformat()
        
        # Path
        if isinstance(obj, Path):
            return str(obj)
        
        # 其他对象尝试转为字符串
        try:
            return str(obj)
        except:
            return f"<{type(obj).__name__}>"
    
    @classmethod
    def list_sessions(cls, trace_dir: str = "data/traces", limit: int = 20) -> list[dict]:
        """列出最近的追踪会话"""
        trace_path = Path(trace_dir)
        if not trace_path.exists():
            return []
        
        sessions = []
        for session_dir in sorted(trace_path.iterdir(), reverse=True)[:limit]:
            if session_dir.is_dir():
                metadata_path = session_dir / "_metadata.json"
                if metadata_path.exists():
                    with open(metadata_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)
                    metadata["path"] = str(session_dir)
                    sessions.append(metadata)
        
        return sessions
