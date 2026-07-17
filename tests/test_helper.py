import io
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from warp_control.commands import CommandResult
from warp_control.installers.detector import Architecture, Distribution, SystemInfo
from warp_control.privileged.helper import (
    InvocationRejected,
    InstallWarpHelper,
    RestartWarpHelper,
    validate_invocation,
)
from warp_control.privileged.repositories import (
    APT_PREFERENCES_CONTENT,
    APT_KEY_URL,
    RPM_REPOSITORY_URL,
    RepositoryRejected,
    repository_config,
    validate_rpm_repository,
    validate_signing_key,
    validate_apt_candidate,
)
from warp_control.privileged.runner import (
    ConcurrentExecution,
    JsonProgress,
    PrivilegedCommandRunner,
    exclusive_lock,
)


def system(distribution, version, codename=None, arch=Architecture.AMD64):
    return SystemInfo(distribution, version, codename, arch)


class CallbackRunner:
    def __init__(self, callback):
        self.callback = callback

    def run(self, argv, timeout=300):
        completed = self.callback(list(argv), timeout=timeout)
        if isinstance(completed, CommandResult):
            return completed
        return CommandResult(
            completed.returncode == 0,
            completed.stdout or "",
            completed.stderr or "",
            completed.returncode,
        )


@pytest.mark.parametrize("argv", [["install-warp", "extra"], [], ["restart-warp", "--force"]])
def test_helpers_reject_every_argument(argv):
    with pytest.raises(InvocationRejected):
        validate_invocation(argv, io.StringIO(""), euid=0)


def test_helpers_reject_nonempty_stdin_and_non_root():
    with pytest.raises(InvocationRejected, match="stdin"):
        validate_invocation(["install-warp"], io.StringIO("payload"), euid=0)
    with pytest.raises(InvocationRejected, match="root"):
        validate_invocation(["install-warp"], io.StringIO(""), euid=1000)


def test_privileged_runner_uses_fixed_environment_absolute_allowlist_and_no_shell():
    calls = []

    class Process:
        stdout = io.BytesIO(b"ok")
        stderr = io.BytesIO(b"")
        pid = 7

        def wait(self, timeout):
            return 0

    def fake_process(argv, **kwargs):
        calls.append((argv, kwargs))
        return Process()

    runner = PrivilegedCommandRunner(process_factory=fake_process)
    result = runner.run(["/usr/bin/systemctl", "enable", "--now", "warp-svc.service"])

    assert result.ok
    argv, options = calls[0]
    assert argv[0] == "/usr/bin/systemctl"
    assert options["shell"] is False
    assert options["env"] == {
        "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": "/root",
    }
    with pytest.raises(ValueError):
        runner.run(["systemctl", "restart", "warp-svc.service"])
    with pytest.raises(ValueError):
        runner.run(["/bin/sh", "-c", "id"])


class FakePopenProcess:
    def __init__(self, stdout=b"", stderr=b"", *, hangs=False):
        self.stdout = io.BytesIO(stdout)
        self.stderr = io.BytesIO(stderr)
        self.pid = 4242
        self.hangs = hangs
        self.killed = False

    def wait(self, timeout):
        if self.hangs and not self.killed:
            raise subprocess.TimeoutExpired("fake", timeout)
        return -9 if self.killed else 0

    def kill(self):
        self.killed = True


def test_privileged_popen_runner_bounds_output_and_starts_new_session():
    calls = []
    process = FakePopenProcess(stdout=b"x" * 128)

    def factory(argv, **options):
        calls.append((argv, options))
        return process

    killed = []
    runner = PrivilegedCommandRunner(
        process_factory=factory,
        output_limit=64,
        killpg=lambda pid, sig: (killed.append((pid, sig)), setattr(process, "killed", True)),
    )
    result = runner.run(["/usr/bin/systemctl", "restart", "warp-svc.service"])
    assert result.returncode == 125
    assert len(result.stdout.encode()) + len(result.stderr.encode()) <= 64
    assert killed and process.killed
    assert calls[0][1]["start_new_session"] is True
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["stdin"] is subprocess.DEVNULL


def test_privileged_popen_runner_kills_and_waits_process_group_on_deadline():
    process = FakePopenProcess(hangs=True)
    killed = []

    def kill_group(pid, sig):
        killed.append((pid, sig))
        process.killed = True

    runner = PrivilegedCommandRunner(
        process_factory=lambda argv, **options: process,
        killpg=kill_group,
    )
    result = runner.run(["/usr/bin/systemctl", "restart", "warp-svc.service"], timeout=1)
    assert result.returncode == 124
    assert killed == [(4242, 9)]
    assert process.killed is True


