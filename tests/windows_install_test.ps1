# Проверка на инсталатора за Windows от .exe до готов брой, както при човек:
#   pwsh tests/windows_install_test.ps1 -Exe <Sutreshen-Vestnik-Setup.exe> -Version <lite|claude>
# 1. тихо инсталиране; файлове, профил, задача в Task Scheduler, иконки;
# 2. брой през самата задача (Start-ScheduledTask), иначе като нея (run.py); копие в Desktop\Сутрешен вестник;
# 3. „Направи брой сега“ (run.py --force) дава втори отделен файл;
# 4. повторно пускане на {app}\Setup.exe (иконката за настройки) пази избора;
# 5. деинсталиране без следи.
# За claude слага фалшив claude.cmd (tests/fake_claude.py), защото в GitHub няма вход в Claude.
# Само за машини за проверка. Грешките излизат и като annotations (::error::), които се четат без вход.
param([Parameter(Mandatory)] [string] $Exe, [Parameter(Mandatory)] [ValidateSet("lite", "claude")] [string] $Version)
$ErrorActionPreference = "Stop"
$Tag = "[windows $Version]"
trap { Write-Output "::error::$Tag $($_.Exception.Message)"; exit 1 }
function Note($text) { Write-Output "::notice::$Tag $text" }

$App = Join-Path $env:LOCALAPPDATA "Сутрешен вестник"
$Desk = [Environment]::GetFolderPath("Desktop")
$Archive = Join-Path $Desk "Сутрешен вестник"
$Start = Join-Path "$env:APPDATA\Microsoft\Windows\Start Menu\Programs" "Сутрешен вестник"
$Python = Join-Path $App ".venv\Scripts\python.exe"
$Exe = (Resolve-Path $Exe).Path
$ver = (Get-Item $Exe).VersionInfo
Note ("exe: {0:N1} MB, версия {1}" -f ((Get-Item $Exe).Length / 1MB), $ver.ProductVersion)

# ---- фалшив claude (npm мястото е в PATH на човека; тук го добавяме ние) ----
if ($Version -eq "claude") {
    $npm = Join-Path $env:APPDATA "npm"
    New-Item -ItemType Directory -Force $npm | Out-Null
    $py = (Get-Command python).Source
    Set-Content (Join-Path $npm "claude.cmd") ('@"' + $py + '" "' + (Join-Path $PSScriptRoot "fake_claude.py") + '" %*') -Encoding ASCII
    $env:PATH = "$npm;$env:PATH"
}

# ---- 1. инсталиране ----
$t0 = Get-Date
$p = Start-Process $Exe -Wait -PassThru -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/LOG=setup.log',
    "/version=$Version", '/topics=bg,world', '/city=Пловдив', '/time=06:30', '/print=0'
if ($p.ExitCode -ne 0) {
    Get-Content (Join-Path $App "install.log") -Encoding UTF8 -ErrorAction SilentlyContinue
    Get-Content setup.log -Tail 40
    throw "Setup върна код $($p.ExitCode)"
}
foreach ($f in ".venv\Scripts\python.exe", ".venv\Scripts\pythonw.exe", "Setup.exe", "lite\profile.yaml", "claude\run.py", "unins000.exe") {
    if (-not (Test-Path (Join-Path $App $f))) { throw "Липсва $f" }
}
$prof = Get-Content (Join-Path $App "lite\profile.yaml") -Encoding UTF8 -Raw
foreach ($want in "version: $Version", "- bg", "- world", "06:30", "Пловдив", "print: false") {
    if (-not $prof.Contains($want)) { throw "Профилът няма '$want'" }
}
$task = Get-ScheduledTask -TaskName "Sutreshen Vestnik"
if (([datetime]$task.Triggers[0].StartBoundary).ToString("HH:mm") -ne "06:30") { throw "Задачата не е в 06:30" }
foreach ($l in (Join-Path $Desk "Сутрешен вестник – настройки.lnk"), (Join-Path $Start "Сутрешен вестник – настройки.lnk"),
               (Join-Path $Start "Направи брой сега.lnk"), (Join-Path $Start "Деинсталирай.lnk")) {
    if (-not (Test-Path $l)) { throw "Липсва $l" }
}
Note ("инсталирано за {0:N0} s: профил, задача 06:30, иконка на Desktop, 3 неща в Start" -f ((Get-Date) - $t0).TotalSeconds)

