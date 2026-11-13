# VPS Network Ops

个人 VPS 的网络配置、TCP 指纹组件和日常运维工具。服务使用 Mihomo 提供 VLESS、Hysteria2 和 AnyTLS；设备身份决定 TCP 出口，UDP 按规则直接出站。Caddy 提供 HTTPS 订阅，Tailscale 提供独立的管理与组网通道。

Windows 指纹出口使用 NFQUEUE，iPhone 指纹出口使用 tc/eBPF。两者分别运行在独立网络空间内。服务配置和凭据保存在服务器，仓库只提供源码、服务定义和不含秘密的示例。

- [代码与文件索引](INDEX.md)
- [系统架构](docs/ARCHITECTURE.md)
- [部署指南](docs/DEPLOYMENT.md)
- [日常运维](docs/OPERATIONS.md)
- [订阅与规则](docs/RULES.md)
- [开发与检查](docs/DEVELOPMENT.md)
- [网络资料](docs/materials/NETWORK.md)
- [运维 Skill](.agents/skills/operate-vps-network/SKILL.md)

## 使用运维工具

新服务器可从出厂 Ubuntu 24.04 AMD64 开始部署，选择仅 Tailscale、仅 Mihomo 或两者都装：

```powershell
uv sync --locked
uv run vps-ops deploy init C:/private/node.yaml
uv run vps-ops deploy apply C:/private/node.yaml
```

配置字段、DNSPod 凭据准备、首次授权和部署结果见[新节点部署](docs/DEPLOYMENT.md)。

本机需要 Python 3.12+、uv 和 OpenSSH。在仓库根目录运行：

```powershell
uv sync --locked
uv run vps-ops connect root@203.0.113.10 --port 23899
```

将示例 IP 和端口换成自己的 SSH 目标。服务器须已安装 CLI，见[安装统一 CLI](docs/DEPLOYMENT.md)。登录后出现 `vps-ops>`，连续输入：

```text
status
check
usage report
```

`status` 查看系统和服务，`check` 验证实际代理出口、协议入口、DNS 和订阅，`usage report` 查看累计观察用量。后续命令复用当前登录，输入 `exit` 退出。在服务器普通终端直接使用 `vps-ops status` 等命令。

[CLI 使用手册](.agents/skills/operate-vps-network/scripts/USAGE.md) 提供连接参数、服务器配置、全部子命令、输入文件示例和故障处理；[日常运维](docs/OPERATIONS.md) 提供更新、重启、恢复与配置修改步骤。

## 开发

开发环境另需 Go、Node.js、clang、libbpf、ShellCheck、shfmt 和 Caddy。在 Linux 或 WSL 中安装依赖后：

```sh
uv sync --locked
npm ci
make check
```

配置文件、订阅链接、密钥、证书和真实连接数据不要放入仓库。服务的监听端口、防火墙和认证方式以服务器实际配置为准。
