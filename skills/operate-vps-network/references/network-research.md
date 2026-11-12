# MTU、TCP 指纹与 CDN：研究及实验记录

研究日期：2026-11-11。本轮只做资料核对、既有证据复盘和允许的独立实验，不调整服务器现有服务。下列方案没有自动执行；网络环境、客户端模式和协议未确认的结果，不能作为用户真实线路的结论。

## 后续进展：2026-11-12

针对可落地方法的进一步研究已完成[每设备凭据分流与出口模板方案](tcp-solution.md)。真实回环实验验证 20/20 身份分流与 TTL 选择，但 TCP options 仍是 Linux；SkyProxy/flash-relay 没有加载，完整 Windows/iOS 模板仍待独立 VM 和外网对照。下文 2026-11-11 的资料与云浏览器结果保留原时间边界，不能与新的回环实验合并成现网验收。

## 结论先行

1. **1400 只是历史试验值。** Tailscale 的接口 MTU、Windows Mihomo 的 TUN MTU、VPS 出口链路 MTU、远端推断值是不同对象。先查路径与实际值，再讨论是否有大包黑洞或性能收益。
2. **TCP 标签首先由谁创建目标连接决定。** Linux 内核 Tailscale 出口转发客户端 TCP；userspace/netstack 和 VPS 上的 VLESS 代理会终止并重建 TCP。把 Tailscale 换回内核模式，不会改变另一条 VLESS 链路的出口 TCP 栈。
3. **REALITY 的 `client-fingerprint` 调整外层 TLS ClientHello。** 它不把 VPS 发往目标网站的 TCP 栈变成 Windows，也不等于改写浏览器与目标站之间的内层 TLS。
4. **CDN 问题要先定对象。** 测试网站选到较远边缘、DNS 解析位置、Tailscale 中继、给自己的订阅加 CDN 是不同问题，不能用同一个“绕路”结论代替证据。
5. **优先补功能和可靠性验收。** 规则实际命中、friend 外网认证、续期通知与重启恢复，比改检测站标签更直接。生产 TCP 改写没有部署，也不建议直接尝试一键 eBPF/NFQUEUE 脚本。

## 1. 把不同路径画清楚

| 路径 | 目标网站的 TCP 由谁建立 | 网站观测的解释 |
| --- | --- | --- |
| 终端直接访问 | 终端操作系统 | 可作为同一设备基线，仍可能有中间设备影响。 |
| 终端 → Linux 内核 Tailscale 出口 → 网站 | 终端建立，出口转发/NAT | 更接近终端的 TCP 特征，但 TTL、MSS 等可能被路径改动；不能保证网站必定识别成某个系统。 |
| 终端 → userspace/netstack Tailscale 出口 → 网站 | 出口端重新建立 | 原始终端 TCP 不再端到端保留，不能与内核路径混称。 |
| 浏览器 → 本机 Mihomo → REALITY/VLESS → VPS → 网站 | VPS 代理出站使用的栈 | Linux 类标签可以是正常代理结果；即使客户端是 Windows、TUN 使用 system 栈，也不会改变 VPS 出站属于另一条 TCP。 |

