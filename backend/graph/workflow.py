"""LangGraph workflow compiler and high-level run orchestrator."""
from __future__ import annotations

import asyncio
from typing import Any

from backend.app.config import Settings
from backend.graph.checkpoint_engine import (
    END,
    START,
    Command,
    CompiledStateGraph,
    SqliteSaver,
    StateGraph,
)
from backend.graph.fixtures import stub_groq_responder, stub_tavily_search
from backend.graph.nodes import (
    AgentGraphState,
    EventBroadcastCallback,
    PipelineContext,
    build_finalizer_node,
    build_human_gate_node,
    build_planner_node,
    build_retriever_node,
    build_synthesizer_node,
    build_verifier_node,
    release_partial_draft_on_budget_exhaustion,
    route_after_human_gate,
    route_after_verifier,
)
from backend.models.schemas import HumanAction, RunStatus
from backend.services.database import Database
from backend.services.llm import (
    AsyncRateLimiter,
    GroqLLMClient,
    TokenBudgetExhaustedError,
)
from backend.services.search import TavilySearchClient


def create_agent_graph(
    ctx: PipelineContext,
    checkpointer: SqliteSaver,
) -> CompiledStateGraph:
    """Build and compile the NEXUS//AGENTIS StateGraph with SqliteSaver checkpointer."""
    builder = StateGraph(AgentGraphState)

    builder.add_node("planner", build_planner_node(ctx))
    builder.add_node("retriever", build_retriever_node(ctx))
    builder.add_node("synthesizer", build_synthesizer_node(ctx))
    builder.add_node("verifier", build_verifier_node(ctx))
    builder.add_node("human_gate", build_human_gate_node(ctx))
    builder.add_node("finalizer", build_finalizer_node(ctx))

    builder.add_edge(START, "planner")
    builder.add_edge("planner", "retriever")
    builder.add_edge("retriever", "synthesizer")
    builder.add_edge("synthesizer", "verifier")
    builder.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {
            "retriever": "retriever",
            "human_gate": "human_gate",
        },
    )
    builder.add_conditional_edges(
        "human_gate",
        route_after_human_gate,
        {
            "retriever": "retriever",
            "finalizer": "finalizer",
            "__end__": END,
        },
    )
    builder.add_edge("finalizer", END)

    return builder.compile(checkpointer=checkpointer)


class RunOrchestrator:
    """Manages active LangGraph runs, concurrency guards, timeouts, and checkpoint resumes."""

    def __init__(
        self,
        *,
        settings: Settings,
        db: Database,
        checkpointer: SqliteSaver | None = None,
        llm_client: GroqLLMClient | None = None,
        search_client: TavilySearchClient | None = None,
        on_event: EventBroadcastCallback | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.checkpointer = checkpointer or SqliteSaver(settings.checkpoint_db_path)
        self.rate_limiter = AsyncRateLimiter(settings.rate_limit_rpm)

        self.llm_client = llm_client or GroqLLMClient(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            base_url=settings.groq_base_url,
            rate_limiter=self.rate_limiter,
            stub_Responder=stub_groq_responder if settings.stub_external_apis else None,
        )
        self.search_client = search_client or TavilySearchClient(
            api_key=settings.tavily_api_key,
            base_url=settings.tavily_base_url,
            rate_limiter=self.rate_limiter,
            stub_searcher=stub_tavily_search if settings.stub_external_apis else None,
        )
        self.ctx = PipelineContext(
            db=self.db,
            llm_client=self.llm_client,
            search_client=self.search_client,
            settings=self.settings,
            on_event=on_event,
        )
        self.graph = create_agent_graph(self.ctx, self.checkpointer)
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_runs)
        self._active_tasks: dict[str, asyncio.Task[Any]] = {}

    @property
    def active_run_count(self) -> int:
        return sum(1 for t in self._active_tasks.values() if not t.done())

    async def execute_run(self, run_id: str) -> None:
        """Execute a run from START until human_gate interrupt, budget exhaustion, or failure."""
        summary = self.db.get_run_summary(run_id)
        if summary is None:
            return

        initial_state: AgentGraphState = {
            "run_id": run_id,
            "question": summary.question,
            "token_budget": summary.token_usage.budget_limit,
            "max_loops": summary.max_loops,
            "support_threshold": summary.support_threshold,
            "current_loop": 0,
            "status": RunStatus.QUEUED.value,
        }
        config = {"configurable": {"thread_id": run_id}}

        async with self._semaphore:
            try:
                await asyncio.wait_for(
                    self.graph.ainvoke(initial_state, config=config),
                    timeout=self.settings.run_timeout_seconds,
                )
            except TokenBudgetExhaustedError as exc:
                release_partial_draft_on_budget_exhaustion(self.ctx, run_id, str(exc))
            except asyncio.TimeoutError:
                msg = f"Run exceeded timeout of {self.settings.run_timeout_seconds}s."
                self.db.update_run_state(
                    run_id,
                    status=RunStatus.FAILED,
                    active_node=None,
                    error_message=msg,
                )
                self.ctx.emit(run_id, "system", "run_failed", {"error": msg})
            except Exception as exc:
                msg = f"Pipeline execution error: {exc}"
                self.db.update_run_state(
                    run_id,
                    status=RunStatus.FAILED,
                    active_node=None,
                    error_message=msg,
                )
                self.ctx.emit(run_id, "system", "run_failed", {"error": msg})

    async def resume_from_human_gate(
        self,
        run_id: str,
        *,
        action: HumanAction,
        feedback: str | None = None,
    ) -> None:
        """Resume an interrupted run from its persisted SQLite checkpoint."""
        config = {"configurable": {"thread_id": run_id}}
        cmd = Command(resume={"action": action.value, "feedback": feedback})
        async with self._semaphore:
            try:
                await asyncio.wait_for(
                    self.graph.ainvoke(cmd, config=config),
                    timeout=self.settings.run_timeout_seconds,
                )
            except TokenBudgetExhaustedError as exc:
                release_partial_draft_on_budget_exhaustion(self.ctx, run_id, str(exc))
            except Exception as exc:
                msg = f"Failed while resuming run from human_gate: {exc}"
                self.db.update_run_state(
                    run_id,
                    status=RunStatus.FAILED,
                    active_node=None,
                    error_message=msg,
                )
                self.ctx.emit(run_id, "system", "run_failed", {"error": msg})
