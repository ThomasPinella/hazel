"""CLI: ``hazel auth`` and ``hazel secret list``.

Unified entry point for setting any credential Hazel ever needs — API keys,
OAuth tokens, MCP bearers, skill passwords. The value lands in the secrets
store (``~/.hazel/secrets/<name>``) and the LLM can then check availability
via the ``request_secret`` tool without ever seeing the value itself.
"""

from __future__ import annotations

import getpass
import os

import typer

from hazel import secrets as _secrets
from hazel.cli.commands import app, console


secret_app = typer.Typer(help="Manage stored secrets (names only — never values)")
app.add_typer(secret_app, name="secret")


def _prompt_overwrite(name: str) -> bool:
    resp = typer.prompt(
        f"Secret '{name}' already exists. Overwrite?",
        default="n",
        show_default=True,
    ).strip().lower()
    return resp in ("y", "yes")


@app.command("auth")
def auth(
    name: str = typer.Argument(
        ..., help="Secret name (e.g. gmail, openweather, my_mcp_bearer)"
    ),
    remove: bool = typer.Option(
        False, "--remove", help="Delete the stored secret instead of setting it"
    ),
    from_env: str | None = typer.Option(
        None, "--from-env",
        help="Read the value from a named environment variable (e.g. --from-env MY_API_KEY)",
    ),
    show: bool = typer.Option(
        False, "--show",
        help="Print the stored value to stdout (dangerous — opt-in only)",
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Skip the overwrite confirmation prompt"
    ),
) -> None:
    """Set, remove, or retrieve a stored secret.

    \b
    hazel auth gmail                # run OAuth if registered, else prompt
    hazel auth openweather          # getpass prompt
    hazel auth mykey --from-env X   # copy env var X into the 'mykey' secret
    hazel auth mykey --remove       # delete the 'mykey' secret
    hazel auth mykey --show         # print the value (dangerous)
    """
    # Validate name shape up front so the user sees the same rule once
    try:
        _secrets.validate_name(name)
    except ValueError as e:
        console.print(f"[red]Invalid secret name:[/red] {e}")
        raise typer.Exit(1)

    # Reject incompatible flag combinations before doing anything, so a
    # user who types `--show --remove` gets a clear error instead of the
    # flag-precedence surprise of "show wins, remove is silently ignored".
    mode_flags = sum(int(x) for x in (remove, bool(from_env), show))
    if mode_flags > 1:
        console.print(
            "[red]--show, --remove, and --from-env are mutually exclusive.[/red]"
        )
        raise typer.Exit(1)

    if show:
        try:
            val = _secrets.get(name)
        except _secrets.SecretMissingError:
            console.print(f"[red]No secret stored as '{name}'[/red]")
            raise typer.Exit(1)
        typer.echo(val)
        return

    if remove:
        if _secrets.delete(name):
            console.print(f"[green]✓[/green] Removed secret [bold]{name}[/bold]")
        else:
            console.print(f"[yellow]No secret stored as '{name}' — nothing to remove[/yellow]")
        return

    if from_env:
        val = os.environ.get(from_env)
        if val is None:
            console.print(f"[red]Environment variable {from_env} is not set[/red]")
            raise typer.Exit(1)
        if _secrets.exists(name) and not force and not _prompt_overwrite(name):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)
        _secrets.set(name, val)
        console.print(f"[green]✓[/green] Secret saved as [bold]{name}[/bold]")
        return

    # Interactive flow: OAuth first (if this name is in the registry), else getpass
    try:
        from hazel.secrets import registry as _oauth_registry
    except ImportError:
        _oauth_registry = None  # type: ignore[assignment]

    if _oauth_registry is not None and _oauth_registry.has_oauth(name):
        if _secrets.exists(name) and not force and not _prompt_overwrite(name):
            console.print("[dim]Aborted.[/dim]")
            raise typer.Exit(0)
        try:
            value = _oauth_registry.run_oauth(name)
        except Exception as e:
            console.print(f"[red]OAuth failed:[/red] {e}")
            raise typer.Exit(1)
        _secrets.set(name, value)
        console.print(f"[green]✓[/green] Secret saved as [bold]{name}[/bold]")
        return

    # Fallback: plain getpass prompt
    if _secrets.exists(name) and not force and not _prompt_overwrite(name):
        console.print("[dim]Aborted.[/dim]")
        raise typer.Exit(0)

    try:
        value = getpass.getpass(f"Paste value for {name}: ")
    except (EOFError, KeyboardInterrupt):
        console.print()
        raise typer.Exit(1)

    if not value:
        console.print("[red]Empty value — not stored[/red]")
        raise typer.Exit(1)

    _secrets.set(name, value)
    console.print(f"[green]✓[/green] Secret saved as [bold]{name}[/bold]")


@secret_app.command("list")
def secret_list() -> None:
    """List stored secret names. Values are never printed."""
    names = _secrets.list_names()
    if not names:
        console.print("[dim]No secrets stored.[/dim]")
        console.print("[dim]Add one with: hazel auth <name>[/dim]")
        return
    for n in names:
        console.print(f"  {n}")
