/* ═══════════════════════════════════════════════════════════════
   AssetManager Share — Three-Column Resizable Asset Library
   ═══════════════════════════════════════════════════════════════ */

const state = {
    currentPath: "", projects: [], tags: [], search: "",
    sort: "name", order: "asc", viewMode: "grid",
    token: null, user: null, userRole: null, userPermissions: null,
    sidebarOpen: true, infoOpen: true,
    selectedPaths: new Set(), batchMode: false,
};

let searchTimer = null, eventsBound = false;
let isDragging = false, dragType = null;
let contextItem = null;
let currentAbortController = null;

function icon(name, cls = '') {
    return `<i data-lucide="${name}" class="${cls}"></i>`;
}
function initIcons() {
    if (typeof lucide !== 'undefined') lucide.createIcons();
    else if (window.LanIconFallback) window.LanIconFallback.render();
}

// ── API ──────────────────────────────────────────────────────

async function api(ep, params = {}, signal = null) {
    const url = new URL(`/api/${ep}`, location.origin);
    Object.entries(params).forEach(([k, v]) => { if (v != null && v !== "") url.searchParams.set(k, v); });
    // Cookie is sent automatically by browser (httpOnly)
    const r = await fetch(url, { signal });
    if (r.status === 401) { showLogin(); throw new Error("Unauthorized"); }
    if (!r.ok) {
        const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
        throw new Error(err.error || `Request failed with status ${r.status}`);
    }
    return r.json();
}

async function apiPost(ep, body, signal = null) {
    const h = { "Content-Type": "application/json" };
    // Cookie is sent automatically by browser (httpOnly)
    const r = await fetch(`/api/${ep}`, { method: "POST", headers: h, body: JSON.stringify(body), signal });
    if (r.status === 401) { showLogin(); throw new Error("Unauthorized"); }
    if (!r.ok) {
        const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
        throw new Error(err.error || `Request failed with status ${r.status}`);
    }
    return r.json();
}

function cancelPendingRequests() {
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }
}

// ── Project Loading ──────────────────────────────────────────

async function loadProjects(path) {
    state.currentPath = path || "";

    cancelPendingRequests();
    const abortController = new AbortController();
    currentAbortController = abortController;

    const grid = document.getElementById("projectGrid");
    grid.innerHTML = skeleton(6);
    showProjectView();
    hideInfoPanel();
    try {
        const d = await api("projects", { path: state.currentPath, sort: state.sort, order: state.order, search: state.search }, abortController.signal);
        if (abortController.signal.aborted) return;
        state.projects = d.items || [];
        renderBreadcrumb(d.current_path || "");
        renderProjects(state.projects);
        const pc = d.project_count || 0, fc = d.folder_count || 0;
        document.getElementById("projectCount").textContent = t('toolbar.project_count', pc, fc, d.total_size_fmt);
        saveState();
        pushHistory(state.currentPath);
    } catch (e) {
        if (e.name === "AbortError") return;
        if (e.message !== "Unauthorized") { grid.innerHTML = `<div class="empty-state"><div class="empty-state__icon">${icon('alert-triangle')}</div><div class="empty-state__text">${t('status.failed_load')}</div></div>`; initIcons(); }
    }
}

// ── Rendering ────────────────────────────────────────────────

function renderBreadcrumb(path) {
    const el = document.getElementById("breadcrumb");
    const parts = path ? path.split("/").filter(Boolean) : [];
    let h = '';

    // Add back button if we're in a subdirectory
    if (parts.length > 0) {
        const parentPath = parts.slice(0, -1).join("/");
        h += `<span class="breadcrumb__back" data-path="${esc(parentPath)}" title="${t('action.back')}">&#8592; ${t('action.back')}</span>`;
    }

    h += `<span class="breadcrumb__item" data-path="">Root</span>`;
    let acc = "";
    for (let i = 0; i < parts.length; i++) {
        acc += (acc ? "/" : "") + parts[i];
        h += `<span class="breadcrumb__sep">/</span><span class="breadcrumb__item${i === parts.length - 1 ? " active" : ""}" data-path="${esc(acc)}">${esc(parts[i])}</span>`;
    }
    el.innerHTML = h;

    // Add event listeners
    el.querySelectorAll(".breadcrumb__item").forEach(item => {
        item.addEventListener("click", () => nav(item.dataset.path));
    });
    const backBtn = el.querySelector(".breadcrumb__back");
    if (backBtn) {
        backBtn.addEventListener("click", () => nav(backBtn.dataset.path));
    }
}

function renderProjects(projects) {
    const grid = document.getElementById("projectGrid");
    if (!projects.length) { grid.innerHTML = `<div class="empty-state"><div class="empty-state__icon">${icon('folder-open')}</div><div class="empty-state__text">${t('status.no_projects')}</div></div>`; initIcons(); return; }
    // Apply view mode class
    grid.className = `project-grid ${state.viewMode === "list" ? "project-grid--list" : ""}`;
    grid.innerHTML = projects.map(p => card(p)).join("");
    initIcons();
    // Add event delegation for cards
    bindCardEvents(grid);
    // Load thumbnails in batch
    loadBatchThumbnails(projects);
}

function bindCardEvents(container) {
    // Remove existing listeners to prevent duplicates
    container.removeEventListener("click", handleCardClick);
    container.removeEventListener("dblclick", handleCardDblClick);
    container.removeEventListener("contextmenu", handleCardContextMenu);

    // Add new listeners
    container.addEventListener("click", handleCardClick);
    container.addEventListener("dblclick", handleCardDblClick);
    container.addEventListener("contextmenu", handleCardContextMenu);
}

function handleCardClick(e) {
    // Tag chip delegation
    const tagChip = e.target.closest(".tag-chip[data-tag]");
    if (tagChip) {
        e.stopPropagation();
        filterByTag(tagChip.dataset.tag);
        return;
    }

    // Copy share link button
    const copyBtn = e.target.closest(".card-copy-link");
    if (copyBtn) {
        e.stopPropagation();
        const path = copyBtn.dataset.path;
        navigator.clipboard.writeText(`${location.origin}/api/download/${enc(path)}`);
        toast(t('status.link_copied'), "success");
        return;
    }

    // Check if clicking on select checkbox
    const selectEl = e.target.closest(".project-card__select");
    if (selectEl) {
        e.stopPropagation();
        const path = selectEl.dataset.path;
        toggleSelection(path);
        return;
    }

    const card = e.target.closest("[data-path]");
    if (!card) return;
    e.stopPropagation();
    const path = card.dataset.path;
    const isProject = card.dataset.type === "project";
    if (isMobile()) {
        // Mobile: navigate to detail page for projects
        if (isProject) navigateToDetail(path); else nav(path);
    } else {
        showInfoPanel(path);
    }
}

function handleCardDblClick(e) {
    const card = e.target.closest("[data-path]");
    if (!card) return;
    const path = card.dataset.path;
    const isProject = card.dataset.type === "project";
    // Navigate to detail page for projects
    if (isProject) navigateToDetail(path); else nav(path);
}

function handleCardContextMenu(e) {
    const card = e.target.closest("[data-path]");
    if (!card) return;
    e.preventDefault();
    const path = card.dataset.path;
    const type = card.dataset.type === "project" ? "file" : "dir";
    showCtx(e, path, type);
}

// ── Multi-Select ──────────────────────────────────────────────

function toggleSelection(path) {
    if (state.selectedPaths.has(path)) {
        state.selectedPaths.delete(path);
    } else {
        state.selectedPaths.add(path);
    }
    updateSelectionUI();
}

function clearSelection() {
    state.selectedPaths.clear();
    updateSelectionUI();
}

function toggleBatchMode() {
    state.batchMode = !state.batchMode;
    document.querySelectorAll(".project-card__select").forEach(el => {
        el.style.opacity = state.batchMode ? "1" : "";
    });
    if (!state.batchMode) clearSelection();
}

function updateSelectionUI() {
    // Update card visuals
    document.querySelectorAll(".project-card").forEach(card => {
        const path = card.dataset.path;
        if (state.selectedPaths.has(path)) {
            card.classList.add("selected");
        } else {
            card.classList.remove("selected");
        }
    });

    // Update toolbar
    const batchActions = document.getElementById("batchActions");
    const selectedCount = document.getElementById("selectedCount");
    if (state.selectedPaths.size > 0) {
        batchActions.style.display = "flex";
        selectedCount.textContent = t('toolbar.selected', state.selectedPaths.size);
    } else {
        batchActions.style.display = "none";
    }
}

