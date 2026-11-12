#requires -Version 5.1
<#
.SYNOPSIS
Isolated HTTPS probe using an existing trusted Mihomo executable and JSON-format YAML profile.
.DESCRIPTION
Does not change TUN, system proxy, DNS or existing processes. Existing routing (including
Tailscale exit node) still applies: success does NOT prove direct ISP reachability.
Only JSON-format profiles produced by this kit are accepted. Raw logs remain private
and are deleted, never printed. -ValidateOnly runs core -t without network probing.
#>
[CmdletBinding()]
param(
 [Parameter(Mandatory=$true)][string]$CorePath,
 [Parameter(Mandatory=$true)][string]$ProfilePath,
 [string]$Url='https://example.com/',
 [switch]$ValidateOnly
)
$ErrorActionPreference='Stop'
$proc=$null; $tmp=$null; $rc=2; $tcp=$null; $udp=$null
try {
 $core=(Resolve-Path -LiteralPath $CorePath).Path
 $source=(Resolve-Path -LiteralPath $ProfilePath).Path
 if (-not (Test-Path -LiteralPath $core -PathType Leaf)) { throw 'core' }
 $uri=[Uri]$Url
 if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) { throw 'url' }
 $inputData=Get-Content -LiteralPath $source -Raw | ConvertFrom-Json
 $nodes=@($inputData.proxies)
 if ($nodes.Count -ne 1) { throw 'single node required' }
 $n=$nodes[0]
 if ($n.type -ne 'vless' -or $n.network -ne 'tcp' -or $n.flow -ne 'xtls-rprx-vision' -or $n.tls -ne $true -or -not $n.'reality-opts'.'public-key') { throw 'node' }
 # Copy protocol fields only; never inherit dialer-proxy, interfaces, provider URLs or startup scripts.
 $node=[ordered]@{
  name='Probe'; type='vless'; server=$n.server; port=$n.port; uuid=$n.uuid
  network='tcp'; tls=$true; udp=$true; flow='xtls-rprx-vision'
  servername=$n.servername; 'client-fingerprint'=$n.'client-fingerprint'
  'reality-opts'=@{'public-key'=$n.'reality-opts'.'public-key'; 'short-id'=$n.'reality-opts'.'short-id'}
 }
 $tmp=Join-Path ([IO.Path]::GetTempPath()) ('mihomo-probe-'+[Guid]::NewGuid().ToString('N'))
 [void][IO.Directory]::CreateDirectory($tmp)
 # Remove inherited access before writing credentials. Failure aborts.
 $acl=New-Object System.Security.AccessControl.DirectorySecurity
 $acl.SetAccessRuleProtection($true,$false)
 $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
 $acl.SetOwner($sid)
 $rule=New-Object System.Security.AccessControl.FileSystemAccessRule($sid,'FullControl','ContainerInherit,ObjectInherit','None','Allow')
 $acl.AddAccessRule($rule)
 Set-Acl -LiteralPath $tmp -AclObject $acl
 $config=Join-Path $tmp 'probe.json'
 $outLog=Join-Path $tmp 'stdout.log'; $errLog=Join-Path $tmp 'stderr.log'
 # Reserve the SAME port for TCP and UDP on IPv4 loopback. Release immediately
 # before core start; PID validation below catches the unavoidable bind race.
 $port=0
 for($i=0;$i -lt 30;$i++){
  try {
   $tcp=New-Object Net.Sockets.TcpListener([Net.IPAddress]::Loopback,0)
   $tcp.Start(); $candidate=$tcp.LocalEndpoint.Port
   $udp=New-Object Net.Sockets.UdpClient
   $udp.ExclusiveAddressUse=$true
   $udp.Client.Bind((New-Object Net.IPEndPoint([Net.IPAddress]::Loopback,$candidate)))
   $port=$candidate; break
  } catch {
   if($tcp){$tcp.Stop();$tcp=$null}; if($udp){$udp.Dispose();$udp=$null}
  }
 }
 if($port -eq 0){throw 'port allocation'}
 $cfg=[ordered]@{
  'socks-port'=$port; 'allow-lan'=$false; 'bind-address'='127.0.0.1'
  mode='rule'; 'log-level'='silent'; ipv6=$false
  tun=@{enable=$false}; dns=@{enable=$false}
  profile=@{'store-selected'=$false;'store-fake-ip'=$false}
  proxies=@($node); rules=@('MATCH,Probe')
 }
 [IO.File]::WriteAllText($config,($cfg|ConvertTo-Json -Depth 15),(New-Object Text.UTF8Encoding($false)))
 $argsLine='-t -d "'+$tmp+'" -f "'+$config+'"'
 $proc=Start-Process -FilePath $core -ArgumentList $argsLine -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
 if(-not $proc.WaitForExit(15000)){throw 'validation timeout'}
 if($proc.ExitCode -ne 0){throw 'configuration rejected'}
 $proc.Dispose();$proc=$null
 if($ValidateOnly){Write-Output 'CONFIG_VALID: supplied core accepted isolated profile.';$rc=0}
 else {
  $tcp.Stop();$tcp=$null;$udp.Dispose();$udp=$null
  $proc=Start-Process -FilePath $core -ArgumentList ('-d "'+$tmp+'" -f "'+$config+'"') -PassThru -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
  $ready=$false
  for($i=0;$i -lt 100;$i++){
   if($proc.HasExited){break}
   $owned=@(Get-NetTCPConnection -LocalAddress '127.0.0.1' -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.OwningProcess -eq $proc.Id})
   if($owned.Count -gt 0){$ready=$true;break}
   Start-Sleep -Milliseconds 100
  }
  if(-not $ready){throw 'isolated listener did not start'}
  Write-Output 'PATH: curl -> isolated loopback SOCKS -> selected VLESS node -> HTTPS target.'
  Write-Output 'Existing OS/Tailscale routing remains in effect. No TUN or system-proxy changes.'
  $curl=(Get-Command curl.exe -ErrorAction Stop).Source
  # Override any inherited NO_PROXY without an empty argv (PowerShell 5.1 drops empty args).
  # Asterisk-leading nonmatching hostname bypasses neither localhost proxy nor target.
  $result=& $curl -q --silent --show-error --noproxy 'never-bypass.invalid' --proxy "socks5h://127.0.0.1:$port" --connect-timeout 10 --max-time 25 --output NUL --write-out 'HTTP=%{http_code}; seconds=%{time_total}' $uri.AbsoluteUri 2>$errLog
  $curlExit=$LASTEXITCODE
  Write-Output ($result -join '')
  Write-Output "curl_exit=$curlExit"
  if($curlExit -eq 0){$rc=0;Write-Output 'PROBE_OK: TLS/HTTPS transfer completed. Inspect HTTP status separately.'}
  else {Write-Output 'PROBE_FAILED: inspect path and server logs. Private raw client logs were not printed.'}
 }
} catch {Write-Output 'PROBE_FAILED: validation/start/probe failed. No secret-containing exception or raw logs printed.'}
finally {
 if($tcp){$tcp.Stop()};if($udp){$udp.Dispose()}
 if($proc){try{if(-not $proc.HasExited){$proc.Kill();$proc.WaitForExit()}}catch{};$proc.Dispose()}
 if($tmp -and (Test-Path -LiteralPath $tmp)){
  try{Remove-Item -LiteralPath $tmp -Recurse -Force;Write-Output 'CLEANUP_OK: own temporary files removed.'}
  catch{Write-Output 'CLEANUP_FAILED: remove the mihomo-probe temporary directory manually; it contains credentials.'}
 }
 Write-Output 'SOURCE_UNCHANGED: original profile and system networking were not modified.'
}
exit $rc
