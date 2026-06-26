"""Shared AutoGen five-agent debate logic for CLI and web."""

from __future__ import annotations

import os
import sys
import threading
from typing import TYPE_CHECKING, Callable, Optional

from autogen import AssistantAgent, GroupChat, GroupChatManager, UserProxyAgent

if TYPE_CHECKING:
    from autogen import Agent

MAX_DEBATE_ROUNDS = 2

AGENT_ROLES = {
    "Proposer": "Drafts clear, well-reasoned answers",
    "Critic": "Reviews reasoning and identifies gaps",
    "Devils_Advocate": "Argues the opposing position",
    "Domain_Expert": "Grounds claims in real-world constraints",
    "Judge": "Delivers the final structured verdict",
    "Human": "Approves or steers the debate",
}

AGENT_DISPLAY_NAMES = {
    "Devils_Advocate": "Devil's Advocate",
}

PROPOSER_SYSTEM = """You are the Proposer. Draft clear, well-reasoned answers to the
user's question. Revise your position when the Critic, Devil's Advocate, or
Domain_Expert surface valid concerns. Stay concise and concrete."""

CRITIC_SYSTEM = """You are the Critic. Review the Proposer's drafts for logical gaps,
missing context, unstated assumptions, and weak reasoning. Be constructive and specific."""

DEVIL_ADVOCATE_SYSTEM = """You are the Devil's Advocate. Argue the strongest opposing
position to the Proposer's current answer. Steelman the counter-argument: name concrete
risks, failure modes, and scenarios where the Proposer's recommendation would be wrong.
Do not agree with the majority view by default."""

DOMAIN_EXPERT_SYSTEM = """You are the Domain_Expert. Ground the discussion in real-world
constraints relevant to the topic: practical limits, costs, timelines, stakeholder
impacts, feasibility, and evidence from how things work in practice. Call out claims
that ignore operational or domain realities."""

JUDGE_SYSTEM = """You are the Judge. You speak only once, after all other agents have
had their turns. Produce a final structured verdict with these sections:

## Summary
## Key tradeoffs
## Recommendation
## Conditions (when this recommendation would change)
## Confidence (High / Medium / Low, with one sentence why)

Weigh the Proposer, Critic, Devil's Advocate, and Domain_Expert inputs evenhandedly.
Be decisive. End with TERMINATE on its own line."""


def display_name(agent_name: str) -> str:
    return AGENT_DISPLAY_NAMES.get(agent_name, agent_name.replace("_", " "))


def build_llm_config() -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY before running.")

    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return {
        "config_list": [{"model": model, "api_key": api_key}],
        "temperature": 0.7,
    }


def make_speaker_selector(
    proposer: Agent,
    human: Agent,
    critic: Agent,
    devils_advocate: Agent,
    domain_expert: Agent,
    judge: Agent,
) -> Callable[[Agent, GroupChat], Optional[Agent]]:
    """Run debate rounds across all five agents, then the Judge exactly once."""
    debate_turn = [
        proposer,
        human,
        critic,
        human,
        devils_advocate,
        human,
        domain_expert,
        human,
    ]
    finale = [judge, human]
    speaking_order = debate_turn * MAX_DEBATE_ROUNDS + finale

    step = [0]

    def select_speaker(last_speaker: Agent, groupchat: GroupChat) -> Optional[Agent]:
        idx = step[0]
        if idx >= len(speaking_order):
            return None
        next_speaker = speaking_order[idx]
        step[0] += 1
        return next_speaker

    return select_speaker


