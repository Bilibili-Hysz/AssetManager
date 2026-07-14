const loginForm = document.getElementById('loginForm');
const loginError = document.getElementById('loginError');
const guestBtn = document.getElementById('guestBtn');

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
            loginError.textContent = data.error || t('error.login_failed');
            loginError.style.display = 'block';
        }
    } catch (err) {
        loginError.textContent = t('error.connection_error');
        loginError.style.display = 'block';
    }
});

guestBtn.addEventListener('click', () => {
    localStorage.setItem('token', 'guest');
    window.location.href = '/';
});