def test_exclusive_lock_rejects_concurrent_execution(tmp_path):
    lock = tmp_path / "install.lock"
    with exclusive_lock(lock):
        with pytest.raises(ConcurrentExecution):
            with exclusive_lock(lock):
                pass


def test_repository_configuration_is_closed_and_fail_closed():
    assert RPM_REPOSITORY_URL == "https://pkg.cloudflareclient.com/cloudflare-warp-ascii.repo"
    assert APT_KEY_URL == "https://pkg.cloudflareclient.com/pubkey.gpg"
    apt = repository_config(system(Distribution.UBUNTU, "24.04", "noble"))
    assert apt.source_line == (
        "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] "
        "https://pkg.cloudflareclient.com/ noble main\n"
    )
    with pytest.raises(RepositoryRejected):
        repository_config(system(Distribution.UBUNTU, "24.04", "jammy"))
    with pytest.raises(RepositoryRejected):
        repository_config(system(Distribution.ARCH, None))


def test_downloaded_rpm_repository_rejects_any_foreign_url():
    valid = (
        b"[cloudflare-warp-stable]\n"
        b"name=cloudflare-warp-stable\n"
        b"baseurl=https://pkg.cloudflareclient.com/rpm/$releasever\n"
        b"enabled=1\n"
        b"type=rpm\n"
        b"gpgcheck=1\n"
        b"gpgkey=https://pkg.cloudflareclient.com/pubkey.gpg\n"
    )
    validate_rpm_repository(valid)
    with pytest.raises(RepositoryRejected, match="unapproved"):
        validate_rpm_repository(
            b"[cloudflare-warp-stable]\n"
            b"name=cloudflare-warp-stable\n"
            b"baseurl=https://mirror.example/warp\n"
            b"enabled=1\n"
            b"type=rpm\n"
            b"gpgcheck=1\n"
            b"gpgkey=https://pkg.cloudflareclient.com/pubkey.gpg\n"
        )


def test_repository_internal_boundaries_reject_tampered_inputs_before_commands(tmp_path):
    calls = []
    helper = InstallWarpHelper(
        runner=CallbackRunner(lambda *args, **kwargs: calls.append(args)),
        detect=lambda: system(Distribution.FEDORA, "44"),
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
        rpm_repository=tmp_path / "repo",
        apt_keyring=tmp_path / "key",
        apt_source=tmp_path / "source",
    )
    with pytest.raises(RepositoryRejected):
        helper._install_rpm_repository(
            "https://pkg.cloudflareclient.com/evil", APT_KEY_URL
        )
    with pytest.raises(RepositoryRejected):
        helper._install_apt_repository("https://example.com/key", "deb evil\n")
    assert calls == []


def test_signing_key_requires_exact_primary_fingerprint_and_handles_subkeys():
    valid = (
        "pub:-:4096:1:6E2DD2174FA1C3BA:0:0::-:::scESC::::::23::0:\n"
        "fpr:::::::::C068A2B5771775193CBE1F2F6E2DD2174FA1C3BA:\n"
        "uid:-::::0::hash::Cloudflare Package Repository <support@cloudflare.com>::::::::::0:\n"
        "sub:-:4096:1:1111111111111111:0:0:::::e::::::23:\n"
        "fpr:::::::::AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA:\n"
    )
    validate_signing_key(valid)
    with pytest.raises(RepositoryRejected, match="fingerprint"):
        validate_signing_key(valid.replace("C068A2B5771775193CBE1F2F6E2DD2174FA1C3BA", "B" * 40))
    with pytest.raises(RepositoryRejected, match="primary"):
        validate_signing_key(valid + valid)


def test_json_progress_has_strict_small_schema():
    output = io.StringIO()
    progress = JsonProgress(output)
    progress.emit("repository", "running", "Configurando repositorio")
    payload = json.loads(output.getvalue())
    assert payload == {
        "stage": "repository",
        "status": "running",
        "message": "Configurando repositorio",
    }
    with pytest.raises(ValueError):
        progress.emit("unknown", "running", "x")
    with pytest.raises(ValueError):
        progress.emit("repository", "running", "x" * 5000)


