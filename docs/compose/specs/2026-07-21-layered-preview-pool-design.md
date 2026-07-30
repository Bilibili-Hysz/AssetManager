# Layered Preview Pool Design

## [S1] Problem

The Gate home response currently does not project the desktop-baked directory preview cache into `recent_projects`, so Gate receives project identity without a usable `thumbnail_url`. The internal Filelist receives directory `thumbnail_url` values through summaries, but renders directories with a plain folder icon because only file thumbnails are passed to the grid and the list has no thumbnail input.

## [S2] Data source and cache boundary

Use the current library's existing RuntimeData-backed SQLite `directory_cache.preview_path` entries. Validate each entry against the directory mtime and the cached preview file's existence. Do not add recursive scans, new image stores, external image URLs, or a new API endpoint. Home and directory-list responses continue to expose root-relative `/api/thumbnails/{path}` URLs, and the existing thumbnail route remains responsible for permissions and image delivery.

## [S3] Gate preview pool

`/api/home` project items include an optional `thumbnail_url` generated from valid cached directory previews. LandingPage builds a de-duplicated pool from items with usable URLs, shuffles it once when the Home response arrives, uses the shuffled pool for the background wall and initial showcase, and preserves the existing preload-before-rotation behavior. Theme changes, tuning changes, and unrelated React renders do not reshuffle the pool.

## [S4] Shared layered preview component

Add a small `LayeredPreview` component used by Gate showcase tiles and Filelist cards/rows. For a valid preview URL it renders one real image with two subtle offset backing layers; for missing or failed images it renders the existing Folder or File lucide icon. It supports compact grid and list sizes, stable dimensions, `alt` text supplied by the caller, visible focus inherited from the containing control, and no interaction of its own.

## [S5] Filelist integration

Grid cards consume `thumbnailMap[item.path]` for both files and directories. The map is populated from the existing base64 file thumbnail cache for image files and from `item.thumbnail_url` for directories after the existing viewport-triggered `/api/files/summaries` hydration. List rows receive the same directory thumbnail mapping and use `LayeredPreview` in the icon cell. Directory navigation, ZIP selection, context menus, and row/card semantics remain unchanged.

## [S6] Failure behavior

Missing RuntimeData cache, stale cache entries, absent preview fields, 403/404 thumbnail responses, and image decode errors all fall back to a folder/file icon without blocking navigation or the Gate `/browse` entry. Failed Gate candidates are removed from the pool/showcase; failed Filelist images fall back locally. Existing preview permission checks remain authoritative.

## [S7] Verification

Add backend tests for Home cache projection and stale/missing cache behavior, frontend component tests for layered/fallback states, Filelist tests for directory thumbnail propagation in grid and list, and Gate tests for stable one-time pool shuffling and URL rendering. Run focused Python and WebUI tests, full WebUI tests, TypeScript typecheck, and production build.
