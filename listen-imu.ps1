# Listen-IMU-Archive.ps1
$port = 3333
$endpoint = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Parse("0.0.0.0"), $port)
$udpClient = New-Object System.Net.Sockets.UdpClient
$udpClient.Client.Bind($endpoint)

# Create a clean directory for your ML vectors
$outDir = ".\training_data"
if (!(Test-Path $outDir)) { New-Item -ItemType Directory -Force -Path $outDir | Out-Null }

Write-Host "Listening universally for Core2 IMU telemetry on UDP port $port..." -ForegroundColor Green
Write-Host "Archiving vectors to $outDir..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor Gray

try {
    while ($true) {
        $content = $udpClient.Receive([ref]$endpoint)
        $payload = [System.Text.Encoding]::UTF8.GetString($content)
        
        try {
            # Parse the JSON to inspect the tag
            $json = $payload | ConvertFrom-Json
            $tag = $json.tag
            
            # Route the raw payload to the correct bin
            $fileName = switch ($tag) {
                1 { "class_1_rattle.jsonl" }
                2 { "class_2_open.jsonl" }
                default { "class_0_idle.jsonl" }
            }
            
            $filePath = Join-Path $outDir $fileName
            Add-Content -Path $filePath -Value $payload
            
            # Provide clean, color-coded console feedback
            if ($tag -eq 1) { Write-Host "[RATTLE] $payload" -ForegroundColor Yellow }
            elseif ($tag -eq 2) { Write-Host "[ OPEN ] $payload" -ForegroundColor Magenta }
            else { Write-Host "[ IDLE ] $payload" -ForegroundColor DarkGray }
            
        } catch {
            Write-Host "Failed to parse or route payload: $payload" -ForegroundColor Red
        }
    }
} finally {
    $udpClient.Close()
    Write-Host "Socket closed."
}