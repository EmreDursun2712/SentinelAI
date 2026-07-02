import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

import en from "./en.json";
import tr from "./tr.json";

export const SUPPORTED_LANGUAGES = [
  { code: "en", label: "EN" },
  { code: "tr", label: "TR" },
] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number]["code"];

// Bilingual UI (matches the bilingual README). Language is detected from
// localStorage (persisted by the switcher), then the browser; English is the
// fallback. Add a locale by dropping a JSON bundle here + a resources entry.
void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      tr: { translation: tr },
    },
    fallbackLng: "en",
    supportedLngs: ["en", "tr"],
    interpolation: { escapeValue: false }, // React already escapes
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "sentinelai_lang",
    },
  });

export default i18n;
