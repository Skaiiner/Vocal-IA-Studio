# Instala Vocal AI Studio en un entorno aislado (.venv). No requiere permisos de administrador.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "`n=== Vocal AI Studio: instalacion ===`n" -ForegroundColor Cyan

$python = $null
foreach ($cmd in @("py", "python")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $version = & $found.Source --version 2>&1
        if ($version -match "Python (\d+)\.(\d+)") {
            if ([int]$Matches[1] -ge 3 -and [int]$Matches[2] -ge 10) { $python = $found.Source; break }
        }
    }
}
if (-not $python) {
    Write-Host "No se encontro Python 3.10 o superior." -ForegroundColor Red
    Write-Host "Instalalo desde https://www.python.org/downloads/ y marca 'Add Python to PATH'."
    exit 1
}
Write-Host "Python encontrado: $python" -ForegroundColor Green

if (-not (Test-Path ".venv")) {
    Write-Host "Creando entorno virtual..."
    & $python -m venv .venv
}

$venvPython = ".\.venv\Scripts\python.exe"
Write-Host "Instalando dependencias (puede tardar unos minutos)..."
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -e ".[dev]" --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "Fallo la instalacion de dependencias." -ForegroundColor Red; exit 1 }

Write-Host "Comprobando la instalacion..."
& $venvPython -m pytest -q
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nAlgunos tests fallaron. La app puede funcionar igualmente; revisa logs/app.log." -ForegroundColor Yellow
} else {
    Write-Host "`nTodo correcto." -ForegroundColor Green
}

$projectRoot = (Get-Location).Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop "Vocal AI Studio.lnk"
$iconPath = Join-Path $projectRoot "src\vocal_ai_studio\assets\icon.ico"
try {
    $ws = New-Object -ComObject WScript.Shell
    $sc = $ws.CreateShortcut($shortcutPath)
    $sc.TargetPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
    $sc.Arguments = "-m vocal_ai_studio"
    $sc.WorkingDirectory = $projectRoot
    if (Test-Path $iconPath) { $sc.IconLocation = "$iconPath,0" }
    $sc.Description = "Vocal AI Studio"
    $sc.Save()
    Write-Host "Acceso directo creado en el escritorio: $shortcutPath" -ForegroundColor Green
} catch {
    Write-Host "No se pudo crear el acceso directo del escritorio: $_" -ForegroundColor Yellow
}

Write-Host "`nListo. Abre 'Vocal AI Studio' desde el escritorio, o con:  .\scripts\run.ps1`n" -ForegroundColor Cyan
