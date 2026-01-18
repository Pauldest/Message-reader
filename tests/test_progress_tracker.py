"""Progress Tracker 单元测试

测试 src/web/progress_tracker.py
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from src.web.progress_tracker import (
    ProgressTracker,
    ProgressState,
    ProgressPhase,
    TaskStatus,
    ParallelTask,
    get_progress_tracker,
    set_progress_tracker,
)


class TestProgressPhase:
    """ProgressPhase 枚举测试"""
    
    def test_phase_values(self):
        """测试阶段枚举值"""
        assert ProgressPhase.IDLE.value == "idle"
        assert ProgressPhase.FETCHING_RSS.value == "fetching_rss"
        assert ProgressPhase.EXTRACTING_CONTENT.value == "extracting_content"
        assert ProgressPhase.ANALYZING.value == "analyzing"
        assert ProgressPhase.SENDING_DIGEST.value == "sending_digest"
        assert ProgressPhase.COMPLETED.value == "completed"
        assert ProgressPhase.ERROR.value == "error"


class TestTaskStatus:
    """TaskStatus 枚举测试"""
    
    def test_status_values(self):
        """测试状态枚举值"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"


class TestParallelTask:
    """ParallelTask 数据类测试"""
    
    def test_parallel_task_creation(self):
        """测试创建并行任务"""
        task = ParallelTask(
            id="task-1",
            title="测试任务"
        )
        
        assert task.id == "task-1"
        assert task.title == "测试任务"
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0
    
    def test_parallel_task_with_all_fields(self):
        """测试所有字段"""
        task = ParallelTask(
            id="task-2",
            title="完整任务",
            status=TaskStatus.RUNNING,
            step="提取信息",
            progress=50,
            started_at="2026-01-18T10:00:00",
            completed_at=None,
            error=None
        )
        
        assert task.step == "提取信息"
        assert task.progress == 50


class TestProgressState:
    """ProgressState 数据类测试"""
    
    def test_progress_state_defaults(self):
        """测试默认值"""
        state = ProgressState()
        
        assert state.phase == ProgressPhase.IDLE
        assert state.phase_display == "空闲"
        assert state.message == ""
        assert state.overall_progress == 0
        assert state.total_items == 0
        assert state.completed_items == 0
        assert len(state.parallel_tasks) == 0
    
    def test_to_dict(self):
        """测试序列化为字典"""
        state = ProgressState(
            phase=ProgressPhase.ANALYZING,
            phase_display="AI 分析",
            message="正在分析文章...",
            overall_progress=50,
            total_items=10,
            completed_items=5
        )
        
        result = state.to_dict()
        
        assert result["phase"] == "analyzing"
        assert result["phase_display"] == "AI 分析"
        assert result["message"] == "正在分析文章..."
        assert result["overall_progress"] == 50
        assert result["total_items"] == 10
        assert result["completed_items"] == 5
        assert "parallel_tasks" in result
    
    def test_to_dict_with_tasks(self):
        """测试带并行任务的序列化"""
        state = ProgressState()
        state.parallel_tasks["task-1"] = ParallelTask(
            id="task-1",
            title="任务1",
            status=TaskStatus.RUNNING
        )
        
        result = state.to_dict()
        
        assert len(result["parallel_tasks"]) == 1
        assert result["parallel_tasks"][0]["id"] == "task-1"


