#Requires -Version 5.1
<#
.SYNOPSIS
    Interactive release script for Starling. Automates docs/RELEASING.md.
.EXAMPLE
    .\scripts\release.ps1
    .\scripts\release.ps1 -Version 0.2.0
    .\scripts\release.ps1 -Version 0.2.0 -Message "chore(release): v0.2.0 - voice caching"
#>
param(
    [string]$Version = "",
    [string]$Message = ""
)

$ErrorActionPreference = "Stop"

if (-not $Version) {
    $Version = Read-Host "Version (e.g. 0.2.0)"
}

# Validate X.Y.Z format
if ($Version -notmatch '^\d+\.\d+\.\d+$') {
    Write-Error "Version must be X.Y.Z (no 'v' prefix). Got: '$Version'"
    exit 1
}

if (-not $Message) {
    $Message = "chore(release): v$Version"
}

$Tag = "v$Version"
$Date = Get-Date -Format "yyyy-MM-dd"

$branch = git rev-parse --abbrev-ref HEAD
if ($branch -ne "main") {
    Write-Error "Must be on main (currently on '$branch')."
    exit 1
}

if (git status --porcelain) {
    Write-Error "Working tree is not clean. Commit or stash first."
    exit 1
}

# Parse the existing "[Unreleased]: .../compare/vPREV...HEAD" link definition so the
# changelog rewrite below can derive the repo URL and previous version without either
# being hardcoded here.
$changelogPath = "CHANGELOG.md"
$changelog = Get-Content $changelogPath
$linkLine = $changelog | Where-Object { $_ -match '^\[Unreleased\]: ' } | Select-Object -First 1
if (-not $linkLine -or $linkLine -notmatch '^\[Unreleased\]: (https://\S+)/compare/v([\d.]+)\.\.\.HEAD$') {
    Write-Error "Could not find a '[Unreleased]: .../compare/vX.Y.Z...HEAD' link at the bottom of $changelogPath."
    exit 1
}
$repoUrl = $Matches[1]
$prevVersion = $Matches[2]

$headingIndex = [Array]::IndexOf($changelog, '## [Unreleased]')
if ($headingIndex -lt 0) {
    Write-Error "Could not find a '## [Unreleased]' heading in $changelogPath."
    exit 1
}

# Dry-run summary
Write-Host ""
Write-Host "Release plan:" -ForegroundColor Cyan
Write-Host "  uv sync --group dev --locked && uv run pytest -q && uv run ruff check"
Write-Host "  CHANGELOG.md: [Unreleased] -> [$Version] - $Date (fresh empty [Unreleased] above)"
Write-Host "  CHANGELOG.md: link definitions (previous release: v$prevVersion)"
Write-Host "  uv version $Version && uv lock"
Write-Host "  git commit -am `"$Message`""
Write-Host "  git tag -a $Tag -m `"$Tag`""
Write-Host "  git push origin main --follow-tags"
Write-Host ""

$confirm = Read-Host "Proceed? [y/N]"
if ($confirm -ne 'y' -and $confirm -ne 'Y') {
    Write-Host "Aborted." -ForegroundColor Yellow
    exit 0
}

Write-Host ""

# Green on main
Write-Host "Syncing and running checks..." -ForegroundColor Cyan
uv sync --group dev --locked
uv run pytest -q
uv run ruff check

# Rewrite CHANGELOG.md: dated heading + fresh Unreleased section + updated link defs
Write-Host "Updating CHANGELOG.md..." -ForegroundColor Cyan
$newHeading = @('## [Unreleased]', '', "## [$Version] - $Date")
$changelog = $changelog[0..($headingIndex - 1)] + $newHeading + $changelog[($headingIndex + 1)..($changelog.Length - 1)]
$changelog = $changelog | ForEach-Object {
    if ($_ -eq $linkLine) {
        "[Unreleased]: $repoUrl/compare/v$Version...HEAD"
        "[$Version]: $repoUrl/compare/v$prevVersion...v$Version"
    } else {
        $_
    }
}
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllLines((Join-Path (Get-Location) $changelogPath), $changelog, $utf8NoBom)

# Stamp version
Write-Host "Stamping version..." -ForegroundColor Cyan
uv version $Version
uv lock

# Commit
Write-Host "Committing..." -ForegroundColor Cyan
git commit -am $Message

# Tag
Write-Host "Tagging $Tag..." -ForegroundColor Cyan
git tag -a $Tag -m $Tag

# Push commits + tag together
Write-Host "Pushing..." -ForegroundColor Cyan
git push origin main --follow-tags

Write-Host ""
Write-Host "Released $Tag. CI will build the sdist/wheel and attach them to a GitHub Release." -ForegroundColor Green
