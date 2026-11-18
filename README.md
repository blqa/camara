# Cámaras · God's Plan

Panel web para ver las cámaras de casa: **https://camara.godsplan.site**

- **Cámara de cable** (192.168.100.4): video en vivo por RTSP a través de [go2rtc](https://github.com/AlexxIT/go2rtc), que corre en la PC de casa.
- **Cámara 2NLF**: solo funciona por su nube; el panel tiene un acceso a su visor web.

## Cómo funciona

La página es estática (GitHub Pages). El video no pasa por internet: el navegador se conecta a go2rtc en `http://localhost:1984`, y go2rtc se conecta a la cámara dentro de la red de casa.

## Instalar go2rtc (una vez)

1. Descarga `go2rtc_win64.zip` de https://github.com/AlexxIT/go2rtc/releases y descomprímelo en `C:\go2rtc`.
2. Copia `go2rtc.yaml.ejemplo` a `C:\go2rtc\go2rtc.yaml` y pon la contraseña de la cámara.
3. Abre `go2rtc.exe` y entra a https://camara.godsplan.site

La contraseña de la cámara **nunca** va en este repo.
