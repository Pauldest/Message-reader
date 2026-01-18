# Services Layer Design Document

## Module Overview

**Module Name**: Services Layer
**Location**: `src/services/`
**Purpose**: Provide unified interfaces for external services including LLM API calls, embedding generation, and AI telemetry tracking.

**Key Features**:
- Unified LLM interface with automatic retry logic
- Robust JSON parsing with fallback strategies
- Comprehensive AI call telemetry and cost tracking
- Context-aware session and agent tracking
- Thread-safe singleton pattern for telemetry
- Automatic error recovery and degradation

---

## File Structure

```
src/services/
├── __init__.py                   # Package exports
├── llm.py                        # LLM service (258 lines)
├── telemetry.py                  # Telemetry service (261 lines)
└── embedding.py                  # Embedding service
```

**Lines of Code**: ~520 lines (core services)
**Complexity**: Medium (handles external API integration)

---

## Class Diagrams

### LLM Service Architecture

```
┌─────────────────────────────────┐
│        LLMService               │
│                                 │
│  - client: AsyncOpenAI          │
│  - config: AIConfig             │
│  - model: str                   │
│                                 │
│  + chat()                       │──┐
│  + chat_json()                  │  │
│  + parse_json()                 │  │
│  + build_messages()             │  │
│  + _exponential_backoff()       │  │
└─────────────────────────────────┘  │
                                     │
                    ┌────────────────┘
                    │
                    ▼
         ┌──────────────────────┐
         │  Telemetry Service   │◄────── Records all calls
         │                      │
         │  - record_chat()     │
         │  - record_chat_json()│
         └──────────────────────┘
```

### Telemetry Service Singleton

```
┌────────────────────────────────────┐
│       AITelemetry (Singleton)      │
│                                    │
│  - _instance: Optional[AITelemetry]│
│  - _lock: threading.Lock           │
│  - store: TelemetryStore           │
│  - enabled: bool                   │
│                                    │
│  Class Methods:                    │
│  + get_instance()                  │
│  + initialize()                    │
│                                    │
│  Instance Methods:                 │
│  + record()                        │
│  + record_chat()                   │
│  + record_chat_json()              │
│  + query()                         │
│  + get_stats()                     │
└────────────────────────────────────┘
         │
         │ uses
         ▼
┌──────────────────┐
│ TelemetryStore   │
│                  │
│ - append()       │
│ - query()        │
│ - get_stats()    │
└──────────────────┘
```

### Context Variables

```
┌─────────────────────────┐
│  Context Variables      │
│  (thread/async-safe)    │
│                         │
│  _current_session       │───► ContextVar[str]
│  _current_agent         │───► ContextVar[str]
└─────────────────────────┘
             │
             │ provides context to
             ▼
┌─────────────────────────┐
│    AICallRecord         │
│                         │
│  - session_id           │
│  - agent_name           │
│  - messages             │
│  - response             │
│  - token_usage          │
└─────────────────────────┘
```

---

## Key Components

### 1. LLMService (llm.py)

**Unified interface for all LLM interactions.**

#### Core Responsibilities:
- OpenAI-compatible API calls (DeepSeek, OpenAI, etc.)
- Automatic retry with exponential backoff
- Token usage tracking
- Robust JSON response parsing
- Integration with telemetry service

#### Initialization:

```python
class LLMService:
    def __init__(self, config: AIConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.default_max_tokens = config.max_tokens
        self.default_temperature = config.temperature
```

#### Chat Method (Core):

