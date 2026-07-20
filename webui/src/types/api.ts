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
}

// ============ Auth ============
export interface LoginResponse {
  token: string;
  user?: User;
}

export interface RegisterResponse {
  token: string;
  user: User;
}

export interface User {
  id: number;
  username: string;
  role: 'admin' | 'user';
  active: boolean;
  created_at: string;
  last_login?: string;
}

export interface MeResponse {
  user: User;
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
  type: 'file' | 'dir';
  is_leaf?: boolean;
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

// ============ Tags ============
export interface Tag {
  id: number;
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
  bytes_transferred: number;
  bytes_transferred_fmt: string;
  uptime: number;
}

// ============ Users ============
export interface UsersResponse {
  users: User[];
}

export interface InviteCode {
  code: string;
  created_at: string;
  used_by?: string;
  revoked: boolean;
}

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
