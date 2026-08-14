"""Pure text/state helpers for the file-list status bar and operation feedback.

Extracted from ``_base.py`` (see docs/reports/file-list-decomposition-plan-2026-08-15.md §5a):
each function is stateless and reproduces the original branch selection and ``tr(...)``
calls verbatim so the panel's runtime behavior is unchanged.
"""
from AssetsManager import i18n

tr = i18n.tr


def compute_total_size(model) -> int:
    """Sum the cached stat sizes of every non-directory entry in *model*."""
    total_sz = 0
    for e in model.entries:
        if e and not e.is_dir():
            try:
                total_sz += model.cached_stat(e).st_size
            except (OSError, AttributeError):
                pass
    return total_sz


def status_text(*, state, view_mode, total, selected, size_str) -> str:
    """Choose the status-bar label for the current list state and selection."""
    if state is not None and state == "loading":
        return tr("filelist.state.loading")
    if state is not None and state == "scan_error":
        return tr("filelist.state.scan_error")
    if state is not None and state == "empty_folder":
        return tr("filelist.empty")
    if state is not None and state == "empty_filtered":
        return tr("filelist.state.empty_filtered")
    if selected > 0:
        return tr("filelist.status_selected", sel=selected, total=total, sz=size_str, mode=view_mode)
    return tr("filelist.status_total", total=total, sz=size_str, mode=view_mode)


def operation_feedback_text(*, operation, changed_count, errors, warnings, running) -> str:
    """Choose the operation-feedback label from the outcome details."""
    label = tr(f"filelist.feedback.operation.{operation}")
    if running:
        return tr("filelist.feedback.running", operation=label)
    if errors and changed_count:
        if warnings:
            return tr(
                "filelist.feedback.partial_degraded",
                operation=label,
                count=changed_count,
                failed=len(errors),
                warnings=len(warnings),
            )
        return tr(
            "filelist.feedback.partial",
            operation=label,
            count=changed_count,
            failed=len(errors),
        )
    if errors:
        if warnings:
            return tr(
                "filelist.feedback.failed_degraded",
                operation=label,
                failed=len(errors),
                warnings=len(warnings),
            )
        return tr("filelist.feedback.failed", operation=label, failed=len(errors))
    if warnings:
        return tr(
            "filelist.feedback.degraded",
            operation=label,
            count=changed_count,
            warnings=len(warnings),
        )
    return tr("filelist.feedback.succeeded", operation=label, count=changed_count)
