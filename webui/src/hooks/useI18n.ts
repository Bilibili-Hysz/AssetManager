import { useCallback, useSyncExternalStore } from 'react';
import { t, setLang, getLang, subscribeToLang, type Lang, SUPPORTED_LANGS } from '../i18n';

export function useI18n() {
  const lang = useSyncExternalStore(subscribeToLang, getLang, getLang);

  const changeLang = useCallback((newLang: Lang) => {
    setLang(newLang);
  }, []);

  return { t, lang, setLang: changeLang, supportedLangs: SUPPORTED_LANGS };
}
