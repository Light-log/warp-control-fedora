Name:           warp-control
Version:        2.0.0
Release:        1%{?dist}
Summary:        Desktop control panel for Cloudflare WARP

License:        MIT
URL:            https://github.com/Light-log/warp-control-fedora
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch
BuildRequires:  python3-devel
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-pytest
BuildRequires:  python3-pyyaml
BuildRequires:  python3-gobject
BuildRequires:  gtk3
BuildRequires:  python3-idna
BuildRequires:  desktop-file-utils
BuildRequires:  appstream

Requires:       python3-gobject
Requires:       gtk3
Requires:       libayatana-appindicator-gtk3
Requires:       python3-idna
Requires:       polkit
Requires:       /usr/bin/curl
Requires:       /usr/bin/dnf
Requires:       /usr/bin/gpg
Requires:       /usr/bin/systemctl

%description
WARP Control is a GTK desktop control panel for Cloudflare WARP. It displays
connection state, manages split-tunnel exclusions, and provides a native tray
integration. Cloudflare WARP itself is offered separately with explicit user
confirmation; this package does not install it as a dependency.

%prep
%autosetup -p1

%generate_buildrequires
%if 0%{?rhel} != 9
%pyproject_buildrequires
%endif

%build
%if 0%{?rhel} == 9
%{python3} setup.py build
%else
%pyproject_wheel
%endif

%install
%if 0%{?rhel} == 9
%{python3} setup.py install --skip-build --root %{buildroot}
%else
%pyproject_install
%pyproject_save_files warp_control
%endif

install -Dpm 0644 data/com.devruby.warpcontrol.desktop \
  %{buildroot}%{_datadir}/applications/com.devruby.warpcontrol.desktop
install -Dpm 0644 data/com.devruby.warpcontrol.metainfo.xml \
  %{buildroot}%{_metainfodir}/com.devruby.warpcontrol.metainfo.xml
install -Dpm 0644 data/icons/com.devruby.warpcontrol.svg \
  %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/com.devruby.warpcontrol.svg
install -Dpm 0644 data/com.devruby.warpcontrol.policy \
  %{buildroot}%{_datadir}/polkit-1/actions/com.devruby.warpcontrol.policy
install -Dpm 0755 libexec/warp-control/install-warp \
  %{buildroot}%{_libexecdir}/warp-control/install-warp
install -Dpm 0755 libexec/warp-control/restart-warp \
  %{buildroot}%{_libexecdir}/warp-control/restart-warp

%check
%pytest -m "not ui" tests/test_*.py tests/installers tests/services tests/ui
desktop-file-validate \
  %{buildroot}%{_datadir}/applications/com.devruby.warpcontrol.desktop
appstreamcli validate --no-net \
  %{buildroot}%{_metainfodir}/com.devruby.warpcontrol.metainfo.xml

%if 0%{?rhel} == 9
%files
%{python3_sitelib}/warp_control/
%{python3_sitelib}/warp_control-*.egg-info/
%else
%files -f %{pyproject_files}
%endif
%license LICENSE
%doc README.md
%{_bindir}/warp-control
%{_datadir}/applications/com.devruby.warpcontrol.desktop
%{_metainfodir}/com.devruby.warpcontrol.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/com.devruby.warpcontrol.svg
%{_datadir}/polkit-1/actions/com.devruby.warpcontrol.policy
%dir %{_libexecdir}/warp-control
%{_libexecdir}/warp-control/install-warp
%{_libexecdir}/warp-control/restart-warp

%changelog
* Fri Jul 17 2026 Carlos David Isturiz - 2.0.0-1
- Add the native Fedora reference package
