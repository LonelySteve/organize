from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Dict,
    Iterable,
    List,
    Literal,
    NamedTuple,
    Protocol,
    Set,
    runtime_checkable,
)

from pydantic import ConfigDict, Field
from pydantic.dataclasses import dataclass

from organize.logger import logger

if TYPE_CHECKING:
    from .output import Output
    from .resource import Resource


FilterMode = Literal["all", "any", "none"]


class FilterConfig(NamedTuple):
    name: str
    files: bool
    dirs: bool


@runtime_checkable
class HasFilterConfig(Protocol):
    filter_config: FilterConfig


class HasFilterPipeline(Protocol):
    def pipeline(self, res: Resource, output: Output) -> bool: ...  # pragma: no cover


@runtime_checkable
class Filter(HasFilterPipeline, HasFilterConfig, Protocol):
    def __init__(self, *args, **kwargs) -> None:
        # allow any amount of args / kwargs for BaseModel and dataclasses.
        ...  # pragma: no cover


DependOnMode = Literal["and", "or"]


@dataclass(config=ConfigDict(extra="forbid", arbitrary_types_allowed=True))
class GroupFilter(HasFilterPipeline):
    name: str
    filters: List[Filter] = Field(default_factory=list)
    filter_mode: FilterMode = "all"
    depend_on: Set[str] = Field(default_factory=set)
    depend_on_mode: DependOnMode = "and"
    depend_on_inverted: Set[str] = Field(default_factory=set)

    def pipeline(self, res: Resource, output: Output) -> bool:
        return filter_pipeline(self.filters, self.filter_mode, res, output)

    @classmethod
    def is_cyclic(cls, node_map: Iterable["GroupFilter"]) -> bool:
        """
        使用标准 Kahn 算法判断图中是否存在环（忽略 match 条件）。
        """
        # 建立节点映射
        nodes: Dict[str, "GroupFilter"] = {node.name: node for node in node_map}
        in_degree: Dict[str, int] = {name: 0 for name in nodes}
        children: Dict[str, List[str]] = {name: [] for name in nodes}

        for node in nodes.values():
            for dep in node.depend_on:
                if dep in nodes:
                    in_degree[node.name] += 1
                    children[dep].append(node.name)

        # Kahn 算法：收集所有入度为 0 的节点，然后逐步删除依赖边
        queue: List[str] = [name for name, deg in in_degree.items() if deg == 0]
        visited_count = 0

        while queue:
            current = queue.pop(0)
            visited_count += 1
            for child in children[current]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return visited_count != len(nodes)

    @classmethod
    def match(
        cls, node_map: Iterable["GroupFilter"], res: Resource, output: Output
    ) -> List[str] | None:
        """
        从所有入度为 0 的节点开始，每一层只从匹配的节点出发向下广度遍历。
        若某层没有匹配节点，则停止遍历，返回已匹配的节点列表。
        如果图存在环（无论节点是否匹配），则返回 None。
        """
        # 先检测整个图是否有环
        if cls.is_cyclic(node_map):
            return None

        # 建立节点名称 -> 节点对象的映射
        nodes: Dict[str, "GroupFilter"] = {node.name: node for node in node_map}

        # 初始化每个节点的入度和反向依赖（children）
        in_degree: Dict[str, int] = {name: 0 for name in nodes}
        children: Dict[str, List[str]] = {name: [] for name in nodes}

        for node in nodes.values():
            for dep in node.depend_on:
                if dep in nodes:
                    in_degree[node.name] += 1
                    children[dep].append(node.name)

        result: List[str] = []
        # 初始起始节点：所有入度为 0 的节点（无依赖节点）
        current_round: List[str] = [name for name, deg in in_degree.items() if deg == 0]

        # 每一轮只从匹配的起始节点出发继续向下遍历
        while current_round:
            next_round: List[str] = []
            round_matched: List[str] = []
            for name in current_round:
                node = nodes[name]
                matched = node.pipeline(res, output)

                if matched:
                    round_matched.append(name)

                for child in children[name]:
                    child_node = nodes[child]

                    if matched ^ (name in child_node.depend_on_inverted):
                        in_degree[child] -= 1
                        if child_node.depend_on_mode == "or" or in_degree[child] == 0:
                            next_round.append(child)

                # 如果当前节点不匹配，则其后继不被考虑
            if round_matched:
                result.extend(round_matched)

            current_round = next_round

        return result


class Not:
    def __init__(self, filter: Filter):
        self.filter = filter
        self.filter_config = self.filter.filter_config

    def pipeline(self, res: Resource, output: Output) -> bool:
        return not self.filter.pipeline(res=res, output=output)

    def __repr__(self):
        return f"Not({self.filter})"


class All:
    def __init__(self, *filters: Filter):
        self.filters = filters

    def pipeline(self, res: Resource, output: Output) -> bool:
        for filter in self.filters:
            try:
                match = filter.pipeline(res, output=output)
                if not match:
                    return False
            except Exception as e:
                output.msg(res=res, level="error", msg=str(e), sender=filter)
                logger.exception(e)
                return False
        return True


class Any:
    def __init__(self, *filters: Filter):
        self.filters = filters

    def pipeline(self, res: Resource, output: Output) -> bool:
        result = False
        for filter in self.filters:
            try:
                match = filter.pipeline(res, output=output)
                if match:
                    result = True
            except Exception as e:
                output.msg(res=res, level="error", msg=str(e), sender=filter)
                logger.exception(e)
        return result


def filter_pipeline(
    filters: Iterable[Filter],
    filter_mode: FilterMode,
    res: Resource,
    output: Output,
) -> bool:
    collection: HasFilterPipeline
    if filter_mode == "all":
        collection = All(*filters)
    elif filter_mode == "any":
        collection = Any(*filters)
    elif filter_mode == "none":
        collection = All(*[Not(x) for x in filters])
    else:
        raise ValueError(f"Unknown filter mode {filter_mode}")
    return collection.pipeline(res, output=output)


def group_filter_pipeline(
    filters: Iterable[GroupFilter],
    res: Resource,
    output: Output,
):
    """
    过滤器的管道函数，返回匹配的过滤器名称列表。
    """
    # 先检测整个图是否有环
    if GroupFilter.is_cyclic(filters):
        raise ValueError("Cyclic dependency detected in filters.")

    # 进行匹配
    return GroupFilter.match(filters, res=res, output=output)
