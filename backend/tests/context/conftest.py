from .fakes import memory_repo  # noqa: F401


def pytest_configure(config):
    config.addinivalue_line("markers", "live_llm: explicitly opt-in Anthropic API tests")
