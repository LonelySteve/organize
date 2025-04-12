# organize/filters/fns.py

import re
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    PrivateAttr,
    model_validator,
)

from organize.filter import FilterConfig
from organize.output.output import Output
from organize.resource import Resource

# Regex to extract tag type and content
TAG_RE = re.compile(r"([CSPLVT])(.*)")
# Regex to validate YYMMDD format
DATE_RE = re.compile(r"^(\d{2})(\d{2})(\d{2})")
# Regex to validate YYWWw format
WEEK_RE = re.compile(r"^\(\\d\{2\}\)\(\\d\{2\}\)w")
# Regex for semantic version V[x.y.z]
SEMVER_RE = re.compile(r"^\[(\d+\.\d+\.\d+)\]$")


def _parse_date(tag_content: str) -> Optional[str]:
    """Parses YYMMDD or YYWWw into YYYY-MM-DD or YYYY-Www format."""
    date_match = DATE_RE.match(tag_content)
    if date_match:
        yy, mm, dd = date_match.groups()
        # Assume 20xx for years 00-99
        year = int(f"20{yy}")
        try:
            # Validate date parts
            datetime(year=year, month=int(mm), day=int(dd))
            return f"{year}-{mm}-{dd}"
        except ValueError:
            return None  # Invalid date

    week_match = WEEK_RE.match(tag_content)
    if week_match:
        yy, ww = week_match.groups()
        year = int(f"20{yy}")
        try:
            # Validate week number (basic check)
            if 1 <= int(ww) <= 53:
                return f"{year}-W{ww}"
        except ValueError:
            pass  # Invalid week number format
    return None


def _parse_filename(filename: Path) -> Dict[str, Any]:
    """Parses a filename according to the draft standard."""
    parts = filename.stem.split(".")
    # main_file_name = parts[0] # We don't need the main name for filtering tags
    tags_part = parts[1:]

    parsed_data = {
        "createTime": None,  # Stores YYYY-MM-DD or YYYY-Www string
        "subject": None,  # Stores string or list of strings
        "page": None,  # Stores integer
        "version": None,  # Stores string (e.g., '1.1.10' or '1')
        "tags": [],  # Stores list of strings
    }

    for part in tags_part:
        match = TAG_RE.match(part)
        if not match:
            continue  # Skip parts that don't match the tag format

        tag_type, tag_content = match.groups()

        try:
            if tag_type == "C":
                parsed_data["createTime"] = _parse_date(tag_content)
            elif tag_type == "S":
                # Keep subjects potentially split by hyphen
                parsed_data["subject"] = (
                    tag_content  # Store as is, user code/match can handle split
                )
            elif tag_type == "P":
                if tag_content.isdigit():
                    parsed_data["page"] = int(tag_content)
            elif tag_type == "V":
                semver_match = SEMVER_RE.match(tag_content)
                if semver_match:
                    parsed_data["version"] = semver_match.group(1)
                elif tag_content.isdigit():
                    parsed_data["version"] = tag_content  # Store simple count as string
            elif tag_type == "T":
                parsed_data["tags"].extend(tag_content.split("-"))
        except Exception:
            # Ignore parsing errors for specific tags, leave as None/default
            pass

    # Clean up empty tags list
    if not parsed_data["tags"]:
        parsed_data["tags"] = None  # Use None if no tags found

    return parsed_data


