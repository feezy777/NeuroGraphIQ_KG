import { apiJson, apiUpload } from "../api.js";

export const fileImportService = {
  async uploadFiles(files) {
    const uploaded = [];
    for (const file of files || []) {
      const result = await apiUpload("/api/files/upload", file);
      const item = result.file || {};
      item.__upload_meta = {
        auto_validation: result.auto_validation || {},
      };
      uploaded.push(item);
    }
    return uploaded;
  },

  async listFiles() {
    return apiJson("/api/files/list");
  },

  async validateFile(fileId, options = {}) {
    const payload = { file_id: fileId };
    if (options && typeof options === "object") {
      if (options.runtimeOverrides && typeof options.runtimeOverrides === "object") {
        payload.runtime_overrides = options.runtimeOverrides;
      }
      if (options.deepseekOverride && typeof options.deepseekOverride === "object") {
        payload.deepseek_override = options.deepseekOverride;
      }
    }
    return apiJson("/api/files/validate", "POST", payload);
  },

  async removeFile(fileId) {
    const response = await fetch(`/api/files/${encodeURIComponent(fileId)}`, {
      method: "DELETE",
      cache: "no-store",
    });
    const text = await response.text();
    let payload = {};
    if (String(text || "").trim()) {
      try {
        payload = JSON.parse(text);
      } catch {
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
  },

  async applyAutoFix(fileId) {
    return apiJson("/api/files/apply-auto-fix", "POST", { file_id: fileId });
  },

  async getReport(fileId) {
    return apiJson(`/api/files/${encodeURIComponent(fileId)}/report`);
  },

  async getPreview(fileId, { page = 1, pageSize = 120, view = "auto" } = {}) {
    return apiJson(
      `/api/files/${encodeURIComponent(fileId)}/preview?page=${encodeURIComponent(page)}&page_size=${encodeURIComponent(pageSize)}&view=${encodeURIComponent(view)}`,
    );
  },

  getContentUrl(fileId) {
    return `/api/files/${encodeURIComponent(fileId)}/content`;
  },
};
