"""Configurable multi-agent debate engine powered by AutoGen."""

from __future__ import annotations

import os
import threading
import traceback
from typing import Any, Callable, Optional

from autogen import AssistantAgent, GroupChat, GroupChatManager, UserProxyAgent
from autogen.oai.client import OpenAIWrapper

from agents import (
    MODERATOR_AGENT,
    MODERATOR_AGENT_ID,
    autogen_name,
    get_agent,
    get_openai_api_key,
    load_agents,
)


def build_llm_config(temperature: float = 0.7) -> dict:
    api_key = get_openai_api_key()
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    return {
        "config_list": [{"model": model, "api_key": api_key}],
        "temperature": temperature,
    }


CONVERSATION_BREVITY_SUFFIX = (
    "\n\nKeep your responses short — 2-4 sentences. React directly to what was just said. "
    "If you have more to add, stop anyway — the manager will give you another turn if needed."
)

CONVERSATION_JUDGE_SUFFIX = (
    "\n\nKeep your final verdict concise — short sections, no more than 1-2 sentences each."
)

CONVERSATION_SPEAKER_PROMPT = (
    "Read the above conversation carefully. Then select the next role from {agentlist} to play. "
    "Consider what was just said: should the current speaker continue (if they were mid-thought "
    "or the topic still belongs to them), or should a different agent respond? "
    "Pick based on relevance to the latest message, not turn order. Only return the role."
)

CONVERSATION_SOFT_CAP = 30
CONVERSATION_MAX_ROUNDS = 500

MODERATOR_CONSENSUS_MESSAGE = (
    "It seems we may be reaching a point where we can assess our progress. "
    "Does everyone agree we've sufficiently addressed the original question? "
    "Please respond with yes or no and a brief reason."
)

MODERATOR_ESCALATION_MESSAGE = (
    "We've built significant depth and checked consensus multiple times. "
    "The disagreement seems structural — you have differing views on how to weight and prioritize factors. "
    "This is legitimate.\n\n"
    "We can:\n"
    "1. Continue refining (keep going)\n"
    "2. Proceed to Judge verdict now with the analysis we have\n\n"
    "What's your preference?"
)

CONVERSATION_VOTE_SUFFIX = (
    "\n\nWhen the Moderator asks for a consensus vote, put Yes or No on the first line, "
    "then one brief sentence explaining why."
)


def _is_red_light_trigger(message_count: int) -> bool:
    return message_count > 0 and message_count % 10 == 0


def _is_green_light_trigger(message_count: int) -> bool:
    if message_count < 30:
        return False
    if message_count in (30, 50):
        return True
    if 60 <= message_count <= 90 and message_count % 10 == 0:
        return True
    return message_count >= 100 and message_count % 10 == 0


class WebHumanProxy(UserProxyAgent):
    """Blocks on browser input while preserving human_input_mode='ALWAYS'."""

    def __init__(self, session: "ConfigurableDebateSession", **kwargs):
        super().__init__(**kwargs)
        self.session = session
        self._feedback_event = threading.Event()
        self._pending_feedback = ""

    def get_human_input(self, prompt: str) -> str:
        self.session._set_waiting_human(prompt)
        self._feedback_event.wait()
        self._feedback_event.clear()
        feedback = self._pending_feedback
        self._pending_feedback = ""
        self.session._set_running()
        if self.session._in_finale and self.session._agent_has_non_empty_message(
            self.session.judge_agent
        ):
            self.session._finale_human_complete = True
        return feedback

    def submit_feedback(self, feedback: str) -> None:
        self._pending_feedback = feedback
        self._feedback_event.set()


