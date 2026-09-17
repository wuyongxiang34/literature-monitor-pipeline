[CmdletBinding()]
param(
    [string]$Profile = "",
    [int]$LookbackDays = 0,
    [switch]$NoDelivery
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Config = Join-Path $ProjectRoot "config\settings.yaml"

if ($PSBoundParameters.ContainsKey("LookbackDays") -and $LookbackDays -lt 1) {
    throw "LookbackDays must be greater than 0 when specified."
}

function Disable-StaleLoopbackProxy {
    $DisabledVariables = [System.Collections.Generic.List[string]]::new()
    $DisabledEndpoints = [System.Collections.Generic.HashSet[string]]::new()

    foreach ($VariableName in @("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")) {
        $Value = [Environment]::GetEnvironmentVariable($VariableName, "Process")
        if ([string]::IsNullOrWhiteSpace($Value)) {
            continue
        }

        try {
            $ProxyUri = [Uri]$Value
        }
        catch {
            continue
        }

        if ($ProxyUri.Host -notin @("127.0.0.1", "localhost", "::1") -or $ProxyUri.Port -le 0) {
            continue
        }

        $Client = [System.Net.Sockets.TcpClient]::new()
        $IsListening = $false
        try {
            $ConnectTask = $Client.ConnectAsync($ProxyUri.Host, $ProxyUri.Port)
            $IsListening = $ConnectTask.Wait(300) -and $Client.Connected
        }
        catch {
            $IsListening = $false
        }
        finally {
            $Client.Dispose()
        }

        if (-not $IsListening) {
            [Environment]::SetEnvironmentVariable(
                $VariableName,
                $null,
                [EnvironmentVariableTarget]::Process
            )
            $DisabledVariables.Add($VariableName)
            [void]$DisabledEndpoints.Add("$($ProxyUri.Host):$($ProxyUri.Port)")
        }
    }

    if ($DisabledVariables.Count -gt 0) {
        $Names = $DisabledVariables -join ", "
        $Endpoints = $DisabledEndpoints -join ", "
        Write-Warning (
            "Inactive local proxy detected ($Endpoints). " +
            "Disabled for this run only: $Names. Windows proxy settings were not changed."
        )
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual environment not found. Run .\scripts\setup.ps1 first."
}

Disable-StaleLoopbackProxy

Set-Location $ProjectRoot
$Arguments = @((Join-Path $ProjectRoot "run.py"), "--config", $Config)
if (-not [string]::IsNullOrWhiteSpace($Profile)) {
    $Arguments += @("--profile", $Profile)
}
$Arguments += "run"
if ($LookbackDays -gt 0) {
    $Arguments += @("--lookback-days", $LookbackDays)
}
if ($NoDelivery) {
    $Arguments += "--no-delivery"
}

& $Python @Arguments
exit $LASTEXITCODE
