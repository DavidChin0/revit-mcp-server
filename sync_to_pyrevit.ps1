# Sync revit_mcp and tools to pyRevit Extensions folder
# Run this after editing revit_mcp/ or tools/ in the repo, before reloading pyRevit

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$extPath = "$env:APPDATA\pyRevit\Extensions\mcp-server-for-revit-python.extension"

if (-not (Test-Path $extPath)) {
    Write-Error "Extension not found: $extPath"
    exit 1
}

Write-Host "Syncing revit_mcp/ and tools/ from repo to Extension..."
Write-Host "  From: $repoRoot"
Write-Host "  To:   $extPath"

# Sync revit_mcp/
Write-Host "`n[1/2] Syncing revit_mcp/..."
try {
    Remove-Item "$extPath\revit_mcp" -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item "$repoRoot\revit_mcp" "$extPath\revit_mcp" -Recurse -Force
    Write-Host "  ✓ revit_mcp synced"
} catch {
    Write-Error "Failed to sync revit_mcp: $_"
    exit 1
}

# Sync tools/
Write-Host "[2/2] Syncing tools/..."
try {
    Remove-Item "$extPath\tools" -Recurse -Force -ErrorAction SilentlyContinue
    Copy-Item "$repoRoot\tools" "$extPath\tools" -Recurse -Force
    Write-Host "  ✓ tools synced"
} catch {
    Write-Error "Failed to sync tools: $_"
    exit 1
}

Write-Host "`n✓ Sync complete. Next step: reload pyRevit from Revit (call from execute_revit_code):"
Write-Host "    from pyrevit.loader import sessionmgr"
Write-Host "    sessionmgr.reload_pyrevit()"
