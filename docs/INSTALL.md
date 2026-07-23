# Instalación en Linux

Cada release publica paquetes nativos y AppImages. Descarga también
`SHA256SUMS`. El comando siguiente valida el manifiesto completo, así que debes
conservar los 13 artefactos en el mismo directorio:

```bash
sha256sum -c SHA256SUMS
```

Si descargaste un solo artefacto, selecciona únicamente su entrada. Por
ejemplo, para el AppImage `x86_64`:

```bash
grep ' WARP-Control-2.0.0-x86_64.AppImage$' SHA256SUMS | sha256sum -c -
```

WARP Control no incluye Cloudflare WARP, no modifica repositorios de terceros
durante la instalación del paquete y no descarga WARP sin confirmación. Los
nombres siguientes son el contrato exacto de la release 2.0.0.

## RPM: Fedora y Enterprise Linux

Descarga exactamente el RPM de tu sistema:

- `warp-control-2.0.0-1.fc43.noarch.rpm`
- `warp-control-2.0.0-1.fc44.noarch.rpm`
- `warp-control-2.0.0-1.el9.noarch.rpm`
- `warp-control-2.0.0-1.el10.noarch.rpm`

Después instala el archivo local, por ejemplo:

```bash
sudo dnf install ./warp-control-2.0.0-1.fc44.noarch.rpm
```

### Construir el RPM localmente

Construye el RPM desde una copia limpia del repositorio:

```bash
scripts/build-source-tarball.sh
rpmbuild -ba packaging/rpm/warp-control.spec \
  --define "_sourcedir $(pwd)/dist" \
  --define "_topdir $(pwd)/packaging/rpm"
sudo dnf install packaging/rpm/RPMS/noarch/warp-control-2.0.0-1*.noarch.rpm
```

El bootstrap también detecta la familia y muestra el comando antes de solicitar
confirmación:

```bash
scripts/install.sh --package packaging/rpm/RPMS/noarch/warp-control-2.0.0-1*.noarch.rpm
```

## DEB: Debian y Ubuntu

La release contiene un DEB construido y probado por cada destino:

- `warp-control_2.0.0-1_all-ubuntu2204.deb`
- `warp-control_2.0.0-1_all-ubuntu2404.deb`
- `warp-control_2.0.0-1_all-ubuntu2604.deb`
- `warp-control_2.0.0-1_all-debian12.deb`
- `warp-control_2.0.0-1_all-debian13.deb`

Instala el que coincide con tu versión, por ejemplo:

```bash
sudo apt-get install ./warp-control_2.0.0-1_all-ubuntu2404.deb
```

### Construir el DEB localmente

Instala las dependencias de compilación y construye el paquete:

```bash
sudo apt-get install build-essential debhelper dh-python pybuild-plugin-pyproject \
  python3-all python3-setuptools python3-wheel python3-pytest python3-yaml python3-idna \
  python3-gi gir1.2-gtk-3.0 desktop-file-utils appstream
dpkg-buildpackage -us -uc -b
sudo apt-get install ../warp-control_2.0.0-1_all.deb
```

También puedes utilizar
`scripts/install.sh --package ./warp-control_2.0.0-1_all-ubuntu2404.deb` para
una confirmación previa equivalente.

## Arch Linux (experimental)

El artefacto publicado es `warp-control-2.0.0-1-any.pkg.tar.zst`:

```bash
sudo pacman -U ./warp-control-2.0.0-1-any.pkg.tar.zst
```

Para construirlo tú mismo, revisa el PKGBUILD local:

```bash
cd packaging/arch
makepkg -si
```

El PKGBUILD usa el tarball versionado de la release y fija su SHA-256 para que la
fuente sea reproducible. Cloudflare no ofrece aquí un flujo oficial equivalente:
instala `warp-cli` desde una fuente comunitaria que revises por separado. WARP
Control no automatiza AUR ni ejecuta un helper privilegiado en Arch.

## AppImage portátil

La release publica ambos nombres de arquitectura:

- `WARP-Control-2.0.0-x86_64.AppImage`
- `WARP-Control-2.0.0-aarch64.AppImage`

Elige el que coincide con `uname -m`. Puedes ejecutarlo sin instalarlo:

```bash
chmod +x ./WARP-Control-2.0.0-x86_64.AppImage
./WARP-Control-2.0.0-x86_64.AppImage
```

Para integrarlo en el menú de aplicaciones sin privilegios, utiliza el
instalador local desde un checkout del repositorio o desde el tarball fuente;
copiará el AppImage a `~/.local` y conservará tu configuración:

```bash
scripts/install.sh --package ./WARP-Control-2.0.0-x86_64.AppImage
```

El AppImage incluye Python, GTK y PyGObject. Necesita un escritorio Linux con
glibc y la arquitectura correspondiente; no incluye `warp-cli` ni `warp-svc`.
La fuente reproducible de la release se publica como
`warp-control-2.0.0.tar.gz`.

## Primer inicio de Cloudflare WARP

Al iniciar la aplicación en un destino RPM/APT oficialmente cubierto, si
`warp-cli` no existe:

1. Se informa qué repositorio oficial se usaría y por qué.
2. Puedes cancelar sin cambios o confirmar la instalación.
3. La elevación se solicita por PolicyKit y el helper valida el origen y la
   clave antes de invocar el gestor de paquetes.

En Arch o al usar el AppImage fuera de esas familias, la aplicación no intenta
instalar WARP: muestra instrucciones separadas y permite reintentar la detección
después de que lo prepares por tu cuenta.

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
