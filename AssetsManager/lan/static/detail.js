/* ═══════════════════════════════════════════════════════════════
   AssetManager — Project Detail Page
   ═══════════════════════════════════════════════════════════════ */

const state = {
    path: "",
    project: null,
    token: null,
    images: [],
    currentImageIndex: 0,
};

// ── Utilities ────────────────────────────────────────────────

const escMap = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const escRe = /[&<>"']/g;
function esc(s) { return (s || "").replace(escRe, c => escMap[c]); }
function enc(s) { return encodeURIComponent(s || ""); }

function formatSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return `${bytes.toFixed(1)} ${units[i]}`;
}

function catIcon(ext) {
    const map = {
        ".png": "&#128444;", ".jpg": "&#128444;", ".jpeg": "&#128444;", ".gif": "&#128444;", ".webp": "&#128444;",
        ".blend": "&#128302;", ".fbx": "&#128302;", ".obj": "&#128302;", ".gltf": "&#128302;",
        ".mp4": "&#127916;", ".mov": "&#127916;", ".avi": "&#127916;",
        ".zip": "&#128230;", ".rar": "&#128230;", ".7z": "&#128230;",
        ".txt": "&#128196;", ".pdf": "&#128196;", ".docx": "&#128196;",
    };
    return map[ext] || "&#128196;";
}

function toast(msg, type = "info") {
    const c = document.getElementById("toastContainer");
    const t = document.createElement("div");
    t.className = `toast toast--${type}`;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => {
        t.classList.add("toast--exit");
        setTimeout(() => t.remove(), 300);
    }, 3000);
}

// ── API ──────────────────────────────────────────────────────

async function api(ep, params = {}) {
    const url = new URL(`/api/${ep}`, location.origin);
    Object.entries(params).forEach(([k, v]) => { if (v != null && v !== "") url.searchParams.set(k, v); });
    const h = {};
    if (state.token) h["Authorization"] = `Bearer ${state.token}`;
    const r = await fetch(url, { headers: h });
    if (r.status === 401) {
        window.location.href = "/";
        throw new Error("Unauthorized");
    }
    if (!r.ok) {
        const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
        throw new Error(err.error || `Request failed with status ${r.status}`);
    }
    return r.json();
}

async function apiPost(ep, body) {
    const h = { "Content-Type": "application/json" };
    if (state.token) h["Authorization"] = `Bearer ${state.token}`;
    const r = await fetch(`/api/${ep}`, { method: "POST", headers: h, body: JSON.stringify(body) });
    if (!r.ok) {
        const err = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
        throw new Error(err.error || `Request failed with status ${r.status}`);
    }
    return r.json();
}

// ── Project Loading ──────────────────────────────────────────

async function loadProject(path) {
    state.path = path;
    showLoading();

    try {
        const data = await api(`projects/${enc(path)}`);
        state.project = data;
        state.images = data.images || [];
        renderProject(data);
        showContent();
    } catch (e) {
        showError(e.message || "Failed to load project");
    }
}

// ── Rendering ────────────────────────────────────────────────

function renderProject(p) {
    // Update title
    document.title = `${p.name} - AssetManager`;
    document.getElementById("projectName").textContent = p.name;

    // Breadcrumb
    renderBreadcrumb(p.path);

    // Meta
    const metaHtml = [
        `<span>${t('detail.files', p.file_count)}</span>`,
        `<span>${p.total_size_fmt}</span>`,
        p.modified ? `<span>${new Date(p.modified * 1000).toLocaleDateString()}</span>` : "",
    ].filter(Boolean).join(" &middot; ");
    document.getElementById("projectMeta").innerHTML = metaHtml;
    document.getElementById("fileCount").textContent = p.file_count;

    // Hero preview
    renderHeroPreview(p);

    // Tags
    renderTags(p.tags || []);

    // Links
    renderLinks(p.urls || []);

    // Notes
    renderNotes(p.notes);

    // Gallery
    renderGallery(state.images);

    // Files
    renderFiles(p.files || []);

    // Download button
    document.getElementById("heroDownload").onclick = () => {
        window.location.href = p.download_url;
    };
    document.getElementById("downloadBtn").onclick = () => {
        window.location.href = p.download_url;
    };
}

function renderBreadcrumb(path) {
    const el = document.getElementById("breadcrumb");
    const parts = path ? path.split("/").filter(Boolean) : [];
    let h = `<span class="detail-breadcrumb__item" onclick="window.location.href='/'">Root</span>`;
    let acc = "";
    for (let i = 0; i < parts.length; i++) {
        acc += (acc ? "/" : "") + parts[i];
        h += `<span class="detail-breadcrumb__sep">/</span><span class="detail-breadcrumb__item${i === parts.length - 1 ? " active" : ""}" onclick="window.location.href='/?path=${enc(acc)}'">${esc(parts[i])}</span>`;
    }
    el.innerHTML = h;
}

