"""Domain layer — core business concepts and value objects.

This package contains pure domain types that represent the core business
concepts of AssetManager. Domain types have no dependencies on infrastructure,
UI, or external libraries.

Modules:
    asset.py     — AssetPath, AssetType, AssetInfo
    errors.py    — DomainError hierarchy
    event_bus.py — EventBus (decoupled event pub/sub)
    events.py    — DomainEvent types
    library.py   — LibraryPath
    share.py     — ShareLink
"""