async function batchDownload() {
    if (state.selectedPaths.size === 0) return;

    const paths = Array.from(state.selectedPaths);
    try {
        showProgressBar();
        const response = await fetch("/api/download/batch", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ paths }),
        });

        if (!response.ok) {
            throw new Error("Download failed");
        }

        const reader = response.body.getReader();
        const contentLength = +response.headers.get("Content-Length");
        let received = 0;
        const chunks = [];
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            if (contentLength) updateProgressBar(received / contentLength);
        }
        hideProgressBar();

        const blob = new Blob(chunks);
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = response.headers.get("Content-Disposition")?.match(/filename="(.+)"/)?.[1] || "download.zip";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        clearSelection();
        toast(t('status.download_started'), "success");
    } catch (e) {
        hideProgressBar();
        toast(t('status.download_failed'), "error");
    }
}

// ── Landing Page ─────────────────────────────────────────────

function showLandingPage() {
    document.getElementById("landingPage").classList.remove("hidden");
    document.getElementById("app").style.display = "none";
}

function hideLandingPage() {
    document.getElementById("landingPage").classList.add("hidden");
    document.getElementById("app").style.display = "";
}

function showProjectView() {
    document.getElementById("projectGrid").style.display = "grid";
}

function handleLandingEnter() {
    // Save no-auth marker so landing page doesn't show again
    sessionStorage.setItem("lan_no_auth", "1");
    hideLandingPage();
    initApp();
}

// ── Batch Thumbnail Loading ─────────────────────────────────

// LRU cache for thumbnails with size limit - persisted to sessionStorage
const THUMB_CACHE_MAX = 300;
let _thumbCache = new Map();

// Load cache from sessionStorage on init
function loadThumbCache() {
    try {
        const saved = sessionStorage.getItem("lan_thumb_cache");
        if (saved) {
            const entries = JSON.parse(saved);
            _thumbCache = new Map(entries);
        }
    } catch (e) { /* ignore */ }
}

// Save cache to sessionStorage
function saveThumbCache() {
    try {
        const entries = Array.from(_thumbCache.entries());
        sessionStorage.setItem("lan_thumb_cache", JSON.stringify(entries));
    } catch (e) { /* ignore */ }
}

function cacheThumb(path, dataUrl) {
    if (_thumbCache.has(path)) _thumbCache.delete(path); // refresh position
    _thumbCache.set(path, dataUrl);
    if (_thumbCache.size > THUMB_CACHE_MAX) {
        // Evict oldest entry
        const firstKey = _thumbCache.keys().next().value;
        _thumbCache.delete(firstKey);
    }
    saveThumbCache();
}

function getThumbCache(path) {
    if (_thumbCache.has(path)) {
        // Move to end (most recently used)
        const val = _thumbCache.get(path);
        _thumbCache.delete(path);
        _thumbCache.set(path, val);
        return val;
    }
    return null;
}

async function loadBatchThumbnails(items) {
    // Collect paths that need thumbnails and aren't cached
    const toLoad = [];
    for (const item of items) {
        if (item.thumbnail_url && !getThumbCache(item.path)) {
            // Extract relative path from thumbnail_url
            const relPath = item.thumbnail_url.replace("/api/thumbnails/", "").split("?")[0];
            toLoad.push({ path: item.path, relPath: decodeURIComponent(relPath), thumbnail_url: item.thumbnail_url });
        }
    }
    if (!toLoad.length) {
        applyCachedThumbnails(items);
        return;
    }

    // Batch load
    try {
        const data = await apiPost("thumbnails/batch", {
            paths: toLoad.map(t => t.relPath),
            size: 512,
        });
        // Cache results
        for (const [relPath, b64] of Object.entries(data.thumbnails || {})) {
            const item = toLoad.find(t => t.relPath === relPath);
            if (item) {
                cacheThumb(item.path, `data:image/webp;base64,${b64}`);
            }
        }
        applyCachedThumbnails(items);
    } catch (e) {
        // Fallback: load individually using direct thumbnail URLs
        for (const item of toLoad) {
            cacheThumb(item.path, item.thumbnail_url);
        }
        applyCachedThumbnails(items);
    }
}

function applyCachedThumbnails(items) {
    // Build a Map once for O(1) lookups instead of O(N) queries per item
    const cardMap = new Map();
    document.querySelectorAll('.project-card, .folder-card').forEach(c => {
        cardMap.set(c.dataset.path, c);
    });

    for (const item of items) {
        const dataUrl = getThumbCache(item.path);
        if (!dataUrl) continue;
        const card = cardMap.get(item.path);
        if (!card) continue;
        const img = card.querySelector("img");
        const placeholder = card.querySelector(".project-card__thumb-placeholder, .file-card__thumb-placeholder");
        if (img) {
            img.src = dataUrl;
            img.style.display = "";
            if (placeholder) placeholder.style.display = "none";
        } else if (card.classList.contains("project-card")) {
            // Create img element if it doesn't exist
            const thumbDiv = card.querySelector(".project-card__thumb");
            if (thumbDiv) {
                const newImg = document.createElement("img");
                newImg.src = dataUrl;
                newImg.alt = "";
                thumbDiv.insertBefore(newImg, thumbDiv.firstChild);
                if (placeholder) placeholder.style.display = "none";
            }
        }
    }
}

function permissionBadges(item) {
    const badges = [];
    if (item.view_only) badges.push(`<span class="perm-badge perm-badge--lock" title="${t('perm.view_only')}">${icon('lock')}</span>`);
    if (item.downloadable !== false) badges.push(`<span class="perm-badge perm-badge--download" title="${t('perm.downloadable')}">${icon('download')}</span>`);
    if (item.password_protected) badges.push(`<span class="perm-badge perm-badge--password" title="${t('perm.password_protected')}">${icon('lock')}</span>`);
    return badges.length ? `<div class="perm-badges">${badges.join("")}</div>` : "";
}

function card(item) {
    const isP = item.is_project;
    const cachedThumb = getThumbCache(item.path);
    const thumbHtml = cachedThumb
        ? `<img src="${cachedThumb}" alt="">`
        : item.thumbnail_url
            ? `<img data-src="${item.thumbnail_url}" alt="" loading="lazy">`
            : "";
    const typeIcon = isP ? icon('folder-open') : icon('folder');
    const tags = isP ? item.tags.slice(0, 4).map(t => `<span class="tag-chip" data-tag="${esc(t)}">${esc(t)}</span>`).join("") : "";
    const more = (isP && item.tags.length > 4) ? `<span class="tag-chip">+${item.tags.length - 4}</span>` : "";
    const isSelected = state.selectedPaths.has(item.path);
    const badges = permissionBadges(item);
    const copyBtn = isP ? `<button class="card-copy-link" data-path="${esc(item.path)}" title="Copy share link">${icon('link')}</button>` : "";

    if (isP) {
        return `<div class="project-card${isSelected ? ' selected' : ''}" data-path="${esc(item.path)}" data-type="project"><div class="project-card__select" data-path="${esc(item.path)}"></div><div class="project-card__thumb">${thumbHtml}<span class="project-card__thumb-placeholder" style="${cachedThumb || item.thumbnail_url ? 'display:none' : ''}">${typeIcon}</span><span class="project-card__size">${esc(item.total_size_fmt)}</span>${badges}</div><div class="project-card__info"><div class="project-card__name" title="${esc(item.name)}">${esc(item.name)}</div><div class="project-card__tags">${tags}${more}</div><div class="project-card__meta">${t('detail.files', item.file_count)} · ${esc(item.total_size_fmt)}${copyBtn}</div></div></div>`;
    } else {
        return `<div class="folder-card" data-path="${esc(item.path)}" data-type="folder"><div class="folder-card__icon">${icon('folder')}</div><div class="folder-card__info"><div class="folder-card__name" title="${esc(item.name)}">${esc(item.name)}</div><div class="folder-card__meta">${t('detail.files', item.file_count)}</div></div></div>`;
    }
}

function isMobile() { return window.innerWidth <= 768; }

function skeleton(count = 6) {
    let html = '';
    for (let i = 0; i < count; i++) {
        html += `<div class="project-card skeleton-card" style="animation-delay: ${i * 50}ms">
            <div class="skeleton" style="height: 140px; border-radius: var(--radius-md) var(--radius-md) 0 0;"></div>
            <div style="padding: 12px;">
                <div class="skeleton" style="height: 16px; width: 70%; margin-bottom: 8px; border-radius: 4px;"></div>
                <div class="skeleton" style="height: 12px; width: 40%; border-radius: 4px;"></div>
            </div>
        </div>`;
    }
    return html;
}

// ── Project Detail ───────────────────────────────────────────

