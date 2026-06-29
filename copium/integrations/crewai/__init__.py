"""CrewAI integration for Copium SharedContext.

Provides wrappers that automatically compress context during
inter-agent handoffs in CrewAI workflows.

Usage:

    from copium.integrations.crewai import CopiumCrew
    from crewai import Agent, Task

    researcher = Agent(role="Researcher", ...)
    coder = Agent(role="Coder", ...)

    research_task = Task(description="Research", agent=researcher)
    code_task = Task(description="Code", agent=coder)

    crew = CopiumCrew(
        agents=[researcher, coder],
        tasks=[research_task, code_task],
        shared_context=True,
    )
    result = crew.kickoff()
"""

from __future__ import annotations

import logging
from typing import Any

from copium import SharedContext

logger = logging.getLogger(__name__)


class CopiumCrewContext:
    """Shared context wrapper for CrewAI workflows.

    Captures task outputs and makes compressed versions available
    to subsequent tasks automatically.

    Args:
        persistent: Enable persistent storage across sessions.
        model: Model for compression pipeline.
        project_id: Project scope for isolation.
    """

    def __init__(
        self,
        *,
        persistent: bool = True,
        model: str = "claude-sonnet-4-5-20250929",
        project_id: str | None = None,
    ) -> None:
        self._ctx = SharedContext(
            model=model,
            persistent=persistent,
            project_id=project_id,
        )

    def store_task_output(
        self,
        task_name: str,
        output: str,
        *,
        agent_role: str | None = None,
    ) -> dict[str, Any]:
        """Store a task's output in shared context.

        Args:
            task_name: Name/key for this task output.
            output: The task output to compress and store.
            agent_role: The CrewAI agent role that produced this.

        Returns:
            Dict with compression stats.
        """
        entry = self._ctx.put(task_name, output, agent=agent_role)
        return {
            "key": task_name,
            "original_tokens": entry.original_tokens,
            "compressed_tokens": entry.compressed_tokens,
            "savings_percent": entry.savings_percent,
        }

    def get_context_for_task(
        self,
        task_name: str,
        *,
        full: bool = False,
    ) -> str | None:
        """Get compressed context from a previous task.

        Args:
            task_name: Key of the previous task output.
            full: If True, return uncompressed original.

        Returns:
            Compressed (or full) content, or None.
        """
        return self._ctx.get(task_name, full=full)

    def get_all_context(self) -> dict[str, str]:
        """Get all available compressed context as a dict."""
        result = {}
        for key in self._ctx.keys():
            content = self._ctx.get(key)
            if content:
                result[key] = content
        return result

    @property
    def stats(self) -> Any:
        """Get compression statistics."""
        return self._ctx.stats()


class CopiumCrewCallbacks:
    """Callback handler for CrewAI task lifecycle.

    Attach to a Crew to automatically capture task outputs
    and inject compressed context into subsequent tasks.
    """

    def __init__(self, context: CopiumCrewContext) -> None:
        self._context = context

    def on_task_complete(
        self,
        task_name: str,
        output: str,
        agent_role: str | None = None,
    ) -> None:
        """Called when a task completes. Stores output in shared context."""
        self._context.store_task_output(
            task_name, output, agent_role=agent_role
        )
        logger.debug("CrewAI task '%s' output stored in shared context", task_name)

    def get_context_prefix(self, task_name: str) -> str:
        """Generate a context prefix for a task from all shared context.

        Returns a formatted string with all available compressed context
        that can be prepended to a task's input.
        """
        all_ctx = self._context.get_all_context()
        if not all_ctx:
            return ""

        parts = ["[Shared Context from previous tasks]:"]
        for key, content in all_ctx.items():
            parts.append(f"\n--- {key} ---\n{content}")
        return "\n".join(parts)
