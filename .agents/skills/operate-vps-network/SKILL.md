---
name: operate-vps-network
description: 维护个人 VPS 的 Mihomo、TCP 指纹出口、Tailscale、HTTPS 订阅、证书和用量统计；诊断客户端与服务器连接。
---

# VPS 网络运维

根据用户任务读取实际配置和服务状态，复用现有 SSH 管理连接。配置与订阅包含凭据，不写入仓库、聊天或日志。

常规运维使用统一 `vps-ops` 入口，先运行 `status`、`check`，再按故障范围查询日志或执行维护。已有普通 SSH 会话时在其中调用命令。`connect` 进入的 CLI 会话只接受子命令，需要编辑文件时使用普通 SSH 管理终端。

全新 Ubuntu 24.04 AMD64 节点使用 `deploy init` 和 `deploy apply`，选择 tailscale、mihomo 或 both。DNSPod 默认选择腾讯云 API 插件，旧 Token 使用 dnspod-token；所有服务商共用 acme.sh。仅 Tailscale 无需域名与 DNS 凭据。初始化细节和凭据准备见部署指南，维护时按配置中的模式检查已启用能力。

- 组件和数据路径：[系统架构](../../../docs/ARCHITECTURE.md)
- 安装与配置：[部署指南](../../../docs/DEPLOYMENT.md)
- 服务、订阅、证书和统计：[日常运维](../../../docs/OPERATIONS.md)
- 订阅策略与规则更新：[订阅与规则](../../../docs/RULES.md)
- 命令行工具：[工具说明](scripts/USAGE.md)
- 开发工具与检查：[开发指南](../../../docs/DEVELOPMENT.md)
- 协议和网络机制：[网络资料](../../../docs/materials/NETWORK.md)

服务配置改动后使用已安装版本的 Mihomo 检查配置，并通过对应客户端和目标路径确认结果。
