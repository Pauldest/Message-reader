# Web UI Module Design Document

## Module Overview

**Module Name**: Web User Interface
**Location**: `src/web/`
**Purpose**: Provide a real-time web interface for managing RSS feeds, monitoring analysis progress, and controlling the Message-reader service.

**Key Features**:
- Real-time progress tracking with WebSocket streaming
- Live log streaming to browser
- Article and feed management
- Manual operation triggers (fetch, analyze, digest)
- Parallel task visualization
- Background task execution
- RESTful API endpoints

---

## File Structure

```
src/web/
├── __init__.py                   # Package exports
├── server.py                     # FastAPI application (300+ lines)
├── socket_manager.py             # WebSocket connection manager (73 lines)
├── progress_tracker.py           # Progress tracking system (200+ lines)
└── static/
    ├── index.html                # Main web interface
    ├── style.css                 # Styling
    └── app.js                    # Frontend JavaScript
```

**Lines of Code**: ~800 lines (backend) + ~500 lines (frontend)
**Complexity**: Medium-High (real-time communication, async operations)

---

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                     Browser Client                            │
│                                                               │
│  ┌────────────┐  ┌────────────┐  ┌─────────────────┐       │
│  │ HTML/CSS   │  │ JavaScript │  │ WebSocket Client│       │
│  │ UI         │  │ Controllers│  │                 │       │
│  └────────────┘  └────────────┘  └────────┬────────┘       │
└───────────────────────────────────────────┼─────────────────┘
                                             │
                                WebSocket    │ HTTP/REST
                                             │
┌────────────────────────────────────────────┼─────────────────┐
│                    FastAPI Server          │                  │
│                                            │                  │
│  ┌──────────────┐         ┌───────────────▼──────────┐      │
│  │  WebSocket   │◄────────┤  ConnectionManager       │      │
│  │  /ws/logs    │         │  - active_connections[]  │      │
│  └──────────────┘         │  - broadcast()           │      │
│                           │  - broadcast_progress()  │      │
│                           └──────────────────────────┘      │
│                                      │                       │
│  ┌──────────────┐         ┌─────────▼──────────────┐       │
│  │  REST API    │         │  WebSocketLogHandler   │       │
│  │  Endpoints   │         │  (structlog processor) │       │
│  └──────┬───────┘         └────────────────────────┘       │
│         │                                                    │
│         │                 ┌────────────────────────┐        │
│         └────────────────►│  ProgressTracker       │        │
│                           │  - state: ProgressState│        │
│                           │  - parallel_tasks{}    │        │
│                           └──────────┬─────────────┘        │
│                                      │                       │
│  ┌───────────────────────────────────▼─────────────────┐   │
│  │        RSSReaderService (main)                       │   │
│  │  - fetch_all()                                       │   │
│  │  - analyze_all()                                     │   │
│  │  - send_digest()                                     │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## Key Components

### 1. FastAPI Server (server.py)

**Web application server with RESTful API and WebSocket support.**

#### Initialization & Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global service
    config = get_config()

    # Initialize progress tracker with broadcast function
    progress_tracker = ProgressTracker(broadcast_fn=manager.broadcast_progress)
    set_progress_tracker(progress_tracker)

    # Initialize RSS reader service
    service = RSSReaderService(
        config,
        analysis_mode="deep",
        concurrency=5,
        progress_tracker=progress_tracker
    )
    logger.info("web_server_started")
    yield

    # Cleanup on shutdown
    if service and service._running:
        service.stop()
    logger.info("web_server_stopped")

app = FastAPI(lifespan=lifespan)
```

**Key Features**:
- Global service instance management
- Progress tracker initialization with WebSocket broadcast
- Graceful shutdown handling
- Static file serving for frontend

#### API Endpoints

**1. GET `/` - Main Interface**
```python
@app.get("/")
async def read_root():
    return FileResponse(str(static_dir / "index.html"))
```

**2. GET `/api/status` - Service Status**
```python
@app.get("/api/status")
async def get_status():
    stats = {}
    if service and hasattr(service, "orchestrator"):
         stats = service.orchestrator.get_stats()

    return {
        "running": is_running,
        "mode": service.analysis_mode.value if service else "unknown",
        "stats": stats  # {total_articles, analyzed_count, etc.}
    }
