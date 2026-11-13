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
- [运维 Skill](skills/operate-vps-network/SKILL.md)

开发环境需要 Python、uv、Go、Node.js、clang、libbpf、ShellCheck、shfmt 和 Caddy。在 Linux 或 WSL 中安装依赖后：

```sh
uv sync --locked
npm ci
make check
```

配置文件、订阅链接、密钥、证书和真实连接数据不要放入仓库。服务的监听端口、防火墙和认证方式以服务器实际配置为准。
