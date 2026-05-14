# scripts/setup_windows_tasks.ps1
# 在 Windows 任务计划程序里创建量化交易的每日任务。
# 需要用管理员权限运行。
#
# 任务安排（中国 A 股交易时段）：
#   09:15  pre_market   盘前信号
#   14:50  settle       收盘前结算（执行卖出信号 + 写日报）
#   15:05  finalize     收盘后最终结算（兜底，确保净值入账）
#
# 卸载：scripts/setup_windows_tasks.ps1 -Uninstall

param(
    [switch]$Uninstall,
    [string]$ProjectRoot = "C:\Users\Administrator\.openclaw\workspace\quant-learn",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$tasks = @(
    @{ Name = "Quant_PreMarket";  Time = "09:15"; Args = "run_daily.py --pre-market" },
    @{ Name = "Quant_Settle";     Time = "14:50"; Args = "run_daily.py --settle" },
    @{ Name = "Quant_Finalize";   Time = "15:05"; Args = "run_daily.py --settle" }
)

if ($Uninstall) {
    foreach ($t in $tasks) {
        try {
            schtasks /Delete /TN $t.Name /F | Out-Null
            Write-Host "✓ 已删除任务: $($t.Name)" -ForegroundColor Yellow
        } catch {
            Write-Host "  跳过（不存在）: $($t.Name)" -ForegroundColor Gray
        }
    }
    return
}

if (-not (Test-Path $ProjectRoot)) {
    throw "项目目录不存在: $ProjectRoot"
}

# 检查管理员权限（创建系统级任务可能需要）
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Warning "未以管理员身份运行，将创建用户级任务（仅当前用户登录时执行）。"
}

foreach ($t in $tasks) {
    $cmd = "cd /d `"$ProjectRoot`" && `"$PythonExe`" $($t.Args) >> `"$ProjectRoot\output\daily.log`" 2>&1"
    Write-Host "→ 创建任务 $($t.Name) @ $($t.Time)" -ForegroundColor Cyan
    schtasks /Create /TN $t.Name /TR "cmd.exe /c $cmd" /SC DAILY /ST $t.Time /F | Out-Null
}

Write-Host ""
Write-Host "✅ 完成。查看：schtasks /Query /TN Quant_PreMarket" -ForegroundColor Green
Write-Host "   日志：$ProjectRoot\output\daily.log"
Write-Host "   注意：任务只在工作日生效是 schtasks 不直接支持的，"
Write-Host "         脚本内可在 run_daily.py 里加 trade_calendar 判断（TODO）。"
