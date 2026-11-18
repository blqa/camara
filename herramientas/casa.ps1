# MI CASA - un solo programa para todo (no necesita instalar nada)
#   1) Prende go2rtc (las camaras) si esta en la misma carpeta.
#   2) Escanea tu red cada minuto y pita si entra un aparato desconocido.
#   3) Le pasa todo a https://camara.godsplan.site para verlo en una sola pagina.
# Uso: doble clic en Iniciar.bat. Para salir: cierra la ventana.

$Carpeta   = Split-Path -Parent $MyInvocation.MyCommand.Path
$Puerto    = 8000
$Pagina    = "https://camara.godsplan.site"
$Permitidos = @($Pagina, "http://localhost:$Puerto")
$Archivo   = Join-Path $Carpeta "dispositivos.json"
$CadaSeg   = 60
$NombresIniciales = @{ "9C:84:B6:B8:AF:2A" = "Camara 2NLF" }

$Disp = @{}
$Global:Red = "?"
$Global:UltimoEscaneo = "nunca"
$Global:EscanearYa = $false

# ---------------- Utilidades ----------------
function Ahora { (Get-Date).ToString("dd/MM HH:mm") }

function PuertoAbierto($p) {
    $c = New-Object Net.Sockets.TcpClient
    try { return $c.ConnectAsync("127.0.0.1", $p).Wait(400) } catch { return $false } finally { $c.Close() }
}

function MiIP {
    try {
        $s = New-Object Net.Sockets.Socket([Net.Sockets.AddressFamily]::InterNetwork, [Net.Sockets.SocketType]::Dgram, [Net.Sockets.ProtocolType]::Udp)
        $s.Connect("8.8.8.8", 80)
        $ip = $s.LocalEndPoint.Address.ToString()
        $s.Close()
        return $ip
    } catch { return "192.168.100.3" }
}

function EsPrivada($mac) { return ($mac.Length -gt 1) -and ("26AE".Contains($mac.Substring(1,1).ToUpper())) }

function Pitar { try { 1..3 | ForEach-Object { [console]::Beep(1200, 180); Start-Sleep -Milliseconds 80 } } catch {} }

function Cargar {
    if (Test-Path $Archivo) {
        try {
            $obj = Get-Content $Archivo -Raw -Encoding UTF8 | ConvertFrom-Json
            foreach ($p in $obj.PSObject.Properties) {
                $h = @{}
                foreach ($q in $p.Value.PSObject.Properties) { $h[$q.Name] = $q.Value }
                $Disp[$p.Name] = $h
            }
            return $false
        } catch { }
    }
    return $true   # primera vez
}

function Guardar {
    try { $Disp | ConvertTo-Json -Depth 5 | Set-Content -Path $Archivo -Encoding UTF8 } catch { }
}