function navigateToDetail(path) {
    // Navigate to the independent detail page
    window.location.href = `/detail?path=${enc(path)}`;
}

function renderProjectDetail(p) {
    const d = document.getElementById("projectDetail");
    const tags = p.tags.map(t => `<span class="tag-chip" data-tag="${esc(t)}">${esc(t)}</span>`).join("");
    const files = p.files.map(f => `<div class="file-item"><span class="file-item__icon">${catIcon(f.category)}</span><span class="file-item__name">${esc(f.name)}</span><span class="file-item__size">${esc(f.size_fmt)}</span><a class="file-item__download" href="/api/download/${enc(pathJoin(p.path, f.name))}" onclick="event.stopPropagation()">${icon('download')} ${t('action.download')}</a></div>`).join("");
    const images = p.images || [];
    const preview = p.thumbnail_url ? `<img src="${p.thumbnail_url}" alt=""><div class="project-detail__preview-hint">${t('info.click_preview')}</div>` : `<span style="font-size:48px;opacity:0.3">${icon('folder-open')}</span>`;
    const previewClick = p.thumbnail_url ? `data-images='${escAttr(JSON.stringify(images))}' data-index="0"` : "";

    // Build links HTML
    const urls = p.urls || [];
    const linksHtml = urls.length ? `<div class="project-detail__links"><div class="project-detail__links-title">${t('info.links')}</div>${urls.map(u => {
        const url = typeof u === "string" ? u : u.url || "";
        const label = typeof u === "string" ? u : u.label || u.url || "";
        return `<a class="project-detail__link" href="${escAttr(url)}" target="_blank" rel="noopener"><span class="project-detail__link-icon">${icon('link')}</span><span class="project-detail__link-text">${esc(label)}</span></a>`;
    }).join("")}</div>` : "";

    // Build notes HTML
    const notesHtml = p.notes ? `<div class="project-detail__notes">${esc(p.notes)}</div>` : "";

    d.innerHTML = `<button class="project-detail__back">&#8592; ${t('action.back')}</button><div class="project-detail__header"><div class="project-detail__preview" ${previewClick}>${preview}</div><div class="project-detail__info"><div class="project-detail__name">${esc(p.name)}</div><div class="project-detail__tags">${tags || `<span style="color:var(--text-muted)">${t('detail.no_tags')}</span>`}</div><div class="project-detail__meta">${t('detail.files', p.file_count)}  ·  ${esc(p.total_size_fmt)}${p.modified ? "  ·  " + new Date(p.modified * 1000).toLocaleDateString() : ""}</div>${linksHtml}${notesHtml}<div style="display:flex;gap:8px;margin-top:12px"><button class="project-detail__download">${icon('package')} ${t('action.download_all')}</button></div></div></div>${p.files.length ? `<div class="project-detail__files"><div class="project-detail__files-title">${t('detail.files_count', p.files.length)}</div>${files}</div>` : ""}`;
    initIcons();

    // Add event listeners
    d.querySelector(".project-detail__back").addEventListener("click", hideDetail);
    d.querySelector(".project-detail__download").addEventListener("click", () => { window.location.href = p.download_url; });

    // Tag chip clicks
    d.querySelectorAll(".tag-chip[data-tag]").forEach(chip => {
        chip.addEventListener("click", (e) => {
            e.stopPropagation();
            filterByTag(chip.dataset.tag);
        });
    });

    // Preview click
    if (p.thumbnail_url) {
        const previewEl = d.querySelector(".project-detail__preview");
        previewEl.addEventListener("click", function() {
            const imgs = JSON.parse(this.dataset.images || "[]");
            const idx = parseInt(this.dataset.index || "0");
            const fullUrl = imgs[idx] ? imgs[idx].url : p.thumbnail_url;
            openViewer(fullUrl, imgs, idx);
        });
    }
}

function showGrid() { state.viewMode = "grid"; document.getElementById("projectGrid").style.display = ""; document.getElementById("projectDetail").style.display = "none"; document.getElementById("viewGrid").classList.add("active"); document.getElementById("viewList").classList.remove("active"); }
function showDetail() { state.viewMode = "detail"; document.getElementById("projectGrid").style.display = "none"; document.getElementById("projectDetail").style.display = ""; }
function hideDetail() {
    showGrid();
    // Go back in history if we came from a detail view
    if (state.currentDetailPath) {
        state.currentDetailPath = null;
        // Replace state to grid view without adding new history entry
        pushHistory(state.currentPath);
    }
}

function pushDetailHistory(path) {
    state.currentDetailPath = path;
    try {
        window.history.pushState(
            { path: state.currentPath, detail: path },
            "",
            `?path=${encodeURIComponent(state.currentPath)}&detail=${encodeURIComponent(path)}`
        );
    } catch (e) { /* ignore */ }
}

// ── Info Panel ───────────────────────────────────────────────

async function showInfoPanel(path) {
    cancelPendingRequests();
    const abortController = new AbortController();
    currentAbortController = abortController;

    const panel = document.getElementById("infoPanel");
    panel.classList.add("open");
    document.getElementById("infoTitle").textContent = path.split("/").pop() || path;
    document.getElementById("infoPreview").innerHTML = '<div class="loading"><div class="spinner"></div></div>';
    document.getElementById("infoFields").innerHTML = "";
    document.getElementById("infoTagsSection").style.display = "none";
    document.getElementById("infoNotesSection").style.display = "none";
    try {
        const data = await api(`projects/${enc(path)}`, {}, abortController.signal);
        if (abortController.signal.aborted) return;
        renderInfoPanel(data);
    } catch (e) {
        if (e.name === "AbortError") return;
        document.getElementById("infoPreview").innerHTML = `<div class="empty-state"><div class="empty-state__icon">${icon('alert-triangle')}</div></div>`;
        initIcons();
    }
}

function renderInfoPanel(p) {
    const preview = document.getElementById("infoPreview");
    const images = p.images || [];
    const firstImageIndex = images.findIndex(img => img.thumb_url === p.thumbnail_url);

    if (p.thumbnail_url) {
        preview.innerHTML = `<img src="${p.thumbnail_url}" alt="" data-images='${escAttr(JSON.stringify(images))}' data-index="${firstImageIndex >= 0 ? firstImageIndex : 0}"><div class="info-panel__preview-hint">${t('info.click_preview')}</div>`;
        preview.querySelector("img").addEventListener("click", function() {
            const imgs = JSON.parse(this.dataset.images || "[]");
            const idx = parseInt(this.dataset.index || "0");
            const fullUrl = imgs[idx] ? imgs[idx].url : this.src;
            openViewer(fullUrl, imgs, idx);
        });
    } else {
        preview.innerHTML = `<span style="font-size:48px;opacity:0.3">${icon('folder-open')}</span>`;
        initIcons();
    }

    // Fields
    document.getElementById("infoFields").innerHTML = `
        <div class="info-panel__field"><span class="info-panel__field-label">${t('info.type')}</span><span class="info-panel__field-value">${t('info.type_project')}</span></div>
        <div class="info-panel__field"><span class="info-panel__field-label">${t('info.size')}</span><span class="info-panel__field-value">${esc(p.total_size_fmt)}</span></div>
        <div class="info-panel__field"><span class="info-panel__field-label">${t('info.files')}</span><span class="info-panel__field-value">${esc(String(p.file_count))}</span></div>
        <div class="info-panel__field"><span class="info-panel__field-label">${t('info.modified')}</span><span class="info-panel__field-value">${p.modified ? new Date(p.modified * 1000).toLocaleDateString() : "—"}</span></div>
        <div class="info-panel__field"><span class="info-panel__field-label">${t('info.path')}</span><span class="info-panel__field-value" style="font-size:11px;word-break:break-all">${esc(p.path)}</span></div>
    `;

    // Tags
    const ts = document.getElementById("infoTagsSection"), te = document.getElementById("infoTags");
    if (p.tags && p.tags.length) {
        ts.style.display = "";
        te.innerHTML = p.tags.map(t => `<span class="info-panel__tag" data-tag="${esc(t)}">${esc(t)}</span>`).join("");
        te.querySelectorAll(".info-panel__tag").forEach(tag => {
            tag.addEventListener("click", () => filterByTag(tag.dataset.tag));
        });
    } else {
        ts.style.display = "none";
    }

    // Links/URLs
    const ls = document.getElementById("infoLinksSection"), le = document.getElementById("infoLinks");
    if (p.urls && p.urls.length) {
        ls.style.display = "";
        le.innerHTML = p.urls.map(u => {
            const url = typeof u === "string" ? u : u.url || "";
            const label = typeof u === "string" ? u : u.label || u.url || "";
            return `<a class="info-panel__link" href="${escAttr(url)}" target="_blank" rel="noopener"><span class="info-panel__link-icon">${icon('link')}</span><span class="info-panel__link-text">${esc(label)}</span></a>`;
        }).join("");
        initIcons();
    } else {
        ls.style.display = "none";
    }

    // Notes
    const ns = document.getElementById("infoNotesSection"), ne = document.getElementById("infoNotes");
    if (p.notes) {
        ns.style.display = "";
        ne.textContent = p.notes;
    } else {
        ns.style.display = "none";
    }

    document.getElementById("infoDownload").onclick = () => { window.location.href = p.download_url; };
    document.getElementById("infoCopyPath").onclick = () => { navigator.clipboard.writeText(p.path); toast(t('status.path_copied'), "success"); };
    document.getElementById("infoOpenLocal").onclick = () => { toast(t('status.open_explorer'), "info"); };

    if (state.userRole === "guest") {
        document.getElementById("infoDownload").style.display = "none";
    }
}

