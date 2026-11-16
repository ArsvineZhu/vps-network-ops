# VPS Network Ops

从全新 Ubuntu 24.04 AMD64 开始部署和维护个人 VPS。向导可选择 Tailscale、Clash（Mihomo）或两者，同时独立选择 TCP 指纹与完整 TCP 链路（RTT）能力。系统更新、SSH 加固、防火墙、证书续期、每设备独立订阅和累计用量共用一个运维入口。

Clash 保留 VLESS、Hysteria2、AnyTLS；开启完整 TCP 链路（RTT）时额外安装独立 WireGuard 服务，并在每个设备的订阅中默认选择 WireGuard 节点，无需 Tailscale 账户。Tailscale 提供原生三层出口和管理通道。设备身份、证书、订阅与凭据保留在服务器，仓库提供源码、服务定义和不含秘密的示例。

- [代码与文件索引](INDEX.md)
- [系统架构](docs/ARCHITECTURE.md)
- [部署指南](docs/DEPLOYMENT.md)
- [日常运维](docs/OPERATIONS.md)
- [订阅与规则](docs/RULES.md)
- [开发与检查](docs/DEVELOPMENT.md)
- [网络资料](docs/materials/NETWORK.md)
- [运维 Skill](.agents/skills/operate-vps-network/SKILL.md)

## 使用运维工具

新服务器可从出厂 Ubuntu 24.04 AMD64 开始部署。向导默认选择 Clash（Mihomo），同时启用指纹和完整 TCP 链路（WireGuard），无需 Tailscale 账户；也可选择仅 Tailscale 或两者都装：

```powershell
uv run vps-ops deploy setup C:/private/node.yaml
```

先安装 uv 与 OpenSSH，并准备 root SSH、公钥；Clash 另需域名和 DNS API 凭据。向导保存选择后立即部署，也可用 `deploy init`、`deploy plan`、`deploy apply` 分别保存、查看和执行。以后修改能力可再次运行同一条 `deploy setup`，或用 `deploy configure` 只保存改选；无需编辑 YAML。向导会登记第一台设备；部署后在管理会话执行 `device list`、`device show 名称或ID` 获取该设备的私有订阅。第二台设备通过 `device add` 登记，各自保留独立链接与凭据。准备细节、凭据和客户端导入见[新节点部署](docs/DEPLOYMENT.md)。

本机需要 uv 和 OpenSSH；uv 会自动准备 Python，无需预先安装。在仓库根目录运行：

```powershell
uv sync --locked
uv run vps-ops connect root@203.0.113.10 --port 23899
```

将示例 IP 和端口换成自己的 SSH 目标。服务器须已安装 CLI，见[部署指南](docs/DEPLOYMENT.md)。登录后出现 `vps-ops>`，连续输入：

```text
status
check
usage report
```

`status` 显示系统和服务概览；`status --all` 查看完整状态，`status --service mihomo` 单独查看一个服务。`check` 验证代理出口、协议入口、DNS 和订阅，`usage report` 查看累计观察用量。后续命令复用当前登录，输入 `exit` 退出。在服务器普通终端直接使用 `vps-ops status` 等命令。

[CLI 使用手册](docs/USAGE.md) 提供连接参数、服务器配置、全部子命令、输入文件示例和故障处理；[日常运维](docs/OPERATIONS.md) 提供更新、重启、恢复与配置修改步骤。

## 开发

开发环境另需 Go、Node.js、clang、libbpf、ShellCheck、shfmt 和 Caddy。在 Linux 或 WSL 中安装依赖后：

```sh
uv sync --locked
npm ci
make check
```

配置文件、订阅链接、密钥、证书和真实连接数据不要放入仓库。服务的监听端口、防火墙和认证方式以服务器实际配置为准。

## 许可证

本项目原创代码采用 [MIT 许可证](LICENSE)。[SYN 队列处理进程](system/tcpfp/mirage-syn/README.md)包含 GPL-3.0 代码；[eBPF 程序](system/tcpfp/ebpf/syn_rewrite.c)采用 GPL-2.0-only，各自保留原许可。
