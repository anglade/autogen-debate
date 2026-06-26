"""Flask API + React static files for the debate web app."""

from __future__ import annotations

import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from agents import create_agent, delete_agent, get_openai_api_key, load_library_agents, update_agent
from debate_engine import ConfigurableDebateSession

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"

app = Flask(__name__, static_folder=None)
CORS(app)
sessions: dict[str, ConfigurableDebateSession] = {}


# ── Agent library ─────────────────────────────────────────────────────────────

@app.get("/api/agents")
def list_agents():
    return jsonify(load_library_agents())


@app.post("/api/agents")
def add_agent():
    data = request.get_json(silent=True) or {}
    for field in ("name", "system_message"):
        if not (data.get(field) or "").strip():
            return jsonify({"error": f"{field} is required."}), 400
    agent = create_agent(data)
    return jsonify(agent), 201


@app.put("/api/agents/<agent_id>")
def edit_agent(agent_id: str):
    data = request.get_json(silent=True) or {}
    agent = update_agent(agent_id, data)
    if not agent:
        return jsonify({"error": "Agent not found."}), 404
    return jsonify(agent)


@app.delete("/api/agents/<agent_id>")
def remove_agent(agent_id: str):
    if not delete_agent(agent_id):
        return jsonify({"error": "Cannot delete this agent."}), 400
    return jsonify({"ok": True})


# ── Debate sessions ───────────────────────────────────────────────────────────

@app.post("/api/debate/start")
def start_debate():
    try:
        get_openai_api_key()

        data = request.get_json(silent=True) or {}
        question = (data.get("question") or "").strip()
        if not question:
            return jsonify({"error": "Question is required."}), 400

        participant_ids = data.get("participant_ids") or []
        if len(participant_ids) < 1:
            return jsonify({"error": "Select at least one agent."}), 400

        style = data.get("style", "debate")
        if style not in ("debate", "conversation", "conversation_beta"):
            return jsonify({"error": "Invalid debate style."}), 400

        mode = data.get("mode", "sequential")
        if style == "debate" and mode not in ("sequential", "dynamic", "manual"):
            return jsonify({"error": "Invalid debate mode."}), 400

        config = {
            "question": question,
            "participant_ids": participant_ids,
            "turn_order": data.get("turn_order") or participant_ids,
            "style": style,
            "mode": mode if style == "debate" else "dynamic",
            "human_gate": bool(data.get("human_gate", True)),
            "rounds": max(1, min(int(data.get("rounds", 2)), 10)),
            "judge_id": data.get("judge_id", "judge"),
        }

        session_id = str(uuid.uuid4())
        session = ConfigurableDebateSession(session_id, config)
        sessions[session_id] = session
        session.start()
        return jsonify({"session_id": session_id})
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        traceback.print_exc()
        return jsonify({"error": str(exc)}), 500


@app.get("/api/debate/<session_id>/status")
def debate_status(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found."}), 404
    return jsonify(session.to_dict())


@app.post("/api/debate/<session_id>/continue")
def continue_debate(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found."}), 404
    if session.status != "waiting_human":
        return jsonify({"error": "Not waiting for human input."}), 400
    data = request.get_json(silent=True) or {}
    session.submit_feedback((data.get("feedback") or "").strip())
    return jsonify({"ok": True})


@app.post("/api/debate/<session_id>/pick-speaker")
def pick_speaker(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found."}), 404
    if session.status != "waiting_manual_pick":
        return jsonify({"error": "Not waiting for speaker selection."}), 400
    data = request.get_json(silent=True) or {}
    agent_id = data.get("agent_id")
    if not agent_id:
        return jsonify({"error": "agent_id is required."}), 400
    session.pick_speaker(agent_id)
    return jsonify({"ok": True})


@app.post("/api/debate/<session_id>/end")
def end_debate(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found."}), 404
    session.end_debate()
    return jsonify({"ok": True})


@app.post("/api/debate/<session_id>/dismiss-verdict-prompt")
def dismiss_verdict_prompt(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found."}), 404
    session.dismiss_verdict_prompt()
    return jsonify({"ok": True})


@app.post("/api/debate/<session_id>/dismiss-escalation-prompt")
def dismiss_escalation_prompt(session_id: str):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found."}), 404
    session.dismiss_escalation_prompt()
    return jsonify({"ok": True})


# ── Frontend ──────────────────────────────────────────────────────────────────

@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def serve_frontend(path: str):
    if path.startswith("api/"):
        return jsonify({"error": "Not found."}), 404
    if FRONTEND_DIST.exists():
        target = FRONTEND_DIST / path
        if path and target.is_file():
            return send_from_directory(FRONTEND_DIST, path)
        return send_from_directory(FRONTEND_DIST, "index.html")
    return jsonify(
        {
            "message": "Frontend not built. Run: cd frontend && npm install && npm run build"
        }
    )


if __name__ == "__main__":
    try:
        api_key = get_openai_api_key()
        print(f"OPENAI_API_KEY loaded: {api_key[:10]}...")
    except RuntimeError:
        print("WARNING: OPENAI_API_KEY is not set")
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
