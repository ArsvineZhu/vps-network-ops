# 命令行工具

在仓库根目录执行。输入和输出中的客户端节点、认证信息和订阅链接应保存在受限目录。

```sh
uv run python skills/operate-vps-network/scripts/clash_profile.py /private/node.json /private/profile.yaml --policy /etc/vps-rules/rules.yaml
uv run python skills/operate-vps-network/scripts/new_member.py /private/server.json member /private/member --policy /etc/vps-rules/rules.yaml
uv run python skills/operate-vps-network/scripts/subscription_policy.py /private/profile.yaml --policy system/subscriptions/rules.yaml
```

`clash_profile.py` 生成 Mihomo 客户端配置；`new_member.py` 生成独立用户身份、客户端配置及服务端用户条目。完整配置使用 `--policy` 指定共享规则；仅生成节点提供者时无需规则。`subscription_policy.py` 将规则配置应用于现有订阅，保留节点及其选择组。各工具的参数可用 `--help` 查看。

节点描述格式见 `system/mihomo/server.example.json`。`new_member.py` 为新用户生成 UUID；`clash_profile.py` 使用已有用户的 UUID，需在输入中添加 `uuid` 字段。

`observed_usage.py` 从私有控制套接字或快照采样；`usage_daemon.py` 运行连续采集并提供报告。结果是近似观察值。`certificate_check.py` 检查证书有效期和主机名；`wait_listener.py` 等待服务监听；`vps_snapshot.sh` 读取主机网络与服务状态。
