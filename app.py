"""Flask entry point for the CVM pipeline control plane.

Run locally:
    flask --app app run                 # defaults to 127.0.0.1:5000
    python app.py                       # same, via __main__ block

This is intentionally a 3-line module — all behavior lives in `src.api`.
See README.md "Flask control plane" for endpoint reference.
"""

from src.api import create_app

app = create_app()


if __name__ == "__main__":
    import os
    app.run(
        host=os.getenv("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_RUN_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "0") == "1",
    )
