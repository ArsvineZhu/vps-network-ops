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