依据：[Tailscale 内核与 userspace 对照](https://tailscale.com/docs/reference/kernel-vs-userspace-routers)、[Mihomo TLS 配置](https://wiki.metacubex.one/config/proxies/tls/)。这些原理不等于已重新核实当前设备状态。

## 2. MTU 与 MSS

- MTU 是一个接口或路径可以承载的 IP 包大小；MSS 是 TCP 两端通告的最大数据段长度。检测站可能据 SYN 的 MSS 推算值，并非读取本机网卡设置。
- Tailscale TUN 默认 1280；历史 `TS_DEBUG_MTU` 是调试覆盖，不是各版本通用性能按钮。当前生产值和持久化状态未由本轮重新读取。
- 一个接口写成 1400 不能证明整条路径支持 1400。客户端、出口、外层隧道与目标路径的瓶颈都可能不同，IPv4/IPv6 也需分开。
- Tailscale 的内核转发路径可能涉及 FORWARD 链 MSS 钳制；VLESS 代理的目标 TCP 由本机新建，不应把 FORWARD 钳制当作所有 Clash 问题的修复。
- 普通 ICMP ping 的“不通”可能是过滤或权限限制；经代理 TUN 的 ping 也可能被客户端特殊处理。单个 ping 结果不足以证明代理全路径 PMTU。

**本轮建议：**保留现况，不为了标签分数更改 MTU。先读取两端接口值与路由、确认直连/中继、收集可重复的小请求和较大受限下载，只有复现吞吐/重传/超时问题才计划单变量对照。

### 数值、封装与证据

[Tailscale 官方排障文档](https://tailscale.com/docs/reference/troubleshooting/network-configuration/tcp-connection-two-devices)写明默认 MTU 为 1280；[当前源码](https://github.com/tailscale/tailscale/blob/main/net/tstun/mtu.go)将其作为安全默认并包含 `TS_DEBUG_MTU` 调试覆盖。源码主分支不是已安装版本，也不能由存在 PMTU 探测代码推导所有数据路径已完整处理。不要把 `TS_DEBUG_ENABLE_PMTUD` 当作已验证修复开关。

1400 是隧道内层 IP 包上限。常规 WireGuard 直连外层还需约 60 字节 IPv4 或 80 字节 IPv6 开销，即约 1460/1480；叠加其他隧道需另算。物理网卡显示 1500 不证明全路径能承载。一端 1280、另一端 1400 也不意味着 TCP 必然失败，因为 TCP 仍交换 MSS。

常见基准：MTU 1280 对应 IPv4/IPv6 MSS 1240/1220，MTU 1400 对应 1360/1340；TCP 选项与扩展头还影响实际负载。MSS 调整只针对 TCP，不修复全部 UDP/QUIC/ICMP 问题，参见 [MTU/MSS 说明](https://developers.cloudflare.com/magic-transit/reference/mtu-mss/)。

Mihomo TUN 的大 MTU 值也不表示公网会逐包发送同样大小的 IP 包；例如 `tun.mtu=9000` 不等于外层 TCP 发 9000 字节 IP 包。[Mihomo TUN 文档](https://wiki.metacubex.one/en/config/inbound/tun/)建议一般用户保留默认值，不照搬 Tailscale 数值。

社区提供故障机制，不替代本机证据：

- [Tailscale #3836](https://github.com/tailscale/tailscale/issues/3836)展示握手成功但较大 TLS 报文丢失的子网/出口组合案例。
- [MSS 双向处理修复 #20077](https://github.com/tailscale/tailscale/pull/20077)涉及特定转发路径，不能认为所有现有安装都已包含相同处理。
- [PMTU #311](https://github.com/tailscale/tailscale/issues/311?timeline_page=2)涉及低 MTU 底层；[站点互联指南](https://tailscale.com/docs/features/site-to-site)里的 MSS 规则是变更示例，本轮没有执行。
- [Mihomo #1698](https://github.com/MetaCubeX/mihomo/issues/1698)和 [#2085](https://github.com/MetaCubeX/mihomo/issues/2085)讨论 TUN ICMP 的模拟/处理边界，不能据经 TUN 的 ping 判定全代理链路 PMTU。

### 只读盘点和待执行尺寸测试

先在已有获准会话读取版本、接口、路由和 TCP 参数，不重启、不改值。输出可能含地址或设备信息，只分享必要脱敏字段。

```sh
tailscale version
ip -d link show tailscale0
ip -brief link
ip -4 rule show
ip -4 route show table all
sysctl net.ipv4.tcp_mtu_probing net.ipv4.ip_no_pmtu_disc
systemctl show tailscaled -p Environment --value | grep -oE 'TS_DEBUG_MTU=[^ "]*|TS_DEBUG_ENABLE_PMTUD=[^ "]*'
```

最后一条只提取指定调试值；没有输出可能表示未配置或读取失败，需要结合退出状态，不能展示完整 Environment。已有 sudo 权限时可读 `iptables -t mangle -S` 与 `ip6tables -t mangle -S`，不新增规则或清计数器。Windows 可读 `Get-NetIPInterface` 的 `NlMtu`/地址族/接口，以及针对已确认目标的 `Find-NetRoute`；不把它们变成修改命令。

确认测试走 Tailscale 内层且对端为已授权设备后，IPv4 DF 小规模测试可分别取 ICMP payload 1252 与 1372，即加 28 字节头部后为 1280 与 1400，每档三次。Linux 示例：

```sh
ping -4 -c 3 -W 1 -M do -s 1252 <已确认的对端Tailscale-IP>
ping -4 -c 3 -W 1 -M do -s 1372 <已确认的对端Tailscale-IP>
```

尖括号是必须替换的说明，不可原样运行。Windows 对应 `ping -4 -n 3 -w 1000 -f -l 1252 <对端>` 与 `-l 1372`。参数依据 [Linux ping](https://man7.org/linux/man-pages/man8/ping.8.html)和 [Windows ping](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/ping)。

本机立即报 Message too long/需要分片可能只是发送接口限制，超时也可能是 ICMP 被过滤。必须记录方向；隧道内 DF 不证明外层 UDP 无分片。只有确认走真实公网、没有被 Clash TUN 特殊处理、没有经同 VPS 出口绕回，公网 DF 才有相应解释价值；无法保持现状确认路径时就记未测，不切断管理通道。

最后仍应以小请求与约 1 MiB 的限时业务传输配合连接记录、重传/PTB 观测验证。若出现稳定的“小包通、大包失败”，才有理由设计下一轮单变量、可回退 MTU/MSS 变更。本轮没有安装 iperf、启动测试服务或开放端口。

## 3. TCP 指纹与检测站

把至少四类信息分别保存：TCP SYN 字段、浏览器内层 TLS/HTTP 特征、代理外层 TLS 特征、出口 IP/ASN/地理数据库。某一层看起来像 Linux，不能直接归因为全部流量泄露，也不能靠改另一层的字段保证消失。

- TTL、窗口、窗口缩放、MSS、TCP options 及顺序都可参与启发式分类。NAT、隧道和中间设备可能影响部分字段；网站的系统标签不是密码学证明。
- 改 MTU/MSS 只触及其中一部分。REALITY 的 `client-fingerprint` 是外层 uTLS，不控制远端网站看到的出口 TCP SYN。
- QUIC/HTTP/3 使用 UDP，没有该连接的 TCP SYN。做 TCP 对照时先确认站点使用 h2 或 HTTP/1.1，不能把 h3 的结果空缺或旧缓存当作 TCP 变化。
- Mihomo 的 VLESS `xtls-rprx-vision` 文档描述其 UDP 443 行为等效 Xray 的 `*-udp443`，不能仅因配置使用 Vision 就断言 QUIC 已被禁用。
- 不承诺用 TCP 改写躲过风控或使所有检测站显示 Windows；这类改动还可能影响校验和、分段卸载、重传与其他用户的连接。

依据：[Mihomo VLESS](https://wiki.metacubex.one/config/proxies/vless/)、[JA4T 指纹解释](https://blog.foxio.io/ja4t-tcp-fingerprinting)。

### 改善方向与代价

- 已有 Tailscale 内核出口是保留客户端原生 TCP 栈特征的合理对照；仍需考虑直连/DERP、MTU 与真实路由。用户态运行的 WireGuard/Tailscale 进程不自动等于 netstack TCP 代理，关键是其 IP 转发模式。
- SNAT 改地址/可能端口，不等于重建 TCP；TTL 递减、MSS 调整可以与原 TCP 端到端存在同时发生，见 [Netfilter NAT](https://www.netfilter.org/documentation/HOWTO/NAT-HOWTO-6.html)。
- 普通 DIRECT 出站通常呈现 VPS 内核 SYN；若服务端另接上游代理或用户态协议栈，最终取决于最后建立目标 TCP 的一方。VLESS 后再套普通 L3 WireGuard/Tailscale，不会恢复已被代理终止的客户端 TCP。
- Vision/Splice 减少复制，不把两段 TCP 还原成原连接，见 [XTLS 文档](https://xtls.github.io/en/config/outbounds/vless.html)。没有 HTTPS 解密时，目标 TLS/HTTP 仍通常来自浏览器，因此 Linux TCP 与 Windows/iPhone 浏览器属性组合可以是正常代理结果。
- 改 sysctl/TTL/MSS 只能改变部分字段；Linux `ip_default_ttl` 影响本机生成包，不影响转发包。全局修改会影响其他服务，关闭窗口缩放还可能严重损害高 RTT 吞吐，见[内核文档](https://docs.kernel.org/networking/ip-sysctl.html)。
- 普通容器共用宿主内核；换容器镜像不是换 TCP 操作系统。换出口系统也无法一份配置同时匹配 Windows 与 iOS。为匹配标签改 UA、做 HTTPS MITM 或定制改包都不是本轮建议。

[p0f 文档](https://github.com/p0f/p0f/blob/master/docs/README)讨论跨层差异与误报；[FoxIO 实现](https://github.com/FoxIO-LLC/ja4-nginx-module/blob/main/README.md)明确 TCP 代理后得到代理连接的 JA4T，QUIC 没有该 TCP SYN 指纹。这说明差异可被观测，不证明用户在某网站遇到的挑战由此触发。[Cloudflare 官方机制](https://developers.cloudflare.com/bots/concepts/bot-detection-engines/)使用多种信号，IP/ASN、请求行为、Cookie、协议与时间等仍可能有影响。

### 验证 TCP 是否被重建

在同一真实 Windows 或 iPhone 浏览器分别比较直连、现有 Tailscale、现有 VLESS。两种设备单独记录，不用云端 curl 模拟。若现有权限与工具允许，可按目标、短时间和有限包数观察 SYN 元数据，关闭混杂模式，不采集 HTTP 内容或账号流量：

- Tailscale 比较 `tailscale0` 入站和物理网卡出站的选项顺序、窗口、缩放等，允许 NAT/TTL/MSS 的预期变化。
- VLESS 比较网站方向的出站 SYN 与真实客户端基线；VPS 节点端口上的入站 SYN 不是网站收到的 SYN。
- 独立目标端观测最有说服力；VPS 上抓到的出站只证明离开 VPS 时的样子，不能排除下游改写。不能访问 VPS 自己的网站就称测过其互联网出口。
- 每组确认 h2/h1，不把 h3 下没看到 SYN 解释成“没有指纹”。只做少量请求，不启动新监听或改生产。

即使同一 VPS 出口 IP 下 Tailscale 成功、VLESS 失败，也需控制 DNS/CDN、IPv6、HTTP 版本、Cookie、时间和请求节奏，才能提高归因可信度；仍不保证改指纹能消除风控。

## 4. DNS 与 CDN 路径

### 三种不同的“绕路”

1. **DNS 映射型 CDN：**权威 DNS 可根据递归解析器来源、ECS 等选点。先用本地 DNS 得到面向本地网络的地址，再由海外 VPS 连接，可能出现出口与选点不匹配。但代理如果把域名交给 VPS 最终解析，单改客户端 DNS 未必改变目标地址。
2. **Cloudflare Anycast：**同一地址可由多处网络宣告，实际 colo 与出口路由、互联及 CDN 策略有关。换 DNS 或“优选 IP”不保证锁定城市；IPv4/IPv6、不同域名和不同时刻可能不同。`cf-ray`/`colo` 是处理位置线索，不是完整往返路由，更不是访客国家定位依据。
3. **走错路径：**Rule/Direct、策略组、Tailscale 与 Clash 叠加、IPv6/UDP 不同出口。先确认期望出口，再谈 CDN 优化。

来源：[Cloudflare 地理路由说明](https://developers.cloudflare.com/support/troubleshooting/general-troubleshooting/geographic-traffic-routing/)、[CDN 架构](https://developers.cloudflare.com/reference-architecture/architectures/cdn/)。[2025 年 DNS/CDN 测量论文](https://arxiv.org/abs/2502.05763)将 DNS 查询与解析后的访问耗时分开比较，也不支持一个解析器各地总是最快；论文样本不是当前 VPS 性能。

### Mihomo 的解析位置和上游路径

以已记录的 v1.19.33 为基线，对照[DNS 文档](https://wiki.metacubex.one/config/dns/)、[解析流程](https://wiki.metacubex.one/config/dns/diagram/)和[该版本 DNS dialer 源码](https://github.com/MetaCubeX/mihomo/blob/v1.19.33/tunnel/dns_dialer.go)：

- `nameserver-policy` 决定查哪个上游；`respect-rules` 决定连接这个上游的路径。后者按 DNS 上游地址构造连接元数据，不是对每个查询中的业务域名再次直接套相同的连接规则。
- 上游 URL 的 `#代理组` 可显式指定出口；`proxy-server-nameserver` 负责代理节点域名；`default-nameserver` 用于上游域名引导。这些角色不能互相替代。
- `direct-nameserver` 负责 DIRECT 连接解析；是否跟随 `nameserver-policy` 另由 `direct-nameserver-follow-policy` 控制。
- 域名命中代理时可能把域名交给远端；直连或 IP 规则判断可能先触发本地解析。需要区分“为规则判断解析”和“最终连接目标的解析”。
- `fake-ip` 保存域名路由信息，TUN DNS hijack 接管匹配到的 DNS 流量。两者都不保证浏览器自带 DoH、任意应用 DoH、IPv6、UDP 和所有旁路已覆盖。
- 仓库基础配置没有 DNS 块且 TUN 默认关闭。CRV 还可能有全局覆写，不能只凭源文件缺少 `dns` 就断言运行内核没有 DNS；应读取合并后有效配置，且不要把整份含凭据配置放进报告。

浏览器与命令行也不同。[Chromium 代理文档](https://chromium.googlesource.com/chromium/src/+/HEAD/net/docs/proxy.md)说明 HTTP 和 SOCKS5 的目标解析在代理侧；Chrome 的 SOCKS5 代理不转发 UDP。不能泛化为“HTTP/SOCKS5 必先本地解析”。curl 的 `socks5://` 与 `socks5h://` 分别涉及本地解析与将域名交代理；交给本地 Mihomo 后，仍取决于其规则与最终出站。

### “DNS 泄露”的判断要有目标

DoH 加密解析传输，但不自动保证经 VPS；解析器仍可知道查询及其可见来源。对本来就计划 DIRECT 的域名使用本地 DNS，可以是设计选择。对预期代理的域名，应查实际查询是否从本地非隧道路径发送。

多条递归出口、IP 地理库不一致、测试页出现另一国家，都不能单独证明泄露。ECS 可影响一些 CDN，也有隐私与缓存成本；[Cloudflare 1.1.1.1](https://developers.cloudflare.com/1.1.1.1/faq/)通常不发送 ECS，[Google ECS 文档](https://developers.google.com/speed/public-dns/docs/ecs)说明其用途，不能据此把启用 ECS 当通用必选。

社区案例可提供排查线索，不能当生产事实：[CRV #7353](https://github.com/clash-verge-rev/clash-verge-rev/issues/7353)涉及 DIRECT 业务与 DNS 上游路径差异；[Mihomo #2971](https://github.com/MetaCubeX/mihomo/issues/2971)涉及测试页和 policy 观测差异。版本、关闭状态与用户现况都要重新核对。

### 轻量复现实验

以下未在用户真实链路执行。先记录设备、浏览器、网络、有效规则、出口、TUN、系统代理、Secure DNS 状态，不擅自切换、重载或清缓存。

1. 在实际使用路径打开 [Net.Coffee](https://ip.net.coffee/)、[DNS](https://ip.net.coffee/dns/)、[WebRTC](https://ip.net.coffee/webrtc/)、[Cloudflare](https://ip.net.coffee/cloudflare/)和 [Egress](https://egress.1ms.dog/)。不点击可能消耗约 350 MB 的测速，不上传配置，不公开分享含 IP 的报告。遇验证挑战停止该项，不能记为网络故障。Egress 的端口组检测其东京服务端，不是检测本 VPS 端口。
2. 固定同一个受支持的 Cloudflare 目标，做五次轻量 trace/HTTP 请求，取中位数与范围。`cloudflare.com` 的 colo 不代表全部 Cloudflare 域名；实际慢的网站可读取其支持的 trace 或 `cf-ray` 响应头。
3. 已有本地代理时可用以下命令，先核实实际端口；它不会建立代理、修改模式或切换出口。环境变量 `NO_PROXY` 仍可能影响命中，最终用出口和客户端连接记录核对。

```powershell
curl.exe -q -sS --connect-timeout 5 --max-time 15 --http1.1 --proxy socks5h://127.0.0.1:7897 https://www.cloudflare.com/cdn-cgi/trace
```

4. 若已有获准的 VPS 会话，可用已安装 curl 对同一公共目标做请求，分开观察“客户端→VPS”和“VPS→目标”。客户端慢、VPS 侧快使第一段更值得检查，但不是唯一因果证明。不要启动新监听或改服务。
5. curl 计时可记录 DNS、连接、TLS、TTFB 和总耗时；经本地 SOCKS 时，`time_connect` 主要是到本地代理，`remote_ip` 可能是回环地址，DNS 计时可能近零。它们不能充当 VPS 到 CDN 的 RTT 或远端解析耗时，详见 [curl 文档](https://curl.se/docs/manpage.html)。
6. 未来获批 DNS A/B 时，只改隔离客户端测试配置中的一个变量，对比 A/AAAA、实际远端、colo 和 TTFB。若最终由 VPS 解析，客户端 DNS 改动未影响目标很正常。`--resolve` 只有在明确的解析/代理语义下才有效，不能认为 SOCKS5h 下它已强制远端解析。

**建议顺序：**先确认出口和同目标时延，再决定 DNS 分流；国内 DIRECT 解析与国内出口匹配，代理域名采用远端或明确经代理的上游，节点引导 DNS 避免环路。若证实 Cloudflare 出口路由差，整理时间、colo、`cf-ray`、时延与有限路径证据供服务商排查。不要先安装 WARP、锁定所谓“优选 IP”、改生产防火墙或 MTU。

## 5. 最小实验矩阵

每行都用同一真实设备、同一浏览器版本、同一目标、接近的时间重复，并记录实际连接协议。不要同时改 MTU、DNS、规则和节点；不要为了测试关闭唯一管理通道。

| 项目 | 操作与记录 | 能回答什么 | 不能回答什么 |
| --- | --- | --- | --- |
| 客户端直连基线 | 记录出口、目标、h2/h1 或 h3、TCP 原始字段；无需上传代理凭据 | 该设备该目标的基线 | VPS 当前状态或代理质量 |
| Tailscale 内核出口 | 核实真实 exit node、内核模式和直连/中继，记录同样字段 | 该次转发路径与基线差异 | 自动证明所有流量不泄露 |
| REALITY/VLESS | 核实选中节点及连接记录，不叠加未知 Tailscale 出口 | 该次代理路径的目标 TCP/出口 | 用客户端 MTU解释所有出口特征 |
| MTU 黑洞排查 | 先只读接口/路由，限制请求大小/次数，分别测 v4/v6 和短/较长传输 | 是否存在可复现尺寸或路径相关失败 | 无 ICMP 回应就断言 PMTU 值 |
| CDN 路径对照 | 记录解析器、A/AAAA、实际远端、站点/边缘信息、DNS/TCP/TLS/TTFB | DNS 选点、路径与应用等待的差异 | 单一城市标签证明物理绕路 |
| WebRTC/UDP | 查看实际候选类型、来源 IP类别和 UDP 连接归属 | 当次浏览器 UDP 的可见出口 | NAT 标签等于泄露或所有应用安全 |

只记录必要摘要，不把带身份信息的完整页面、账号 Cookie、订阅 URL 或 `/connections` 响应放进仓库。访问检测站会向它披露当次出口及浏览器信息；指定测试站点不表示可以随意上传配置或使用公开端口报告服务。

## 6. 实际完成与未完成

- 已完成：现有仓库和会话证据复盘，官方与第三方机制核对，离线工具基线复测。详细结果见[VALIDATION.md](../../../VALIDATION.md)。
- **独立云浏览器实验：**Net.Coffee Cloudflare 页七个可达目标都显示 MSP，页面各自三次测量的最小值为 24–31 ms；1.1.1.1 目标不可达。以 IPv6、HTTP/2 为主，测速服务行显示 HTTP/1.1，页面显示 WARP 未启用。没有启动大流量测速。
- **独立云浏览器 DNS 页：**返回四个 Cloudflare 递归出口，地理标签 Chicago/Minneapolis，页面判断“未检测到泄露”。这只涉及当次随机测试域名及该云环境。另一页面同时出现英国出口地理标签、美国 MSP colo 与“就近”评级，说明需保留原始字段，不能直接采信自动评级。
- **测试站限制：**Egress 在同一云浏览器显示 Site Unavailable，未出现可确认原因，未绕过；公开功能说明可读取，动态测试没有跑通。不能解释成用户链路故障。用户 Windows 设备当时未在线，未用它执行新测量。
- **合成配置实验：**基础生成器输出 `mode: rule`、TUN 关闭、IPv6 关闭、无 DNS 块；分类版有九个 providers，每个 `Route-*` 初选 VPS-Select。这里只运行本地生成，没有下载规则、触达 VPS，也不代表托管订阅或 CRV 合并后配置完全相同。
- 历史证据：Tailscale 1400、独立 REALITY HTTP 200、若干当次 WebRTC 结果均为既有会话记录，不是本轮重新实测。
- 未完成：同一真实 Windows 浏览器的直连/Tailscale/VLESS 三路 TCP 对照、两端 PMTU 数值闭环、CDN 最优节点结论以及任何生产指纹改写。
- **MTU 实验限制：**本次测试环境无 ping、tracepath、tailscale，读取接口和路由的 netlink 调用返回 Operation not permitted；未提权或换路线绕过。因此没有得到新的 MTU/PMTU 测量值，也没有读取 VPS 当前 MTU。
- 暂不可做的测试继续保留为待验证，不通过切换未授权机器或换网络路由规避限制。独立云端请求只能代表该测试环境，不能冒充用户家庭网络或生产 VPS。

## 7. 实验记录模板

```text
时间（含时区）：
设备与软件版本：
路径：直连 / Tailscale 内核 / Tailscale userspace / VLESS / 未知
系统代理 / TUN / 模式 / 出口节点：
目标与实际协议（h1/h2/h3）：
IPv4 或 IPv6、解析器与实际远端：
接口 MTU / 路径观测 / 原始 TCP 字段（未知填未知）：
成功率与 DNS/TCP/TLS/TTFB/下载耗时：
本次只改变的变量：
证据等级：直接观测 / 用户报告 / 文档机制 / 待验证假设
结论与不能推出的结论：
```

保持目标、协议和路径可复现比收集更多无上下文截图更重要。实际地址、配置或捕获文件应保存在受限私有位置；本仓库只收脱敏摘要。
