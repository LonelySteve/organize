from pathlib import Path
from typing import ClassVar

from PIL import Image, ImageSequence
from pillow_heif import register_heif_opener
from pydantic.config import ConfigDict
from pydantic.dataclasses import dataclass

from organize.action import ActionConfig
from organize.output import Output
from organize.resource import Resource
from organize.template import Template, render

from .common.target_path import prepare_target_path

register_heif_opener()


@dataclass(config=ConfigDict(coerce_numbers_to_str=True, extra="forbid"))
class ExtractHeic:
    dest: str = "{path.parent/path.stem}/"
    rename_template: str = "{name} {counter}{extension}"
    autodetect_folder: bool = True

    action_config: ClassVar[ActionConfig] = ActionConfig(
        name="extract_heic", standalone=False, files=True, dirs=False
    )

    def __post_init__(self):
        self._dest = Template.from_string(self.dest)
        self._rename_template = Template.from_string(self.rename_template)

    def pipeline(self, res: Resource, output: Output, simulate: bool):
        assert res.path is not None, "Does not support standalone mode"

        rendered = render(self._dest, res.dict())

        im = Image.open(res.path)
        # 遍历图像中的每一帧，并依次保存为 PNG 文件
        for i, frame in enumerate(ImageSequence.Iterator(im)):
            out_dst = prepare_target_path(
                src_name=(str(i) + ".png"),
                dst=rendered,
                autodetect_folder=self.autodetect_folder,
                simulate=simulate,
            )

            output.msg(
                res=res, msg=f"Image frame {i} extracted to ${out_dst}.", sender=self
            )

            if not simulate:
                frame.save(out_dst)

        res.path = Path(rendered).resolve()
