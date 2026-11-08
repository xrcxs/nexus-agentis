# ADR 001: Stateful Agent Orchestration with LangGraph & SQLite Checkpointing

## Status
Accepted

## Context
Multi-agent research pipelines that pause for human review must survive process restarts without losing intermediate retrieval, synthesis, or verification state.

## Decision
We model the pipeline as a cyclic state machine (`planner -> retriever -> synthesizer -> verifier -> human_gate -> finalizer`) persisted to SQLite (`SqliteSaver`). At `human_gate`, calling `interrupt()` serializes the full `AgentGraphState` keyed by `thread_id = run_id`. When `POST /runs/{id}/decision` arrives—even after a container restart—the orchestrator reloads the checkpoint from SQLite and resumes via `Command(resume=...)`.

## Consequences
- **Positive:** Zero state loss across server restarts; deterministic replay of `approve`, `revise`, and `reject` transitions.
- **Trade-off:** SQLite write serialization limits single-node write concurrency, which we bound via `MAX_CONCURRENT_RUNS`.
