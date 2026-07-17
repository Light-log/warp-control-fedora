Name:           warp-control
Version:        2.0.0
Release:        1%{?dist}
Summary:        Desktop control panel for Cloudflare WARP

License:        MIT
URL:            https://github.com/robler/warp-control
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pytest
BuildRequires:  desktop-file-utils
BuildRequires:  appstream

Requires:       python3-gobject
Requires:       gtk3
Requires:       libayatana-appindicator-gtk3
Requires:       python3-idna
Requires:       polkit

%description
WARP Control is a GTK desktop control panel for Cloudflare WARP. It displays
connection state, manages split-tunnel exclusions, and provides a native tray
integration. Cloudflare WARP itself is offered separately with explicit user
confirmation; this package does not install it as a dependency.

%prep
%autosetup -p1

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files warp_control

install -Dpm 0644 data/com.robler.warpcontrol.desktop \
  %{buildroot}%{_datadir}/applications/com.robler.warpcontrol.desktop
install -Dpm 0644 data/com.robler.warpcontrol.metainfo.xml \
  %{buildroot}%{_metainfodir}/com.robler.warpcontrol.metainfo.xml
install -Dpm 0644 data/icons/com.robler.warpcontrol.svg \
  %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/com.robler.warpcontrol.svg
install -Dpm 0644 data/com.robler.warpcontrol.policy \
  %{buildroot}%{_datadir}/polkit-1/actions/com.robler.warpcontrol.policy
install -Dpm 0755 libexec/warp-control/install-warp \
  %{buildroot}%{_libexecdir}/warp-control/install-warp
install -Dpm 0755 libexec/warp-control/restart-warp \
  %{buildroot}%{_libexecdir}/warp-control/restart-warp

%check
%pytest -m "not ui"
desktop-file-validate \
  %{buildroot}%{_datadir}/applications/com.robler.warpcontrol.desktop
appstreamcli validate --no-net \
  %{buildroot}%{_metainfodir}/com.robler.warpcontrol.metainfo.xml

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/warp-control
%{_datadir}/applications/com.robler.warpcontrol.desktop
%{_metainfodir}/com.robler.warpcontrol.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/com.robler.warpcontrol.svg
%{_datadir}/polkit-1/actions/com.robler.warpcontrol.policy
%dir %{_libexecdir}/warp-control
%{_libexecdir}/warp-control/install-warp
%{_libexecdir}/warp-control/restart-warp

%changelog
* Fri Jul 17 2026 Carlos David Isturiz - 2.0.0-1
- Add the native Fedora reference package