function hideInfoPanel() {
    document.getElementById("infoPanel").classList.remove("open");
}

// ── Image Viewer ─────────────────────────────────────────────

const viewer = { scale: 1, pos: { x: 0, y: 0 }, start: { x: 0, y: 0 }, panning: false, clickStart: { time: 0, x: 0, y: 0 }, images: [], currentIndex: 0 };
let hintTimer = null;

function openViewer(src, images, index) {
    if (!src) return;
    const overlay = document.getElementById("imageViewer");
    const img = document.getElementById("imageViewerImg");
    const hint = document.getElementById("imageViewerHint");
    const prevBtn = document.getElementById("imageViewerPrev");
    const nextBtn = document.getElementById("imageViewerNext");
    const counter = document.getElementById("imageViewerCounter");

    // Store images array for navigation
    viewer.images = images || [];
    viewer.currentIndex = index || 0;

    img.setAttribute("src", src);
    resetViewer();
    clearTimeout(hintTimer);
    hint.classList.remove("visible");
    setTimeout(() => hint.classList.add("visible"), 10);
    hintTimer = setTimeout(() => hint.classList.remove("visible"), 4000);
    overlay.classList.add("visible");
    document.body.style.overflow = "hidden";

    // Update navigation
    updateViewerNavigation();
}

function closeViewer() {
    clearTimeout(hintTimer);
    const overlay = document.getElementById("imageViewer");
    const img = document.getElementById("imageViewerImg");
    overlay.classList.remove("visible");
    document.getElementById("imageViewerHint").classList.remove("visible");
    document.getElementById("imageViewerCounter").classList.remove("visible");
    document.body.style.overflow = "";

    // Free memory
    img.removeAttribute("src");
    viewer.images = [];
    viewer.currentIndex = 0;
}

function updateViewerNavigation() {
    const prevBtn = document.getElementById("imageViewerPrev");
    const nextBtn = document.getElementById("imageViewerNext");
    const counter = document.getElementById("imageViewerCounter");
    const hasMultiple = viewer.images.length > 1;

    prevBtn.style.display = hasMultiple ? "flex" : "none";
    nextBtn.style.display = hasMultiple ? "flex" : "none";

    if (hasMultiple) {
        prevBtn.disabled = viewer.currentIndex <= 0;
        nextBtn.disabled = viewer.currentIndex >= viewer.images.length - 1;
        counter.textContent = `${viewer.currentIndex + 1} / ${viewer.images.length}`;
        counter.classList.add("visible");
    } else {
        counter.classList.remove("visible");
    }
}

function navigateViewer(direction) {
    if (viewer.images.length <= 1) return;
    const newIndex = viewer.currentIndex + direction;
    if (newIndex < 0 || newIndex >= viewer.images.length) return;

    viewer.currentIndex = newIndex;
    const img = document.getElementById("imageViewerImg");
    const src = viewer.images[newIndex].url;

    // Smooth transition
    img.style.transition = "opacity 0.2s ease";
    img.style.opacity = "0";
    setTimeout(() => {
        img.setAttribute("src", src);
        resetViewer();
        img.style.opacity = "1";
    }, 200);

    updateViewerNavigation();
}

function resetViewer() {
    viewer.scale = 1; viewer.pos.x = 0; viewer.pos.y = 0;
    const img = document.getElementById("imageViewerImg");
    img.style.transition = "transform 0.2s cubic-bezier(0.25,0.46,0.45,0.94)";
    updateViewerTransform();
}

function updateViewerTransform() {
    const img = document.getElementById("imageViewerImg");
    img.style.transform = `translate(${viewer.pos.x}px,${viewer.pos.y}px) scale(${viewer.scale})`;
}

function handleViewerZoom(e) {
    e.preventDefault();
    const img = document.getElementById("imageViewerImg");
    const rect = img.getBoundingClientRect();
    const delta = -e.deltaY * 0.001;
    const newScale = Math.max(0.2, Math.min(10, viewer.scale * (1 + delta * 1.5)));
    const mx = e.clientX, my = e.clientY;
    const sx = mx - rect.left, sy = my - rect.top;
    const ratio = newScale / viewer.scale;
    viewer.pos.x = mx - (sx * ratio) - (rect.left - viewer.pos.x);
    viewer.pos.y = my - (sy * ratio) - (rect.top - viewer.pos.y);
    viewer.scale = newScale;
    img.style.transition = "transform 0.2s cubic-bezier(0.25,0.46,0.45,0.94)";
    updateViewerTransform();
}

function handleViewerMouseDown(e) {
    const img = document.getElementById("imageViewerImg");
    if (e.target === document.getElementById("imageViewer") && e.button === 0) { closeViewer(); return; }
    e.preventDefault();
    if (e.target === img && (e.button === 0 || e.button === 1)) {
        viewer.panning = true;
        viewer.start.x = e.clientX - viewer.pos.x;
        viewer.start.y = e.clientY - viewer.pos.y;
        img.classList.add("panning");
    }
    if (e.button === 1) { viewer.clickStart = { time: Date.now(), x: e.clientX, y: e.clientY }; }
}

function handleViewerMouseMove(e) {
    if (!viewer.panning) return;
    viewer.pos.x = e.clientX - viewer.start.x;
    viewer.pos.y = e.clientY - viewer.start.y;
    document.getElementById("imageViewerImg").style.transition = "none";
    updateViewerTransform();
}

function handleViewerMouseUp(e) {
    if (viewer.panning) {
        viewer.panning = false;
        document.getElementById("imageViewerImg").classList.remove("panning");
        document.getElementById("imageViewerImg").style.transition = "transform 0.2s cubic-bezier(0.25,0.46,0.45,0.94)";
    }
    if (e.button === 1 && Date.now() - viewer.clickStart.time < 250 && Math.hypot(e.clientX - viewer.clickStart.x, e.clientY - viewer.clickStart.y) < 10) {
        resetViewer();
    }
}

// ── Context Menu ─────────────────────────────────────────────

function showCtx(event, path, type) {
    event.preventDefault(); event.stopPropagation();
    contextItem = { path, type };
    const menu = document.getElementById("contextMenu");
    menu.querySelector('[data-action="downloadZip"]').style.display = type === "dir" ? "" : "none";
    menu.querySelector('[data-action="download"]').style.display = type === "file" ? "" : "none";
    menu.querySelector('[data-action="open"]').style.display = type === "dir" ? "" : "none";
    const x = Math.min(event.clientX, window.innerWidth - 220);
    const y = Math.min(event.clientY, window.innerHeight - 280);
    menu.style.left = x + "px"; menu.style.top = y + "px";
    menu.classList.add("visible");
}

function hideCtx() {
    document.getElementById("contextMenu").classList.remove("visible");
    contextItem = null;
}

function handleCtxAction(action) {
    if (!contextItem) return;
    const item = contextItem; hideCtx();
    switch (action) {
        case "open": nav(item.path); break;
        case "openExplorer": toast(t('status.open_explorer'), "info"); break;
        case "download": case "downloadZip": window.location.href = `/api/download/${enc(item.path)}`; break;
        case "share": showShareDialog(item.path); break;
        case "copyPath": navigator.clipboard.writeText(item.path); toast(t('status.path_copied'), "success"); break;
        case "copyLink": navigator.clipboard.writeText(`${location.origin}/api/download/${enc(item.path)}`); toast(t('status.link_copied'), "success"); break;
        case "details": showInfoPanel(item.path); break;
    }
}

// ── Share Dialog ─────────────────────────────────────────────

let sharePath = null;

