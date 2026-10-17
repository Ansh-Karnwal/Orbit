"""Owner: Ansh. Stub from CP0 — replace. Mock provider booking portal (FastAPI + Jinja) on :8100."""
from fastapi import FastAPI

app = FastAPI(title="Orbit mock provider portal")


@app.get("/")
def index() -> dict:
    return {"ok": True, "portal": "stub"}


@app.post("/admin/reset")
def admin_reset() -> dict:
    return {"ok": True}


@app.post("/admin/fault")
def admin_fault(body: dict) -> dict:
    return {"mode": body.get("mode", "none")}
