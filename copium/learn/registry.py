"""Plugin registry for copium learn.

Discovers built-in plugins from copium.learn.plugins.* and external
plugins registered via the ``copium.learn_plugin`` entry point group.

Follows the same pattern as copium.storage_backend (storage/__init__.py).
"""

from __future__ import annotations

import importlib
import logging
import pkgutil

from .base import LearnPlugin

logger = logging.getLogger(__name__)

_registry: dict[str, LearnPlugin] | None = None


def _discover() -> dict[str, LearnPlugin]:
    """Discover all built-in and external plugins."""
    plugins: dict[str, LearnPlugin] = {}

    # 1. Built-in: scan copium.learn.plugins.* submodules
    from copium.learn import plugins as plugins_pkg

    for _, mod_name, _ in pkgutil.iter_modules(plugins_pkg.__path__):
        try:
            mod = importlib.import_module(f"copium.learn.plugins.{mod_name}")
            if hasattr(mod, "plugin"):
                p = mod.plugin
                if isinstance(p, LearnPlugin):
                    plugins[p.name] = p
                    logger.debug("Loaded built-in learn plugin: %s", p.name)
        except Exception:
            logger.debug("Failed to load built-in plugin: %s", mod_name, exc_info=True)

    # 2. External: entry_points(group="copium.learn_plugin")
    try:
        from importlib.metadata import entry_points

        for ep in entry_points(group="copium.learn_plugin"):
            try:
                obj = ep.load()
                # Support both instances and factory callables
                if isinstance(obj, LearnPlugin):
                    p = obj
                elif callable(obj):
                    p = obj()
                else:
                    logger.warning("Learn plugin %s is not a LearnPlugin instance", ep.name)
                    continue

                if isinstance(p, LearnPlugin):
                    plugins[p.name] = p  # External overrides built-in on name collision
                    logger.debug("Loaded external learn plugin: %s (%s)", p.name, ep.name)
            except Exception:
                logger.warning("Failed to load external learn plugin: %s", ep.name, exc_info=True)
    except Exception:
        logger.debug("Entry point discovery failed", exc_info=True)

    return plugins


def get_registry() -> dict[str, LearnPlugin]:
    """Get the plugin registry, discovering plugins on first call.

    Returns a name → LearnPlugin mapping of all available plugins.
    """
    global _registry
    if _registry is None:
        _registry = _discover()
    return _registry


def get_plugin(name: str) -> LearnPlugin:
    """Look up a plugin by name.

    Raises KeyError with a helpful message if not found.
    """
    reg = get_registry()
    if name not in reg:
        available = ", ".join(sorted(reg.keys()))
        raise KeyError(f"Unknown agent: {name!r}. Available: {available}")
    return reg[name]


def auto_detect_plugins() -> list[LearnPlugin]:
    """Return plugins that have data on the current machine.

    Calls ``detect()`` on each registered plugin and filters to those
    that return True.
    """
    return [p for p in get_registry().values() if p.detect()]


def available_agent_names() -> list[str]:
    """Return sorted list of all registered agent names."""
    return sorted(get_registry().keys())


def reset_registry() -> None:
    """Clear the registry cache. Used in tests."""
    global _registry
    _registry = None