function showShareDialog(path) {
    sharePath = path;
    const overlay = document.getElementById("shareOverlay");
    const subtitle = document.getElementById("shareSubtitle");
    const result = document.getElementById("shareResult");
    const actions = document.getElementById("shareActions");
    const error = document.getElementById("shareError");

    subtitle.textContent = `Share: ${path.split("/").pop() || path}`;
    result.style.display = "none";
    actions.style.display = "flex";
    error.style.display = "none";

    // Reset form
    document.getElementById("sharePassword").value = "";
    document.getElementById("shareExpiry").value = "24";
    document.getElementById("shareMaxDownloads").value = "";
    document.getElementById("shareAllowPreview").checked = true;

    overlay.style.display = "flex";
}

function hideShareDialog() {
    document.getElementById("shareOverlay").style.display = "none";
    sharePath = null;
}

async function createShareLink() {
    if (!sharePath) return;

    const password = document.getElementById("sharePassword").value.trim() || null;
    const expiresHours = document.getElementById("shareExpiry").value ? parseInt(document.getElementById("shareExpiry").value) : null;
    const maxDownloads = document.getElementById("shareMaxDownloads").value ? parseInt(document.getElementById("shareMaxDownloads").value) : null;
    const allowPreview = document.getElementById("shareAllowPreview").checked;
    const errorEl = document.getElementById("shareError");
    const resultEl = document.getElementById("shareResult");
    const actionsEl = document.getElementById("shareActions");

    errorEl.style.display = "none";

    try {
        const d = await apiPost("shares", {
            paths: [sharePath],
            password,
            expires_hours: expiresHours,
            max_downloads: maxDownloads,
            allow_preview: allowPreview,
        });

        if (d.error) {
            errorEl.textContent = d.error;
            errorEl.classList.add("visible");
            return;
        }

        // Show result with URL
        const shareUrl = d.url;
        document.getElementById("shareUrl").textContent = shareUrl;

        // Add key hint if required
        const keyHint = document.getElementById("shareKeyHint");
        if (d.requires_key) {
            keyHint.textContent = t('share.key_hint');
            keyHint.style.display = "block";
        } else {
            keyHint.style.display = "none";
        }

        resultEl.style.display = "block";
        actionsEl.style.display = "none";

        toast(t('status.share_created'), "success");
    } catch (e) {
        errorEl.textContent = e.message || t('error.create_share_failed');
        errorEl.classList.add("visible");
    }
}

function copyShareLink() {
    const url = document.getElementById("shareUrl").textContent;
    navigator.clipboard.writeText(url);
    toast(t('status.link_copied_clipboard'), "success");
}

// ── Sidebar Tree ─────────────────────────────────────────────

async function loadDirectoryTree() {
    const tree = document.getElementById("dirTree");
    try {
        const d = await api("tree");
        const nodes = d.tree || [];
        if (!nodes.length) { tree.innerHTML = `<div style="padding:12px;color:var(--text-muted);font-size:12px">${t('sidebar.empty')}</div>`; return; }
        tree.innerHTML = nodes.map(n => treeNode(n, 0)).join("");
        initIcons();
        // Add event listeners
        bindTreeEvents(tree);
    } catch (e) { tree.innerHTML = `<div style="padding:12px;color:var(--text-muted);font-size:12px">${t('sidebar.failed')}</div>`; }
}

function treeNode(node, depth) {
    const indent = Math.min(depth, 3);
    const indentCls = indent > 0 ? ` tree-item--indent-${indent}` : "";
    const hasChildren = node.children && node.children.length > 0;
    const isLeaf = node.is_leaf;
    const arrow = hasChildren ? '<span class="tree-item__arrow">&#9654;</span>' : '<span class="tree-item__arrow"></span>';
    const typeIcon = isLeaf ? icon('folder-open') : icon('folder');
    const dataType = isLeaf ? "leaf" : "folder";
    let h = `<div class="tree-item${indentCls}" data-path="${esc(node.path)}" data-type="${dataType}">${arrow}<span class="tree-item__icon">${typeIcon}</span><span class="tree-item__name">${esc(node.name)}</span></div>`;
    if (hasChildren) {
        h += `<div class="tree-children">`;
        h += node.children.map(c => treeNode(c, depth + 1)).join("");
        h += `</div>`;
    }
    return h;
}

function bindTreeEvents(container) {
    // Tree item clicks
    container.querySelectorAll(".tree-item").forEach(item => {
        item.addEventListener("click", (e) => {
            if (e.target.closest(".tree-item__arrow")) return;
            const path = item.dataset.path;
            const isLeaf = item.dataset.type === "leaf";
            if (isLeaf) navigateToDetail(path); else nav(path);
        });
    });

    // Arrow clicks
    container.querySelectorAll(".tree-item__arrow").forEach(arrow => {
        arrow.addEventListener("click", (e) => {
            e.stopPropagation();
            toggleTreeNode(arrow);
        });
    });
}

function toggleTreeNode(arrowEl) {
    const item = arrowEl.parentElement;
    const childrenDiv = item.nextElementSibling;
    if (!childrenDiv || !childrenDiv.classList.contains("tree-children")) return;
    const expanded = arrowEl.classList.contains("expanded");
    if (expanded) { arrowEl.classList.remove("expanded"); childrenDiv.classList.remove("expanded"); }
    else { arrowEl.classList.add("expanded"); childrenDiv.classList.add("expanded"); }
}

// ── Server Stats ──────────────────────────────────────────────

let statsTimer = null;

async function loadStats() {
    try {
        const d = await api("stats");
        document.getElementById("statConnections").textContent = d.connections || 0;
        document.getElementById("statRequests").textContent = d.requests || 0;
    } catch (e) {
        // Ignore errors
    }

    // Load library stats
    try {
        const d = await api("home");
        const stats = d.stats || {};
        document.getElementById("statProjectsMini").textContent = stats.total_projects || 0;
        document.getElementById("statTotalSizeMini").textContent = stats.total_size_fmt || "0 B";
    } catch (e) {
        // Ignore errors
    }
}

function startStatsPolling() {
    stopStatsPolling(); // Clear existing interval first
    loadStats();
    statsTimer = setInterval(() => {
        if (!document.hidden) loadStats();
    }, 5000); // Poll every 5 seconds, pause when hidden
}

function stopStatsPolling() {
    if (statsTimer) {
        clearInterval(statsTimer);
        statsTimer = null;
    }
}

// Pause/resume polling on visibility change
document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
        stopStatsPolling();
    } else {
        startStatsPolling();
        // Reconnect WebSocket if needed
        if (!ws || ws.readyState > WebSocket.OPEN) connectWebSocket();
    }
});

// ── Navigation ───────────────────────────────────────────────

function nav(path) {
    hideDetail(); hideInfoPanel(); hideCtx();
    document.getElementById("sidebar").classList.remove("open");
    document.getElementById("sidebarBackdrop").classList.remove("open");
    loadProjects(path);
}

function filterByTag(tag) { state.search = ""; document.getElementById("searchInput").value = ""; loadSearchResults("", tag); }

async function loadSearchResults(query, tag) {
    cancelPendingRequests();
    const abortController = new AbortController();
    currentAbortController = abortController;

    const grid = document.getElementById("projectGrid");
    grid.innerHTML = skeleton(4); showGrid(); hideInfoPanel();
    try {
        const d = await api("search", { q: query, tags: tag || "" }, abortController.signal);
        if (abortController.signal.aborted) return;
        const map = {};
        (d.results || []).forEach(r => {
            const parts = r.path.split("/");
            const pn = parts.length > 1 ? parts[parts.length - 2] : r.name;
            const pp = parts.slice(0, -1).join("/") || "";
            if (!map[pp]) map[pp] = { name: pn, path: pp, files: [], tags: [], is_project: true };
            map[pp].files.push(r);
        });
        state.projects = Object.values(map);
        renderBreadcrumb(tag ? `Tag: ${tag}` : `Search: ${query}`);
        renderProjects(state.projects);
        document.getElementById("projectCount").textContent = `${d.count} files in ${state.projects.length} projects`;
    } catch (e) {
        if (e.name === "AbortError") return;
    }
}

// ── Resize Grabbers ──────────────────────────────────────────

function startDrag(e, type) {
    e.preventDefault(); isDragging = true; dragType = type;
    document.body.classList.add("no-select");
    document.getElementById(type === "left" ? "leftGrabber" : "rightGrabber").classList.add("active-drag");
    // Add will-change hint to reduce layout thrashing
    document.getElementById("app").style.willChange = "grid-template-columns";
}

function stopDrag() {
    if (!isDragging) return;
    isDragging = false; document.body.classList.remove("no-select");
    document.getElementById("leftGrabber").classList.remove("active-drag");
    document.getElementById("rightGrabber").classList.remove("active-drag");
    document.getElementById("app").style.willChange = "";
    saveState();
}

