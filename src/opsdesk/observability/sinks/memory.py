"""Keep events in a list. Used by tests now; M17 builds ``AgentResult`` from this list."""

from opsdesk.observability.events import Event, EventKind


class MemorySink:
    def __init__(self, name: str = "memory") -> None:
        self._name = name
        self.events: list[Event] = []

    @property
    def name(self) -> str:
        return self._name

    async def handle(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> list[EventKind]:
        """Event kinds in delivery order: handy for assertions."""
        return [e.kind for e in self.events]
