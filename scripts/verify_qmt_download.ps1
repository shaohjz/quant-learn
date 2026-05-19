#!/usr/bin/env pwsh
<#
verify_qmt_download.ps1 — QMT 客户端下载文件完整性校验

用法：
  .\verify_qmt_download.ps1 -FilePath "D:\Downloads\gjzqqmt_ceshi.rar"

会输出：
  - 文件大小
  - SHA-256 哈希
  - SHA-1 哈希
  - MD5 哈希（兼容老的校验源）
  - 数字签名状态（如果是 exe/dll，rar 没用）

用法建议：
  1. 跑这个脚本
  2. 把输出贴到企微给国金 QMT 客服核对哈希
  3. 客服确认匹配再解压
#>

param(
  [Parameter(Mandatory=$true)]
  [string]$FilePath
)

if (!(Test-Path $FilePath)) {
  Write-Host "❌ 文件不存在: $FilePath" -ForegroundColor Red
  exit 1
}

$file = Get-Item $FilePath
Write-Host "`n=== QMT 下载文件校验 ===" -ForegroundColor Cyan
Write-Host "文件路径 : $($file.FullName)"
Write-Host "文件大小 : $([math]::Round($file.Length / 1MB, 2)) MB ($($file.Length) bytes)"
Write-Host "修改时间 : $($file.LastWriteTime)"
Write-Host ""

Write-Host "=== 哈希值（贴给客服核对）===" -ForegroundColor Yellow
$sha256 = (Get-FileHash -Path $FilePath -Algorithm SHA256).Hash
$sha1   = (Get-FileHash -Path $FilePath -Algorithm SHA1).Hash
$md5    = (Get-FileHash -Path $FilePath -Algorithm MD5).Hash

Write-Host "SHA-256 : $sha256"
Write-Host "SHA-1   : $sha1"
Write-Host "MD5     : $md5"
Write-Host ""

# 风险提示
Write-Host "=== ⚠️ 安全检查清单 ===" -ForegroundColor Magenta
Write-Host "[ ] 下载链接来自国金证券官方/客服直发（非论坛/网盘转发）"
Write-Host "[ ] 已向客服核对上述至少一种哈希值"
Write-Host "[ ] 解压后 .exe 文件右键 > 属性 > 数字签名 显示「国金证券」或「迅投」"
Write-Host "[ ] 安装路径不要选 C:\Program Files（权限问题），建议 D:\国金QMT"
Write-Host "[ ] 安装完先用测试账号 90072426 登录，第一时间改密码"
Write-Host ""
Write-Host "✅ 校验完成。哈希值核对通过后，再双击运行安装包。" -ForegroundColor Green
