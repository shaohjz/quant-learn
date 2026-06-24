# 扫描待处理任务
$reqDir = "C:\Users\Administrator\.openclaw\workspace\quant-learn\pm\requirements"
$bugDir = "C:\Users\Administrator\.openclaw\workspace\quant-learn\pm\bugs"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "扫描待处理任务" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# 扫描需求
Write-Host "`n1. 扫描需求..." -ForegroundColor Yellow
$reqTasks = @()
Get-ChildItem "$reqDir\*.md" | ForEach-Object {
    $file = $_.FullName
    $content = Get-Content $file -Raw
    if ($content -match '状态:\s*(pending|in_progress)') {
        $status = $matches[1]
        $priority = "P3"
        if ($content -match '优先级:\s*(\S+)') {
            $priority = $matches[1]
        }
        $reqTasks += [PSCustomObject]@{
            File = $_.Name
            ID = $_.BaseName
            Type = "requirement"
            Status = $status
            Priority = $priority
            Path = $file
        }
        Write-Host "   找到: $($_.Name) - $status [$priority]" -ForegroundColor Green
    }
}

Write-Host "`n   找到 $($reqTasks.Count) 个待处理需求" -ForegroundColor Yellow

# 扫描Bug
Write-Host "`n2. 扫描Bug..." -ForegroundColor Yellow
$bugTasks = @()
Get-ChildItem "$bugDir\*.md" | ForEach-Object {
    $file = $_.FullName
    $content = Get-Content $file -Raw
    if ($content -match '状态:\s*(open|reopened|in_progress)') {
        $status = $matches[1]
        $priority = "P3"
        if ($content -match '优先级:\s*(\S+)') {
            $priority = $matches[1]
        }
        $bugTasks += [PSCustomObject]@{
            File = $_.Name
            ID = $_.BaseName
            Type = "bug"
            Status = $status
            Priority = $priority
            Path = $file
        }
        Write-Host "   找到: $($_.Name) - $status [$priority]" -ForegroundColor Red
    }
}

Write-Host "`n   找到 $($bugTasks.Count) 个待处理Bug" -ForegroundColor Yellow

# 合并所有任务
$allTasks = $reqTasks + $bugTasks

if ($allTasks.Count -eq 0) {
    Write-Host "`n✅ 没有待处理的任务" -ForegroundColor Green
    exit 0
}

# 按优先级排序
$allTasks = $allTasks | Sort-Object @{
    Expression = {
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
        elseif ($sta -eq "pending") { $score += 200 }
        
        # Bug 优先于需求
        if ($typ -eq "bug") { $score += 50 }
        
        $score
    }
    Descending = $true
}

Write-Host "`n" + "=" * 60 -ForegroundColor Cyan
Write-Host "待处理任务列表（按优先级排序）" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

$allTasks | ForEach-Object -Begin { $i = 1 } -Process {
    Write-Host "`n$($i). [$($_.Type)] $($_.ID)" -ForegroundColor White
    Write-Host "   文件: $($_.File)" -ForegroundColor Gray
    Write-Host "   状态: $($_.Status)" -ForegroundColor Yellow
    Write-Host "   优先级: $($_.Priority)" -ForegroundColor Magenta
    Write-Host "   路径: $($_.Path)" -ForegroundColor DarkGray
    $i++
}

Write-Host "`n" + "=" * 60 -ForegroundColor Cyan
Write-Host "总计: $($allTasks.Count) 个待处理任务" -ForegroundColor Cyan
Write-Host "=" * 60 -ForegroundColor Cyan

# 输出最高优先级的任务
if ($allTasks.Count -gt 0) {
    $topTask = $allTasks[0]
    Write-Host "`n🎯 最高优先级任务:" -ForegroundColor Red
    Write-Host "   $($topTask.Type.ToUpper()): $($topTask.ID)" -ForegroundColor Red
    Write-Host "   优先级: $($topTask.Priority)" -ForegroundColor Red
    Write-Host "   状态: $($topTask.Status)" -ForegroundColor Red
    
    # 输出任务信息供后续处理
    Write-Output "TOP_TASK_ID=$($topTask.ID)"
    Write-Output "TOP_TASK_TYPE=$($topTask.Type)"
    Write-Output "TOP_TASK_PRIORITY=$($topTask.Priority)"
    Write-Output "TOP_TASK_STATUS=$($topTask.Status)"
    Write-Output "TOP_TASK_PATH=$($topTask.Path)"
}