# Scan for pending tasks
$reqResults = @()
$bugResults = @()

# Check requirements
Get-ChildItem "pm/requirements/*.md" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    $status = ""
    $priority = ""
    if ($content -match '\*\*状态\*\*:\s*(\S+)') { $status = $Matches[1] }
    if ($content -match '\*\*优先级\*\*:\s*(\S+)') { $priority = $Matches[1] }
    if ($status -in @("pending", "in_progress")) {
        $reqResults += [PSCustomObject]@{
            File = $_.Name
            Type = "REQ"
            Status = $status
            Priority = $priority
        }
    }
}

# Check bugs
Get-ChildItem "pm/bugs/*.md" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    $status = ""
    $severity = ""
    if ($content -match '\*\*状态\*\*:\s*(\S+)') { $status = $Matches[1] }
    if ($content -match '\*\*优先级\*\*:\s*(\S+)') { $severity = $Matches[1] }
    if ($status -in @("open", "reopened", "in_progress")) {
        $bugResults += [PSCustomObject]@{
            File = $_.Name
            Type = "BUG"
            Status = $status
            Severity = $severity
        }
    }
}

Write-Host "=== Pending Requirements ==="
$reqResults | Format-Table -AutoSize

Write-Host "`n=== Open Bugs ==="
$bugResults | Format-Table -AutoSize

# Output summary
Write-Host "`n=== Summary ==="
Write-Host "Pending Requirements: $($reqResults.Count)"
Write-Host "Open Bugs: $($bugResults.Count)"

# Save to temp file for parsing
$output = @{
    requirements = $reqResults
    bugs = $bugResults
} | ConvertTo-Json -Compress

$output | Out-File -FilePath "pm/data/task_scan_result.json" -Encoding UTF8
