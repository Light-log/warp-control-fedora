# Instalación

WARP Control se distribuye como paquete nativo. Instálalo con el gestor de tu
distribución; el bootstrap opcional solo instala un archivo local que ya hayas
revisado. No descarga WARP ni añade repositorios por su cuenta.

## Fedora y RHEL compatibles

Construye el RPM desde una copia limpia del repositorio:

```bash
scripts/build-source-tarball.sh
rpmbuild -ba packaging/rpm/warp-control.spec \
  --define "_sourcedir $(pwd)/dist" \
  --define "_topdir $(pwd)/packaging/rpm"
sudo dnf install packaging/rpm/RPMS/noarch/warp-control-2.0.0-1.noarch.rpm
```

Como alternativa, si ya tienes un RPM en `dist/`, el bootstrap detecta la
familia y te muestra el comando antes de solicitar confirmación:

```bash
scripts/install.sh --package dist/warp-control-2.0.0-1.noarch.rpm
```

## Debian y Ubuntu

Instala las dependencias de compilación y construye el paquete:

```bash
sudo apt-get install build-essential debhelper dh-python pybuild-plugin-pyproject \
  python3-all python3-setuptools python3-wheel python3-pytest python3-idna \
  python3-gi gir1.2-gtk-3.0 desktop-file-utils appstream
dpkg-buildpackage -us -uc -b
sudo apt-get install ../warp-control_2.0.0-1_all.deb
```

O utiliza `scripts/install.sh --package ../warp-control_2.0.0-1_all.deb` para
una confirmación previa equivalente.

## Arch Linux (experimental)

Revisa y construye el PKGBUILD local:

```bash
cd packaging/arch
makepkg -si
```

El PKGBUILD fija un commit completo del repositorio para que la fuente sea
reproducible. Cloudflare no ofrece aquí un flujo oficial equivalente: instala
`warp-cli` desde una fuente comunitaria que revises por separado. WARP Control
no automatiza AUR ni ejecuta un helper privilegiado en Arch.

## Primer inicio de Cloudflare WARP

Al iniciar la aplicación, si `warp-cli` no existe:

1. Se informa qué repositorio oficial se usaría y por qué.
2. Puedes cancelar sin cambios o confirmar la instalación.
3. La elevación se solicita por PolicyKit y el helper valida el origen y la
   clave antes de invocar el gestor de paquetes.

Después, registra el cliente si Cloudflare lo solicita y conéctalo desde la
ventana. Para conocer las distribuciones de WARP oficialmente soportadas, lee
[SUPPORT.md](SUPPORT.md).

## Desinstalar

Desinstalar WARP Control no elimina la configuración de Cloudflare ni el
cliente WARP:

```bash
sudo dnf remove warp-control      # Fedora/RHEL
sudo apt-get remove warp-control  # Debian/Ubuntu
sudo pacman -R warp-control       # Arch
```
