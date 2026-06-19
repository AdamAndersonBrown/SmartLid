# Listen-IMU-V2.ps1
$port = 3333
# Force binding to 0.0.0.0 to catch broadcasts across all adapters
$endpoint = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Parse("0.0.0.0"), $port)
$udpClient = New-Object System.Net.Sockets.UdpClient
$udpClient.Client.Bind($endpoint)

Write-Host "Listening universally for Core2 IMU telemetry on UDP port $port..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop." -ForegroundColor Gray

try {
    while ($true) {
        $content = $udpClient.Receive([ref]$endpoint)
        $payload = [System.Text.Encoding]::UTF8.GetString($content)
        Write-Host "[$($endpoint.Address)] $payload"
    }
} finally {
    $udpClient.Close()
    Write-Host "Socket closed."
}