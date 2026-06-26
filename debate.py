#!/usr/bin/env python3
"""CLI entry point for the five-agent AutoGen debate."""

from __future__ import annotations

import sys

from agents import load_agents
from debate_engine import build_llm_config
from autogen import AssistantAgent, GroupChat, GroupChatManager, UserProxyAgent

from agents import autogen_name


def prompt_question() -> str:
    print("Enter the question for the agents to debate:")
    while True:
        question = input("> ").strip()
        if question:
            return question
        print("Please enter a non-empty question.")


def run_debate(question: str) -> None:
    try:
        llm_config = build_llm_config()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    library = [a for a in load_agents() if a["id"] != "judge"]
    human = UserProxyAgent(
        name="Human",
        human_input_mode="ALWAYS",
        max_consecutive_auto_reply=0,
        code_execution_config=False,
        is_termination_msg=lambda msg: "TERMINATE" in (msg.get("content") or ""),
    )

    assistants = []
    for agent_def in library:
        assistants.append(
            AssistantAgent(
                name=autogen_name(agent_def),
                system_message=agent_def["system_message"],
                llm_config={**llm_config, "temperature": agent_def.get("temperature", 0.7)},
            )
        )

    order = []
    for a in assistants:
        order.extend([a, human])

    step = [0]

    def select_speaker(last_speaker, groupchat):
        idx = step[0]
        if idx >= len(order):
            return None
        agent = order[idx]
        step[0] += 1
        return agent

    groupchat = GroupChat(
        agents=[*assistants, human],
        messages=[],
        max_round=len(order) + 4,
        speaker_selection_method=select_speaker,
    )
    manager = GroupChatManager(groupchat=groupchat, llm_config=llm_config)

    print("=" * 72)
    print("AutoGen debate (human_input_mode='ALWAYS')")
    print("=" * 72)
    print(f"\nQuestion:\n{question}\n")
    print("Press Enter to approve, type feedback to steer, 'exit' to stop.")
    print("=" * 72 + "\n")

    human.initiate_chat(
        manager,
        message=f"Question for debate:\n\n{question}\n\nPlease begin.",
    )


def main() -> None:
    run_debate(prompt_question())


if __name__ == "__main__":
    main()
