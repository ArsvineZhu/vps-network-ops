---
name: operate-vps-network
description: 维护个人 VPS 的 Mihomo、TCP 指纹出口、Tailscale、HTTPS 订阅、证书和用量统计；诊断客户端与服务器连接。
---

# VPS 网络运维

根据用户任务读取实际配置和服务状态，复用现有 SSH 管理连接。配置与订阅包含凭据，不写入仓库、聊天或日志。

常规运维使用统一 `vps-ops` 入口，先运行 `status`、`check`，再按故障范围查询日志或执行维护。已有普通 SSH 会话时在其中调用命令。`connect` 进入的 CLI 会话只接受子命令，需要编辑文件时使用普通 SSH 管理终端。

- 组件和数据路径：[系统架构](../../docs/ARCHITECTURE.md)
- 安装与配置：[部署指南](../../docs/DEPLOYMENT.md)
- 服务、订阅、证书和统计：[日常运维](../../docs/OPERATIONS.md)
- 订阅策略与规则更新：[订阅与规则](../../docs/RULES.md)
- 命令行工具：[工具说明](scripts/USAGE.md)
- 开发工具与检查：[开发指南](../../docs/DEVELOPMENT.md)
- 协议和网络机制：[网络资料](../../docs/materials/NETWORK.md)

服务配置改动后使用已安装版本的 Mihomo 检查配置，并通过对应客户端和目标路径确认结果。
