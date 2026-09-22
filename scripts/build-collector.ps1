param([string]$Version='0.1.0',[switch]$UnsignedPilot)
$ErrorActionPreference='Stop'
$root=Split-Path $PSScriptRoot -Parent
if (-not $UnsignedPilot -and (Get-Content "$root\collector\update-public-key.pem" -Raw) -notmatch 'BEGIN PUBLIC KEY') { throw 'Configure the release verification public key before distribution. Use -UnsignedPilot only for an isolated pilot build.' }
dotnet publish "$root\collector\SysTracker.Collector.csproj" -c Release -r win-x64 --self-contained true -o "$root\dist\collector" -p:Version=$Version
if($LASTEXITCODE -ne 0){throw 'Collector publish failed'}
# WiX 5: install once using `dotnet tool install --global wix --version 5.0.2`.
wix build "$root\installer\Package.wxs" -arch x64 -d "Version=$Version" -d "PublishDir=$root\dist\collector" -o "$root\dist\SysTracker-$Version.msi"
if($LASTEXITCODE -ne 0){throw 'MSI build failed'}
Write-Host "Built $root\dist\SysTracker-$Version.msi. Validate install, upgrade, and uninstall on Windows before distribution."
