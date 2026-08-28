# Sharing Module UI/UX Redesign Implementation Plan
> **ARCHIVED (2026-08-27)**: 已执行完毕或被后续批次取代,仅追溯用;导航与现行参考见 docs/compose/README.md。

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the LAN sharing module with quick share entry, multi-tab management dialog, role-based permissions, and mobile-optimized web UI.

**Architecture:** Backend-first approach — extend existing auth/share API with role-based middleware, then build desktop UI (quick share + management dialog), then enhance web UI (login page + permissions + mobile). Each task is independently testable.

**Tech Stack:** Python 3.14, PySide6, aiohttp, SQLite, JWT (PyJWT), HTML/CSS/JS

---

## File Structure

### New Files
- `AssetsManager/lan/routes/online.py` — Online users endpoint
- `AssetsManager/lan/routes/activity.py` — Activity log endpoint
- `AssetsManager/lan/static/login.html` — Login page
- `AssetsManager/lan/static/login.js` — Login page logic
- `AssetsManager/dialogs/quick_share_card.py` — Floating quick share card widget
- `tests/lan/test_role_permissions.py` — Role-based permission tests

### Modified Files
- `AssetsManager/lan/routes/_helpers.py` — Role-based middleware helpers
- `AssetsManager/lan/routes/auth.py` — Enhanced login with roles
- `AssetsManager/lan/routes/users.py` — Online users + activity
- `AssetsManager/lan/routes/shares.py` — Share link permissions
- `AssetsManager/lan/server.py` — Public endpoint updates
- `AssetsManager/lan/static/index.html` — Login page integration
- `AssetsManager/lan/static/app.js` — Permission badges + mobile
- `AssetsManager/lan/static/style.css` — Mobile responsive + login styles
- `AssetsManager/lan/static/share.html` — Permission badges
- `AssetsManager/widgets/lan_sharing.py` — Quick share integration
- `AssetsManager/dialogs/sharing_settings_dialog.py` — 4-tab redesign

---

### Task 1: Role-Based Middleware Foundation

**Covers:** S4

**Files:**
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Create: `tests/lan/test_role_permissions.py`

- [ ] **Step 1: Add role constants and helper functions**

In `AssetsManager/lan/routes/_helpers.py`, add after existing imports:

```python
ROLE_ADMIN = "admin"
ROLE_USER = "user"
ROLE_GUEST = "guest"

def require_role(request, *roles):
    """Return user dict if user has one of the required roles, else None."""
    user = get_request_user(request)
    if not user:
        return None
    if user.get("role") in roles:
        return user
    return None

def require_admin(request):
    """Return user dict if admin, else None."""
    return require_role(request, ROLE_ADMIN)

def get_user_permissions(user):
    """Return permission dict for a user role."""
    role = user.get("role", ROLE_GUEST) if user else ROLE_GUEST
    perms = {
        ROLE_ADMIN: {"browse": True, "download": True, "upload": True, "manage_links": True, "manage_users": True, "settings": True},
        ROLE_USER:  {"browse": True, "download": True, "upload": False, "manage_links": False, "manage_users": False, "settings": False},
        ROLE_GUEST: {"browse": True, "download": False, "upload": False, "manage_links": False, "manage_users": False, "settings": False},
    }
    return perms.get(role, perms[ROLE_GUEST])
```

- [ ] **Step 2: Write tests**

```python
def test_require_admin_with_admin_user():
    from AssetsManager.lan.routes._helpers import require_admin
    # Mock request with admin user
    assert require_admin(mock_request_with_admin) is not None

def test_require_admin_with_guest():
    from AssetsManager.lan.routes._helpers import require_admin
    assert require_admin(mock_request_with_guest) is None

def test_get_user_permissions_admin():
    from AssetsManager.lan.routes._helpers import get_user_permissions, ROLE_ADMIN
    perms = get_user_permissions({"role": ROLE_ADMIN})
    assert perms["upload"] is True
    assert perms["manage_users"] is True

def test_get_user_permissions_guest():
    from AssetsManager.lan.routes._helpers import get_user_permissions
    perms = get_user_permissions(None)
    assert perms["download"] is False
```

- [ ] **Step 3: Run quality gate**

