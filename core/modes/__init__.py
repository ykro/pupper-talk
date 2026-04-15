"""Mode registry — maps mode names to Mode subclasses."""

from core.modes.base import Mode

MODE_REGISTRY: dict[str, type] = {}


def create_mode(name: str) -> Mode:
    """Instantiate a Mode by name."""
    if not MODE_REGISTRY:
        register_modes()
    cls = MODE_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown mode: {name!r}. Available: {list(MODE_REGISTRY)}")
    return cls()


def register_modes() -> None:
    """Import and register all modes."""
    from core.modes.live import LiveMode
    from core.modes.quiz import QuizMode
    from core.modes.code import CodeMode
    from core.modes.vision import VisionMode
    from core.modes.rocky import RockyMode
    from core.modes.bumblebee import BumblebeeMode
    from core.modes.sentiment import SentimentMode

    MODE_REGISTRY.update({
        "live": LiveMode,
        "quiz": QuizMode,
        "code": CodeMode,
        "vision": VisionMode,
        "rocky": RockyMode,
        "bumblebee": BumblebeeMode,
        "sentiment": SentimentMode,
    })
