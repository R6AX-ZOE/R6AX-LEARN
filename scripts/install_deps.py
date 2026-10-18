#!/usr/bin/env python3
"""
安装项目依赖（仅使用预编译 wheel）。

在内存受限的设备上，pip 回退到源码构建大型依赖（如 Ruff 的 Rust 二进制）
会耗尽内存并导致安装失败。本脚本：

1. 用 --only-binary=:all: 安装运行依赖，绝不触发源码编译；
2. 同样以预编译 wheel 安装开发工具（pytest / mypy 等，失败仅告警）；
3. 若当前平台没有 Ruff 的预编译 wheel，自动下载 Ruff 官方预编译二进制。

用法:
    python scripts/install_deps.py
    python scripts/install_deps.py --runtime-only
    python scripts/install_deps.py --allow-sdist   # 旧行为，允许源码编译
"""

import argparse
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT_DIR / "pyproject.toml"
GITHUB_API = "https://api.github.com/repos/astral-sh/ruff/releases/latest"
GITHUB_RELEASE = "https://github.com/astral-sh/ruff/releases/download/{tag}/{asset}"
PYPI_RUFF = "https://pypi.org/pypi/ruff/json"
USER_AGENT = "r6ax-learn-installer"


def info(message):
    print(f"[deps] {message}", flush=True)


def warn(message):
    print(f"[warn] {message}", flush=True)


def fail(message):
    print(f"[error] {message}", file=sys.stderr, flush=True)
    sys.exit(1)


def run(cmd, env=None):
    info("$ " + " ".join(str(part) for part in cmd))
    return subprocess.call([str(part) for part in cmd], cwd=ROOT_DIR, env=env)


def pip(*args, binary_only=True):
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    env = os.environ.copy()
    if binary_only:
        cmd.append("--only-binary=:all:")
        env.pop("PIP_NO_BINARY", None)
        env["PIP_ONLY_BINARY"] = ":all:"
    cmd.extend(args)
    return run(cmd, env=env)


def dev_requirements():
    if not PYPROJECT.exists():
        return []
    try:
        data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn(f"Could not parse {PYPROJECT.name}: {exc}")
        return []
    return list(data.get("project", {}).get("optional-dependencies", {}).get("dev", []))


