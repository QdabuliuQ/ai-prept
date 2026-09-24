import 'i18next';
import zhCN from '../i18n/locales/zh-CN.json';

declare module 'i18next' {
  interface CustomTypeOptions {
    // 使用中文语言包作为默认类型，获得更好的类型提示
    resources: {
      translation: typeof zhCN;
    };
    // 返回类型为 string
    returnNull: false;
  }
}