def test_install_helper_never_runs_for_unsupported_system(tmp_path):
    calls = []
    runner = CallbackRunner(lambda *args, **kwargs: calls.append(args))
    helper = InstallWarpHelper(
        runner=runner,
        detect=lambda: system(Distribution.ARCH, None),
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
    )
    with pytest.raises(InvocationRejected, match="soportad"):
        helper.run()
    assert calls == []


@pytest.mark.parametrize(
    "unsupported",
    [
        system(Distribution.FEDORA, "42"),
        system(Distribution.FEDORA, "44", arch=Architecture.UNKNOWN),
        system(Distribution.DEBIAN, "11", "bullseye"),
        system(Distribution.RHEL, "8"),
    ],
)
def test_helper_rejects_unsupported_versions_and_architectures_before_commands(tmp_path, unsupported):
    calls = []
    helper = InstallWarpHelper(
        runner=CallbackRunner(lambda *args, **kwargs: calls.append(args)),
        detect=lambda: unsupported,
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
    )
    with pytest.raises(InvocationRejected):
        helper.run()
    assert calls == []


def _installing_runner(calls):
    def fake_run(argv, **kwargs):
        calls.append(tuple(argv))
        if argv[0] == "/usr/bin/curl":
            output = Path(argv[argv.index("--output") + 1])
            if argv[-1] == RPM_REPOSITORY_URL:
                output.write_bytes(
                    b"[cloudflare-warp-stable]\n"
                    b"name=cloudflare-warp-stable\n"
                    b"baseurl=https://pkg.cloudflareclient.com/rpm/$releasever\n"
                    b"enabled=1\n"
                    b"type=rpm\n"
                    b"gpgcheck=1\n"
                    b"gpgkey=https://pkg.cloudflareclient.com/pubkey.gpg\n"
                )
            else:
                output.write_bytes(b"-----BEGIN PGP PUBLIC KEY BLOCK-----\ntest\n")
        if argv[:4] == ["/usr/bin/gpg", "--batch", "--yes", "--no-options"]:
            output = Path(argv[argv.index("--output") + 1])
            output.write_bytes(b"binary-keyring")
        stdout = ""
        if "--show-keys" in argv:
            stdout = (
                "pub:-:4096:1:6E2DD2174FA1C3BA:0:0::-:::scESC::::::23::0:\n"
                "fpr:::::::::C068A2B5771775193CBE1F2F6E2DD2174FA1C3BA:\n"
                "uid:-::::0::hash::Cloudflare Package Repository <support@cloudflare.com>::::::::::0:\n"
            )
        if argv[:2] == ["/usr/bin/apt-cache", "policy"]:
            stdout = (
                "cloudflare-warp:\n  Installed: (none)\n  Candidate: 2026.1.1\n"
                "  Version table:\n     2026.1.1 1001\n"
                "        1001 https://pkg.cloudflareclient.com/ bookworm/main amd64 Packages\n"
            )
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    return fake_run


def test_fedora_helper_uses_only_official_repo_targeted_metadata_and_service(tmp_path):
    calls = []
    repository = tmp_path / "etc/yum.repos.d/cloudflare-warp.repo"
    helper = InstallWarpHelper(
        runner=CallbackRunner(_installing_runner(calls)),
        detect=lambda: system(Distribution.FEDORA, "44"),
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
        rpm_repository=repository,
        rpm_keyring=tmp_path / "keyrings/cloudflare.gpg",
    )
    helper.run()
    assert repository.is_file()
    assert "gpgkey=file:///usr/share/keyrings/cloudflare-warp-archive-keyring.gpg" in repository.read_text()
    assert (tmp_path / "keyrings/cloudflare.gpg").read_bytes() == b"binary-keyring"
    assert calls[-3:] == [
        ("/usr/bin/dnf", "-q", "makecache", "--repo", "cloudflare-warp-stable"),
        (
            "/usr/bin/dnf", "-y", "repository-packages",
            "cloudflare-warp-stable", "install", "cloudflare-warp",
        ),
        ("/usr/bin/systemctl", "enable", "--now", "warp-svc.service"),
    ]


def test_rhel_helper_performs_confirmed_epel_action_before_official_repo(tmp_path):
    calls = []
    helper = InstallWarpHelper(
        runner=CallbackRunner(_installing_runner(calls)),
        detect=lambda: system(Distribution.RHEL, "9"),
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
        rpm_repository=tmp_path / "repo",
        rpm_keyring=tmp_path / "key",
    )
    helper.run()
    assert calls[0] == ("/usr/bin/dnf", "-y", "install", "epel-release")


