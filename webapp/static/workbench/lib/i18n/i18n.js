import { zhCN } from "./messages/zh-CN.js";
import { enUS } from "./messages/en-US.js";

const bundles = {
  "zh-CN": zhCN,
  "en-US": enUS,
};

function getByPath(source, path) {
  const keys = String(path || "").split(".");
  let current = source;
  for (const key of keys) {
    if (!current || typeof current !== "object" || !(key in current)) return undefined;
    current = current[key];
  }
  return current;
}

export function resolveMessage(language, key) {
  const safe = language === "en-US" ? "en-US" : "zh-CN";
  const message = getByPath(bundles[safe], key);
  if (typeof message === "string") return message;
  const fallback = getByPath(bundles["zh-CN"], key);
  return typeof fallback === "string" ? fallback : key;
}

export function createTranslator(getLanguage) {
  return {
    t(key) {
      return resolveMessage(getLanguage(), key);
    },
    language() {
      return getLanguage();
    },
  };
}

export function applyI18nToDom(t, root = document) {
  root.querySelectorAll("[data-i18n]").forEach((node) => {
    const key = node.getAttribute("data-i18n");
    if (!key) return;
    node.textContent = t(key);
  });
}
