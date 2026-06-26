"""Agent definitions and JSON persistence."""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent / "data"
AGENTS_FILE = DATA_DIR / "agents.json"

DEFAULT_AGENTS: list[dict[str, Any]] = [
    {
        "id": "proposer",
        "name": "Proposer",
        "role": "Drafts clear, well-reasoned answers",
        "system_message": (
            "You are the Proposer. Draft clear, well-reasoned answers to the "
            "user's question. Revise your position when other agents surface valid "
            "concerns. Stay concise and concrete."
        ),
        "temperature": 0.7,
        "color": "#2563eb",
        "builtin": True,
    },
    {
        "id": "critic",
        "name": "Critic",
        "role": "Reviews reasoning and identifies gaps",
        "system_message": (
            "You are the Critic. Review the Proposer's drafts for logical gaps, "
            "missing context, unstated assumptions, and weak reasoning. Be constructive "
            "and specific."
        ),
        "temperature": 0.7,
        "color": "#d97706",
        "builtin": True,
    },
    {
        "id": "devils_advocate",
        "name": "Devil's Advocate",
        "role": "Argues the opposing position",
        "system_message": (
            "You are the Devil's Advocate. Argue the strongest opposing position to "
            "the current consensus. Steelman the counter-argument: name concrete risks, "
            "failure modes, and scenarios where the prevailing recommendation would be "
            "wrong. Do not agree with the majority view by default."
        ),
        "temperature": 0.8,
        "color": "#dc2626",
        "builtin": True,
    },
    {
        "id": "domain_expert",
        "name": "Domain Expert",
        "role": "Grounds claims in real-world constraints",
        "system_message": (
            "You are the Domain Expert. Ground the discussion in real-world constraints "
            "relevant to the topic: practical limits, costs, timelines, stakeholder "
            "impacts, feasibility, and evidence from how things work in practice. Call "
            "out claims that ignore operational or domain realities."
        ),
        "temperature": 0.6,
        "color": "#059669",
        "builtin": True,
    },
    {
        "id": "judge",
        "name": "Judge",
        "role": "Delivers the final structured verdict",
        "system_message": (
            "You are the Judge. Produce a final structured verdict with these sections:\n\n"
            "## Summary\n"
            "## Key tradeoffs\n"
            "## Recommendation\n"
            "## Conditions (when this recommendation would change)\n"
            "## Confidence (High / Medium / Low, with one sentence why)\n\n"
            "Weigh all prior agent inputs evenhandedly. Be decisive. "
            "End with TERMINATE on its own line."
        ),
        "temperature": 0.5,
        "color": "#7c3aed",
        "builtin": True,
    },
]

MODERATOR_AGENT_ID = "moderator"
MODERATOR_PROMPT_PATH = Path(__file__).parent / "moderator_system_prompt.md"


def load_moderator_system_prompt() -> str:
    if MODERATOR_PROMPT_PATH.exists():
        return MODERATOR_PROMPT_PATH.read_text(encoding="utf-8").strip()
    return (
        "You are a neutral conversation moderator. Use RED LIGHT interventions every 10 messages "
        "to re-anchor on the original question. Use GREEN LIGHT interventions at scheduled counts "
        "to check consensus readiness. Stay brief — 2-3 sentences max."
    )


MODERATOR_AGENT: dict[str, Any] = {
    "id": MODERATOR_AGENT_ID,
    "name": "Moderator",
    "role": "Keeps discussion on track",
    "system_message": load_moderator_system_prompt(),
    "temperature": 0.3,
    "color": "#78716c",
    "builtin": True,
    "selectable": False,
    "is_system_agent": True,
    "beta_only": True,
}

NON_PARTICIPANT_AGENT_IDS = frozenset({"judge", MODERATOR_AGENT_ID})


def get_openai_api_key() -> str:
    """Return the OpenAI API key from the environment (no hardcoded fallback)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not api_key.strip():
        raise RuntimeError("Set OPENAI_API_KEY before running.")
    return api_key.strip()


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_agents() -> list[dict[str, Any]]:
    _ensure_data_dir()
    if not AGENTS_FILE.exists():
        save_agents(deepcopy(DEFAULT_AGENTS))
        return deepcopy(DEFAULT_AGENTS)
    with AGENTS_FILE.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_library_agents() -> list[dict[str, Any]]:
    """Participant agents plus system agents shown in the library UI."""
    return [*load_agents(), deepcopy(MODERATOR_AGENT)]


def save_agents(agents: list[dict[str, Any]]) -> None:
    _ensure_data_dir()
    with AGENTS_FILE.open("w", encoding="utf-8") as fh:
        json.dump(agents, fh, indent=2)


def get_agent(agent_id: str) -> dict[str, Any] | None:
    for agent in load_agents():
        if agent["id"] == agent_id:
            return agent
    return None


def create_agent(payload: dict[str, Any]) -> dict[str, Any]:
    agents = load_agents()
    agent = {
        "id": str(uuid.uuid4()),
        "name": payload["name"].strip(),
        "role": payload.get("role", "").strip(),
        "system_message": payload["system_message"].strip(),
        "temperature": float(payload.get("temperature", 0.7)),
        "color": payload.get("color") or "#64748b",
        "builtin": False,
    }
    agents.append(agent)
    save_agents(agents)
    return agent


def update_agent(agent_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    if agent_id in NON_PARTICIPANT_AGENT_IDS:
        return None
    agents = load_agents()
    for idx, agent in enumerate(agents):
        if agent["id"] != agent_id:
            continue
        agent = {
            **agent,
            "name": payload.get("name", agent["name"]).strip(),
            "role": payload.get("role", agent["role"]).strip(),
            "system_message": payload.get("system_message", agent["system_message"]).strip(),
            "temperature": float(payload.get("temperature", agent["temperature"])),
            "color": payload.get("color", agent.get("color", "#64748b")),
        }
        agents[idx] = agent
        save_agents(agents)
        return agent
    return None


def delete_agent(agent_id: str) -> bool:
    if agent_id in NON_PARTICIPANT_AGENT_IDS:
        return False
    agents = load_agents()
    target = next((a for a in agents if a["id"] == agent_id), None)
    if not target or target.get("builtin"):
        return False
    agents = [a for a in agents if a["id"] != agent_id]
    save_agents(agents)
    return True


def autogen_name(agent: dict[str, Any]) -> str:
    """Stable AutoGen agent name from library id."""
    return agent["id"].replace("-", "_")
