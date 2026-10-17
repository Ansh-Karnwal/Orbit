import ast
from pathlib import Path


def test_verifier_source_has_no_repository_writes_or_adapters():
    root = Path(__file__).parents[2] / "app/verify"
    forbidden = {"insert_fact", "set_fact_status", "add_evidence", "record_inbound", "set_status", "create_approval_request",
                 "decide_approval", "invalidate_approvals", "save_verification", "emit", "save_action", "save_evidence"}
    for path in root.glob("*.py"):
        source = path.read_text()
        assert not any(name in source for name in forbidden), path
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert "adapters" not in (node.module or "")
                assert "sqlalchemy" not in (node.module or "")
