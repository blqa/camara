# -*- coding: utf-8 -*-
"""
MI CASA - un solo programa para todo
  1) Prende go2rtc (las camaras) si esta en la misma carpeta.
  2) Escanea tu red cada minuto y avisa si entra un aparato desconocido.
  3) Le pasa todo a https://camara.godsplan.site para verlo en una sola pagina.

Uso:  doble clic en Iniciar.bat   (o:  python casa.py)
Pon este archivo en la misma carpeta que go2rtc.exe (por ejemplo C:\\camaras).
Para detenerlo: cierra la ventana negra o Ctrl + C.

Solo usa librerias que ya trae Python, no hay que instalar nada.
"""

import html
import json
import os
import platform
import re
import socket
import subprocess
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

# ---------------- AJUSTES (puedes cambiarlos) ----------------
PUERTO = 8000            # aqui escucha el radar (http://localhost:8000)
PAGINA = "https://camara.godsplan.site"
# Solo estas paginas pueden leer la lista de aparatos de tu red
ORIGENES_PERMITIDOS = {PAGINA, f"http://localhost:{PUERTO}", f"http://127.0.0.1:{PUERTO}"}
CADA_SEGUNDOS = 60       # cada cuanto escanea la red
SONIDO_AL_DETECTAR = True

# Nombres que ya conocemos (MAC -> nombre)
NOMBRES_INICIALES = {
    "9C:84:B6:B8:AF:2A": "Camara 2NLF",
}
# --------------------------------------------------------------

CARPETA = os.path.dirname(os.path.abspath(__file__))
ARCHIVO = os.path.join(CARPETA, "dispositivos.json")
ES_WINDOWS = platform.system() == "Windows"
SIN_VENTANA = subprocess.CREATE_NO_WINDOW if ES_WINDOWS else 0

estado = {"dispositivos": {}, "ultimo_escaneo": "nunca", "escaneando": False, "red": "?"}
candado = threading.Lock()


