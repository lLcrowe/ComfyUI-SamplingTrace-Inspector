param(
    [Parameter(Mandatory = $true)]
    [string]$ComfyRoot,
    [string]$OutputDir = "",
    [string]$PreviousJson = ""
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path (Split-Path -Parent $ScriptDir) "docs"
}

$Args = @(
    (Join-Path $ScriptDir "scan_custom_nodes.py"),
    "--comfy-root", $ComfyRoot,
    "--output-dir", $OutputDir
)
if (-not [string]::IsNullOrWhiteSpace($PreviousJson)) {
    $Args += @("--previous-json", $PreviousJson)
}

& python @Args
exit $LASTEXITCODE