```

**Response Example**:
```json
{
  "running": false,
  "mode": "deep",
  "stats": {
    "total_articles": 150,
    "analyzed_count": 45,
    "pending_count": 105
  }
}
```

**3. GET `/api/progress/state` - Progress Recovery**
```python
@app.get("/api/progress/state")
async def get_progress_state():
    """Get current progress state (for page refresh recovery)"""
    tracker = get_progress_tracker()
    if tracker:
        return tracker.get_state()
    return {"phase": "idle", "phase_display": "空闲", "parallel_tasks": []}
```

**Purpose**: Allow frontend to recover progress state after page refresh

**4. POST `/api/run` - Trigger Fetch & Analyze**
```python
class RunRequest(BaseModel):
    limit: Optional[int] = None
    dry_run: bool = False
    concurrency: int = 5

@app.post("/api/run")
async def run_task(req: RunRequest, background_tasks: BackgroundTasks):
    global is_running
    if is_running:
        raise HTTPException(status_code=400, detail="Task already running")

    background_tasks.add_task(
        run_worker,
        limit=req.limit,
        dry_run=req.dry_run,
        concurrency=req.concurrency
    )
    return {"status": "started", "concurrency": req.concurrency}
```

**Background Worker**:
```python
async def run_worker(limit: int = None, dry_run: bool = False, concurrency: int = 5):
    global is_running
    if is_running:
        return

    is_running = True
    try:
        # Dynamically adjust concurrency
        service.concurrency = concurrency
        service.orchestrator.concurrency = concurrency

        logger.info("worker_started", limit=limit, dry_run=dry_run, concurrency=concurrency)
        await service.run_once(limit=limit, dry_run=dry_run)
    except Exception as e:
        logger.error("worker_failed", error=str(e))
    finally:
        is_running = False
        logger.info("worker_finished")
```

**5. POST `/api/digest` - Generate and Send Digest**
```python
@app.post("/api/digest")
async def generate_digest(background_tasks: BackgroundTasks):
    if is_running:
        raise HTTPException(status_code=400, detail="Task already running")

    background_tasks.add_task(digest_worker)
    return {"status": "started"}
```

**6. GET `/api/articles` - List Articles**
```python
@app.get("/api/articles")
async def list_articles(limit: int = 50, offset: int = 0):
    articles = service.db.get_all_articles(limit=limit, offset=offset)
    return {"articles": [a.dict() for a in articles]}
```

**7. DELETE `/api/articles/{article_id}` - Delete Article**
```python
@app.delete("/api/articles/{article_id}")
async def delete_article(article_id: int):
    success = service.db.delete_article(article_id)
    return {"success": success}
```

**8. GET `/api/feeds` - List Feeds**
```python
@app.get("/api/feeds")
async def list_feeds():
    feeds = service.feed_manager.list_feeds()
    return {"feeds": feeds}
```

**9. POST `/api/feeds` - Add Feed**
```python
class FeedRequest(BaseModel):
    name: str
    url: str
    category: str = "未分类"

@app.post("/api/feeds")
async def add_feed(req: FeedRequest):
    service.feed_manager.add_feed(req.name, req.url, req.category)
    return {"status": "added"}
```

**10. DELETE `/api/feeds` - Remove Feed**
```python
@app.delete("/api/feeds")
async def remove_feed(req: FeedToggleRequest):
    service.feed_manager.remove_feed(req.identifier)
    return {"status": "removed"}
```

**11. WebSocket `/ws/logs` - Real-time Logs**
```python
@app.websocket("/ws/logs")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, can receive commands from frontend
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

---

### 2. WebSocket Manager (socket_manager.py)

**Manages WebSocket connections and broadcasts messages to all connected clients.**

#### ConnectionManager Class

```python
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept and register new WebSocket connection"""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcast message to all connected clients"""
        payload = json.dumps(message, default=str)
        # Copy list to avoid modification during iteration
        for connection in list(self.active_connections):
            try:
                await connection.send_text(payload)
            except Exception:
                # Ignore send errors, disconnection handled in receive loop
                pass

    async def broadcast_progress(self, event: Dict[str, Any]):
        """Broadcast progress update messages"""
        await self.broadcast(event)

# Global singleton instance
manager = ConnectionManager()
```

