const I18N = {
    _dict: {},
    _lang: 'en',

    async init() {
        const saved = localStorage.getItem('am_lang');
        const nav = navigator.language || 'en';
        const lang = saved || (nav.startsWith('zh') ? 'zh' : nav.startsWith('ja') ? 'ja' : 'en');
        await this.load(lang);
    },

    async load(lang) {
        try {
            const resp = await fetch(`/static/i18n/${lang}.json`);
            if (resp.ok) this._dict = await resp.json();
            this._lang = lang;
            document.documentElement.lang = this._lang;
        } catch(e) { /* fallback to English */ }
    },

    t(key, ...args) {
        let s = this._dict[key] || key;
        args.forEach((v, i) => { s = s.replace(`{${i}}`, v); });
        return s;
    },

    async setLang(lang) {
        localStorage.setItem('am_lang', lang);
        await this.load(lang);
        this.applyToDOM();
    },

    applyToDOM() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            el.textContent = this.t(el.dataset.i18n);
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.placeholder = this.t(el.dataset.i18nPlaceholder);
        });
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            el.title = this.t(el.dataset.i18nTitle);
        });
        document.querySelectorAll('[data-i18n-html]').forEach(el => {
            el.innerHTML = this.t(el.dataset.i18nHtml);
        });
    }
};

function t(key, ...args) { return I18N.t(key, ...args); }
