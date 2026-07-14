# 扫描待处理的需求和Bug - 简化版
$requirementsPath = "pm/requirements"
$bugsPath = "pm/bugs"

$results = @()

# 扫描需求文件
if (Test-Path $requirementsPath) {
    Get-ChildItem -Path $requirementsPath -Filter "*.md" | ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw
        
        # 提取状态
        $statusMatch = [regex]::Match($content, '状态:\s*(.+?)(\n|$)')
        if ($statusMatch.Success) {
            $status = $statusMatch.Groups[1].Value.Trim()
            
            # 只处理 pending 或 in_progress 状态
            if ($status -eq "pending" -or $status -eq "in_progress") {
                # 提取优先级
                $priority = "P3"  # 默认优先级
                $priorityMatch = [regex]::Match($content, '优先级:\s*(.+?)(\n|$)')
                if ($priorityMatch.Success) {
                    $priority = $priorityMatch.Groups[1].Value.Trim()
                }
                
                # 提取标题
                $title = "Unknown Requirement"
                $titleMatch = [regex]::Match($content, '#\s*REQ-\d+:\s*(.+?)(\n|$)')
                if ($titleMatch.Success) {
                    $title = $titleMatch.Groups[1].Value.Trim()
                }
                
                $results += [PSCustomObject]@{
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
}

# 扫描Bug文件
if (Test-Path $bugsPath) {
    Get-ChildItem -Path $bugsPath -Filter "*.md" | ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw
        
        # 提取状态
        $statusMatch = [regex]::Match($content, '状态:\s*(.+?)(\n|$)')
        if ($statusMatch.Success) {
            $status = $statusMatch.Groups[1].Value.Trim()
            
            # 只处理 open, reopened 或 in_progress 状态
            if ($status -eq "open" -or $status -eq "reopened" -or $status -eq "in_progress") {
                # 提取优先级
                $priority = "S3"  # 默认优先级
                $priorityMatch = [regex]::Match($content, '优先级:\s*(.+?)(\n|$)')
                if ($priorityMatch.Success) {
                    $priority = $priorityMatch.Groups[1].Value.Trim()
                }
                
                # 提取标题
                $title = "Unknown Bug"
                $titleMatch = [regex]::Match($content, '#\s*BUG-\d+:\s*(.+?)(\n|$)')
                if ($titleMatch.Success) {
                    $title = $titleMatch.Groups[1].Value.Trim()
                }
                
                $results += [PSCustomObject]@{
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
}

# 按优先级排序
$sortedResults = $results | Sort-Object @{
    Expression = {
        # 优先级排序逻辑
        $p = $_.Priority
        if ($p -match 'S0') { 1 }
        elseif ($p -match 'S1') { 2 }
        elseif ($p -match 'P0') { 3 }
        elseif ($p -match 'S2') { 4 }
        elseif ($p -match 'P1') { 5 }
        elseif ($p -match 'S3') { 6 }
        elseif ($p -match 'P2') { 7 }
        else { 8 }
    }
}, @{
    Expression = { $_.Type }  # 同优先级下Bug优先
}, @{
    Expression = { $_.ID }   # 然后按ID排序
}

# 输出结果
if ($sortedResults.Count -eq 0) {
    Write-Output "NO_TASK"
} else {
    # 选择最高优先级的一项
    $topTask = $sortedResults[0]
    
    Write-Output "=== Pending Tasks ==="
    $sortedResults | ForEach-Object {
        Write-Output "$($_.Type): $($_.ID) - $($_.Title) [Status: $($_.Status), Priority: $($_.Priority)]"
    }
    
    Write-Output "`n=== Selected Highest Priority Task ==="
    Write-Output "$($topTask.Type): $($topTask.ID) - $($topTask.Title)"
    Write-Output "Status: $($topTask.Status)"
    Write-Output "Priority: $($topTask.Priority)"
    Write-Output "File Path: $($topTask.Path)"
    
    # 返回选择的任务信息
    $topTask | ConvertTo-Json
}