let _rafId = null;
function onDrag(e) {
    if (!isDragging || !dragType) return;
    if (_rafId) return; // Throttle to rAF
    _rafId = requestAnimationFrame(() => {
        _rafId = null;
        const appRect = document.getElementById("app").getBoundingClientRect();
        if (dragType === "left") {
            const w = Math.max(150, Math.min(e.clientX - appRect.left, appRect.width * 0.4));
            document.documentElement.style.setProperty("--sidebar-w", w + "px");
        } else {
            const w = Math.max(200, Math.min(appRect.right - e.clientX, appRect.width * 0.4));
            document.documentElement.style.setProperty("--info-w", w + "px");
        }
    });
}

// ── localStorage Persistence ─────────────────────────────────

function saveState() {
    try {
        localStorage.setItem("am_sidebar_w", getComputedStyle(document.documentElement).getPropertyValue("--sidebar-w").trim());
        localStorage.setItem("am_info_w", getComputedStyle(document.documentElement).getPropertyValue("--info-w").trim());
        localStorage.setItem("am_sidebar_open", state.sidebarOpen);
        localStorage.setItem("am_info_open", state.infoOpen);
        localStorage.setItem("am_sort", state.sort);
        localStorage.setItem("am_order", state.order);
        localStorage.setItem("am_view", state.viewMode);
    } catch (e) { /* ignore */ }
}

function loadState() {
    try {
        const sw = localStorage.getItem("am_sidebar_w");
        if (sw) document.documentElement.style.setProperty("--sidebar-w", sw);
        const iw = localStorage.getItem("am_info_w");
        if (iw) document.documentElement.style.setProperty("--info-w", iw);
        const so = localStorage.getItem("am_sidebar_open");
        if (so === "false") { state.sidebarOpen = false; document.getElementById("app").classList.add("sidebar-collapsed"); }
        const io = localStorage.getItem("am_info_open");
        if (io === "false") { state.infoOpen = false; document.getElementById("app").classList.add("info-collapsed"); }
        const sort = localStorage.getItem("am_sort");
        if (sort) { state.sort = sort; document.getElementById("sortSelect").value = sort; }
        const order = localStorage.getItem("am_order");
        if (order) { state.order = order; document.getElementById("sortOrder").innerHTML = order === "asc" ? icon('arrow-up') : icon('arrow-down'); initIcons(); }
        // Load view mode
        const view = localStorage.getItem("am_view");
        if (view) {
            state.viewMode = view;
            if (view === "grid") {
                document.getElementById("viewGrid").classList.add("active");
                document.getElementById("viewList").classList.remove("active");
            } else {
                document.getElementById("viewList").classList.add("active");
                document.getElementById("viewGrid").classList.remove("active");
            }
        }
    } catch (e) { /* ignore */ }
}

// ── Browser History ──────────────────────────────────────────

function pushHistory(path) {
    try { window.history.pushState({ path }, "", `?path=${encodeURIComponent(path)}`); } catch (e) { /* ignore */ }
}

// ── Sidebar/Info Toggle ──────────────────────────────────────

function toggleSidebar() {
    if (isMobile()) {
        document.getElementById("sidebar").classList.toggle("open");
        document.getElementById("sidebarBackdrop").classList.toggle("open");
    } else {
        state.sidebarOpen = !state.sidebarOpen;
        document.getElementById("app").classList.toggle("sidebar-collapsed", !state.sidebarOpen);
        saveState();
    }
}

function toggleInfoPanel() {
    state.infoOpen = !state.infoOpen;
    document.getElementById("app").classList.toggle("info-collapsed", !state.infoOpen);
    saveState();
}

// ── User Menu ────────────────────────────────────────────────

function updateUserMenu(user) {
    if (!user) return;
    state.userRole = user.role || "guest";
    state.userPermissions = user.permissions || {};
    document.getElementById("userMenu").style.display = "";
    document.getElementById("userAvatar").textContent = (user.username || "U")[0].toUpperCase();
    document.getElementById("userName").textContent = user.username;
    document.getElementById("userInfo").textContent = `${user.username} · ${user.role}`;
    const statusEl = document.getElementById("headerRole");
    if (statusEl) {
        const roleLabel = user.role ? user.role.charAt(0).toUpperCase() + user.role.slice(1) : "Guest";
        statusEl.textContent = roleLabel;
        statusEl.className = `header__role-badge header__role-badge--${user.role || "guest"}`;
    }
    if (state.userRole === "guest") {
        document.querySelectorAll(".file-item__download, .project-detail__download").forEach(el => {
            el.style.display = "none";
        });
    }
}

// ── Toast ────────────────────────────────────────────────────

function toast(msg, type = "info") {
    const c = document.getElementById("toastContainer");
    const t = document.createElement("div");
    t.className = `toast toast--${type}`; t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => {
        t.classList.add("toast--exit");
        setTimeout(() => t.remove(), 300);
    }, 3000);
}

// ── Download Progress ─────────────────────────────────────────

function showProgressBar() {
    let bar = document.getElementById("downloadProgressBar");
    if (!bar) {
        bar = document.createElement("div");
        bar.id = "downloadProgressBar";
        bar.className = "progress-bar";
        bar.innerHTML = '<div class="progress-bar__fill"></div>';
        document.body.appendChild(bar);
    }
    bar.classList.add("active");
    bar.querySelector(".progress-bar__fill").style.width = "0%";
}

function updateProgressBar(ratio) {
    const bar = document.getElementById("downloadProgressBar");
    if (bar) {
        bar.querySelector(".progress-bar__fill").style.width = `${Math.min(100, Math.round(ratio * 100))}%`;
    }
}

function hideProgressBar() {
    const bar = document.getElementById("downloadProgressBar");
    if (bar) {
        bar.querySelector(".progress-bar__fill").style.width = "100%";
        setTimeout(() => bar.classList.remove("active"), 300);
    }
}

async function downloadWithProgress(url, filename) {
    try {
        const resp = await fetch(url);
        const reader = resp.body.getReader();
        const contentLength = +resp.headers.get("Content-Length");
        let received = 0;
        const chunks = [];
        showProgressBar();
        while (true) {
            const {done, value} = await reader.read();
            if (done) break;
            chunks.push(value);
            received += value.length;
            if (contentLength) updateProgressBar(received / contentLength);
        }
        hideProgressBar();
        const blob = new Blob(chunks);
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
    } catch (e) {
        hideProgressBar();
        toast(t('status.download_failed'), "error");
    }
}

// ── Auth ─────────────────────────────────────────────────────

async function checkAuth() {
    try {
        const info = await api("info");
        document.getElementById("shareName").textContent = info.share_name || "";
        document.title = `${info.share_name || "AssetManager"} Share`;
        if (info.theme_color) document.documentElement.style.setProperty("--accent", info.theme_color);
        if (info.welcome_msg) { const el = document.getElementById("welcomeMsg"); if (el) { el.textContent = info.welcome_msg; el.style.display = ""; } }
        if (info.footer_text) { const el = document.getElementById("footerText"); if (el) { el.textContent = info.footer_text; el.style.display = ""; } }

        state.authEnabled = info.auth_enabled;
        state.authMode = info.auth_mode;

        // Check URL for key parameter
        const urlParams = new URLSearchParams(window.location.search);
        const urlKey = urlParams.get("key");
        if (urlKey) {
            try {
                const d = await apiPost("auth/verify_key", { key: urlKey });
                if (d.token) {
                    // Cookie is set by server automatically
                    window.history.replaceState({}, "", window.location.pathname);
                    return true;
                }
            } catch (e) { /* invalid key, show login */ }
        }

        // Check no-auth marker (for when auth is disabled)
        const noAuth = sessionStorage.getItem("lan_no_auth");
        if (noAuth) {
            return true;
        }

        // Try to access a protected endpoint to check if we're already authenticated
        try {
            await api("home");
            return true; // Already authenticated (cookie is valid)
        } catch (e) {
            // Not authenticated
        }

        // If auth enabled (any mode), show Login Overlay
        if (info.auth_enabled) {
            showLogin(info.auth_mode);
            return false;
        }

        // No auth required - show Landing Page
        updateLandingPage(info);
        return false;
    } catch (e) { return false; }
}

