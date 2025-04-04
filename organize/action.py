from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    ClassVar,
    Iterable,
    List,
    NamedTuple,
    Protocol,
    Union,
    runtime_checkable,
)

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

if TYPE_CHECKING:
    from .output import Output
    from .resource import Resource


class ActionConfig(NamedTuple):
    name: str
    standalone: bool
    files: bool
    dirs: bool


@runtime_checkable
class HasActionConfig(Protocol):
    action_config: ClassVar[ActionConfig]


class HasActionPipeline(Protocol):
    def pipeline(self, res: Resource, output: Output, simulate: bool): ...


@runtime_checkable
class Action(HasActionConfig, HasActionPipeline, Protocol):
    def __init__(self, *args, **kwargs) -> None:
        # allow any amount of args / kwargs for BaseModel and dataclasses.
        ...


def action_pipeline(
    actions: Union[Iterable[Action], Iterable[GroupAction]],
    res: Resource,
    simulate: bool,
    output: Output,
) -> Iterable[Union[Action, GroupAction]]:
    for action in actions:
        try:
            yield action
            action.pipeline(res=res, simulate=simulate, output=output)
        except StopIteration:
            break


@dataclass(config=ConfigDict(extra="forbid", arbitrary_types_allowed=True))
class GroupAction:
    name: str
    actions: List[Action] = Field(default_factory=list)

    def pipeline(self, res: Resource, output: Output, simulate: bool) -> None:
        for action in action_pipeline(
            actions=self.actions, res=res, simulate=simulate, output=output
        ):
            pass
