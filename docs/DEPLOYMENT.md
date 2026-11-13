# 部署

以下配置面向 Ubuntu、systemd 和 IPv4 出口。准备一台可管理的服务器、指向服务器的域名、DNS-01 证书，以及独立的设备认证信息。安装官方 Mihomo、Caddy、Tailscale、UFW、nftables、iproute2、Python 和 PyYAML；版本以各项目当前发布及服务器环境为准。

## 构建指纹组件

在 Linux 开发环境中按 [开发指南](DEVELOPMENT.md) 安装工具并运行 `make build`。将 `build/mirage-syn`、`build/syn_rewrite.o` 和仓库源码传到服务器，然后以仓库根目录为当前目录安装：

```sh
sudo install -d -m 0755 /usr/local/lib/tcpfp /usr/local/lib/tcpfp/ebpf
sudo install -d -m 0700 /etc/tcpfp
sudo install -m 0755 build/mirage-syn /usr/local/lib/tcpfp/mirage-syn
sudo install -m 0644 build/syn_rewrite.o /usr/local/lib/tcpfp/ebpf/syn_rewrite.o
sudo install -m 0755 /path/to/mihomo /usr/local/lib/tcpfp/mihomo
sudo install -m 0755 system/tcpfp/network.py system/tcpfp/engines.py system/tcpfp/syn_capture.py system/tcpfp/syn_preflight.py /usr/local/lib/tcpfp/
sudo install -m 0700 system/tcpfp/network.sh /etc/tcpfp/network.sh
sudo install -m 0600 system/tcpfp/preflight.py system/tcpfp/fingerprint-engines.json system/tcpfp/syn-windows.json /etc/tcpfp/
```

用服务器的公网 IPv4 和出口网卡生成规则，将结果安装到 `/etc/tcpfp`：

```sh
python3 system/tcpfp/render_assets.py --public-ipv4 "$SERVER_IPV4" --wan "$WAN" --output /private/tcpfp-network
sudo install -m 0600 /private/tcpfp-network/host.nft /private/tcpfp-network/windows.nft /private/tcpfp-network/ios.nft /private/tcpfp-network/plan.json /etc/tcpfp/
```

根据 `system/tcpfp/backend.example.yaml` 分别创建 `/etc/tcpfp/windows.json` 与 `/etc/tcpfp/ios.json`。Windows 监听 `10.203.1.2:1080`，iPhone 监听 `10.203.2.2:1080`；各自使用独立 SOCKS 口令。后端文件归 root 所有，权限为 0600。

## 配置入口与防护

创建 `mihomo` 系统账户和工作目录，将官方 Mihomo 可执行文件安装为 `/usr/local/bin/mihomo`：

```sh
sudo useradd --system --user-group --home-dir /var/lib/mihomo --shell /usr/sbin/nologin mihomo
sudo install -d -o mihomo -g mihomo -m 0700 /var/lib/mihomo /var/lib/mihomo/controller
sudo install -d -m 0700 /etc/mihomo /etc/mihomo-observed
sudo install -m 0755 /path/to/mihomo /usr/local/bin/mihomo
```

参考 `system/mihomo/config.example.yaml` 创建 `/etc/mihomo/config.yaml`，填入订阅域名、服务器公网 IPv4、REALITY 密钥、设备 UUID、各协议口令和 SOCKS 后端口令。为不同设备及协议使用不同认证信息。

将 `system/mihomo/mihomo-guard.nft` 中的 `MIHOMO_UID`、`VPS_IPV4`、`LISTEN_PORT` 和 `SUBSCRIPTION_PORT` 替换为实际值，安装到 `/etc/nftables.d/mihomo-guard.nft`。确认 SSH 管理端口、VLESS TCP 8443、Hysteria2 UDP 8443、AnyTLS TCP 9444 和订阅 TCP 9443 的入站规则。启用 IPv4 转发，并使该设置在重启后生效。

通过 DNS-01 获取订阅域名证书。将 `system/mihomo/mihomo-tls.conf.in` 中的证书目录替换为实际目录，安装为 `mihomo.service` 的 drop-in；将 `renew-credential-refresh.sh.in` 的内容接入证书续期流程。参考 `system/caddy/Caddyfile.example` 配置 Caddy，并将订阅文件放在 `/srv/vps-subscriptions`。

安装规则配置、工具和服务单元，并在 `/etc/vps-rules/rules.yaml` 中设置订阅域名和 SSH 地址：

```sh
sudo install -d -m 0700 /etc/vps-rules
sudo install -m 0600 system/subscriptions/rules.yaml /etc/vps-rules/rules.yaml
sudo install -D -m 0755 skills/operate-vps-network/scripts/subscription_policy.py /usr/local/lib/vps-rules/subscription_policy.py
sudo install -D -m 0644 system/subscriptions/vps-rules.service /etc/systemd/system/vps-rules.service
sudo install -D -m 0644 system/subscriptions/vps-rules.path /etc/systemd/system/vps-rules.path
sudo systemctl daemon-reload
sudo systemctl start vps-rules.service
sudo systemctl enable --now vps-rules.path
```

规则和客户端更新方式见[订阅与规则](RULES.md)。

## 安装并启动服务

```sh
sudo install -D -m 0644 system/mihomo/mihomo.service /etc/systemd/system/mihomo.service
sudo install -D -m 0644 system/mihomo/mihomo-guard.service /etc/systemd/system/mihomo-guard.service
sudo install -D -m 0644 system/mihomo/mihomo-observed.service /etc/systemd/system/mihomo-observed.service
sudo install -D -m 0644 system/mihomo/mihomo-private-controller.conf /etc/systemd/system/mihomo.service.d/40-private-controller.conf
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-network.service /etc/systemd/system/tcpfp-network.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-windows-test.service /etc/systemd/system/tcpfp-windows-test.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-ios-test.service /etc/systemd/system/tcpfp-ios-test.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-syn-windows.service /etc/systemd/system/tcpfp-syn-windows.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-syn-capture-windows.service /etc/systemd/system/tcpfp-syn-capture-windows.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-windows-test.service.d/20-syn-capture.conf /etc/systemd/system/tcpfp-windows-test.service.d/20-syn-capture.conf
sudo install -d -m 0755 /usr/local/lib/mihomo-observed
sudo install -m 0755 skills/operate-vps-network/scripts/usage_daemon.py skills/operate-vps-network/scripts/observed_usage.py skills/operate-vps-network/scripts/check_socket_dir.py /usr/local/lib/mihomo-observed/
sudo install -m 0755 system/mihomo/vps-usage /usr/local/bin/vps-usage
```

按 `system/mihomo/collector.example.json` 创建 `/etc/mihomo-observed/collector.json`，设置实际监听名称和用户标签。

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-guard tcpfp-network
sudo systemctl enable --now tcpfp-syn-windows tcpfp-syn-capture-windows
sudo systemctl enable --now tcpfp-windows-test tcpfp-ios-test mihomo
sudo systemctl enable --now mihomo-observed caddy tailscaled
```

确认三个协议的认证、两个设备出口、UDP、订阅刷新和 SSH；服务检查命令见 [日常运维](OPERATIONS.md)。
