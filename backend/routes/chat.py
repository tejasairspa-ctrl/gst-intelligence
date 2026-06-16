"""
Chat route — Flask blueprint with SSE streaming + direct numeric answers.

RULE: Numeric questions → direct computed answer (no LLM needed).
LLM is ONLY used for explanations, insights, and summarization.
"""
import json
import logging
import asyncio
from flask import Blueprint, Response, jsonify, request, stream_with_context

from store import store
from services.chat_service import (
    build_context, build_prompt, ask_ollama, get_direct_answer,
)

chat_bp = Blueprint("chat", __name__)
logger  = logging.getLogger(__name__)


@chat_bp.post("/chat")
def chat():
    data  = request.get_json() or {}
    query = data.get("query", "").strip()
    if not query:
        return jsonify(error="Query is required"), 400

    if not store.has_data():
        return jsonify(
            answer="No GST document uploaded yet. Please upload a GSTR-1, 3B, 9, or 9C PDF first.",
            sources=[],
            query=query,
            direct=False,
        )

    ctx       = store.get_active_context()
    extracted = ctx.get("extracted_data") or {}
    analytics = ctx.get("analytics") or {}

    # Try direct numeric answer first (no LLM needed)
    direct_answer = get_direct_answer(query, extracted, analytics)
    if direct_answer:
        store.add_message("user", query)
        store.add_message("assistant", direct_answer)
        return jsonify(
            answer=direct_answer,
            sources=["Extracted GST Data", "Computed Analytics"],
            query=query,
            direct=True,
        )

    # Fallback: LLM for explanation/insights
    context = build_context(ctx)
    prompt  = build_prompt(query, context, store.get_chat_history())
    store.add_message("user", query)
    answer = asyncio.run(ask_ollama(prompt))
    store.add_message("assistant", answer)

    return jsonify(answer=answer, sources=["Extracted GST Data", "Computed Analytics"], query=query, direct=False)


@chat_bp.post("/chat/stream")
def chat_stream():
    data  = request.get_json() or {}
    query = data.get("query", "").strip()

    if not query:
        def no_query():
            yield f"data: {json.dumps({'token': 'Query is required.', 'done': True})}\n\n"
        return Response(stream_with_context(no_query()), mimetype="text/event-stream")

    if not store.has_data():
        def no_data():
            msg = "No GST document uploaded yet. Please upload a PDF first."
            yield f"data: {json.dumps({'token': msg, 'done': True})}\n\n"
        return Response(stream_with_context(no_data()), mimetype="text/event-stream")

    ctx       = store.get_active_context()
    extracted = ctx.get("extracted_data") or {}
    analytics = ctx.get("analytics") or {}

    # Try direct numeric answer first — stream it instantly
    direct_answer = get_direct_answer(query, extracted, analytics)
    if direct_answer:
        def direct_stream():
            store.add_message("user", query)
            # Stream word by word for smoother UX
            for word in direct_answer.split(" "):
                yield f"data: {json.dumps({'token': word + ' ', 'done': False, 'direct': True})}\n\n"
            store.add_message("assistant", direct_answer)
            yield f"data: {json.dumps({'token': '', 'done': True, 'direct': True})}\n\n"
        return Response(
            stream_with_context(direct_stream()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # LLM streaming
    context = build_context(ctx)
    prompt  = build_prompt(query, context, store.get_chat_history())
    store.add_message("user", query)

    def generate():
        full = []
        import httpx
        payload = {
            "model": "llama3:8b",
            "prompt": prompt,
            "stream": True,
            "options": {"temperature": 0.1, "top_p": 0.9, "num_predict": 1024},
        }
        try:
            with httpx.stream("POST", "http://localhost:11434/api/generate",
                              json=payload, timeout=120) as r:
                for line in r.iter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            token = chunk.get("response", "")
                            if token:
                                full.append(token)
                                yield f"data: {json.dumps({'token': token, 'done': False})}\n\n"
                            if chunk.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.ConnectError:
            msg = (
                "⚠️ Ollama is not running. "
                "Start it: `ollama serve` and pull: `ollama pull llama3:8b`. "
                "\n\nFor numeric questions, I can still answer directly without the AI model — "
                "try asking about specific values like 'total tax liability' or 'ITC available'."
            )
            full.append(msg)
            yield f"data: {json.dumps({'token': msg, 'done': False})}\n\n"
        except Exception as exc:
            msg = f"⚠️ AI error: {exc}"
            full.append(msg)
            yield f"data: {json.dumps({'token': msg, 'done': False})}\n\n"

        store.add_message("assistant", "".join(full))
        yield f"data: {json.dumps({'token': '', 'done': True})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@chat_bp.get("/chat/history")
def get_history():
    return jsonify(history=store.get_chat_history())


@chat_bp.delete("/chat/history")
def clear_history():
    store.clear_chat()
    return jsonify(status="cleared")
