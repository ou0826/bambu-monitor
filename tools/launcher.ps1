# ============================================================
#  启动器：先开监控，再开 Bambu Studio
#  由「让拓竹启动时带上监控.bat」调用，也可以右键用 PowerShell 运行
#
#  本文件必须保存为 UTF-8 with BOM，否则中文会乱码。
# ============================================================
param([switch]$DryRun)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms | Out-Null

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Fail($msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Red
    Write-Host ""
    Write-Host "按任意键关闭..." -ForegroundColor DarkGray
    try { [void][System.Windows.Forms.MessageBox]::Show($msg, "拓竹打印监控 · 启动器") } catch {}
    [void][Console]::ReadKey($true)
    exit 1
}

# ---------- 1) 找监控程序 ----------
$monitor = Join-Path $scriptDir '拓竹打印监控.exe'
if (-not (Test-Path -LiteralPath $monitor)) {
    $hit = Get-ChildItem -LiteralPath $scriptDir -Filter '*打印监控*.exe' -ErrorAction SilentlyContinue |
           Select-Object -First 1
    if ($hit) { $monitor = $hit.FullName }
}
if (-not (Test-Path -LiteralPath $monitor)) {
    Fail "找不到「拓竹打印监控.exe」。`n请把本启动器和监控程序放在同一个文件夹里。"
}

# ---------- 2) 找 Bambu Studio ----------
$studio = $env:BAMBUMON_STUDIO          # 手动指定 / 测试用
if (-not $studio) {
    $tries = @(
        "${env:ProgramFiles}\Bambu Studio\bambu-studio.exe",
        "${env:ProgramFiles(x86)}\Bambu Studio\bambu-studio.exe",
        "$env:LOCALAPPDATA\Programs\Bambu Studio\bambu-studio.exe",
        "$env:APPDATA\BambuStudio\bambu-studio.exe"
    )
    foreach ($t in $tries) {
        if ($t -and (Test-Path -LiteralPath $t)) { $studio = $t; break }
    }
}

if (-not $studio) {
    # 注册表：卸载项里的 DisplayIcon
    $keys = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    foreach ($k in $keys) {
        $items = Get-ItemProperty -Path $k -ErrorAction SilentlyContinue |
                 Where-Object {
                     ($_.DisplayName -like '*Bambu*') -or ($_.DisplayIcon -like '*bambu-studio*')
                 }
        foreach ($it in $items) {
            $icon = "$($it.DisplayIcon)"
            if ($icon -like '*bambu-studio.exe*') {
                $cand = ($icon -replace '^"', '') -replace '",.*$', ''
                if (Test-Path -LiteralPath $cand) { $studio = $cand; break }
            }
        }
        if ($studio) { break }
    }
}

if (-not $studio) {
    # 开始菜单快捷方式
    $menus = @(
        (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
        (Join-Path $env:ProgramData 'Microsoft\Windows\Start Menu\Programs')
    )
    foreach ($m in $menus) {
        if (-not (Test-Path -LiteralPath $m)) { continue }
        $lnk = Get-ChildItem -LiteralPath $m -Recurse -Filter '*.lnk' -ErrorAction SilentlyContinue |
               Where-Object { $_.Name -like '*Bambu*' } | Select-Object -First 1
        if ($lnk) {
            try {
                $sh = New-Object -ComObject WScript.Shell
                $target = $sh.CreateShortcut($lnk.FullName).TargetPath
                if ($target -and (Test-Path -LiteralPath $target)) { $studio = $target; break }
            } catch {}
        }
    }
}

if (-not $studio) {
    Fail @"
没有自动找到 Bambu Studio。

请用记事本打开本文件夹里的 launcher.ps1，
把它最上面加一行（换成你自己的真实路径）：

    `$env:BAMBUMON_STUDIO = 'D:\你的位置\Bambu Studio\bambu-studio.exe'

或者直接手动打开 Bambu Studio 也可以，监控已经会跟着启动。
"@
}

if ($DryRun) {
    Write-Host "== 只检测，不启动 ==" -ForegroundColor Cyan
    Write-Host "监控程序: $monitor"
    Write-Host " 存在: $([bool](Test-Path -LiteralPath $monitor))"
    Write-Host "Bambu Studio: $studio"
    Write-Host " 存在: $([bool](Test-Path -LiteralPath $studio))"
    exit 0
}

# ---------- 3) 先起监控（已经在跑就不重复开） ----------
$monitorName = [System.IO.Path]::GetFileNameWithoutExtension($monitor)
$running = Get-Process -Name $monitorName -ErrorAction SilentlyContinue
if (-not $running) {
    Write-Host "启动监控：$monitor" -ForegroundColor Green
    Start-Process -FilePath $monitor -WorkingDirectory $scriptDir
    Start-Sleep -Seconds 2
} else {
    Write-Host "监控已在运行，跳过启动" -ForegroundColor DarkGray
}

# ---------- 4) 再起 Bambu Studio ----------
Write-Host "启动 Bambu Studio：$studio" -ForegroundColor Green
Start-Process -FilePath $studio
Start-Sleep -Seconds 1
exit 0