# ---------------- Utilidades de red ----------------
def mi_ip():
    """Averigua la IP local de esta PC (no manda nada a internet)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    finally:
        s.close()


def ping(ip):
    """Devuelve True si el aparato responde al ping."""
    if ES_WINDOWS:
        cmd = ["ping", "-n", "1", "-w", "700", ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           creationflags=SIN_VENTANA, timeout=4)
        return "TTL=" in r.stdout.decode(errors="ignore").upper()
    except Exception:
        return False


def tabla_arp():
    """Lee la tabla ARP de la PC: que IP tiene que MAC."""
    try:
        r = subprocess.run(["arp", "-a"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                           creationflags=SIN_VENTANA, timeout=10)
    except Exception:
        return {}
    resultado = {}
    patron = re.compile(r"(\d+\.\d+\.\d+\.\d+)\D{1,40}?([0-9a-fA-F]{2}(?:[:-][0-9a-fA-F]{2}){5})")
    for linea in r.stdout.decode(errors="ignore").splitlines():
        m = patron.search(linea)
        if not m:
            continue
        ip, mac = m.group(1), m.group(2).replace("-", ":").upper()
        if mac == "FF:FF:FF:FF:FF:FF" or mac.startswith("01:00:5E") or ip.endswith(".255"):
            continue
        resultado[ip] = mac
    return resultado


def nombre_de_red(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        return ""


def es_mac_privada(mac):
    """Celulares modernos usan MACs 'inventadas' (privadas)."""
    try:
        return mac[1].upper() in "26AE"
    except Exception:
        return False


# ---------------- Guardar / cargar ----------------
def cargar():
    if os.path.exists(ARCHIVO):
        with open(ARCHIVO, "r", encoding="utf-8") as f:
            return json.load(f), False
    return {}, True  # True = primera vez


def guardar():
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(estado["dispositivos"], f, ensure_ascii=False, indent=2)


def pitar():
    if not SONIDO_AL_DETECTAR:
        return
    try:
        if ES_WINDOWS:
            import winsound
            for _ in range(3):
                winsound.Beep(1200, 180)
                time.sleep(0.08)
        else:
            print("\a", end="", flush=True)
    except Exception:
        pass


# ---------------- El escaneo ----------------
def escanear(primera_vez=False):
    with candado:
        if estado["escaneando"]:
            return
        estado["escaneando"] = True
    try:
        yo = mi_ip()
        base = ".".join(yo.split(".")[:3])
        estado["red"] = base + ".0/24"
        ips = [f"{base}.{i}" for i in range(1, 255)]

        # 1) Ping a toda la red al mismo tiempo (64 a la vez)
        with ThreadPoolExecutor(max_workers=64) as ex:
            list(ex.map(ping, ips))

        # 2) Leer quien respondio (la tabla ARP tiene IP + MAC)
        vistos = {mac: ip for ip, mac in tabla_arp().items() if ip.startswith(base + ".")}
        vistos["ESTA-PC"] = yo

        # 3) Buscar nombres de red
        with ThreadPoolExecutor(max_workers=32) as ex:
            nombres = dict(zip(vistos.keys(), ex.map(nombre_de_red, vistos.values())))

        ahora = datetime.now().strftime("%d/%m %H:%M")
        nuevos = []
        with candado:
            disp = estado["dispositivos"]
            for d in disp.values():
                d["en_linea"] = False
            for mac, ip in vistos.items():
                host = socket.gethostname() if mac == "ESTA-PC" else nombres.get(mac, "")
                if mac not in disp:
                    disp[mac] = {
                        "nombre": "Esta PC" if mac == "ESTA-PC" else NOMBRES_INICIALES.get(mac, ""),
                        "primera_vez": ahora,
                        "nuevo": not primera_vez and mac != "ESTA-PC",
                    }
                    if disp[mac]["nuevo"]:
                        nuevos.append((mac, ip))
                disp[mac].update({"ip": ip, "host": host, "ultima_vez": ahora, "en_linea": True})
            estado["ultimo_escaneo"] = datetime.now().strftime("%H:%M:%S")
            guardar()

        en_linea = sum(1 for d in estado["dispositivos"].values() if d["en_linea"])
        print(f"[{estado['ultimo_escaneo']}] Escaneo listo: {en_linea} aparatos conectados")
        for mac, ip in nuevos:
            print(f"   !!! APARATO NUEVO: {ip}  ({mac})")
        if nuevos:
            pitar()
    finally:
        estado["escaneando"] = False


def bucle():
    _, primera = cargar()
    escanear(primera_vez=primera)
    while True:
        time.sleep(CADA_SEGUNDOS)
        escanear()


# ---------------- La pagina web ----------------
def pagina():
    e = html.escape
    with candado:
        lista = list(estado["dispositivos"].items())
    lista.sort(key=lambda x: (not x[1].get("nuevo"), not x[1].get("en_linea"),
                              [int(p) for p in x[1].get("ip", "0.0.0.0").split(".")]))
    en_linea = sum(1 for _, d in lista if d.get("en_linea"))
    nuevos = sum(1 for _, d in lista if d.get("nuevo"))

    tarjetas = []
    for mac, d in lista:
        clases = "card" + (" on" if d.get("en_linea") else " off") + (" nuevo" if d.get("nuevo") else "")
        nombre = d.get("nombre") or d.get("host") or "Sin nombre"
        extra = []
        if d.get("host") and d.get("host") != nombre:
            extra.append(f"Red: {e(d['host'])}")
        if mac != "ESTA-PC" and es_mac_privada(mac):
            extra.append("MAC privada (probablemente un celular)")
        etiqueta = '<span class="tag">NUEVO</span>' if d.get("nuevo") else ""
        boton_ok = (f'<form method="post" action="/ok"><input type="hidden" name="mac" value="{e(mac)}">'
                    f'<button class="ok">Lo conozco</button></form>') if d.get("nuevo") else ""
        tarjetas.append(f"""
        <div class="{clases}">
          <div class="top"><span class="dot"></span><b>{e(nombre)}</b>{etiqueta}</div>
          <div class="ip">{e(d.get('ip', ''))}</div>
          <div class="mac">{e(mac)}</div>
          <div class="info">{'<br>'.join(extra)}</div>
          <div class="info">Visto por 1a vez: {e(d.get('primera_vez', ''))} &middot; Ultima: {e(d.get('ultima_vez', ''))}</div>
          <form method="post" action="/nombrar" class="renombrar">
            <input type="hidden" name="mac" value="{e(mac)}">
            <input name="nombre" placeholder="Ponle nombre..." value="{e(d.get('nombre', ''))}">
            <button>Guardar</button>
          </form>
          {boton_ok}
        </div>""")

    aviso = (f'<div class="alerta">Hay {nuevos} aparato(s) nuevo(s). Si no sabes que son, revisalos.</div>'
             if nuevos else "")
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Radar de mi red</title>
<style>
  body{{margin:0;font-family:Segoe UI,system-ui,sans-serif;background:#0b1120;color:#e2e8f0}}
  header{{display:flex;align-items:center;gap:24px;padding:24px 32px;border-bottom:1px solid #1e293b}}
  .radar{{width:84px;height:84px;border-radius:50%;position:relative;overflow:hidden;
    background:radial-gradient(circle,#064e3b 0 2px,transparent 3px),
    repeating-radial-gradient(circle,transparent 0 13px,#10b98140 14px 15px),#022c22;
    border:2px solid #10b981}}
  .radar::after{{content:"";position:absolute;inset:0;
    background:conic-gradient(from 0deg,#10b981aa,transparent 25%);animation:gira 2.5s linear infinite}}
  @keyframes gira{{to{{transform:rotate(360deg)}}}}
  h1{{margin:0;font-size:28px}} .sub{{color:#94a3b8;margin-top:4px}}
  .stats{{margin-left:auto;display:flex;gap:28px;text-align:center}}
  .stats b{{display:block;font-size:30px;color:#10b981}} .stats .n b{{color:#f59e0b}}
  .barra{{padding:12px 32px;display:flex;gap:12px;align-items:center;color:#94a3b8}}
  .alerta{{margin:12px 32px;padding:14px 18px;border-radius:10px;background:#78350f;color:#fde68a;font-weight:600}}
  .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px;padding:16px 32px 40px}}
  .card{{background:#111827;border:1px solid #1f2937;border-radius:14px;padding:16px}}
  .card.off{{opacity:.45}} .card.nuevo{{border-color:#f59e0b;box-shadow:0 0 18px #f59e0b55}}
  .top{{display:flex;align-items:center;gap:8px;font-size:17px}}
  .dot{{width:10px;height:10px;border-radius:50%;background:#64748b}} .on .dot{{background:#10b981;box-shadow:0 0 8px #10b981}}
  .tag{{margin-left:auto;background:#f59e0b;color:#111;font-size:11px;font-weight:700;padding:2px 8px;border-radius:99px}}
  .ip{{font-family:Consolas,monospace;font-size:20px;margin-top:8px;color:#38bdf8}}
  .mac{{font-family:Consolas,monospace;color:#64748b;font-size:13px}}
  .info{{color:#94a3b8;font-size:12px;margin-top:6px}}
  form{{margin:0}} .renombrar{{display:flex;gap:6px;margin-top:10px}}
  input{{flex:1;background:#0b1120;border:1px solid #334155;color:#e2e8f0;border-radius:8px;padding:6px 8px}}
  button{{background:#10b981;color:#022c22;border:0;border-radius:8px;padding:6px 12px;font-weight:700;cursor:pointer}}
  button.ok{{background:#f59e0b;margin-top:8px;width:100%}}
</style></head><body>
<header>
  <div class="radar"></div>
  <div><h1>Radar de mi red</h1><div class="sub">Red {e(estado['red'])} &middot; ultimo escaneo {e(estado['ultimo_escaneo'])}
    {' &middot; escaneando...' if estado['escaneando'] else ''}</div></div>
  <div class="stats"><div><b>{en_linea}</b>conectados</div><div><b>{len(lista)}</b>conocidos</div>
    <div class="n"><b>{nuevos}</b>nuevos</div></div>
</header>
<div class="barra"><form method="post" action="/escanear"><button>Escanear ahora</button></form>
  <span>La pagina se actualiza sola cada 30 s. Los apagados se ven transparentes.</span></div>
{aviso}
<div class="grid">{''.join(tarjetas) or '<p>Escaneando por primera vez, espera unos segundos...</p>'}</div>
</body></html>"""


