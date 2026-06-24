"""Shared CLI options for consistent flag handling across commands."""

from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

import click

F = TypeVar("F", bound=Callable[..., Any])


def add_common_options(func: F) -> F:
    """Decorator that adds --json and --quiet flags to a Click command.

    Usage:
        @main.command()
        @add_common_options
        def my_command(json: bool, quiet: bool) -> None:
            ...
    """
    func = click.option(
        "--json",
        "as_json",
        is_flag=True,
        default=False,
        help="Output machine-readable JSON.",
    )(func)
    func = click.option(
        "--quiet",
        "-q",
        is_flag=True,
        default=False,
        help="Suppress non-error output.",
    )(func)
    return func


def output_json(data: dict[str, Any], as_json: bool) -> None:
    """Output data as JSON if --json flag is set, otherwise return None.

    Returns True if JSON was output, False otherwise.
    """
    if as_json:
        import json

        click.echo(json.dumps(data, indent=2))
        return True
    return False


def quiet_print(message: str, quiet: bool, **kwargs: Any) -> None:
    """Print a message only if --quiet is not set.

    Args:
        message: The message to print.
        quiet: If True, suppress output.
        **kwargs: Additional arguments passed to click.echo.
    """
    if not quiet:
        click.echo(message, **kwargs)