# ---- 2. брой през задачата ----
$result = if ($Version -eq "claude") { Join-Path $App "claude\latest.docx" } else { Join-Path $App "lite\output\latest.docx" }
$before = Get-Date
Start-ScheduledTask -TaskName "Sutreshen Vestnik"
$fromTask = $false
foreach ($i in 1..120) {   # до 20 минути
    if ((Test-Path $result) -and (Get-Item $result).LastWriteTime -ge $before) { $fromTask = $true; break }
    Start-Sleep 10
}
if ($fromTask) {
    Note "задачата в Task Scheduler направи брой: $((Get-Item $result).Length) байта"
} else {
    Write-Output "::warning::$Tag задачата не направи брой за 20 минути (LastTaskResult $((Get-ScheduledTaskInfo -TaskName 'Sutreshen Vestnik').LastTaskResult)); пускам run.py като нея"
    & $Python (Join-Path $App "claude\run.py")
    if ($LASTEXITCODE -ne 0) {
        Get-Content (Join-Path $App "claude\logs\*.log") -Encoding UTF8 -Tail 20 -ErrorAction SilentlyContinue
        throw "run.py върна код $LASTEXITCODE"
    }
}
Start-Sleep 3

# ---- 3. „Направи брой сега“ ----
& $Python (Join-Path $App "claude\run.py") --force
if ($LASTEXITCODE -ne 0) { throw "run.py --force върна код $LASTEXITCODE" }
$files = @(Get-ChildItem $Archive -Filter *.docx -ErrorAction SilentlyContinue |
           Where-Object { $_.Name -match '^\d\d\.\d\d\.\d{4} \d\d\.\d\d( \(\d+\))?\.docx$' })
if ($files.Count -lt 2) { throw "В Desktop\Сутрешен вестник има $($files.Count) броя вместо 2" }
Note ("Desktop\Сутрешен вестник: " + (($files | ForEach-Object { $_.Name }) -join ' | '))

# ---- 4. смяна на настройките (иконката пуска {app}\Setup.exe) ----
$p = Start-Process (Join-Path $App "Setup.exe") -Wait -PassThru -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/LOG=change.log'
if ($p.ExitCode -ne 0) { Get-Content change.log -Tail 40; throw "Повторният Setup.exe върна код $($p.ExitCode)" }
$prof = Get-Content (Join-Path $App "lite\profile.yaml") -Encoding UTF8 -Raw
foreach ($want in "version: $Version", "- bg", "- world", "06:30", "Пловдив") {
    if (-not $prof.Contains($want)) { throw "След повторно пускане профилът няма '$want'" }
}
Note "повторното пускане запази избора"

# ---- 5. деинсталиране ----
$p = Start-Process (Join-Path $App "unins000.exe") -Wait -PassThru -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
Start-Sleep 5
if (Get-ScheduledTask -TaskName "Sutreshen Vestnik" -ErrorAction SilentlyContinue) { throw "Задачата остана" }
if (Test-Path (Join-Path $App ".venv")) { throw "Папката на програмата остана" }
if (Test-Path (Join-Path $Desk "Сутрешен вестник – настройки.lnk")) { throw "Иконката на Desktop остана" }
if (Test-Path $Start) { throw "Папката в Start остана" }
if (-not (Test-Path $Archive)) { throw "Папката с броевете трябва да остане" }
Note "деинсталирано; папката с броевете остана"
Remove-Item -Recurse -Force $Archive
if ($Version -eq "claude") { Remove-Item (Join-Path $env:APPDATA "npm\claude.cmd") }
Write-Output "$Tag Всичко мина."
