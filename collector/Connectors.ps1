# Fixed inventory queries only. Credentials arrive through standard input, never arguments.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$target = [Console]::In.ReadToEnd() | ConvertFrom-Json
$records = New-Object 'System.Collections.Generic.List[object]'
function Record($identity, $product, $name, $version) {
    if ([string]::IsNullOrWhiteSpace($identity) -or [string]::IsNullOrWhiteSpace($version)) { throw 'unsupported' }
    $records.Add(@{ identity=[string]$identity; product=$product; name=[string]$name; version=[string]$version; target=[string]$target.address })
}
function XmlEscape($value) { [Security.SecurityElement]::Escape([string]$value) }
function ReadXml([string]$content) {
    $settings = New-Object System.Xml.XmlReaderSettings
    $settings.DtdProcessing = [System.Xml.DtdProcessing]::Prohibit
    $settings.XmlResolver = $null
    $reader = [System.Xml.XmlReader]::Create((New-Object System.IO.StringReader($content)), $settings)
    $doc = New-Object System.Xml.XmlDocument
    $doc.XmlResolver = $null
    try { $doc.Load($reader) } finally { $reader.Dispose() }
    return ,$doc
}
try {
    if ([Uri]::CheckHostName($target.address) -eq [UriHostNameType]::Unknown) { throw 'unsupported' }
    if ($target.kind -in @('Windows', 'Hyper-V')) {
        $secure = ConvertTo-SecureString $target.password -AsPlainText -Force
        $credential = New-Object Management.Automation.PSCredential($target.username, $secure)
        $options = New-CimSessionOption -Protocol Wsman -UseSsl:([bool]$target.win_rm_https)
        $cim = New-CimSession -ComputerName $target.address -Credential $credential -Authentication Negotiate -SessionOption $options -OperationTimeoutSec 45
        try {
            $os = Get-CimInstance -CimSession $cim -ClassName Win32_OperatingSystem -Property Caption,CSName
            $system = Get-CimInstance -CimSession $cim -ClassName Win32_ComputerSystemProduct -Property UUID
            $caption = [string]$os.Caption
            if ($caption -notmatch '(?:Windows|Hyper-V) Server.*?(2008|2012|2016|2019|2022|2025)( R2)?') { throw 'unsupported' }
            $release = 'Windows Server ' + $Matches[1] + $Matches[2]
            if ($caption -match 'Hyper-V Server') { $release = $caption.Trim() }
            Record $system.UUID 'Windows Server' $os.CSName $release
            if ($target.kind -eq 'Hyper-V') {
                $hyperv = Get-CimInstance -CimSession $cim -ClassName Win32_Service -Filter "Name='vmms'" -Property Name
                if (-not $hyperv) { throw 'unsupported' }
                Record $system.UUID 'Hyper-V' $os.CSName $release
            }
        } finally { Remove-CimSession $cim }
    }
    elseif ($target.kind -eq 'Palo Alto') {
        $uri = 'https://' + $target.address + '/api/'
        $response = Invoke-WebRequest -UseBasicParsing -Uri $uri -Method Post -Body @{type='keygen';user=$target.username;password=$target.password} -TimeoutSec 45 -MaximumRedirection 0
        $xml = ReadXml $response.Content
        if ($xml.response.status -ne 'success') { throw 'authentication' }
        $key = [string]$xml.response.result.key
        $response = Invoke-WebRequest -UseBasicParsing -Uri $uri -Method Post -Headers @{'X-PAN-KEY'=$key} -Body @{type='op';cmd='<show><system><info></info></system></show>'} -TimeoutSec 45 -MaximumRedirection 0
        $xml = ReadXml $response.Content
        if ($xml.response.status -ne 'success') { throw 'permissions' }
        $system = $xml.response.result.system
        Record ('pan:' + $system.serial) 'Palo Alto PAN-OS' $system.hostname $system.'sw-version'
    }
    elseif ($target.kind -eq 'Veeam') {
        $base = 'https://' + $target.address + ':9419'
        $headers = @{'x-api-version'=[string]$target.api_version}
        $auth = Invoke-RestMethod -Uri ($base+'/api/oauth2/token') -Method Post -Headers $headers -Body @{grant_type='password';username=$target.username;password=$target.password} -TimeoutSec 45 -MaximumRedirection 0
        $headers.Authorization = 'Bearer ' + $auth.access_token
        try {
            $info = Invoke-RestMethod -Uri ($base+'/api/v1/serverInfo') -Headers $headers -TimeoutSec 45 -MaximumRedirection 0
            $installationId = if ($info.vbrId) { $info.vbrId } else { $info.installationId }
            if (-not $installationId) { throw 'unsupported' }
            Record ('veeam:'+$installationId) 'Veeam Backup & Replication' $info.name $info.buildVersion
        } finally {
            try { Invoke-RestMethod -Uri ($base+'/api/oauth2/logout') -Method Post -Headers $headers -TimeoutSec 15 -MaximumRedirection 0 | Out-Null } catch { }
        }
    }
    elseif ($target.kind -eq 'VMware') {
        $script:vmUri = 'https://' + $target.address + '/sdk'
        $script:vmSession = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        function Soap($operation, $body) {
            $envelope = '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><soap:Body><'+$operation+' xmlns="urn:vim25">'+$body+'</'+$operation+'></soap:Body></soap:Envelope>'
            $r = Invoke-WebRequest -UseBasicParsing -Uri $script:vmUri -WebSession $script:vmSession -Method Post -ContentType 'text/xml; charset=utf-8' -Headers @{SOAPAction='"urn:vim25/6.5"'} -Body $envelope -TimeoutSec 60 -MaximumRedirection 0
            $doc = ReadXml $r.Content
            if ($doc.SelectSingleNode("//*[local-name()='Fault']")) { throw 'query_failed' }
            return ,$doc
        }
        $content = (Soap 'RetrieveServiceContent' '<_this type="ServiceInstance">ServiceInstance</_this>').SelectSingleNode("//*[local-name()='returnval']")
        $manager = XmlEscape $content.sessionManager.InnerText
        $null = Soap 'Login' ('<_this type="SessionManager">'+$manager+'</_this><userName>'+(XmlEscape $target.username)+'</userName><password>'+(XmlEscape $target.password)+'</password>')
        $view = $null
        try {
            if ($content.about.apiType -eq 'VirtualCenter') {
                if (-not $content.about.instanceUuid) { throw 'unsupported' }
                Record ('vcenter:'+$content.about.instanceUuid) 'VMware vCenter' $target.address ($content.about.version+' build '+$content.about.build)
            }
            $viewDoc = Soap 'CreateContainerView' ('<_this type="ViewManager">'+(XmlEscape $content.viewManager.InnerText)+'</_this><container type="Folder">'+(XmlEscape $content.rootFolder.InnerText)+'</container><type>HostSystem</type><recursive>true</recursive>')
            $view = $viewDoc.SelectSingleNode("//*[local-name()='returnval']").InnerText
            $collector = '<_this type="PropertyCollector">'+(XmlEscape $content.propertyCollector.InnerText)+'</_this>'
            $spec = '<specSet><propSet><type>HostSystem</type><pathSet>name</pathSet><pathSet>config.product</pathSet><pathSet>summary.hardware.uuid</pathSet></propSet><objectSet><obj type="ContainerView">'+(XmlEscape $view)+'</obj><skip>true</skip><selectSet xsi:type="TraversalSpec"><name>hosts</name><type>ContainerView</type><path>view</path><skip>false</skip></selectSet></objectSet></specSet><options><maxObjects>250</maxObjects></options>'
            $doc = Soap 'RetrievePropertiesEx' ($collector+$spec)
            do {
                foreach ($obj in $doc.SelectNodes("//*[local-name()='returnval']/*[local-name()='objects']")) {
                    $props=@{}
                    foreach ($prop in $obj.SelectNodes("*[local-name()='propSet']")) { $props[$prop.name]=$prop.val }
                    if (-not $props['summary.hardware.uuid'] -or -not $props['config.product']) { throw 'permissions' }
                    $id = if ($props['summary.hardware.uuid'] -is [System.Xml.XmlElement]) {$props['summary.hardware.uuid'].InnerText} else {[string]$props['summary.hardware.uuid']}
                    $hostName = if ($props['name'] -is [System.Xml.XmlElement]) {$props['name'].InnerText} else {[string]$props['name']}
                    Record ('esxi:'+$id) 'VMware ESXi' $hostName ($props['config.product'].version+' build '+$props['config.product'].build)
                }
                $continuation = $doc.SelectSingleNode("//*[local-name()='returnval']/*[local-name()='token']")
                if ($continuation) { $doc = Soap 'ContinueRetrievePropertiesEx' ($collector+'<token>'+(XmlEscape $continuation.InnerText)+'</token>') }
            } while ($continuation)
        } finally {
            if ($view) { try { $null=Soap 'DestroyView' ('<_this type="ContainerView">'+(XmlEscape $view)+'</_this>') } catch {} }
            try { $null=Soap 'Logout' ('<_this type="SessionManager">'+$manager+'</_this>') } catch {}
        }
    }
    else { throw 'unsupported' }
    [Console]::Out.Write((ConvertTo-Json -InputObject @($records.ToArray()) -Depth 8 -Compress))
    exit 0
} catch {
    # Do not emit exception content; vendor responses may contain credentials or tokens.
    $message = $_.Exception.Message
    if ($message -match 'authentication|401|logon failure|incorrect user') { exit 2 }
    if ($message -match 'permissions|403|access is denied|access denied') { exit 3 }
    if ($message -match 'unsupported|404') { exit 5 }
    if ($message -match 'connect|timed out|resolve|certificate|SSL|TLS') { exit 4 }
    exit 1
}
