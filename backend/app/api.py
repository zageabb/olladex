from __future__ import annotations

from .main import app
from .task_routes import router as task_router


app.include_router(task_router)
