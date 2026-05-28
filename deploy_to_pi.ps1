Write-Host "=========================================================="
Write-Host "Deploying WhatsApp Agent to Raspberry Pi 5"
Write-Host "=========================================================="
Write-Host "Connecting to Pi via Tailscale IP: 100.123.233.122"
Write-Host "Note: When prompted, enter the password: 0967471344"
Write-Host ""

$setupCommand = "sudo apt-get update && sudo apt-get install -y chromium && cd ~/what-app-database 2>/dev/null && git pull origin main && npm install"
ssh -t admin@100.123.233.122 $setupCommand

echo 'Restarting wa-agent service...'
$sshCommand = "sudo systemctl restart wa-agent 2>/dev/null; pkill -f 'node index.js'; cd ~/what-app-database && nohup node index.js > tts_node.log 2>&1 &"
ssh admin@100.123.233.122 $sshCommand

Write-Host ""
Write-Host "Deployment script finished. Please check the logs."
Pause
