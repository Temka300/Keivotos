from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ImageSummary(BaseModel):
    id: int
    file_id: int
    thumbnail_token: str
    filename: str
    folder: str | None
    ext: str | None
    downloaded_at: str | None = None
    created_at: str | None = None
    width: int | None
    height: int | None
    score: int | None
    rating: str | None
    danbooru_post_id: int | None
    is_favorite: bool = False
    favorite_added_at: str | None = None
    favorite_pinned_at: str | None = None
    collection_added_at: str | None = None
    collection_pinned_at: str | None = None


class TagInfo(BaseModel):
    name: str
    category: str
    count: int
    favorite_added_at: str | None = None
    pinned_at: str | None = None


class TagWikiTextPart(BaseModel):
    text: str
    tag: str | None = None
    post_id: int | None = None


class TagWikiTextLine(BaseModel):
    parts: list[TagWikiTextPart] = Field(default_factory=list)


class TagWikiExample(BaseModel):
    danbooru_post_id: int
    local_post_id: int | None = None
    file_id: int | None = None
    thumbnail_token: str | None = None
    filename: str | None = None
    folder: str | None = None
    ext: str | None = None
    width: int | None = None
    height: int | None = None
    score: int | None = None
    rating: str | None = None
    post_url: str | None = None
    created_at: str | None = None


class TagWikiSection(BaseModel):
    title: str
    paragraphs: list[TagWikiTextLine] = Field(default_factory=list)
    items: list[TagWikiTextLine] = Field(default_factory=list)


class ArtistUrl(BaseModel):
    url: str
    is_active: bool = True


class TagWikiInfo(BaseModel):
    tag_name: str
    title: str
    other_names: list[str] = Field(default_factory=list)
    description: list[TagWikiTextLine] = Field(default_factory=list)
    examples: list[TagWikiExample] = Field(default_factory=list)
    post_references: list[TagWikiExample] = Field(default_factory=list)
    sections: list[TagWikiSection] = Field(default_factory=list)
    aliases: list[str] = Field(default_factory=list)
    implications: list[str] = Field(default_factory=list)
    artist_id: int | None = None
    artist_name: str | None = None
    artist_group_name: str | None = None
    artist_urls: list[ArtistUrl] = Field(default_factory=list)
    available: bool = False
    cached_at: str | None = None
    error: str | None = None


class ArtistFollowInfo(BaseModel):
    tag_name: str
    tag_category: str = "artist"
    display_name: str | None = None
    local_count: int = 0
    added_at: str
    last_checked_at: str | None = None
    notification_initialized_at: str | None = None
    last_seen_danbooru_post_id: int | None = None
    unseen_count: int = 0
    profile_post: TagWikiExample | None = None
    posts: list[TagWikiExample] = Field(default_factory=list)


class ArtistFollowCheckResult(BaseModel):
    follow: ArtistFollowInfo
    discovered_count: int = 0


class ArtistProfileAsset(BaseModel):
    id: int
    tag_name: str
    platform: str
    asset_kind: str
    source_profile_url: str
    source_url: str
    file_url: str
    width: int
    height: int
    captured_at: str


class ArtistProfileArchiveResult(BaseModel):
    assets: list[ArtistProfileAsset] = Field(default_factory=list)
    saved_count: int = 0
    unchanged_count: int = 0
    notices: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class ArtistProfileBulkArchiveResult(BaseModel):
    checked_artists: int = 0
    saved_count: int = 0
    unchanged_count: int = 0
    errors: list[str] = Field(default_factory=list)


class HomeCoverCandidate(BaseModel):
    post_id: int
    file_id: int
    thumbnail_token: str
    width: int | None = None
    height: int | None = None


class HomeTagInfo(BaseModel):
    name: str
    category: str
    count: int
    cover_post_id: int | None = None
    cover_file_id: int | None = None
    thumbnail_token: str | None = None
    cover_candidates: list[HomeCoverCandidate] = Field(default_factory=list)


class HomeTags(BaseModel):
    featured: list[HomeTagInfo] = Field(default_factory=list)
    groups: dict[str, list[HomeTagInfo]] = Field(default_factory=dict)


class HomeImageRailItem(BaseModel):
    id: int
    file_id: int
    thumbnail_token: str
    filename: str
    folder: str | None
    ext: str | None
    width: int | None
    height: int | None
    score: int | None
    rating: str | None
    tag_name: str | None = None
    tag_category: str | None = None
    is_favorite: bool = False


class HomeImageRail(BaseModel):
    key: str
    label: str
    items: list[HomeImageRailItem] = Field(default_factory=list)


