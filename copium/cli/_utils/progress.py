"""Progress and spinner utilities for CLI output using Rich."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.text import Text

# Shared console (reuse the one from formatting if possible)
try:
    from copium.cli._utils.formatting import console
except ImportError:
    console = Console()


@contextmanager
def spinner(message: str) -> Iterator[Live]:
    """Context manager that shows a spinner with a message.

    Usage:
        with spinner("Starting proxy..."):
            do_work()
    """
    live = Live(Text(f"  ⏳ {message}"), console=console, refresh_per_second=10)
    with live:
        yield live


def download_bar(description: str, total: int) -> Progress:
    """Create a Rich Progress bar for downloads.

    Usage:
        bar = download_bar("Downloading RTK binary", total_size)
        with bar:
            task = bar.add_task(description, total=total_size)
            bar.update(task, advance=chunk_size)
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    )


def step_indicator(step: int, total: int, message: str) -> Text:
    """Create a formatted step indicator like 'Step 1/4: Detecting agents...'."""
    return Text(f"  Step {step}/{total}: {message}")


@contextmanager
def step_progress(steps: list[str]) -> Iterator[Live]:
    """Context manager that shows step-by-step progress.

    Usage:
        with step_progress(["Detecting agents", "Patching shell config"]) as live:
            # do step 1
            live.update(step_indicator(1, 2, "Detecting agents ✓"))
            # do step 2
            live.update(step_indicator(2, 2, "Patching shell config ✓"))
    """
    total = len(steps)
    text = step_indicator(1, total, steps[0])
    live = Live(text, console=console, refresh_per_second=10)
    with live:
        yield live
