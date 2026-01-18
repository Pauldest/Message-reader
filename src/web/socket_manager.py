"""WebSocket Log Manager"""

import asyncio
import json
from datetime import datetime
from typing import List, Dict, Any
from fastapi import WebSocket, WebSocketDisconnect
import structlog

# 全局 WebSocket 连接管理器
class ConnectionManager:
    def __init__(self, max_connections: int = 100):
        self.active_connections: List[WebSocket] = []
        self.max_connections = max_connections

    async def connect(self, websocket: WebSocket) -> bool:
        """连接客户端，如果超过最大连接数则拒绝"""
        if len(self.active_connections) >= self.max_connections:
            await websocket.close(code=1008, reason="Too many connections")
            return False

        await websocket.accept()
        self.active_connections.append(websocket)
        return True

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """广播消息给所有连接的客户端"""
        payload = json.dumps(message, default=str)
        # 复制列表以避免在迭代时修改
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                # 忽略发送错误，断开连接会在 receive loop 中处理
                pass

    async def broadcast_progress(self, event: Dict[str, Any]):
        """广播进度更新消息"""
        await self.broadcast(event)

manager = ConnectionManager()

# Structlog 处理器，用于拦截日志并发送到 WebSocket
class WebSocketLogHandler:
    def __call__(self, logger, name, event_dict):
        # 异步发送日志需要放到 event loop 中
        # 注意：这里可能在同步或异步上下文中调用，需要小心处理
        try:
            log_entry = {
                "type": "log",
                "timestamp": datetime.now().isoformat(),
                "level": event_dict.get("level", "info").upper(),
                "event": event_dict.get("event", ""),
                "logger": name,
                "context": {k: v for k, v in event_dict.items() if k not in ["level", "event", "timestamp"]}
            }
            
            # 只有在有活跃连接时才尝试发送
            if manager.active_connections:
                # 获取当前 loop 或创建新的（如果在线程中）
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast(log_entry))
                except RuntimeError:
                    # 如果没有运行中的 loop (极其少见情况)，则无法广播
                    pass
                    
        except Exception:
            # 防止日志系统崩溃
            pass
            
        return event_dict

# 需要在 structlog 配置中添加此 processor
# structlog.configure(processors=[..., WebSocketLogHandler(), ...])
