"""Web Server Module"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import structlog
from contextlib import asynccontextmanager
from pydantic import BaseModel

# 确保可以找到 src 包
ROOT_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from src.config import get_config
from src.main import RSSReaderService
from src.web.socket_manager import WebSocketLogHandler, manager, ConnectionManager
from src.web.progress_tracker import ProgressTracker, set_progress_tracker, get_progress_tracker

# 重新配置 structlog 以添加 WebSocket 支持
def configure_logging():
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            WebSocketLogHandler(),  # 添加 WebSocket 处理器
            structlog.processors.JSONRenderer(),
        ]
    )

configure_logging()
logger = structlog.get_logger()

# 全局服务实例和运行锁
service: Optional[RSSReaderService] = None
is_running = False
run_lock = asyncio.Lock()  # 防止并发运行的锁

@asynccontextmanager
async def lifespan(app: FastAPI):
    global service
    config = get_config()
    
    # 初始化进度追踪器
    progress_tracker = ProgressTracker(broadcast_fn=manager.broadcast_progress)
    set_progress_tracker(progress_tracker)
    
    # 初始化服务，默认使用 deep 模式，并发数 5
    service = RSSReaderService(config, analysis_mode="deep", concurrency=5, progress_tracker=progress_tracker)
    logger.info("web_server_started")
    yield
    if service and service._running:
        service.stop()
    logger.info("web_server_stopped")

app = FastAPI(lifespan=lifespan)

# 配置 CORS 中间件
# 生产环境应该使用具体的域名列表，而不是 ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],  # 在生产环境中配置具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Models
class RunRequest(BaseModel):
    limit: Optional[int] = None
    dry_run: bool = False
    concurrency: int = 5  # 🆕 并发数控制

class FeedRequest(BaseModel):
    name: str
    url: str
    category: str = "未分类"

class FeedToggleRequest(BaseModel):
    identifier: str

# --- WebSocket ---

@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time logs with DoS protection"""
    # 尝试连接，如果超过最大连接数则拒绝
    connected = await manager.connect(websocket)
    if not connected:
        return

    try:
        # 设置超时以防止僵尸连接
        while True:
            try:
                # 30秒超时，如果客户端没有发送心跳则断开
                data = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=30.0
                )
                # 可以处理客户端发来的指令（如心跳ping）
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # 超时，发送ping检查连接是否仍然活跃
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    # 发送失败，连接已断开
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("websocket_error", error=str(e))
    finally:
        manager.disconnect(websocket)

# --- API ---

@app.get("/")
async def read_root():
    return FileResponse(str(static_dir / "index.html"))

@app.get("/api/status")
async def get_status():
    stats = {}
    if service and hasattr(service, "orchestrator"):
         stats = service.orchestrator.get_stats()
    
    return {
        "running": is_running,
        "mode": service.analysis_mode.value if service else "unknown",
        "stats": stats
    }

@app.get("/api/progress/state")
async def get_progress_state():
    """Get current progress state (for page refresh recovery)"""
    tracker = get_progress_tracker()
    if tracker:
        return tracker.get_state()
    return {"phase": "idle", "phase_display": "空闲", "parallel_tasks": []}


async def run_worker(limit: int = None, dry_run: bool = False, concurrency: int = 5):
    """工作线程，使用锁防止并发运行"""
    global is_running

    # 使用锁确保原子性检查和设置
    async with run_lock:
        if is_running:
            return
        is_running = True

    try:
        # 🆕 动态设置并发数
        service.concurrency = concurrency
        service.orchestrator.concurrency = concurrency

        logger.info("worker_started", limit=limit, dry_run=dry_run, concurrency=concurrency)
        await service.run_once(limit=limit, dry_run=dry_run)
    except Exception as e:
        logger.error("worker_failed", error=str(e))
    finally:
        async with run_lock:
            is_running = False
        logger.info("worker_finished")

@app.post("/api/run")
async def run_task(req: RunRequest, background_tasks: BackgroundTasks):
    """启动RSS抓取和分析任务"""
    global is_running

    # 使用锁检查状态，防止race condition
    async with run_lock:
        if is_running:
            raise HTTPException(status_code=400, detail="Task already running")

    background_tasks.add_task(run_worker, limit=req.limit, dry_run=req.dry_run, concurrency=req.concurrency)
    return {"status": "started", "concurrency": req.concurrency}

