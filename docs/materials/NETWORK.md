# 网络资料

- [Mihomo 配置文档](https://wiki.metacubex.one/config/)：入口、设备规则、代理组、DNS 和协议配置。
- [nftables 文档](https://wiki.nftables.org/)：防火墙、连接跟踪、NAT 与队列规则。
- [Linux tc-bpf 手册](https://man7.org/linux/man-pages/man8/tc-bpf.8.html)：tc egress 与 eBPF 附着。
- [Tailscale 子网路由与出口节点](https://tailscale.com/kb/1019/subnets)：组网与转发。
- [Let's Encrypt DNS-01](https://letsencrypt.org/docs/challenge-types/#dns-01-challenge)：通过 DNS 签发证书。

TCP 指纹由接收端观察到的 SYN 字段形成。MSS、窗口、缩放值和时间戳由内核协商；仅重排选项不会改变 UDP、QUIC、TLS 或 IP 信誉。接收端抓包可以直接检查 SYN，出口主机上的抓包还需考虑校验和卸载。

## 设备身份与出口

代理入口接受客户端连接后，由后端建立到目标网站的新连接。目标网站看到的是后端 TCP 栈；设备身份规则决定使用哪个出口。Mihomo 的 `IN-USER` 和 `NETWORK` 规则可以分别选择设备和 UDP 路径。

TCP 选项中的 MSS、窗口缩放和时间戳参与两端协商。修改选项顺序时应保留内核产生的值；不同网络和内核参数会产生不同数值。经路由转发时，IP TTL 会逐跳递减。

## 抓包与卸载

Linux 可以把 TCP 校验和计算交给网卡或虚拟链路。抓包中的 `CHECKSUM_PARTIAL` 可能仍是伪首部种子；关闭相关卸载或在独立接收端抓包后再检查完整校验和。GSO、TSO 和 GRO 会影响分段观察，详见 [Linux 校验和卸载](https://docs.kernel.org/networking/checksum-offloads.html)和[分段卸载](https://docs.kernel.org/networking/segmentation-offloads.html)。

Mihomo 后端使用自身 DNS 配置。直接在网络空间中运行系统工具时，工具还依赖该空间可访问的系统解析器；排查时可通过 `curl --resolve` 指定已解析的地址，并保留 HTTPS 主机名和证书校验。

## TTL 与往返时延的一致性

VPS 当前在网络空间中独立建立目标 TCP 连接。iOS 出口的 `ip_default_ttl=65`、Windows 出口的 `129` 是为了补偿一次内部转发。远端看到 `TTL 54/64` 时，p0f 估算的 10 跳是出口到远端的路径，并不包括设备到 VPS 的原始路径。10 跳属于正常公网范围；调高初始 TTL 可以让特定检测站的估计值变小，但不会缩短真实路径。跨目标站点与路由变化后还可能出现反常的初始 TTL 估算。

TCP 代理分别终止设备端和服务器端连接。服务器读取 `TCP_INFO.tcpi_rtt` 得到的是 VPS 后端与远端之间的平滑 RTT；浏览器测得的请求时间还包含设备到 VPS 的路径、代理调度和应用处理。Linux 服务器被动建立 TCP 时，会从 SYN-ACK 到第三次 ACK 的时间建立初始 RTT 样本，之后随着新数据确认继续更新。修改 SYN 选项、TTL、MSS 或 TCP 时间戳的值，都不会直接消除这两个观测范围的差别。

以 `tc netem` 延迟 ACK/握手可以在隔离实验中影响 TCP RTT 估计，但也会影响真实发送窗口、拥塞控制和请求完成时间。普通追加网络延迟会同时加大服务器与浏览器所测时延，不能稳定消除差值，不应直接部署到用户出站。客户端开启 Mihomo TUN 仅改变流量捕获，不会使 VLESS/AnyTLS 的 TCP 重新建连变成端到端 TCP。

### 远端 TCP RTT 的真实采样机制

在 Linux `tcp_input.c` 中，`tcp_synack_rtt_meas()` 可以用 SYN-ACK 发出到最终握手 ACK 到达的时间建立初始 RTT；后续 `tcp_ack_update_rtt()` 则优先使用基于序列号的 ACK 时序样本，只有缺少该样本时才使用 `TSecr`。所以简单修改 TCP Timestamp 的 `TSecr`，不能在通常的数据往返中稳定改写远端的 `TCP_INFO.tcpi_rtt`。这也是只修改 SYN 选项的当前 eBPF 程序不会改变 RTT 的直接原因。

如果只在 egress 将第三次握手 ACK 延迟，探针可能暂时读到更大的初始 RTT，但 HTTP/2 持久连接上的后续数据 ACK 会更新平滑 RTT。若持续延迟与数据确认有关的 ACK，会抬高发送端看到的 RTT，同时扰动其拥塞窗口、重传定时器与传输速度；不能保证浏览器侧的延迟保持不变。实验应分别记录 `tcpi_rtt`、`tcpi_min_rtt`、`tcpi_rttvar`、重传与浏览器端耗时，并复用 HTTP/2 连接。

### 其他指纹维度

现有 SYN 重排只覆盖特定布局的 IPv4 SYN。除初始 TTL、MSS、SACK、窗口比例及选项顺序，检测系统还可能分析 DF/ECN、IPID、时间戳时钟增长、重传时序、拥塞控制行为、浏览器 TLS/HTTP2 指纹以及 UDP/QUIC 出口的一致性。把某一项伪装为 Apple 不会自动让整条 TCP 连接模拟 Darwin/XNU 内核。应以被动观测和性能基线检查这些特征，避免为追求单站评分修改已经工作的内核协商值。

### 建议对照实验

1. 在同一客户端、网络和网站上分别测试 VLESS、Hysteria2、AnyTLS，记录多次浏览器时间、网站 TCP RTT、HTTP 版本及服务器端连接状态，避免单次测量偏差。
2. 在 VPS 网络空间使用 `ss -ti` 观察实际出站连接 RTT，结合远端抓包验证 SYN 选项/TTL；比较不同协议的分布，而非只看平均值。
3. 使用同一 VPS 的 Tailscale Exit Node 单独对照（关闭 Clash VPN），验证三层转发是否消除 TCP 连接的分段建连特征。它不增加代理跳数，但会改变整个运行形态和端到端拥塞控制。
4. TTL 调整或 ACK 延迟只在可撤销的隔离网络空间测试，不混入已验证的生产 TCP 指纹路径。

依据：[p0f 指纹格式](https://github.com/p0f/p0f/blob/master/docs/README)、[Linux TCP RTT 样本更新](https://github.com/torvalds/linux/blob/master/net/ipv4/tcp_input.c)、[TCP_INFO](https://github.com/torvalds/linux/blob/master/net/ipv4/tcp.c)、[RFC 6298](https://www.rfc-editor.org/rfc/rfc6298)、[tc-netem](https://man7.org/linux/man-pages/man8/tc-netem.8.html)。
