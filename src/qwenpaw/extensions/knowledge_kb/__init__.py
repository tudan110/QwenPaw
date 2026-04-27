"""knowledge_kb subsystem: serves the operational knowledge base used by the
knowledge specialist agent and the portal "管理知识库" panel.

Public surface:
    router      — FastAPI router mounted at /api/portal/knowledge/*
    startup     — idempotent init (db schema, builtin packs)
    shutdown    — currently a no-op
"""

from .api import router
from .manager import shutdown, startup

__all__ = ["router", "startup", "shutdown"]
