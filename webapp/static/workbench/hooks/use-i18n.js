import { createTranslator } from "../lib/i18n/i18n.js";
import { settingsStore } from "../store/settings-store.js";

export function useI18n() {
  return createTranslator(() => settingsStore.getState().language || "zh-CN");
}