```python
async def chat(
    self,
    messages: list[dict],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    json_mode: bool = False,
    retry_count: int = 3,
) -> tuple[str, dict]:
    """
    Send chat request with automatic retry.

    Args:
        messages: OpenAI format messages
        max_tokens: Override default max tokens
        temperature: Override default temperature
        json_mode: Hint for JSON output (model-dependent)
        retry_count: Number of retry attempts

    Returns:
        (response_text, token_usage)

    Raises:
        Last exception if all retries fail
    """
    max_tokens = max_tokens or self.default_max_tokens
    temperature = temperature if temperature is not None else self.default_temperature

    call_id = str(uuid.uuid4())
    start_time = time.time()
    last_error = None

    for attempt in range(retry_count):
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            duration_ms = int((time.time() - start_time) * 1000)
            content = response.choices[0].message.content or ""

            token_usage = {
                "prompt": response.usage.prompt_tokens,
                "completion": response.usage.completion_tokens,
                "total": response.usage.total_tokens,
            }

            # Record successful call
            telemetry = _get_telemetry()
            if telemetry:
                telemetry.record_chat(
                    model=self.model,
                    messages=messages,
                    response=content,
                    token_usage=token_usage,
                    duration_ms=duration_ms,
                    retry_count=attempt,
                    caller="LLMService.chat",
                )

            return content, token_usage

        except Exception as e:
            last_error = e
            logger.warning("llm_call_failed", attempt=attempt + 1, error=str(e))

            if attempt < retry_count - 1:
                await self._exponential_backoff(attempt)

    # Record failed call
    duration_ms = int((time.time() - start_time) * 1000)
    telemetry = _get_telemetry()
    if telemetry:
        telemetry.record_chat(
            model=self.model,
            messages=messages,
            response="",
            token_usage={"prompt": 0, "completion": 0, "total": 0},
            duration_ms=duration_ms,
            error=str(last_error),
            caller="LLMService.chat",
        )

    raise last_error
```

#### JSON Parsing (Robust):

```python
@staticmethod
def parse_json(content: str) -> Optional[dict]:
    """
    Parse AI-generated JSON with multiple fallback strategies.

    Strategies:
    1. Direct JSON parse
    2. Extract from ```json ... ``` code block
    3. Extract first {...} braces content

    Args:
        content: Raw LLM response

    Returns:
        Parsed dict or None if all strategies fail
    """
    if not content:
        return None

    # Strategy 1: Direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from code block
    json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Strategy 3: Extract first brace content
    brace_match = re.search(r'\{[\s\S]*\}', content)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    logger.warning("json_parse_failed", content_preview=content[:200])
    return None
```

#### Chat JSON (Convenience Method):

```python
async def chat_json(
    self,
    messages: list[dict],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    retry_count: int = 3,
) -> tuple[Optional[dict], dict]:
    """
    Chat with automatic JSON parsing.

    Returns:
        (parsed_json, token_usage)
        parsed_json is None if parsing fails
    """
    content, token_usage = await self.chat(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        json_mode=True,
        retry_count=retry_count,
    )

    parsed = self.parse_json(content)

    # Additional telemetry for JSON parsing
    telemetry = _get_telemetry()
    if telemetry:
        telemetry.record_chat_json(
            model=self.model,
            messages=messages,
            response=content,
            parsed_json=parsed,
            token_usage=token_usage,
            duration_ms=0,  # Already recorded in chat()
            caller="LLMService.chat_json",
        )

    return parsed, token_usage
```

#### Retry Strategy:

```python
async def _exponential_backoff(self, attempt: int):
    """Exponential backoff with jitter"""
    wait_time = min(2 ** attempt, 30)  # Max 30 seconds
    await asyncio.sleep(wait_time)
```

#### Message Builder:

```python
def build_messages(
    self,
    system_prompt: str,
    user_prompt: str,
    examples: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Build OpenAI message format with few-shot examples.

    Args:
        system_prompt: System instruction
        user_prompt: User query
        examples: Few-shot examples [{"user": "...", "assistant": "..."}]

    Returns:
        List of message dicts
    """
    messages = [{"role": "system", "content": system_prompt}]

    if examples:
        for example in examples:
            messages.append({"role": "user", "content": example["user"]})
            messages.append({"role": "assistant", "content": example["assistant"]})

    messages.append({"role": "user", "content": user_prompt})

    return messages
```

---

### 2. AITelemetry (telemetry.py)

**Singleton service for tracking all AI API calls.**

#### Design Pattern: Thread-Safe Singleton

```python
class AITelemetry:
    _instance: Optional["AITelemetry"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:  # Double-check
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
```

#### Context Management (AsyncIO-Safe):

```python
# Module-level context variables
_current_session: ContextVar[Optional[str]] = ContextVar("current_session", default=None)
_current_agent: ContextVar[Optional[str]] = ContextVar("current_agent", default=None)

class AITelemetry:
    @staticmethod
    def set_session(session_id: Optional[str]):
        """Set current session ID for context tracking"""
        _current_session.set(session_id)

    @staticmethod
    def get_session() -> Optional[str]:
        """Get current session ID"""
        return _current_session.get()

    @staticmethod
    def set_agent(agent_name: Optional[str]):
        """Set current agent name for context tracking"""
        _current_agent.set(agent_name)

    @staticmethod
    def get_agent() -> Optional[str]:
        """Get current agent name"""
        return _current_agent.get()
```

