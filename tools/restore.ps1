$ErrorActionPreference = 'Stop'
$Root     = Split-Path $PSScriptRoot -Parent
$WinFont  = Join-Path $env:WINDIR 'Fonts'
$FontsKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
$RegName  = 'Segoe UI Emoji (TrueType)'
$NewFile  = 'seguiemj_flags.ttf'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '需要管理员权限:请右键 restore.bat -> 以管理员身份运行' -ForegroundColor Red; exit 1
}

$orig = 'seguiemj.ttf'
$regBak = Join-Path $Root 'backup\SegoeUIEmoji_original.txt'
if (Test-Path $regBak) { $v = (Get-Content $regBak -TotalCount 1).Trim(); if ($v) { $orig = $v } }
if (-not (Test-Path (Join-Path $WinFont $orig))) {
    Write-Host "找不到系统原版 $orig,未做修改" -ForegroundColor Red; exit 1
}
Set-ItemProperty $FontsKey -Name $RegName -Value $orig
Write-Host "注册表: $RegName = $orig"

Add-Type -Namespace W -Name K -MemberDefinition '[DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] public static extern bool MoveFileEx(string a, string b, int f);'
$f = Join-Path $WinFont $NewFile
if (Test-Path $f) {
    try { Remove-Item $f -Force; Write-Host "已删除 $NewFile" }
    catch { [void][W.K]::MoveFileEx($f, $null, 4); Write-Host "$NewFile 正在使用,重启后自动删除" }
}

try {
    Stop-Service FontCache -Force -ErrorAction Stop
    Get-ChildItem "$env:WINDIR\ServiceProfiles\LocalService\AppData\Local\FontCache" -Filter '*FontCache*' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item "$env:WINDIR\System32\FNTCACHE.DAT" -Force -ErrorAction SilentlyContinue
    Start-Service FontCache
} catch {}

Write-Host ''
Write-Host '已还原,重启电脑后生效。' -ForegroundColor Green
