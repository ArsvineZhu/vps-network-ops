---
name: operate-vps-network
description: 维护个人 Ubuntu VPS 的 SSH、安全更新、Tailscale 出口节点及 mihomo VLESS REALITY 服务；生成 Clash 客户端配置，维护 DNS-01 证书与 HTTPS 订阅、观测熟人用量，并诊断公网端口、代理链路和泄露问题。适用于新主机统一部署、VLESS/可选HY2/AnyTLS配置、维护、迁移及连接故障排查。
---

# VPS 网络运维

以用户当前可用连接为基础，完成部署、维护或排障。把服务端配置、客户端实际加载状态和公网路径分别验证；最终以用户要使用的路径完成真实请求。

## 开始工作

1. 确认本次目标和当前可用的管理通道，读取现有版本、监听、服务状态与规则。把用户已有证据先用起来。
2. 记录本次路径：客户端 → Tailscale 出口或 REALITY 节点 → 目标网站。特别注明 Tailscale 是否开启、Clash 模式、系统代理、TUN 和实际节点端口。
3. 选择下列一份参考，按需要继续读取。示例参数必须替换为当前实例值；历史端口不是部署默认值。
4. 先做只读诊断。修改前明确范围、影响和恢复方法，遵守当前环境的批准要求。Skill 和历史批准都不替代本次操作权限。

## 统一系统和重建

仓库完整使用时，先读 [统一系统入口](../../system/README.md) 和 [迁移清单](../../docs/migration.md)。配置模型、协议身份、订阅、防护和服务由 `system/build.py` 同源生成，秘密与输出放在仓库外。Ansible 仅适用于经批准的新主机；不要对已有机器直接运行以覆盖正在进行的维护。

单独安装此 Skill 时上述仓库相对路径可能不存在。完整重建需要整个仓库，不能只复制 Skill；原有单项诊断工具仍可独立使用。

## 按任务读取

- 按设备 TCP 模板方案、候选和已做回环实验：[tcp-solution.md](references/tcp-solution.md)
- 全过程复盘与改进顺序：[retrospective.md](references/retrospective.md)
- MTU、TCP 指纹、CDN 路径及实验矩阵：[network-research.md](references/network-research.md)

- 日常检查、更新窗口、续期及交接：[maintenance.md](references/maintenance.md)
- 新机器、更新与 SSH 加固：[bootstrap.md](references/bootstrap.md)
- Tailscale 组网和出口：[tailscale.md](references/tailscale.md)
- 空VPS完整mihomo部署模板：[fresh-mihomo.md](references/fresh-mihomo.md)
- REALITY 服务、端口迁移与 Clash 配置：[mihomo-clash.md](references/mihomo-clash.md)
- 熟人独立凭据、规则与估算用量：[sharing-usage.md](references/sharing-usage.md)
- DNS-01证书与HTTPS订阅发布：[dns01-subscription.md](references/dns01-subscription.md)
- 超时、监听、指纹、泄露：[troubleshooting.md](references/troubleshooting.md)
- 本次部署的事实、踩坑与待办：[deployment-record.md](references/deployment-record.md)
- 官方资料索引：[sources.md](references/sources.md)

`scripts/` 提供可重复工具。运行前先查看具体工具的 `--help` 和依赖；优先使用只读命令和离线生成器。客户端配置与订阅含访问凭据，按密钥文件保护，输出摘要只显示非敏感状态。脚本不能把修改服务器、上传订阅或外部探测混进默认诊断。

## 执行准则

- 保留可用 SSH 会话。变更认证方式前，用新会话证明新方式能登录；再关闭旧方式。
- 防火墙变更只动明确归属的规则。先建可验证的独立恢复机制，再执行可能中断管理连接的操作。记录并取消过期清理计时器，避免它删除新生产规则。
- 配置写入前备份，完成语法校验后应用；以实际监听和请求成功判断就绪。systemd 的 active 不等于应用端口已就绪。
- 生成配置不会自动改变运行内核。核对选中的配置源、生成文件与实际内核；订阅刷新可能覆盖手工改动。
- 某次测试成功，只宣称它验证的路径。经同一 VPS 的 Tailscale 出口访问该 VPS 公网地址，可能在 VPS 本机回环。
- 工具连接失效与用户断网分开描述。遇到限制就保留已完成结果，继续可行的独立工作；不要换路线绕过访问限制。
- 对用户一次给一个明确动作，批量收集相关只读结果。长命令优先交付脚本文件；需要粘贴时用完整代码块，避免反复重跑整段迁移。

## 交付与完成

交付本次更改、验证路径、尚未验证事项、备份与恢复方法。涉及生产节点时补齐：服务自启、防护启动顺序、客户端配置来源和端口、凭据保管位置。排障结束后清理临时监听、放行规则、进程和敏感临时文件；日志只保留诊断所需内容。
