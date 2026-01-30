# Update .env.local with Webhook Secret

param(
    [Parameter(Mandatory=$true)]
    [string]$Secret
)

$envFile = "C:\Users\The Yoda Trader\easygiveqr-web\.env.local"

Write-Host "Updating .env.local with webhook secret..." -ForegroundColor Cyan

if (-not (Test-Path $envFile)) {
    Write-Host "ERROR: .env.local not found at $envFile" -ForegroundColor Red
    exit 1
}

# Read current content
$content = Get-Content $envFile
$updated = $false
$newContent = @()

foreach ($line in $content) {
    if ($line -match "^STRIPE_WEBHOOK_SECRET=") {
        $newContent += "STRIPE_WEBHOOK_SECRET=$Secret"
        $updated = $true
    } else {
        $newContent += $line
    }
}

# Add if not found
if (-not $updated) {
    $newContent += "STRIPE_WEBHOOK_SECRET=$Secret"
}

# Write back
$newContent | Set-Content $envFile

Write-Host "[OK] Updated .env.local with STRIPE_WEBHOOK_SECRET" -ForegroundColor Green
Write-Host ""
Write-Host "Next step: Restart your Next.js dev server (npm run dev)" -ForegroundColor Yellow
