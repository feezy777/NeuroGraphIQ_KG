"""File metadata helpers: extension parsing, type inference, safe filenames, path checks."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import unicodedata
from pathlib import Path, PurePosixPath

from app.schemas.resource_file import FileRole, FileType

_UNSAFE_CHARS = re.compile(r"[^\w.\-]+", re.UNICODE)
_PATH_TRAVERSAL = re.compile(r"(^|[\\/])\.\.([\\/]|$)")


def normalize_extension(filename: str) -> str:
    """Return lowercase extension including compound forms like .nii.gz."""
    name = Path(filename).name.lower()
    if name.endswith(".nii.gz"):
        return ".nii.gz"
    if name.endswith(".tar.gz"):
        return ".tar.gz"
    suffix = Path(name).suffix.lower()
    return suffix


def infer_file_type(filename: str, override: FileType | None = None) -> FileType:
    """Coarse file type inference from extension; user override wins."""
    if override is not None:
        return override

    ext = normalize_extension(filename)
    if ext in (".nii", ".nii.gz"):
        return FileType.nifti
    if ext in (".xml", ".txt", ".csv", ".tsv"):
        return FileType.label_table if ext in (".xml", ".csv", ".tsv") else FileType.text
    if ext in (".xls", ".xlsx"):
        return FileType.spreadsheet
    if ext == ".pdf":
        return FileType.pdf
    if ext in (".owl", ".rdf", ".ttl"):
        return FileType.ontology
    if ext == ".json":
        return FileType.json
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff"):
        return FileType.image
    if ext in (".mat", ".npy", ".npz"):
        return FileType.connectivity_matrix
    return FileType.other


def infer_file_role(filename: str, file_type: FileType | None = None) -> FileRole:
    """Suggest file_role from filename + extension (ignores user override)."""
    ft = file_type if file_type is not None else infer_file_type(filename)
    ext = normalize_extension(filename)
    name_lower = filename.lower().replace("_", " ")

    if ext in (".xlsx", ".xls") and "brain volume" in name_lower:
        return FileRole.macro_region_pool_source
    if ext == ".xml":
        return FileRole.label_dictionary
    if ext in (".csv", ".tsv"):
        return FileRole.label_dictionary
    if ext in (".xlsx", ".xls"):
        return FileRole.auxiliary
    if ext in (".nii", ".nii.gz"):
        return FileRole.primary_atlas_volume
    if ext == ".json":
        return FileRole.metadata
    if ext in (".owl", ".rdf", ".ttl"):
        return FileRole.ontology_source
    if ext == ".pdf":
        return FileRole.documentation
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"):
        return FileRole.auxiliary
    if ext in (".mat", ".npy", ".npz"):
        return FileRole.connectivity_source
    if ft == FileType.text:
        return FileRole.documentation
    return FileRole.unknown


def suggest_file_classification(
    filename: str,
) -> tuple[FileType, FileRole]:
    """Return recommended (file_type, file_role) for upload forms."""
    ft = infer_file_type(filename)
    fr = infer_file_role(filename, ft)
    return ft, fr


def safe_filename(original: str, *, max_len: int = 200) -> str:
    """Sanitize original filename for disk storage (basename only, no path segments)."""
    base = Path(original).name
    base = unicodedata.normalize("NFKC", base)
    if _PATH_TRAVERSAL.search(base):
        base = base.replace("..", "_")
    base = _UNSAFE_CHARS.sub("_", base).strip("._")
    if not base:
        base = "upload"
    if len(base) > max_len:
        ext = normalize_extension(base)
        stem = base[: max_len - len(ext)] if ext else base[:max_len]
        base = f"{stem}{ext}"
    return base


def guess_mime_type(filename: str, content_type: str | None = None) -> str | None:
    if content_type and content_type != "application/octet-stream":
        return content_type
    guessed, _ = mimetypes.guess_type(filename)
    return guessed


def sha256_stream(read_fn, chunk_size: int = 65536) -> tuple[str, int]:
    """Hash readable stream via read_fn(); returns (hex_digest, total_bytes)."""
    h = hashlib.sha256()
    total = 0
    while True:
        chunk = read_fn(chunk_size)
        if not chunk:
            break
        h.update(chunk)
        total += len(chunk)
    return h.hexdigest(), total


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_stored_filename(file_id: str, sha256: str, original: str) -> str:
    prefix = sha256[:12]
    return f"{file_id}_{prefix}_{safe_filename(original)}"


def relative_storage_path(resource_id: str, stored_filename: str) -> str:
    """POSIX-style relative path stored in DB."""
    return str(PurePosixPath(resource_id) / stored_filename)


def resolve_under_root(upload_root: Path, storage_path: str) -> Path:
    """Resolve storage_path under upload_root; reject path traversal."""
    root = upload_root.resolve()
    rel = PurePosixPath(storage_path)
    if ".." in rel.parts:
        raise ValueError("path traversal detected in storage_path")
    full = (root / Path(*rel.parts)).resolve()
    if not str(full).startswith(str(root)):
        raise ValueError("resolved path escapes upload root")
    return full