class Servidor(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # que no llene la consola

    def responder(self, cuerpo):
        datos = cuerpo.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def regresar(self):
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    # --- Permisos para que camara.godsplan.site pueda hablar con este programa ---
    def cors(self):
        origen = self.headers.get("Origin", "")
        if origen in ORIGENES_PERMITIDOS:
            self.send_header("Access-Control-Allow-Origin", origen)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def responder_json(self, obj, codigo=200):
        datos = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/api/dispositivos"):
            with candado:
                lista = [dict(d, mac=mac, mac_privada=(mac != "ESTA-PC" and es_mac_privada(mac)))
                         for mac, d in estado["dispositivos"].items()]
                info = {"red": estado["red"], "ultimo_escaneo": estado["ultimo_escaneo"],
                        "escaneando": estado["escaneando"], "go2rtc": puerto_abierto(1984),
                        "dispositivos": lista}
            self.responder_json(info)
            return
        self.responder(pagina())

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        crudo = self.rfile.read(largo).decode("utf-8")

        # API para la pagina de internet (manda JSON)
        if self.path.startswith("/api/"):
            if self.headers.get("Origin", "") not in ORIGENES_PERMITIDOS:
                self.responder_json({"error": "origen no permitido"}, 403)
                return
            try:
                cuerpo = json.loads(crudo or "{}")
            except ValueError:
                cuerpo = {}
            mac = str(cuerpo.get("mac", ""))
            with candado:
                d = estado["dispositivos"].get(mac)
                if self.path == "/api/nombrar" and d is not None:
                    d["nombre"] = str(cuerpo.get("nombre", "")).strip()[:40]
                    d["nuevo"] = False
                    guardar()
                elif self.path == "/api/ok" and d is not None:
                    d["nuevo"] = False
                    guardar()
            if self.path == "/api/escanear":
                threading.Thread(target=escanear, daemon=True).start()
            self.responder_json({"ok": True})
            return

        # Formularios de la pagina local (http://localhost:8000)
        campos = parse_qs(crudo)
        mac = campos.get("mac", [""])[0]
        with candado:
            d = estado["dispositivos"].get(mac)
            if self.path == "/nombrar" and d is not None:
                d["nombre"] = campos.get("nombre", [""])[0].strip()[:40]
                d["nuevo"] = False
                guardar()
            elif self.path == "/ok" and d is not None:
                d["nuevo"] = False
                guardar()
        if self.path == "/escanear":
            threading.Thread(target=escanear, daemon=True).start()
        self.regresar()


def puerto_abierto(puerto):
    try:
        with socket.create_connection(("127.0.0.1", puerto), timeout=0.5):
            return True
    except OSError:
        return False


def iniciar_go2rtc():
    """Prende go2rtc escondido si esta en la misma carpeta y no esta corriendo ya."""
    if puerto_abierto(1984):
        print("  Camaras: go2rtc ya estaba prendido")
        return None
    exe = os.path.join(CARPETA, "go2rtc.exe" if ES_WINDOWS else "go2rtc")
    if not os.path.exists(exe):
        print("  Camaras: no encontre go2rtc.exe en esta carpeta (las camaras no se veran)")
        return None
    log = open(os.path.join(CARPETA, "go2rtc.log"), "a", encoding="utf-8")
    proceso = subprocess.Popen([exe], cwd=CARPETA, stdout=log, stderr=subprocess.STDOUT,
                               creationflags=SIN_VENTANA)
    print("  Camaras: go2rtc prendido")
    return proceso


def main():
    datos, _ = cargar()
    estado["dispositivos"] = datos
    print("=" * 50)
    print("  MI CASA")
    go2rtc = iniciar_go2rtc()
    threading.Thread(target=bucle, daemon=True).start()
    servidor = ThreadingHTTPServer(("127.0.0.1", PUERTO), Servidor)  # solo accesible desde esta PC
    print("  Red: escaneando cada minuto")
    print(f"  Abre {PAGINA}")
    print("  Deja esta ventana abierta. Para salir: cierrala o Ctrl + C")
    print("=" * 50)
    threading.Timer(2, lambda: webbrowser.open(PAGINA)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nApagando...")
    finally:
        if go2rtc is not None:
            go2rtc.terminate()
        print("Bye!")


if __name__ == "__main__":
    main()
