"""CP0-independent guard for interfaces consumed by all four teammates."""
import ast
from pathlib import Path

import pytest

CONTRACT = [
    ("context/domain.py", "load_pack", False, ["name", "version"], []),
    ("context/facts.py", "ingest_fact", False, ["task_id", "key", "value"], ["source_id", "scope", "currency", "observed_at", "valid_until", "status"]),
    ("context/conflicts.py", "detect_conflicts", False, ["task_id"], []),
    ("context/extract.py", "extract_provider_facts", True, ["task_id", "provider_id", "text", "source_id"], []),
    ("context/compose.py", "compose_inquiry", False, ["task_id", "provider_id"], []),
    ("context/compose.py", "compose_followup", False, ["task_id", "provider_id", "missing_keys"], []),
    ("context/proposals.py", "eligibility", False, ["task_id"], []),
    ("context/proposals.py", "build_proposal", False, ["task_id", "provider_id"], []),
    ("context/proposals.py", "best_proposal", False, ["task_id"], []),
    ("context/proposals.py", "approval_still_valid", False, ["task_id"], []),
    ("context/assembler.py", "assemble", False, ["task_id", "step"], []),
    ("context/summary.py", "summarize", True, ["task_id", "verification"], []),
    ("llm/client.py", "structured", True, ["schema"], ["system", "instructions", "untrusted", "task_id"]),
    ("verify/verifier.py", "verify", True, ["task_id"], []),
]


@pytest.mark.parametrize("path,name,is_async,args,keywords", CONTRACT, ids=[x[1] for x in CONTRACT])
def test_shared_public_signatures(path, name, is_async, args, keywords):
    root = Path(__file__).parents[2] / "app"
    tree = ast.parse((root / path).read_text())
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    assert isinstance(node, ast.AsyncFunctionDef) == is_async
    assert [a.arg for a in node.args.args] == args
    assert [a.arg for a in node.args.kwonlyargs] == keywords
    assert node.args.vararg is None and node.args.kwarg is None
