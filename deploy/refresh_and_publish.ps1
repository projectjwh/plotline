<#
  Daily refresh + publish for the link-only Plotline explorer.

  Runs the data gather, rebuilds the API-backed shell + explorer_data.json, and
  redeploys to Cloudflare Pages. Intended to run once a day from Task Scheduler,
  from this machine (residential IP — CI datacenter IPs are often blocked).

  One-time setup (see web/README.md):
    - A Cloudflare account + a Pages project named "plotline".
    - `npx wrangler login`   (authorizes this machine)
    - `npx wrangler pages secret put SITE_PASSWORD --project-name plotline`

  Register the daily task (PowerShell, one-off):
    $ps = (Get-Command powershell).Source
    $act = New-ScheduledTaskAction -Execute $ps `
      -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\deploy\refresh_and_publish.ps1`""
    $trg = New-ScheduledTaskTrigger -Daily -At 6am
    Register-ScheduledTask -TaskName "Plotline-Refresh" -Action $act -Trigger $trg `
      -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun)
#>
param(
  [int]$Enrich = 300,          # detail pages to crawl each run
  [switch]$Scrape = $true,     # also fetch fresh rankings (Playwright)
  [string]$Project = "plotline"
)
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
Write-Host "[$stamp] Plotline daily refresh starting in $repo"

# 1. Gather + process data (Bronze -> Silver -> Gold warehouse).
$pipeArgs = @("run_pipeline.py", "--enrich", "$Enrich")
if ($Scrape) { $pipeArgs += "--scrape" }
Write-Host "[1/3] python $($pipeArgs -join ' ')"
python @pipeArgs
if ($LASTEXITCODE -ne 0) { throw "pipeline failed (exit $LASTEXITCODE)" }

# 2. Rebuild the API-backed shell + explorer_data.json (covers embedded).
Write-Host "[2/3] Building API-backed explorer..."
python -m src.reports.build_explorer --mode api --covers 6000 `
  --data-url "/explorer_data.json" --out web\index.html
if ($LASTEXITCODE -ne 0) { throw "build_explorer failed (exit $LASTEXITCODE)" }

# 3. Deploy the refreshed front-end to Cloudflare Pages (auth Worker travels with it).
Write-Host "[3/3] Deploying to Cloudflare Pages (project: $Project)..."
npx --yes wrangler pages deploy web --project-name $Project --commit-dirty=true
if ($LASTEXITCODE -ne 0) { throw "wrangler deploy failed (exit $LASTEXITCODE)" }

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Done - front-end refreshed."
