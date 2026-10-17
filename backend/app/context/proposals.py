from app.core import repo
from app.core.schemas import Proposal
from app.context.decisions import approval_validity, eligibility_for, proposal_for


def eligibility(task_id: str) -> dict[str, list[str]]:
    return eligibility_for(repo.get_task(task_id), repo.get_providers(task_id), repo.list_facts(task_id))


def build_proposal(task_id: str, provider_id: str) -> Proposal | None:
    return proposal_for(repo.get_task(task_id), repo.get_provider(task_id, provider_id), repo.list_facts(task_id), repo.get_providers(task_id))


def best_proposal(task_id: str) -> Proposal | None:
    task, providers, facts = repo.get_task(task_id), repo.get_providers(task_id), repo.list_facts(task_id)
    options = [proposal_for(task, p, facts, providers) for p in providers]
    return min((p for p in options if p is not None),
               key=lambda p: (p.visit_charge_cents, p.slot_start, p.provider_id), default=None)


def approval_still_valid(task_id: str) -> tuple[bool, str]:
    return approval_validity(repo.get_task(task_id), repo.get_providers(task_id), repo.list_facts(task_id), repo.get_latest_approval(task_id))