# ---------------- Escaneo de la red ----------------
function Escanear([bool]$primera = $false) {
    $yo = MiIP
    $base = ($yo.Split(".")[0..2]) -join "."
    $Global:Red = "$base.0/24"

    # 1) Ping a toda la red al mismo tiempo
    $tareas = @{}
    foreach ($i in 1..254) {
        $ip = "$base.$i"
        $tareas[$ip] = (New-Object Net.NetworkInformation.Ping).SendPingAsync($ip, 600)
    }
    try { [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($tareas.Values), 5000) | Out-Null } catch { }
    $respondieron = @{}
    foreach ($ip in $tareas.Keys) {
        $t = $tareas[$ip]
        if ($t.Status -eq "RanToCompletion" -and $t.Result.Status -eq "Success") { $respondieron[$ip] = $true }
    }

    # 2) Tabla de vecinos de Windows: IP + MAC
    $vistos = @{}
    $vecinos = Get-NetNeighbor -AddressFamily IPv4 -ErrorAction SilentlyContinue
    foreach ($v in $vecinos) {
        $ip = $v.IPAddress
        $mac = "$($v.LinkLayerAddress)".Replace("-", ":").ToUpper()
        if (-not $ip.StartsWith("$base.") -or $ip.EndsWith(".255")) { continue }
        if ($mac -eq "" -or $mac -eq "00:00:00:00:00:00" -or $mac -eq "FF:FF:FF:FF:FF:FF" -or $mac.StartsWith("01:00:5E")) { continue }
        $estado = "$($v.State)"
        if ($respondieron.ContainsKey($ip) -or @("Reachable", "Delay", "Probe") -contains $estado) { $vistos[$mac] = $ip }
    }
    $vistos["ESTA-PC"] = $yo

    # 3) Nombres de red (maximo 2.5 s)
    $dns = @{}
    foreach ($mac in @($vistos.Keys)) { if ($mac -ne "ESTA-PC") { $dns[$mac] = [Net.Dns]::GetHostEntryAsync($vistos[$mac]) } }
    if ($dns.Count -gt 0) { try { [Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($dns.Values), 2500) | Out-Null } catch { } }

    # 4) Actualizar la lista
    $hora = Ahora
    $nuevos = @()
    foreach ($k in @($Disp.Keys)) { $Disp[$k].en_linea = $false }
    foreach ($mac in @($vistos.Keys)) {
        $ip = $vistos[$mac]
        $host_ = ""
        if ($mac -eq "ESTA-PC") { $host_ = $env:COMPUTERNAME }
        elseif ($dns[$mac].Status -eq "RanToCompletion") {
            $host_ = $dns[$mac].Result.HostName
            if ($host_ -eq $ip) { $host_ = "" }
        }
        if (-not $Disp.ContainsKey($mac)) {
            $nombre = ""
            if ($mac -eq "ESTA-PC") { $nombre = "Esta PC" } elseif ($NombresIniciales.ContainsKey($mac)) { $nombre = $NombresIniciales[$mac] }
            $esNuevo = (-not $primera) -and ($mac -ne "ESTA-PC")
            $Disp[$mac] = @{ nombre = $nombre; primera_vez = $hora; nuevo = $esNuevo }
            if ($esNuevo) { $nuevos += "$ip ($mac)" }
        }
        $Disp[$mac].ip = $ip
        $Disp[$mac].host = $host_
        $Disp[$mac].ultima_vez = $hora
        $Disp[$mac].en_linea = $true
    }
    $Global:UltimoEscaneo = (Get-Date).ToString("HH:mm:ss")
    Guardar

    Write-Host ("[{0}] Escaneo listo: {1} aparatos conectados" -f $Global:UltimoEscaneo, $vistos.Count)
    foreach ($n in $nuevos) { Write-Host "   !!! APARATO NUEVO: $n" -ForegroundColor Yellow }
    if ($nuevos.Count -gt 0) { Pitar }
}

# ---------------- Servidor para la pagina ----------------
function Enviar($res, [string]$texto, [string]$tipo = "application/json; charset=utf-8") {
    $bytes = [Text.Encoding]::UTF8.GetBytes($texto)
    $res.ContentType = $tipo
    $res.Headers.Add("Cache-Control", "no-store")
    $res.ContentLength64 = $bytes.Length
    $res.OutputStream.Write($bytes, 0, $bytes.Length)
    $res.Close()
}

function InfoJson {
    $lista = @()
    foreach ($k in @($Disp.Keys)) {
        $d = $Disp[$k]
        $lista += [ordered]@{
            mac = $k; nombre = "$($d.nombre)"; ip = "$($d.ip)"; host = "$($d.host)"
            primera_vez = "$($d.primera_vez)"; ultima_vez = "$($d.ultima_vez)"
            en_linea = [bool]$d.en_linea; nuevo = [bool]$d.nuevo
            mac_privada = (($k -ne "ESTA-PC") -and (EsPrivada $k))
        }
    }
    $info = [ordered]@{
        red = $Global:Red; ultimo_escaneo = $Global:UltimoEscaneo; escaneando = $false
        go2rtc = (PuertoAbierto 1984); dispositivos = @($lista)
    }
    return ($info | ConvertTo-Json -Depth 5 -Compress)
}

