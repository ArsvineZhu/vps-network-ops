# 订阅与规则

服务器通过 HTTPS 同时提供客户端订阅和规则资源。规则资源由 Caddy 转发至 MetaCubeX、VPSDance、ACL4SSR 和 Loyalsoldier；客户端按规则提供者的更新周期获取最新内容。当前策略区分 OpenAI、Anthropic、Google AI、Grok、编程工具、游戏、流媒体、开发服务、国内站点和广告。

## 自动设备识别与网络接管

统一订阅始终包含 Windows 和 Apple 两套身份，每套都有 VLESS、Hysteria2、AnyTLS，共六个可选节点。更新时，设备识别只调整 `Nodes` 组的默认选中项；用户可随时手动切换身份和协议，TCP 出口随实际选中节点的认证身份变化。

- 检测到 `Darwin`、`iPhone`、`iPad`、`Macintosh`、`Mac OS X` 或 `CFNetwork`：默认选择 `Apple · VLESS`。即使 UA 同时包含 `clash-verge/` 或 Windows 标识，也按 Apple 处理。
- 未出现 Apple 标识，且检测到 `Windows`、`Win64` 或 `clash-verge/`：默认选择 `Windows · VLESS`。
- 未识别设备：仍返回全部节点，初始默认选择 `Windows · VLESS`，可手动修改。不会拒绝订阅更新。

Clash Verge Rev 的通用 UA `clash-verge/v...` 用作当前 Windows 客户端的默认提示；若在 macOS 上使用相同 UA，可设置带 `Darwin` 的订阅下载 UA，或手动选择 Apple 节点。User-Agent 只影响默认项；订阅令牌授权读取两套身份的凭据。不同订阅持有者应使用独立令牌和独立认证身份。离线 `member create` 仍只生成待注册的单身份材料，注册、发布及双身份分配由服务器管理者完成。

统一 URL 使用 `/s/auto/<令牌>.yaml`。设备变体 `.Windows.yaml`、`.Apple.yaml` 只在服务器内部使用。响应设置 `Cache-Control: no-store` 与 `Vary: User-Agent`。原有链接继续可用，也包含两套身份，其默认节点按原设备身份设置；设备自动识别使用统一地址。

`GLOBAL` 组把 `Nodes` 放在第一项。客户端可能保留上次手动选择；更新订阅后应核对 `Nodes` 的实际选中项，生成配置中的默认值不强制覆盖客户端保存的选择。

客户端 DNS 使用 Fake IP，并通过 `Nodes` 访问 Cloudflare DoH；代理入口采用固定 IPv4。识别为 Windows 时使用 `mixed` TUN 栈、自动路由、严格路由和端口 53 DNS 劫持。Apple 和未识别设备使用通用 TUN 配置，Apple 上的 VPN 接管由客户端 Network Extension 管理。TUN 字段是否生效还取决于客户端是否启用 VPN/TUN，以及客户端的覆写设置。

`check dns` 检查 VPS 网络空间的解析。客户端 DNS 泄露需在设备启用 VPN/TUN 后复测，同时观察端口 53、IPv6 和应用自带 DoH/DoT 的流量路径。UDP 经选中的代理协议进入 VPS 后按服务端规则直接出站；HTTP/3 是否可用需另外确认客户端 UDP 接管与目标 QUIC 握手。

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
