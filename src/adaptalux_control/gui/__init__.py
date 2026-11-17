"""A small window for controlling pods. Needs the ``gui`` extra (PySide6, qasync)."""


def main() -> None:
    from .app import main as run

    run()