class HomeImageRails(BaseModel):
    rails: list[HomeImageRail] = Field(default_factory=list)


class DailyChallengeImage(BaseModel):
    id: int
    file_id: int
    thumbnail_token: str
    filename: str
    folder: str | None
    ext: str | None
    width: int | None
    height: int | None
    score: int | None
    rating: str | None
    created_at: str | None
    danbooru_post_id: int | None


class DailyChallengeOption(BaseModel):
    name: str
    count: int


class DailyChallengeClues(BaseModel):
    copyrights: list[str] = Field(default_factory=list)
    artists: list[str] = Field(default_factory=list)
    general: list[str] = Field(default_factory=list)
    meta: list[str] = Field(default_factory=list)
    folder: str | None = None
    rating: str | None = None
    score: int | None = None
    year: int | None = None


class DailyChallenge(BaseModel):
    date: str
    challenge_id: str
    image: DailyChallengeImage
    answer_tag: str
    options: list[DailyChallengeOption] = Field(default_factory=list)
    clues: DailyChallengeClues = Field(default_factory=DailyChallengeClues)
    total_candidates: int


class FavoriteTagComboCreate(BaseModel):
    name: str | None = None
    tags: list[str]


class UserImageTagCreate(BaseModel):
    name: str
    category: str = "general"


class FavoriteTagComboInfo(BaseModel):
    id: int
    name: str
    tags: list[str]
    added_at: str


class RelatedImageInfo(BaseModel):
    danbooru_post_id: int
    local_post_id: int | None = None
    file_id: int | None = None
    thumbnail_token: str | None = None
    filename: str | None = None
    folder: str | None = None
    ext: str | None = None
    width: int | None = None
    height: int | None = None
    score: int | None = None
    rating: str | None = None
    post_url: str | None = None
    created_at: str | None = None


class ImageRelations(BaseModel):
    parent: RelatedImageInfo | None = None
    siblings: list[RelatedImageInfo] = Field(default_factory=list)
    children: list[RelatedImageInfo] = Field(default_factory=list)
    has_metadata: bool = False


class ImageDetail(BaseModel):
    id: int
    file_id: int
    thumbnail_token: str
    filename: str
    folder: str | None
    ext: str | None
    path: str
    size: int | None
    local_md5: str | None
    downloaded_at: str | None
    width: int | None
    height: int | None
    score: int | None
    rating: str | None
    danbooru_post_id: int | None
    post_url: str | None
    source_url: str | None
    created_at: str | None
    updated_at: str | None
    tags: dict[str, list[str]]
    removed_tags: list[str] = Field(default_factory=list)
    user_tags: dict[str, list[str]] = {}
    is_favorite: bool = False
    favorite_added_at: str | None = None
    favorite_pinned_at: str | None = None
    view_count: int = 0
    heart_spam_count: int = 0
    first_viewed_at: str | None = None
    last_viewed_at: str | None = None
    collections: list[CollectionInfo] = []
    relations: ImageRelations = Field(default_factory=ImageRelations)


class PaginatedImages(BaseModel):
    images: list[ImageSummary]
    total: int
    offset: int
    limit: int


class PaginatedTags(BaseModel):
    tags: list[TagInfo]
    total: int
    offset: int
    limit: int


class PopularityPeriod(BaseModel):
    period: str
    label: str
    start_date: str
    end_date: str
    image_count: int
    popularity: int
    average_score: float
    best_score: int


class TimelapseFrames(BaseModel):
    images: list[ImageSummary]
    total: int
    sampled: int
    start_date: str | None = None
    end_date: str | None = None


class FolderInfo(BaseModel):
    name: str
    selector: str
    count: int
    path: str | None = None
    root_id: str | None = None
    registered: bool = False


class FolderRelocate(BaseModel):
    path: str


class FolderRelocateResult(BaseModel):
    status: Literal["relocated"]
    name: str
    selector: str
    path: str
    root_id: str
    files_updated: int
    sync: str
    active_tool_id: str | None = None


class FolderRemovalPreview(BaseModel):
    name: str
    path: str
    root_id: str
    indexed_files: int
    sidecar_files: int
    sidecar_bytes: int
    external_images_affected: int = 0
    sidecar_history_preserved: bool = True


class FolderRemovalResult(BaseModel):
    status: str
    name: str
    mode: Literal["unindex_only", "delete_sidecars"]
    files_removed: int
    sidecar_files_removed: int = 0
    sidecar_bytes_removed: int = 0
    external_images_affected: int = 0
    sidecar_history_preserved: bool = True


