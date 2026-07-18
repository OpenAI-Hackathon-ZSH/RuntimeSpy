"""Configuration discovery, validation, and initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import tomllib
from typing import Any, Iterable


CONFIG_FILE = ".runtimespy.toml"
DEFAULT_EXCLUDE_PATHS = (
    ".git/**",
    ".hg/**",
    ".svn/**",
    ".tox/**",
    ".nox/**",
    ".venv/**",
    "venv/**",
    "env/**",
    "**/__pycache__/**",
    "**/site-packages/**",
    "**/dist-packages/**",
    "**/node_modules/**",
)


class ConfigError(RuntimeError):
    """Raised when RuntimeSpy configuration is missing or invalid."""


def _strings(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ConfigError(f"{key} must be a string or an array of strings")


@dataclass(frozen=True, slots=True)
class RuntimeSpyConfig:
    """Resolved RuntimeSpy configuration for one target project."""

    project_root: Path
    source: tuple[str, ...]
    include_modules: tuple[str, ...] = ()
    exclude_modules: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = field(default_factory=lambda: DEFAULT_EXCLUDE_PATHS)
    data_file: str = ".runtimespy/runtime.db"

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", self.project_root.resolve())
        if not self.source:
            raise ConfigError("at least one source root is required")
        for source in self.source:
            source_path = (self.project_root / source).resolve()
            if not source_path.exists():
                raise ConfigError(f"source root does not exist: {source}")
            if not source_path.is_dir():
                raise ConfigError(f"source root is not a directory: {source}")

    @property
    def source_roots(self) -> tuple[Path, ...]:
        return tuple((self.project_root / item).resolve() for item in self.source)

    @property
    def database_path(self) -> Path:
        return (self.project_root / self.data_file).resolve()

    @classmethod
    def from_mapping(cls, root: Path, values: dict[str, Any]) -> "RuntimeSpyConfig":
        source = _strings(values.get("source"), "source")
        configured_excludes = _strings(values.get("exclude_paths"), "exclude_paths")
        excludes = tuple(dict.fromkeys((*DEFAULT_EXCLUDE_PATHS, *configured_excludes)))
        data_file = values.get("data_file", ".runtimespy/runtime.db")
        if not isinstance(data_file, str):
            raise ConfigError("data_file must be a string")
        return cls(
            project_root=root,
            source=source,
            include_modules=_strings(values.get("include_modules"), "include_modules"),
            exclude_modules=_strings(values.get("exclude_modules"), "exclude_modules"),
            exclude_paths=excludes,
            data_file=data_file,
        )


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc


def load_config(start: Path | str | None = None) -> RuntimeSpyConfig:
    """Find and load RuntimeSpy config at or above *start*."""

    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for root in (current, *current.parents):
        standalone = root / CONFIG_FILE
        if standalone.is_file():
            values = _read_toml(standalone).get("runtimespy")
            if not isinstance(values, dict):
                raise ConfigError(f"{standalone} must contain a [runtimespy] table")
            return RuntimeSpyConfig.from_mapping(root, values)

        pyproject = root / "pyproject.toml"
        if pyproject.is_file():
            document = _read_toml(pyproject)
            values = document.get("tool", {}).get("runtimespy")
            if isinstance(values, dict):
                return RuntimeSpyConfig.from_mapping(root, values)

    raise ConfigError(
        f"no RuntimeSpy configuration found from {current}; run `runtimespy init`"
    )


def detect_source_roots(root: Path) -> list[str]:
    """Return likely Python source roots, ordered by usefulness."""

    root = root.resolve()
    candidates: list[str] = []
    src = root / "src"
    if src.is_dir() and any(src.rglob("*.py")):
        candidates.append("src")

    for child in sorted(root.iterdir()):
        if (
            child.is_dir()
            and (child / "__init__.py").is_file()
            and child.name not in {"tests", "test"}
        ):
            candidates.append(child.name)

    if any(root.glob("*.py")):
        candidates.append(".")

    return list(dict.fromkeys(candidates))


def choose_source_roots(candidates: list[str]) -> tuple[str, ...]:
    """Interactively choose roots, or use the best detected root when piped."""

    if not candidates:
        raise ConfigError("no Python source directory detected; pass --source PATH")
    if not sys.stdin.isatty():
        return (candidates[0],)

    print("Detected Python source directories:\n")
    for index, candidate in enumerate(candidates, start=1):
        print(f"  [{index}] {candidate}")
    print()
    answer = input("Select source directories (comma separated) [1]: ").strip() or "1"
    selected: list[str] = []
    for raw in answer.split(","):
        try:
            index = int(raw.strip())
        except ValueError as exc:
            raise ConfigError(f"invalid selection: {raw!r}") from exc
        if not 1 <= index <= len(candidates):
            raise ConfigError(f"selection is out of range: {index}")
        selected.append(candidates[index - 1])
    return tuple(dict.fromkeys(selected))


def _toml_array(items: Iterable[str]) -> str:
    return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in items) + "]"


def write_config(config: RuntimeSpyConfig, *, force: bool = False) -> Path:
    """Write a standalone RuntimeSpy configuration file."""

    destination = config.project_root / CONFIG_FILE
    if destination.exists() and not force:
        raise ConfigError(f"{destination} already exists; use --force to replace it")
    custom_excludes = [
        pattern for pattern in config.exclude_paths if pattern not in DEFAULT_EXCLUDE_PATHS
    ]
    document = "\n".join(
        (
            "[runtimespy]",
            f"source = {_toml_array(config.source)}",
            f"include_modules = {_toml_array(config.include_modules)}",
            f"exclude_modules = {_toml_array(config.exclude_modules)}",
            f"exclude_paths = {_toml_array(custom_excludes)}",
            f"data_file = {json.dumps(config.data_file)}",
            "",
        )
    )
    destination.write_text(document, encoding="utf-8")
    return destination

