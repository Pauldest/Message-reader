# Agents package - Multi-Agent News Analysis System

from .base import BaseAgent
from .orchestrator import AnalysisOrchestrator
from .collector import CollectorAgent
from .librarian import LibrarianAgent
from .editor import EditorAgent
from .curator import CuratorAgent
from .analysts import SkepticAnalyst, EconomistAnalyst, DetectiveAnalyst
from .trace_manager import TraceManager

__all__ = [
    "BaseAgent",
    "AnalysisOrchestrator",
    "CollectorAgent",
    "LibrarianAgent",
    "EditorAgent",
    "CuratorAgent",
    "SkepticAnalyst",
    "EconomistAnalyst",
    "DetectiveAnalyst",
    "TraceManager",
]