function renderHeroPreview(p) {
    const el = document.getElementById("heroPreview");
    if (p.thumbnail_url && state.images.length > 0) {
        const firstImg = state.images[0];
        el.innerHTML = `<img src="${firstImg.url}" alt="${esc(p.name)}" id="heroImage">`;
        el.onclick = () => openImageViewer(0);
    } else if (p.thumbnail_url) {
        el.innerHTML = `<img src="${p.thumbnail_url}" alt="${esc(p.name)}">`;
    } else {
        el.innerHTML = `<div class="detail-hero__placeholder">&#128193;</div>`;
    }
}

function renderTags(tags) {
    const el = document.getElementById("projectTags");
    if (tags.length) {
        el.innerHTML = tags.map(t => `<span class="detail-tag">${esc(t)}</span>`).join("");
    } else {
        el.innerHTML = `<span class="detail-hero__no-tags">${t('detail.no_tags')}</span>`;
    }
}

function renderLinks(urls) {
    const section = document.getElementById("linksSection");
    const el = document.getElementById("linksList");
    if (urls.length) {
        section.style.display = "";
        el.innerHTML = urls.map(u => {
            const url = typeof u === "string" ? u : u.url || "";
            const label = typeof u === "string" ? u : u.label || u.url || "";
            return `<a class="detail-link" href="${esc(url)}" target="_blank" rel="noopener">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                <span>${esc(label)}</span>
            </a>`;
        }).join("");
    } else {
        section.style.display = "none";
    }
}

function renderNotes(notes) {
    const section = document.getElementById("notesSection");
    const el = document.getElementById("notesContent");
    if (notes && notes.trim()) {
        section.style.display = "";
        el.textContent = notes;
    } else {
        section.style.display = "none";
    }
}

function renderGallery(images) {
    const section = document.getElementById("gallerySection");
    const el = document.getElementById("galleryGrid");
    if (images.length > 0) {
        section.style.display = "";
        el.innerHTML = images.map((img, i) => `
            <div class="detail-gallery__item" data-index="${i}">
                <img src="${img.thumb_url}" alt="${esc(img.name)}" loading="lazy">
                <div class="detail-gallery__name">${esc(img.name)}</div>
            </div>
        `).join("");
        el.querySelectorAll(".detail-gallery__item").forEach(item => {
            item.addEventListener("click", () => openImageViewer(parseInt(item.dataset.index)));
        });
    } else {
        section.style.display = "none";
    }
}

function renderFiles(files) {
    const el = document.getElementById("filesList");
    el.innerHTML = files.map(f => `
        <div class="detail-file">
            <span class="detail-file__icon">${catIcon(f.extension)}</span>
            <span class="detail-file__name">${esc(f.name)}</span>
            <span class="detail-file__size">${f.size_fmt}</span>
            <a class="detail-file__download" href="/api/download/${enc(state.path + '/' + f.name)}" onclick="event.stopPropagation()">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            </a>
        </div>
    `).join("");
}

// ── Image Viewer ─────────────────────────────────────────────

function openImageViewer(index) {
    if (!state.images.length) return;
    state.currentImageIndex = index;
    const overlay = document.getElementById("imageViewer");
    const img = document.getElementById("imageViewerImg");
    const counter = document.getElementById("imageViewerCounter");

    img.src = state.images[index].url;
    if (state.images.length > 1) {
        counter.textContent = `${index + 1} / ${state.images.length}`;
        counter.classList.add("visible");
        document.getElementById("imageViewerPrev").style.display = "flex";
        document.getElementById("imageViewerNext").style.display = "flex";
        document.getElementById("imageViewerPrev").disabled = index === 0;
        document.getElementById("imageViewerNext").disabled = index === state.images.length - 1;
    } else {
        counter.classList.remove("visible");
        document.getElementById("imageViewerPrev").style.display = "none";
        document.getElementById("imageViewerNext").style.display = "none";
    }

    overlay.classList.add("visible");
    document.body.style.overflow = "hidden";
}

function closeImageViewer() {
    document.getElementById("imageViewer").classList.remove("visible");
    document.body.style.overflow = "";
    document.getElementById("imageViewerImg").removeAttribute("src");
}

function navigateImage(direction) {
    const newIndex = state.currentImageIndex + direction;
    if (newIndex >= 0 && newIndex < state.images.length) {
        openImageViewer(newIndex);
    }
}