#### Recording Methods:

```python
def record(self, record: AICallRecord):
    """
    Record an AI call with automatic context injection.

    Args:
        record: Call record to store
    """
    if not self.enabled or not self.store:
        return

    # Auto-fill context from ContextVars
    if record.session_id is None:
        record.session_id = self.get_session()
    if record.agent_name is None:
        record.agent_name = self.get_agent()

    # Truncate long content
    self._truncate_content(record)

    # Write to storage
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
    """Record a chat completion call"""
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
    """Record a JSON chat call with parsing result"""
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
```

#### Content Truncation:

```python
def _truncate_content(self, record: AICallRecord):
    """Truncate overly long content to save storage"""
    max_len = self.max_content_length

    # Truncate message contents
    for msg in record.messages:
        if "content" in msg and isinstance(msg["content"], str):
            if len(msg["content"]) > max_len:
                original_len = len(msg["content"])
                msg["content"] = (
                    msg["content"][:max_len] +
                    f"... [truncated, total {original_len} chars]"
                )

    # Truncate response
    if len(record.response) > max_len:
        original_len = len(record.response)
        record.response = (
            record.response[:max_len] +
            f"... [truncated, total {original_len} chars]"
        )
```

#### Query and Statistics:

```python
def query(self, **kwargs) -> list[dict]:
    """
    Query telemetry records.

    Kwargs:
        start_time, end_time, session_id, agent_name,
        call_type, limit, offset
    """
    if not self.enabled or not self.store:
        return []
    return self.store.query(**kwargs)

def get_stats(self, **kwargs) -> TelemetryStats:
    """
    Get aggregated statistics.

    Returns:
        TelemetryStats with:
        - total_calls, total_tokens
        - calls_by_type, calls_by_agent, calls_by_model
        - avg_duration_ms, error_rate
    """
    if not self.enabled or not self.store:
        return TelemetryStats()
    return self.store.get_stats(**kwargs)

def get_full_record(self, call_id: str) -> Optional[AICallRecord]:
    """Retrieve complete record from JSONL storage"""
    if not self.enabled or not self.store:
        return None
    return self.store.get_full_record(call_id)

def list_sessions(self, limit: int = 20) -> list[dict]:
    """List recent tracking sessions"""
    if not self.enabled or not self.store:
        return []
    return self.store.list_sessions(limit)
```

#### Maintenance:

```python
def cleanup(self) -> int:
    """Clean up old telemetry records"""
    if not self.enabled or not self.store:
        return 0
    return self.store.cleanup_old_records()

def export(self, output_path: str, **kwargs) -> int:
    """Export records to JSONL file"""
    if not self.enabled or not self.store:
        return 0
    return self.store.export_jsonl(output_path, **kwargs)
```

#### Global Access Function:

```python
def get_telemetry() -> AITelemetry:
    """Get the singleton telemetry instance"""
    return AITelemetry.get_instance()
```

---

## API/Interface Documentation

### LLMService API

#### Constructor

```python
def __init__(self, config: AIConfig):
    """
    Initialize LLM service.

    Args:
        config: AI configuration with api_key, base_url, model, etc.
    """
```

#### Core Methods

```python
async def chat(
    self,
    messages: list[dict],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    json_mode: bool = False,
    retry_count: int = 3,
) -> tuple[str, dict]:
    """
    Send chat completion request.

    Args:
        messages: OpenAI format [{"role": "user", "content": "..."}]
        max_tokens: Max completion tokens (default: from config)
        temperature: Sampling temperature 0.0-2.0 (default: from config)
        json_mode: Hint for JSON output
        retry_count: Retry attempts on failure

    Returns:
        (response_content, token_usage_dict)

    Raises:
        Exception: If all retries fail

    Example:
        >>> service = LLMService(config)
        >>> messages = [
        ...     {"role": "system", "content": "You are a helpful assistant"},
        ...     {"role": "user", "content": "What is AI?"}
        ... ]
        >>> response, usage = await service.chat(messages)
        >>> print(f"Used {usage['total']} tokens")
    """

async def chat_json(
    self,
    messages: list[dict],
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    retry_count: int = 3,
) -> tuple[Optional[dict], dict]:
    """
    Chat with automatic JSON parsing.

    Returns:
        (parsed_json_or_none, token_usage)

    Example:
        >>> messages = [{"role": "user", "content": "Return JSON: {\"name\": \"AI\"}"}]
        >>> data, usage = await service.chat_json(messages)
        >>> if data:
        ...     print(data["name"])
    """

@staticmethod
def parse_json(content: str) -> Optional[dict]:
    """
    Robust JSON parsing with fallback strategies.

    Example:
        >>> LLMService.parse_json('{"key": "value"}')
        {'key': 'value'}
        >>> LLMService.parse_json('```json\n{"key": "value"}\n```')
        {'key': 'value'}
    """

def build_messages(
    self,
    system_prompt: str,
    user_prompt: str,
    examples: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Build message list with optional few-shot examples.

    Example:
        >>> messages = service.build_messages(
        ...     system_prompt="You are a summarizer",
        ...     user_prompt="Summarize: ...",
        ...     examples=[
        ...         {"user": "Text A", "assistant": "Summary A"},
        ...         {"user": "Text B", "assistant": "Summary B"}
        ...     ]
        ... )
    """
```

