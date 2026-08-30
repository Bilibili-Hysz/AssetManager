// ============ Source-of-truth note ============
// The types below are generated into contracts.ts from the backend frozen
// dataclasses in AssetsManager/lan/dto.py (scripts/gen_ts_types.py). For every
// type that exists in both files, contracts.ts is the single source of truth:
// api.ts only re-exports it and must not redeclare it.
//
// Types that exist only here (ShareLink, gallery/files DTOs, ...) have
// no frozen dataclass in lan/dto.py yet — their wire shapes live in
// domain/share.py (ShareLink.to_public_dict, plus the route-added
// url/requires_key) — so they remain hand-written; update them together
// with the backend serializers.
import type {
  Capabilities,
  InviteResponse,
  SessionPrincipal,
  Tag,
  TreeItem,
  UserResponse,
} from './contracts';

export type {
  Capabilities,
  Collection,
  CollectionEvaluateResponse,
  CollectionMember,
  CollectionMembersResponse,
  CollectionsResponse,
  InviteResponse,
  RuntimeCursor,
  SessionPrincipal,
  StatsResponse,
  Tag,
  TreeItem,
  UserResponse,
} from './contracts';

// ============ Server Info ============
export interface FeatureFlags {
  quota: boolean;
}

export interface ServerInfo {
  version: string;
  share_name: string;
  library_root: string;
  thumbnail_cache_namespace?: string | null;
  auth_enabled: boolean;
  auth_mode: 'none' | 'password' | 'key' | 'user';
  theme_color: string;
  /** Owner's current desktop theme display name (core.themes.name()); ""
   * when the theme subsystem is unavailable. Maps onto THEMES in
   * tokens/themes.manifest.generated.ts -> data-am-theme identity. */
  theme_name: string;
  welcome_msg: string;
  footer_text: string;
  library_stats: {
    total_projects: number;
    total_size: number;
    total_size_fmt: string;
  };
  principal?: SessionPrincipal;
  capabilities?: Capabilities;
  feature_flags?: FeatureFlags;
}

// Capabilities, RuntimeCursor, UserResponse, SessionPrincipal, InviteResponse,
// StatsResponse, Tag and TreeItem are re-exported from './contracts' (see the
// source-of-truth note at the top of this file).

export type User = UserResponse;

export interface LoginResponse {
  user?: UserResponse;
  principal?: SessionPrincipal;
}

export interface RegisterResponse {
  user: UserResponse;
  principal?: SessionPrincipal;
}

export interface MeResponse {
  principal: SessionPrincipal;
  user?: UserResponse;
}

// ============ Files / Projects ============
export interface ProjectItem {
  name: string;
  path: string;
  type: 'file' | 'dir';
  size: number;
  size_fmt: string;
  modified: number;
  extension: string;
  category: string;
  thumbnail_url?: string;
  tags?: string[];
  /** Backend sends this on every directory listing entry (files.py). */
  is_project?: boolean;
}

export interface PreviewPoolItem {
  name: string;
  path: string;
  thumbnail_url?: string;
}

// ============ Gallery ============
export type GalleryEntryKind = 'collection' | 'project' | 'artwork';

export interface GalleryEntry {
  name: string;
  path: string;
  kind: GalleryEntryKind;
  /** Parent collection path; "" (empty string) means the entry lives at the library root. */
  parent_path: string;
  cover_path?: string | null;
  cover_url?: string | null;
  thumbnail_url?: string | null;
  image_url?: string;
  width?: number | null;
  height?: number | null;
  aspect_ratio?: number | null;
  modified: number;
  size?: number;
  size_fmt?: string;
  file_count?: number;
  artwork_count?: number;
  child_count?: number;
  extension?: string;
  tags?: string[];
}

export interface GalleryHomeBuildingResponse {
  building: true;
}

export interface GalleryHomeReadyResponse {
  featured: GalleryEntry | null;
  collections: GalleryEntry[];
  projects: GalleryEntry[];
  recent: GalleryEntry[];
  stats: {
    collections: number;
    projects: number;
    artworks: number;
    total_size_fmt: string;
  };
}

export type GalleryHomeResponse = GalleryHomeBuildingResponse | GalleryHomeReadyResponse;

export interface GalleryCollectionResponse {
  collection: GalleryEntry;
  children: GalleryEntry[];
  entries: GalleryEntry[];
  next_cursor: string | null;
}

export interface GalleryResolveResponse {
  kind: GalleryEntryKind;
  path: string;
  gallery_context: string;
  workspace_context: string;
}

export interface FavoritesResponse {
  favorites: GalleryEntry[];
}

export interface FavoriteMutationResponse {
  ok: boolean;
  path: string;
  favorite: boolean;
  changed: boolean;
}

export interface FilesResponse {
  current_path: string;
  parent_path: string | null;
  items: ProjectItem[];
  total_count: number;
  total_size: number;
  total_size_fmt: string;
}

