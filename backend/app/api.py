from __future__ import annotations

from .github_review_routes import router as github_review_router
from .main import app
from .orchestration_routes import router as orchestration_router
from .task_routes import router as task_router


app.include_router(task_router)
app.include_router(github_review_router)
app.include_router(orchestration_router)