function updateLandingPage(info) {
    const subtitle = document.getElementById("landingSubtitle");
    const enterBtn = document.getElementById("landingEnterBtn");

    // Update subtitle with library name and stats
    let subtitleText = info.share_name || "Asset Library";
    if (info.library_stats) {
        const stats = info.library_stats;
        subtitleText += ` — ${stats.total_projects} projects · ${stats.total_size_fmt}`;
    }
    subtitle.textContent = subtitleText;

    // Apply theme color
    if (info.theme_color) {
        document.documentElement.style.setProperty("--accent", info.theme_color);
    }

    // Focus enter button
    setTimeout(() => enterBtn.focus(), 100);
}

function showLogin(authMode) {
    document.getElementById("loginOverlay").style.display = "";
    document.getElementById("registerOverlay").style.display = "none";
    document.getElementById("landingPage").classList.add("hidden");

    const keyMode = document.getElementById("loginKeyMode");
    const userMode = document.getElementById("loginUserMode");
    const subtitle = document.getElementById("loginSubtitle");

    if (authMode === "user") {
        keyMode.style.display = "none";
        userMode.style.display = "";
        subtitle.textContent = t('auth.login_subtitle_user');
        document.getElementById("loginUsername").focus();
    } else if (authMode === "key") {
        // Default: key mode
        keyMode.style.display = "";
        userMode.style.display = "none";
        subtitle.textContent = t('auth.login_subtitle_key');
        document.getElementById("loginKey").focus();
    } else {
        // Unknown auth mode - show both options
        keyMode.style.display = "";
        userMode.style.display = "";
        subtitle.textContent = t('auth.login_subtitle_both');
        document.getElementById("loginKey").focus();
    }
}

function hideLogin() {
    document.getElementById("loginOverlay").style.display = "none";
    document.getElementById("loginKeyError").style.display = "none";
    document.getElementById("loginError").style.display = "none";
    document.getElementById("landingPage").classList.add("hidden");
}

function showRegister() {
    document.getElementById("registerOverlay").style.display = "";
    document.getElementById("loginOverlay").style.display = "none";
    document.getElementById("regUsername").focus();
}

function hideRegister() {
    document.getElementById("registerOverlay").style.display = "none";
    document.getElementById("regError").style.display = "none";
}

async function handleKeyLogin() {
    const key = document.getElementById("loginKey").value.trim();
    if (!key) return;
    const btn = document.getElementById("loginKeySubmit");
    await withLoading(btn, async () => {
        try {
            const d = await apiPost("auth/verify_key", { key });
            if (d.token) {
                // Cookie is set by server automatically
                hideLogin();
                hideLandingPage();
                initApp();
            } else {
                document.getElementById("loginKeyError").classList.add("visible");
            }
        } catch (e) {
            document.getElementById("loginKeyError").classList.add("visible");
        }
    });
}

async function handleLogin() {
    const username = document.getElementById("loginUsername").value.trim();
    const password = document.getElementById("loginPassword").value;
    const btn = document.getElementById("loginSubmit");
    await withLoading(btn, async () => {
        try {
            const d = await apiPost("auth/login", { username, password });
            if (d.token) {
                // Cookie is set by server automatically
                state.user = d.user || null;
                if (state.user) {
                    state.userRole = state.user.role || "user";
                    state.userPermissions = state.user.permissions || {};
                }
                hideLogin();
                hideLandingPage();
                if (state.user) updateUserMenu(state.user);
                initApp();
            } else {
                document.getElementById("loginError").classList.add("visible");
            }
        } catch (e) {
            document.getElementById("loginError").classList.add("visible");
        }
    });
}

