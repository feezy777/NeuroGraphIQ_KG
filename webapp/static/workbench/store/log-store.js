import { createStore } from "./create-store.js";

const store = createStore({
  items: [],
});

function normalizePrefix(prefix) {
  const raw = String(prefix || "UI").replace(/[^A-Z]/g, "").toUpperCase();
  return raw || "UI";
}

export const logStore = {
  ...store,
  add(prefix, message, level = "info", extra = {}) {
    const entry = {
      id: `log_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      ts: new Date().toISOString(),
      prefix: normalizePrefix(prefix),
      level,
      message: String(message || ""),
      ...extra,
    };
    store.setState((state) => ({
      items: [...state.items, entry].slice(-2000),
    }));
    return entry;
  },
  listBy(filterFn) {
    const items = store.getState().items || [];
    if (typeof filterFn !== "function") return items;
    return items.filter(filterFn);
  },
  toText(filterFn) {
    return logStore
      .listBy(filterFn)
      .map((item) => `[${item.ts}] [${item.prefix}] ${item.message}`)
      .join("\n");
  },
};