// ── Share Dialog ─────────────────────────────────────────────

function showShareDialog() {
    document.getElementById("shareOverlay").style.display = "flex";
    document.getElementById("shareResult").style.display = "none";
    document.getElementById("shareActions").style.display = "flex";
    document.getElementById("shareError").style.display = "none";
}

function hideShareDialog() {
    document.getElementById("shareOverlay").style.display = "none";
}

async function createShareLink() {
    const password = document.getElementById("sharePassword").value.trim() || null;
    const expiresHours = document.getElementById("shareExpiry").value ? parseInt(document.getElementById("shareExpiry").value) : null;
    const errorEl = document.getElementById("shareError");

    try {
        const d = await apiPost("shares", {
            paths: [state.path],
            password,
            expires_hours: expiresHours,
        });

        if (d.error) {
            errorEl.textContent = d.error;
            errorEl.style.display = "";
            return;
        }

        document.getElementById("shareUrl").textContent = d.url;
        document.getElementById("shareResult").style.display = "block";
        document.getElementById("shareActions").style.display = "none";
        toast(t('status.share_created'), "success");
    } catch (e) {
        errorEl.textContent = e.message || t('error.create_share_failed');
        errorEl.style.display = "";
    }
}

// ── State Helpers ────────────────────────────────────────────

function showLoading() {
    document.getElementById("loadingState").style.display = "flex";
    document.getElementById("errorState").style.display = "none";
    document.getElementById("projectContent").style.display = "none";
}

function showError(msg) {
    document.getElementById("loadingState").style.display = "none";
    document.getElementById("errorState").style.display = "flex";
    document.getElementById("projectContent").style.display = "none";
    document.getElementById("errorMessage").textContent = msg;
}

function showContent() {
    document.getElementById("loadingState").style.display = "none";
    document.getElementById("errorState").style.display = "none";
    document.getElementById("projectContent").style.display = "block";
}

// ── Auth ─────────────────────────────────────────────────────

function checkAuth() {
    const saved = sessionStorage.getItem("lan_token");
    if (saved) state.token = saved;

    // Check URL for key parameter
    const urlParams = new URLSearchParams(window.location.search);
    const urlKey = urlParams.get("key");
    if (urlKey) {
        apiPost("auth/verify_key", { key: urlKey }).then(d => {
            if (d.token) {
                state.token = d.token;
                sessionStorage.setItem("lan_token", d.token);
                window.history.replaceState({}, "", window.location.pathname + "?path=" + encodeURIComponent(state.path));
            }
        }).catch(() => {});
    }
}

// ── Init ─────────────────────────────────────────────────────

function init() {
    // Get path from URL
    const urlParams = new URLSearchParams(window.location.search);
    const path = urlParams.get("path") || "";

    if (!path) {
        window.location.href = "/";
        return;
    }

    state.path = path;
    checkAuth();

    // Event listeners
    document.getElementById("backBtn").onclick = () => window.location.href = "/?path=" + enc(state.path.split("/").slice(0, -1).join("/"));
    document.getElementById("errorBackBtn").onclick = () => window.location.href = "/";
    document.getElementById("shareBtn").onclick = showShareDialog;
    document.getElementById("heroShare").onclick = showShareDialog;
    document.getElementById("shareCreateBtn").onclick = createShareLink;
    document.getElementById("shareCopyBtn").onclick = () => {
        navigator.clipboard.writeText(document.getElementById("shareUrl").textContent);
        toast(t('status.link_created'), "success");
    };
    document.getElementById("shareCancelBtn").onclick = hideShareDialog;
    document.getElementById("shareOverlay").onclick = (e) => {
        if (e.target.id === "shareOverlay") hideShareDialog();
    };

    // Image viewer
    document.getElementById("imageViewerClose").onclick = closeImageViewer;
    document.getElementById("imageViewerPrev").onclick = () => navigateImage(-1);
    document.getElementById("imageViewerNext").onclick = () => navigateImage(1);
    document.getElementById("imageViewer").onclick = (e) => {
        if (e.target.id === "imageViewer") closeImageViewer();
    };
    document.addEventListener("keydown", (e) => {
        const overlay = document.getElementById("imageViewer");
        if (overlay.classList.contains("visible")) {
            if (e.key === "Escape") closeImageViewer();
            if (e.key === "ArrowLeft") navigateImage(-1);
            if (e.key === "ArrowRight") navigateImage(1);
        }
    });

    // Load project
    loadProject(state.path);
}

document.addEventListener("DOMContentLoaded", init);
