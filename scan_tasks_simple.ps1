# 简单扫描待处理任务
$reqDir = "C:\Users\Administrator\.openclaw\workspace\quant-learn\pm\requirements"
$bugDir = "C:\Users\Administrator\.openclaw\workspace\quant-learn\pm\bugs"

Write-Host "扫描待处理任务..." -ForegroundColor Cyan

# 扫描需求
$reqTasks = @()
Get-ChildItem "$reqDir\*.md" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    if ($content -match '状态:\s*(pending|in_progress)') {
        $status = $matches[1]
        $priority = "P3"
        if ($content -match '优先级:\s*(\S+)') {
            $priority = $matches[1]
        }
        $reqTasks += @{
            File = $_.Name
            ID = $_.BaseName
            Type = "requirement"
            Status = $status
            Priority = $priority
            Path = $_.FullName
        }
    }
}

# 扫描Bug
$bugTasks = @()
Get-ChildItem "$bugDir\*.md" | ForEach-Object {
    $content = Get-Content $_.FullName -Raw
    if ($content -match '状态:\s*(open|reopened|in_progress)') {
        $status = $matches[1]
        $priority = "P3"
        if ($content -match '优先级:\s*(\S+)') {
            $priority = $matches[1]
        }
        $bugTasks += @{
            File = $_.Name
            ID = $_.BaseName
            Type = "bug"
            Status = $status
            Priority = $priority
            Path = $_.FullName
        }
    }
}

# 合并所有任务
$allTasks = $reqTasks + $bugTasks

if ($allTasks.Count -eq 0) {
    Write-Host "✅ 没有待处理的任务" -ForegroundColor Green
    exit 0
}

# 按优先级排序
$allTasks = $allTasks | Sort-Object {
    $pri = $_.Priority
    $sta = $_.Status
    $typ = $_.Type
    
    # 优先级分数
    $score = 0
    if ($pri -match "S0|S1|P0") { $score += 1000 }
    elseif ($pri -match "P1") { $score += 100 }
    elseif ($pri -match "P2") { $score += 10 }
    else { $score += 1 }
    
    # 状态分数
    if ($sta -eq "reopened") { $score += 500 }
    elseif ($sta -eq "open") { $score += 400 }
    elseif ($sta -eq "in_progress") { $score += 300 }
    
    # Bug 优先于需求
    if ($typ -eq "bug") { $score += 50 }
    
    $score
} -Descending

Write-Host "`n待处理任务列表（按优先级排序）:" -ForegroundColor Yellow
$i = 1
foreach ($task in $allTasks) {
    Write-Host "`n$($i). [$($task.Type)] $($task.ID)" -ForegroundColor White
    Write-Host "   文件: $($task.File)" -ForegroundColor Gray
    Write-Host "   状态: $($task.Status)" -ForegroundColor Yellow
    Write-Host "   优先级: $($task.Priority)" -ForegroundColor Magenta
    $i++
}

# 输出最高优先级的任务
if ($allTasks.Count -gt 0) {
    $topTask = $allTasks[0]
    Write-Host "`n🎯 最高优先级任务:" -ForegroundColor Red
    Write-Host "   $($topTask.Type.ToUpper()): $($topTask.ID)" -ForegroundColor Red
    Write-Host "   优先级: $($topTask.Priority)" -ForegroundColor Red
    Write-Host "   状态: $($topTask.Status)" -ForegroundColor Red
    
    # 输出任务信息
    Write-Output "TOP_TASK_ID=$($topTask.ID)"
    Write-Output "TOP_TASK_TYPE=$($topTask.Type)"
    Write-Output "TOP_TASK_PRIORITY=$($topTask.Priority)"
    Write-Output "TOP_TASK_STATUS=$($topTask.Status)"
    Write-Output "TOP_TASK_PATH=$($topTask.Path)"
}