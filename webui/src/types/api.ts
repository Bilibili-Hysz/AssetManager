// ============ Source-of-truth note ============
// The types below are generated into contracts.ts from the backend frozen
// dataclasses in AssetsManager/lan/dto.py (scripts/gen_ts_types.py). For every
// type that exists in both files, contracts.ts is the single source of truth:
// api.ts only re-exports it and must not redeclare it.
//
// Types that exist only here (ShareLink, Shop*, gallery/files DTOs, ...) have
// no frozen dataclass in lan/dto.py yet — their wire shapes live in
// domain/share.py (ShareLink.to_public_dict, plus the route-added
// url/requires_key) and application/order_service.py (_BUYER/_SELLER_ORDER_
// FIELDS) — so they remain hand-written; update them together with the
// backend serializers.
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
  commerce: boolean;
  seller: boolean;
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

export interface SearchResponse {
  results: SearchResult[];
  count: number;
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

// ============ Shop ============
// These DTOs mirror the JSON emitted by the LAN commerce routes. Keep the
// persistence field names here; presentation adapters live in useCommerce.ts.
export type ShopItemStatus = 'active' | 'archived' | 'draft';

export interface ShopItem {
  id: number;
  path: string;
  title: string;
  description: string;
  price_cents: number;
  currency: string;
  cover_path: string | null;
  gallery_paths: string[];
  enabled: boolean;
  metadata: Record<string, unknown>;
  status: ShopItemStatus;
  created_at: number;
  updated_at: number;
}

export interface ShopItemsResponse {
  items: ShopItem[];
}

export type ShopCatalogSort = 'newest';

export interface ShopCatalogQuery {
  q?: string;
  page?: number;
  page_size?: number;
  sort?: ShopCatalogSort;
}

export interface ShopCatalogResponse {
  items: ShopItem[];
  page: number;
  page_size: number;
  total: number;
}

export type ShopCartStatus = 'active' | 'converted' | 'expired' | 'merged';

export interface ShopCartItem {
  id: number;
  item_id: number;
  quantity: number;
  unit_price_cents: number;
  currency: string;
  path: string;
  title: string;
  line_status: 'active' | 'unavailable' | 'removed';
  created_at: number;
  updated_at: number;
}

export interface ShopCart {
  id: number;
  owner_type: 'user' | 'anonymous';
  status: ShopCartStatus;
  version: number;
  expires_at: number | null;
  created_at: number;
  updated_at: number;
  items: ShopCartItem[];
}

export interface ShopCartResponse {
  cart: ShopCart;
}

export interface ShopCartCheckoutResponse {
  orders: ShopBuyerOrder[];
  idempotent: boolean;
  checkout_group_id?: string;
  cart: ShopCart;
}

export interface ShopCheckoutGroupOrder extends ShopBuyerOrder {
  quantity: number;
  unit_price_cents?: number;
}

export type ShopCheckoutGroupStatus =
  | 'pending'
  | 'confirmed'
  | 'in_progress'
  | 'fulfilled'
  | 'revoked'
  | 'mixed';

export interface ShopCheckoutGroupResponse {
  checkout_group_id: string;
  orders: ShopCheckoutGroupOrder[];
  idempotent: boolean;
  status: ShopCheckoutGroupStatus;
  created_at: number;
  cart: ShopCart;
}

export type ShopWishlistAvailability = 'available' | 'unavailable';

export interface ShopWishlistItem {
  item_id: number;
  added_at: number;
  path: string | null;
  title: string | null;
  price_cents: number | null;
  currency: string | null;
  availability: ShopWishlistAvailability;
}

export interface ShopWishlistResponse {
  items: ShopWishlistItem[];
}

/**
 * Result of explicitly merging the anonymous buyer state into the signed-in
 * user's cart and wishlist. The endpoint is intentionally additive: callers
 * can update local state from this response without a second pair of reads.
 */
export interface ShopBuyerMergeResponse {
  merged: boolean;
  cart: ShopCart;
  wishlist: ShopWishlistItem[];
  /** Legacy-compatible alias returned by the first merge implementation. */
  items?: ShopWishlistItem[];
  source?: {
    cart?: boolean;
    wishlist?: boolean;
  };
  limits?: {
    cart_item_quantity?: number;
    wishlist_items?: number;
  };
}

export interface ShopItemPayload {
  path?: string;
  title?: string;
  description?: string;
  price_cents?: number;
  currency?: string;
  status?: ShopItemStatus;
  cover_path?: string;
  gallery_paths?: string[];
  metadata?: Record<string, unknown>;
}

export interface ShopSellerProfile {
  store_name: string;
  contact_email: string;
  description: string;
  accept_orders: boolean;
  updated_at: number;
}

export interface ShopSellerProfilePayload {
  store_name?: string;
  contact_email?: string;
  description?: string;
  accept_orders?: boolean;
}

export interface ShopPublicSellerProfile {
  store_name: string;
  description: string;
  accept_orders: boolean;
}


export type ShopOrderStatus = 'pending' | 'confirmed' | 'fulfilled' | 'revoked';

export interface ShopOrder {
  id: number;
  item_id: number;
  item_path: string;
  item_title: string;
  buyer_name: string | null;
  buyer_email: string | null;
  amount_cents: number;
  currency: string;
  status: ShopOrderStatus;
  metadata: Record<string, unknown>;
  created_at: number;
  updated_at: number;
}

/**
 * Buyer-safe order data returned by the public order routes.
 *
 * Keep this separate from the seller order DTO: the buyer receipt is carried
 * by an HttpOnly cookie, so it must not be represented as a token or delivery
 * path in frontend state.
 */
export interface ShopBuyerOrder {
  id: number;
  item_id: number;
  item_title: string;
  amount_cents: number;
  currency: string;
  status: ShopOrderStatus;
  delivery_available: boolean;
  quantity?: number;
  unit_price_cents?: number;
  created_at: number;
  updated_at: number;
}

export interface ShopOrdersResponse {
  orders: ShopOrder[];
}

export interface ShopBuyerOrdersResponse {
  orders: ShopBuyerOrder[];
  total?: number;
  next_cursor?: string | null;
}

export interface ShopStats {
  total_orders: number;
  gross_cents: number;
  store_views?: number;
  pending_orders?: number;
  confirmed_orders?: number;
  fulfilled_orders?: number;
  revoked_orders?: number;
}

/** Safe delivery-only state returned after resolving a bearer delivery token. */
export interface DeliveryOrder {
  order_id: number;
  item_id: number;
  item_title: string;
  status: ShopOrderStatus;
  max_downloads: number;
  download_count: number;
  expires_at: number | null;
  last_download_at: number | null;
}

export interface DeliveryInfo {
  order: DeliveryOrder;
  filename: string;
  is_directory: boolean;
  download_url: string;
}

export interface ReceiptRecoveryResponse {
  ok: boolean;
  order_id: number;
}

export interface FulfillOrderResponse {
  order: ShopOrder;
  delivery_url: string;
  rotated?: boolean;
  /**
   * One-time share claim code for the new storefront delivery link flow.
   * Present on new backends; legacy backends omit it (bearer delivery_url).
   */
  share_claim?: string;
}
