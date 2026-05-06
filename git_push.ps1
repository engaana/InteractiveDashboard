# ============================================================
# git_push.ps1 — Auto-push CarolFloodOptimization to GitHub
# Run this script whenever you want to update your repository.
# ============================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Carol Flood Optimization — Git Push   " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Move to project directory
$projectPath = $PSScriptRoot
Set-Location $projectPath

# Show current status
Write-Host "📋 Changed files:" -ForegroundColor Yellow
git status --short

Write-Host ""

# Ask for a commit message (or use default)
$defaultMsg = "update: dashboard and optimization results $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
$commitMsg = Read-Host "✏️  Commit message (press Enter for default)"
if ([string]::IsNullOrWhiteSpace($commitMsg)) {
    $commitMsg = $defaultMsg
}

Write-Host ""

# Stage all changes
Write-Host "📦 Staging all changes..." -ForegroundColor Yellow
git add .

# Commit
Write-Host "💾 Creating commit..." -ForegroundColor Yellow
git commit -m "$commitMsg"

# Push
Write-Host "🚀 Pushing to GitHub..." -ForegroundColor Yellow
git push

Write-Host ""
Write-Host "✅ Done! Your repository is up to date." -ForegroundColor Green
Write-Host "🔗 https://github.com/engaana/CarolFloodOptimization" -ForegroundColor Cyan
Write-Host ""

Read-Host "Press Enter to close"
