# TCP 指纹：可落地路线与本轮实验

日期：2026-11-12 UTC。生产服务器未连接、未修改。本轮没有调整 MTU、Tailscale、订阅、防火墙、系统代理或用户设备设置。

## 结论

针对“手机与 Windows 使用同一 VLESS 服务器，但让网站看到对应设备的 TCP 特征”，可执行的服务端结构是：

**每设备独立 VLESS 凭据 → Mihomo 的 IN-USER 分流 → 有不同 TCP 模板的出口。**

本轮已用官方 Mihomo v1.19.33 实际验证前两段和末段按连接选参数：20 次真实本地请求全部成功，Windows/iOS 两种测试身份各 10 次正确分流。完整的内核 TCP 模板尚未加载，不能把这个结果称为“Windows/iOS 指纹已经伪装成功”。

找到的候选项目中，SkyProxy 最接近上述结构，有 SOCKS5、每用户模板、Windows/iOS 参数及 mirror 模式。但其实现依赖第三方内核模块，存在明确的兼容与失效检查问题，尚不适合直接放进现有生产 VPS。flash-relay 的 eBPF 版本更容易限定到带标记的连接，但目前只有 IPv4 改写，作者自己也列出公网网卡校验、窗口值与最终识别尚待验证，不能视为即装即用成品。

**推荐下一步不是切回 userspace，也不是继续改 MTU，而是沿着已测通的“按设备凭据分流”结构，在可丢弃的 Linux 虚拟机里验证 SkyProxy 的完整模板。** 如果必须马上采用已有成熟机制，原生设备 → 内核转发的 Tailscale/WireGuard 出口能保留设备 TCP 栈；这是不同路径，不会修复仍经过 VLESS 重建的连接。

## 1. 本轮真正运行了什么

脚本：[test_device_routing.py](../experiments/tcp-device-routing/test_device_routing.py)。结果：[device-routing-results.json](../experiments/tcp-device-routing/device-routing-results.json)。

- 下载并校验官方 `mihomo-linux-amd64-compatible-v1.19.33.gz`。GitHub release 提供的 SHA256 与下载文件相符：`386508bfb1c72c43b6a0eda73708ecdce82546581b0ebcb16366c53757c622b6`。
- 两个 Mihomo 进程使用临时目录、临时凭据及回环监听。外层实际使用 VLESS、REALITY、Vision，不是仅测试规则解析。
- Windows/iOS 是测试身份名称，**不是本次实际使用的 Windows/iPhone 设备**。同一 Linux 实验环境发起两类请求。
- 每一身份使用不同 UUID；服务端 IN-USER 规则选择不同 SOCKS 用户。自写的受限 SOCKS 实验服务按用户名为目标连接设置 IP_TTL。
- 接收端使用 Linux TCP_SAVE_SYN/TCP_SAVED_SYN 读取真实收到的 SYN，无需 raw socket，也没有抓取其他连接。
- 共 20 个 HTTP 往返，4 路并发，每类 10 个。两个配置检查通过，20 个请求均成功且选中正确出口。
- Windows 测试出口收到 TTL 128，iOS 测试出口收到 TTL 64。两者 options 均为 `2-4-8-1-3`，窗口/MSS 均为 65495、缩放 10。这是实验机器回环 TCP 的实际值，不能拿作公网模板。
- 每条从 Mihomo 到 SOCKS 的入站 SYN 都是 TTL 64 和 Linux options。这印证：在 VLESS 后面接 mirror，只会复制 Mihomo 新建的连接，不能取回终端的原始 SYN。
- 所有进程和临时配置已在 finally 清理，没有安装 systemd 服务或长期监听。

**实验回答了什么：**现有协议和官方 Mihomo 无需修改源码，就能把不同设备身份自动送往不同出口。这是可复用的接入结构。

**实验没有回答什么：**没有加载 SkyProxy/flash-relay；没有 Windows/iOS 真机对照、完整 TCP 改写、外网检测站识别、IPv6、吞吐、丢包恢复或长连接验收。TTL 修改不是完整指纹修复。

