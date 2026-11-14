"""Native OpenSSH deployment with one streamed install session."""

import argparse
import getpass
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import cast

import yaml

from .config import load


def init(path):
    def ask(label, default=""):
        return input(label + (" [" + default + "]" if default else "") + ": ").strip() or default

    c = {
        "mode": ask("模式 tailscale / mihomo / both", "both"),
        "target": ask("SSH 目标（root@主机或 SSH 别名）"),
        "port": int(ask("初始 SSH 端口", "22")),
        "name": ask("新节点名称", "vps-node"),
        "public_key": ask("管理公钥文件（.pub）"),
        "identity": ask("对应私钥文件（安全密钥引用文件亦可）"),
    }
    if c["mode"] != "tailscale":
        c.update(
            domain=ask("订阅域名"),
            public_ipv4=ask("新节点公网 IPv4"),
            email=ask("ACME 邮箱"),
            dns_provider=ask(
                "DNS cloudflare / aliyun / dnspod / dnspod-token / dns_插件", "dnspod"
            ),
        )
        if c["dns_provider"].startswith("dns_"):
            c["dns_credentials"] = ask("凭据字段，逗号分隔").split(",")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        yaml.safe_dump(c, stream, allow_unicode=True)
    load(destination)
    print("私有节点配置已创建；Windows 请确认该目录 ACL 仅允许自己访问。")


def ssh(c, key_only=False):
    from vps_ops.transport import ssh_command

    return ssh_command(c["target"], port=c["port"], identity=c.get("identity"), key_only=key_only)


def bundle(c):
    root = Path(__file__).parent
    payload = io.BytesIO()
    temporary = None
    checkout = root.resolve().parents[2]
    if (checkout / "pyproject.toml").exists():
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(checkout / "build/deploy")],
            cwd=checkout,
            check=True,
            capture_output=True,
        )
        wheel = next((checkout / "build/deploy").glob("*.whl"))
    else:
        import tempfile
        import zipfile
        from importlib.metadata import distribution

        package = distribution("vps-network-ops")
        temporary = tempfile.TemporaryDirectory(prefix="vps-ops-wheel-")
        wheel = Path(temporary.name) / ("vps_network_ops-" + package.version + "-py3-none-any.whl")
        with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as output:
            for item in package.files or []:
                if ".." in item.parts or "__pycache__" in item.parts:
                    continue
                if item.parts[0] == "vps_ops" or item.parts[0].endswith(".dist-info"):
                    output.write(str(package.locate_file(item)), str(item).replace("\\", "/"))
    try:
        credentials = {}
        if c["mode"] != "tailscale":
            if c.get("credential_file"):
                credentials = json.loads(Path(c["credential_file"]).read_text(encoding="utf-8-sig"))
            for name in c["dns_names"]:
                if name not in credentials:
                    if not sys.stdin.isatty():
                        raise ValueError("非交互部署需要 credential_file 提供 DNS 凭据")
                    credentials[name] = getpass.getpass("DNS 凭据 " + name + ": ")
                if not isinstance(credentials[name], str) or not credentials[name]:
                    raise ValueError("DNS 凭据为空")
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            archive.add(wheel, arcname=wheel.name)
            for name in ("bootstrap.sh", "base.yaml", "apply.yaml", "preflight.py"):
                archive.add(root / name, arcname=name)
            for name, value in (("node.json", c), ("dns.json", credentials)):
                data = json.dumps(value).encode()
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(data))
        return payload.getvalue()
    finally:
        if temporary is not None:
            temporary.cleanup()


def apply(path):
    c = load(path)
    data = bundle(c)
    key_verified = False
    for _attempt in range(3):
        command = (
            "umask 077; mkdir -p /var/lib/vps-ops/deploy; "
            "exec 9>/var/lib/vps-ops/deploy.lock; "
            "flock -n 9 || { echo 'Another deployment is running'; exit 1; }; "
            "echo VPS_OPS_TRANSFER_READY; head -c "
            + str(len(data))
            + " | tar -xz -C /var/lib/vps-ops/deploy "
            "&& exec bash /var/lib/vps-ops/deploy/bootstrap.sh"
        )
        completed = False
        process = subprocess.Popen(
            ssh(c, key_only=key_verified) + [command], stdin=subprocess.PIPE, stdout=subprocess.PIPE
        )
        try:
            assert process.stdin is not None and process.stdout is not None
            while True:
                greeting = process.stdout.readline()
                if not greeting:
                    raise RuntimeError(
                        "SSH 登录或部署锁检查失败（退出码 " + str(process.wait()) + "）"
                    )
                line = greeting.decode(errors="replace").rstrip()
                if line == "VPS_OPS_TRANSFER_READY":
                    break
                print(line, flush=True)
            process.stdin.write(data)
            process.stdin.flush()
            for raw in process.stdout:
                line = raw.decode(errors="replace").rstrip()
                if line == "VPS_OPS_KEY_READY":
                    if not key_verified:
                        checked = subprocess.run(
                            ssh(c, True) + ["id -u"], capture_output=True, text=True
                        )
                        if checked.returncode or checked.stdout.strip() != "0":
                            raise RuntimeError("公钥 root 登录验证失败，保留密码认证")
                        key_verified = True
                    process.stdin.write(b"KEY_VERIFIED\n")
                    process.stdin.flush()
                elif line == "VPS_OPS_READY":
                    completed = True
                    import threading

                    def forward(pipe=process.stdin):
                        try:
                            for value in sys.stdin:
                                pipe.write(value.encode())
                                pipe.flush()
                        except (BrokenPipeError, OSError, ValueError):
                            pass
                        finally:
                            pipe.close()

                    threading.Thread(target=forward, daemon=True).start()
                    while chunk := cast(io.BufferedReader, process.stdout).read1(4096):
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    break
                else:
                    print(line, flush=True)
            code = process.wait()
        finally:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except (BrokenPipeError, OSError):
                    pass
            if process.poll() is None:
                process.terminate()
                process.wait()
        if completed:
            if code:
                print("部署已完成；SSH 管理会话已结束。")
            return
        if code != 42:
            if code:
                raise RuntimeError("部署失败；处理提示后用同一配置再次 apply")
            return
        print("节点正在重启，等待后继续。", flush=True)
        time.sleep(10)
        from vps_ops.transport import wait_ssh

        wait_ssh(ssh(c), 300)
    raise RuntimeError("节点持续要求重启，请检查系统更新")


def main(args, *, machine=False):
    p = argparse.ArgumentParser(
        prog="vps-ops deploy", description="初始化并部署全新 Ubuntu 24.04 AMD64 节点"
    )
    p.add_argument(
        "action",
        choices=["init", "apply", "show"],
        help="init 创建配置；apply 部署并保留登录；show 查看私有结果",
    )
    p.add_argument("config", help="init/apply 的私有 YAML 路径；show 使用 subscriptions")
    p.add_argument("--json", action="store_true", help="以 JSON 显示订阅地址")
    a = p.parse_args(args)
    if a.action == "init":
        init(a.config)
    elif a.action == "apply":
        apply(a.config)
    elif a.config == "subscriptions":
        from vps_ops.output import emit

        data = json.loads(Path("/etc/vps-ops/subscriptions.json").read_text())
        emit(data, machine or a.json, view="subscriptions")
    else:
        p.error("show 仅支持 subscriptions")
