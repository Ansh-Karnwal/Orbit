"""Owner: Victor. Every adapter writes evidence through save_evidence."""
from __future__ import annotations

import hashlib
from pathlib import Path

from app.core import repo
from app.core.config import get_settings
from app.core.schemas import (AdapterName, ClaimLevel, EvidenceArtifact, EvidenceKind, new_id,
                              utcnow)


def save_evidence(task_id: str, kind: EvidenceKind, source: AdapterName, *, is_fixture: bool,
                  data: bytes | None = None, ext: str | None = None, mime_type: str | None = None,
                  extracted: dict | None = None, claim_level: ClaimLevel | None = None,
                  provider_ref: str | None = None) -> EvidenceArtifact:
    ev_id = new_id("evd")
    uri = sha = None
    if data is not None:
        rel = Path(task_id) / f"{ev_id}.{(ext or 'bin').lstrip('.')}"
        path = Path(get_settings().artifact_dir) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        uri, sha = rel.as_posix(), hashlib.sha256(data).hexdigest()
    ev = EvidenceArtifact(
        id=ev_id, task_id=task_id, kind=kind, source=source, uri=uri, mime_type=mime_type,
        sha256=sha, extracted=extracted or {}, claim_level=claim_level, is_fixture=is_fixture,
        provider_ref=provider_ref, captured_at=utcnow(),
    )
    return repo.add_evidence(ev)
