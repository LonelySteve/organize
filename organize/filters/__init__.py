from .created import Created
from .date_added import DateAdded
from .date_lastused import DateLastUsed
from .dircontent import DirContent
from .duplicate import Duplicate
from .empty import Empty
from .exif import Exif
from .extension import Extension
from .filecontent import FileContent
from .fns import FileNamingStandard
from .hash import Hash
from .lastmodified import LastModified
from .macos_tags import MacOSTags
from .mediainfos import MediaInfos
from .mimetype import MimeType
from .name import Name
from .otaku_mediainfos import OtakuMediaInfos
from .python import Python
from .regex import Regex
from .size import Size

ALL = (
    Created,
    DateAdded,
    DateLastUsed,
    Duplicate,
    Empty,
    Exif,
    Extension,
    FileContent,
    Hash,
    LastModified,
    MacOSTags,
    MimeType,
    Name,
    Python,
    Regex,
    Size,
    DirContent,
    MediaInfos,
    FileNamingStandard,
    OtakuMediaInfos,
)
