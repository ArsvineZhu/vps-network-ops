# 订阅与规则

服务器通过 HTTPS 同时提供客户端订阅和规则资源。规则资源由 Caddy 转发至 MetaCubeX、VPSDance、ACL4SSR 和 Loyalsoldier；客户端按规则提供者的更新周期获取最新内容。当前策略区分 OpenAI、Anthropic、Google AI、Grok、编程工具、游戏、流媒体、开发服务、国内站点和广告。

## 设备目标与网络接管

部署时为 `win` 和 `Apple` 分别生成订阅；两者使用各自已有的入口认证凭据，对应服务端独立的 TCP 指纹出口。名称用于标识目标，实际路由身份由认证信息决定。每份订阅只包含该身份的 VLESS、Hysteria2 与 AnyTLS 节点，并将 VLESS 设为默认选择。

主选择组为 `节点`，`GLOBAL` 组默认指向它。切换到全局模式时也使用目标身份；首次导入时按对应身份初始化；如果客户端已经记住旧的策略组选择，重载后仍可能使用其缓存结果，应在客户端确认一次。手动选择的协议不应因重启而被强制重置。

客户端 DNS 默认采用 Fake IP，并通过 `节点` 访问 Cloudflare DoH；代理入口使用固定 IPv4，因此正常连接无需从本地解析节点域名。节点改为域名时，`proxy-server-nameserver` 用于独立引导解析，不等同于普通目标域名的解析出口。

Windows 订阅启用 TUN 自动路由、严格路由和 53 端口 DNS 劫持。Apple 订阅启用 TUN 标志，实际 VPN 接管由 iOS 客户端的 Network Extension 管理。普通 DoH/DoT 应用流量不会被端口 53 劫持自动解密，是否走代理仍要以连接日志核查。

## 调整规则

`/etc/vps-rules/rules.yaml` 是服务器的规则配置。`base-url` 是订阅服务地址；`variables` 设置服务器 IPv4 和 SSH 端口；`hosts` 指定订阅域名解析；`proxy-groups`、`rule-providers` 和 `rules` 分别决定策略组、规则源和匹配顺序。HTTP 规则使用 `/rules/` 下的服务器地址，`interval` 的单位是秒。

保存配置后，`vps-rules.path` 会触发 `vps-rules.service`，将策略应用到 `/srv/vps-subscriptions/` 中的所有 YAML 订阅。也可以手动更新：

```sh
sudo systemctl start vps-rules.service
systemctl status vps-rules.path vps-rules.service
```

该命令保留订阅中的节点及节点选择组。客户端刷新订阅后接收策略组和规则顺序；规则源内容按提供者的更新周期刷新。添加其他上游仓库时，还需在 Caddy 的 `@rule_resources` 匹配器中允许对应路径，再重载 Caddy。

规则从上往下匹配。SSH 管理连接与 OpenAI 的指定域名优先处理，之后拦截广告和处理 Anthropic；UDP 使用节点选择组。其他服务依次进入对应策略组，国内站点默认直连，未命中流量使用节点选择组。Anthropic 组默认阻断，可在客户端切换到代理或仅 TCP 直连。游戏下载、Steam、游戏和其他服务均有独立策略组。

## 客户端更新

Windows 的 Clash Verge Rev 使用远程订阅并将自动更新间隔设为 24 小时。iPhone 的 Clash 在配置列表中通过订阅链接添加配置，在客户端设置中启用配置和资源的自动更新；本地文件导入的配置需要手动更新。iPhone 上的按进程规则受系统限制，应使用域名和 IP 规则。

订阅链接包含访问凭据，只发送给自己的设备。规则文件本身是公开规则数据；客户端通过服务器获取时，上游看到服务器的请求。
