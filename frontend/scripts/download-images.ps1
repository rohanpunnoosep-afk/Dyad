$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$imageDir = Join-Path $projectRoot 'public/images'
New-Item -ItemType Directory -Force -Path $imageDir | Out-Null
$sources = Get-Content -Raw (Join-Path $PSScriptRoot 'image-sources.json') | ConvertFrom-Json
foreach ($entry in $sources.PSObject.Properties) {
    $imagePath = Join-Path $imageDir ($entry.Name + '.jpg')
    try {
        Invoke-WebRequest -Uri $entry.Value -OutFile $imagePath -TimeoutSec 25
        Write-Output ($entry.Name + ': downloaded')
    } catch {
        Write-Output ($entry.Name + ': FAILED ' + $_.Exception.Message)
    }
}
