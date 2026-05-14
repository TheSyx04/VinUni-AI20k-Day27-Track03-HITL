"""Exercise 2 — HITL with interrupt() + Command(resume=...).

Starting from exercise 1, turn the `human_approval` node from a placeholder
into real HITL: call interrupt() with a payload containing diff + reasoning,
then resume the graph with Command(resume=<user choice>).
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


def node_fetch_pr(state: ReviewState) -> dict:
    pr = fetch_pr(state["pr_url"])
    return {"pr_title": pr.title, "pr_diff": pr.diff, "pr_files": pr.files_changed, "pr_head_sha": pr.head_sha}


def node_analyze(state: ReviewState) -> dict:
    llm = get_llm().with_structured_output(PRAnalysis)
    return {"analysis": llm.invoke([
        {"role": "system", "content": "Senior reviewer. Structured output."},
        {"role": "user", "content": f"Title: {state['pr_title']}\nDiff:\n{state['pr_diff']}"},
    ])}


def node_route(state: ReviewState) -> dict:
    c = state["analysis"].confidence
    if c >= AUTO_APPROVE_THRESHOLD: return {"decision": "auto_approve"}
    if c < ESCALATE_THRESHOLD:      return {"decision": "escalate"}
    return {"decision": "human_approval"}


def node_human_approval(state: ReviewState) -> dict:
    """Pause and ask the human."""
    a = state["analysis"]
    # TODO: call interrupt(payload) where payload contains these fields:
    #         "kind": "approval_request",
    #         "confidence": a.confidence,
    #         "confidence_reasoning": a.confidence_reasoning,
    #         "summary": a.summary,
    #         "comments": [c.model_dump() for c in a.comments],
    #         "diff_preview": state["pr_diff"][:2000],
    # interrupt() returns whatever the caller passes via Command(resume=...).
    # response = interrupt(...)
    # return {"human_choice": response["choice"], "human_feedback": response.get("feedback")}
    raise NotImplementedError("Call interrupt() with an approval_request payload")


def node_commit(state: ReviewState) -> dict:
    return {"final_action": "committed" if state.get("human_choice") == "approve" else "rejected"}


def node_auto_approve(state): return {"final_action": "auto_approved"}
def node_escalate(state):     return {"final_action": "pending_escalation"}


def build_graph():
    g = StateGraph(ReviewState)
    for name, fn in [
        ("fetch_pr", node_fetch_pr), ("analyze", node_analyze), ("route", node_route),
        ("auto_approve", node_auto_approve), ("human_approval", node_human_approval),
        ("escalate", node_escalate), ("commit", node_commit),
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
    g.add_edge("escalate", END)
    # TODO: compile with checkpointer=MemorySaver()
    return g.compile()


def prompt_human(payload: dict) -> dict:
    console.print(Panel.fit(
        f"Confidence: {payload['confidence']:.0%}\n{payload['confidence_reasoning']}\n\n{payload['summary']}",
        title="Approval request",
    ))
    choice = ""
    while choice not in {"approve", "reject", "edit"}:
        choice = console.input("Choice (approve/reject/edit)? ").strip().lower()
    feedback = console.input("Feedback: ").strip() if choice != "approve" else ""
    return {"choice": choice, "feedback": feedback}


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--pr", required=True)
    args = parser.parse_args()

    app = build_graph()
    thread_id = str(uuid.uuid4())
    cfg = {"configurable": {"thread_id": thread_id}}

    result = app.invoke({"pr_url": args.pr, "thread_id": thread_id}, cfg)

    # TODO: write a `while "__interrupt__" in result:` loop:
    #   - take payload from result["__interrupt__"][0].value
    #   - call prompt_human(payload)
    #   - resume with app.invoke(Command(resume=<answer>), cfg)
    # while "__interrupt__" in result:
    #     ...

    console.rule("Done")
    console.print(result.get("final_action"))


if __name__ == "__main__":
    main()