Run: `python -m ruff check . --exclude ".Cython&Noikta" && python -m pyright && python -m pytest -q`

---

### Task 2: Activity Log System

**Covers:** S2

**Files:**
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/routes/users.py`

- [ ] **Step 1: Add activity log to LanScopedServices**

In `_helpers.py`, add activity logging:

```python
import time
from collections import deque

class ActivityLog:
    def __init__(self, max_entries=100):
        self._entries = deque(maxlen=max_entries)
        self._lock = __import__('threading').Lock()

    def add(self, user, action, detail=""):
        with self._lock:
            self._entries.append({
                "time": time.time(),
                "user": user or "guest",
                "action": action,
                "detail": detail,
            })

    def recent(self, count=10):
        with self._lock:
            return list(self._entries)[-count:]
```

Add `activity_log` field to `LanScopedServices`.

- [ ] **Step 2: Add activity endpoint**

In `users.py`, add:

```python
async def handle_activity(request):
    user = get_request_user(request)
    if not user or user.get("role") != "admin":
        return web.json_response({"error": "Admin access required"}, status=403)
    lan = get_lan(request)
    return web.json_response({"activities": lan.activity_log.recent(20)})
```

- [ ] **Step 3: Register route and run tests**

---

### Task 3: Online Users Tracking

**Covers:** S2

**Files:**
- Modify: `AssetsManager/lan/routes/_helpers.py`
- Modify: `AssetsManager/lan/routes/users.py`

- [ ] **Step 1: Add online user tracker**

```python
class OnlineUsers:
    def __init__(self):
        self._users = {}  # user_id -> {"username", "ip", "connected_at"}
        self._lock = __import__('threading').Lock()

    def connect(self, user_id, username, ip):
        with self._lock:
            self._users[user_id] = {"username": username, "ip": ip, "connected_at": time.time()}

    def disconnect(self, user_id):
        with self._lock:
            self._users.pop(user_id, None)

    def list_all(self):
        with self._lock:
            return [{"user_id": k, **v} for k, v in self._users.items()]
```

- [ ] **Step 2: Add online users endpoint**

```python
async def handle_online_users(request):
    user = get_request_user(request)
    if not user or user.get("role") != "admin":
        return web.json_response({"error": "Admin access required"}, status=403)
    lan = get_lan(request)
    return web.json_response({"users": lan.online_users.list_all()})
```

- [ ] **Step 3: Run quality gate**

---

### Task 4: Quick Share Card Widget

**Covers:** S1

**Files:**
- Create: `AssetsManager/dialogs/quick_share_card.py`
- Modify: `AssetsManager/widgets/lan_sharing.py`

- [ ] **Step 1: Create QuickShareCard widget**

```python
"""QuickShareCard — floating card for one-click sharing."""
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QCheckBox, QFrame, QApplication,
)
from AssetsManager.core import themes
from AssetsManager.core.ui_scale import scaled_px, scaled_pt
from AssetsManager import i18n

tr = i18n.tr

