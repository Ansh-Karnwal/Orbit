from app.core import repo
from app.context.domain import load_pack, service_def
from app.context.values import local_window, money

QUESTIONS = {
    "service_supported": "can you repair this appliance?",
    "visit_charge_cents": "total diagnostic visit charge including all travel/trip fees?",
    "base_charge_cents": "base visit charge before extra fees?",
    "extra_fees": "any mandatory extra fees?",
    "fee_scope": "what does the visit charge cover?",
    "slots_offered": "available appointment slots within {window}?",
    "portal_slots": "which offered slots can be booked within {window}?",
    "cancellation_terms": "cancellation notice and charges?",
    "repair_cost_known": "are parts and labor quoted after diagnosis?",
    "no_reply": "are you available for this repair within {window}?",
}


def compose_inquiry(task_id: str, provider_id: str) -> str:
    task = repo.get_task(task_id)
    provider = repo.get_provider(task_id, provider_id)
    service = service_def(task.constraints.service)
    noun = (service.synonyms[0] if service else
            task.constraints.service.replace("_repair", "").replace("_", " "))
    text = load_pack().message_templates["inquiry"].format(
        provider_name=provider.name[:50], service=noun[:50],
        window=local_window(task.constraints), budget=money(task.constraints.max_visit_charge_cents))
    if len(text) > 480:
        raise ValueError("Inquiry exceeds 480 characters")
    return text


def compose_followup(task_id: str, provider_id: str, missing_keys: list[str]) -> str:
    task = repo.get_task(task_id)
    provider = repo.get_provider(task_id, provider_id)
    fields = list(dict.fromkeys(k.rsplit(".", 1)[-1] for k in missing_keys))
    if any(k not in QUESTIONS for k in fields):
        raise ValueError("Unknown follow-up fact key")
    if not fields:
        return ""
    questions = " ".join(QUESTIONS[k].format(window=local_window(task.constraints)) for k in fields)
    return load_pack().message_templates["followup"].format(provider_name=provider.name[:50], questions=questions)
