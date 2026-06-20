"""CLI: compression recipe management."""

from __future__ import annotations

import click
from pathlib import Path

from .main import main


@main.group("recipe")
def recipe_group() -> None:
    """Manage compression recipes.

    \b
    Examples:
        copium recipe list              List all recipes
        copium recipe show agent-heavy  Show recipe details
        copium recipe apply agent-heavy Apply recipe to config
    """


@recipe_group.command("list")
@click.option("--json-output", is_flag=True, help="Output as JSON.")
def list_recipes(json_output: bool) -> None:
    """List all available compression recipes."""
    from copium.recipes import RecipeManager
    import json

    manager = RecipeManager()
    recipes = manager.list_recipes()

    if json_output:
        output = [
            {
                "name": r.name,
                "description": r.description,
                "tags": r.tags,
                "estimated_savings": r.estimated_savings,
                "transforms": len(r.transforms),
            }
            for r in recipes
        ]
        click.echo(json.dumps(output, indent=2))
    else:
        click.echo("\nAvailable compression recipes:\n")
        click.echo(f"{'Name':<20}{'Savings':<12}{'Transforms':<12}{'Description'}")
        click.echo("-" * 80)
        for r in recipes:
            click.echo(
                f"{r.name:<20}{r.estimated_savings:<12}{len(r.transforms):<12}{r.description}"
            )
        click.echo(f"\n({len(recipes)} recipes available)")


@recipe_group.command("show")
@click.argument("name")
def show_recipe(name: str) -> None:
    """Show details of a specific recipe."""
    from copium.recipes import RecipeManager

    manager = RecipeManager()
    recipe = manager.get_recipe(name)

    if recipe is None:
        click.echo(f"Recipe '{name}' not found.")
        raise SystemExit(1)

    click.echo(f"\nRecipe: {recipe.name}")
    click.echo(f"Description: {recipe.description}")
    click.echo(f"Version: {recipe.version}")
    click.echo(f"Author: {recipe.author or 'N/A'}")
    click.echo(f"Tags: {', '.join(recipe.tags)}")
    click.echo(f"Estimated savings: {recipe.estimated_savings}")
    click.echo(f"Use case: {recipe.use_case}")
    click.echo(f"\nTransforms ({len(recipe.transforms)}):")
    for t in recipe.transforms:
        status = "enabled" if t.enabled else "disabled"
        click.echo(f"  - {t.name} ({status})")
        if t.config:
            for k, v in t.config.items():
                click.echo(f"      {k}: {v}")


@recipe_group.command("apply")
@click.argument("name")
@click.option("--output", "-o", type=click.Path(), help="Output config file.")
def apply_recipe(name: str, output: str | None) -> None:
    """Apply a recipe to generate a config file."""
    from copium.recipes import RecipeManager
    from copium.config import CopiumConfig

    manager = RecipeManager()
    recipe = manager.get_recipe(name)

    if recipe is None:
        click.echo(f"Recipe '{name}' not found.")
        raise SystemExit(1)

    config = CopiumConfig()
    new_config = manager.apply_recipe(recipe, config)

    click.echo(f"Applied recipe '{name}' to config.")
    if output:
        click.echo(f"Config saved to: {output}")
    else:
        click.echo("\nTo use this config, set COPIUM_CONFIG env var or pass --config to proxy.")


@recipe_group.command("create")
@click.argument("name")
@click.option("--description", "-d", required=True, help="Recipe description.")
@click.option("--transforms", "-t", multiple=True, help="Transform names to include.")
@click.option("--tags", multiple=True, help="Tags for the recipe.")
def create_recipe(name: str, description: str, transforms: tuple[str, ...], tags: tuple[str, ...]) -> None:
    """Create a new custom recipe."""
    from copium.recipes import RecipeManager, CompressionRecipe

    manager = RecipeManager()

    if manager.get_recipe(name) is not None:
        click.echo(f"Recipe '{name}' already exists.")
        raise SystemExit(1)

    recipe = CompressionRecipe(
        name=name,
        description=description,
        tags=list(tags),
        transforms=[
            {"name": t, "enabled": True} for t in transforms
        ],
    )

    path = manager.save_recipe(recipe)
    click.echo(f"Created recipe '{name}' at {path}")
