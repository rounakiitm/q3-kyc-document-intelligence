# Deploy Q3 static frontend to Vercel (points at Cloud Run API).
# Usage: .\scripts\deploy_vercel.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Frontend = Join-Path $Root "frontend"
$ApiUrlFile = Join-Path $Root ".cloudrun_url"
$Api = if (Test-Path $ApiUrlFile) {
  (Get-Content $ApiUrlFile -Raw).Trim()
} else {
  "https://q3-kyc-pipeline-yp4xrztlaq-el.a.run.app"
}

Set-Content -Path (Join-Path $Frontend "config.js") -Value @"
/* Production API (Cloud Run). Leave empty for local same-origin. */
window.__KYC_API__ = "$Api";
"@

Push-Location $Frontend
try {
  npx vercel deploy --prod --yes
  npx vercel project protection disable q3-kyc-frontend --sso
} finally {
  Pop-Location
}
Write-Host "Frontend: https://q3-kyc-frontend.vercel.app"
Write-Host "API:      $Api"
