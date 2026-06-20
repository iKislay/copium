"""Compression Recipe System.

YAML-configurable compression recipes that users can share and extend.
Like TokenPak's 50 built-in recipes but community-driven.
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from copium.config import CopiumConfig


@dataclass
class RecipeTransform:
    """A single transform in a recipe."""

    name: str
    enabled: bool = True
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class CompressionRecipe:
    """A compression recipe - named set of transforms and configs."""

    name: str
    description: str
    version: str = "1.0"
    author: str = ""
    tags: list[str] = field(default_factory=list)

    # Transforms to apply (in order)
    transforms: list[RecipeTransform] = field(default_factory=list)

    # Override CopiumConfig settings
    config_overrides: dict[str, Any] = field(default_factory=dict)

    # Metadata
    estimated_savings: str = ""  # e.g., "40-60%"
    use_case: str = ""  # e.g., "agent-heavy workflows"


# Built-in recipes
BUILTIN_RECIPES: dict[str, CompressionRecipe] = {
    "lossless": CompressionRecipe(
        name="lossless",
        description="Safe, lossless-only compression. No quality loss.",
        version="1.0",
        tags=["safe", "lossless", "default"],
        use_case="Risk-averse users, production workloads",
        estimated_savings="20-40%",
        transforms=[
            RecipeTransform("cache_aligner", enabled=True),
            RecipeTransform("content_router", enabled=True, config={"mode": "lossless"}),
        ],
    ),
    "agent-heavy": CompressionRecipe(
        name="agent-heavy",
        description="Optimized for agent workflows with lots of tool calls.",
        version="1.0",
        tags=["agent", "tools", "code"],
        use_case="Coding assistants, multi-step agents",
        estimated_savings="50-70%",
        transforms=[
            RecipeTransform("cache_aligner", enabled=True),
            RecipeTransform("differential_response", enabled=True),
            RecipeTransform("content_router", enabled=True, config={"mode": "balanced"}),
            RecipeTransform("output_compressor", enabled=True),
            RecipeTransform("schema_compressor", enabled=True),
            RecipeTransform("toon_encoder", enabled=True),
        ],
    ),
    "rag-pipeline": CompressionRecipe(
        name="rag-pipeline",
        description="Optimized for RAG with many document chunks.",
        version="1.0",
        tags=["rag", "retrieval", "documents"],
        use_case="RAG pipelines, document Q&A",
        estimated_savings="60-80%",
        transforms=[
            RecipeTransform("cache_aligner", enabled=True),
            RecipeTransform("content_router", enabled=True, config={"mode": "aggressive"}),
            RecipeTransform("smart_crusher", enabled=True),
            RecipeTransform("output_compressor", enabled=True),
        ],
    ),
    "chat-optimized": CompressionRecipe(
        name="chat-optimized",
        description="Optimized for multi-turn chat conversations.",
        version="1.0",
        tags=["chat", "conversation"],
        use_case="Chatbots, conversational AI",
        estimated_savings="30-50%",
        transforms=[
            RecipeTransform("cache_aligner", enabled=True),
            RecipeTransform("chain_of_draft", enabled=True),
            RecipeTransform("output_compressor", enabled=True),
        ],
    ),
    "max-savings": CompressionRecipe(
        name="max-savings",
        description="Maximum compression, may lose some quality.",
        version="1.0",
        tags=["aggressive", "savings"],
        use_case="Cost-sensitive workloads, testing",
        estimated_savings="70-90%",
        transforms=[
            RecipeTransform("cache_aligner", enabled=True),
            RecipeTransform("differential_response", enabled=True),
            RecipeTransform("content_router", enabled=True, config={"mode": "aggressive"}),
            RecipeTransform("output_compressor", enabled=True),
            RecipeTransform("schema_compressor", enabled=True),
            RecipeTransform("toon_encoder", enabled=True),
            RecipeTransform("chain_of_draft", enabled=True),
        ],
    ),
}


class RecipeManager:
    """Manages compression recipes - loading, saving, applying."""

    def __init__(self, recipes_dir: Path | None = None) -> None:
        self.recipes_dir = recipes_dir or Path.home() / ".config" / "copium" / "recipes"
        self._recipes: dict[str, CompressionRecipe] = dict(BUILTIN_RECIPES)
        self._load_custom_recipes()

    def _load_custom_recipes(self) -> None:
        """Load custom recipes from the recipes directory."""
        if not self.recipes_dir.exists():
            return

        for recipe_file in self.recipes_dir.glob("*.yaml"):
            try:
                recipe = self.load_recipe(recipe_file)
                self._recipes[recipe.name] = recipe
            except Exception:
                continue

    def list_recipes(self) -> list[CompressionRecipe]:
        """List all available recipes."""
        return list(self._recipes.values())

    def get_recipe(self, name: str) -> CompressionRecipe | None:
        """Get a recipe by name."""
        return self._recipes.get(name)

    def load_recipe(self, path: Path) -> CompressionRecipe:
        """Load a recipe from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        transforms = [
            RecipeTransform(
                name=t["name"],
                enabled=t.get("enabled", True),
                config=t.get("config", {}),
            )
            for t in data.get("transforms", [])
        ]

        return CompressionRecipe(
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            transforms=transforms,
            config_overrides=data.get("config_overrides", {}),
            estimated_savings=data.get("estimated_savings", ""),
            use_case=data.get("use_case", ""),
        )

    def save_recipe(self, recipe: CompressionRecipe, path: Path | None = None) -> Path:
        """Save a recipe to a YAML file."""
        if path is None:
            self.recipes_dir.mkdir(parents=True, exist_ok=True)
            path = self.recipes_dir / f"{recipe.name}.yaml"

        data = {
            "name": recipe.name,
            "description": recipe.description,
            "version": recipe.version,
            "author": recipe.author,
            "tags": recipe.tags,
            "transforms": [
                {"name": t.name, "enabled": t.enabled, "config": t.config}
                for t in recipe.transforms
            ],
            "config_overrides": recipe.config_overrides,
            "estimated_savings": recipe.estimated_savings,
            "use_case": recipe.use_case,
        }

        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False)

        return path

    def apply_recipe(self, recipe: CompressionRecipe, config: CopiumConfig) -> CopiumConfig:
        """Apply a recipe to a CopiumConfig, returning modified config."""
        import copy
        new_config = copy.deepcopy(config)

        # Apply config overrides
        for key, value in recipe.config_overrides.items():
            if hasattr(new_config, key):
                setattr(new_config, key, value)

        # Apply transform configs
        for transform in recipe.transforms:
            if hasattr(new_config, transform.name):
                transform_config = getattr(new_config, transform.name)
                if hasattr(transform_config, "enabled"):
                    transform_config.enabled = transform.enabled
                for k, v in transform.config.items():
                    if hasattr(transform_config, k):
                        setattr(transform_config, k, v)

        return new_config

    def create_recipe(
        self,
        name: str,
        description: str,
        transforms: list[str],
        **kwargs: Any,
    ) -> CompressionRecipe:
        """Create a new recipe from a list of transform names."""
        recipe_transforms = [
            RecipeTransform(name=t, enabled=True) for t in transforms
        ]

        return CompressionRecipe(
            name=name,
            description=description,
            transforms=recipe_transforms,
            **kwargs,
        )