def test_debian_helper_verifies_and_dearmors_key_and_writes_signed_by_source(tmp_path):
    calls = []
    keyring = tmp_path / "keyrings/key.gpg"
    source = tmp_path / "sources/cloudflare.list"
    preferences = tmp_path / "preferences/cloudflare"
    helper = InstallWarpHelper(
        runner=CallbackRunner(_installing_runner(calls)),
        detect=lambda: system(Distribution.DEBIAN, "12", "bookworm"),
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
        apt_keyring=keyring,
        apt_source=source,
        apt_preferences=preferences,
    )
    helper.run()
    assert keyring.read_bytes() == b"binary-keyring"
    assert "signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg" in source.read_text()
    assert preferences.read_bytes() == APT_PREFERENCES_CONTENT
    assert any("--show-keys" in command and "--no-auto-key-retrieve" in command for command in calls)
    assert ("/usr/bin/apt-get", "update") in calls
    assert ("/usr/bin/apt-cache", "policy", "cloudflare-warp") in calls
    assert ("/usr/bin/apt-get", "install", "-y", "cloudflare-warp") in calls


def test_apt_candidate_parser_rejects_foreign_same_name_package():
    validate_apt_candidate(
        "cloudflare-warp:\n Candidate: 1\n  1 1001\n"
        "  1001 https://pkg.cloudflareclient.com/ noble/main amd64 Packages\n"
    )
    with pytest.raises(RepositoryRejected, match="approved origin"):
        validate_apt_candidate(
            "cloudflare-warp:\n Candidate: 99\n"
            "  99 1001\n  1001 https://mirror.example/ noble/main amd64 Packages\n"
        )

    with pytest.raises(RepositoryRejected, match="approved origin"):
        validate_apt_candidate(
            "cloudflare-warp:\n Candidate: 99\n"
            "  99 1001\n  1001 https://mirror.example/ noble/main amd64 Packages\n"
            "  1 1001\n  1001 https://pkg.cloudflareclient.com/ noble/main amd64 Packages\n"
        )


def test_restart_helper_is_purpose_only(tmp_path):
    calls = []

    def fake_run(argv, **kwargs):
        calls.append(tuple(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    helper = RestartWarpHelper(
        runner=CallbackRunner(fake_run),
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
        detect=lambda: system(Distribution.FEDORA, "44"),
    )
    helper.run()
    assert calls == [("/usr/bin/systemctl", "restart", "warp-svc.service")]


@pytest.mark.parametrize(
    "unsupported",
    [system(Distribution.ARCH, None), system(Distribution.UNKNOWN, None), system(Distribution.FEDORA, "42")],
)
def test_restart_helper_rejects_unsupported_system_before_systemctl(tmp_path, unsupported):
    calls = []
    helper = RestartWarpHelper(
        runner=CallbackRunner(lambda *args, **kwargs: calls.append(args)),
        progress=JsonProgress(io.StringIO()),
        lock_path=tmp_path / "lock",
        detect=lambda: unsupported,
    )
    with pytest.raises(InvocationRejected):
        helper.run()
    assert calls == []


def test_libexec_entrypoints_are_fixed_and_argument_free():
    root = Path(__file__).parents[1]
    install = (root / "libexec/warp-control/install-warp").read_text()
    restart = (root / "libexec/warp-control/restart-warp").read_text()
    assert "install_main" in install
    assert "restart_main" in restart
    assert "eval " not in install + restart


def test_policy_grants_only_two_exact_helpers_without_cached_authorization():
    root = Path(__file__).parents[1]
    policy = ET.parse(root / "data/com.robler.warpcontrol.policy").getroot()
    actions = policy.findall("action")
    assert {action.attrib["id"] for action in actions} == {
        "com.robler.warpcontrol.install-warp",
        "com.robler.warpcontrol.restart-warp",
    }
    assert {
        action.find("./annotate[@key='org.freedesktop.policykit.exec.path']").text
        for action in actions
    } == {
        "/usr/libexec/warp-control/install-warp",
        "/usr/libexec/warp-control/restart-warp",
    }
    assert all(action.find("./defaults/allow_active").text == "auth_admin" for action in actions)
    assert "auth_admin_keep" not in (root / "data/com.robler.warpcontrol.policy").read_text()
