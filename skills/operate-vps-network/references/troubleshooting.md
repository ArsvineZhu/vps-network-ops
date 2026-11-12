# 排障 Cookbook

## 节点超时

先记录失败时间、当时网络路径、模式、端口和最内层错误。用户为恢复上网切回 Tailscale 后的状态，不代表测试时状态。

### A. 本机代理没启动

检查进程退出码、监听归属和脱敏日志。Windows临时 SOCKS 同时需要 TCP/UDP 的同号端口；只验证 TCP 可用可能抽到 UDP 排除范围。选择可同时绑定的端口，释放预留后启动，检查归属，竞争失败只清理自己的进程。

### B. 代理启动了，但请求失败

curl35是泛化TLS错误，不能直接断言REALITY认证失败。保存核心最内层错误；先脱敏再输出。临时日志删除前提取原因。

mihomo本次版本连接过程存在5秒期限，约5秒失败既可能发生在TCP连接，也可能在外层握手。分别看 `dial tcp`、认证失败、reset及服务器收到的包。

### C. 公网端口是否到达

```bash
ss -lntpe '( sport = :8443 )'
ip -4 route get PUBLIC_IP
ip -4 route get PROBE_IP
ufw status verbose
```
用真实地址替换参数。`ss -4` 无监听不表示IPv4不通，IPv6 socket 的 `v6only:0` 支持双栈。

最有效对照是同一外部探针对生产端口和已知可用SSH端口测试。外部服务会收到IP/端口并可能产生公开报告，先确认分享范围。

先启动服务器抓包，再发探测，持续到任务完成。只筛目标IP/端口的连接包头，避免无关用户流量：
```bash
tcpdump -p -i any -nn -tttt 'tcp and dst host PUBLIC_IP and (dst port SERVICE_PORT or dst port SSH_PORT) and (tcp[tcpflags] & tcp-syn != 0)'
```
- SSH SYN可见并回复、服务端口 SYN不可见：强烈指向服务器抓包点之前的选择性丢弃。
- 服务端口 SYN可见但不回复：核查监听、INPUT、OUTPUT和回程。
- 已回复 SYN-ACK但对端超时：核查回程和上游。

Check-Host是异步探测。创建请求返回HTTPError但无ID时，不知道是否已创建；不能把它当成端口失败，也不盲重试。记录状态码和有限脱敏响应。`0 captured`须结合窗口覆盖判断，`received by filter`单项不能证明特定探针到达。

## 临时外网测试

优先用户手机蜂窝网络与独立测试监听，电脑保留管理连接。手机关闭自身VPN后访问固定文本页面；勿用列目录HTTP服务器。先核对端口/既有规则，再安排独立定时清理、启动有时限的非root监听，最后临时放行已批准的来源。清理须核验，生产迁移前取消该计时器。

## 服务 active 但不可用

systemd启动成功和应用监听就绪之间可能有间隔。采用限时轮询而非紧接重启执行一次 `ss | grep`。每个失败阶段独立标记，回滚也等待就绪。长脚本终端回显折叠不代表执行内容损坏，优先看实际阶段输出与状态。

## TCP 指纹、WebRTC、NAT

需要落地方案时先看[按设备选择出口模板](tcp-solution.md)：不同 UUID/IN-USER 可自动分流，已完成 20/20 回环验证；完整改写后端未验收。若在 VLESS 后再接 mirror，只能复制新建连接，不能恢复手机/Windows 原始 SYN。

- Linux内核Tailscale出口转发原始连接；VLESS代理由VPS重新建立TCP，网站可看到Linux TCP特征而UA仍是Windows。TUN不改变VLESS的这种语义。
- MTU/MSS改变尺寸，REALITY `client-fingerprint`改变外层TLS；两者都不是网站所见TCP操作系统指纹的完整解决方案。
- WebRTC需分辨运营商公网IP、VPS出口、私网候选与mDNS。NAT4描述映射特性，不等于泄露。
- NAT4 排查先前暂停；当晚已恢复 MTU、TCP 指纹和 CDN 资料研究。详见[网络研究与实验记录](network-research.md)，将 TCP SYN、内外层 TLS、DNS/出口与浏览器协议分开。指纹改写未部署，不把 eBPF/NFQUEUE 一键脚本直接装进生产。


## UID检查失败与回滚报错

先区分账户名/数字UID表示不同与实际身份不符。读取当前MainPID和该进程UID，不仅比较systemd配置字符串。重启后一次过早读取可能遇到暂态，必须有界等待当前进程及其监听；超过期限仍不匹配才失败。回滚使用同样过早检查也可能误报，不能仅据错误名判断恢复结果。

续装先核对现有服务、配置、guard、目录与当前版本，记录哪些是首次操作的残留。不要为绕过“路径存在”而删除所有内容。实际案例在核对残留后续装成功，不能推出所有类似故障都可忽略。

## 订阅下载正常但规则或节点异常

分别验证订阅HTTPS、内容格式、CRV选中配置、MRS下载、节点认证与实际策略匹配。当前Direct模式下下载完成不证明规则生效；TUN关闭也不能证明浏览器UDP接管。测试完成切回Tailscale只代表恢复网络，不应要求用户为确认界面状态反复重测已记录结果。

## 证书已签发但公网仍不通

DNS-01绕过的是CA验证时的入站80/443要求，不修复订阅服务端口。核对Caddy部署、served证书和公网指定端口。健康页成功也不是含凭据订阅内容已发布的证明。完整步骤见[dns01-subscription.md](dns01-subscription.md)。


## 检测站显示远端 CDN 或 DNS 国家不同

先记录实际出口、目标域名、IPv4/IPv6、HTTP 协议、解析器、远端地址、colo 与耗时。DNS 映射选点、Cloudflare Anycast、错误代理路径是不同问题；地理库标签和单次“就近”评级都不能证明物理路由。详细拆解与轻量实验见[网络研究](network-research.md)。独立云测试环境的结果不能代替用户设备或生产 VPS。

## 模板与运行状态不一致

读取 CRV 合并后的有效配置，不只看源文件。基础生成器没有完整 DNS 接管方案、TUN 默认关闭，分类组默认走 VPS；全局覆写、个人规则和客户端选择都可能改变结果。重新生成会漏掉 owner 已上线的 SSH 精确直连例外，先做脱敏结构差异比较再计划发布。
