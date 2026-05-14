"""Flask control plane for the CVM ingestion pipeline.

Local-only HTTP wrapper around `src.pipeline.cvm_pipeline.CVMIngestor` that
exposes each ingest method as a background job, so partial fills can be
triggered and monitored one (entity, doc_type, year, month) slice at a time.

See docs/AGENT_GUIDE.md for the operator workflow.
"""

from __future__ import annotations

import logging
import os

from flask import Flask

from src.api.routes import bp


def create_app() -> Flask:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = Flask(__name__)
    app.register_blueprint(bp)
    return app


__all__ = ["create_app"]
