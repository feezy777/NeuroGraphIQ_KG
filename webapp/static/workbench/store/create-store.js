export function createStore(initialState) {
  let state = { ...initialState };
  const listeners = new Set();

  const getState = () => state;

  const setState = (patch) => {
    const nextPatch = typeof patch === "function" ? patch(state) : patch;
    state = { ...state, ...(nextPatch || {}) };
    listeners.forEach((listener) => listener(state));
    return state;
  };

  const subscribe = (listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  };

  const reset = () => {
    state = { ...initialState };
    listeners.forEach((listener) => listener(state));
  };

  return {
    getState,
    setState,
    subscribe,
    reset,
  };
}
