import { useState, useCallback } from 'react';
import { t, setLang, getLang, type Lang, SUPPORTED_LANGS } from '../i18n';

export function useI18n() {
  const [lang, setLangState] = useState<Lang>(getLang());

  const changeLang = useCallback((newLang: Lang) => {
    setLang(newLang);
    setLangState(newLang);
  }, []);

  return { t, lang, setLang: changeLang, supportedLangs: SUPPORTED_LANGS };
}