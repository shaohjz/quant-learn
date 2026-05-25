# scripts/register_tasks.ps1 — 注册新的 Windows 计划任务
# 使用：powershell -ExecutionPolicy Bypass -File scripts\register_tasks.ps1

$ProjectRoot = "C:\Users\Administrator\.openclaw\workspace\quant-learn"

# 任务1: 盘中异动扫描（每30分钟，9:30-14:30）
Write-Host "注册任务: QuantLearn_IntradayScanner"
schtasks /create /tn "QuantLearn_IntradayScanner" `
    /tr "$ProjectRoot\scripts\intraday_scanner_runner.bat" `
    /sc MINUTE /mo 30 /st 09:30 /et 15:00 `
    /sd 01/01/2026 `
    /f /rl HIGHEST

# 任务2: 观察池淘汰器（每日8:00）
Write-Host "注册任务: QuantLearn_CleanupWatchlist"
schtasks /create /tn "QuantLearn_CleanupWatchlist" `
    /tr "$ProjectRoot\scripts\cleanup_watchlist_runner.bat" `
    /sc DAILY /st 08:00 `
    /sd 01/01/2026 `
    /f /rl HIGHEST

Write-Host "`n✓ 计划任务注册完成！"
Write-Host "`n查看任务状态："
Write-Host "  schtasks /query /tn QuantLearn_IntradayScanner /fo LIST /v"
Write-Host "  schtasks /query /tn QuantLearn_CleanupWatchlist /fo LIST /v"
Write-Host "`n手动触发测试："
Write-Host "  schtasks /run /tn QuantLearn_IntradayScanner"
Write-Host "  schtasks /run /tn QuantLearn_CleanupWatchlist"