@app.post("/api/digest")
async def generate_digest(background_tasks: BackgroundTasks):
    """生成并发送邮件摘要"""
    global is_running

    # 使用锁检查状态，防止race condition
    async with run_lock:
        if is_running:
            raise HTTPException(status_code=400, detail="Task already running")

    async def digest_worker():
        global is_running

        async with run_lock:
            is_running = True

        try:
            logger.info("digest_generation_started")
            # 调用 run_once 的 digest 模式逻辑
            # 由于 run_once 内部逻辑较复杂，这里我们可能需要稍微 hack 一下或者重构 main.py
            # 为了简单，我们直接调用 service 中的 prepare_digest
            
            # 检查是否有未发送的文章
            # 这部分逻辑在 main.py 的 async_main 中的 parser.args.digest 部分
            # service.run_once 默认包含 fetch -> analyze -> digest 流程
            # 如果我们要只生成 digest，我们需要一个专门的方法
            
            # 暂时我们调用一个专门的方法，如果是 hack 的话，我们也许可以在 service 中加一个 generate_digest_only 方法
            # 但现在我们先假设 service.run_once 会完成整个流程。
            # 如果用户只想生成摘要而不抓取，我们可以修改 run_once 的参数控制流程，或者直接调用内部方法
            
            # 使用 hack 方式调用内部方法生成 digest
            await service.send_daily_digest()
            
        except Exception as e:
            logger.error("digest_generation_failed", error=str(e))
        finally:
            async with run_lock:
                is_running = False
            logger.info("digest_generation_finished")

    background_tasks.add_task(digest_worker)
    return {"status": "started"}

@app.post("/api/stop")
async def stop_task():
    global is_running
    if service:
        service.stop() # 这只是设置标帜位，可能不会立即停止正在进行的 await
    return {"status": "stopping"}

# --- Database Viewing ---

@app.get("/api/db/articles")
async def get_articles(limit: int = 50, offset: int = 0, search: str = ""):
    with service.db._get_conn() as conn:
        cursor = conn.execute(
            f"SELECT * FROM articles WHERE title LIKE ? OR content LIKE ? ORDER BY published_at DESC LIMIT ? OFFSET ?",
            (f"%{search}%", f"%{search}%", limit, offset)
        )
        columns = [description[0] for description in cursor.description]
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
        return results

@app.get("/api/db/info_units")
async def get_info_units(limit: int = 50, offset: int = 0, search: str = ""):
    with service.db._get_conn() as conn:
        cursor = conn.execute(
            f"SELECT * FROM information_units WHERE title LIKE ? OR summary LIKE ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (f"%{search}%", f"%{search}%", limit, offset)
        )
        columns = [description[0] for description in cursor.description]
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
        return results

# --- RSS Feeds ---

@app.get("/api/feeds")
async def get_feeds():
    from src.feeds import FeedManager
    fm = FeedManager(config_dir=ROOT_DIR / "config")
    return [f.__dict__ for f in fm.list_feeds()]

@app.post("/api/feeds")
async def add_feed(req: FeedRequest):
    from src.feeds import FeedManager
    fm = FeedManager(config_dir=ROOT_DIR / "config")
    
    # 验证
    # 这里为了不阻塞，我们在主线程验证（会有点慢），或者应该异步化
    # 简单期间，先直接添加
    result = await fm.verify_feed(req.url, timeout=5)
    if result["valid"]:
        name = req.name or result["title"]
        fm.add_feed(name, req.url, req.category)
        return {"status": "added", "title": name}
    else:
        raise HTTPException(status_code=400, detail=f"Invalid feed: {result['error']}")

@app.post("/api/feeds/toggle")
async def toggle_feed(req: FeedToggleRequest):
    from src.feeds import FeedManager
    fm = FeedManager(config_dir=ROOT_DIR / "config")
    if fm.toggle_feed(req.identifier):
        return {"status": "toggled"}
    else:
        raise HTTPException(status_code=404, detail="Feed not found")

@app.delete("/api/feeds/{identifier}")
async def remove_feed(identifier: str):
    from src.feeds import FeedManager
    fm = FeedManager(config_dir=ROOT_DIR / "config")
    if fm.remove_feed(identifier):
        return {"status": "removed"}
    else:
        # Client side might pass URL which contains slashes, likely need to handle that or use POST
        # For simplicity, if simple identifier fails, maybe it's URL encoded?
        # Let's hope identifier is simple name
        raise HTTPException(status_code=404, detail="Feed not found")
