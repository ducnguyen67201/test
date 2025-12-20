# PowerShell script to start development servers
Write-Host "Starting zeroZero Development Environment..." -ForegroundColor Green

# Start API server in new terminal
Write-Host "Starting Go API server..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/api; go run cmd/server/main.go"

# Wait a moment for API to start
Start-Sleep -Seconds 3

# Start Web server in new terminal
Write-Host "Starting Next.js web server..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/web; npm run dev"

Write-Host "`nServers starting:" -ForegroundColor Green
Write-Host "  - API Server: http://localhost:8080" -ForegroundColor Cyan
Write-Host "  - Web Server: http://localhost:3000" -ForegroundColor Cyan
Write-Host "  - gRPC Server: http://localhost:9090" -ForegroundColor Cyan
Write-Host "`nPress any key to exit..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')