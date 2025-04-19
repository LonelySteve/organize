from pathlib import Path
from typing import ClassVar

import otaku_media_info

from organize.filter import FilterConfig
from organize.output import Output
from organize.resource import Resource


class OtakuMediaInfos:
    filter_config: ClassVar[FilterConfig] = FilterConfig(
        name="otaku_mediainfos", files=True, dirs=False
    )

    def parse(self, p: Path):
        return otaku_media_info.parse(p)

    def pipeline(self, res: Resource, output: Output) -> bool:
        assert res.path is not None, "Does not support standalone mode"

        media_infos = self.parse(res.path)

        res.vars[self.filter_config.name] = media_infos

        return True
