from pathlib import Path
from typing import Dict, List, Literal, Optional, Set, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from organize.logger import logger

from .action import Action, GroupAction, action_pipeline
from .filter import (
    Filter,
    FilterMode,
    GroupFilter,
    Not,
    filter_pipeline,
    group_filter_pipeline,
)
from .location import Location
from .output import Output
from .registry import action_by_name, filter_by_name
from .resource import Resource
from .template import render
from .utils import ReportSummary, classify_by_type
from .validators import FlatList, flatten
from .walker import Walker


def action_from_dict(d: Dict) -> Action:
    """
    :param d:
        A dict in the forms of
        { "action_name": None }
        { "action_name": "value" }
        { "action_name": {"param": "value"} }
    :returns:
        An instantiated action.
    """
    if not len(d.keys()) == 1:
        raise ValueError("Action definition must have only one key")
    name, value = next(iter(d.items()))
    ActionCls = action_by_name(name)
    if value is None:
        return ActionCls()
    elif isinstance(value, dict):
        return ActionCls(**value)
    else:
        return ActionCls(value)


def group_action_from_dict(name: str, d: Dict | List) -> GroupAction:
    if isinstance(d, List):
        d = {"actions": d}

    if not len(d.keys()) == 1:
        raise ValueError("Group action definition must have only one key")
    actions = transform_instances(d["actions"], action_from_dict)
    return GroupAction(
        name,
        actions=actions,
    )


def filter_from_dict(d: Dict) -> Filter:
    """
    :param d:
        A dict in the forms of ("not" prefix is optional)
        { "[not] filter_name": None }
        { "[not] filter_name": "value" }
        { "[not] filter_name": {"param": "value"} }
    :returns: An instantiated filter.
    """
    if not len(d.keys()) == 1:
        raise ValueError("Filter definition must have a single key")
    name, value = next(iter(d.items()))

    # check for "not" in filter key
    invert_filter = False
    if name.startswith("not "):
        name = name[4:]
        invert_filter = True

    FilterCls = filter_by_name(name)

    # instantiate
    if value is None:
        inst = FilterCls()
    elif isinstance(value, dict):
        inst = FilterCls(**value)
    else:
        inst = FilterCls(value)

    return Not(inst) if invert_filter else inst


def group_filter_from_dict(name: str, d: Dict) -> GroupFilter:
    filters = transform_instances(d.get("filters", []), filter_from_dict)
    original_depend_on = set(d.get("depend_on", []))

    depend_on = set()
    depend_on_inverted = set()
    for dep in original_depend_on:
        if dep.startswith("not "):
            dep = dep[4:]
            depend_on_inverted.add(dep)
        depend_on.add(dep)

    return GroupFilter(
        name,
        filters=filters,
        filter_mode=d.get("filter_mode", "all"),
        depend_on=depend_on,
        depend_on_inverted=depend_on_inverted,
    )


def transform_instances(instances, instance_from_dict):
    result = []
    instances = flatten(instances)
    for x in instances:
        # make sure "- extension" becomes "- extension:"
        if isinstance(x, str):
            x = {x: None}
        # create instance from dict
        if isinstance(x, dict):
            result.append(instance_from_dict(x))
        # other instances
        else:
            result.append(x)
    return result


def transform_instances_dict(instances: Dict, instance_from_dict):
    return [instance_from_dict(k, v) for k, v in instances.items()]


