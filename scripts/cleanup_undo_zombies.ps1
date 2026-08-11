# 清理测试残留的 undo 备份僵尸目录（需要管理员权限）
#
# 背景：历史测试会话的挂起进程（python.exe，内存 ~30KB、CPU≈0、存活数天）
# 在 Windows 上持有系统临时目录下 AssetsManager_undo_* 目录的句柄，
# 导致这些空目录无法被程序化删除（PermissionError WinError 5）。
# 本脚本以管理员权限：1) 结束此类僵尸进程；2) 删除全部 AssetsManager_undo_*
# 残留目录（含 >7 天与 7 天内的测试残留）。
#
# 用法（管理员 PowerShell）：
#   powershell -ExecutionPolicy Bypass -File scripts\cleanup_undo_zombies.ps1
#
# 注意：
# - 仅结束 CPU 时间≈0 且内存极小的 python 僵尸进程（不触碰正常 python 进程）。
# - 删除的是系统临时目录下 AssetsManager_undo_*——这些是应用级临时撤销备份，
#   7 天策略下本就会被应用启动清理；如需保留最近 7 天内真实应用的撤销备份，
#   可先运行 `python -m pytest` 一次（conftest 会按 7 天策略清理 >7 天的部分）。

$ErrorActionPreference = 'SilentlyContinue'

Write-Host '== 1. 结束 python 僵尸进程（CPU≈0 且内存 < 2MB） =='
$zombies = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object {
        $p = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        $p -and $p.CPU -lt 1 -and $p.WorkingSet64 -lt 2MB
    }
foreach ($z in $zombies) {
    Write-Host ("  PID {0} (内存 {1:N0} B) -> 结束" -f $z.ProcessId, $z.WorkingSet64)
    Stop-Process -Id $z.ProcessId -Force
}
if (-not $zombies) { Write-Host '  无僵尸进程' }

Write-Host '== 2. 删除 AssetsManager_undo_* 残留目录 =='
$temp = [System.IO.Path]::GetTempPath()
$removed = 0
Get-ChildItem -Path $temp -Directory -Filter 'AssetsManager_undo_*' -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath $_.FullName)) { $removed++ }
    }
Write-Host "  已删除 $removed 个目录"

$left = (Get-ChildItem -Path $temp -Directory -Filter 'AssetsManager_undo_*' | Measure-Object).Count
Write-Host "  剩余 $left 个（若仍 >0，请重启机器释放句柄后重跑）"
