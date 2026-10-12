# Create a desktop shortcut for KeyFreeze.exe
$ErrorActionPreference = 'Stop'

$exe = 'D:\LABS\KeyFreeze\dist\KeyFreeze.exe'
if (-not (Test-Path -LiteralPath $exe)) {
    throw "KeyFreeze.exe not found at $exe"
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktop 'KeyFreeze.lnk'

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($shortcutPath)
$lnk.TargetPath = $exe
$lnk.WorkingDirectory = 'D:\LABS\KeyFreeze\dist'
$lnk.IconLocation = "$exe,0"
$lnk.Description = 'KeyFreeze - temporarily lock keyboard and mouse input'
$lnk.Save()

Write-Output "Desktop folder : $desktop"
Write-Output "Shortcut saved : $shortcutPath"

Get-Item -LiteralPath $exe | ForEach-Object {
    Write-Output ("Exe            : {0} ({1:N0} bytes)" -f $_.FullName, $_.Length)
}
