from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_env_file_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_local_env_file(path: Path | None = None, *, override: bool = False) -> list[str]:
    """Load gitignored local runtime config without exposing secret values."""
    env_path = path or PROJECT_ROOT / ".env.local"
    if not env_path.is_file():
        return []
    loaded: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if key in os.environ and not override:
            continue
        os.environ[key] = parse_env_file_value(raw_value)
        loaded.append(key)
    return loaded


def configure_v20_test_routes() -> None:
    """Bind the opt-in v20 test endpoint to the two Phase 0 model routes.

    The test credentials are deliberately separate from the child's runtime
    ``OPENAI_*`` route. This helper only maps already-loaded local values and
    never prints or persists secrets.
    """
    api_key = os.environ.get("V20_TEST_API_KEY", "").strip()
    base_url = os.environ.get("V20_TEST_BASE_URL", "").strip()
    model = os.environ.get("V20_TEST_MODEL", "").strip()
    if not api_key or not base_url:
        return
    for prefix in (
        "AI_SLOT_BRIEF_DESIGNER_AGENT_SLOT_BRIEF_GENERATION",
        "AI_SLOT_BRIEF_REVIEWER_AGENT_SLOT_BRIEF_REVIEW",
    ):
        os.environ.setdefault(f"{prefix}_API_KEY", api_key)
        os.environ.setdefault(f"{prefix}_BASE_URL", base_url)
        if model:
            os.environ.setdefault(f"{prefix}_MODEL", model)


def configure_v20_concrete_test_routes() -> None:
    """Bind concrete-question pilot routes to the opt-in v20 test endpoint."""
    api_key = os.environ.get("V20_TEST_API_KEY", "").strip()
    base_url = os.environ.get("V20_TEST_BASE_URL", "").strip()
    model = os.environ.get("V20_TEST_MODEL", "").strip()
    if not api_key or not base_url:
        return
    prefixes = [
        "AI_QUESTION_DESIGNER_AGENT_QUESTION_CANDIDATE",
        "AI_QUESTION_REVIEWER_AGENT_QUESTION_REVIEW",
    ]
    prefixes.extend(
        f"AI_QUESTION_REVIEWER_AGENT_QUESTION_REVIEW_{stage}"
        for stage in ("TARGETED", "MATH_EDUCATION", "ASSESSMENT", "CHILD_LEARNING", "COLLISION")
    )
    for prefix in prefixes:
        os.environ[f"{prefix}_API_KEY"] = api_key
        os.environ[f"{prefix}_BASE_URL"] = base_url
        if model:
            os.environ[f"{prefix}_MODEL"] = model
