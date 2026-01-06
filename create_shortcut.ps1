$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\재무제표 챗봇.lnk")
$Shortcut.TargetPath = "C:\Projects\financial-chatbot\run.bat"
$Shortcut.WorkingDirectory = "C:\Projects\financial-chatbot"
$Shortcut.IconLocation = "shell32.dll,21"
$Shortcut.Description = "재무제표 분석 챗봇 실행"
$Shortcut.Save()
Write-Host "바탕화면에 바로가기가 생성되었습니다!"
