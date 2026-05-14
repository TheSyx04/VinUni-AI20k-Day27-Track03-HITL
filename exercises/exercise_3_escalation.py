"""Exercise 3 — Escalation branch with reviewer Q&A.

When confidence < 60%, the agent doesn't ask approve/reject — it asks specific
clarifying questions and then synthesizes a refined review from the answers.
"""

from __future__ import annotations

import argparse
import uuid

from dotenv import load_dotenv
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from rich.console import Console
from rich.panel import Panel

from common.github import fetch_pr
from common.llm import get_llm
from common.schemas import (
    AUTO_APPROVE_THRESHOLD,
    ESCALATE_THRESHOLD,
    PRAnalysis,
    ReviewState,
)


console = Console()


def node_fetch_pr(state):
    pr = fetch_pr(state["pr_url"])
    return {"pr_title": pr.title, "pr_diff": pr.diff, "pr_files": pr.files_changed, "pr_head_sha": pr.head_sha}


def node_analyze(state):
    llm = get_llm().with_structured_output(PRAnalysis)
    return {"analysis": llm.invoke([
        {"role": "system", "content": (
            "Senior reviewer. Structured output. "
            # TODO: add an instruction: if confidence < 60%, populate escalation_questions
            # with 2–4 specific, context-rich questions (reference which file/section in the diff).
        )},
        {"role": "user", "content": f"Title: {state['pr_title']}\nDiff:\n{state['pr_diff']}"},
    ])}


def node_route(state):
    c = state["analysis"].confidence
    if c >= AUTO_APPROVE_THRESHOLD: return {"decision": "auto_approve"}
    if c < ESCALATE_THRESHOLD:      return {"decision": "escalate"}
    return {"decision": "human_approval"}


def node_escalate(state: ReviewState) -> dict:
    """Ask the reviewer specific questions; return their answers in state."""
    a = state["analysis"]
    questions = a.escalation_questions
    if not questions:
        # fallback when the LLM didn't generate any questions
        questions = ["What is the intent of this PR?", "Any migration concerns?"]

    # TODO: call interrupt(payload) where payload kind="escalation" contains:
    #       pr_url, confidence, confidence_reasoning, summary, risk_factors, questions.
    # answers = interrupt({...})
    # return {"escalation_answers": answers}
    raise NotImplementedError("Call interrupt() with an escalation payload")


def node_synthesize(state: ReviewState) -> dict:
    """Re-prompt LLM with the reviewer's answers and produce a refined review."""
    # TODO:
    #   - read state["escalation_answers"] (dict[question, answer])
    #   - call get_llm().with_structured_output(PRAnalysis).invoke(...) with a prompt
    #     containing the original diff + initial analysis + Q&A.
    #   - return {"analysis": refined, "final_action": "escalated_then_synthesized"}
    raise NotImplementedError("Synthesize a refined PRAnalysis using the reviewer answers")


def node_human_approval(state):
    a = state["analysis"]
    response = interrupt({
        "kind": "approval_request", "pr_url": state["pr_url"],
        "confidence": a.confidence, "confidence_reasoning": a.confidence_reasoning,
        "summary": a.summary,
        "comments": [c.model_dump() for c in a.comments],
        "diff_preview": state["pr_diff"][:2000],
    })
    return {"human_choice": response.get("choice"), "human_feedback": response.get("feedback")}


def node_commit(state):
    return {"final_action": "committed" if state.get("human_choice") == "approve" else "rejected"}


def node_auto_approve(state): return {"final_action": "auto_approved"}


def build_graph():
    g = StateGraph(ReviewState)
    for name, fn in [
        ("fetch_pr", node_fetch_pr), ("analyze", node_analyze), ("route", node_route),
        ("auto_approve", node_auto_approve), ("human_approval", node_human_approval),
        ("commit", node_commit), ("escalate", node_escalate), ("synthesize", node_synthesize),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "fetch_pr")
    g.add_edge("fetch_pr", "analyze")
    g.add_edge("analyze", "route")
    g.add_conditional_edges(
        "route", lambda s: s["decision"],
        {"auto_approve": "auto_approve", "human_approval": "human_approval", "escalate": "escalate"},
    )
    g.add_edge("auto_approve", END)
    g.add_edge("human_approval", "commit")
    g.add_edge("commit", END)
    # TODO: wire escalate → synthesize → END
    return g.compile(checkpointer=MemorySaver())


def handle_interrupt(payload):
    kind = payload["kind"]
    if kind == "approval_request":
        console.print(Panel.fit(payload["summary"], title=f"Approve? conf={payload['confidence']:.0%}"))
        choice = console.input("approve/reject/edit? ").strip().lower()
        return {"choice": choice, "feedback": console.input("Feedback: ").strip()}
    if kind == "escalation":
        console.print(Panel.fit(payload["summary"], title=f"Escalation conf={payload['confidence']:.0%}"))
        return {q: console.input(f"Q: {q}\nA: ").strip() for q in payload["questions"]}
    raise ValueError(kind)


def main():
    load_dotenv()
    p = argparse.ArgumentParser(); p.add_argument("--pr", required=True)
    args = p.parse_args()
    app = build_graph()
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}}
    result = app.invoke({"pr_url": args.pr, "thread_id": thread_id}, cfg)
    while "__interrupt__" in result:
        result = app.invoke(Command(resume=handle_interrupt(result["__interrupt__"][0].value)), cfg)
    console.print(f"final_action = {result.get('final_action')}")


if __name__ == "__main__":
    main()
