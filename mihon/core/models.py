"""
Data models for Mihon Linux.
"""
from dataclasses import dataclass, field
from typing import Optional, List
from enum import Enum


class ReadingStatus(Enum):
    NONE = "none"
    READING = "reading"
    COMPLETED = "completed"
    ON_HOLD = "on_hold"
    DROPPED = "dropped"
    PLAN_TO_READ = "plan_to_read"


class ReadingDirection(Enum):
    LTR = "ltr"          # Left to right (Western)
    RTL = "rtl"          # Right to left (Manga)
    VERTICAL = "vertical"  # Vertical scroll
    WEBTOON = "webtoon"  # Continuous vertical (webtoon)


class DownloadStatus(Enum):
    NOT_DOWNLOADED = "not_downloaded"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    ERROR = "error"
    QUEUED = "queued"


@dataclass
class Manga:
    id: Optional[int] = None
    source_id: str = ""
    source_manga_id: str = ""
    title: str = ""
    alt_titles: List[str] = field(default_factory=list)
    author: str = ""
    artist: str = ""
    description: str = ""
    genres: List[str] = field(default_factory=list)
    status: str = ""           # ongoing, completed, hiatus, cancelled
    cover_url: str = ""
    url: str = ""
    in_library: bool = False
    reading_status: ReadingStatus = ReadingStatus.NONE
    unread_count: int = 0
    chapter_count: int = 0
    last_read_at: Optional[float] = None
    added_at: Optional[float] = None
    updated_at: Optional[float] = None
    category_ids: List[int] = field(default_factory=list)
    cover_local_path: Optional[str] = None
    score: float = 0.0
    year: Optional[int] = None
    content_rating: str = "safe"


@dataclass
class Chapter:
    id: Optional[int] = None
    manga_id: int = 0
    source_chapter_id: str = ""
    title: str = ""
    chapter_number: float = -1.0
    volume_number: Optional[float] = None
    scanlator: str = ""
    uploaded_at: Optional[float] = None
    fetched_at: Optional[float] = None
    read: bool = False
    last_page_read: int = 0
    page_count: int = 0
    download_status: DownloadStatus = DownloadStatus.NOT_DOWNLOADED
    local_path: Optional[str] = None
    url: str = ""


@dataclass
class Page:
    index: int = 0
    url: str = ""
    image_url: str = ""
    local_path: Optional[str] = None
    width: int = 0
    height: int = 0


@dataclass
class Category:
    id: Optional[int] = None
    name: str = ""
    sort_order: int = 0


@dataclass
class DownloadItem:
    manga: "Manga" = None
    chapter: "Chapter" = None
    progress: float = 0.0
    status: DownloadStatus = DownloadStatus.QUEUED
    error_message: str = ""
    pages_downloaded: int = 0
    total_pages: int = 0


@dataclass
class SearchFilter:
    query: str = ""
    genres: List[str] = field(default_factory=list)
    status: str = ""
    sort_by: str = "relevance"
    content_rating: List[str] = field(default_factory=list)


@dataclass
class ExtensionInfo:
    id: str = ""
    name: str = ""
    version: str = ""
    language: str = ""
    icon: str = ""
    description: str = ""
    installed: bool = False
    has_settings: bool = False
    nsfw: bool = False