def _match_single_condition(filter_condition: Dict, parsed_data: Dict) -> bool:
    """Checks if parsed_data matches ALL conditions in filter_condition."""
    for key, expected_value in filter_condition.items():
        actual_value = parsed_data.get(key)

        # If the key doesn't exist in parsed data (or parsing failed -> None),
        # it cannot match a filter condition expecting a value.
        # However, a filter could theoretically check for None (e.g., page: null),
        # but we'll consider None from parsing as non-match for specific value checks.
        # A filter checking for None explicitly would need different handling if required.

        if key == "createTime":
            if actual_value is None or str(actual_value) != str(expected_value):
                return False
        elif key == "subject":
            # Check if expected value is a substring of the actual subject
            if actual_value is None or str(expected_value) not in str(actual_value):
                return False
        elif key == "page":
            # Ensure actual value is not None before comparing
            if actual_value is None or str(actual_value) != str(expected_value):
                return False
        elif key == "version":
            # Direct string comparison
            if actual_value is None or str(actual_value) != str(expected_value):
                return False
        elif key == "tags":
            # 1. Get actual tags (ensure it's a list or None, convert to set)
            actual_tags_list = actual_value
            if actual_tags_list is None:
                actual_tags_list = []
            if not isinstance(actual_tags_list, list):
                return False  # Parsed data must be a list
            actual_tags_set = set(actual_tags_list)

            # 2. Process expected tags (can be string or list of strings)
            required_tags_list: List[str] = []
            if isinstance(expected_value, str):
                if not expected_value:
                    required_tags_list = []
                elif "-" in expected_value:
                    required_tags_list = expected_value.split("-")
                else:
                    required_tags_list = [expected_value]
            elif isinstance(expected_value, list):
                # Ensure all items in the list are strings
                if not all(isinstance(item, str) for item in expected_value):
                    return False  # Invalid format: list must contain only strings
                required_tags_list = expected_value
            else:
                # Invalid format for expected_value (must be str or list)
                return False

            required_tags_set = set(required_tags_list)

            # 3. Perform subset check
            if not required_tags_set.issubset(actual_tags_set):
                return False

        else:
            # Unknown key in filter condition means no match
            return False

    # If all conditions passed
    return True