**Features**:
- Thread-safe connection management
- Broadcast to all clients simultaneously
- Automatic error handling for disconnected clients
- Separate method for progress updates

#### WebSocketLogHandler (structlog processor)

```python
class WebSocketLogHandler:
    """Structlog processor to intercept logs and send to WebSocket"""

    def __call__(self, logger, name, event_dict):
        try:
            log_entry = {
                "type": "log",
                "timestamp": datetime.now().isoformat(),
                "level": event_dict.get("level", "info").upper(),
                "event": event_dict.get("event", ""),
                "logger": name,
                "context": {
                    k: v for k, v in event_dict.items()
                    if k not in ["level", "event", "timestamp"]
                }
            }

            # Only broadcast if there are active connections
            if manager.active_connections:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(manager.broadcast(log_entry))
                except RuntimeError:
                    # No running loop (rare case), cannot broadcast
                    pass

        except Exception:
            # Prevent logging system crash
            pass

        return event_dict
```

**Integration**:
```python
def configure_logging():
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            WebSocketLogHandler(),  # Add WebSocket processor
            structlog.processors.JSONRenderer(),
        ]
    )
```

**Message Format**:
```json
{
  "type": "log",
  "timestamp": "2026-01-18T14:30:45.123456",
  "level": "INFO",
  "event": "article_analyzed",
  "logger": "src.agents.orchestrator",
  "context": {
    "article_id": 123,
    "duration": 2.5,
    "tokens": 1500
  }
}
```

---

### 3. Progress Tracker (progress_tracker.py)

**Tracks and broadcasts real-time progress updates for long-running operations.**

#### Data Models

**ProgressPhase Enum**:
```python
class ProgressPhase(str, Enum):
    IDLE = "idle"
    FETCHING_RSS = "fetching_rss"
    EXTRACTING_CONTENT = "extracting_content"
    ANALYZING = "analyzing"
    SENDING_DIGEST = "sending_digest"
    COMPLETED = "completed"
    ERROR = "error"
```

**TaskStatus Enum**:
```python
class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
```

**ParallelTask**:
```python
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
```

**ProgressState**:
```python
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
```

#### ProgressTracker Class

```python
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
        self.state = ProgressState()
        self.broadcast_fn = broadcast_fn
        self._lock = asyncio.Lock()
```

**Key Methods**:

**1. start_operation()**
```python
async def start_operation(self):
    """Start a new operation"""
    async with self._lock:
        self.state = ProgressState(started_at=datetime.now().isoformat())
        await self._broadcast()
```

**2. set_phase()**
```python
async def set_phase(self, phase: ProgressPhase, message: str = "", phase_display: str = None):
    """Update current phase"""
    async with self._lock:
        self.state.phase = phase
        self.state.message = message
        if phase_display:
            self.state.phase_display = phase_display
        await self._broadcast()
```

**3. add_task()**
```python
async def add_task(self, title: str, task_id: str = None) -> str:
    """Add a new parallel task and return its ID"""
    if task_id is None:
        task_id = str(uuid.uuid4())[:8]

    async with self._lock:
        task = ParallelTask(
            id=task_id,
            title=title,
            started_at=datetime.now().isoformat()
        )
        self.state.parallel_tasks[task_id] = task
        self.state.total_items = len(self.state.parallel_tasks)
        await self._broadcast()

    return task_id
```

**4. update_task()**
```python
async def update_task(self, task_id: str, step: str = None, progress: int = None, status: TaskStatus = None):
    """Update a task's progress"""
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
```

**5. complete_task()**
```python
async def complete_task(self, task_id: str, error: str = None):
    """Mark a task as completed or failed"""
    async with self._lock:
        if task_id not in self.state.parallel_tasks:
            return

        task = self.state.parallel_tasks[task_id]
        task.completed_at = datetime.now().isoformat()
        task.progress = 100

        if error:
            task.status = TaskStatus.FAILED
            task.error = error
        else:
            task.status = TaskStatus.COMPLETED

        self.state.completed_items += 1
        self.state.overall_progress = int(
            (self.state.completed_items / self.state.total_items) * 100
        ) if self.state.total_items > 0 else 0

        await self._broadcast()
```

