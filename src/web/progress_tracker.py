"""Progress Tracker for Web UI

Provides real-time progress updates via WebSocket during fetch and analysis operations.
"""

import asyncio
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, List, Any

import structlog

logger = structlog.get_logger()


class ProgressPhase(str, Enum):
    """Phases of the fetch/analyze workflow"""
    IDLE = "idle"
    FETCHING_RSS = "fetching_rss"
    EXTRACTING_CONTENT = "extracting_content"
    ANALYZING = "analyzing"
    SENDING_DIGEST = "sending_digest"
    COMPLETED = "completed"
    ERROR = "error"


class TaskStatus(str, Enum):
    """Status of individual parallel tasks"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ParallelTask:
    """Represents a single parallel task (e.g., analyzing one article)"""
    id: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    step: str = ""  # Current step within the task
    progress: int = 0  # 0-100
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ProgressState:
    """Current progress state for the entire operation"""
    phase: ProgressPhase = ProgressPhase.IDLE
    phase_display: str = "空闲"
    message: str = ""
    overall_progress: int = 0  # 0-100
    total_items: int = 0
    completed_items: int = 0
    parallel_tasks: Dict[str, ParallelTask] = field(default_factory=dict)
    started_at: Optional[str] = None
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization"""
        return {
            "phase": self.phase.value,
            "phase_display": self.phase_display,
            "message": self.message,
            "overall_progress": self.overall_progress,
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "parallel_tasks": [asdict(t) for t in self.parallel_tasks.values()],
            "started_at": self.started_at,
        }


class ProgressTracker:
    """
    Tracks and broadcasts progress updates via WebSocket.
    
    Usage:
        tracker = ProgressTracker(broadcast_fn)
        
        await tracker.start_operation()
        await tracker.set_phase(ProgressPhase.FETCHING_RSS, "正在抓取 RSS...")
        
        # For parallel tasks
        task_id = await tracker.add_task("Article Title")
        await tracker.update_task(task_id, step="extracting", progress=50)
        await tracker.complete_task(task_id)
        
        await tracker.finish()
    """
    
    def __init__(self, broadcast_fn=None):
        """
        Initialize the tracker.
        
        Args:
            broadcast_fn: Async function to broadcast messages, 
                         signature: async def broadcast(message: dict)
        """
        self.broadcast_fn = broadcast_fn
        self.state = ProgressState()
        self._lock = asyncio.Lock()
    
    async def _broadcast(self):
        """Broadcast current state to all WebSocket clients"""
        if not self.broadcast_fn:
            return
        
        try:
            message = {
                "type": "progress",
                "timestamp": datetime.now().isoformat(),
                "data": self.state.to_dict()
            }
            await self.broadcast_fn(message)
        except Exception as e:
            logger.warning("progress_broadcast_failed", error=str(e))
    
    async def start_operation(self, message: str = "开始执行..."):
        """Called when a new fetch/analyze operation starts"""
        async with self._lock:
            self.state = ProgressState(
                phase=ProgressPhase.IDLE,
                phase_display="准备中",
                message=message,
                started_at=datetime.now().isoformat()
            )
        await self._broadcast()
    
    async def set_phase(
        self, 
        phase: ProgressPhase, 
        display: str,
        message: str = "",
        total_items: int = 0
    ):
        """Update the current phase"""
        async with self._lock:
            self.state.phase = phase
            self.state.phase_display = display
            self.state.message = message
            if total_items > 0:
                self.state.total_items = total_items
            # Clear parallel tasks when entering a new phase
            self.state.parallel_tasks = {}
            self.state.completed_items = 0
        await self._broadcast()
    
    async def update_progress(self, completed: int, total: int, message: str = ""):
        """Update overall progress"""
        async with self._lock:
            self.state.completed_items = completed
            self.state.total_items = total
            if total > 0:
                self.state.overall_progress = int((completed / total) * 100)
            if message:
                self.state.message = message
        await self._broadcast()
    
    async def add_task(self, title: str, task_id: str = None) -> str:
        """Add a new parallel task and return its ID"""
        if not task_id:
            task_id = str(uuid.uuid4())[:8]
        
        # Truncate title for display
        display_title = title[:40] + "..." if len(title) > 40 else title
        
        async with self._lock:
            self.state.parallel_tasks[task_id] = ParallelTask(
                id=task_id,
                title=display_title,
                status=TaskStatus.RUNNING,
                started_at=datetime.now().isoformat()
            )
        await self._broadcast()
        return task_id
    
    async def update_task(
        self, 
        task_id: str, 
        step: str = None, 
        progress: int = None,
        status: TaskStatus = None
    ):
        """Update a parallel task's progress"""
        async with self._lock:
            if task_id not in self.state.parallel_tasks:
                return
            
            task = self.state.parallel_tasks[task_id]
            if step is not None:
                task.step = step
            if progress is not None:
                task.progress = progress
            if status is not None:
                task.status = status
        await self._broadcast()
    
    async def complete_task(self, task_id: str, success: bool = True, error: str = None):
        """Mark a parallel task as completed"""
        async with self._lock:
            if task_id not in self.state.parallel_tasks:
                return
            
            task = self.state.parallel_tasks[task_id]
            task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
            task.progress = 100 if success else task.progress
            task.completed_at = datetime.now().isoformat()
            if error:
                task.error = error
            
            # Update overall progress
            self.state.completed_items += 1
            if self.state.total_items > 0:
                self.state.overall_progress = int(
                    (self.state.completed_items / self.state.total_items) * 100
                )
        await self._broadcast()
    
    async def finish(self, success: bool = True, message: str = "执行完成"):
        """Called when the operation finishes"""
        async with self._lock:
            if success:
                self.state.phase = ProgressPhase.COMPLETED
                self.state.phase_display = "已完成"
                self.state.overall_progress = 100
            else:
                self.state.phase = ProgressPhase.ERROR
                self.state.phase_display = "出错"
            self.state.message = message
        await self._broadcast()
    
    def get_state(self) -> dict:
        """Get current state as dict (for API endpoint)"""
        return self.state.to_dict()


# Global tracker instance (will be initialized by server.py)
_tracker: Optional[ProgressTracker] = None


def get_progress_tracker() -> Optional[ProgressTracker]:
    """Get the global progress tracker"""
    return _tracker


def set_progress_tracker(tracker: ProgressTracker):
    """Set the global progress tracker"""
    global _tracker
    _tracker = tracker