class DebateSession:
    """Runs a debate in a background thread; exposes state for the web UI."""

    def __init__(self, session_id: str, question: str):
        self.session_id = session_id
        self.question = question
        self.lock = threading.Lock()
        self.status = "starting"
        self.error: Optional[str] = None
        self.human_prompt = ""
        self.messages: list[dict] = []
        self.groupchat: Optional[GroupChat] = None
        self.human_agent: Optional[WebHumanProxy] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_waiting_for_human(self, prompt: str) -> None:
        with self.lock:
            self.status = "waiting_human"
            self.human_prompt = prompt
            self.sync_messages()

    def set_running(self) -> None:
        with self.lock:
            self.status = "running"
            self.human_prompt = ""

    def sync_messages(self) -> None:
        if not self.groupchat:
            return
        self.messages = format_messages(self.groupchat.messages)

    def to_dict(self) -> dict:
        with self.lock:
            self.sync_messages()
            return {
                "session_id": self.session_id,
                "question": self.question,
                "messages": list(self.messages),
                "status": self.status,
                "error": self.error,
                "human_prompt": self.human_prompt,
            }

    def _run(self) -> None:
        try:
            llm_config = build_llm_config()
            human = WebHumanProxy(
                session=self,
                name="Human",
                human_input_mode="ALWAYS",
                max_consecutive_auto_reply=0,
                code_execution_config=False,
                is_termination_msg=lambda msg: "TERMINATE" in (msg.get("content") or ""),
            )

            proposer = AssistantAgent(
                name="Proposer",
                system_message=PROPOSER_SYSTEM,
                llm_config=llm_config,
            )
            critic = AssistantAgent(
                name="Critic",
                system_message=CRITIC_SYSTEM,
                llm_config=llm_config,
            )
            devils_advocate = AssistantAgent(
                name="Devils_Advocate",
                system_message=DEVIL_ADVOCATE_SYSTEM,
                llm_config=llm_config,
            )
            domain_expert = AssistantAgent(
                name="Domain_Expert",
                system_message=DOMAIN_EXPERT_SYSTEM,
                llm_config=llm_config,
            )
            judge = AssistantAgent(
                name="Judge",
                system_message=JUDGE_SYSTEM,
                llm_config=llm_config,
            )

            groupchat = GroupChat(
                agents=[proposer, critic, devils_advocate, domain_expert, judge, human],
                messages=[],
                max_round=MAX_DEBATE_ROUNDS * 8 + 4,
                speaker_selection_method=make_speaker_selector(
                    proposer,
                    human,
                    critic,
                    devils_advocate,
                    domain_expert,
                    judge,
                ),
            )
            manager = GroupChatManager(groupchat=groupchat, llm_config=llm_config)

            self.groupchat = groupchat
            self.human_agent = human

            with self.lock:
                self.status = "running"

            human.initiate_chat(
                manager,
                message=(
                    f"Question for debate:\n\n{self.question}\n\n"
                    "Proposer: please draft an initial answer."
                ),
            )

            with self.lock:
                self.status = "complete"
                self.sync_messages()
        except Exception as exc:
            with self.lock:
                self.status = "error"
                self.error = str(exc)


class WebHumanProxy(UserProxyAgent):
    """UserProxyAgent that waits for browser input instead of terminal input."""

    def __init__(self, session: DebateSession, **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self._feedback_event = threading.Event()
        self._pending_feedback = ""

    def get_human_input(self, prompt: str) -> str:
        self.session.set_waiting_for_human(prompt)
        self._feedback_event.wait()
        self._feedback_event.clear()
        feedback = self._pending_feedback
        self._pending_feedback = ""
        self.session.set_running()
        return feedback

    def submit_feedback(self, feedback: str) -> None:
        self._pending_feedback = feedback
        self._feedback_event.set()


def format_messages(raw_messages: list[dict]) -> list[dict]:
    formatted = []
    for msg in raw_messages:
        name = msg.get("name") or "Unknown"
        content = msg.get("content") or ""
        if not content.strip():
            continue
        formatted.append(
            {
                "name": display_name(name),
                "agent_key": name,
                "role": AGENT_ROLES.get(name, ""),
                "content": content,
            }
        )
    return formatted


def create_debate_agents(llm_config: dict) -> tuple[UserProxyAgent, GroupChatManager, GroupChat]:
    """Create agents for CLI use with terminal human input."""
    human = UserProxyAgent(
        name="Human",
        human_input_mode="ALWAYS",
        max_consecutive_auto_reply=0,
        code_execution_config=False,
        is_termination_msg=lambda msg: "TERMINATE" in (msg.get("content") or ""),
    )

    proposer = AssistantAgent(
        name="Proposer",
        system_message=PROPOSER_SYSTEM,
        llm_config=llm_config,
    )
    critic = AssistantAgent(
        name="Critic",
        system_message=CRITIC_SYSTEM,
        llm_config=llm_config,
    )
    devils_advocate = AssistantAgent(
        name="Devils_Advocate",
        system_message=DEVIL_ADVOCATE_SYSTEM,
        llm_config=llm_config,
    )
    domain_expert = AssistantAgent(
        name="Domain_Expert",
        system_message=DOMAIN_EXPERT_SYSTEM,
        llm_config=llm_config,
    )
    judge = AssistantAgent(
        name="Judge",
        system_message=JUDGE_SYSTEM,
        llm_config=llm_config,
    )

    groupchat = GroupChat(
        agents=[proposer, critic, devils_advocate, domain_expert, judge, human],
        messages=[],
        max_round=MAX_DEBATE_ROUNDS * 8 + 4,
        speaker_selection_method=make_speaker_selector(
            proposer,
            human,
            critic,
            devils_advocate,
            domain_expert,
            judge,
        ),
    )
    manager = GroupChatManager(groupchat=groupchat, llm_config=llm_config)
    return human, manager, groupchat
