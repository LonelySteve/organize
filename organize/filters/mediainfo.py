from pathlib import Path
from typing import ClassVar, Literal

from pydantic.config import ConfigDict
from pydantic.dataclasses import dataclass
from pymediainfo import MediaInfo as PyMediaInfo

from organize.filter import FilterConfig
from organize.output import Output
from organize.resource import Resource


@dataclass(config=ConfigDict(extra="forbid"))
class MediaInfo:
    media_infos: (
        Literal["image_tracks"] | Literal["audio_tracks"] | Literal["video_tracks"]
    ) | None = None

    library_file: str | None = None
    cover_data: bool = False
    encoding_errors: str = "replace"
    parse_speed: float = 0.5
    full: bool = True
    legacy_stream_display: bool = False
    mediainfo_options: dict[str, str] | None = None
    buffer_size: int | None = 64 * 1024

    filter_config: ClassVar[FilterConfig] = FilterConfig(
        name="mediainfo", files=True, dirs=False
    )

    def parse(self, p: Path):
        return PyMediaInfo.parse(
            p,
            library_file=self.library_file,
            cover_data=self.cover_data,
            encoding_errors=self.encoding_errors,
            parse_speed=self.parse_speed,
            full=self.full,
            legacy_stream_display=self.legacy_stream_display,
            mediainfo_options=self.mediainfo_options,
            buffer_size=self.buffer_size,
        )

    def matches(self, media_info: PyMediaInfo) -> bool:
        general_track = next(iter(media_info.general_tracks), None)

        if general_track is None or general_track.fileextension_invalid:
            return False

        if self.media_infos is None:
            return True

        if "image_tracks" == self.media_infos and media_info.image_tracks:
            return True

        if "audio_tracks" == self.media_infos and media_info.audio_tracks:
            return True

        if "video_tracks" == self.media_infos and media_info.video_tracks:
            return True

        return False

    def pipeline(self, res: Resource, output: Output) -> bool:
        assert res.path is not None, "Does not support standalone mode"

        media_info = self.parse(res.path)
        res.vars[self.filter_config.name] = media_info

        return self.matches(media_info)
