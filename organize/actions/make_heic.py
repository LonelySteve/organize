from pathlib import Path
from typing import ClassVar

from PIL import Image
from pillow_heif import register_heif_opener
from pydantic.config import ConfigDict
from pydantic.dataclasses import dataclass

from organize.action import ActionConfig
from organize.output import Output
from organize.resource import Resource
from organize.template import Template

from .common.conflict import ConflictMode, resolve_conflict

register_heif_opener()


@dataclass(config=ConfigDict(coerce_numbers_to_str=True, extra="forbid"))
class MakeHeic:
    rename_template: str = "{name} {counter}{extension}"
    on_conflict: ConflictMode = "rename_new"

    action_config: ClassVar[ActionConfig] = ActionConfig(
        name="make_heic", standalone=False, files=True, dirs=True
    )

    def __post_init__(self):
        self._rename_template = Template.from_string(self.rename_template)

    def pipeline(self, res: Resource, output: Output, simulate: bool):
        assert res.path is not None, "Does not support standalone mode"

        if res.path.is_file():
            dst = res.path.parent / (res.path.stem + ".heic")
            src = [res.path]
        elif res.path.is_dir():
            dst = res.path.parent / (res.path.name + ".heic")
            src = res.path.iterdir()
        else:
            raise ValueError(f"{res.path} is not a valid file or directory")

        skip_action, dst = resolve_conflict(
            dst=dst,
            res=res,
            conflict_mode=self.on_conflict,
            rename_template=self._rename_template,
            simulate=simulate,
            output=output,
        )
        if skip_action:
            return

        output.msg(res=res, msg=f"Created a HEIC image file in {dst}.", sender=self)

        res.path = Path(dst).resolve()

        if not simulate:
            primary_image, *additional_images = (Image.open(file) for file in src)
            primary_image.save(dst, save_all=True, append_images=additional_images)
