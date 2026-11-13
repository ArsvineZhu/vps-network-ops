# 订阅与规则

服务器通过 HTTPS 同时提供客户端订阅和规则资源。规则资源由 Caddy 转发至 MetaCubeX、VPSDance、ACL4SSR 和 Loyalsoldier；客户端按规则提供者的更新周期获取最新内容。当前策略区分 OpenAI、Anthropic、Google AI、Grok、编程工具、游戏、流媒体、开发服务、国内站点和广告。

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
