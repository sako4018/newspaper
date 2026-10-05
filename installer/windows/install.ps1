# Стъпките на инсталирането за Windows. Вика ги setup.iss (Inno Setup) една по една:
#   install.ps1 -Step python     намира Python 3.9-3.12; ако няма, го инсталира (winget или python.org)
#   install.ps1 -Step venv       прави .venv и инсталира пакетите
#   install.ps1 -Step settings   записва settings.json в профила (lite\profile.yaml)
#   install.ps1 -Step schedule   задача в Task Scheduler в часа от профила
# Всичко се пише в install.log в папката на програмата. Безопасно е да се пусне пак.
param([Parameter(Mandatory = $true)][string]$Step)

# Не "Stop": в Windows PowerShell 5.1 всеки ред в stderr на външна програма (напр. предупреждение
# на pip) тогава става грешка. Грешките се проверяват по кода на изход.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # папката на програмата
Set-Location $Root
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Log = Join-Path $Root "install.log"
$PythonFile = Join-Path $Root "python-path.txt"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$env:PYTHONIOENCODING = "utf-8"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest е много по-бърз без лентата

function Log($text) {
    Add-Content -Path $Log -Value ("{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Step, $text) -Encoding UTF8
}

# Пуска програма, пише изхода ѝ в лога и връща кода.
function Run($exe, [string[]]$arguments) {
    Log ("> " + $exe + " " + ($arguments -join " "))
    $out = & $exe @arguments 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $out) { Log ("  " + $line) }
    return $code
}

# Python 3.9-3.12 (пакетите за превод още нямат готови версии за 3.13+)
function Test-Python($exe) {
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    if ($exe -like "*\WindowsApps\*") { return $false }   # това е само връзка към Microsoft Store
    & $exe -c "import sys; sys.exit(0 if (3, 9) <= sys.version_info[:2] <= (3, 12) else 1)" 2>$null
    return $LASTEXITCODE -eq 0
}

function Find-Python {
    $candidates = @()
    foreach ($v in "3.12", "3.11", "3.10", "3.9") {
        $short = $v -replace "\.", ""
        $candidates += Join-Path $env:LOCALAPPDATA "Programs\Python\Python$short\python.exe"
        $candidates += Join-Path $env:ProgramFiles "Python$short\python.exe"
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in "3.12", "3.11", "3.10", "3.9") {
            $p = & py "-$v" -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $p) { $candidates += $p.Trim() }
        }
    }
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) { $candidates += $onPath.Source }
    foreach ($c in $candidates) {
        if (Test-Python $c) { return $c }
    }
    return $null
}

function Install-Python {
    $target = Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe"
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Log "Инсталирам Python 3.11 с winget..."
        Run "winget" @("install", "--exact", "--id", "Python.Python.3.11", "--scope", "user", "--silent",
                       "--accept-package-agreements", "--accept-source-agreements") | Out-Null
        if (Test-Python $target) { return $target }
        $found = Find-Python
        if ($found) { return $found }
        Log "winget не успя, тегля от python.org"
    }
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq "ARM64") { "arm64" } else { "amd64" }
    $url = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-$arch.exe"
    $file = Join-Path $env:TEMP "python-3.11.9-$arch.exe"
    Log "Тегля $url"
    Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing -ErrorAction Stop
    $code = Run $file @("/quiet", "InstallAllUsers=0", "PrependPath=1", "Include_launcher=1", "Include_test=0")
    Remove-Item $file -ErrorAction SilentlyContinue
    if ($code -ne 0) { throw "Инсталаторът на Python върна код $code." }
    if (Test-Python $target) { return $target }
    throw "Python е инсталиран, но не го намирам."
}

try {
    Log "начало"
    switch ($Step) {
        "python" {
            $python = Find-Python
            if ($python) { Log "намерен: $python" } else { $python = Install-Python; Log "инсталиран: $python" }
            Set-Content -Path $PythonFile -Value $python -Encoding UTF8
        }
        "venv" {
            if (-not (Test-Path $PythonFile)) { throw "Няма python-path.txt (стъпката python не е минала)." }
            $python = (Get-Content $PythonFile -Encoding UTF8 | Select-Object -First 1).Trim()
            if (-not (Test-Path $VenvPython)) {
                if ((Run $python @("-m", "venv", (Join-Path $Root ".venv"))) -ne 0) { throw "Не успях да направя .venv." }
            }
            & $VenvPython -c "import yaml, feedparser, docx, argostranslate" 2>$null
            if ($LASTEXITCODE -ne 0) {
                Run $VenvPython @("-m", "pip", "install", "-q", "--upgrade", "pip") | Out-Null
                $code = Run $VenvPython @("-m", "pip", "install", "--progress-bar", "off",
                    "-r", (Join-Path $Root "claude\requirements.txt"), "-r", (Join-Path $Root "lite\requirements.txt"))
                if ($code -ne 0) { throw "Инсталирането на пакетите не успя. Провери интернет връзката." }
            } else {
                Log "пакетите вече са инсталирани"
            }
        }
        "settings" {
            $code = Run $VenvPython @((Join-Path $Root "app\apply_settings.py"), (Join-Path $Root "settings.json"))
            if ($code -ne 0) { throw "Не успях да запиша профила." }
        }
        "schedule" {
            $code = Run $VenvPython @("-c", "import sys; sys.path.insert(0, 'app'); import platform_support; sys.exit(0 if platform_support.schedule_set(True) else 1)")
            if ($code -ne 0) { throw "Не успях да включа задачата в Task Scheduler." }
        }
        default { throw "Непозната стъпка: $Step" }
    }
    Log "готово"
    exit 0
} catch {
    Log ("ГРЕШКА: " + $_.Exception.Message)
    exit 1
}
