# 资料与证据索引

部署前核对安装版本对应文档，尤其旧版本与主分支字段差异。

- OpenAI Skills：https://developers.openai.com/codex/skills/
- OpenAI skill-creator：https://github.com/openai/skills/tree/main/skills/.system/skill-creator
- Tailscale Linux kernel/userspace：https://tailscale.com/docs/reference/kernel-vs-userspace-routers
- Tailscale exit nodes：https://tailscale.com/kb/1103/exit-nodes
- mihomo VLESS：https://wiki.metacubex.one/config/proxies/vless/
- mihomo TUN：https://wiki.metacubex.one/config/inbound/tun/
- mihomo direct：https://wiki.metacubex.one/config/proxies/direct/
- Clash Verge Rev源码：https://github.com/clash-verge-rev/clash-verge-rev
- UFW说明：https://manpages.ubuntu.com/manpages/noble/man8/ufw.8.html
- nftables链语义：https://wiki.nftables.org/wiki-nftables/index.php/Configuring_chains
- Linux网络参数：https://docs.kernel.org/networking/ip-sysctl.html
- Check-Host API：https://check-host.net/about/api
- curl错误码：https://curl.se/libcurl/c/libcurl-errors.html
- WebRTC IP处理RFC：https://www.rfc-editor.org/rfc/rfc8828.html

本Skill按渐进披露组织：入口只放决策流程，具体作业放references，可重复机械操作放scripts。脚本语法通过只证明可解析，仍需离线测试和真实路径验收；任何真实部署另需授权。

- 固定版本服务端 REALITY schema：https://github.com/MetaCubeX/mihomo/blob/v1.19.33/listener/inbound/reality.go
- 官方规则示例：https://github.com/MetaCubeX/Meta-Docs/blob/main/docs/example/conf.en.md
- MRS规则仓库：https://github.com/MetaCubeX/meta-rules-dat （使用时核对版本、当前许可及更新影响；本包不复制规则本体）

## DNS-01与证书部署

- Let's Encrypt验证方式：https://letsencrypt.org/docs/challenge-types/
- Caddy TLS配置：https://caddyserver.com/docs/caddyfile/directives/tls
- Caddy官方安装：https://caddyserver.com/docs/install
- Tencent acme.sh DNS示例：https://cloud.tencent.cn/document/product/302/105900
- DNSPod CAM资源类型：https://docs.dnspod.cn/dns/cam-resource-type/
- Tencent CAM操作/资源：https://intl.cloud.tencent.com/zh/document/product/598/57108
- 固定版dns_tencent实现：https://github.com/acmesh-official/acme.sh/blob/3.1.6/dnsapi/dns_tencent.sh
- 固定版签名者：https://github.com/acmesh-official/acme.sh/blob/3.1.6/allowed_signers

上述资料用于解释机制；生产完成状态以deployment-record记录的实际证据为准。

## 私有用量采集实现依据

- Unix控制器权限与认证：https://github.com/MetaCubeX/mihomo/blob/v1.19.33/hub/route/server.go
- 当前连接接口：https://github.com/MetaCubeX/mihomo/blob/v1.19.33/hub/route/connections.go
- 空闲null与连接生命周期：https://github.com/MetaCubeX/mihomo/blob/v1.19.33/tunnel/statistic/manager.go
- 连接ID及计数：https://github.com/MetaCubeX/mihomo/blob/v1.19.33/tunnel/statistic/tracker.go


## TCP 方案调查与实验（2026-11-12）

[tcp-solution.md](tcp-solution.md)记录官方 Mihomo IN-USER 的实际回环验证，以及固定提交的 SkyProxy 和 flash-relay 源码审阅。源码能说明设计及风险，不证明完整模板已部署；本轮唯一新增运行证据是回环身份分流和 TTL，TCP options 没有变成设备模板。第三方模块没有装入测试环境或生产。

## 本轮复盘和网络研究（2026-11-11）

完整的结论与链接放在[网络研究](network-research.md)、[搭建复盘](retrospective.md)以及对应操作参考，避免把资料结论混入生产验收。使用三类证据：

1. **官方文档与固定版本源码：**解释实现和字段；最新文档的默认值不自动适用于旧核心。重点包括 Tailscale 内核/netstack、Mihomo v1.19.33 DNS dialer、Cloudflare Anycast、Caddy reload 和 Let's Encrypt 到期邮件政策。
2. **第三方研究与社区案例：**JA4T、DNS/CDN 测量论文和 issue 可提供机制/假设。不同版本、地域和测试条件不能直接证明当前 VPS 有同一问题。
3. **实际观测：**用户设备、VPS、独立云浏览器分别记录。站点给出的风险分、OS 标签、“无泄露”或“就近”判定是该站解释，不是服务商官方认证；隐私声明也未做独立审计。

本轮 Cloudflare、DNS 页的新测量来自独立云环境；用户真实客户端的三路指纹和完整 PMTU 对照仍未完成。官方资料读到、脚本测试通过、历史用户反馈、实际生产验收四者不互相替代。
