"""Owner: Ansh. Mock provider booking portal on :8100 — `uvicorn main:app --port 8100`.

Logic lives in portal_core.py (a unique module name so backend tests can import it in-process).
"""
from portal_core import create_app

app = create_app()