async function handleRegister() {
    const username = document.getElementById("regUsername").value.trim();
    const password = document.getElementById("regPassword").value;
    const confirm = document.getElementById("regConfirm").value;
    const inviteCode = document.getElementById("regInvite").value.trim();
    const errEl = document.getElementById("regError");

    // Client-side validation
    if (!username) { errEl.textContent = t('error.username_required'); errEl.classList.add("visible"); return; }
    if (username.length < 2) { errEl.textContent = t('error.username_min'); errEl.classList.add("visible"); return; }
    if (!/^[a-zA-Z0-9_-]+$/.test(username)) { errEl.textContent = t('error.username_chars'); errEl.classList.add("visible"); return; }

    // Password strength validation
    if (password.length < 8) { errEl.textContent = t('error.password_min'); errEl.classList.add("visible"); return; }
    if (password.length > 128) { errEl.textContent = t('error.password_max'); errEl.classList.add("visible"); return; }

    const weakPasswords = ["password", "12345678", "qwerty123", "admin123", "letmein", "welcome1", "monkey123", "dragon12", "master12", "abc12345"];
    if (weakPasswords.includes(password.toLowerCase())) { errEl.textContent = t('error.password_common'); errEl.classList.add("visible"); return; }

    const hasUpper = /[A-Z]/.test(password);
    const hasLower = /[a-z]/.test(password);
    const hasDigit = /[0-9]/.test(password);
    const hasSpecial = /[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(password);

    const missing = [];
    if (!hasUpper) missing.push(t('error.password_uppercase'));
    if (!hasLower) missing.push(t('error.password_lowercase'));
    if (!hasDigit) missing.push(t('error.password_digit'));
    if (!hasSpecial) missing.push(t('error.password_special'));

    if (missing.length > 0) {
        errEl.textContent = t('error.password_requirement', missing.join(", "));
        errEl.classList.add("visible");
        return;
    }

    if (password !== confirm) { errEl.textContent = t('error.passwords_no_match'); errEl.classList.add("visible"); return; }

    const btn = document.getElementById("regSubmit");
    await withLoading(btn, async () => {
        try {
            const body = { username, password }; if (inviteCode) body.invite_code = inviteCode;
            const d = await apiPost("auth/register", body);
            if (d.user_id) {
                hideRegister();
                showLogin("user");
                document.getElementById("loginUsername").value = username;
                document.getElementById("loginPassword").value = "";
                document.getElementById("loginPassword").focus();
                toast(t('status.account_created'), "success");
            } else {
                errEl.textContent = d.error || t('error.registration_failed');
                errEl.classList.add("visible");
            }
        } catch (e) {
            errEl.textContent = t('error.registration_failed');
            errEl.classList.add("visible");
        }
    });
}

// ── WebSocket ────────────────────────────────────────────────

let ws = null;
let wsReconnectDelay = 3000;  // Initial delay: 3 seconds
const WS_MAX_DELAY = 60000;   // Max delay: 60 seconds
const WS_BACKOFF_FACTOR = 2;  // Double the delay on each failure

function connectWebSocket() {
    if (ws && ws.readyState <= WebSocket.OPEN) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${location.host}/ws`);

    ws.onopen = () => {
        // Reset delay on successful connection
        wsReconnectDelay = 3000;
    };

    ws.onmessage = (e) => {
        try {
            const m = JSON.parse(e.data);
            if (m.type === "files_changed") loadProjects(state.currentPath);
        } catch (err) { /* ignore */ }
    };

    ws.onclose = () => {
        if (document.readyState !== "unloading") {
            // Exponential backoff: 3s, 6s, 12s, 24s, 48s, 60s (max)
            setTimeout(connectWebSocket, wsReconnectDelay);
            wsReconnectDelay = Math.min(wsReconnectDelay * WS_BACKOFF_FACTOR, WS_MAX_DELAY);
        }
    };
}

// ── Utilities ────────────────────────────────────────────────

function catIcon(c) { const m = { images: icon('image'), "3d": icon('box'), videos: icon('film'), documents: icon('file-text'), archives: icon('package'), folder: icon('folder-open'), other: icon('file-text') }; return m[c] || m.other; }
const _escMap = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const _escRe = /[&<>"']/g;
function esc(s) { return (s || "").replace(_escRe, c => _escMap[c]); }
function escAttr(s) { return (s || "").replace(_escRe, c => _escMap[c]); }
function enc(s) { return encodeURIComponent(s || ""); }
function pathJoin(...p) { return p.filter(Boolean).join("/"); }

function withLoading(btn, asyncFn) {
    btn.classList.add("btn--loading");
    btn.disabled = true;
    return asyncFn().finally(() => {
        btn.classList.remove("btn--loading");
        btn.disabled = false;
    });
}

// ── Event Bindings ───────────────────────────────────────────

function bindEvents() {
    if (eventsBound) return; eventsBound = true;

    // Sidebar toggle
    document.getElementById("menuToggle").addEventListener("click", toggleSidebar);
    document.getElementById("toggleSidebar").addEventListener("click", toggleSidebar);
    document.getElementById("toggleInfo").addEventListener("click", toggleInfoPanel);
    document.getElementById("sidebarBackdrop").addEventListener("click", () => { document.getElementById("sidebar").classList.remove("open"); document.getElementById("sidebarBackdrop").classList.remove("open"); });

    // Sidebar controls
    document.getElementById("expandAll").addEventListener("click", () => {
        document.querySelectorAll(".tree-children").forEach(el => {
            el.classList.add("expanded");
            const arrow = el.previousElementSibling?.querySelector(".tree-item__arrow");
            if (arrow) arrow.classList.add("expanded");
        });
    });
    document.getElementById("collapseAll").addEventListener("click", () => {
        document.querySelectorAll(".tree-children").forEach(el => {
            el.classList.remove("expanded");
            const arrow = el.previousElementSibling?.querySelector(".tree-item__arrow");
            if (arrow) arrow.classList.remove("expanded");
        });
    });
    document.getElementById("sidebarSearch").addEventListener("input", (e) => {
        const f = e.target.value.toLowerCase();
        document.querySelectorAll(".tree-item").forEach(el => { const n = el.querySelector(".tree-item__name"); if (n) el.style.display = (!f || n.textContent.toLowerCase().includes(f)) ? "" : "none"; });
    });

    // Resize grabbers
    document.getElementById("leftGrabber").addEventListener("mousedown", (e) => startDrag(e, "left"));
    document.getElementById("rightGrabber").addEventListener("mousedown", (e) => startDrag(e, "right"));
    document.addEventListener("mousemove", onDrag);
    document.addEventListener("mouseup", stopDrag);

    // Info panel close
    document.getElementById("infoPanelClose").addEventListener("click", hideInfoPanel);

    // Search
    const searchInput = document.getElementById("searchInput");
    searchInput.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = searchInput.value; if (state.search) loadSearchResults(state.search); else loadProjects(state.currentPath); }, 200); });

    // Sort
    document.getElementById("sortSelect").addEventListener("change", (e) => { state.sort = e.target.value; loadProjects(state.currentPath); });
    document.getElementById("sortOrder").addEventListener("click", () => { state.order = state.order === "asc" ? "desc" : "asc"; document.getElementById("sortOrder").innerHTML = state.order === "asc" ? icon('arrow-up') : icon('arrow-down'); initIcons(); loadProjects(state.currentPath); });

    // View mode
    document.getElementById("viewGrid").addEventListener("click", () => { state.viewMode = "grid"; document.getElementById("viewGrid").classList.add("active"); document.getElementById("viewList").classList.remove("active"); renderProjects(state.projects); saveState(); });
    document.getElementById("viewList").addEventListener("click", () => { state.viewMode = "list"; document.getElementById("viewList").classList.add("active"); document.getElementById("viewGrid").classList.remove("active"); renderProjects(state.projects); saveState(); });

    // Batch actions
    document.getElementById("batchDownload").addEventListener("click", batchDownload);
    document.getElementById("batchClear").addEventListener("click", clearSelection);

    // Bottom bar (mobile)
    const mobileMenuBtn = document.getElementById("mobileMenuBtn");
    const mobileViewBtn = document.getElementById("mobileViewBtn");
    const mobileInfoBtn = document.getElementById("mobileInfoBtn");
    const mobileSelectBtn = document.getElementById("mobileSelectBtn");
    if (mobileMenuBtn) mobileMenuBtn.addEventListener("click", toggleSidebar);
    if (mobileViewBtn) mobileViewBtn.addEventListener("click", () => {
        state.viewMode = state.viewMode === "grid" ? "list" : "grid";
        mobileViewBtn.textContent = state.viewMode === "grid" ? t('mobile.grid') : t('mobile.list');
        renderProjects(state.projects);
        saveState();
    });
    if (mobileInfoBtn) mobileInfoBtn.addEventListener("click", toggleInfoPanel);
    if (mobileSelectBtn) mobileSelectBtn.addEventListener("click", toggleBatchMode);

    // User menu
    document.getElementById("userBtn").addEventListener("click", () => { document.getElementById("userDropdown").classList.toggle("open"); });
    document.getElementById("logoutBtn").addEventListener("click", async () => {
        // Call server to clear cookie
        try {
            await apiPost("auth/logout", {});
        } catch (e) { /* ignore */ }
        sessionStorage.removeItem("lan_no_auth");
        state.token = null;
        state.user = null;
        document.getElementById("userMenu").style.display = "none";
        showLogin();
    });

    // Auth - Key login
    document.getElementById("loginKeySubmit").addEventListener("click", handleKeyLogin);
    document.getElementById("loginKey").addEventListener("keydown", (e) => { if (e.key === "Enter") handleKeyLogin(); });

    // Auth - User login
    document.getElementById("loginSubmit").addEventListener("click", handleLogin);
    document.getElementById("loginPassword").addEventListener("keydown", (e) => { if (e.key === "Enter") handleLogin(); });
    document.getElementById("regSubmit").addEventListener("click", handleRegister);
    document.getElementById("regConfirm").addEventListener("keydown", (e) => { if (e.key === "Enter") handleRegister(); });
    document.getElementById("showRegister").addEventListener("click", (e) => { e.preventDefault(); showRegister(); });
    document.getElementById("showLogin").addEventListener("click", (e) => { e.preventDefault(); hideRegister(); showLogin(); });

    // Share dialog
    document.getElementById("shareCreateBtn").addEventListener("click", createShareLink);
    document.getElementById("shareCopyBtn").addEventListener("click", copyShareLink);
    document.getElementById("shareCancelBtn").addEventListener("click", hideShareDialog);
    document.getElementById("shareOverlay").addEventListener("click", (e) => { if (e.target === document.getElementById("shareOverlay")) hideShareDialog(); });

    // Landing page
    document.getElementById("landingEnterBtn").addEventListener("click", handleLandingEnter);
    document.getElementById("landingEnterBtn").addEventListener("keydown", (e) => { if (e.key === "Enter") handleLandingEnter(); });

    // Image viewer
    document.getElementById("imageViewer").addEventListener("wheel", handleViewerZoom, { passive: false });
    document.getElementById("imageViewer").addEventListener("mousedown", handleViewerMouseDown);
    document.addEventListener("mousemove", handleViewerMouseMove);
    document.addEventListener("mouseup", handleViewerMouseUp);
    document.getElementById("imageViewerClose").addEventListener("click", closeViewer);
    document.getElementById("imageViewerPrev").addEventListener("click", () => navigateViewer(-1));
    document.getElementById("imageViewerNext").addEventListener("click", () => navigateViewer(1));

    // Context menu
    document.getElementById("contextMenu").addEventListener("click", (e) => { const item = e.target.closest(".context-menu__item"); if (item) handleCtxAction(item.dataset.action); });
    document.addEventListener("click", hideCtx);
    document.addEventListener("contextmenu", (e) => { if (!e.target.closest(".project-card") && !e.target.closest(".folder-card") && !e.target.closest(".tree-item")) hideCtx(); });

    // Browser history - handle back/forward navigation
    window.addEventListener("popstate", (e) => {
        if (e.state) {
            hideInfoPanel();
            if (e.state.detail) {
                // Navigate to detail view
                navigateToDetail(e.state.detail);
            } else if (e.state.path) {
                // Navigate to grid view
                hideDetail();
                loadProjects(e.state.path);
            }
        }
    });

    // Keyboard
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") {
            if (document.getElementById("imageViewer").classList.contains("visible")) closeViewer();
            else if (document.getElementById("infoPanel").classList.contains("open")) hideInfoPanel();
            else if (state.viewMode === "detail") hideDetail();
        }
        if (e.key === "/" && !e.target.closest("input, textarea")) { e.preventDefault(); searchInput.focus(); }
        // Image viewer navigation
        if (document.getElementById("imageViewer").classList.contains("visible")) {
            if (e.key === "ArrowLeft") { e.preventDefault(); navigateViewer(-1); }
            if (e.key === "ArrowRight") { e.preventDefault(); navigateViewer(1); }
        }
    });

    // Close dropdowns
    document.addEventListener("click", (e) => { if (!e.target.closest(".app-header__user")) document.getElementById("userDropdown").classList.remove("open"); });
}

// ── Init ─────────────────────────────────────────────────────

async function init() {
    const info = await checkAuth();
    
    // If auth returned false, it means we need to show landing/login
    if (!info) return;
    
    // Auth passed (token exists), hide landing and show app
    hideLandingPage();
    initApp();
}

function initApp() {
    loadState();
    loadThumbCache(); // Load thumbnail cache from sessionStorage
    bindEvents();
    // Read path from URL if present
    const urlParams = new URLSearchParams(window.location.search);
    const urlPath = urlParams.get("path") || "";
    loadProjects(urlPath);
    loadDirectoryTree();
    connectWebSocket();
    startStatsPolling();
}

document.addEventListener("DOMContentLoaded", init);