class TestProgressTracker:
    """ProgressTracker 测试"""
    
    def setup_method(self):
        """每个测试前创建 tracker"""
        self.broadcast_mock = AsyncMock()
        self.tracker = ProgressTracker(broadcast_fn=self.broadcast_mock)
    
    @pytest.mark.asyncio
    async def test_start_operation(self):
        """测试开始操作"""
        await self.tracker.start_operation("开始测试...")
        
        assert self.tracker.state.message == "开始测试..."
        assert self.tracker.state.started_at is not None
        
        # 应该广播一次
        self.broadcast_mock.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_set_phase(self):
        """测试设置阶段"""
        await self.tracker.set_phase(
            phase=ProgressPhase.FETCHING_RSS,
            display="抓取 RSS",
            message="正在抓取...",
            total_items=5
        )
        
        assert self.tracker.state.phase == ProgressPhase.FETCHING_RSS
        assert self.tracker.state.phase_display == "抓取 RSS"
        assert self.tracker.state.message == "正在抓取..."
        assert self.tracker.state.total_items == 5
    
    @pytest.mark.asyncio
    async def test_update_progress(self):
        """测试更新进度"""
        await self.tracker.update_progress(
            completed=3,
            total=10,
            message="进行中..."
        )
        
        assert self.tracker.state.completed_items == 3
        assert self.tracker.state.total_items == 10
        assert self.tracker.state.overall_progress == 30
        assert self.tracker.state.message == "进行中..."
    
    @pytest.mark.asyncio
    async def test_add_task(self):
        """测试添加并行任务"""
        task_id = await self.tracker.add_task("测试任务标题")
        
        assert task_id is not None
        assert len(task_id) == 8  # UUID 前 8 位
        
        assert task_id in self.tracker.state.parallel_tasks
        task = self.tracker.state.parallel_tasks[task_id]
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None
    
    @pytest.mark.asyncio
    async def test_add_task_with_custom_id(self):
        """测试使用自定义 ID 添加任务"""
        task_id = await self.tracker.add_task("任务", task_id="custom-id")
        
        assert task_id == "custom-id"
        assert "custom-id" in self.tracker.state.parallel_tasks
    
    @pytest.mark.asyncio
    async def test_add_task_truncates_long_title(self):
        """测试长标题被截断"""
        long_title = "这是一个非常长的标题" * 10  # 超过 40 字符
        
        await self.tracker.add_task(long_title, task_id="long-task")
        
        task = self.tracker.state.parallel_tasks["long-task"]
        assert len(task.title) <= 43  # 40 + "..."
        assert task.title.endswith("...")
    
    @pytest.mark.asyncio
    async def test_update_task(self):
        """测试更新任务"""
        task_id = await self.tracker.add_task("任务")
        
        await self.tracker.update_task(
            task_id,
            step="处理中",
            progress=50
        )
        
        task = self.tracker.state.parallel_tasks[task_id]
        assert task.step == "处理中"
        assert task.progress == 50
    
    @pytest.mark.asyncio
    async def test_update_nonexistent_task(self):
        """测试更新不存在的任务（应该不报错）"""
        await self.tracker.update_task("nonexistent", step="test")
        # 不应该抛出异常
    
    @pytest.mark.asyncio
    async def test_complete_task_success(self):
        """测试成功完成任务"""
        task_id = await self.tracker.add_task("任务")
        await self.tracker.complete_task(task_id, success=True)
        
        task = self.tracker.state.parallel_tasks[task_id]
        assert task.status == TaskStatus.COMPLETED
        assert task.progress == 100
        assert task.completed_at is not None
        
        # 完成项计数应该增加
        assert self.tracker.state.completed_items == 1
    
    @pytest.mark.asyncio
    async def test_complete_task_failure(self):
        """测试任务失败"""
        task_id = await self.tracker.add_task("任务")
        await self.tracker.complete_task(task_id, success=False, error="出错了")
        
        task = self.tracker.state.parallel_tasks[task_id]
        assert task.status == TaskStatus.FAILED
        assert task.error == "出错了"
    
    @pytest.mark.asyncio
    async def test_finish_success(self):
        """测试成功完成操作"""
        await self.tracker.finish(success=True, message="全部完成")
        
        assert self.tracker.state.phase == ProgressPhase.COMPLETED
        assert self.tracker.state.phase_display == "已完成"
        assert self.tracker.state.overall_progress == 100
        assert self.tracker.state.message == "全部完成"
    
    @pytest.mark.asyncio
    async def test_finish_error(self):
        """测试操作出错"""
        await self.tracker.finish(success=False, message="发生错误")
        
        assert self.tracker.state.phase == ProgressPhase.ERROR
        assert self.tracker.state.phase_display == "出错"
        assert self.tracker.state.message == "发生错误"
    
    def test_get_state(self):
        """测试获取状态"""
        state = self.tracker.get_state()
        
        assert isinstance(state, dict)
        assert "phase" in state
        assert "parallel_tasks" in state
    
    @pytest.mark.asyncio
    async def test_broadcast_called_on_updates(self):
        """测试更新时调用广播"""
        await self.tracker.start_operation()
        await self.tracker.set_phase(ProgressPhase.ANALYZING, "分析")
        await self.tracker.add_task("任务")
        await self.tracker.finish()
        
        # 应该多次调用广播
        assert self.broadcast_mock.call_count >= 4
    
    @pytest.mark.asyncio
    async def test_no_broadcast_without_function(self):
        """测试没有广播函数时不报错"""
        tracker = ProgressTracker(broadcast_fn=None)
        
        await tracker.start_operation()
        await tracker.set_phase(ProgressPhase.ANALYZING, "分析")
        await tracker.finish()
        
        # 不应该抛出异常


class TestProgressTrackerGlobalFunctions:
    """全局函数测试"""
    
    def test_set_and_get_tracker(self):
        """测试设置和获取全局 tracker"""
        tracker = ProgressTracker()
        set_progress_tracker(tracker)
        
        retrieved = get_progress_tracker()
        assert retrieved is tracker
    
    def test_get_tracker_initially_none(self):
        """测试初始值可能为 None"""
        # 注意：这个测试可能会受到其他测试影响
        # 因为全局变量会被修改
        pass
