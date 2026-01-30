# Generate vercel.json with cron secret
# This script helps generate vercel.json with your actual CRON_SECRET

param(
    [string]$CronSecret = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Generate Vercel Cron Configuration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if (-not $CronSecret) {
    $CronSecret = Read-Host "Enter your CRON_SECRET"
}

if (-not $CronSecret -or $CronSecret.Trim().Length -eq 0) {
    Write-Host "[ERROR] CRON_SECRET is required" -ForegroundColor Red
    exit 1
}

$vercelJson = @{
    crons = @(
        @{
            path = "/api/jobs/weekly-summary?cron=$CronSecret"
            schedule = "0 14 * * 3"
        },
        @{
            path = "/api/jobs/wednesday-payouts?cron=$CronSecret"
            schedule = "0 14 * * 3"
        },
        @{
            path = "/api/jobs/annual-receipts?cron=$CronSecret"
            schedule = "0 14 15 1 *"
        }
    )
} | ConvertTo-Json -Depth 10

$vercelJson | Out-File -FilePath "vercel.json" -Encoding UTF8

Write-Host "[OK] Generated vercel.json with cron secret" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. Review vercel.json" -ForegroundColor White
Write-Host "2. Commit and push to trigger deployment" -ForegroundColor White
Write-Host "3. Verify cron jobs in Vercel Dashboard -> Settings -> Cron Jobs" -ForegroundColor White
Write-Host ""
Write-Host "Security Note:" -ForegroundColor Yellow
Write-Host "  The cron secret is now in vercel.json. Keep your repository private." -ForegroundColor Yellow
Write-Host ""
