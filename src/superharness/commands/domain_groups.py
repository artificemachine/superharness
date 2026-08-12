"""Click groups that expose existing commands through progressive domains."""

from __future__ import annotations

import click

from superharness.commands.help_catalog import (
    DOMAIN_COMMANDS,
    DOMAIN_ENTRY_POINTS,
    LEGACY_STATE_COMMANDS,
    legacy_state_present,
)


class DomainGroup(click.Group):
    """Read-only view over root commands; it never wraps business callbacks."""

    def __init__(
        self,
        root: click.Group,
        name: str,
        command_map: dict[str, str],
        help_text: str,
    ) -> None:
        super().__init__(name=name, help=help_text)
        self._root = root
        self._command_map = command_map

    def list_commands(self, ctx: click.Context) -> list[str]:
        commands = self._command_map
        if self.name == "state" and not legacy_state_present():
            commands = {
                name: target
                for name, target in commands.items()
                if name not in LEGACY_STATE_COMMANDS
            }
        return sorted(commands)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        canonical_name = self._command_map.get(cmd_name)
        if canonical_name is None:
            return None
        return self._root.commands.get(canonical_name)


def register_domain_groups(root: click.Group) -> None:
    """Register the four progressive discovery groups after root setup."""
    for name, command_map in DOMAIN_COMMANDS.items():
        root.add_command(
            DomainGroup(root, name, command_map, DOMAIN_ENTRY_POINTS[name])
        )