---

### AITelemetry API

#### Singleton Access

```python
@classmethod
def get_instance(cls) -> "AITelemetry":
    """Get singleton instance"""

@classmethod
def initialize(
    cls,
    enabled: bool = True,
    storage_path: str = "data/telemetry",
    retention_days: int = 30,
    max_content_length: int = 10000,
) -> "AITelemetry":
    """Initialize with custom settings"""
```

#### Context Management

```python
@staticmethod
def set_session(session_id: Optional[str]):
    """Set session ID for current async context"""

@staticmethod
def get_session() -> Optional[str]:
    """Get current session ID"""

@staticmethod
def set_agent(agent_name: Optional[str]):
    """Set agent name for current async context"""

@staticmethod
def get_agent() -> Optional[str]:
    """Get current agent name"""
```

#### Recording

```python
def record(self, record: AICallRecord):
    """Record a telemetry event"""

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
    """Record chat call"""

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
    """Record JSON chat call with parsing metadata"""
```

#### Querying

```python
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
    """Query telemetry records"""

def get_stats(
    self,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    session_id: Optional[str] = None,
) -> TelemetryStats:
    """Get aggregated statistics"""

def get_full_record(self, call_id: str) -> Optional[AICallRecord]:
    """Get complete record including full messages"""

def list_sessions(self, limit: int = 20) -> list[dict]:
    """List recent sessions"""
```

---

## Usage Examples

### Basic LLM Usage

```python
from src.services.llm import LLMService
from src.config import get_config

config = get_config()
llm = LLMService(config.ai)

# Simple chat
messages = [
    {"role": "system", "content": "You are a helpful assistant"},
    {"role": "user", "content": "Explain quantum computing in one sentence"}
]
response, usage = await llm.chat(messages)
print(f"Response: {response}")
print(f"Tokens: {usage['total']}")

# JSON output
json_messages = [
    {"role": "user", "content": "Return a JSON with fields: name, age, city"}
]
data, usage = await llm.chat_json(json_messages)
if data:
    print(f"Name: {data.get('name')}")
```

### Telemetry Tracking

```python
from src.services.telemetry import AITelemetry

# Initialize (usually done at app startup)
telemetry = AITelemetry.initialize(
    enabled=True,
    storage_path="data/telemetry",
    retention_days=30
)

# Set context for tracking
telemetry.set_session("session_123")
telemetry.set_agent("CollectorAgent")

# Calls are automatically tracked by LLMService
# ...

# Query statistics
stats = telemetry.get_stats(
    start_time=datetime.now() - timedelta(days=7)
)
print(f"Total calls: {stats.total_calls}")
print(f"Total tokens: {stats.total_tokens}")
print(f"Average duration: {stats.avg_duration_ms}ms")
print(f"Error rate: {stats.error_rate:.1f}%")

# Query by agent
records = telemetry.query(agent_name="CollectorAgent", limit=10)
for r in records:
    print(f"{r['timestamp']}: {r['total_tokens']} tokens")
```

### Session Tracking

```python
import uuid
from src.services.telemetry import get_telemetry

async def analyze_article(article):
    # Create session for this analysis
    session_id = str(uuid.uuid4())
    telemetry = get_telemetry()
    telemetry.set_session(session_id)

    # All LLM calls in this context will be grouped
    telemetry.set_agent("CollectorAgent")
    result1 = await collector_agent.analyze(article)

    telemetry.set_agent("EditorAgent")
    result2 = await editor_agent.process(result1)

    # View session summary
    sessions = telemetry.list_sessions(limit=1)
    print(f"Session used {sessions[0]['total_tokens']} tokens")
```