export interface DirectorySummaryItem {
  path: string;
  item_count: number;
  size_fmt: string;
  thumbnail_url: string | null;
}

export interface DirectorySummariesResponse {
  items: DirectorySummaryItem[];
}

export interface ProjectFile {
  name: string;
  size: number;
  size_fmt: string;
  extension: string;
  category: string;
}

export interface ProjectImage {
  name: string;
  url: string;
  thumb_url: string;
}

export interface ProjectDetail {
  name: string;
  path: string;
  tags: string[];
  notes: string;
  urls: string[];
  total_size: number;
  total_size_fmt: string;
  file_count: number;
  files: ProjectFile[];
  images: ProjectImage[];
  thumbnail_url: string | null;
  modified: number;
  download_url: string;
}

// ============ Tree ============
export interface TreeResponse {
  tree: TreeItem[];
  depth_config: {
    global: number;
    branches: Record<string, number>;
  };
}

// ============ Home ============
export interface PopularTag {
  name: string;
  count: number;
}

export interface HomeData {
  recent_projects: ProjectItem[];
  preview_pool?: PreviewPoolItem[];
  popular_tags: PopularTag[];
  stats: {
    total_projects: number;
    total_size: number;
    total_size_fmt: string;
  };
}

// ============ Search ============
export interface SearchResult {
  name: string;
  path: string;
  type: string;
  extension: string;
  category: string;
  thumbnail_url?: string;
}

/** Per-source outcome, present when the request opted in via include_status=1. */
export interface SearchSourceStatus {
  source: string;
  status: string;
  result_count: number;
  dropped_count: number;
  error_count: number;
}

export interface SearchResponse {
  results: SearchResult[];
  count: number;
  /**
   * Aggregate outcome ('partial' | 'degraded' | 'complete' | ...), only sent
   * when the request carries include_status=1.
   */
  status?: string;
  sources?: SearchSourceStatus[];
  errors?: Array<{ code: string; source: string; recoverable: boolean }>;
  dropped_count?: number;
  fallback_used?: boolean;
}

export type BrowsableItem = SearchResult & Partial<Pick<ProjectItem, 'size' | 'size_fmt' | 'modified' | 'tags'>> & {
  is_project?: boolean;
};

// ============ Tags ============
export interface TagsResponse {
  tags: Tag[];
}

// ============ Metadata ============
export interface Metadata {
  path: string;
  thumbnail_url?: string;
  tags: string[];
  notes: string;
  urls: string[];
}

export interface SaveNotesResponse {
  ok: boolean;
  path: string;
  notes: string;
}

// ============ Thumbnails ============
export interface ThumbnailBatchRequest {
  paths: string[];
  size?: number;
}

export interface ThumbnailBatchResponse {
  thumbnails: Record<string, string>;
}

// ============ Shares ============
export interface ShareLink {
  id: string;
  paths: string[];
  created_by: string;
  created_at: number; // Unix timestamp
  allow_preview: boolean;
  download_count: number;
  max_downloads: number | null;
  has_password: boolean;
  expired: boolean;
  expires_in_hours: number | null; // hours remaining
  url?: string; // Added by server
  requires_key?: boolean; // Added by server
}

export interface ShareCreateRequest {
  paths: string[];
  password?: string;
  expires_hours?: number;
  max_downloads?: number;
  allow_preview?: boolean;
}

export interface ShareVerifyResponse {
  share: ShareLink;
}

export interface ShareInfoResponse {
  id: string;
  has_password: boolean;
  expired: boolean;
  allow_preview: boolean;
  paths?: string[];
  created_by?: string;
  created_at?: number;
  download_count?: number;
  max_downloads?: number | null;
  expires_in_hours?: number | null;
}

// ============ System Stats ============
// StatsResponse is re-exported from './contracts'.

// ============ Users ============
export interface UsersResponse {
  users: UserResponse[];
}

export type InviteCode = InviteResponse;

export interface InvitesResponse {
  invites: InviteCode[];
}

export interface ActivityLog {
  id: number;
  username: string;
  action: string;
  details: string;
  ip: string;
  timestamp: number; // Unix epoch seconds
}

export interface ActivityResponse {
  activities: ActivityLog[];
}

export interface OnlineUsersResponse {
  users: Array<{
    user_id: string;
    username: string;
    ip: string;
    connected_at: number; // Unix timestamp
  }>;
}

// ============ Common ============
export interface ErrorResponse {
  error: string;
  code: string;
  details: Record<string, unknown>;
  field?: string;
  [key: string]: unknown;
}

export interface OkResponse {
  ok: boolean;
}

// ============ Quota ============
export interface QuotaInfo {
  enabled: boolean;
  period: 'daily' | 'weekly';
  limit: number;
  used: number;
  remaining: number | null;
  reset_at: number | null;
  min_interval_seconds: number;
}
