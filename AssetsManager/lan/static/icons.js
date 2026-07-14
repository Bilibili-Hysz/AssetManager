/* Local fallback for legacy data-lucide placeholders in offline LAN mode. */
(function () {
    const glyphs = {
        "alert-triangle": "!", "arrow-down": "v", "arrow-up": "^",
        "check-square": "[]", clipboard: "=", download: "v", "file-text": "#",
        "folder-open": ">", "layout-grid": "#", link: "~", list: "=",
        "log-out": "<-", lock: "*", menu: "=", package: "[]",
        "panel-left": "|<", "panel-right": ">|", "panel-right-close": ">|",
        search: "o", x: "x",
    };

    function render(root) {
        (root || document).querySelectorAll("i[data-lucide]").forEach((node) => {
            if (node.dataset.iconFallback) return;
            node.dataset.iconFallback = "true";
            node.textContent = glyphs[node.dataset.lucide] || "+";
            node.setAttribute("aria-hidden", "true");
            node.style.fontStyle = "normal";
            node.style.fontWeight = "700";
            node.style.display = "inline-block";
            node.style.minWidth = "1em";
            node.style.textAlign = "center";
        });
    }

    window.LanIconFallback = { render };
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => render());
    else render();
}());
