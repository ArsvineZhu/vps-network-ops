---
name: operate-vps-network
description: 维护个人 VPS 的 Mihomo、TCP 指纹出口、Tailscale、HTTPS 订阅、证书和用量统计；诊断客户端与服务器连接。
---

# VPS 网络运维

根据用户任务读取实际配置和服务状态，复用现有 SSH 管理连接。配置与订阅包含凭据，不写入仓库、聊天或日志。

常规运维使用统一 `vps-ops` 入口，先运行 `status`、`check`，再按故障范围查询日志或执行维护。已有普通 SSH 会话时在其中调用命令。`connect` 进入的 CLI 会话只接受子命令，需要编辑文件时使用普通 SSH 管理终端。

全新 Ubuntu 24.04 AMD64 节点使用 `deploy setup` 向导，或分开运行 `deploy init`、`deploy plan` 和 `deploy apply`。新建向导默认 mihomo，加指纹与 WireGuard 完整链路，无需 Tailscale 账户；已有配置默认保留原选择。可选择 tailscale、mihomo 或 both，并独立选择 features.fingerprint 与 features.rtt；依赖由能力模型统一决定。Clash 开启 rtt 时自动安装独立 WireGuard 服务，每台设备的独立订阅包含十二个节点并默认 WireGuard，无需 Tailscale。Tailscale 原生转发保留设备 TCP 延迟。DNSPod 默认选择腾讯云 API 插件，旧 Token 使用 dnspod-token；所有服务商共用 acme.sh。仅 Tailscale 无需域名与 DNS 凭据。Tailscale 初始登录有 5 秒等待上限，等待网页授权时保留 SSH 与 CLI，会报告 pending/warning，已就绪的 Clash/WireGuard 继续可用；授权及出口批准后执行 check tailscale，无需重新部署。首次 Clash 向导登记首台物理设备；管理会话用 device add/list/show/revoke 登记、取私有链接和撤销，每个设备均提供可同时用的 Default/Windows/Apple 三套出口配置。UA 仅调整默认，未知 UA 回退登记出口。撤销清除三协议认证和连接、WG peers、订阅文件，保留历史累计；device sync 恢复已保存的运行态变更。WG 健康检查只读取配置/握手，禁止用设备私钥启动服务端探针。初始化细节和凭据准备见部署指南，维护时按配置中的 mode 与 features 检查已启用能力。已有选择使用 `deploy configure` 向导修改，或再次 `deploy setup` 改选并立即部署；保留 SSH、域名、邮箱与凭据路径作为默认。修改后 apply 会停用淘汰服务和对应公网规则，保留身份、密钥、证书、订阅和用量。

- 组件和数据路径：[系统架构](../../../docs/ARCHITECTURE.md)
- 安装与配置：[部署指南](../../../docs/DEPLOYMENT.md)
- 服务、订阅、证书和统计：[日常运维](../../../docs/OPERATIONS.md)
- 订阅策略与规则更新：[订阅与规则](../../../docs/RULES.md)
- 命令行工具：[工具说明](../../../docs/USAGE.md)
- 开发工具与检查：[开发指南](../../../docs/DEVELOPMENT.md)
- 协议和网络机制：[网络资料](../../../docs/materials/NETWORK.md)

服务配置改动后使用已安装版本的 Mihomo 检查配置，并通过对应客户端和目标路径确认结果。