class Stats(BaseModel):
    total_images: int
    total_tags: int
    total_folders: int
    total_favorites: int
    total_collections: int
    total_image_views: int = 0
    seen_images: int = 0
    total_storage_bytes: int = 0
    total_user_tags: int = 0
    total_favorite_tags: int = 0
    total_followed_artists: int = 0
    total_collection_items: int = 0
    average_score: float | None = None
    best_score: int | None = None
    downloaded_from: str | None = None
    downloaded_to: str | None = None
    first_viewed_at: str | None = None
    last_viewed_at: str | None = None
    profile_avatar_file_id: int | None = None
    profile_avatar_token: str | None = None
    profile_banner_file_id: int | None = None
    profile_banner_token: str | None = None


class UserSetting(BaseModel):
    key: str
    value: str


class UserSettingUpdate(BaseModel):
    value: str = Field(max_length=200)


class CollectionPreviewItem(BaseModel):
    file_id: int
    thumbnail_token: str | None = None
    filename: str | None = None
    ext: str | None = None
    width: int | None = None
    height: int | None = None


class CollectionInfo(BaseModel):
    id: int
    name: str
    description: str
    created_at: str
    pinned_at: str | None = None
    image_count: int = 0
    preview_ids: list[int] = Field(default_factory=list)
    preview_items: list[CollectionPreviewItem] = Field(default_factory=list)
    item_added_at: str | None = None
    item_pinned_at: str | None = None


class FolderCreate(BaseModel):
    path: str


class DanbooruCredentialsUpdate(BaseModel):
    username: str
    api_key: str | None = None


class BackfillToolRequest(BaseModel):
    folder: str | None = None
    limit: int | None = Field(default=None, ge=1, le=1000000)


class AutomationUpdate(BaseModel):
    enabled: bool
    interval_minutes: int | None = Field(default=None, ge=5, le=1440)


class AutomationStatus(BaseModel):
    enabled: bool
    enabled_at: str | None = None
    interval_minutes: int = 15
    last_run_at: str | None = None
    candidate_count: int = 0


class BackupConfigurationUpdate(BaseModel):
    components: dict[str, bool] = Field(default_factory=dict)


class BackupCreateRequest(BaseModel):
    components: dict[str, bool] | None = None


class BackupRestoreRequest(BaseModel):
    name: str


class ImportRunRequest(BaseModel):
    phase: str
    folder: str | None = None
    limit: int | None = Field(default=None, ge=1, le=1000000)
    confirm_network: bool = False


class ThumbnailCacheLimitUpdate(BaseModel):
    limit_gb: int = Field(ge=1, le=100)


class DanbooruCredentialStatus(BaseModel):
    username: str | None = None
    has_api_key: bool
    has_saved_api_key: bool
    has_saved_credentials: bool
    configured: bool
    source: str


class ToolFolderInfo(BaseModel):
    name: str
    path: str
    registered: bool
    exists: bool


class ToolRunResult(BaseModel):
    status: str
    active_tool_id: str | None = None


class ToolFileResult(BaseModel):
    filename: str
    path: str
    status: Literal["matched", "no_match", "error"]
    detail: str = ""
    index: int | None = None
    total: int | None = None


class ToolStatusInfo(BaseModel):
    status: str
    output: str = ""
    progress: int = 0
    total: int = 0
    stage: str | None = None
    stage_index: int | None = None
    stage_total: int | None = None
    cancellable: bool = False
    current_file: str | None = None
    current_file_path: str | None = None
    current_file_status: str | None = None
    file_results: list[ToolFileResult] = Field(default_factory=list)
    result_counts: dict[str, int] = Field(default_factory=dict)


class ToolInfo(ToolStatusInfo):
    id: str
    name: str
    description: str
    command: str
    requires_form: bool = False
    advanced: bool = False


class CollectionCreate(BaseModel):
    name: str
    description: str = ""


class CollectionUpdate(BaseModel):
    name: str
    description: str = ""


class CollectionItemsUpdate(BaseModel):
    file_ids: list[int]
    action: str = "add"


class CollectionMembershipRequest(BaseModel):
    file_ids: list[int]


class FavoriteBatchUpdate(BaseModel):
    file_ids: list[int]
    action: Literal["add", "remove"] = "add"


class ImageBatchRequest(BaseModel):
    post_ids: list[int]


class ImageBatchMove(ImageBatchRequest):
    folder: str


class ImageMoveFolder(BaseModel):
    folder: str
