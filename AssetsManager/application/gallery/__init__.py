"""Gallery projection service subpackage.

Internal modules split the monolithic ``gallery_service`` module:

- ``_types``      — dataclasses, errors, constants and helpers.
- ``_persistence`` — persisted home projection load/save mixin.
- ``_projection_builder`` — filesystem-to-response traversal mixin.
- ``_incremental`` — FileSystemChanged incremental apply mixin.

The public API remains on ``AssetsManager.application.gallery_service``;
importing from this subpackage's private modules is not part of the contract.
"""
