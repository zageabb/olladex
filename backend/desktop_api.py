import os

import uvicorn

from backend.app.main import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("OLLADEX_API_PORT", "8001")),
        log_level="info",
    )