---

## Data Flow

### LLM Call Flow

```
User Code
   │
   ├─► LLMService.chat()
   │      │
   │      ├─► AsyncOpenAI.chat.completions.create()
   │      │      │
   │      │      ├─► Success ──┐
   │      │      └─► Failure ──┤
   │      │                    │
   │      ├─► Retry Logic ◄────┘
   │      │
   │      └─► Telemetry.record_chat()
   │             │
   │             └─► TelemetryStore.append()
   │                    │
   │                    ├─► JSONL file
   │                    └─► SQLite index
   │
   └─► (response, token_usage)
```

### JSON Parsing Flow

```
LLM Response (string)
   │
   ├─► Strategy 1: json.loads()
   │      └─► Success? ──► Return dict
   │      └─► Fail ──┐
   │                │
   ├─► Strategy 2: Extract ```json...```
   │      └─► Success? ──► Return dict
   │      └─► Fail ──┤
   │                │
   ├─► Strategy 3: Extract {...}
   │      └─► Success? ──► Return dict
   │      └─► Fail ──┤
   │                │
   └─► Return None ◄─┘
```

### Telemetry Context Flow

```
┌──────────────────┐
│   Main Thread    │
│                  │
│  set_session()   │──► ContextVar stores "session_123"
└──────────────────┘
         │
         ├─────────────────┬─────────────────┐
         │                 │                 │
    ┌────▼────┐      ┌────▼────┐      ┌────▼────┐
    │ Task 1  │      │ Task 2  │      │ Task 3  │
    │         │      │         │      │         │
    │ Agent A │      │ Agent B │      │ Agent C │
    │         │      │         │      │         │
    │ LLM call│      │ LLM call│      │ LLM call│
    └────┬────┘      └────┬────┘      └────┬────┘
         │                 │                 │
         └─────────────────┴─────────────────┘
                           │
                    All inherit session_id
                    from ContextVar
```

---

## Design Patterns

### 1. Singleton Pattern (Thread-Safe)

```python
class AITelemetry:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
```

**Why**: Ensure single telemetry instance across entire application.

### 2. Strategy Pattern (JSON Parsing)

```python
def parse_json(content: str) -> Optional[dict]:
    strategies = [
        DirectParse(),
        CodeBlockExtract(),
        BraceExtract(),
    ]
    for strategy in strategies:
        result = strategy.try_parse(content)
        if result:
            return result
    return None
```

**Why**: Multiple fallback strategies for robustness.

### 3. Decorator Pattern (Delayed Telemetry)

```python
def _get_telemetry():
    """Lazy loading to avoid circular imports"""
    global _telemetry
    if _telemetry is None:
        from .telemetry import get_telemetry
        _telemetry = get_telemetry()
    return _telemetry
```

**Why**: Break circular dependencies between modules.

### 4. Context Manager Pattern (Implicit)

```python
# Using ContextVar for async-safe context
_current_session = ContextVar("current_session", default=None)

# Each async task gets isolated context
telemetry.set_session("session_123")  # Only affects current task
```

**Why**: Async-safe context propagation without explicit passing.

---

## Error Handling

### LLM Retry Strategy

```python
async def chat(self, messages, retry_count=3):
    for attempt in range(retry_count):
        try:
            return await self._make_api_call(messages)
        except Exception as e:
            if attempt < retry_count - 1:
                await self._exponential_backoff(attempt)
            else:
                raise  # Give up after all retries
```

### Telemetry Non-Blocking

```python
def record(self, record):
    try:
        self.store.append(record)
    except Exception as e:
        logger.error("telemetry_failed", error=str(e))
        # Don't raise - telemetry failures shouldn't break app
```

### JSON Parse Fallback

```python
parsed = LLMService.parse_json(response)
if parsed is None:
    logger.warning("json_parse_failed")
    # Continue with degraded functionality
    return default_value
```

---

## Performance Considerations

### 1. Lazy Telemetry Loading

Avoid circular imports and startup overhead:
```python
_telemetry = None

def _get_telemetry():
    global _telemetry
    if _telemetry is None:
        from .telemetry import get_telemetry
        _telemetry = get_telemetry()
    return _telemetry
```

### 2. Content Truncation

Prevent storage bloat:
```python
max_len = 10000
if len(content) > max_len:
    content = content[:max_len] + "... [truncated]"
```

