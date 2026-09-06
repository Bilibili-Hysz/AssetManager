# Upstream Issue Drafts（2026-09-06，待用户斟酌后提交）

> 两份草稿均按目标项目惯例撰写（英文、最小复现、版本信息、已核对的排查记录）。是否提交由你决定；提交链接建议回填到本文件与相关代码注释。

---

## Draft 1 · PySide6: `QApplication.setOverrideCursor` fast-fails the whole process when no QApplication instance exists

**Target repo**: pyside6 / qt-for-python (bug tracker: JIRA https://bugreports.qt.io — project PYSIDE)

**Title**: `QApplication.setOverrideCursor()` crashes the process with Windows FAST_FAIL (0xC0000409) when no QApplication instance exists

**Body**:

```markdown
### Environment
- PySide6 6.11.0 (shiboken6 6.11.0)
- Python 3.14.3, Windows 10/11 x64
- Occurs with the offscreen platform plugin as well as default

### Minimal reproduction (3 lines)
```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)  # no instance → process dies
```

### Actual result
The process terminates immediately with Windows fail-fast exception
`0xC0000409` (STATUS_STACK_BUFFER_OVERRUN). No Python traceback, no warning;
`faulthandler` cannot intercept it (C-level abort). Under pytest-xdist this
kills the whole worker and every test it is executing.

### Expected result
A `RuntimeWarning` (or RuntimeError) stating that a QApplication instance is
required — consistent with other Qt static calls that warn instead of
aborting — or at worst a regular Python-level exception.

### Notes
- The same call with a live `QApplication` instance works as documented.
- Found in the wild: a unit test that exercises a window method calling
  `QApplication.setOverrideCursor()` without instantiating the app crashed
  the test process; the crash signature (absence of any handler) made it hard
  to attribute until bisected to this call.
- Suggested fix direction: instance check in the Shiboken binding for the
  static override-cursor family (`setOverrideCursor`, `restoreOverrideCursor`,
  `changeOverrideCursor`).
```

**回填处**：`tests/desktop/test_window_session_switching.py` 的 reduce/FAST_FAIL 注释、质量轮证据行（dialect-unification-plan §5）。

---

## Draft 2 · Vite: `isFileLoadingAllowed` rejects any Windows path containing `~`, breaking projects located under `~`-containing directories

**Target repo**: vitejs/vite (GitHub Discussions → prefer an issue; check CONTRIBUTING — they may route to discussions first)

**Title**: **Windows: any project path containing `~` is hard-rejected by `isFileLoadingAllowed`, breaking dev server and vitest regardless of `server.fs.allow`**

**Body**:

```markdown
### Describe the bug

On Windows, Vite 7.3.6 refuses to serve/load any file whose path contains `~`,
before `server.fs.allow` is consulted. The check lives in
`vite/dist/node/chunks/config.js` (`isFileLoadingAllowed`):

```js
if (isWindows && filePath.includes("~")) return false;
```

A project checked out under e.g. `D:\~Vibe-Coding\my-app` therefore fails on
every module load through the client pipeline. `vitest` (jsdom environment,
`transformMode: "web"`) is affected too: each forked worker first executes
`/@vite/env` and then loads test files through the client pipeline — surfacing
as `Cannot find module '/@vite/env'` unhandled errors while the test files
**silently never run** (no failures are reported; the tests simply don't
execute).

### Reproduction

1. Clone any Vite + vitest project into a directory whose absolute path
   contains `~` (e.g. `D:\~work\demo`) on Windows.
2. `npx vitest run` (jsdom environment).
3. Observe `Cannot find module '/@vite/env'` per test file; the files do not
   run. Same for dev-server module requests.

### Expected behavior

The tilde guard (path-confusion protection against `~` home shorthand) should
not match absolute paths with a drive letter, or should consult
`server.fs.allow` first. Suggested refinement: only treat a leading `~/` or
`~\` (or a `~` path segment) as the home shorthand — e.g.
`filePath === "~" || filePath.startsWith("~/") || filePath.startsWith("~\\")`
after normalization — so `D:\~Vibe-Coding\...` passes.

### Workaround

A `load`-hook plugin that serves files the guard rejects, re-implementing the
remaining security checks (drive-letter colon confusion stays denied; target
must be a real file):

```ts
function tildePathLoader() {
  return {
    name: 'tilde-path-loader-workaround',
    enforce: 'pre' as const,
    load(id: string) {
      if (process.platform !== 'win32' || !id.includes('~')) return undefined;
      const clean = id.split('?')[0];
      const withoutDrive = clean.replace(/^[A-Za-z]:/, '');
      if (withoutDrive.includes(':')) return undefined; // keep colon guard
      try {
        const resolved = path.resolve(clean);
        if (!fs.statSync(resolved).isFile()) return undefined;
        return fs.readFileSync(resolved, 'utf-8');
      } catch {
        return undefined;
      }
    },
  };
}
```

### Environment
- vite 7.3.6, Windows 11, Node 22
- vitest 3.x (jsdom environment files affected; node-environment files load via SSR pipeline and are unaffected)
```

**回填处**：`webui/vite.config.ts` 的 tildePathLoader 注释（"vite 升级若解除该 guard 可删"）。

---

## 提交前检查清单

- [ ] Draft 1：先搜 Qt JIRA 是否已有同报（关键词 `setOverrideCursor FAST_FAIL` / `0xC0000409`）
- [ ] Draft 2：Vite 可能要求先在 Discussions 发起（`isFileLoadingAllowed` 属安全相关改动，维护者对安全边界敏感——草稿已强调"不是要求移除 guard，是收窄匹配条件"）
- [ ] 提交后把 issue 链接回填本文件与对应代码注释
