# 日常运维

## 服务状态

```sh
systemctl status mihomo mihomo-guard caddy tailscaled mihomo-observed
systemctl status tcpfp-network tcpfp-windows-test tcpfp-ios-test
systemctl status tcpfp-syn-windows tcpfp-syn-capture-windows
ip netns exec tcpfp-windows-test /usr/local/lib/tcpfp/mirage-syn check -c /etc/tcpfp/syn-windows.json
ip netns exec tcpfp-windows-test python3 /usr/local/lib/tcpfp/syn_capture.py check --config /etc/tcpfp/syn-windows.json
journalctl -u tcpfp-syn-windows -f
```

Windows 队列日志显示改写、跳过和丢包计数。检查 iPhone 的过滤器可运行 `ip netns exec tcpfp-ios-test tc filter show dev e0 egress`。诊断服务器可运行 `sudo bash skills/operate-vps-network/scripts/vps_snapshot.sh`，输出包含网络地址和服务状态。

## 用户和客户端

Mihomo 入口配置位于 `/etc/mihomo/config.yaml`。为每个设备使用独立认证信息，并在 TCP 出口规则之前处理该设备的 UDP 规则。客户端配置可用 `clash_profile.py` 和 `new_member.py` 生成；参数见[工具说明](../skills/operate-vps-network/scripts/USAGE.md)。

修改入口配置后，运行 `/usr/local/bin/mihomo -t -d /var/lib/mihomo -f /etc/mihomo/config.yaml`，再重启 `mihomo` 并从对应客户端连接。订阅文件由 Caddy 从 `/srv/vps-subscriptions` 提供；订阅地址本身包含访问凭据。

规则源、策略组和更新方式见[订阅与规则](RULES.md)。

## 证书与用量

订阅和 TLS 证书由 acme.sh 的 DNS-01 流程维护。`mihomo.service` 的凭据配置指向证书目录，证书更新后重启 Mihomo 以读取新凭据。可用 `certificate_check.py` 检查证书主机名和有效期。

`mihomo-observed.service` 从 `/var/lib/mihomo/controller/control.sock` 采样。使用服务器安装的 `vps-usage` 命令查看统计；结果是采样期间观察到的近似用量，不用于计费。
