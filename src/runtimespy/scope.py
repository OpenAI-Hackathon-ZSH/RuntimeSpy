"""Source-root and module filtering."""

from __future__ import annotations

from dataclasses import dataclass
from fnmatch import fnmatchcase
import os
from pathlib import Path

from .config import RuntimeSpyConfig


PRUNED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "dist-packages",
    "node_modules",
    "site-packages",
    "venv",
}


@dataclass(frozen=True, slots=True)
class ScopeDecision:
    path: Path
    relative_path: str
    module: str
    included: bool
    reason: str


def _module_matches(module: str, pattern: str) -> bool:
    if not any(character in pattern for character in "*?["):
        return module == pattern or module.startswith(f"{pattern}.")
    return fnmatchcase(module, pattern)


def _path_matches(relative_path: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/").lstrip("./")
    candidates = (relative_path, f"/{relative_path}")
    if any(fnmatchcase(candidate, normalized) for candidate in candidates):
        return True
    if normalized.startswith("**/"):
        return fnmatchcase(relative_path, normalized[3:])
    return False


class ScopeMatcher:
    """Make deterministic include/exclude decisions for target source files."""

    def __init__(self, config: RuntimeSpyConfig):
        self.config = config
        self._decision_cache: dict[Path, ScopeDecision] = {}

    def _source_root_for(self, path: Path) -> Path | None:
        for root in self.config.source_roots:
            if path.is_relative_to(root):
                return root
        return None

    def _relative_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.config.project_root).as_posix()
        except ValueError:
            return Path(os.path.relpath(path, self.config.project_root)).as_posix()

    @staticmethod
    def _module_for(path: Path, source_root: Path) -> str:
        relative = path.relative_to(source_root).with_suffix("")
        parts = list(relative.parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if (source_root / "__init__.py").is_file():
            parts.insert(0, source_root.name)
        return ".".join(parts) or source_root.name

    def decide(self, path: Path | str) -> ScopeDecision:
        raw = Path(path)
        if not raw.is_absolute():
            raw = self.config.project_root / raw
        resolved = raw.resolve()
        cached = self._decision_cache.get(resolved)
        if cached is not None:
            return cached

        relative = self._relative_path(resolved)
        source_root = self._source_root_for(resolved)
        if source_root is None:
            decision = ScopeDecision(resolved, relative, "", False, "outside source roots")
        elif resolved.suffix != ".py":
            decision = ScopeDecision(resolved, relative, "", False, "not a Python source file")
        else:
            module = self._module_for(resolved, source_root)
            include_rules = self.config.include_modules
            if include_rules and not any(
                _module_matches(module, pattern) for pattern in include_rules
            ):
                decision = ScopeDecision(
                    resolved, relative, module, False, "did not match include_modules"
                )
            else:
                excluded_module = next(
                    (
                        pattern
                        for pattern in self.config.exclude_modules
                        if _module_matches(module, pattern)
                    ),
                    None,
                )
                excluded_path = next(
                    (
                        pattern
                        for pattern in self.config.exclude_paths
                        if _path_matches(relative, pattern)
                    ),
                    None,
                )
                if excluded_module:
                    decision = ScopeDecision(
                        resolved,
                        relative,
                        module,
                        False,
                        f"matched exclude module {excluded_module!r}",
                    )
                elif excluded_path:
                    decision = ScopeDecision(
                        resolved,
                        relative,
                        module,
                        False,
                        f"matched exclude path {excluded_path!r}",
                    )
                else:
                    decision = ScopeDecision(
                        resolved, relative, module, True, "inside configured scope"
                    )

        self._decision_cache[resolved] = decision
        return decision

    def discover(self) -> list[ScopeDecision]:
        """Discover Python files below source roots without entering dependency trees."""

        discovered: dict[Path, ScopeDecision] = {}
        for root in self.config.source_roots:
            for directory, directory_names, filenames in os.walk(root):
                directory_names[:] = [
                    name for name in directory_names if name not in PRUNED_DIRECTORIES
                ]
                for filename in filenames:
                    if not filename.endswith(".py"):
                        continue
                    decision = self.decide(Path(directory) / filename)
                    discovered[decision.path] = decision
        return sorted(discovered.values(), key=lambda item: item.relative_path)

    def find_module(self, module: str) -> ScopeDecision | None:
        for decision in self.discover():
            if decision.module == module:
                return decision
        return None
