from pathlib import Path
from typing import ClassVar

from PIL import Image
from pydantic.config import ConfigDict
from pydantic.dataclasses import dataclass

from organize.action import ActionConfig
from organize.output import Output
from organize.resource import Resource
from organize.template import Template

from .common.conflict import ConflictMode, resolve_conflict


def merge_images_to_pdf(image_paths, output_pdf, compression_level=0):
    """
    将多张图片合并到一个 PDF 文件中，并根据压缩等级控制图像质量。

    参数:
        image_paths (list): 图片文件路径列表，例如 ['image1.jpg', 'image2.png']。
        output_pdf (str): 输出的 PDF 文件路径，例如 'output.pdf'。
        compression_level (int): 压缩等级，0 表示无损，1-100 表示有损压缩（1 为最低质量，100 为最高质量）。
    """
    # 打开所有图片并转换为 RGB 模式
    images = [Image.open(path).convert("RGB") for path in image_paths]

    # 根据压缩等级设置保存选项
    if compression_level == 0:
        # 无损压缩：不应用任何压缩，直接保存原始图像
        pdf_options = {}
    else:
        # 有损压缩：使用 JPEG 压缩，调整质量
        # 将 compression_level (1-100) 映射到 Pillow 的 quality 参数 (1-95)
        jpeg_quality = max(1, min(95, 100 - compression_level + 1))
        pdf_options = {"compress": True, "quality": jpeg_quality}

    # 将图片保存为多页 PDF
    images[0].save(output_pdf, save_all=True, append_images=images[1:], **pdf_options)


@dataclass(config=ConfigDict(coerce_numbers_to_str=True, extra="forbid"))
class MakePdf:
    rename_template: str = "{name} {counter}{extension}"
    compression_level: int = 0
    on_conflict: ConflictMode = "rename_new"

    action_config: ClassVar[ActionConfig] = ActionConfig(
        name="make_pdf", standalone=False, files=True, dirs=True
    )

    def __post_init__(self):
        self._rename_template = Template.from_string(self.rename_template)

    def pipeline(self, res: Resource, output: Output, simulate: bool):
        assert res.path is not None, "Does not support standalone mode"

        if res.path.is_file():
            dst = res.path.parent / (res.path.stem + ".pdf")
            src = [res.path]
        elif res.path.is_dir():
            dst = res.path.parent / (res.path.name + ".pdf")
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

        output.msg(res=res, msg=f"Created a PDF file in {dst}.", sender=self)

        res.path = Path(dst).resolve()

        if not simulate:
            merge_images_to_pdf(src, dst, self.compression_level)