**6. finish()**
```python
async def finish(self, error: str = None):
    """Finish the operation"""
    async with self._lock:
        if error:
            self.state.phase = ProgressPhase.ERROR
            self.state.message = error
        else:
            self.state.phase = ProgressPhase.COMPLETED
            self.state.message = "操作完成"

        self.state.overall_progress = 100
        await self._broadcast()
```

**7. get_state()**
```python
def get_state(self) -> dict:
    """Get current state (for API endpoint)"""
    return self.state.to_dict()
```

**8. _broadcast()**
```python
async def _broadcast(self):
    """Broadcast current state to WebSocket clients"""
    if self.broadcast_fn:
        message = {
            "type": "progress",
            **self.state.to_dict()
        }
        await self.broadcast_fn(message)
```

#### Global Singleton Pattern

```python
_global_tracker: Optional[ProgressTracker] = None

def set_progress_tracker(tracker: ProgressTracker):
    """Set global progress tracker"""
    global _global_tracker
    _global_tracker = tracker

def get_progress_tracker() -> Optional[ProgressTracker]:
    """Get global progress tracker"""
    return _global_tracker
```

---

## Data Flow Patterns

### Pattern 1: Progress Update Flow

```
User Action (Browser)
    │
    └─► POST /api/run
            │
            ├─► BackgroundTask: run_worker()
            │       │
            │       ├─► service.run_once()
            │       │       │
            │       │       ├─► fetch_all()
            │       │       │       │
            │       │       │       ├─► tracker.set_phase(FETCHING_RSS)
            │       │       │       │       │
            │       │       │       │       └─► broadcast(progress_message)
            │       │       │       │               │
            │       │       │       │               └─► WebSocket → Browser
            │       │       │       │
            │       │       │       └─► For each feed:
            │       │       │               tracker.add_task()
            │       │       │               tracker.update_task()
            │       │       │               tracker.complete_task()
            │       │       │
            │       │       ├─► analyze_all()
            │       │       │       │
            │       │       │       ├─► tracker.set_phase(ANALYZING)
            │       │       │       └─► For each article:
            │       │       │               tracker.add_task()
            │       │       │               tracker.update_task()
            │       │       │               tracker.complete_task()
            │       │       │
            │       │       └─► tracker.finish()
            │       │
            │       └─► is_running = False
            │
            └─► Response: {"status": "started"}
```

### Pattern 2: Log Streaming Flow

```
Application Code
    │
    └─► logger.info("event_name", key=value)
            │
            └─► structlog.process()
                    │
                    ├─► WebSocketLogHandler()
                    │       │
                    │       └─► Format log entry
                    │               │
                    │               └─► manager.broadcast(log_entry)
                    │                       │
                    │                       └─► For each WebSocket:
                    │                               websocket.send_text(json)
                    │
                    └─► JSONRenderer() → Console/File
```

### Pattern 3: Page Refresh Recovery

```
Browser Refresh
    │
    └─► GET /api/progress/state
            │
            └─► tracker.get_state()
                    │
                    └─► Return current ProgressState
                            │
                            └─► Browser updates UI to match current state
```

---

## Frontend Integration

### WebSocket Connection

```javascript
const ws = new WebSocket('ws://localhost:8000/ws/logs');

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    if (data.type === 'log') {
        appendLog(data.level, data.event, data.context);
    } else if (data.type === 'progress') {
        updateProgress(data);
    }
};

ws.onerror = (error) => {
    console.error('WebSocket error:', error);
};

ws.onclose = () => {
    console.log('WebSocket closed, attempting reconnect...');
    setTimeout(connectWebSocket, 3000);
};
```

### Progress Update Handling

```javascript
function updateProgress(data) {
    // Update overall progress
    document.getElementById('overall-progress').style.width = data.overall_progress + '%';
    document.getElementById('phase-display').textContent = data.phase_display;
    document.getElementById('phase-message').textContent = data.message;

    // Update parallel tasks
    const tasksContainer = document.getElementById('parallel-tasks');
    tasksContainer.innerHTML = '';

    data.parallel_tasks.forEach(task => {
        const taskElement = createTaskElement(task);
        tasksContainer.appendChild(taskElement);
    });
}

function createTaskElement(task) {
    return `
        <div class="task-card ${task.status}">
            <div class="task-title">${task.title}</div>
            <div class="task-step">${task.step}</div>
            <div class="task-progress">
                <div class="progress-bar" style="width: ${task.progress}%"></div>
            </div>
            ${task.error ? `<div class="task-error">${task.error}</div>` : ''}
        </div>
    `;
}
```

