$ErrorActionPreference = "Continue"

$ProjectRoot = $PSScriptRoot
if ($ProjectRoot -eq "") {
    $ProjectRoot = (Get-Location).Path
}
Set-Location -Path $ProjectRoot

Write-Host "==========================================="
Write-Host "EchoSense - Demo Mode (Nainital Region)"
Write-Host "==========================================="

Write-Host "`n[0/4] Setting up Python environment and installing dependencies..."

if (-not (Test-Path "venv\Scripts\Activate.ps1")) {
    Write-Host "      Cleaning and creating virtual environment..."
    if (Test-Path "venv") { Remove-Item -Recurse -Force venv }
    py -m venv venv
}

$venvPython = ".\venv\Scripts\python.exe"
$venvPip = ".\venv\Scripts\pip.exe"

& $venvPython -m pip install --quiet --upgrade pip setuptools wheel
& $venvPython -m pip install --quiet -r requirements.txt
try {
    & $venvPython -m pip install --quiet birdnetlib webrtcvad
} catch {
    Write-Host "      [WARNING] birdnetlib/webrtcvad install failed (demo mode will work without native vad)"
}

Write-Host "      [OK] Dependencies ready"

Write-Host "`n[1/4] Resetting database..."
if (Test-Path "data\echosense.db") { Remove-Item -Force "data\echosense.db" }
if (-not (Test-Path "data")) { New-Item -ItemType Directory "data" | Out-Null }
Write-Host "      [OK] Fresh database ready"

Write-Host "`n[1.5/4] Building React Dashboard..."
Set-Location -Path "frontend"
npm install --silent
npm run build --silent
Set-Location -Path $ProjectRoot
Write-Host "      [OK] Dashboard built"

Write-Host "`n[2/4] Starting FastAPI backend..."
Start-Process -FilePath $venvPython -ArgumentList "-m","uvicorn","backend.main:app","--port","8000"

Start-Sleep -Seconds 5
Write-Host "      [OK] Backend running  ->  http://127.0.0.1:8000"

Write-Host "      Registering 3 field nodes..."
$headers = @{ "Content-Type" = "application/json" }

$b1 = @{id="E-NK";site_name="Nainital Lake Node";lat=29.3919;lng=79.4542;battery_pct=95} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/devices" -Method POST -Headers $headers -Body $b1 | Out-Null
Write-Host "        [OK] E-NK  Nainital Lake Node"

$b2 = @{id="E-PG";site_name="Pangot Forest Node";lat=29.4351;lng=79.3951;battery_pct=88} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/devices" -Method POST -Headers $headers -Body $b2 | Out-Null
Write-Host "        [OK] E-PG  Pangot Forest Node"

$b3 = @{id="E-KB";site_name="Kilbury Reserve Node";lat=29.3726;lng=79.4231;battery_pct=92} | ConvertTo-Json -Compress
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/devices" -Method POST -Headers $headers -Body $b3 | Out-Null
Write-Host "        [OK] E-KB  Kilbury Reserve Node"

Write-Host "`n[3/4] Starting 3 edge simulators (Nainital region)..."
Set-Location -Path "edge"
$simulatorPython = "..\venv\Scripts\python.exe"

Start-Process -FilePath $simulatorPython -ArgumentList "simulator.py","--demo","--low-bandwidth","--watch","--sleep","5","--device-id","E-NK","--lat","29.3919","--lng","79.4542"
Write-Host "      [OK] E-NK  running"
Start-Sleep -Seconds 1

Start-Process -FilePath $simulatorPython -ArgumentList "simulator.py","--demo","--low-bandwidth","--watch","--sleep","5","--device-id","E-PG","--lat","29.4351","--lng","79.3951"
Write-Host "      [OK] E-PG  running"
Start-Sleep -Seconds 1

Start-Process -FilePath $simulatorPython -ArgumentList "simulator.py","--demo","--low-bandwidth","--watch","--sleep","5","--device-id","E-KB","--lat","29.3726","--lng","79.4231"
Write-Host "      [OK] E-KB  running"

Write-Host "`nEchoSense is fully running!"
Write-Host "    Dashboard  ->  http://127.0.0.1:8000/dashboard/"
Write-Host "`nTo close the processes, you can close the newly opened console windows."
