# 티모의 버섯농장 서버 다시 켜기
# 지금 돌고 있는 이 서버(python app.py)만 찾아서 끄고, 같은 포트로 새로 켭니다.
# 다른 파이썬 프로그램은 건드리지 않도록, 그 포트에서 이 서버 화면이 나오는지 확인한 뒤에만 끕니다.
param([int]$Port = 0)   # 포트를 직접 정하려면: restart.ps1 -Port 8088
$here = $PSScriptRoot
Set-Location $here
$port = $null
$exe = "python"

$cands = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
  Where-Object { $_.CommandLine -match 'app\.py' -or $_.CommandLine -match 'tracker\.web\.server' }

foreach ($p in $cands) {
  $ls = Get-NetTCPConnection -OwningProcess $p.ProcessId -State Listen -ErrorAction SilentlyContinue
  $mine = $false
  foreach ($l in $ls) {
    try {
      $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 ("http://127.0.0.1:" + $l.LocalPort + "/")
      if ($r.Content -match '/api/refresh' -or $r.Content -match '/static/common\.js') { $mine = $true; if (-not $port) { $port = $l.LocalPort } }
    } catch {
      try {
        $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 ("http://127.0.0.1:" + $l.LocalPort + "/lck")
        if ($r.Content -match '/static/common\.js') { $mine = $true; if (-not $port) { $port = $l.LocalPort } }
      } catch {}
    }
  }
  if ($mine) {
    if ($p.ExecutablePath) { $exe = $p.ExecutablePath }
    # 자동 재시작 버전이면 부모('감독' app.py)부터 끔. 안 그러면 서버를 다시 띄움
    $parent = $cands | Where-Object { $_.ProcessId -eq $p.ParentProcessId }
    if ($parent) {
      Write-Host ("재시작 감독을 끕니다 (PID " + $parent.ProcessId + ")")
      Stop-Process -Id $parent.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host ("예전 서버를 끕니다 (PID " + $p.ProcessId + ")")
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
  }
}

# Tailscale이 사이트를 넘겨주는 포트(serve/funnel 설정)를 찾아봄 → 있으면 그 포트로 켬
$tsPort = $null
try {
  $ts = (& tailscale serve status --json 2>$null) | Out-String
  $m = [regex]::Match($ts, '"Proxy"\s*:\s*"https?://(?:127\.0\.0\.1|localhost|\[::1\]):(\d+)')
  if ($m.Success) { $tsPort = [int]$m.Groups[1].Value }
} catch {}
if ($tsPort) { Write-Host ("Tailscale이 넘겨주는 포트: " + $tsPort) } else { Write-Host "Tailscale 설정에서 포트를 못 찾았어요" }

if ($Port -gt 0) { $port = $Port }
elseif ($tsPort) { $port = $tsPort }
elseif (-not $port) {
  if ($env:PORT) { $port = $env:PORT } else { $port = 8080 }
  Write-Host ("돌고 있는 서버를 못 찾아서 포트 " + $port + "로 켭니다")
}
Start-Sleep -Seconds 2
$env:PORT = "$port"
$env:DB_PATH = Join-Path $here "data\stove.db"
Write-Host ("새 서버를 켭니다: 포트 " + $port + ", DB " + $env:DB_PATH)
Write-Host "이제 코드가 바뀌면 알아서 다시 켜집니다. 끌 때는 이 창을 닫으면 됩니다."
& $exe app.py