---

## Design Patterns Used

### 1. Singleton Pattern
- **ProgressTracker**: Global singleton instance
- **ConnectionManager**: Single manager for all WebSocket connections

### 2. Observer Pattern
- **WebSocketLogHandler**: Observes log events, broadcasts to clients
- **ProgressTracker**: Observes operation progress, broadcasts updates

### 3. Facade Pattern
- **FastAPI App**: Simplifies complex service operations into simple API endpoints

### 4. Background Task Pattern
- **BackgroundTasks**: Long-running operations execute in background
- **Non-blocking API**: Returns immediately while work continues

### 5. Publisher-Subscriber Pattern
- **WebSocket Broadcasting**: Publisher broadcasts to multiple subscribers

---

## Error Handling Strategy

### API Error Handling

```python
@app.post("/api/run")
async def run_task(req: RunRequest, background_tasks: BackgroundTasks):
    if is_running:
        raise HTTPException(
            status_code=400,
            detail="Task already running"
        )

    try:
        background_tasks.add_task(run_worker, ...)
        return {"status": "started"}
    except Exception as e:
        logger.error("api_error", endpoint="/api/run", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )
```

### WebSocket Error Handling

```python
async def broadcast(self, message: Dict[str, Any]):
    payload = json.dumps(message, default=str)
    for connection in list(self.active_connections):
        try:
            await connection.send_text(payload)
        except Exception:
            # Silently ignore send errors
            # Connection cleanup handled by disconnect event
            pass
```

### Progress Tracker Error Handling

```python
async def complete_task(self, task_id: str, error: str = None):
    async with self._lock:
        if task_id not in self.state.parallel_tasks:
            logger.warning("task_not_found", task_id=task_id)
            return

        task = self.state.parallel_tasks[task_id]
        if error:
            task.status = TaskStatus.FAILED
            task.error = error
            logger.error("task_failed", task_id=task_id, error=error)
```

---

## Performance Considerations

### 1. Async Operations
- All I/O operations are async (database, HTTP, WebSocket)
- Background tasks for long-running operations
- Non-blocking API endpoints

### 2. Connection Management
- Efficient WebSocket connection pooling
- Automatic cleanup of disconnected clients
- Broadcast to multiple clients in parallel

### 3. State Management
- In-memory state for fast access
- Lock-based synchronization to prevent race conditions
- Minimal serialization overhead (direct dict conversion)

### 4. Concurrency Control
- Configurable concurrency limits for analysis
- Semaphore-based rate limiting
- Background task isolation

---

## Security Considerations

### 1. CORS Configuration
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 2. Input Validation
- Pydantic models for request validation
- Type checking and constraints
- Automatic error responses for invalid input

### 3. Rate Limiting
- Consider adding rate limiting for API endpoints
- Prevent abuse of compute-intensive operations

---

## Testing Strategy

### Unit Tests

```python
@pytest.mark.asyncio
async def test_progress_tracker():
    events = []

    async def mock_broadcast(message):
        events.append(message)

    tracker = ProgressTracker(broadcast_fn=mock_broadcast)

    await tracker.start_operation()
    assert len(events) == 1
    assert events[0]["type"] == "progress"

    task_id = await tracker.add_task("Test Task")
    await tracker.update_task(task_id, step="processing", progress=50)
    await tracker.complete_task(task_id)

    assert tracker.state.completed_items == 1
    assert tracker.state.overall_progress == 100
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_api_run_endpoint():
    from fastapi.testclient import TestClient

    client = TestClient(app)

    response = client.post("/api/run", json={
        "limit": 10,
        "dry_run": True,
        "concurrency": 3
    })

    assert response.status_code == 200
    assert response.json()["status"] == "started"
```

### WebSocket Tests

```python
@pytest.mark.asyncio
async def test_websocket_broadcast():
    from fastapi.testclient import TestClient

    with TestClient(app).websocket_connect("/ws/logs") as websocket:
        # Trigger a log event
        logger.info("test_event", data="test")

        # Receive message
        data = websocket.receive_json()
        assert data["type"] == "log"
        assert data["event"] == "test_event"
```

