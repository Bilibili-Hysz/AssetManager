"""Shared formatting and classification utilities."""


def format_size(size: int) -> str:
    """Format bytes to human readable string.

    Examples:
        format_size(1024) -> "1.0 KB"
        format_size(1048576) -> "1.0 MB"
    """
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


CATEGORY_MAP: dict[str, str] = {
    ".png": "images", ".jpg": "images", ".jpeg": "images", ".gif": "images",
    ".bmp": "images", ".webp": "images", ".tiff": "images", ".svg": "images",
    ".blend": "3d", ".fbx": "3d", ".obj": "3d", ".gltf": "3d", ".glb": "3d",
    ".max": "3d", ".ma": "3d", ".mb": "3d", ".3ds": "3d", ".stl": "3d",
    ".mp4": "videos", ".mov": "videos", ".avi": "videos", ".mkv": "videos",
    ".webm": "videos", ".wmv": "videos",
    ".zip": "archives", ".rar": "archives", ".7z": "archives",
    ".tar": "archives", ".gz": "archives",
    ".txt": "documents", ".pdf": "documents", ".docx": "documents",
    ".xlsx": "documents", ".pptx": "documents", ".md": "documents",
    ".json": "documents", ".py": "documents", ".xml": "documents",
}
