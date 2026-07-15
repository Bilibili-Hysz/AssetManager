/* ═══════════════════════════════════════════════════════════════
   AssetManager Share — Share Page Logic
   ═══════════════════════════════════════════════════════════════ */

const shareState = {
    id: null,
    paths: [],
    hasPassword: false,
    allowPreview: true,
    verified: false,
};

// ── Utilities ────────────────────────────────────────────────

function esc(s) {
    const el = document.createElement("span");
    el.textContent = s || "";
    return el.innerHTML;
}

function enc(s) {
    return encodeURIComponent(s || "");
}

function encPath(p) {
    // Encode each path segment separately, preserving slashes
    return (p || "").split("/").map(encodeURIComponent).join("/");
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

function formatSize(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (bytes >= 1024 && i < units.length - 1) {
        bytes /= 1024;
        i++;
    }
    return `${bytes.toFixed(1)} ${units[i]}`;
}

// ── API ──────────────────────────────────────────────────────

async function fetchShareInfo() {
    const shareId = window.location.pathname.split("/s/")[1];
    if (!shareId) {
        showError(t('share_page.link_not_found'), t('share_page.link_not_found_msg'));
        return;
    }
    shareState.id = shareId;

    try {
        const r = await fetch(`/api/shares/${shareId}/info`);
        if (r.status === 404) {
            showError(t('share_page.link_not_found'), t('share_page.link_not_found_msg'));
            return;
        }
        const d = await r.json();
        if (d.error) {
            showError("Error", d.error);
            return;
        }

        shareState.paths = d.paths || [];
        shareState.hasPassword = d.has_password;
        shareState.allowPreview = d.allow_preview;

        if (shareState.hasPassword) {
            showPasswordOverlay();
        } else {
            loadShareContent();
        }
    } catch (e) {
        showError("Error", t('error.load_share_failed'));
    }
}

async function verifyPassword() {
    const password = document.getElementById("sharePasswordInput").value;
    const errorEl = document.getElementById("passwordError");

    try {
        const r = await fetch(`/api/shares/${shareState.id}/verify`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ password }),
        });

        if (r.ok) {
            const d = await r.json();
            const share = d.share;
            if (!share) throw new Error("Missing verified share");
            shareState.verified = true;
            shareState.paths = d.share.paths || [];
            shareState.hasPassword = d.share.has_password;
            shareState.allowPreview = d.share.allow_preview;
            loadShareContent();
        } else {
            errorEl.style.display = "";
        }
    } catch (e) {
        errorEl.textContent = t('error.verification_failed');
        errorEl.style.display = "";
    }
}

// ── Content Loading ──────────────────────────────────────────

function getDownloadUrl(path) {
    return `/api/shares/${shareState.id}/download/${encPath(path)}`;
}

function getPreviewUrl(path) {
    return `/api/shares/${shareState.id}/preview/${encPath(path)}`;
}

async function loadShareContent() {
    hidePasswordOverlay();
    hideErrorOverlay();

    const content = document.getElementById("shareContent");
    const grid = document.getElementById("shareGrid");
    const title = document.getElementById("shareTitle");
    const meta = document.getElementById("shareMeta");

    content.style.display = "block";
    title.textContent = t('share_page.shared_files', shareState.paths.length);

    // Load file info for each path
    grid.innerHTML = "";

    for (const path of shareState.paths) {
        const name = path.split("/").pop() || path;
        const ext = name.includes(".") ? "." + name.split(".").pop().toLowerCase() : "";
        const isImage = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"].includes(ext);
        const downloadUrl = getDownloadUrl(path);
        const previewUrl = isImage ? getPreviewUrl(path) : downloadUrl;

        const card = document.createElement("div");
        card.className = "share-card";

        const thumbHtml = isImage && shareState.allowPreview
            ? `<img class="share-card__thumb" src="${previewUrl}" alt="" loading="lazy">`
            : `<div class="share-card__icon">${catIcon(ext)}</div>`;

        card.innerHTML = `
            ${thumbHtml}
            <div class="share-card__info">
                <div class="share-card__name" title="${esc(name)}">${esc(name)}</div>
                <div class="share-card__path">${esc(path)}</div>
            </div>
            <a class="share-card__download" href="${downloadUrl}" download>
                &#11015; ${t('action.download')}
            </a>
        `;

        // Click to view image (uses preview URL to avoid incrementing download counter)
        if (isImage && shareState.allowPreview) {
            card.querySelector(".share-card__thumb").addEventListener("click", () => {
                openImageViewer(previewUrl);
            });
        }

        grid.appendChild(card);
    }

    // Update meta
    const expiryInfo = document.getElementById("shareMeta");
    // Meta info is already set
}

// ── Image Viewer ─────────────────────────────────────────────

function openImageViewer(src) {
    const overlay = document.getElementById("imageViewer");
    const img = document.getElementById("imageViewerImg");
    img.src = src;
    overlay.classList.add("visible");
    document.body.style.overflow = "hidden";
}

function closeImageViewer() {
    document.getElementById("imageViewer").classList.remove("visible");
    document.body.style.overflow = "";
}

// ── UI Helpers ───────────────────────────────────────────────

function showPasswordOverlay() {
    document.getElementById("passwordOverlay").style.display = "flex";
    document.getElementById("sharePasswordInput").focus();
}

function hidePasswordOverlay() {
    document.getElementById("passwordOverlay").style.display = "none";
}

function showError(title, message) {
    document.getElementById("errorTitle").textContent = title;
    document.getElementById("errorMessage").textContent = message;
    document.getElementById("errorOverlay").style.display = "flex";
}

function hideErrorOverlay() {
    document.getElementById("errorOverlay").style.display = "none";
}

// ── Event Bindings ───────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    // Password verification
    document.getElementById("verifyPasswordBtn").addEventListener("click", verifyPassword);
    document.getElementById("sharePasswordInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter") verifyPassword();
    });

    // Image viewer
    document.getElementById("imageViewerClose").addEventListener("click", closeImageViewer);
    document.getElementById("imageViewer").addEventListener("click", (e) => {
        if (e.target === document.getElementById("imageViewer")) closeImageViewer();
    });
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeImageViewer();
    });

    // Load share info
    fetchShareInfo();
});