class FileNamingStandard(BaseModel):
    """
    Filter files based on metadata encoded in the filename according to a
    specified standard (C[date], S[subject], P[page], V[version], T[tags]).

    Filtering can be done using Python code or by specifying exact values/patterns.

    **Python Code Filtering:**
    If the configuration value is a string, it's treated as Python code.
    The code must return a boolean value. It has access to the following variables
    parsed from the filename:
    - `createTime` (str | None): Date 'YYYY-MM-DD' or week 'YYYY-Www'.
    - `subject` (str | None): Subject string (may contain hyphens).
    - `page` (int | None): Page number.
    - `version` (str | None): Version string (e.g., '1.1.10' or '1').
    - `tags` (list[str] | None): List of auxiliary tags.

    Example:
    ```yaml
    filters:
      - fns: "return createTime == '2025-04-12' and '旅行' in (subject or '')"
    ```

    **Object/Array Filtering:**
    - If the configuration is a dictionary, all conditions must match (AND logic).
    - If the configuration is a list of dictionaries, at least one dictionary must match (OR logic).

    Comparison Logic:
    - `createTime`: Exact string match for 'YYYY-MM-DD' or 'YYYY-Www'.
    - `subject`: Checks if the filter value is a substring of the parsed subject.
    - `page`: Exact integer match.
    - `version`: Exact string match.
    - `tags`: Checks if the filter tag string exists in the list of parsed tags.

    Examples:
    ```yaml
    filters:
      - fns:  # AND logic
          createTime: 2025-04-12
          tags: 截图
    ```
    ```yaml
    filters:
      - fns:  # OR logic
          - createTime: 2025-04-12
            tags: 截图
          - page: 3
            subject: Report
    ```

    **Returns:**
    - `{fns.createTime}`
    - `{fns.subject}`
    - `{fns.page}`
    - `{fns.version}`
    - `{fns.tags}`
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    filter_config: ClassVar[FilterConfig] = FilterConfig(
        name="fns",
        files=True,
        dirs=False,
    )

    # --- Fields to store the processed configuration ---
    # These fields will be populated by the dictionary returned from the 'before' validator.
    # They don't need default values here if the validator always provides them.
    mode: Literal["python", "dict", "list"]
    conditions: Union[Dict, List[Dict]]
    code: Optional[str]

    # Private attribute for compiled function cache - this is okay
    _code_func = PrivateAttr(default=None)

    # --- Root Validator (mode='before') ---
    @model_validator(mode="before")
    @classmethod
    def process_raw_config(cls, data: Any) -> Dict[str, Any]:
        """
        Determines the config mode (python, dict, list) based on the input data
        passed by filter_from_dict and returns a dict matching the model fields.
        """
        mode: Literal["python", "dict", "list"]
        conditions: Union[Dict, List[Dict]] = {}
        code: Optional[str] = None

        # `data` is what filter_from_dict passes during initialization.
        if isinstance(data, str):
            # Case: fns: "return True" -> FilterCls(data)
            mode = "python"
            code = data
            if "return" not in code:
                raise ValueError(
                    "Python code string must include a 'return' statement."
                )
        elif isinstance(data, dict):
            # Case: fns: {tags: "a"} -> FilterCls(**data) or sometimes FilterCls(data)
            # We need to handle both possibilities if Pydantic calls this validator
            # even when kwargs are passed. Let's assume `data` is the dict itself.
            mode = "dict"
            conditions = data
            # We could add validation here to ensure keys are valid fns keys if needed
            allowed_keys = {"tags", "createTime", "subject", "page", "version"}
            invalid_keys = set(data.keys()) - allowed_keys
            if invalid_keys:
                raise ValueError(
                    f"Invalid keys in fns filter conditions: {invalid_keys}"
                )

        elif isinstance(data, list):
            # Case: fns: [{tags: "a"}] -> FilterCls(data)
            mode = "list"
            if not all(isinstance(item, dict) for item in data):
                raise ValueError("If config is a list, all items must be dictionaries.")
            conditions = data
        else:
            # This case might occur if filter_from_dict passes kwargs that don't match
            # the simple string/dict/list patterns, or an unexpected type.
            raise ValueError(
                f"Invalid configuration type or structure for 'fns': "
                f"Received type {type(data).__name__}"
            )

        # Return a dictionary matching the model's field names
        return {
            "mode": mode,
            "conditions": conditions,
            "code": code,
        }

    # --- Python Code Execution Logic ---
    def _prepare_python_code(self):
        if self.mode != "python" or self._code_func or not self.code:
            return

        func_name = "__fns_usercode__"
        args = "createTime, subject, page, version, tags"
        code_str = f"def {func_name}({args}):\n"
        # Use self.code now
        code_str += textwrap.indent(self.code, "    ")

        try:
            scope: Dict[str, Any] = {}
            exec(code_str, globals(), scope)
            self._code_func = scope[func_name]
        except Exception as e:
            raise ValueError(f"Error compiling FNS Python code: {e}") from e

    def _execute_python_code(
        self, parsed_data: Dict, output: Output, res: Resource
    ) -> bool:
        if not self._code_func:
            self._prepare_python_code()

        if not self._code_func:
            output.msg(
                res=res,
                msg="FNS Python code function not available.",
                level="error",
                sender=self,  # type: ignore
            )
            return False

        try:
            result = self._code_func(
                createTime=parsed_data.get("createTime"),
                subject=parsed_data.get("subject"),
                page=parsed_data.get("page"),
                version=parsed_data.get("version"),
                tags=parsed_data.get("tags"),
            )
            return bool(result)
        except Exception as e:
            output.msg(
                res=res,
                msg=f"Error executing FNS Python code: {e}",
                level="error",
                sender=self,  # type: ignore
            )
            return False

    # --- Pipeline Method ---
    def pipeline(self, res: Resource, output: Output) -> bool:
        assert res.path is not None, "FNS filter does not support standalone mode."
        if res.is_dir():
            return False

        try:
            parsed_data = _parse_filename(res.path)
            res.vars[self.filter_config.name] = parsed_data
        except Exception as e:
            output.msg(
                res=res,
                msg=f"Error parsing filename '{res.path.name}': {e}",
                level="warn",
                sender=self,  # type: ignore
            )
            return False

        # Use the public fields populated by the validator
        if self.mode == "python":
            return self._execute_python_code(parsed_data, output, res)
        elif self.mode == "dict":
            if not isinstance(self.conditions, dict):
                output.msg(
                    res=res,
                    msg="Internal error: Dict mode selected but conditions not a dict.",
                    level="error",
                    sender=self,  # type: ignore
                )
                return False
            conditions = self.conditions.copy()
            if "page" in conditions and conditions["page"] is not None:
                conditions["page"] = str(conditions["page"])
            return _match_single_condition(conditions, parsed_data)
        elif self.mode == "list":
            if not isinstance(self.conditions, list):
                output.msg(
                    res=res,
                    msg="Internal error: List mode selected but conditions not a list.",
                    level="error",
                    sender=self,  # type: ignore
                )
                return False
            for condition_set in self.conditions:
                current_condition = condition_set.copy()
                if (
                    "page" in current_condition
                    and current_condition["page"] is not None
                ):
                    current_condition["page"] = str(current_condition["page"])
                if _match_single_condition(current_condition, parsed_data):
                    return True
            return False
        else:
            # Should not happen
            output.msg(
                res=res,
                msg=f"Internal error: Unknown config mode '{self.mode}'.",
                level="error",
                sender=self,  # type: ignore
            )
            return False