class Rule(BaseModel):
    name: Optional[str] = None
    enabled: bool = True
    targets: Literal["files", "dirs"] = "files"
    locations: FlatList[Location] = Field(default_factory=list)
    subfolders: bool = False
    tags: Set[str] = Field(default_factory=set)
    filters: Union[List[Filter], List[GroupFilter]] = Field(default_factory=list)
    filter_mode: FilterMode = "all"
    actions: Union[List[Action], List[GroupAction]] = Field(..., min_length=1)

    model_config = ConfigDict(
        extra="forbid",
        arbitrary_types_allowed=True,
    )

    @field_validator("locations", mode="before")
    def validate_locations(cls, locations):
        if locations is None:
            return []
        locations = flatten(locations)
        result = []
        for x in locations:
            if isinstance(x, str):
                x = {"path": x}
            result.append(x)
        return result

    @field_validator("filters", mode="before")
    def validate_filters(cls, filters):
        if isinstance(filters, dict):
            return transform_instances_dict(filters, group_filter_from_dict)
        else:
            return transform_instances(filters, filter_from_dict)

    @field_validator("actions", mode="before")
    def validate_actions(cls, actions):
        if isinstance(actions, dict):
            return transform_instances_dict(actions, group_action_from_dict)
        else:
            return transform_instances(actions, action_from_dict)

    @model_validator(mode="after")
    def validate_target_support(self) -> "Rule":
        all_filters = []
        if isinstance(
            self.filters, list
        ):  # Result of validation can be List[Filter] or List[GroupFilter]
            for f in self.filters:
                if isinstance(f, GroupFilter):
                    all_filters.extend(f.filters)
                else:
                    all_filters.append(f)

        all_actions = []
        if isinstance(
            self.actions, list
        ):  # Result of validation can be List[Action] or List[GroupAction]
            for a in self.actions:
                if isinstance(a, GroupAction):
                    all_actions.extend(a.actions)
                else:
                    all_actions.append(a)

        # standalone mode
        if not self.locations:
            if self.filters:
                raise ValueError("Filters are present but no locations are given!")
            for action in all_actions:
                if not action.action_config.standalone:
                    raise ValueError(
                        f'Action "{action.action_config.name}" does not support '
                        "standalone mode (no rule.locations specified)."
                    )

        # targets dirs
        if self.targets == "dirs":
            for filter in all_filters:
                if not filter.filter_config.dirs:
                    raise ValueError(
                        f'Filter "{filter.filter_config.name}" does not support '
                        "folders (targets: dirs)"
                    )
            for action in all_actions:
                if not action.action_config.dirs:
                    raise ValueError(
                        f'Action "{action.action_config.name}" does not support '
                        "folders (targets: dirs)"
                    )
        # targets files
        elif self.targets == "files":
            for filter in all_filters:
                if not filter.filter_config.files:
                    raise ValueError(
                        f'Filter "{filter.filter_config.name}" does not support '
                        "files (targets: files)"
                    )
            for action in all_actions:
                if not action.action_config.files:
                    raise ValueError(
                        f'Action "{action.action_config.name}" does not support '
                        "files (targets: files)"
                    )
        else:
            raise ValueError(f"Unknown target: {self.targets}")

        return self

    def walk(self, rule_nr: int = 0):
        for location in self.locations:
            # instantiate the filesystem walker
            exclude_files = location.system_exclude_files | location.exclude_files
            exclude_dirs = location.system_exclude_dirs | location.exclude_dirs
            if location.max_depth == "inherit":
                max_depth = None if self.subfolders else 0
            else:
                max_depth = location.max_depth

            walker = Walker(
                min_depth=location.min_depth,
                max_depth=max_depth,
                filter_dirs=location.filter_dirs,
                filter_files=location.filter,
                method="breadth",
                exclude_dirs=exclude_dirs,
                exclude_files=exclude_files,
            )

            # whether to walk dirs or files
            _walk_funcs = {
                "files": walker.files,
                "dirs": walker.dirs,
            }
            for loc_path in location.path:
                expanded_path = render(loc_path)
                for path in _walk_funcs[self.targets](expanded_path):
                    yield Resource(
                        path=Path(path),
                        basedir=Path(expanded_path),
                        rule=self,
                        rule_nr=rule_nr,
                    )

    def execute(
        self, *, simulate: bool, output: Output, rule_nr: int = 0
    ) -> ReportSummary:
        if not self.enabled:
            return ReportSummary()

        group_filters, filters = classify_by_type(self.filters, [GroupFilter, Filter])
        group_actions, actions = classify_by_type(self.actions, [GroupAction, Action])

        # standalone mode
        if not self.locations:
            res = Resource(path=None, rule_nr=rule_nr)
            try:
                for action in action_pipeline(
                    actions=actions,
                    res=res,
                    simulate=simulate,
                    output=output,
                ):
                    pass
                return ReportSummary(success=1)
            except Exception as e:
                output.msg(
                    res=res,
                    msg=str(e),
                    level="error",
                    sender=action,
                )
                logger.exception(e)
                return ReportSummary(errors=1)

        # normal mode
        summary = ReportSummary()
        skip_pathes: Set[Path] = set()
        for res in self.walk(rule_nr=rule_nr):
            if res.path in skip_pathes:
                continue

            if group_filters:
                result = group_filter_pipeline(
                    filters=group_filters,
                    res=res,
                    output=output,
                )
                matched_group_actions = list(
                    filter(lambda a: a.name in result, group_actions)
                )
                try:
                    for action in action_pipeline(
                        actions=matched_group_actions,
                        res=res,
                        simulate=simulate,
                        output=output,
                    ):
                        pass
                    skip_pathes = skip_pathes.union(res.walker_skip_pathes)
                    summary.success += 1
                except Exception as e:
                    output.msg(
                        res=res,
                        msg=str(e),
                        level="error",
                        sender=action,
                    )
                    logger.exception(e)
                    summary.errors += 1

            result = filter_pipeline(
                filters=filters,
                filter_mode=self.filter_mode,
                res=res,
                output=output,
            )
            if result and self.actions:
                try:
                    for action in action_pipeline(
                        actions=actions,
                        res=res,
                        simulate=simulate,
                        output=output,
                    ):
                        pass
                    skip_pathes = skip_pathes.union(res.walker_skip_pathes)
                    summary.success += 1
                except Exception as e:
                    output.msg(
                        res=res,
                        msg=str(e),
                        level="error",
                        sender=action,
                    )
                    logger.exception(e)
                    summary.errors += 1
        return summary
