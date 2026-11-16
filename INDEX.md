# 仓库索引

| 位置                                                        | 内容                                           |
| ----------------------------------------------------------- | ---------------------------------------------- |
| `system/tcpfp/mirage-syn/`                                  | NFQUEUE SYN 处理进程和 Go 测试                 |
| `system/tcpfp/ebpf/`                                        | tc/eBPF SYN 处理程序                           |
| `system/tcpfp/network.py`、`network.sh`                     | 网络空间、路由与防护启动                       |
| `system/tcpfp/engines.py`                                   | 每个设备出口的指纹引擎配置                     |
| `system/tcpfp/syn_capture.py`、`syn_preflight.py`           | 队列捕获规则及出口检查                         |
| `system/tcpfp/*.nft.in`、`render_assets.py`                 | 防护规则和网络配置生成                         |
| `system/tcpfp/systemd/`                                     | 指纹网络和后端服务单元                         |
| `system/mihomo/`                                            | Mihomo、防护、统计与证书的配置示例和服务单元   |
| `system/caddy/`                                             | HTTPS 订阅服务配置示例                         |
| `system/subscriptions/rules.yaml`                           | 订阅的策略组、规则源及匹配顺序                 |
| `src/vps_ops/capabilities.py`、`deploy/`                    | 能力选择、部署向导、依赖安装与服务生成         |
| `src/vps_ops/forwarding.py`、`wireguard.py`                 | 三层转发、指纹队列、WireGuard 身份与配置       |
| `src/vps_ops/exit_profiles.py`、`identity.py`、`devices.py` | 出口配置、物理设备注册表、独立订阅与热更新     |
| `src/vps_ops/`                                              | 统一部署与运维 CLI、客户端配置、订阅策略和用量 |
| `experiments/tcp-rtt/`                                      | TCP RTT 真实链路采集、隔离 ACK 与三层出口实验  |
| `tests/`                                                    | Python 行为测试                                |
| `docs/`                                                     | 架构、部署、运维、开发和网络资料               |

`AGENTS.md` 是仓库级 Agent 指引；格式、静态检查和构建入口在 `Makefile` 与各语言配置文件中。

CLI 参数与交互输入位于 `src/vps_ops/arguments.py`、`prompts.py`，调用入口位于 `cli.py`，文本与 JSON 展示位于 `output.py`。同目录其余业务模块负责采集、检查、生成和维护，返回数据供入口使用。
