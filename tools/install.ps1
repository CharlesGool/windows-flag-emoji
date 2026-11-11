$ErrorActionPreference = 'Stop'
$Root     = Split-Path $PSScriptRoot -Parent
$Out      = Join-Path $Root 'output\seguiemj_flags.ttf'
$Backup   = Join-Path $Root 'backup'
$WinFont  = Join-Path $env:WINDIR 'Fonts'
$FontsKey = 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'
$RegName  = 'Segoe UI Emoji (TrueType)'
$NewFile  = 'seguiemj_flags.ttf'

$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '需要管理员权限:请右键 install.bat -> 以管理员身份运行' -ForegroundColor Red; exit 1
}

# 1. 检查 Python
$py = $null
foreach ($c in 'python', 'py') {
    try { & $c -c "import sys; assert sys.version_info >= (3, 8)" 2>$null; if ($LASTEXITCODE -eq 0) { $py = $c; break } } catch {}
}
if (-not $py) {
    Write-Host '没有找到 Python 3.8 以上版本。请先安装 Python:https://www.python.org/downloads/ (安装时勾选 Add Python to PATH)' -ForegroundColor Red
    exit 1
}

# 2. 生成字体(从系统自带的 Segoe UI Emoji 生成,本工具从不覆盖原文件)
Write-Host '安装 fonttools ...'
& $py -m pip install --quiet --disable-pip-version-check fonttools
if ($LASTEXITCODE -ne 0) { Write-Host 'pip 安装 fonttools 失败' -ForegroundColor Red; exit 1 }
Write-Host '生成带国旗的 Segoe UI Emoji ...'
$env:PYTHONIOENCODING = 'utf-8'
& $py (Join-Path $PSScriptRoot 'build_emoji.py') (Join-Path $WinFont 'seguiemj.ttf') (Join-Path $Root 'src\Twemoji.Mozilla.ttf') $Out
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Out)) { Write-Host '生成失败' -ForegroundColor Red; exit 1 }

# 3. 备份注册表(只在第一次)
New-Item -ItemType Directory -Force $Backup | Out-Null
$regBak = Join-Path $Backup 'SegoeUIEmoji_original.txt'
if (-not (Test-Path $regBak)) {
    $cur = (Get-ItemProperty $FontsKey -Name $RegName -ErrorAction SilentlyContinue).$RegName
    if (-not $cur -or $cur -eq $NewFile) { $cur = 'seguiemj.ttf' }
    Set-Content $regBak $cur -Encoding ASCII
    Write-Host "已备份注册表原值: $cur"
}

# 4. 复制到系统字体目录:文件被占用时,安排重启时替换
Add-Type -Namespace W -Name K -MemberDefinition '[DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)] public static extern bool MoveFileEx(string a, string b, int f);'
$dst = Join-Path $WinFont $NewFile
if ((Test-Path $dst) -and ((Get-FileHash $Out).Hash -eq (Get-FileHash $dst).Hash)) {
    Write-Host "$NewFile 已是最新"
} else {
    try { Copy-Item $Out $dst -Force; Write-Host "已复制 $NewFile" }
    catch {
        $staged = "$dst.new"
        Copy-Item $Out $staged -Force
        if (-not [W.K]::MoveFileEx($staged, $dst, 5)) { Write-Host '安排重启替换失败' -ForegroundColor Red; exit 1 }
        Write-Host "$NewFile 正在使用,已安排重启时替换"
    }
}

# 5. 注册表指向新文件
Set-ItemProperty $FontsKey -Name $RegName -Value $NewFile
Write-Host "注册表: $RegName = $NewFile"

# 6. 清除字体缓存
try {
    Stop-Service FontCache -Force -ErrorAction Stop
    Get-ChildItem "$env:WINDIR\ServiceProfiles\LocalService\AppData\Local\FontCache" -Filter '*FontCache*' -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
    Remove-Item "$env:WINDIR\System32\FNTCACHE.DAT" -Force -ErrorAction SilentlyContinue
    Start-Service FontCache
    Write-Host '字体缓存已清除'
} catch {}

Write-Host ''
Write-Host '安装完成,重启电脑后生效。要恢复原样请运行 restore.bat' -ForegroundColor Green
