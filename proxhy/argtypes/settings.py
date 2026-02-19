from typing import TYPE_CHECKING, Any

from plugins.commands._commands import (  # import directly to avoid circular imports
    CommandArg,
    CommandException,
)
from protocol.datatypes import TextComponent

from ._argtypes import _resolve_in_proxy_chain

if TYPE_CHECKING:
    from plugins.commands._commands import (
        CommandContext,  # import directly to avoid circular imports
    )
    from plugins.settings import Setting, SettingGroup


class SettingPath(CommandArg):
    """
    A validated setting path that resolves to a Setting object.

    This type validates the dot-separated path against the proxy's settings
    and provides tab completion for setting names.

    Attributes:
        path: The full dot-separated path to the setting
        setting: The resolved Setting object
    """

    def __init__(self, path: str, setting: Setting):
        self.path = path
        self.setting = setting

    @classmethod
    def _get_all_setting_paths(cls, group: SettingGroup, prefix: str = "") -> list[str]:
        """Recursively get all setting paths from a SettingGroup."""
        from plugins.settings import Setting, SettingGroup

        paths: list[str] = []

        for attr_name in dir(group):
            if attr_name.startswith("_"):
                continue

            attr = getattr(group, attr_name)
            full_path = f"{prefix}.{attr_name}" if prefix else attr_name

            if isinstance(attr, Setting):
                paths.append(full_path)
            elif isinstance(attr, SettingGroup):
                paths.extend(cls._get_all_setting_paths(attr, full_path))

        return paths

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> SettingPath:
        """
        Convert a setting path string to a SettingPath.

        Raises:
            CommandException: If the path is invalid or doesn't point to a Setting
        """
        from plugins.settings import Setting, SettingGroup

        settings = _resolve_in_proxy_chain(ctx.proxy, "settings")
        if settings is None:
            raise CommandException(
                TextComponent("Settings not available!").color("red")
            )

        parts = value.split(".")
        current: Any = settings
        traversed: list[str] = []

        for part in parts:
            if not hasattr(current, part):
                if isinstance(current, SettingGroup):
                    raise CommandException(
                        TextComponent("Setting group '")
                        .append(
                            TextComponent(".".join(traversed) or "settings").color(
                                "gold"
                            )
                        )
                        .append("' does not have a setting named '")
                        .append(TextComponent(part).color("gold"))
                        .append("'!")
                    )
                elif isinstance(current, Setting):
                    raise CommandException(
                        TextComponent("'")
                        .append(TextComponent(".".join(traversed)).color("gold"))
                        .append("' is a setting, not a group!")
                    )
                else:
                    raise CommandException(
                        TextComponent("Invalid setting path '")
                        .append(TextComponent(value).color("gold"))
                        .append("'!")
                    )

            traversed.append(part)
            current = getattr(current, part)

        if isinstance(current, SettingGroup):
            raise CommandException(
                TextComponent("'")
                .append(TextComponent(value).color("gold"))
                .append("' is a setting group, not a setting!")
            )

        if not isinstance(current, Setting):
            raise CommandException(
                TextComponent("'")
                .append(TextComponent(value).color("gold"))
                .append("' is not a valid setting!")
            )

        return cls(path=value, setting=current)

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        """Suggest setting paths based on partial input."""
        settings = _resolve_in_proxy_chain(ctx.proxy, "settings")
        if settings is None:
            return []

        all_paths = cls._get_all_setting_paths(settings)
        partial_lower = partial.lower()
        return [path for path in all_paths if path.lower().startswith(partial_lower)]


class SettingValue(CommandArg):
    """
    A validated setting value.

    This type uses the command context to validate the value against
    the setting's allowed states when a SettingPath is available.

    Attributes:
        value: The normalized (uppercase) value
        original: The original value as provided by the user
    """

    def __init__(self, value: str):
        self.value = value.upper()
        self.original = value

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> SettingValue:
        """
        Convert and validate the setting value.

        If a SettingPath is available in context, validates that the value
        is one of the setting's allowed states.

        Raises:
            CommandException: If the value is not valid for the setting
        """
        setting_path = await ctx.get_arg(SettingPath)

        if setting_path is not None:
            normalized = value.upper()
            if normalized not in setting_path.setting.states:
                valid_states = ", ".join(setting_path.setting.states.keys())
                raise CommandException(
                    TextComponent("Invalid value '")
                    .append(TextComponent(value).color("gold"))
                    .append("' for setting '")
                    .append(TextComponent(setting_path.path).color("gold"))
                    .append("'. Valid values: ")
                    .append(TextComponent(valid_states).color("green"))
                )

        return cls(value)

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        """
        Suggest setting values based on the setting's allowed states.

        If a SettingPath is available in context, suggests from the setting's
        actual states. Otherwise, suggests common values (ON, OFF).
        """
        setting_path = await ctx.get_arg(SettingPath)

        if setting_path is not None:
            # Suggest from the setting's actual allowed states
            states = list(setting_path.setting.states.keys())
            return [s for s in states if s.lower().startswith(partial.lower())]

        # Fallback to common values
        common = ["ON", "OFF"]
        return [v for v in common if v.lower().startswith(partial.lower())]
