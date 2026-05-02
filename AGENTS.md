# Voice Assistant Script - Agent Rules

## Text-to-speech after every answer

After you produce your final answer to the user, speak the same text by running a PowerShell command.

Command:

`powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$t=@'<PASTE_FINAL_ANSWER_HERE>'@; & 'C:\Project\Voice Assistant Script\speak.ps1' -Text $t"`

Notes:
- Paste the full final answer inside the here-string exactly as sent.
- If the final answer is very long, you may summarize it for speech, but keep the on-screen answer unchanged.
- Do not run other commands unless explicitly requested.

## Open Jarvis command

If the user says `เปิดระบบจาวิส` or `open jarvis`, start the interactive Jarvis loop by running:

`powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\Project\Voice Assistant Script\jarvis.ps1"`
