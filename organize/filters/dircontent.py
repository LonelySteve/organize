from pathlib import Path
from typing import ClassVar

from pydantic import field_validator
from pydantic.config import ConfigDict
from pydantic.dataclasses import dataclass

from organize.filter import FilterConfig
from organize.output import Output
from organize.resource import Resource


class BaseDirSet:
    def __init__(self):
        self._base_dirs: list[Path] = []

    def __iter__(self):
        return iter(self._base_dirs)

    def add(self, path: Path) -> None:
        for i, base_dir in enumerate(self._base_dirs):
            try:
                path.relative_to(base_dir)
                return  # base_dir is parent of path
            except ValueError:
                try:
                    base_dir.relative_to(path)
                    self._base_dirs[i] = path  # path is parent of base_dir
                    return
                except ValueError:
                    continue
        self._base_dirs.append(path)

    def has(self, path: Path):
        return any(p == path for p in self._base_dirs)


ALLOWED_MODES = {"only_files", "only_dirs", "not_empty", "empty", "file_dirs"}


@dataclass(config=ConfigDict(extra="forbid"))
class DirContent:
    filter_config: ClassVar[FilterConfig] = FilterConfig(
        name="dircontent",
        files=False,
        dirs=True,
    )

    mode: str = "file_dirs"  # only_files/only_dirs/not_empty/empty/file_dirs
    base_file_dirs: bool = False

    def __post_init__(self):
        self._base_dir_sets = BaseDirSet()

    @field_validator("mode")
    def validate_mode(cls, value: str) -> str:
        if value not in ALLOWED_MODES:
            raise ValueError(f"mode must be one of {ALLOWED_MODES}")
        return value

    def pipeline(self, res: Resource, output: Output) -> bool:
        assert res.path is not None, "Does not support standalone mode"

        if self.mode == "file_dirs":
            has_file = False
            has_dir = False
            for child in res.path.iterdir():
                if child.is_file():
                    has_file = True
                if child.is_dir():
                    has_dir = True
                if has_file and has_dir:
                    if self.base_file_dirs:
                        self._base_dir_sets.add(res.path)
                        return self._base_dir_sets.has(res.path)

                    return True
            return False

        if self.mode == "only_files":
            return all(child.is_file() for child in res.path.iterdir())

        if self.mode == "only_dirs":
            return all(child.is_dir() for child in res.path.iterdir())

        if self.mode == "empty":
            return next(res.path.iterdir(), None) is None

        if self.mode == "not_empty":
            return next(res.path.iterdir(), None) is not None

        return True
