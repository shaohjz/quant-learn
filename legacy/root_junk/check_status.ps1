# Check status of all bug and requirement files
Get-ChildItem "pm/bugs/*.md" | ForEach-Object {
    $name = $_.Name
    $content = Get-Content $_.FullName -Raw
    if ($content -match '\*\*状态\*\*:\s*(\S+)') {
        $status = $Matches[1]
        $priority = ""
        if ($content -match '\*\*优先级\*\*:\s*(\S+)') { $priority = $Matches[1] }
        Write-Host "$name : status=$status : priority=$priority"
    }
}

Write-Host "`n=== Requirements ===`n"
Get-ChildItem "pm/requirements/*.md" | ForEach-Object {
    $name = $_.Name
    $content = Get-Content $_.FullName -Raw
    if ($content -match '\*\*状态\*\*:\s*(\S+)') {
        $status = $Matches[1]
        $priority = ""
        if ($content -match '\*\*优先级\*\*:\s*(\S+)') { $priority = $Matches[1] }
        Write-Host "$name : status=$status : priority=$priority"
    }
}