function Atender($ctx) {
    $req = $ctx.Request
    $res = $ctx.Response
    $origen = $req.Headers["Origin"]
    $permitido = $origen -and ($Permitidos -contains $origen)
    if ($permitido) {
        $res.Headers.Add("Access-Control-Allow-Origin", $origen)
        $res.Headers.Add("Vary", "Origin")
        $res.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        $res.Headers.Add("Access-Control-Allow-Headers", "Content-Type")
        $res.Headers.Add("Access-Control-Allow-Private-Network", "true")
    }
    $ruta = $req.Url.AbsolutePath

    if ($req.HttpMethod -eq "OPTIONS") { $res.StatusCode = 204; $res.Close(); return }

    if ($req.HttpMethod -eq "GET" -and $ruta -eq "/api/dispositivos") { Enviar $res (InfoJson); return }

    if ($req.HttpMethod -eq "POST" -and $ruta.StartsWith("/api/")) {
        if (-not $permitido) { $res.StatusCode = 403; Enviar $res '{"error":"origen no permitido"}'; return }
        $cuerpo = (New-Object IO.StreamReader($req.InputStream, [Text.Encoding]::UTF8)).ReadToEnd()
        $datos = $null
        if ($cuerpo) { try { $datos = $cuerpo | ConvertFrom-Json } catch { } }
        $mac = if ($datos) { "$($datos.mac)" } else { "" }
        if ($ruta -eq "/api/nombrar" -and $Disp.ContainsKey($mac)) {
            $nombre = "$($datos.nombre)".Trim()
            if ($nombre.Length -gt 40) { $nombre = $nombre.Substring(0, 40) }
            $Disp[$mac].nombre = $nombre
            $Disp[$mac].nuevo = $false
            Guardar
        } elseif ($ruta -eq "/api/ok" -and $Disp.ContainsKey($mac)) {
            $Disp[$mac].nuevo = $false
            Guardar
        } elseif ($ruta -eq "/api/escanear") {
            $Global:EscanearYa = $true
        }
        Enviar $res '{"ok":true}'
        return
    }

    Enviar $res "<html><body style='font-family:sans-serif;background:#0a0f1c;color:#e5e7eb;padding:40px'><h1>Mi casa esta corriendo</h1><p>Abre <a style='color:#38bdf8' href='$Pagina'>$Pagina</a></p></body></html>" "text/html; charset=utf-8"
}

# ---------------- Arranque ----------------
$Host.UI.RawUI.WindowTitle = "Mi casa - no cierres esta ventana"
Write-Host "=================================================="
Write-Host "  MI CASA" -ForegroundColor Green

$go2rtc = $null
$exe = Join-Path $Carpeta "go2rtc.exe"
if (PuertoAbierto 1984) {
    Write-Host "  Camaras: go2rtc ya estaba prendido"
} elseif (Test-Path $exe) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $exe
    $psi.WorkingDirectory = $Carpeta
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $go2rtc = [Diagnostics.Process]::Start($psi)
    Write-Host "  Camaras: go2rtc prendido"
} else {
    Write-Host "  Camaras: no encontre go2rtc.exe en esta carpeta" -ForegroundColor Yellow
}

$listener = New-Object Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Puerto/")
try { $listener.Start() } catch {
    Write-Host "  No pude abrir el puerto $Puerto. Quiza Mi casa ya esta abierto en otra ventana." -ForegroundColor Red
    Read-Host "Presiona Enter para salir"
    exit 1
}
Write-Host "  Red: escaneando cada minuto"
Write-Host "  Pagina: $Pagina"
Write-Host "  Deja esta ventana abierta (puedes minimizarla)."
Write-Host "=================================================="

$primera = Cargar
Start-Process $Pagina
$siguiente = Get-Date
$tarea = $null
try {
    while ($true) {
        if ((Get-Date) -ge $siguiente -or $Global:EscanearYa) {
            $Global:EscanearYa = $false
            try { Escanear $primera } catch { Write-Host "Error al escanear: $_" -ForegroundColor Red }
            $primera = $false
            $siguiente = (Get-Date).AddSeconds($CadaSeg)
        }
        if ($null -eq $tarea) { $tarea = $listener.GetContextAsync() }
        if ($tarea.Wait(500)) {
            $ctx = $tarea.Result
            $tarea = $null
            try { Atender $ctx } catch { try { $ctx.Response.Abort() } catch { } }
        }
    }
} finally {
    $listener.Stop()
    if ($null -ne $go2rtc -and -not $go2rtc.HasExited) { $go2rtc.Kill() }
}