复现要求为 Linux、Python 3、OpenSSL、curl 和已校验的官方 Mihomo，运行脚本只会创建回环实验连接。该脚本是显式集成实验，导入即执行，故放在独立 experiments 目录，不纳入普通 unittest 自动发现；复现前先读[实验说明](../experiments/tcp-device-routing/README.md)，在仓库外的私有临时目录运行，不覆盖随包证据。初版试验发现 v1.19.33 不接受无保护的 VLESS 入站，因此最终脚本使用 REALITY，没有关闭生产或实验客户端的证书验证。REALITY 的本地模拟握手目标还需一个只针对该临时端口的 DIRECT 实验例外；这条规则绝不能复制到生产配置。

## 2. 现成项目调查结果

### SkyProxy：功能最接近，但需要真正的隔离虚拟机试验

核对版本：`e936e61fe56fcbea4a866afbfe9d8de0e7aab1a4`。

- 提供每用户 Windows/iOS 模板，SOCKS 认证可选择模板；mirror 使用入站 socket 保存的 SYN。
- 真正调整 options、窗口缩放和重传行为的部分依赖内核模块；不是换镜像或普通代理参数就能得到这些能力。
- 源码使用 ftrace/kprobes 接入 TCP 内部函数，并读写 x86_64 寄存器参数。官方首页笼统写 Linux 5.10+，但不能据此认为所有架构与内核都兼容。
- 普通 `make` 的默认目标会尝试卸载、加载内核模块。**不要在生产服务器、共享宿主或普通容器中照抄其快速开始。** 容器没有隔离宿主内核故障。
- 源码中多项 hook 注册失败只记 warning，模块初始化仍可能返回成功；用户态后端不可用时也可能降级为普通 socket 参数。因此“进程启动”“模块加载”“网页能打开”都不证明完整指纹生效。
- 没有找到足以证明生产可靠性的独立长时间、多内核测试证据。作者宣称的 p0f/active 验证仅作为项目报告，不当成本轮复测。

