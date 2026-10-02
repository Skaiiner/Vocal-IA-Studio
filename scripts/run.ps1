# Abre Vocal AI Studio.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Test-Path ".\.venv\Scripts\pythonw.exe")) {
    Write-Host "Falta el entorno virtual. Ejecuta primero:  .\scripts\install.ps1" -ForegroundColor Yellow
    exit 1
}

# pythonw abre la app sin ventana de consola. Usa python.exe si quieres ver los mensajes.
Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList "-m", "vocal_ai_studio"
Write-Host "Vocal AI Studio se esta abriendo. Si algo falla, mira logs\app.log" -ForegroundColor Cyan
