# 订阅与规则

服务器通过 HTTPS 同时提供客户端订阅和规则资源。规则资源由 Caddy 转发至 MetaCubeX、VPSDance、ACL4SSR 和 Loyalsoldier；客户端按规则提供者的更新周期获取最新内容。当前策略区分 OpenAI、Anthropic、Google AI、Grok、编程工具、游戏、流媒体、开发服务、国内站点和广告。

## 自动设备识别与网络接管

一名拥有两种设备身份的订阅持有者只需要一个随机 HTTPS 订阅地址。更新时 Caddy 根据请求的 `User-Agent` 在已生成的 `WIN`、`Apple` 配置中选择；**服务端认证身份和出口路由由选中的配置决定**，不是靠客户端自定义标签。

- Apple：检测到 `Darwin`、`iPhone`、`iPad`、`Macintosh`、`Mac OS X` 或 `CFNetwork`，返回 Apple 认证信息及其 tc/eBPF TCP 出口。
- WIN：检测到 `Windows`、`Win64` 或 `clash-verge/`，返回 WIN 认证信息及其 NFQUEUE TCP 出口。
- 既未匹配也无法可靠判断时，返回 HTTP 406，不默默使用错误身份。设备专用旧订阅 URL 仍按原身份提供静态文件，不受此判断影响。

Clash for Apple 默认的下载身份可能包含 `Darwin/...` 和硬件型号；Clash Verge Rev 默认只报告 `clash-verge/v...`，**并不能凭这个 UA 单独证明运行在 Windows**。在当前仅使用 WIN 上的 Clash Verge Rev 的设备组合中可将其用于默认分发；若以后在 Mac 上使用 Clash Verge Rev，需要配置能够报告平台的下载请求头，或扩展判断方式。User-Agent 可以被修改，不能作为身份认证或安全边界；持有统一订阅 URL 就相当于有权获得两套设备凭据。一个普通新成员仍需要先注册对应的服务器身份，不能凭一个尚未注册的 UUID 自动产生两个 TCP 指纹出口。

统一 URL 只暴露随机令牌，实际文件后缀 `.WIN.yaml` / `.Apple.yaml` 不在 Caddy 可直接请求的 URL 匹配范围内。响应设置 `Cache-Control: no-store` 与 `Vary: User-Agent`，避免共享缓存把一台设备的配置发给另一台设备。

主选择组名为 `节点`，其默认项为当前设备的 VLESS；`GLOBAL` 组把 `节点` 放在第一项。客户端保留原有手动切换协议的选择状态，因此旧客户端若记录了其他组选择，首次导入统一订阅后应核对实际选中节点。

客户端 DNS 默认采用 Fake IP，并通过 `节点` 访问 Cloudflare DoH；代理入口使用固定 IPv4，不需要先从本地解析代理域名。WIN 订阅启用 TUN 自动路由、严格路由和端口 53 DNS 劫持；Apple 订阅启用 TUN 标志，实际 VPN 接管由其 Network Extension 管理。第三方应用独立使用的 DoH/DoT 流量需要单独观察连接日志，端口 53 的 DNS 劫持不会自动解密这些连接。

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
