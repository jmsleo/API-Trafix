import uuid
from pathlib import Path

from api_trafix.config.settings import get_settings
from api_trafix.models.signage import SignageContent, SignageContentType


class SignageMediaError(Exception):
    pass


_IMAGE_MIME = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

_VIDEO_MIME = {
    "mp4": "video/mp4",
    "mov": "video/quicktime",
}


def _allowed_extensions() -> dict[str, str]:
    settings = get_settings()
    mapping: dict[str, str] = {}
    for ext in settings.signage_allowed_image_extensions.split(","):
        ext = ext.strip().lower()
        if ext in _IMAGE_MIME:
            mapping[ext] = _IMAGE_MIME[ext]
    for ext in settings.signage_allowed_video_extensions.split(","):
        ext = ext.strip().lower()
        if ext in _VIDEO_MIME:
            mapping[ext] = _VIDEO_MIME[ext]
    return mapping


def media_dir() -> Path:
    settings = get_settings()
    path = Path(settings.signage_media_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def resolve_content_file(content: SignageContent) -> Path:
    if not content.file_path:
        raise SignageMediaError("Konten tidak memiliki file media")
    directory = media_dir()
    path = (directory / content.file_path).resolve()
    if path.parent != directory:
        raise SignageMediaError("Path file media tidak valid")
    return path


def validate_upload(
    content_type: SignageContentType,
    filename: str | None,
) -> str:
    if content_type not in (SignageContentType.IMAGE, SignageContentType.VIDEO):
        raise SignageMediaError("content_type harus berupa gambar atau video")
    extension = Path(filename or "").suffix.lstrip(".").lower()
    allowed = _allowed_extensions()
    mime = allowed.get(extension)
    if mime is None:
        raise SignageMediaError(
            f"Jenis file '.{extension}' tidak didukung, yang diizinkan: {', '.join(sorted(allowed))}"
        )
    return mime


def save_upload(content_type: SignageContentType, mime: str, data: bytes, filename: str | None) -> str:
    extension = Path(filename or "").suffix.lstrip(".").lower() or mime.split("/")[-1]
    stored_name = f"{uuid.uuid4().hex}_{content_type.value}.{extension}"
    target = media_dir() / stored_name
    target.write_bytes(data)
    return stored_name


def delete_content_file(content: SignageContent) -> None:
    if not content.file_path:
        return
    try:
        resolve_content_file(content).unlink(missing_ok=True)
    except SignageMediaError:
        pass
