import { createInstance } from 'i18next';
import { initReactI18next } from 'react-i18next';
import en from './locales/en.json' with { type: 'json' };
import zhTW from './locales/zh-TW.json' with { type: 'json' };

export const LOCALE_COOKIE = 'zerofield_locale';
export const SUPPORTED_LOCALES = ['en', 'zh-TW'];
export const normalizeLocale = value => SUPPORTED_LOCALES.includes(value) ? value : 'en';

export function localeFromCookie(cookie = '') {
  const value = String(cookie).split(';').map(part => part.trim()).find(part => part.startsWith(LOCALE_COOKIE + '='));
  try { return normalizeLocale(value ? decodeURIComponent(value.slice(LOCALE_COOKIE.length + 1)) : 'en'); }
  catch { return 'en'; }
}

function initialLocale() {
  try { return localeFromCookie(globalThis.document?.cookie); } catch { return 'en'; }
}

export const i18n = createInstance();
i18n.use(initReactI18next).init({
  resources: {en: {translation: en}, 'zh-TW': {translation: zhTW}},
  lng: initialLocale(), supportedLngs: SUPPORTED_LOCALES, fallbackLng: 'en',
  initImmediate: false, interpolation: {escapeValue: false}, returnNull: false,
});

export const t = (key, params) => i18n.t(key, params);
export const currentLocale = () => i18n.resolvedLanguage || 'en';

function updateDocument() {
  if (globalThis.document) document.documentElement.lang = currentLocale();
}
i18n.on('languageChanged', updateDocument);
updateDocument();

export async function setLocale(value) {
  const locale = normalizeLocale(value);
  try {
    if (globalThis.document) document.cookie = `${LOCALE_COOKIE}=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`;
  } catch { /* A browser may disable preference cookies; switching still works. */ }
  await i18n.changeLanguage(locale);
}

export const formatNumber = (value, options) => new Intl.NumberFormat(currentLocale(), options).format(value);
