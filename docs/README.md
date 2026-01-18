# Message-Reader Design Documentation

Comprehensive design documents for all modules of the Message-reader project.

## Complete Documentation

1. **[Agents Design](modules/agents-design.md)** - Multi-Agent System (Core Intelligence)
2. **[Storage Layer Design](design/storage-design.md)** - Database, Vector Store, Information Store, Entity Store, Telemetry Store
3. **[Services Layer Design](design/services-design.md)** - LLM Service, Telemetry Service
4. **[Models Design](design/models-design.md)** - Article, InformationUnit, Entity, Agent Models
5. **[Fetcher Design](design/fetcher-design.md)** - RSS Parser, Content Extractor
6. **[Notifier Design](design/notifier-design.md)** - Email Sender System
7. **[Web UI Design](design/web-design.md)** - FastAPI Server, WebSocket, Progress Tracker
8. **[AI Module Design](design/ai-design.md)** - Legacy AI Analyzer (Article-Centric)
9. **[Visualization Design](design/visualization-design.md)** - Knowledge Graph Visualization
10. **[Core Design](design/core-design.md)** - Config, Feeds, Scheduler, Main Entry Point

## Quick Reference

- **Total Modules**: 8
- **Total Files**: ~50 Python files
- **Total Lines**: ~10,000+ lines of code
- **Architecture**: Multi-Agent + Event-Driven + Layered

## Document Status

- ✅ **agents-design.md** - Complete (996 lines) - Multi-Agent Intelligence System
- ✅ **storage-design.md** - Complete (1,130 lines) - Data Persistence Layer
- ✅ **services-design.md** - Complete (1,312 lines) - LLM & Telemetry Services
- ✅ **models-design.md** - Complete (992 lines) - Data Models & Schemas
- ✅ **fetcher-design.md** - Complete (900 lines) - RSS & Content Extraction
- ✅ **notifier-design.md** - Complete (854 lines) - Email Notification System
- ✅ **web-design.md** - Complete (1,200+ lines) - Web UI & Real-time Communication
- ✅ **ai-design.md** - Complete (800+ lines) - Legacy AI Analysis Module
- ✅ **visualization-design.md** - Complete (650+ lines) - Knowledge Graph Visualization
- ✅ **core-design.md** - Complete (1,100+ lines) - Core Infrastructure

**Total Lines**: ~10,000+ lines of comprehensive design documentation

---

## Documentation Overview

All design documents follow a comprehensive structure including:
- ✅ Complete module overview with file structure
- ✅ Detailed architecture diagrams
- ✅ All key components with code examples
- ✅ Complete API documentation with usage examples
- ✅ Data flow diagrams
- ✅ Design patterns identification
- ✅ Error handling strategies
- ✅ Performance considerations
- ✅ Testing strategies
- ✅ Extension points
- ✅ Best practices

## Quick Navigation by Function

**Data Processing**:
- Agents (Intelligence) → Models (Data Structures) → Storage (Persistence)

**Content Acquisition**:
- Fetcher (RSS) → Models (Articles) → Storage (Database)

**User Interface**:
- Web UI (FastAPI) → Progress Tracker → Socket Manager

**Services & Utilities**:
- Services (LLM/Telemetry) → AI Module (Legacy) → Visualization

**Infrastructure**:
- Core (Config/Scheduler/Main) → All Modules
