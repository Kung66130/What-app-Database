Write-Host "=========================================================="
Write-Host "Deploying WhatsApp Agent to Raspberry Pi 5"
Write-Host "=========================================================="
Write-Host "Connecting to Pi via Tailscale IP: 100.123.233.122"
Write-Host "Note: When prompted, enter the password: 0967471344"
Write-Host ""

$sshCommand = @"
echo 'Updating system packages and installing Chromium browser (Required for Pi)...'
sudo apt-get update && sudo apt-get install -y chromium-browser

echo 'Updating code from GitHub...'
cd ~/what-app-database 2>/dev/null || { echo 'Directory ~/what-app-database not found'; exit 1; }
git pull origin main

echo 'Installing Node.js dependencies...'
npm install

echo 'Restarting wa-agent service...'
sudo systemctl restart wa-agent

echo 'Starting Node TTS background process...'
pkill -f "node index.js"
nohup node index.js > tts_node.log 2>&1 &

echo '====================================='
echo 'Deployment completed successfully!'
echo '====================================='
"@

ssh admin@100.123.233.122 $sshCommand

Write-Host ""
Write-Host "Deployment script finished."
Pause