class QuickShareCard(QWidget):
    """Floating card for quick share link generation."""

    share_requested = Signal(dict)  # {paths, password, expiry, max_downloads}

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self._paths = []
        self._setup_ui()

    def _setup_ui(self):
        t = themes.get()
        self.setFixedSize(scaled_px(320), scaled_px(280))
        self.setStyleSheet(f"""
            QWidget {{
                background: {t['panel']};
                border: 1px solid {t['border']};
                border-radius: {scaled_px(10)}px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(scaled_px(16), scaled_px(12), scaled_px(16), scaled_px(12))

        # File info
        self._file_label = QLabel()
        self._file_label.setStyleSheet(f"font-size: {scaled_pt(13)}px; color: {t['heading']};")
        layout.addWidget(self._file_label)

        self._size_label = QLabel()
        self._size_label.setStyleSheet(f"font-size: {scaled_pt(11)}px; color: {t['muted']};")
        layout.addWidget(self._size_label)

        # Password (collapsed)
        self._pwd_check = QCheckBox(tr("sharing.quick.password"))
        self._pwd_input = QLineEdit()
        self._pwd_input.setPlaceholderText(tr("sharing.quick.password_placeholder"))
        self._pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pwd_input.setVisible(False)
        self._pwd_check.toggled.connect(self._pwd_input.setVisible)

        # Expiry (collapsed)
        self._expiry_check = QCheckBox(tr("sharing.quick.expiry"))
        self._expiry_input = QLineEdit("24")
        self._expiry_input.setPlaceholderText(tr("sharing.quick.hours"))
        self._expiry_input.setVisible(False)
        self._expiry_check.toggled.connect(self._expiry_input.setVisible)

        # Buttons
        btn_layout = QHBoxLayout()
        self._generate_btn = QPushButton(tr("sharing.quick.generate"))
        self._generate_btn.setStyleSheet(f"""
            QPushButton {{
                background: {t['accent']};
                color: white;
                border: none;
                border-radius: {scaled_px(6)}px;
                padding: {scaled_px(8)}px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {t['accent_hover']}; }}
        """)
        self._generate_btn.clicked.connect(self._on_generate)

        self._copy_btn = QPushButton(tr("sharing.quick.copy"))
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._on_copy)

        btn_layout.addWidget(self._generate_btn)
        btn_layout.addWidget(self._copy_btn)

        # Result
        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        self._result_label.setVisible(False)

        layout.addWidget(self._pwd_check)
        layout.addWidget(self._pwd_input)
        layout.addWidget(self._expiry_check)
        layout.addWidget(self._expiry_input)
        layout.addLayout(btn_layout)
        layout.addWidget(self._result_label)

    def show_for_paths(self, paths, global_pos):
        self._paths = paths
        count = len(paths)
        self._file_label.setText(f"{count} {'item' if count == 1 else 'items'} selected")
        # Calculate total size...
        self._result_label.setVisible(False)
        self._copy_btn.setEnabled(False)
        self.move(global_pos)
        self.show()

    def _on_generate(self):
        data = {"paths": self._paths}
        if self._pwd_check.isChecked():
            data["password"] = self._pwd_input.text()
        if self._expiry_check.isChecked():
            data["expiry_hours"] = int(self._expiry_input.text())
        self.share_requested.emit(data)

    def _on_copy(self):
        QApplication.clipboard().setText(self._result_label.text())

    def show_result(self, url):
        self._result_label.setText(url)
        self._result_label.setVisible(True)
        self._copy_btn.setEnabled(True)
```

- [ ] **Step 2: Integrate into LanSharingMixin**

Add right-click menu "Quick Share" that creates and shows the card.

- [ ] **Step 3: Run quality gate**

---

### Task 5: Share Management Dialog Redesign

**Covers:** S2

**Files:**
- Modify: `AssetsManager/dialogs/sharing_settings_dialog.py`

- [ ] **Step 1: Add 4th tab (Users)**

Add "Users" tab between "Share Links" and "Settings":
- Admin list display
- Invite code generation/revocation
- Online users list (from Task 3)
- Guest permission defaults

- [ ] **Step 2: Redesign Overview tab**

Replace current share tab with overview:
- Server status card (IP, port, online count, traffic)
- Quick share button (large, centered)
- Recent activity list (from Task 2)
- Tunnel status section

- [ ] **Step 3: Add share links table view**

Replace current share links list with table:
- Columns: Name | Path | Permissions | Expiry | Downloads | Actions
- Per-row: Copy | Edit | Disable | Delete
- Top: search + filter

- [ ] **Step 4: Run quality gate**

---

### Task 6: Web Login Page

**Covers:** S3

**Files:**
- Create: `AssetsManager/lan/static/login.html`
- Create: `AssetsManager/lan/static/login.js`
- Modify: `AssetsManager/lan/static/style.css`

- [ ] **Step 1: Create login.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - AssetManager</title>
    <link rel="stylesheet" href="/static/style.css?v=30">
</head>
<body class="login-page">
    <div class="login-card">
        <div class="login-card__icon">A</div>
        <h1 class="login-card__title" id="serverName">AssetManager</h1>
        <p class="login-card__subtitle">Sign in to access the library</p>
        <form id="loginForm" class="login-form">
            <input type="text" id="usernameInput" placeholder="Username" autocomplete="username" class="login-form__input">
            <input type="password" id="passwordInput" placeholder="Password" autocomplete="current-password" class="login-form__input">
            <div class="login-form__error" id="loginError" style="display:none"></div>
            <button type="submit" class="login-form__btn login-form__btn--primary">Sign In</button>
            <button type="button" class="login-form__btn login-form__btn--guest" id="guestBtn" style="display:none">
                Browse as Guest
            </button>
        </form>
    </div>
    <script src="/static/login.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create login.js**

```javascript
const loginForm = document.getElementById('loginForm');
const loginError = document.getElementById('loginError');
const guestBtn = document.getElementById('guestBtn');

// Check if guest access is allowed
fetch('/api/info').then(r => r.json()).then(info => {
    if (info.allow_guest) guestBtn.style.display = 'block';
    if (info.share_name) document.getElementById('serverName').textContent = info.share_name;
});

loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('usernameInput').value;
    const password = document.getElementById('passwordInput').value;

    try {
        const resp = await fetch('/api/auth/login', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username, password}),
        });
        const data = await resp.json();
        if (resp.ok && data.token) {
            localStorage.setItem('token', data.token);
            window.location.href = '/';
        } else {
            loginError.textContent = data.error || 'Login failed';
            loginError.style.display = 'block';
        }
    } catch (err) {
        loginError.textContent = 'Connection error';
        loginError.style.display = 'block';
    }
});

guestBtn.addEventListener('click', () => {
    localStorage.setItem('token', 'guest');
    window.location.href = '/';
});
```

- [ ] **Step 3: Add login page styles to style.css**

- [ ] **Step 4: Run quality gate**

---

### Task 7: Web Permission Badges

**Covers:** S3

**Files:**
- Modify: `AssetsManager/lan/static/app.js`
- Modify: `AssetsManager/lan/static/style.css`

- [ ] **Step 1: Add permission badge rendering**

In `app.js`, when rendering file cards, add permission indicators:
```javascript
function renderPermissionBadge(perms) {
    if (!perms.download) return '<span class="badge badge--lock" title="View only">🔒</span>';
    if (perms.password) return '<span class="badge badge--pwd" title="Password protected">🔐</span>';
    return '';
}
```

- [ ] **Step 2: Add role indicator to header**

Show current user role in the header status area.

- [ ] **Step 3: Run quality gate**

---

### Task 8: Web Mobile Optimization

**Covers:** S3

**Files:**
- Modify: `AssetsManager/lan/static/style.css`
- Modify: `AssetsManager/lan/static/app.js`

- [ ] **Step 1: Add mobile breakpoints**

```css
@media (max-width: 768px) {
    .sidebar { position: fixed; transform: translateX(-100%); }
    .sidebar.open { transform: translateX(0); }
    .main-content { margin-left: 0; }
    .bottom-bar { display: flex; }
    .file-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
}
```

- [ ] **Step 2: Add bottom action bar**

```html
<div class="bottom-bar" style="display:none">
    <button class="bottom-bar__btn" id="mobileBack">← Back</button>
    <button class="bottom-bar__btn" id="mobileView">Grid</button>
    <button class="bottom-bar__btn" id="mobileDownload">Download</button>
    <button class="bottom-bar__btn" id="mobileShare">Share</button>
</div>
```

- [ ] **Step 3: Run quality gate**

---

### Task 9: Web Interaction Enhancements

**Covers:** S3

**Files:**
- Modify: `AssetsManager/lan/static/app.js`
- Modify: `AssetsManager/lan/static/style.css`

- [ ] **Step 1: Add download progress bar**

```javascript
async function downloadWithProgress(url, filename) {
    const resp = await fetch(url);
    const reader = resp.body.getReader();
    const contentLength = +resp.headers.get('Content-Length');
    let received = 0;
    const chunks = [];

    showProgressBar();
    while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        chunks.push(value);
        received += value.length;
        updateProgressBar(received / contentLength);
    }
    hideProgressBar();
    // Create blob and trigger download
}
```

- [ ] **Step 2: Add batch selection mode**

- [ ] **Step 3: Add copy share link button per file**

- [ ] **Step 4: Run quality gate**

---

## Quality Gate

```powershell
python -m ruff check . --exclude ".Cython&Noikta" && python -m pyright && python -m pytest -q
```
