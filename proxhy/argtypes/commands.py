from core.command import CommandArg, CommandContext, CommandGroup, CommandRegistry


class HelpPath(CommandArg):
    """Suggests command names and subcommand paths."""

    def __init__(self, value: str):
        self.value = value

    @classmethod
    async def convert(cls, ctx: CommandContext, value: str) -> HelpPath:
        return cls(value)

    @classmethod
    async def suggest(cls, ctx: CommandContext, partial: str) -> list[str]:
        registry: CommandRegistry = ctx.proxy.command_registry
        prior = ctx.raw_args[: ctx.param_index]

        if not prior:
            return [
                name
                for name in registry.command_names()
                if name.startswith(partial.lower())
            ]

        root = registry.get(prior[0].lower())
        if not isinstance(root, CommandGroup):
            return []

        group = root
        for segment in prior[1:]:
            lower = segment.lower()
            if lower in group._subgroups:
                group = group._subgroups[lower]
            else:
                return []

        options: list[str] = []
        seen: set[int] = set()
        for cmd in group._subcommands.values():
            if id(cmd) not in seen:
                seen.add(id(cmd))
                if cmd.name.startswith(partial.lower()):
                    options.append(cmd.name)
        for grp in group._subgroups.values():
            if id(grp) not in seen:
                seen.add(id(grp))
                if grp.name.startswith(partial.lower()):
                    options.append(grp.name)
        return options
