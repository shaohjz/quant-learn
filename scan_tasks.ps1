# 扫描待处理的需求和Bug
$requirementsPath = "pm/requirements"
$bugsPath = "pm/bugs"

$results = @()

# 扫描需求文件
if (Test-Path $requirementsPath) {
    Get-ChildItem -Path $requirementsPath -Filter "*.md" | ForEach-Object {
        $file = $_.FullName
        $content = Get-Content $file -Raw
        
        # 提取状态
        if ($content -match '状态:\s*(.+?)(\n|$)') {
            $status = $matches[1].Trim()
            
            # 只处理 pending 或 in_progress 状态
            if ($status -eq "pending" -or $status -eq "in_progress") {
                # 提取优先级
                $priority = "P3"  # 默认优先级
                if ($content -match '优先级:\s*(.+?)(\n|$)') {
                    $priority = $matches[1].Trim()
                }
                
                # 提取标题
                $title = "未知需求"
                if ($content -match '#\s*REQ-\d+:\s*(.+?)(\n|$)') {
                    $title = $matches[1].Trim()
                }
                
                $results += [PSCustomObject]@{
                    Type = "需求"
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
        if ($content -match '状态:\s*(.+?)(\n|$)') {
            $status = $matches[1].Trim()
            
            # 只处理 open, reopened 或 in_progress 状态
            if ($status -eq "open" -or $status -eq "reopened" -or $status -eq "in_progress") {
                # 提取优先级
                $priority = "S3"  # 默认优先级
                if ($content -match '优先级:\s*(.+?)(\n|$)') {
                    $priority = $matches[1].Trim()
                }
                
                # 提取标题
                $title = "未知Bug"
                if ($content -match '#\s*BUG-\d+:\s*(.+?)(\n|$)') {
                    $title = $matches[1].Trim()
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
    
    Write-Output "=== 待处理任务列表 ==="
    $sortedResults | ForEach-Object {
        Write-Output "$($_.Type): $($_.ID) - $($_.Title) [状态: $($_.Status), 优先级: $($_.Priority)]"
    }
    
    Write-Output "`n=== 选择最高优先级任务 ==="
    Write-Output "$($topTask.Type): $($topTask.ID) - $($topTask.Title)"
    Write-Output "状态: $($topTask.Status)"
    Write-Output "优先级: $($topTask.Priority)"
    Write-Output "文件路径: $($topTask.Path)"
    
    # 返回选择的任务信息
    $topTask | ConvertTo-Json
}