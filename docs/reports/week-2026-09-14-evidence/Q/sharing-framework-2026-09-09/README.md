# 分享框架集成证据

主报告：[首批可开发框架](../../../sharing-framework-2026-09-09.md)。日期 2026-09-09，候选为含用户未提交变更的当前源码；未打 exe、未发布。

| 文件 | 内容 |
|---|---|
| `python-regression.xml` | 142 passed、1 skipped；Qt offscreen，独立源码快照，1 条旧 finished.disconnect RuntimeWarning |
| `frontend-regression.xml` | 6 个文件、60 项 Vitest 测试通过 |
| `browser-regression.xml` | 3 项 Chromium 通过；其中 1 项真实 loopback HTTP、2 项模拟接口交互 |
| `static-gates.json` | 各项静态门禁的命令、退出码及输出 |
| `source-manifest.json` | 源码/构建 SHA-256 与测试快照比对、起始 Git HEAD |
| `desktop-center-offscreen.png` | 英文桌面中心，offscreen 组件布局检查，显式加载本机 Segoe UI |
| `share-live-mobile.png` | 真实 HTTP 夹具的分享目录与操作 |
| `share-mobile.png` / `share-mobile-light.png` | 375px 浏览器深色/浅色交互截图 |

## 重现方式

Python 只在完整源码快照执行，设置 `QT_QPA_PLATFORM=offscreen`；`tests/conftest.py` 初始化独立 RuntimeData。

```powershell
python -m pytest -n 0 tests/lan/test_share_entries_api.py tests/lan/test_share_preview_policy.py tests/lan/test_login_share_verify_offload.py tests/lan/test_t2_t4_contracts.py tests/lan/test_route_policy_contract.py tests/lan/test_public_contracts.py tests/unit/test_gen_ts_types.py tests/unit/test_share_delivery.py tests/desktop/test_share_center_dialog.py tests/desktop/test_share_link_dialog.py tests/desktop/test_sharing_settings_dialog.py tests/desktop/test_share_api.py tests/desktop/test_share_qr_dialog.py tests/unit/test_lan_sharing.py tests/desktop/test_share_status_url.py --junitxml=sharing-framework-regression.xml -v
```

前端在 `webui` 目录运行；构建之后把当前 `dist` 同步到该测试快照。

```powershell
npm run build
npm test -- src/pages/ShareReceivePage.test.tsx src/api/shares.contract.test.ts src/components/ui/Modal.test.tsx src/App.test.tsx src/components/layout/ConnectionStatusBanner.test.tsx src/api/public-contracts.test.ts
```

在快照目录启动限时测试服务，另一个终端运行浏览器检查。服务只使用生成的测试资产、内存数据库和 loopback 地址。

```powershell
python -m tests.test_support.share_browser_server --ready-file sharing-browser-fixture.json --seconds 120
```

```powershell
# 下列变量指向刚生成的快照内 JSON，按实际快照位置填写。
$env:AM_SHARE_BROWSER_FIXTURE='<快照绝对路径>\sharing-browser-fixture.json'
$env:PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH='C:\Program Files\Google\Chrome\Application\chrome.exe'
npx playwright test --config=playwright.sharing.config.ts
```

真实 HTTP 夹具使用测试应用组合，不能代替生产启动/认证中间件全链路验收。跨设备扫码与独立网络公网验证均为 NOT_RUN。符号链接系统用例当前因权限跳过，不能据此声明该 Windows 环境的 symlink 实测通过。
