"""Where the engine's own files are: prompts, the default config, schemas, fonts, the job template.

They ship inside the package (ADR 0027), so an installed copy finds them beside its code, on any
machine, with no checkout. A source checkout keeps them at the repo's root, where people edit them,
and the wheel's build copies them into `kalainova/_data`. Every reader asks here, so both run the
same code; `just ci-wheel` proves the installed side on a built wheel in an empty folder.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

_CHECKOUT = Path(__file__).resolve().parents[2]


def _packaged() -> Path:
    return Path(str(files("kalainova").joinpath("_data"))).resolve()


def root() -> Path:
    """The folder holding prompts/, config/, schemas/, fonts/ and jobs/_template."""
    packaged = _packaged()
    return packaged if packaged.is_dir() else _CHECKOUT


def path(*parts: str) -> Path:
    """One of the engine's own files or folders."""
    return root().joinpath(*parts)


def in_checkout() -> bool:
    """Whether this engine runs from a source checkout, where git can say which commit it is."""
    return root() == _CHECKOUT and (_CHECKOUT / "pyproject.toml").is_file()
