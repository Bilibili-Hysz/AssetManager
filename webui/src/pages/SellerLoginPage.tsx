import { ArrowLeft, KeyRound, LockKeyhole } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useState, type FormEvent } from 'react';
import { StorefrontShell } from '../components/storefront/StorefrontShell';
import { useSellerAuth } from '../stores/SellerAuthContext';
import { useI18n } from '../hooks/useI18n';
import { useToast } from '../components/ui/Toast';

export default function SellerLoginPage() {
  const { t } = useI18n();
  const { showToast } = useToast();
  const { login } = useSellerAuth();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!password.trim() || submitting) return;
    setSubmitting(true);
    try {
      await login(password, username);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Seller login failed', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <StorefrontShell storeName={t('seller.portal')}>
      <main className="storefront-main">
        <Link className="storefront-link" to="/storefront"><ArrowLeft size={15} /> {t('commerce.back_to_store')}</Link>
        <section className="seller-login-card" aria-labelledby="seller-login-title">
          <span className="seller-login-icon"><KeyRound size={22} /></span>
          <p className="storefront-eyebrow"><LockKeyhole size={14} /> {t('seller.portal')}</p>
          <h1 id="seller-login-title">{t('header.login')}</h1>
          <p>{t('seller.settings_subtitle')}</p>
          <form className="seller-form" onSubmit={submit}>
            <label className="seller-field" htmlFor="seller-username">{t('auth.username')}
              <input id="seller-username" value={username} onChange={event => setUsername(event.target.value)} autoComplete="username" required />
            </label>
            <label className="seller-field" htmlFor="seller-password">{t('auth.password')}
              <input id="seller-password" type="password" value={password} onChange={event => setPassword(event.target.value)} autoComplete="current-password" required />
            </label>
            <button className="storefront-button storefront-button-primary" type="submit" disabled={submitting}>
              {submitting ? t('browse.loading') : t('header.login')}
            </button>
          </form>
        </section>
      </main>
    </StorefrontShell>
  );
}
