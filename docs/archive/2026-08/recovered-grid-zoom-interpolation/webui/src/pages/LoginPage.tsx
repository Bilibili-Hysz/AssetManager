import { useState, useEffect, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { KeyRound, User, Lock, Eye, EyeOff, UserPlus, LogIn, ArrowLeft } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { useI18n } from '../hooks/useI18n';

type LoginView = 'login' | 'register' | 'key';

export default function LoginPage() {
  const { serverInfo, authMode, authApi, setSessionUser, refreshMe, isLoading } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();

  const [view, setView] = useState<LoginView>('login');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Login form
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  // Key form
  const [accessKey, setAccessKey] = useState('');

  // Register form
  const [regUsername, setRegUsername] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirm, setRegConfirm] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regInvite, setRegInvite] = useState('');
  const [regErrors, setRegErrors] = useState<string[]>([]);

  // Determine which views to show based on auth mode
  const showKeyMode = authMode === 'key' || authMode === 'none';
  const showUserMode = authMode === 'user' || authMode === 'none';
  const showPasswordMode = authMode === 'password' || authMode === 'none';
  const guestEnabled = authMode === 'none' || authMode === 'password';

  // Auto-determine initial view
  useEffect(() => {
    if (authMode === 'key') setView('key');
    else if (authMode === 'user') setView('login');
    else if (authMode === 'password') setView('login');
  }, [authMode]);

  // Redirect if already authenticated
  useEffect(() => {
    if (!isLoading && serverInfo && !serverInfo.auth_enabled) {
      navigate('/');
    }
  }, [isLoading, serverInfo, navigate]);

  // URL key parameter auto-login
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlKey = params.get('key');
    if (urlKey && authMode === 'key') {
      setAccessKey(urlKey);
      handleKeyLogin();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (showPasswordMode && !loginUsername) {
        // Password-only mode
        await authApi.loginWithPassword(loginPassword);
        const restored = await refreshMe();
        if (!restored) throw new Error(t('auth.login_failed'));
      } else {
        const res = await authApi.login(loginUsername, loginPassword);
        setSessionUser(res.user);
      }
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  const handleKeyLogin = async () => {
    if (!accessKey.trim()) return;
    setError('');
    setLoading(true);
    try {
      await authApi.verifyKey(accessKey.trim());
      const restored = await refreshMe();
      if (!restored) throw new Error(t('auth.invalid_key'));
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid key');
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setRegErrors([]);

    // Validation
    const errors: string[] = [];
    if (!regUsername) errors.push(t('auth.username_required'));
    else if (regUsername.length < 2) errors.push(t('auth.username_min'));
    else if (!/^[a-zA-Z0-9_-]+$/.test(regUsername)) errors.push(t('auth.username_chars'));

    if (regPassword.length < 8) errors.push(t('auth.password_min'));
    else if (regPassword.length > 128) errors.push(t('auth.password_max'));
    else {
      const weakPasswords = ['password', '12345678', 'qwerty123', 'admin123', 'letmein', 'welcome1', 'monkey123', 'dragon12', 'master12', 'abc12345'];
      if (weakPasswords.includes(regPassword.toLowerCase())) errors.push(t('auth.password_common'));
      if (!/[A-Z]/.test(regPassword)) errors.push(t('auth.password_uppercase'));
      if (!/[a-z]/.test(regPassword)) errors.push(t('auth.password_lowercase'));
      if (!/[0-9]/.test(regPassword)) errors.push(t('auth.password_digit'));
      if (!/[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]/.test(regPassword)) errors.push(t('auth.password_special'));
    }

    if (regPassword !== regConfirm) errors.push(t('auth.password_mismatch'));

    if (errors.length > 0) {
      setRegErrors(errors);
      return;
    }

    setLoading(true);
    try {
      const res = await authApi.register(
        regUsername, regPassword,
        regEmail || undefined,
        regInvite || undefined,
      );
      setSessionUser(res.user);
      navigate('/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  const handleGuest = () => {
    setSessionUser(null);
    navigate('/');
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-slate-950">
        <div className="flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-2 border-brand-500/30 border-t-brand-500 rounded-full animate-spin" />
          <p className="text-sm text-slate-500">{t('landing.loading')}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-slate-950 p-4">
      <div className="w-full max-w-sm">
        {/* Server info */}
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-xl bg-brand-500/10 border border-brand-500/20 flex items-center justify-center mx-auto mb-4">
            <span className="text-2xl font-bold text-brand-400">A</span>
          </div>
          <h1 className="text-2xl font-bold text-white">
            {serverInfo?.share_name ?? 'AssetManager'}
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            {view === 'key'
              ? t('auth.key_subtitle')
              : view === 'register'
                ? t('auth.register_subtitle')
                : t('auth.login_subtitle')}
          </p>
        </div>

        {/* Tab bar */}
        {view !== 'register' && (
          <div className="flex border border-slate-700/50 rounded-lg overflow-hidden mb-6">
            {showUserMode && (
              <button
                onClick={() => { setView('login'); setError(''); }}
                className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                  view === 'login'
                    ? 'bg-brand-500/10 text-brand-400 border-r border-slate-700/50'
                    : 'bg-slate-900 text-slate-400 hover:text-slate-300 border-r border-slate-700/50'
                }`}
              >
                <User size={16} className="inline mr-1.5" />
                {t('auth.login')}
              </button>
            )}
            {showPasswordMode && !showUserMode && (
              <button
                onClick={() => { setView('login'); setError(''); }}
                className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                  view === 'login'
                    ? 'bg-brand-500/10 text-brand-400'
                    : 'bg-slate-900 text-slate-400 hover:text-slate-300'
                }`}
              >
                <Lock size={16} className="inline mr-1.5" />
                {t('auth.password')}
              </button>
            )}
            {showKeyMode && (
              <button
                onClick={() => { setView('key'); setError(''); }}
                className={`flex-1 py-2.5 text-sm font-medium transition-colors ${
                  view === 'key'
                    ? 'bg-brand-500/10 text-brand-400'
                    : 'bg-slate-900 text-slate-400 hover:text-slate-300'
                }`}
              >
                <KeyRound size={16} className="inline mr-1.5" />
                {t('auth.key')}
              </button>
            )}
          </div>
        )}

        {/* Key Login View */}
        {view === 'key' && (
          <div className="bg-slate-900 border border-slate-700/50 rounded-xl p-6 space-y-4">
            <div className="space-y-3">
              <label className="block text-xs text-slate-500">{t('auth.access_key')}</label>
              <input
                type="text"
                value={accessKey}
                onChange={e => setAccessKey(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleKeyLogin(); }}
                placeholder={t('auth.key_placeholder')}
                className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
                autoFocus
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-900/20 border border-red-900/30 rounded-lg px-3 py-2">{error}</p>
            )}

            <button
              onClick={handleKeyLogin}
              disabled={loading || !accessKey.trim()}
              className="w-full py-2.5 text-sm text-white bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <><KeyRound size={16} /> {t('auth.connect')}</>
              )}
            </button>
          </div>
        )}

        {/* Login View */}
        {view === 'login' && (
          <form onSubmit={handleLogin} className="bg-slate-900 border border-slate-700/50 rounded-xl p-6 space-y-4">
            {showUserMode && (
              <div className="space-y-3">
                <label className="block text-xs text-slate-500">{t('auth.username')}</label>
                <input
                  type="text"
                  value={loginUsername}
                  onChange={e => setLoginUsername(e.target.value)}
                  placeholder={t('auth.username_placeholder')}
                  className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                    placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
                  autoFocus
                />
              </div>
            )}

            <div className="space-y-3">
              <label className="block text-xs text-slate-500">{t('auth.password')}</label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={loginPassword}
                  onChange={e => setLoginPassword(e.target.value)}
                  placeholder={t('auth.password_placeholder')}
                  className="w-full px-4 py-2.5 pr-10 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                    placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={t(showPassword ? 'auth.hide_password' : 'auth.show_password')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-900/20 border border-red-900/30 rounded-lg px-3 py-2">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 text-sm text-white bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <><LogIn size={16} /> {t('auth.sign_in')}</>
              )}
            </button>

            {/* Register link */}
            <button
              type="button"
              onClick={() => { setView('register'); setError(''); setRegErrors([]); }}
              className="w-full text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              {t('auth.no_account')}
            </button>
          </form>
        )}

        {view !== 'login' && view !== 'register' && (
          <button
            type="button"
            onClick={() => { setView('register'); setError(''); setRegErrors([]); }}
            className="w-full mt-4 text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            {t('auth.no_account')}
          </button>
        )}

        {/* Register View */}
        {view === 'register' && (
          <form onSubmit={handleRegister} className="bg-slate-900 border border-slate-700/50 rounded-xl p-6 space-y-4">
            <button
              type="button"
              onClick={() => { setView('login'); setError(''); setRegErrors([]); }}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              <ArrowLeft size={14} /> {t('auth.back_to_login')}
            </button>

            <div className="space-y-3">
              <label className="block text-xs text-slate-500">{t('auth.username')}</label>
              <input
                type="text"
                value={regUsername}
                onChange={e => setRegUsername(e.target.value)}
                placeholder={t('auth.username_placeholder')}
                className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
                autoFocus
              />
            </div>

            <div className="space-y-3">
              <label className="block text-xs text-slate-500">{t('auth.password')}</label>
              <input
                type="password"
                value={regPassword}
                onChange={e => setRegPassword(e.target.value)}
                placeholder={t('auth.password_placeholder')}
                className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
              />
            </div>

            <div className="space-y-3">
              <label className="block text-xs text-slate-500">{t('auth.confirm_password')}</label>
              <input
                type="password"
                value={regConfirm}
                onChange={e => setRegConfirm(e.target.value)}
                placeholder={t('auth.confirm_placeholder')}
                className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
              />
            </div>

            <div className="space-y-3">
              <label className="block text-xs text-slate-500">{t('auth.email')}</label>
              <input
                type="email"
                value={regEmail}
                onChange={e => setRegEmail(e.target.value)}
                placeholder={t('auth.email_placeholder')}
                className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
              />
            </div>

            <div className="space-y-3">
              <label className="block text-xs text-slate-500">{t('auth.invite_code')}</label>
              <input
                type="text"
                value={regInvite}
                onChange={e => setRegInvite(e.target.value)}
                placeholder={t('auth.invite_placeholder')}
                className="w-full px-4 py-2.5 bg-slate-800 border border-slate-700/50 rounded-lg text-sm text-slate-200
                  placeholder-slate-500 focus:outline-none focus:border-brand-500/50 transition-colors"
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-900/20 border border-red-900/30 rounded-lg px-3 py-2">{error}</p>
            )}

            {regErrors.length > 0 && (
              <div className="text-xs text-red-400 bg-red-900/20 border border-red-900/30 rounded-lg px-3 py-2 space-y-1">
                {regErrors.map((err, i) => <p key={i}>{err}</p>)}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 text-sm text-white bg-brand-500 hover:bg-brand-600 disabled:opacity-50 rounded-lg transition-colors flex items-center justify-center gap-2"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <><UserPlus size={16} /> {t('auth.create_account')}</>
              )}
            </button>
          </form>
        )}

        {/* Guest mode entry */}
        {guestEnabled && (
          <div className="text-center mt-6">
            <button
              onClick={handleGuest}
              className="text-sm text-slate-500 hover:text-slate-300 transition-colors underline underline-offset-2"
            >
              {t('auth.guest_mode')}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
