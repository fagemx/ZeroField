import { useTranslation } from 'react-i18next';
import { i18n, setLocale } from './index.js';

export { useTranslation };
export function useLocale() { return useTranslation().i18n.resolvedLanguage || 'en'; }

export function LanguageSwitch() {
  const {t} = useTranslation(undefined, {i18n});
  return <div className="language-switch" role="group" aria-label={t('common.language')}>
    {['en', 'zh-TW'].map(locale => <button key={locale} type="button" lang={locale}
      aria-pressed={i18n.resolvedLanguage === locale} onMouseDown={event => event.preventDefault()}
      onClick={() => setLocale(locale)}>{locale === 'en' ? 'English' : '繁體中文'}</button>)}
  </div>;
}
