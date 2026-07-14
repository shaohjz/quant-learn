# 检查待处理的任务和Bug - PowerShell版本
$requirementsPath = "pm/requirements"
$bugsPath = "pm/bugs"

$tasks = @()

# 扫描需求文件
if (Test-Path $requirementsPath) {
    Get-ChildItem -Path $requirementsPath -Filter "*.md" | ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw
        
        # 提取状态 - 尝试多种格式
        $status = "unknown"
        $patterns = @(
            '\*\*状态\*\*:\s*(.+?)(\n|$)',
            '状态:\s*(.+?)(\n|$)',
            '- \*\*状态\*\*:\s*(.+?)(\n|$)'
        )
        
        foreach ($pattern in $patterns) {
            if ($content -match $pattern) {
                $status = $matches[1].Trim()
                break
            }
        }
        
        # 只处理 pending 或 in_progress 状态
        if ($status -eq "pending" -or $status -eq "in_progress") {
            # 提取优先级
            $priority = "P3"
            $priorityPatterns = @(
                '\*\*优先级\*\*:\s*(.+?)(\n|$)',
                '优先级:\s*(.+?)(\n|$)'
            )
            
            foreach ($pattern in $priorityPatterns) {
                if ($content -match $pattern) {
                    $priority = $matches[1].Trim()
                    break
                }
            }
            
            # 提取标题
            $title = $_.Name -replace '\.md$', ''
            if ($content -match '#\s*REQ-\d+:\s*(.+?)(\n|$)') {
                $title = $matches[1].Trim()
            }
            
            $tasks += [PSCustomObject]@{
                Type = "Requirement"
                ID = $_.Name -replace '\.md$', ''
                Title = $title
                Status = $status
                Priority = $priority
                Path = $file
            }
        }
    }
}

# 扫描Bug文件
if (Test-Path $bugsPath) {
    Get-ChildItem -Path $bugsPath -Filter "*.md" | ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw
        
        # 提取状态 - 尝试多种格式
        $status = "unknown"
        $patterns = @(
            '\*\*状态\*\*:\s*(.+?)(\n|$)',
            '状态:\s*(.+?)(\n|$)',
            '- \*\*状态\*\*:\s*(.+?)(\n|$)'
        )
        
        foreach ($pattern in $patterns) {
            if ($content -match $pattern) {
                $status = $matches[1].Trim()
                break
            }
        }
        
        # 只处理 open, reopened 或 in_progress 状态
        if ($status -eq "open" -or $status -eq "reopened" -or $status -eq "in_progress") {
            # 提取优先级/严重程度
            $priority = "S3"
            $priorityPatterns = @(
                '\*\*优先级\*\*:\s*(.+?)(\n|$)',
                '优先级:\s*(.+?)(\n|$)',
                '\*\*严重程度\*\*:\s*(.+?)(\n|$)'
            )
            
            foreach ($pattern in $priorityPatterns) {
                if ($content -match $pattern) {
                    $priorityText = $matches[1].Trim()
                    # 转换严重程度为优先级
                    if ($priorityText -match 'S[0123]'') {
                        $priority = $priorityText
                    } elseif ($priorityText -match '高|critical|blocker') {
                        $priority = "S0"
                    } elseif ($priorityText -match '中|major') {
                        $priority = "S2"
                    } elseif ($priorityText -match '低|minor') {
                        $priority = "S3"
                    } else {
                        $priority = $priorityText
                    }
                    break
                }
            }
            
            # 提取标题
            $title = $_.Name -replace '\.md$', ''
            if ($content -match '#\s*Bug 报告.*?:\s*(.+?)(\n|$)') {
                $title = $matches[1].Trim()
            } elseif ($content -match '#\s*(.+?)(\n|$)') {
                $title = $matches[1].Trim()
            }
            
            $tasks += [PSCustomObject]@{
                Type = "Bug"
                ID = $_.Name -replace '\.md$', ''
                Title = $title
                Status = $status
                Priority = $priority
                Path = $file
            }
        }
    }
}

# 检查是否有待处理的任务
if ($tasks.Count -eq 0) {
    Write-Output "NO_TASK"
    exit
}

# 按优先级排序
$sortedTasks = $tasks | Sort-Object @{
    Expression = {
        $p = $_.Priority
        $s = $_.Status
        $t = $_.Type
        
        # 优先级排序规则
        if ($p -match 'S[01]' -and $s -eq "reopened") { 0 }  # S0/S1 reopened Bug
        elseif ($p -match 'S[01]' -and $s -eq "open") { 1 }   # S0/S1 open Bug
        elseif ($p -match 'P0' -and $s -eq "pending") { 2 }    # P0 pending 需求
        elseif ($p -match 'S1') { 3 }                          # P1 Bug
        elseif ($p -match 'P1' -and $t -eq "Bug") { 3 }       # P1 Bug
        elseif ($p -match 'P1' -and $t -eq "Requirement") { 4 } # P1 需求
        else { 5 }                                              # 其他
    }
}, @{
    Expression = { $_.Type }  # 同优先级下Bug优先
}, @{
    Expression = { $_.ID }   # 然后按ID排序
}

# 输出结果
Write-Output "=== Pending Tasks ==="
$sortedTasks | ForEach-Object {
    Write-Output "$($_.Type): $($_.ID) - $($_.Title)"
    Write-Output "  Status: $($_.Status), Priority: $($_.Priority)"
    Write-Output "  File: $($_.Path)"
    Write-Output ""
}

# 选择最高优先级任务
$topTask = $sortedTasks[0]
Write-Output "=== Selected Highest Priority Task ==="
Write-Output "Type: $($topTask.Type)"
Write-Output "ID: $($topTask.ID)"
Write-Output "Title: $($topTask.Title)"
Write-Output "Status: $($topTask.Status)"
Write-Output "Priority: $($topTask.Priority)"
Write-Output "File: $($topTask.Path)"

# 输出JSON格式
$topTask | ConvertTo-Json