### 3. Async Context Variables

Zero-overhead context propagation:
```python
# No need to pass session_id through function arguments
telemetry.set_session(session_id)  # Once at top
# All child tasks inherit automatically
```

### 4. Exponential Backoff

Efficient retry without overwhelming API:
```python
wait_time = min(2 ** attempt, 30)  # 1s, 2s, 4s, 8s, 16s, 30s
```

---

## Testing Strategy

### Unit Tests

```python
@pytest.mark.asyncio
async def test_llm_chat():
    config = AIConfig(api_key="test", model="test-model")
    service = LLMService(config)

    # Mock OpenAI client
    service.client = MockAsyncOpenAI()

    messages = [{"role": "user", "content": "test"}]
    response, usage = await service.chat(messages)

    assert response
    assert usage["total"] > 0

def test_json_parsing():
    # Test direct JSON
    assert LLMService.parse_json('{"key": "value"}') == {"key": "value"}

    # Test code block
    assert LLMService.parse_json('```json\n{"key": "value"}\n```') == {"key": "value"}

    # Test extraction
    assert LLMService.parse_json('text {"key": "value"} more text') == {"key": "value"}

    # Test failure
    assert LLMService.parse_json('invalid') is None

def test_telemetry_singleton():
    t1 = AITelemetry.get_instance()
    t2 = AITelemetry.get_instance()
    assert t1 is t2  # Same instance
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_telemetry_integration():
    telemetry = AITelemetry.initialize(
        enabled=True,
        storage_path="/tmp/test_telemetry"
    )

    telemetry.set_session("test_session")

    service = LLMService(config)
    await service.chat([{"role": "user", "content": "test"}])

    # Verify recording
    records = telemetry.query(session_id="test_session")
    assert len(records) > 0
    assert records[0]["session_id"] == "test_session"
```

---

## Extension Points

### 1. Custom LLM Providers

```python
class CustomLLMService(LLMService):
    async def chat(self, messages, **kwargs):
        # Call custom API
        response = await self.custom_api.call(messages)
        return self._format_response(response)
```

### 2. Additional Telemetry Backends

```python
class CloudTelemetry(AITelemetry):
    def record(self, record):
        super().record(record)
        # Also send to cloud
        await self.cloud_client.send(record)
```

### 3. Custom Retry Strategies

```python
class AdaptiveLLMService(LLMService):
    async def _exponential_backoff(self, attempt):
        # Custom backoff based on error type
        if self.last_error_is_rate_limit():
            wait_time = 60  # Wait longer
        else:
            wait_time = 2 ** attempt
        await asyncio.sleep(wait_time)
```

---

## Best Practices

### 1. Always Use Telemetry Context

```python
# Good
telemetry.set_session(session_id)
telemetry.set_agent("MyAgent")
await llm.chat(messages)  # Automatically tracked

# Bad
await llm.chat(messages)  # Missing context
```

### 2. Handle JSON Parse Failures

```python
# Good
data, _ = await llm.chat_json(messages)
if data:
    process(data)
else:
    logger.warning("json_parse_failed")
    use_fallback()

# Bad
data, _ = await llm.chat_json(messages)
process(data)  # May crash if data is None
```

### 3. Set Appropriate Retry Counts

```python
# For critical operations
await llm.chat(messages, retry_count=5)

# For non-critical operations
await llm.chat(messages, retry_count=1)
```

### 4. Clean Up Telemetry Regularly

```python
# In scheduled task
telemetry.cleanup()  # Removes old records based on retention_days
```

---

## Summary

The Services Layer provides robust, production-ready interfaces to external AI services:

**Key Strengths**:
1. **Unified Interface**: Single LLMService for all LLM interactions
2. **Automatic Retry**: Exponential backoff with configurable attempts
3. **Robust Parsing**: Multiple fallback strategies for JSON
4. **Comprehensive Telemetry**: Track every call, analyze costs, debug issues
5. **Context Propagation**: Automatic session/agent tracking via ContextVars
6. **Thread-Safe**: Singleton pattern with proper locking
7. **Non-Blocking**: Telemetry failures don't break main flow

**Production Features**:
- Automatic truncation to prevent storage bloat
- Thread-local connections for concurrency
- Hybrid JSONL+SQLite storage
- Query and export capabilities
- Cost analysis and error tracking

The layer is essential for reliable AI integration and debugging in production environments.
