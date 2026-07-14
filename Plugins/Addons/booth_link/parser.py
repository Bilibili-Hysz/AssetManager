"""Booth Link Parser — parse _link/*.txt files from Booth downloader tools.

Supports both the Tampermonkey script format and booth_link_batch.py format:
  Line 1: URL
  Line 2: blank
  Line 3: 商品名称: ...
  Line 4: 作者: ...
  Line 5: 商品ID: ...
"""
import os


def match(file_path: str) -> bool:
    """Match files inside _link/ directories with .txt extension."""
    name = os.path.basename(file_path).lower()
    parent = os.path.basename(os.path.dirname(file_path)).lower()
    return name.endswith(".txt") and parent == "_link"


def parse(file_path: str) -> dict:
    """Parse a Booth _link/*.txt file and return structured metadata."""
    result = {
        "url": "",
        "name": "",
        "author": "",
        "item_id": "",
    }
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [line.strip() for line in f]
    except OSError:
        return result

    if not lines:
        return result

    # Line 1: URL
    if lines[0].startswith("http://") or lines[0].startswith("https://"):
        result["url"] = lines[0]

    # Parse key-value pairs (lines 3+)
    for line in lines[2:]:
        if not line:
            continue
        for key, target in [
            ("商品名称:", "name"),
            ("商品名:", "name"),
            ("店铺:", "author"),
            ("作者:", "author"),
            ("商品ID:", "item_id"),
            ("商品编号:", "item_id"),
        ]:
            if line.startswith(key):
                result[target] = line[len(key):].strip()
                break

    return result