来源：[功能与配置](https://github.com/Muno459/skyproxy/blob/e936e61fe56fcbea4a866afbfe9d8de0e7aab1a4/README.md)、[mirror 实现](https://github.com/Muno459/skyproxy/blob/e936e61fe56fcbea4a866afbfe9d8de0e7aab1a4/src/hev-socks5-session.c)、[模块加载目标](https://github.com/Muno459/skyproxy/blob/e936e61fe56fcbea4a866afbfe9d8de0e7aab1a4/Makefile)、[内核 hook 与失效处理](https://github.com/Muno459/skyproxy/blob/e936e61fe56fcbea4a866afbfe9d8de0e7aab1a4/src/dkms/hev-tcpfp-kmod.c)。

### flash-relay：适合参考实现，不是当前现成替换件

核对版本：`f2a894f69a904b3d2735b7f25b32beb2f51a9f9c`。

- 是 Go relay 库。用 SO_MARK 选择连接模板，tc-egress eBPF 改 TTL、IP ID 与 SYN 选项；窗口/缩放通过真正的 socket 参数形成，而非仅修改线上的数值。
- 源码明确跳过 IPv6；并且只对特定 Linux 20 字节 options 布局改写。不能说所有 TCP 都覆盖。
- 作者列出的部署需要 tc/eBPF 权限，并修改接收缓冲上限及 ECN。按原说明直接部署会改变全局/所在网络命名空间参数，而不仅是某个用户。
- 作者明确保留公网网卡 TCP checksum/offload、精确窗口、最终 p0f/JA4T 标签验证项目。固定 SO_RCVBUF 会失去正常接收缓冲自动增长，重传定时也未仿真。
- 作者的约 3.9% 指令开销是其回环测试，不是这个 VPS 的性能承诺；本轮没有复现该数字。

来源：[实现与未完成项](https://github.com/thealonlevi/flash-relay/blob/f2a894f69a904b3d2735b7f25b32beb2f51a9f9c/fingerprint/README.md)、[实际 IPv4 判断及改写代码](https://github.com/thealonlevi/flash-relay/blob/f2a894f69a904b3d2735b7f25b32beb2f51a9f9c/fingerprint/bpf/syn_rewrite.bpf.c)。

### 不推荐作为此问题的解法

- OSfooler-ng、简单 NFQUEUE/iptables 脚本：没有找到足以优先于上述候选的维护、全会话一致性和现代双栈证据。
- 只改 TTL、MSS、窗口：本轮真实 SYN 已验证，即使 TTL 改到 128，TCP options 仍是 Linux，JA4T 也未改变。
- 切回 Tailscale userspace：其 TCP 转发会终止并重建连接，不是手机/Windows 模板选择器。[Tailscale 官方对照](https://tailscale.com/docs/reference/kernel-vs-userspace-routers)
- 普通 VLESS 后再接 WireGuard：它只能运输 VPS 已经建立的新 TCP，不能恢复原始终端 TCP。

## 3. “自动识别设备”要怎样做才稳

优先使用 **owner-windows、owner-ios 两个认证身份**，服务器按身份应用模板。客户端一次性导入各自订阅即可，日常无需手动切换模板。这叫按身份选择，不要对外宣传成准确探测操作系统。

不优先根据 UA、TLS 或公网 IP 猜设备：HTTPS 的 UA 位于加密内容内；不应为此部署 MITM 或要求用户安装根证书。外层 REALITY ClientHello 可以人为设成相同浏览器模板；同一个 NAT 地址也能包含手机与 Windows。被 VLESS 终止的原始 TCP SYN不在协议中自动传给后端。

若两设备继续共用一个 UUID，仅靠现有服务端普通配置无法保证区分。可扩展服务端观察外层连接，但那是新开发，且只能得到代理外层栈特征，仍不是终端每条目标连接的完整指纹。

官方配置依据：[VLESS 用户配置](https://wiki.metacubex.one/config/inbound/listeners/vless/)、[IN-USER 路由](https://wiki.metacubex.one/config/rules/)。本轮已验证 v1.19.33 的实际行为，不只引用新版文档。

## 4. 保留现有服务的部署设计

以下是待批准、待验证设计，本轮未执行：

1. **先在可丢弃 VM 做后端验收。** 不使用生产 VPS，也不以 Docker 代替内核隔离。记录内核与架构，固定源码提交；加载前审查模块，逐项确认 hook 成功。
2. **只用固定模板，不用 VLESS 后的 mirror。** VM 内配置两个 SOCKS 身份分别绑定 win11/ios，禁止默认通用口令和任意模板输入。不要暴露无保护的公网 SOCKS。
3. **保留原有 VLESS/REALITY 服务入口。** 实际上线时新增每设备身份并将相应 IN-USER 规则放在原有私网/本机/元数据目标阻断规则之后。既有用户可暂时仍走现状，便于小范围验收和回退。
4. **不能忽略已有出站 guard。** 仓库的 guard 会阻止 Mihomo 访问回环 SOCKS。未来接入必须精确允许仅该进程到固定本地端口；新的出口进程也要继承对私网、元数据与本机目标的拒绝，避免绕过原来的防护。不能直接放行全部 loopback、删除 guard 或换 UID 后任意访问。
5. **后端故障策略明确。** 试验阶段失败应中断被测身份，不要静默回到普通 Linux 出口。回退应由单一受控规则切回原 DIRECT，明确告知此时 TCP 模板不再生效。

## 5. 完整验收门槛与代价

最小合格证据不是检测站一个 OS 标签，而是两个设备的直连基线和代理出口对照：

- 在独立接收端记录 SYN 的 options 顺序、窗口、缩放、MSS、TTL、flags、IP ID；再看数据包和重传是否自洽。
- Win/iOS 同时连接，检查各自模板互不串用；换错凭据的结果应清楚可解释。
- 受控小请求、约 1 MiB 传输、长连接、后端退出、并发、IPv4/IPv6 分别测试。外网观测不能以回环代替。
- 在用户给的 ip.net.coffee 与 egress.1ms.dog 比较，但保留原始协议字段。标签变化不保证其他网站免于验证，也不会改变 VPS 的 IP/ASN 信誉。
- 检查 SSH、Tailscale、订阅服务及未参与试验的连接未受影响；新内核版本更新后重新验收。

实际代价：多一个出口服务和一套模板、每设备凭据维护、内核升级兼容测试，以及包改写/模块故障风险。额外本地代理跳转通常不会新增跨洲 RTT，但 CPU、连接数、吞吐与内存代价必须在目标环境测量，不能用项目宣传值替代。

当前完整改写实验的边界是本执行环境没有 raw-socket/eBPF/内核模块所需权限；已经确认普通 socket 可用，raw socket 创建得到 EPERM。未申请扩大权限、未换机器绕过该限制、未加载陌生模块。可做的路由与真实 SYN 实验已完成；剩余最小动作就是独立 VM 上的完整模板验收，而不是再泛泛搜一轮。
