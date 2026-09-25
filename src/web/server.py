"""Run the dashboard API inside the same process as the Telegram bot."""
from __future__ import annotations

import os
import uvicorn


def build_server() -> uvicorn.Server:
    port = int(os.getenv("PORT", "8000"))
    config = uvicorn.Config(
        "src.web.api:app",
        host="0.0.0.0",
        port=port,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        access_log=False,
        reload=False,
    )
    return uvicorn.Server(config)
