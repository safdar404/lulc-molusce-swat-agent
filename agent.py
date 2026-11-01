"""Anthropic tool-use loop for the web app."""
import json, os
from . import agent_tools

DEFAULT_MODEL = os.environ.get("LULC_AGENT_MODEL", "claude-sonnet-5-5")  # set LULC_AGENT_MODEL or the sidebar field if needed
SYSTEM_PROMPT = """You are a senior geospatial research assistant for a PhD workflow:
satellite imagery -> LULC classification -> change detection -> MOLUSCE simulation -> SWAT+ hydrology -> scenarios -> thesis.
Rules:
1. Never state a numeric result unless a tool returned it in this conversation. Never invent file contents, accuracies or parameters.
2. Inspect before you analyse: start with list_session, inspect_raster and check_geometry_match.
3. Enforce scientific order: accuracy assessment before change detection; MOLUSCE hindcasting before future scenarios; SWAT calibration then independent validation with frozen parameters; hold climate constant to isolate LULC effects.
4. MOLUSCE ANN/CA runs and QSWAT+ delineation happen in the user's own software. You prepare, check and evaluate around them; you do not run them. Use record_model_settings to log what the user reports.
5. Report units, CRS, class codes and sample sizes with every statistic. State uncertainty and limitations. Call outputs simulated or scenario-based, never certain.
6. When teaching, cite the practical number, deliverable and a viva question.
7. Be concise. If information is missing, ask one clear question."""


def run_agent(api_key, model, messages, session, user_text, max_rounds=10):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    messages.append({"role": "user", "content": user_text})
    events = []
    for _ in range(max_rounds):
        resp = client.messages.create(model=model, max_tokens=2048, system=SYSTEM_PROMPT, tools=agent_tools.schemas(), messages=messages)
        content = []
        for b in resp.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        messages.append({"role": "assistant", "content": content})
        results = []
        for b in content:
            if b["type"] == "text" and b["text"].strip():
                events.append(("assistant", b["text"]))
            elif b["type"] == "tool_use":
                events.append(("tool", f"{b['name']}({json.dumps(b['input'], default=str)[:200]})"))
                out = agent_tools.run_tool(session, b["name"], b["input"])
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": json.dumps(out, default=str)[:6000]})
        if not results:
            return events
        messages.append({"role": "user", "content": results})
    events.append(("error", "Stopped after the maximum number of tool rounds."))
    return events