class ConfigurableDebateSession:
    def __init__(self, session_id: str, config: dict[str, Any]):
        self.session_id = session_id
        self.config = config
        self.question = config["question"]
        self.style = config.get("style", "debate")
        self.mode = config["mode"]
        self.human_gate = config["human_gate"]
        self.rounds = int(config["rounds"])
        self.participant_ids: list[str] = config["participant_ids"]
        self.turn_order: list[str] = config.get("turn_order") or list(self.participant_ids)
        self.judge_id: str = config.get("judge_id") or "judge"

        self.lock = threading.Lock()
        self.status = "starting"
        self.error: Optional[str] = None
        self.human_prompt = ""
        self.messages: list[dict] = []
        self.available_speakers: list[dict] = []

        self.groupchat: Optional[GroupChat] = None
        self.manager: Optional[GroupChatManager] = None
        self.human_agent: Optional[WebHumanProxy] = None
        self.agents_by_id: dict[str, AssistantAgent] = {}
        self.agent_meta: dict[str, dict] = {}
        self.judge_agent: Optional[AssistantAgent] = None
        self.judge_library_id: Optional[str] = None

        self._thread: Optional[threading.Thread] = None
        self._manual_event = threading.Event()
        self._pending_pick_id: Optional[str] = None
        self._force_judge = False
        self._sequential_order: list[Any] = []
        self._sequential_step = [0]
        self._in_finale = False
        self._finale_complete = False
        self._finale_human_complete = False
        self._verdict_prompt_dismissed = False
        self.moderator_agent: Optional[AssistantAgent] = None
        self._consensus_phase: Optional[str] = None
        self._voting_queue: list[Any] = []
        self._voting_index = 0
        self._votes: dict[str, bool] = {}
        self._consensus_resume_after = 0
        self._triggered_counts: set[int] = set()
        self._moderator_next_message = ""
        self._moderator_intervention: Optional[str] = None
        self._pending_green_after_red = False
        self._green_vote_history: list[dict[str, bool]] = []
        self._escalation_prompt_dismissed = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def to_dict(self) -> dict[str, Any]:
        with self.lock:
            self._sync_messages()
            return {
                "session_id": self.session_id,
                "question": self.question,
                "messages": list(self.messages),
                "status": self.status,
                "error": self.error,
                "human_prompt": self.human_prompt,
                "style": self.style,
                "mode": self.mode,
                "human_gate": self.human_gate,
                "available_speakers": list(self.available_speakers),
                "participant_ids": self.participant_ids,
                "conversation_agent_messages": self._conversation_agent_message_count(),
                "show_verdict_prompt": self._show_verdict_prompt(),
                "show_escalation_prompt": self._show_escalation_prompt(),
            }

    def dismiss_verdict_prompt(self) -> None:
        with self.lock:
            self._verdict_prompt_dismissed = True

    def dismiss_escalation_prompt(self) -> None:
        with self.lock:
            self._escalation_prompt_dismissed = True

    def _conversation_agent_message_count(self) -> int:
        if self.style not in ("conversation", "conversation_beta"):
            return 0
        return self._debate_turn_count()

    def _conversation_debater_message_count(self) -> int:
        return self._conversation_agent_message_count()

    def _show_verdict_prompt(self) -> bool:
        if self.style != "conversation":
            return False
        if self._verdict_prompt_dismissed or self._in_finale or self._finale_complete:
            return False
        if self.status in ("complete", "error", "starting"):
            return False
        return self._conversation_agent_message_count() >= CONVERSATION_SOFT_CAP

    def _show_escalation_prompt(self) -> bool:
        if self.style != "conversation_beta":
            return False
        if self._escalation_prompt_dismissed or self._in_finale or self._finale_complete:
            return False
        if self.status in ("complete", "error", "starting"):
            return False
        return self._should_escalate_consensus()

    def submit_feedback(self, feedback: str) -> None:
        if self.human_agent:
            self.human_agent.submit_feedback(feedback)

    def pick_speaker(self, agent_id: str) -> None:
        with self.lock:
            self._pending_pick_id = agent_id
        self._manual_event.set()

    def end_debate(self) -> None:
        """Skip remaining rounds and route to the Judge on the next turn."""
        with self.lock:
            self._force_judge = True
        if self.status == "waiting_human" and self.human_agent:
            self.human_agent.submit_feedback("")
        elif self.status == "waiting_manual_pick":
            with self.lock:
                self._pending_pick_id = self.judge_library_id
            self._manual_event.set()

    def _termination_check(self, msg: dict) -> bool:
        if "TERMINATE" not in (msg.get("content") or ""):
            return False
        if (
            self.human_gate
            and self._in_finale
            and self.judge_agent
            and self._agent_has_non_empty_message(self.judge_agent)
            and not self._finale_human_complete
        ):
            return False
        return True

    def _debater_autogen_names(self) -> set[str]:
        names: set[str] = set()
        for lib_id in self.participant_ids:
            if lib_id == self.judge_library_id:
                continue
            meta = self.agent_meta.get(lib_id)
            if meta:
                names.add(autogen_name(meta))
        return names

    def _debate_turn_count(self) -> int:
        if not self.groupchat:
            return 0
        debaters = self._debater_autogen_names()
        return sum(
            1
            for msg in self.groupchat.messages
            if msg.get("name") in debaters and (msg.get("content") or "").strip()
        )

    def _debate_turns_complete(self) -> bool:
        debaters = self._debater_autogen_names()
        if not debaters:
            return False
        return self._debate_turn_count() >= self.rounds * len(debaters)

    def _agent_has_non_empty_message(self, agent: Any) -> bool:
        if not self.groupchat or not agent:
            return False
        name = getattr(agent, "name", None)
        if not name:
            return False
        return any(
            msg.get("name") == name and (msg.get("content") or "").strip()
            for msg in self.groupchat.messages
        )

    def _judge_has_manager_history(self) -> bool:
        if not self.manager or not self.judge_agent:
            return False
        return bool(self.judge_agent._oai_messages.get(self.manager))

    def _ensure_judge_in_groupchat(self) -> None:
        """Ensure Judge is in the group and has the conversation history."""
        if not self.groupchat or not self.judge_agent:
            return
        if self.judge_agent not in self.groupchat.agents:
            self.groupchat.agents.append(self.judge_agent)
            self._register_judge_transitions()
        if not self._judge_has_manager_history():
            self._seed_judge_history()

    def _register_judge_transitions(self) -> None:
        """Keep speaker-transition graph consistent after adding the Judge."""
        if not self.groupchat or not self.judge_agent:
            return
        transitions = self.groupchat.allowed_speaker_transitions_dict
        for agent in self.groupchat.agents:
            if agent not in transitions:
                transitions[agent] = [
                    other for other in self.groupchat.agents if other is not agent
                ]
            elif self.judge_agent not in transitions[agent] and agent is not self.judge_agent:
                transitions[agent].append(self.judge_agent)
        if self.judge_agent not in transitions:
            transitions[self.judge_agent] = [
                other for other in self.groupchat.agents if other is not self.judge_agent
            ]

    def _seed_judge_history(self) -> None:
        """Replay group messages to the Judge so generate_reply has context."""
        if not self.manager or not self.judge_agent or not self.groupchat:
            return
        for msg in self.groupchat.messages:
            if not (msg.get("content") or "").strip():
                continue
            self.manager.send(msg, self.judge_agent, request_reply=False, silent=True)

    def _should_enter_finale(self) -> bool:
        if self._finale_complete:
            return False
        if self._in_finale:
            return True
        if self._force_judge:
            return True
        if self.mode == "sequential":
            return self._sequential_step[0] >= len(self._sequential_order)
        return self._debate_turns_complete()

    def _handle_finale_turn(self, last_speaker) -> Optional[Any]:
        """Return the Judge (then optional human gate) once, based on who has spoken."""
        if not self.judge_agent:
            self._finale_complete = True
            return None

        self._in_finale = True
        self._force_judge = False
        self._ensure_judge_in_groupchat()

        if not self._agent_has_non_empty_message(self.judge_agent):
            return self.judge_agent

        if self.human_gate and self.human_agent and not self._finale_human_complete:
            return self.human_agent

        self._finale_complete = True
        return None

    def _try_finale(self, last_speaker) -> Optional[Any]:
        if not self._should_enter_finale():
            return None
        return self._handle_finale_turn(last_speaker)

    def _set_waiting_human(self, prompt: str) -> None:
        with self.lock:
            self.status = "waiting_human"
            self.human_prompt = prompt
            self._sync_messages()

    def _set_waiting_manual(self) -> None:
        with self.lock:
            self.status = "waiting_manual_pick"
            self.available_speakers = [
                {
                    "id": lib_id,
                    "name": meta["name"],
                    "role": meta["role"],
                    "color": meta.get("color", "#64748b"),
                }
                for lib_id, meta in self.agent_meta.items()
                if lib_id in self.participant_ids and lib_id != self.judge_library_id
            ]
            if self.judge_library_id and self._force_judge:
                judge_meta = self.agent_meta.get(self.judge_library_id, {})
                self.available_speakers.append(
                    {
                        "id": self.judge_library_id,
                        "name": judge_meta.get("name", "Judge"),
                        "role": judge_meta.get("role", "Final verdict"),
                        "color": judge_meta.get("color", "#7c3aed"),
                    }
                )
            self._sync_messages()

    def _set_running(self) -> None:
        with self.lock:
            self.status = "running"
            self.human_prompt = ""
            self.available_speakers = []

    def _sync_messages(self) -> None:
        if not self.groupchat:
            return
        formatted = []
        for msg in self.groupchat.messages:
            content = (msg.get("content") or "").strip()
            if not content:
                continue
            autogen_key = msg.get("name") or "unknown"
            meta = self._meta_for_autogen_name(autogen_key)
            formatted.append(
                {
                    "id": f"{autogen_key}-{len(formatted)}",
                    "name": meta.get("name", autogen_key),
                    "agent_id": meta.get("id", autogen_key),
                    "role": meta.get("role", ""),
                    "color": meta.get("color", "#64748b"),
                    "content": content,
                }
            )
        self.messages = formatted

    def _meta_for_autogen_name(self, autogen_key: str) -> dict:
        if autogen_key == "Human":
            return {
                "id": "human",
                "name": "Human",
                "role": "Approves or steers the debate",
                "color": "#475569",
            }
        if autogen_key == "moderator" or autogen_key == MODERATOR_AGENT_ID:
            return {
                "id": MODERATOR_AGENT_ID,
                "name": MODERATOR_AGENT["name"],
                "role": MODERATOR_AGENT["role"],
                "color": MODERATOR_AGENT["color"],
            }
        for lib_id, meta in self.agent_meta.items():
            if autogen_name(meta) == autogen_key or meta.get("name") == autogen_key:
                return meta
        return {"id": autogen_key, "name": autogen_key.replace("_", " "), "role": ""}

    def _build_assistant(self, library_agent: dict) -> AssistantAgent:
        llm = build_llm_config(library_agent.get("temperature", 0.7))
        name = autogen_name(library_agent)
        return AssistantAgent(
            name=name,
            system_message=library_agent["system_message"],
            llm_config=llm,
        )

    def _build_sequential_order(self, human: WebHumanProxy) -> list[Any]:
        ordered_agents = []
        for lib_id in self.turn_order:
            if lib_id not in self.participant_ids or lib_id == self.judge_library_id:
                continue
            if lib_id in self.agents_by_id:
                ordered_agents.append(self.agents_by_id[lib_id])

        speaking: list[Any] = []
        for _ in range(self.rounds):
            for agent in ordered_agents:
                speaking.append(agent)
                if self.human_gate:
                    speaking.append(human)
        return speaking

    def _sequential_selector(self, last_speaker, groupchat: GroupChat):
        finale_agent = self._try_finale(last_speaker)
        if finale_agent is not None:
            return finale_agent
        if self._finale_complete:
            return None

        idx = self._sequential_step[0]
        if not self._sequential_order or idx >= len(self._sequential_order):
            return self._handle_finale_turn(last_speaker)

        agent = self._sequential_order[idx]
        self._sequential_step[0] += 1
        return agent

    def _manual_selector(self, last_speaker, groupchat: GroupChat):
        finale_agent = self._try_finale(last_speaker)
        if finale_agent is not None:
            self._set_running()
            return finale_agent
        if self._finale_complete:
            return None

        self._set_waiting_manual()
        self._manual_event.wait()
        self._manual_event.clear()
        pick_id = self._pending_pick_id
        self._pending_pick_id = None
        self._set_running()

        if pick_id == self.judge_library_id:
            with self.lock:
                self._force_judge = True
            return self._handle_finale_turn(last_speaker)

        if pick_id and pick_id in self.agents_by_id:
            return self.agents_by_id[pick_id]
        return None

    def _dynamic_selector(self, last_speaker, groupchat: GroupChat):
        finale_agent = self._try_finale(last_speaker)
        if finale_agent is not None:
            return finale_agent
        if self._finale_complete:
            return None
        return "auto"

    def _compute_max_rounds(self, num_debaters: int) -> int:
        finale_len = (1 if self.judge_agent else 0) + (1 if self.human_gate else 0)
        if self.mode == "sequential":
            return len(self._sequential_order) + finale_len + 4
        return num_debaters * self.rounds + finale_len + 8

    # ── Conversation mode (separate code path) ────────────────────────────────

    def _build_conversation_assistant(
        self, library_agent: dict, *, is_judge: bool = False, include_vote_suffix: bool = False
    ) -> AssistantAgent:
        llm = build_llm_config(library_agent.get("temperature", 0.7))
        name = autogen_name(library_agent)
        suffix = CONVERSATION_JUDGE_SUFFIX if is_judge else CONVERSATION_BREVITY_SUFFIX
        if include_vote_suffix:
            suffix += CONVERSATION_VOTE_SUFFIX
        return AssistantAgent(
            name=name,
            system_message=library_agent["system_message"] + suffix,
            llm_config=llm,
        )

    def _build_moderator_agent(self) -> AssistantAgent:
        llm = build_llm_config(MODERATOR_AGENT.get("temperature", 0.3))
        moderator = AssistantAgent(
            name="moderator",
            system_message=(
                MODERATOR_AGENT["system_message"]
                + f"\n\nORIGINAL_QUESTION = \"{self.question}\""
            ),
            llm_config=llm,
        )
        session = self

        def _dynamic_moderator_reply(recipient, messages, sender, config):
            return True, session._moderator_next_message

        moderator.register_reply([GroupChatManager], _dynamic_moderator_reply)
        return moderator

    def _conversation_debater_agents(self) -> list[AssistantAgent]:
        agents: list[AssistantAgent] = []
        for lib_id in self.participant_ids:
            if lib_id == self.judge_library_id:
                continue
            agent = self.agents_by_id.get(lib_id)
            if agent is not None:
                agents.append(agent)
        return agents

    def _recent_debater_messages(self, count: int = 5) -> list[dict]:
        if not self.groupchat:
            return []
        debaters = self._debater_autogen_names()
        debater_msgs = [
            msg
            for msg in self.groupchat.messages[self._consensus_resume_after :]
            if msg.get("name") in debaters and (msg.get("content") or "").strip()
        ]
        return debater_msgs[-count:]

    def _summarize_recent_themes(self, messages: list[dict]) -> str:
        if not messages:
            return "the discussion so far"
        client = OpenAIWrapper(**build_llm_config(temperature=0))
        transcript = "\n".join(
            f"{m.get('name')}: {(m.get('content') or '').strip()[:200]}" for m in messages
        )
        response = client.create(
            messages=[
                {
                    "role": "system",
                    "content": "Summarize the current discussion in 5-10 words (themes only).",
                },
                {"role": "user", "content": transcript},
            ]
        )
        summary = client.extract_text_or_completion_object(response)[0]
        return str(summary).strip() or "the discussion so far"

    def _generate_red_light_message(self, message_count: int) -> str:
        recent = self._recent_debater_messages(5)
        themes = self._summarize_recent_themes(recent)
        return (
            f"You've developed {themes}. Now let's ground that work: "
            f"**Directly addressing the original question — {self.question} — "
            f"what's your position based on what you've just discussed?** "
            f"Keep it tight: one clear answer + one reason. "
            f"(We're at {message_count} messages in this conversation.)"
        )

    def _generate_green_light_message(self, message_count: int) -> str:
        if self._should_escalate_consensus():
            return MODERATOR_ESCALATION_MESSAGE
        return (
            f"It seems we may be reaching a point where we can assess our progress. "
            f"Does everyone agree we've sufficiently addressed **{self.question}**? "
            f"Please respond with yes or no and a brief reason. "
            f"(Consensus check at {message_count} messages.)"
        )

    def _parse_vote(self, content: str) -> bool:
        first_line = (content or "").strip().splitlines()[0].strip().lower()
        if first_line.startswith("yes"):
            return True
        if first_line.startswith("no"):
            return False
        lowered = content.lower()
        if "vote: yes" in lowered or "i vote yes" in lowered:
            return True
        return False

    def _record_vote(self, agent: AssistantAgent) -> None:
        if not self.groupchat:
            return
        name = agent.name
        for msg in reversed(self.groupchat.messages):
            if msg.get("name") == name and (msg.get("content") or "").strip():
                self._votes[name] = self._parse_vote(msg.get("content", ""))
                return

    def _all_votes_yes(self) -> bool:
        if not self._voting_queue:
            return False
        expected = {agent.name for agent in self._voting_queue}
        return expected.issubset(self._votes.keys()) and all(self._votes[name] for name in expected)

    def _should_escalate_consensus(self) -> bool:
        if self._conversation_debater_message_count() < 80:
            return False
        if len(self._green_vote_history) < 3:
            return False
        recent = self._green_vote_history[-3:]
        return all(not all(votes.values()) for votes in recent)

    def _ensure_moderator_in_groupchat(self) -> None:
        if not self.groupchat or not self.moderator_agent:
            return
        if self.moderator_agent not in self.groupchat.agents:
            self.groupchat.agents.append(self.moderator_agent)
        if self.manager and not self.moderator_agent._oai_messages.get(self.manager):
            for msg in self.groupchat.messages:
                if not (msg.get("content") or "").strip():
                    continue
                self.manager.send(msg, self.moderator_agent, request_reply=False, silent=True)

    def _teardown_consensus_round(self) -> None:
        if self.groupchat and self.moderator_agent and self.moderator_agent in self.groupchat.agents:
            self.groupchat.agents.remove(self.moderator_agent)
        self._consensus_phase = None
        self._moderator_intervention = None
        self._pending_green_after_red = False
        self._voting_queue = []
        self._voting_index = 0
        self._votes = {}

    def _start_moderator_intervention(self, kind: str, message_count: int) -> None:
        if kind == "red":
            self._moderator_next_message = self._generate_red_light_message(message_count)
            self._moderator_intervention = "red"
        else:
            self._moderator_next_message = self._generate_green_light_message(message_count)
            self._moderator_intervention = "green"
        self._consensus_phase = "moderator_pending"
        self._ensure_moderator_in_groupchat()

    def _conversation_should_enter_finale(self) -> bool:
        if self._finale_complete:
            return False
        if self._in_finale:
            return True
        return self._force_judge

    def _conversation_try_finale(self, last_speaker) -> Optional[Any]:
        if self._force_judge and self._consensus_phase:
            self._teardown_consensus_round()
        if not self._conversation_should_enter_finale():
            return None
        return self._handle_finale_turn(last_speaker)

    def _plain_conversation_selector(self, last_speaker, groupchat: GroupChat):
        finale_agent = self._conversation_try_finale(last_speaker)
        if finale_agent is not None:
            return finale_agent
        if self._finale_complete:
            return None
        return "auto"

    def _beta_conversation_selector(self, last_speaker, groupchat: GroupChat):
        finale_agent = self._conversation_try_finale(last_speaker)
        if finale_agent is not None:
            return finale_agent
        if self._finale_complete:
            return None

        debaters = self._conversation_debater_agents()

        if self._consensus_phase == "voting":
            if last_speaker in debaters:
                self._record_vote(last_speaker)
            if self._voting_index < len(self._voting_queue):
                voter = self._voting_queue[self._voting_index]
                self._voting_index += 1
                return voter
            self._green_vote_history.append(dict(self._votes))
            if self._all_votes_yes():
                self._teardown_consensus_round()
                with self.lock:
                    self._force_judge = True
                return self._handle_finale_turn(last_speaker)
            if self.groupchat:
                self._consensus_resume_after = len(self.groupchat.messages)
            self._teardown_consensus_round()
            return "auto"

        if (
            self._consensus_phase == "moderator_pending"
            and self.moderator_agent
            and last_speaker is self.moderator_agent
        ):
            if self._moderator_intervention == "green":
                self._consensus_phase = "voting"
                self._voting_queue = list(debaters)
                self._voting_index = 0
                self._votes = {}
                if self._voting_index < len(self._voting_queue):
                    voter = self._voting_queue[self._voting_index]
                    self._voting_index += 1
                    return voter
            self._consensus_phase = None
            self._moderator_intervention = None
            return "auto"

        if (
            self._consensus_phase is None
            and self._pending_green_after_red
            and last_speaker in debaters
            and not self._in_finale
        ):
            self._pending_green_after_red = False
            count = self._conversation_debater_message_count()
            self._start_moderator_intervention("green", count)
            return self.moderator_agent

        if (
            self._consensus_phase is None
            and last_speaker in debaters
            and not self._in_finale
        ):
            count = self._conversation_debater_message_count()
            if count not in self._triggered_counts:
                red = _is_red_light_trigger(count)
                green = _is_green_light_trigger(count)
                if red or green:
                    self._triggered_counts.add(count)
                    if red and green:
                        self._pending_green_after_red = True
                        self._start_moderator_intervention("red", count)
                    elif red:
                        self._start_moderator_intervention("red", count)
                    else:
                        self._start_moderator_intervention("green", count)
                    return self.moderator_agent

        return "auto"

    def _run_conversation(self, *, include_moderator: bool) -> None:
        library = {a["id"]: a for a in load_agents()}
        participant_defs = []
        for lib_id in self.participant_ids:
            agent_def = library.get(lib_id) or get_agent(lib_id)
            if agent_def:
                participant_defs.append(agent_def)
                self.agent_meta[lib_id] = agent_def

        if self.judge_id in library:
            self.judge_library_id = self.judge_id
        elif "judge" in library:
            self.judge_library_id = "judge"
        else:
            self.judge_library_id = None

        human_mode = "ALWAYS" if self.human_gate else "NEVER"
        human = WebHumanProxy(
            session=self,
            name="Human",
            human_input_mode=human_mode,
            max_consecutive_auto_reply=0,
            code_execution_config=False,
            is_termination_msg=self._termination_check,
        )
        self.human_agent = human

        chat_agents: list[Any] = []
        if self.human_gate:
            chat_agents.append(human)

        vote_suffix = include_moderator
        for agent_def in participant_defs:
            if agent_def["id"] == self.judge_library_id:
                continue
            assistant = self._build_conversation_assistant(
                agent_def, include_vote_suffix=vote_suffix
            )
            self.agents_by_id[agent_def["id"]] = assistant
            chat_agents.append(assistant)

        if self.judge_library_id and self.judge_library_id in library:
            judge_def = library[self.judge_library_id]
            self.agent_meta[self.judge_library_id] = judge_def
            self.judge_agent = self._build_conversation_assistant(
                judge_def, is_judge=True, include_vote_suffix=False
            )
            self.agents_by_id[self.judge_library_id] = self.judge_agent

        if include_moderator:
            self.agent_meta[MODERATOR_AGENT_ID] = MODERATOR_AGENT
            self.moderator_agent = self._build_moderator_agent()
            selector = self._beta_conversation_selector
        else:
            selector = self._plain_conversation_selector

        groupchat = GroupChat(
            agents=chat_agents,
            messages=[],
            max_round=CONVERSATION_MAX_ROUNDS,
            speaker_selection_method=selector,
            allow_repeat_speaker=True,
            select_speaker_prompt_template=CONVERSATION_SPEAKER_PROMPT,
            allowed_or_disallowed_speaker_transitions=None,
        )
        manager = GroupChatManager(
            groupchat=groupchat,
            llm_config=build_llm_config(),
        )
        self.groupchat = groupchat
        self.manager = manager

        with self.lock:
            self.status = "running"

        human.initiate_chat(
            manager,
            message=(
                f"Question for discussion:\n\n{self.question}\n\n"
                "Please begin the conversation."
            ),
        )

        with self.lock:
            self.status = "complete"
            self._sync_messages()

    def _run(self) -> None:
        try:
            if self.style == "conversation":
                self._run_conversation(include_moderator=False)
                return
            if self.style == "conversation_beta":
                self._run_conversation(include_moderator=True)
                return

            library = {a["id"]: a for a in load_agents()}
            participant_defs = []
            for lib_id in self.participant_ids:
                agent_def = library.get(lib_id) or get_agent(lib_id)
                if agent_def:
                    participant_defs.append(agent_def)
                    self.agent_meta[lib_id] = agent_def

            if self.judge_id in library:
                self.judge_library_id = self.judge_id
            elif "judge" in library:
                self.judge_library_id = "judge"
            else:
                self.judge_library_id = None

            human_mode = "ALWAYS" if self.human_gate else "NEVER"
            human = WebHumanProxy(
                session=self,
                name="Human",
                human_input_mode=human_mode,
                max_consecutive_auto_reply=0,
                code_execution_config=False,
                is_termination_msg=self._termination_check,
            )
            self.human_agent = human

            chat_agents: list[Any] = []
            if self.human_gate:
                chat_agents.append(human)

            for agent_def in participant_defs:
                if agent_def["id"] == self.judge_library_id:
                    continue
                assistant = self._build_assistant(agent_def)
                self.agents_by_id[agent_def["id"]] = assistant
                chat_agents.append(assistant)

            if self.judge_library_id and self.judge_library_id in library:
                judge_def = library[self.judge_library_id]
                self.agent_meta[self.judge_library_id] = judge_def
                self.judge_agent = self._build_assistant(judge_def)
                self.agents_by_id[self.judge_library_id] = self.judge_agent
                chat_agents.append(self.judge_agent)

            if self.mode == "sequential":
                selector: Callable | str = self._sequential_selector
                self._sequential_order = self._build_sequential_order(human)
            elif self.mode == "manual":
                selector = self._manual_selector
            else:
                selector = self._dynamic_selector

            num_debaters = len(
                [lib_id for lib_id in self.participant_ids if lib_id != self.judge_library_id]
            )

            # In dynamic mode, prevent auto-selection of the Judge until the finale.
            disallowed_transitions = None
            transitions_type = None
            if self.mode == "dynamic" and self.judge_agent:
                disallowed_transitions = {
                    agent: [self.judge_agent]
                    for agent in chat_agents
                    if agent is not self.judge_agent
                }
                transitions_type = "disallowed"

            groupchat = GroupChat(
                agents=chat_agents,
                messages=[],
                max_round=self._compute_max_rounds(num_debaters),
                speaker_selection_method=selector,
                allowed_or_disallowed_speaker_transitions=disallowed_transitions,
                speaker_transitions_type=transitions_type,
            )
            manager = GroupChatManager(
                groupchat=groupchat,
                llm_config=build_llm_config(),
            )
            self.groupchat = groupchat
            self.manager = manager

            with self.lock:
                self.status = "running"

            human.initiate_chat(
                manager,
                message=(
                    f"Question for debate:\n\n{self.question}\n\n"
                    "Please begin the discussion."
                ),
            )

            with self.lock:
                self.status = "complete"
                self._sync_messages()
        except Exception as exc:
            traceback.print_exc()
            with self.lock:
                self.status = "error"
                self.error = f"{exc}\n\n{traceback.format_exc()}"
