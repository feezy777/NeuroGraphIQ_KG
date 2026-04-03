export async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: {
      ...(options.headers || {}),
    },
    ...options,
  });

  const text = await response.text();
  let payload = {};
  if (text.trim()) {
    try {
      payload = JSON.parse(text);
    } catch {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status} ${response.statusText}: ${text.slice(0, 320)}`);
      }
      payload = { raw: text };
    }
  }

  if (!response.ok) {
    const message = payload?.error || payload?.message || `HTTP ${response.status} ${response.statusText}`;
    const err = new Error(String(message));
    err.payload = payload;
    throw err;
  }
  return payload;
}

export async function apiJson(url, method = "GET", body = null) {
  const options = { method };
  if (body !== null) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  return apiRequest(url, options);
}

export async function apiUpload(url, file) {
  const form = new FormData();
  form.append("file", file);
  return apiRequest(url, {
    method: "POST",
    body: form,
  });
}
