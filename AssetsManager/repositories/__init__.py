"""Repository layer — data access abstractions.

Repositories encapsulate all database operations behind clean interfaces.
Each repository handles one aggregate root or table group.

Modules:
    tag_repository.py        — Tag CRUD operations
    metadata_repository.py   — File metadata (notes, URLs, size cache)
    share_repository.py      — Share link persistence
    auth_repository.py       — Users and invite codes CRUD
    thumbnail_repository.py  — Thumbnail cache table access
"""
