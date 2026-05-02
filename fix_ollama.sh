#!/bin/bash
echo '0967471344' | sudo -S sh -c 'printf "[Service]\nEnvironment=OLLAMA_HOST=0.0.0.0\n" > /etc/systemd/system/ollama.service.d/override.conf'
echo '0967471344' | sudo -S systemctl daemon-reload
echo '0967471344' | sudo -S systemctl restart ollama
sleep 2
curl -s http://127.0.0.1:11434/
