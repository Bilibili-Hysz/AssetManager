// ============ Server Info ============
export interface ServerInfo {
  version: string;
  share_name: string;
  library_root: string;
  auth_enabled: boolean;
  auth_mode: 'none' | 'password' | 'key' | 'user';
  theme_color: string;
  welcome_msg: string;
  footer_text: string;
  library_stats: {
    total_projects: number;
    total_size: number;
    total_size_fmt: string;
  };
  principal?: SessionPrincipal;
  capabilities?: Capabilities;
}

// ============ Auth ============
export interface Capabilities {
  browse: boolean;
  preview: boolean;
  download: boolean;
  upload: boolean;
  manage_links: boolean;
  manage_users: boolean;
  settings: boolean;
  realtime: boolean;
}

export interface RuntimeCursor {
  epoch: string;
  revision: number;
}

export interface UserResponse {
  id: number;
  username: string;
  role: 'admin' | 'user';
  active: boolean;
  created_at: number;
}

export type User = UserResponse;

export interface SessionPrincipal {
  kind: 'user' | 'password' | 'access_key' | 'local_ui' | 'guest' | 'share';
  authenticated: boolean;
  role: 'admin' | 'user' | 'guest';
  display_name: string;
  capabilities: Capabilities;
  user_profile?: UserResponse;
}

export interface LoginResponse {
  token: string;
  user?: UserResponse;
  principal?: SessionPrincipal;
}

export interface RegisterResponse {
  token: string;
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
  view_only?: boolean;
  downloadable?: boolean;
  password_protected?: boolean;
}

export interface PreviewPoolItem {
  name: string;
  path: string;
  thumbnail_url?: string;
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
export interface TreeItem {
  name: string;
  path: string;
  type: 'dir';
  is_leaf: boolean;
  children?: TreeItem[];
}

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

export interface SearchResponse {
  results: SearchResult[];
  count: number;
}

export type BrowsableItem = SearchResult & Partial<Pick<ProjectItem, 'size' | 'size_fmt' | 'modified' | 'tags' | 'view_only' | 'downloadable' | 'password_protected'>> & {
  is_project?: boolean;
};

// ============ Tags ============
export interface Tag {
  id: number | null;
  name: string;
  count: number;
}

export interface TagsResponse {
  tags: Tag[];
}

// ============ Metadata ============
export interface Metadata {
  path: string;
  tags: string[];
  notes: string;
  urls: string[];
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
export interface StatsResponse {
  connections: number;
  requests: number;
  bytes_transferred: number | null;
  bytes_transferred_fmt: string | null;
  uptime: number;
}

// ============ Users ============
export interface UsersResponse {
  users: UserResponse[];
}

export interface InviteResponse {
  code: string;
  created_at: number;
  used_by: string | null;
  revoked: boolean;
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
  timestamp: string;
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
}

export interface OkResponse {
  ok: boolean;
}
