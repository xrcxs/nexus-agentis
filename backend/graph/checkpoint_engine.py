"""LangGraph StateGraph + SqliteSaver checkpointer binding with SQLite-persisted fallback engine."""
from __future__ import annotations

import copy
import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

START = "__start__"
END = "__end__"

try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver as NativeAsyncSqliteSaver  # type: ignore[import]
    from langgraph.graph import END as LG_END, START as LG_START, StateGraph as NativeStateGraph  # type: ignore[import]
    from langgraph.types import Command as NativeCommand, interrupt as native_interrupt  # type: ignore[import]

    LANGGRAPH_NATIVE_AVAILABLE = True
except ImportError:
    LANGGRAPH_NATIVE_AVAILABLE = False


class GraphInterruptException(Exception):
    """Internal signal raised by `interrupt()` to pause graph execution and persist checkpoint."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__("Graph interrupted at human_gate")
        self.payload = payload


@dataclass(frozen=True)
class Command:
    """Resume command passed to compiled_graph.ainvoke(Command(resume=...), config=...)."""

    resume: dict[str, Any]


_ACTIVE_RESUME_CONTEXT: dict[str, Any] = {}


def interrupt(payload: dict[str, Any]) -> dict[str, Any]:
    """Pause execution and persist state to SqliteSaver, or return the resume value if resuming."""
    thread_id = _ACTIVE_RESUME_CONTEXT.get("thread_id")
    if thread_id and thread_id in _ACTIVE_RESUME_CONTEXT.get("resume_payloads", {}):
        resume_val = _ACTIVE_RESUME_CONTEXT["resume_payloads"].pop(thread_id)
        return dict(resume_val)
    raise GraphInterruptException(payload)


class SqliteSaver:
    """Real SQLite-backed state checkpointer persisting graph state across process restarts."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._mem_conn: sqlite3.Connection | None = None
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        else:
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        self._init_table()

    def _connect(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self.db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
        except sqlite3.OperationalError:
            pass
        return conn

    def _init_table(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS langgraph_checkpoints (
                        thread_id TEXT PRIMARY KEY,
                        current_node TEXT NOT NULL,
                        state_json TEXT NOT NULL,
                        interrupted INTEGER NOT NULL DEFAULT 0,
                        interrupt_payload_json TEXT,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def put_checkpoint(
        self,
        *,
        thread_id: str,
        current_node: str,
        state: dict[str, Any],
        interrupted: bool = False,
        interrupt_payload: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO langgraph_checkpoints (
                        thread_id, current_node, state_json, interrupted, interrupt_payload_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        current_node = excluded.current_node,
                        state_json = excluded.state_json,
                        interrupted = excluded.interrupted,
                        interrupt_payload_json = excluded.interrupt_payload_json,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        thread_id,
                        current_node,
                        json.dumps(state, sort_keys=True),
                        1 if interrupted else 0,
                        json.dumps(interrupt_payload) if interrupt_payload else None,
                    ),
                )
                conn.commit()
            finally:
                if self._mem_conn is None:
                    conn.close()

    def get_checkpoint(self, thread_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT * FROM langgraph_checkpoints WHERE thread_id = ?",
                    (thread_id,),
                ).fetchone()
                if row is None:
                    return None
                return {
                    "thread_id": str(row["thread_id"]),
                    "current_node": str(row["current_node"]),
                    "state": json.loads(str(row["state_json"])),
                    "interrupted": bool(row["interrupted"]),
                    "interrupt_payload": (
                        json.loads(str(row["interrupt_payload_json"]))
                        if row["interrupt_payload_json"]
                        else None
                    ),
                }
            finally:
                if self._mem_conn is None:
                    conn.close()


NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
RouterFn = Callable[[dict[str, Any]], str]


class CompiledStateGraph:
    """Executable state graph supporting async nodes, conditional edges, and SQLite checkpoint resume."""

    def __init__(
        self,
        *,
        nodes: dict[str, NodeFn],
        edges: dict[str, str],
        conditional_edges: dict[str, tuple[RouterFn, dict[str, str]]],
        checkpointer: SqliteSaver,
    ) -> None:
        self._nodes = nodes
        self._edges = edges
        self._conditional_edges = conditional_edges
        self.checkpointer = checkpointer

    async def ainvoke(
        self,
        input_or_command: dict[str, Any] | Command,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        thread_id = str(config.get("configurable", {}).get("thread_id", "default"))
        _ACTIVE_RESUME_CONTEXT.setdefault("resume_payloads", {})

        if isinstance(input_or_command, Command):
            saved = self.checkpointer.get_checkpoint(thread_id)
            if saved is None:
                raise RuntimeError(f"No persisted checkpoint found for thread_id='{thread_id}'.")
            state = copy.deepcopy(saved["state"])
            current_node = str(saved["current_node"])
            _ACTIVE_RESUME_CONTEXT["thread_id"] = thread_id
            _ACTIVE_RESUME_CONTEXT["resume_payloads"][thread_id] = input_or_command.resume
        else:
            state = copy.deepcopy(input_or_command)
            current_node = self._edges[START]
            self.checkpointer.put_checkpoint(
                thread_id=thread_id,
                current_node=current_node,
                state=state,
                interrupted=False,
            )

        while current_node != END:
            node_fn = self._nodes[current_node]
            _ACTIVE_RESUME_CONTEXT["thread_id"] = thread_id
            try:
                updates = await node_fn(state)
                if updates:
                    state.update(updates)
            except GraphInterruptException as intr:
                self.checkpointer.put_checkpoint(
                    thread_id=thread_id,
                    current_node=current_node,
                    state=state,
                    interrupted=True,
                    interrupt_payload=intr.payload,
                )
                return state

            if current_node in self._conditional_edges:
                router_fn, path_map = self._conditional_edges[current_node]
                route_key = router_fn(state)
                next_node = path_map.get(route_key, route_key)
            else:
                next_node = self._edges.get(current_node, END)

            self.checkpointer.put_checkpoint(
                thread_id=thread_id,
                current_node=next_node,
                state=state,
                interrupted=False,
            )
            current_node = next_node

        return state


class StateGraph:
    """LangGraph-compatible StateGraph builder."""

    def __init__(self, state_schema: Any) -> None:
        self.state_schema = state_schema
        self._nodes: dict[str, NodeFn] = {}
        self._edges: dict[str, str] = {}
        self._conditional_edges: dict[str, tuple[RouterFn, dict[str, str]]] = {}

    def add_node(self, name: str, fn: NodeFn) -> None:
        self._nodes[name] = fn

    def add_edge(self, source: str, target: str) -> None:
        self._edges[source] = target

    def add_conditional_edges(
        self,
        source: str,
        router: RouterFn,
        path_map: dict[str, str],
    ) -> None:
        self._conditional_edges[source] = (router, path_map)

    def compile(self, checkpointer: SqliteSaver) -> CompiledStateGraph:
        if START not in self._edges:
            raise ValueError("StateGraph must have an edge from START.")
        return CompiledStateGraph(
            nodes=dict(self._nodes),
            edges=dict(self._edges),
            conditional_edges=dict(self._conditional_edges),
            checkpointer=checkpointer,
        )
