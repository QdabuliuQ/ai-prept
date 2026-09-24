import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zhCN from './locales/zh-CN.json';
import enUS from './locales/en-US.json';

function getSavedLanguage(): string {
  if (typeof window === 'undefined') return 'zh-CN';
  try {
    const saved = localStorage.getItem('language');
    if (saved === 'en-US' || saved === 'zh-CN') return saved;
  } catch {
    // ignore
  }
  return 'zh-CN';
}

const savedLanguage = getSavedLanguage();

i18n
  .use(initReactI18next)
  .init({
    resources: {
      'zh-CN': {
        translation: zhCN,
      },
      'en-US': {
        translation: enUS,
      },
    },
    lng: savedLanguage,
    fallbackLng: 'zh-CN',
    supportedLngs: ['zh-CN', 'en-US'],
    interpolation: {
      escapeValue: false,
    },
  });

if (typeof document !== 'undefined') {
  document.documentElement.lang = savedLanguage;
}

export default i18n;