---

## Extension Points

### 1. Adding New API Endpoints

```python
@app.get("/api/custom-endpoint")
async def custom_endpoint():
    # Custom logic
    return {"data": "custom"}
```

### 2. Custom Progress Phases

```python
class ProgressPhase(str, Enum):
    # ... existing phases
    CUSTOM_PHASE = "custom_phase"

# Usage
await tracker.set_phase(
    ProgressPhase.CUSTOM_PHASE,
    "Doing custom operation...",
    phase_display="自定义操作"
)
```

### 3. Additional WebSocket Channels

```python
@app.websocket("/ws/custom-channel")
async def custom_websocket(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle custom messages
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

---

## Dependencies

### Internal
- `src/config.py`: Configuration management
- `src/main.py`: RSSReaderService
- `src/models/`: Data models
- `src/storage/`: Database access

### External
- `fastapi`: Web framework
- `uvicorn`: ASGI server
- `websockets`: WebSocket support
- `pydantic`: Request/response validation
- `structlog`: Structured logging
- `jinja2`: Template rendering (optional)

---

## Configuration

### Server Configuration

```yaml
web:
  host: "0.0.0.0"
  port: 8000
  reload: false  # Development only
  log_level: "info"

  # CORS settings
  cors_origins:
    - "http://localhost:3000"
    - "https://your-domain.com"

  # WebSocket settings
  ws_heartbeat_interval: 30  # seconds
  ws_max_connections: 100

  # Background task settings
  max_concurrent_tasks: 3
  task_timeout: 3600  # seconds
```

---

## Deployment

### Development

```bash
# Run with auto-reload
uvicorn src.web.server:app --reload --host 0.0.0.0 --port 8000
```

### Production

```bash
# Run with Gunicorn + Uvicorn workers
gunicorn src.web.server:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --timeout 300 \
  --access-logfile - \
  --error-logfile -
```

### Docker

```dockerfile
FROM python:3.10-slim

WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

EXPOSE 8000

CMD ["uvicorn", "src.web.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Monitoring & Observability

### Metrics to Track

- **API Metrics**:
  - Request count per endpoint
  - Response times
  - Error rates

- **WebSocket Metrics**:
  - Active connections
  - Messages sent/received
  - Broadcast latency

- **Progress Metrics**:
  - Operation durations
  - Task success/failure rates
  - Parallel task efficiency

### Logging

```python
# Structured logging examples
logger.info("api_request", endpoint="/api/run", method="POST", user_ip=request.client.host)
logger.info("websocket_connected", client_id=websocket.client.id)
logger.info("progress_update", phase="analyzing", completed=10, total=50)
logger.error("api_error", endpoint="/api/run", error=str(e), traceback=traceback.format_exc())
```

---

## Future Enhancements

### 1. Authentication & Authorization
- User login/logout
- Role-based access control
- API key authentication

### 2. Multi-User Support
- Per-user feed subscriptions
- Personalized dashboards
- User preference management

### 3. Enhanced Visualization
- Real-time charts (D3.js, Chart.js)
- Network graphs for knowledge graph
- Timeline visualization

### 4. Advanced Features
- WebSocket command channel (pause/resume operations)
- Real-time configuration editing
- Drag-and-drop feed upload
- Export/import configurations

---

## Summary

The Web UI module provides a modern, real-time interface for the Message-reader system with:

**Strengths**:
- ✅ Real-time progress tracking with WebSocket
- ✅ Live log streaming to browser
- ✅ Non-blocking background task execution
- ✅ Comprehensive API coverage
- ✅ State recovery after page refresh
- ✅ Clean separation of concerns

**Innovations**:
- 🎯 Parallel task visualization
- 🎯 Dual-channel communication (REST + WebSocket)
- 🎯 Dynamic concurrency control
- 🎯 Integrated progress tracking system

**Best Practices**:
- Async-first architecture
- Proper error handling
- Type-safe request/response models
- Structured logging
- Graceful degradation

This module transforms the Message-reader from a CLI tool into a **production-ready web application** with enterprise-grade real-time monitoring capabilities.