def _download(url, destination):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with (
        urllib.request.urlopen(request, timeout=60) as response,
        destination.open("wb") as output,
    ):
        shutil.copyfileobj(response, output, length=1 << 20)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checksum(checksum_url, archive):
    try:
        request = urllib.request.Request(
            checksum_url, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", "replace").strip()
    except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
        warn(f"Could not download checksum ({checksum_url}): {exc}")
        return False
    expected = text.split()[0].lower() if text else ""
    actual = _sha256(archive)
    if not expected or actual != expected:
        warn(f"Checksum mismatch for {archive.name}")
        return False
    return True


def _extract_ruff(archive, destination_dir):
    names = {"ruff", "ruff.exe"}
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if Path(name).name in names:
                    target = destination_dir / Path(name).name
                    with bundle.open(name) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    return target
    else:
        with tarfile.open(archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                if member.isfile() and Path(member.name).name in names:
                    source = bundle.extractfile(member)
                    if source is None:
                        continue
                    target = destination_dir / Path(member.name).name
                    with source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    return target
    return None


def _is_musl():
    if "musl" in platform.libc_ver()[0].lower():
        return True
    if Path("/etc/alpine-release").exists():
        return True
    try:
        return any(Path("/lib").glob("ld-musl-*.so.1"))
    except OSError as exc:
        warn(f"Could not inspect /lib for musl: {exc}")
        return False


def target_triple():
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "windows":
        if machine in {"amd64", "x86_64"}:
            return "x86_64-pc-windows-msvc"
        if machine in {"arm64", "aarch64"}:
            return "aarch64-pc-windows-msvc"
        if machine in {"x86", "i386", "i486", "i586", "i686"}:
            return "i686-pc-windows-msvc"
        return None

    if system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "aarch64-apple-darwin"
        if machine in {"x86_64", "amd64"}:
            return "x86_64-apple-darwin"
        return None

    if system == "linux":
        musl = _is_musl()
        if machine in {"x86_64", "amd64"}:
            arch = "x86_64"
        elif machine in {"aarch64", "arm64"}:
            arch = "aarch64"
        elif machine == "armv7l":
            return f"armv7-unknown-linux-{'musleabihf' if musl else 'gnueabihf'}"
        elif machine in {"armv6l", "arm"}:
            return "arm-unknown-linux-musleabihf"
        elif machine in {"x86", "i386", "i486", "i586", "i686"}:
            arch = "i686"
        elif machine in {"ppc64le", "powerpc64le"}:
            return "powerpc64le-unknown-linux-gnu"
        elif machine == "s390x":
            return "s390x-unknown-linux-gnu"
        elif machine in {"riscv64", "riscv64gc"}:
            return "riscv64gc-unknown-linux-gnu"
        else:
            return None
        return f"{arch}-unknown-linux-{'musl' if musl else 'gnu'}"

    return None


def latest_ruff_tag():
    try:
        request = urllib.request.Request(GITHUB_API, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["tag_name"]
    except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
        warn(f"Could not query GitHub for the latest Ruff release: {exc}")

    try:
        request = urllib.request.Request(PYPI_RUFF, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)["info"]["version"]
    except (OSError, ValueError, KeyError, http.client.HTTPException) as exc:
        warn(f"Could not query PyPI for the latest Ruff version: {exc}")
        return None


def download_standalone_ruff():
    triple = target_triple()
    if not triple:
        warn(f"No precompiled Ruff binary for {platform.system()} {platform.machine()}")
        return False

    tag = latest_ruff_tag()
    if not tag:
        return False

    archive_name = f"ruff-{triple}{'.zip' if os.name == 'nt' else '.tar.gz'}"
    url = GITHUB_RELEASE.format(tag=tag, asset=archive_name)

    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            archive = temp_path / archive_name
            info(f"Downloading precompiled Ruff {tag}: {url}")
            _download(url, archive)
            if not _verify_checksum(url + ".sha256", archive):
                return False
            binary = _extract_ruff(archive, temp_path)
            if binary is None:
                warn(f"{archive_name} does not contain a Ruff executable")
                return False

            scripts_dir = Path(sys.executable).parent
            destination = scripts_dir / ("ruff.exe" if os.name == "nt" else "ruff")
            shutil.copyfile(binary, destination)
            if os.name != "nt":
                destination.chmod(
                    destination.stat().st_mode
                    | stat.S_IXUSR
                    | stat.S_IXGRP
                    | stat.S_IXOTH
                )

            result = subprocess.run(
                [str(destination), "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                warn(f"Downloaded Ruff binary failed to run: {result.stderr.strip()}")
                return False
            info(f"Ruff installed from precompiled binary: {result.stdout.strip()}")
            return True
    except (
        OSError,
        ValueError,
        KeyError,
        EOFError,
        tarfile.TarError,
        zipfile.BadZipFile,
    ) as exc:
        warn(f"Failed to install the precompiled Ruff binary: {exc}")
        return False


def ruff_available():
    candidates = [
        Path(sys.executable).parent / ("ruff.exe" if os.name == "nt" else "ruff")
    ]
    found = shutil.which("ruff")
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        result = subprocess.run(
            [str(candidate), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            info(f"Ruff already available: {result.stdout.strip()}")
            return True
    return False


def install_ruff(requirement):
    if ruff_available():
        return True

    if pip(requirement) == 0:
        info("Ruff installed from a precompiled wheel")
        return True

    warn(
        "No precompiled Ruff wheel for this platform; falling back to the official binary"
    )
    if download_standalone_ruff():
        return True

    warn(
        "Ruff is unavailable on this platform; linting is optional, continuing without it"
    )
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Install project dependencies using precompiled wheels."
    )
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help="skip dev tools (pytest / ruff / mypy)",
    )
    parser.add_argument(
        "--allow-sdist",
        action="store_true",
        help="allow source builds (old behavior; may exhaust memory on constrained devices)",
    )
    args = parser.parse_args()

    if sys.prefix == sys.base_prefix:
        warn(
            "Not running inside a virtual environment; installing into the current Python"
        )

    info("Upgrading pip / setuptools / wheel (precompiled wheels only) ...")
    if pip("--upgrade", "pip", "setuptools", "wheel") != 0:
        warn("Failed to upgrade pip; continuing with the current version")

    if args.allow_sdist:
        warn("--allow-sdist enabled: source builds are allowed and may exhaust memory")
        if pip("-e", ".[dev]", binary_only=False) != 0:
            fail("Failed to install dependencies (source builds allowed)")
        return

    info("Installing runtime dependencies (precompiled wheels only) ...")
    if pip("-e", ".") != 0:
        fail(
            "No precompiled wheel is available for at least one runtime dependency.\n"
            "Retry with --allow-sdist on a device with enough memory / build toolchain,\n"
            "or install on a platform supported by precompiled wheels."
        )

    if args.runtime_only:
        info("Skipping dev tools (--runtime-only)")
        return

    dev = dev_requirements()
    ruff_requirements = [
        item for item in dev if re.match(r"^\s*ruff\b", item, re.IGNORECASE)
    ]
    dev_without_ruff = [item for item in dev if item not in ruff_requirements]

    if dev_without_ruff:
        info("Installing dev tools (precompiled wheels only) ...")
        if pip(*dev_without_ruff) != 0:
            warn(
                "Some dev tools have no precompiled wheel for this platform; skipping them"
            )

    if ruff_requirements:
        install_ruff(ruff_requirements[0])


if __name__ == "__main__":
    main()
