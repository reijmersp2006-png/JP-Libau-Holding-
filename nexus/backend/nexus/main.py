"""Start de API: ``nexus-api`` (of ``uvicorn nexus.main:app``)."""

from __future__ import annotations

import json
import logging
import os

import uvicorn

from nexus.app import create_app


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"ts": self.formatTime(record), "level": record.levelname, "logger": record.name,
                           "msg": record.getMessage()}, ensure_ascii=False)


def _logging() -> None:
    h = logging.StreamHandler()
    h.setFormatter(JsonFormatter())
    logging.basicConfig(level=os.environ.get("NEXUS_LOG_LEVEL", "INFO"), handlers=[h], force=True)


_logging()
app = create_app()


def run() -> None:
    uvicorn.run("nexus.main:app", host=os.environ.get("NEXUS_HOST", "127.0.0.1"),
                port=int(os.environ.get("NEXUS_PORT", "8000")))
