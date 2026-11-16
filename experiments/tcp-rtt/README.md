# TCP RTT 实验

独立的真实链路采集、TCP_INFO 探针及 ACK 时序实验。生产 `vps-ops` 不加载这些程序。

## 准备和编译

需要项目要求的 Go 工具链和 Python 3.12+。Linux 拓扑还需要 root、iproute2、ethtool、nftables、tcpdump，以及 Mihomo 二进制。抓包分析使用可选依赖组：

```sh
uv sync --group tcp-rtt
cd experiments/tcp-rtt
go build -o ../../temp/tcp-rtt-probe .
cd ../..
```

Windows 将输出文件名改为 `tcp-rtt-probe.exe`。在 Windows 交叉编译 Linux 二进制时，先设置 `$env:GOOS='linux'`，编译后执行 `Remove-Item Env:GOOS`。

## Windows 真实代理链路

保持 CRV 运行，使用当前 `Nodes` 策略组。每种协议默认采集 30 条新连接、30 条复用请求，另保留复用连接的首个冷请求。结束或中断后恢复原节点选择。

```powershell
uv run python experiments/tcp-rtt/baseline.py --probe temp/tcp-rtt-probe.exe --output temp/tcp-rtt/windows --platform Windows --observer cleanip
uv run python experiments/tcp-rtt/report.py temp/tcp-rtt/windows --source observer
```

`--platform Apple` 验证同一 Windows 客户端通过 Apple 身份的三个出口；手机真机结果另行采集。`--observer onems` 读取第二个观测点的 Cloudflare TCP RTT。检测接口的原始 JSON 和请求错误都会保存。

控制器默认发现唯一的 CRV 生产命名管道。有多个实例时，通过 `--pipe` 指定管道路径。输出目录必须不存在，避免覆盖上一轮数据。

### 独立直连测量

`--interface-index` 仅绑定测试 socket 的出网网卡，保留系统默认路由及其他程序的联网方式。先查看带默认网关的物理接口，取得其索引：

```powershell
Get-NetIPConfiguration | Select-Object InterfaceAlias,InterfaceIndex,IPv4DefaultGateway
# 将地址及索引换成自己的 VPS 和物理网卡。
temp/tcp-rtt-probe.exe -mode tcp -address 203.0.113.10:9443 -interface-index 9 -count 30
```

TCP 模式记录连接握手耗时。经过 TUN 的普通 socket 可能只测到本地接管栈，因此本机至 VPS 的独立探测应指定物理接口。

直接访问观测站时，`-url` 保留正确的 TLS 主机名，`-connect-address` 提供真实解析地址，避免把 fake-ip 发往物理网卡；`-ca ""` 使用系统信任库：

```powershell
$dns = Invoke-RestMethod -Headers @{Accept='application/dns-json'} 'https://cloudflare-dns.com/dns-query?name=fp.cleanip.io&type=A'
$probeIp = ($dns.Answer | Where-Object type -eq 1 | Select-Object -First 1).data
temp/tcp-rtt-probe.exe -url https://fp.cleanip.io:8443/api/probe -ca '' -connect-address "${probeIp}:8443" -interface-index 9 -count 31
```

## 隔离 ACK 实验

```sh
sudo python3 experiments/tcp-rtt/lab.py run \
  --probe temp/tcp-rtt-probe --mihomo /path/to/mihomo \
  --output temp/tcp-rtt/ack100 --count 30 \
  --ack-policy data --ack-delay 100 --timestamps 0 \
  --client-delay-ms 100 --server-delay-ms 25 --rate-mbit 100 --queue-limit 10000
uv run python experiments/tcp-rtt/report.py temp/tcp-rtt/ack100
```

拓扑为 `client → wire1 → edge/Mihomo → wire2 → site/HTTPS`，共五个命名空间，均以 `rtt-` 开头。模拟链路的 bridge 端口承担延迟和限速；实验接口关闭 TSO/GSO/GRO。网络与宿主公网没有连接。这里的 Mihomo 使用最小 HTTP CONNECT 出站隔离 TCP 机制；三种加密入口与两套指纹身份由 Windows 真实链路采集验证。

| 参数                                      | 含义                                                                        |
| ----------------------------------------- | --------------------------------------------------------------------------- |
| `--ack-policy none`                       | 相同拓扑、不加载 ACK 队列的对照                                             |
| `--ack-policy handshake`                  | 延迟第三次握手的纯 ACK                                                      |
| `--ack-policy data`                       | 延迟确认新数据的普通纯 ACK                                                  |
| `--ack-delay`                             | 额外 ACK 延迟，毫秒；0 是同一处理路径的零延迟对照                           |
| `--client-delay-ms` / `--server-delay-ms` | 两段链路各自的单向延迟；ACK 实验默认均为 25 ms                              |
| `--rate-mbit` / `--queue-limit`           | 每个模拟链路方向的带宽及队列长度；0 带宽表示不限速                          |
| `--size`                                  | 响应字节数，默认 1024，最大 4194304                                         |
| `--timestamps` / `--cc`                   | 实验 TCP 栈的时间戳开关、拥塞算法；默认 1 / bbr                             |
| `--handshake-control`                     | 在 edge 直接发起新 TCP，等待 150 ms 才发送 TLS，用于观察握手纯 ACK 独立生效 |

分类器使用项目已有的 go-nfqueue 库。队列 9500 仅匹配 edge 到实验服务端的 TCP 4433，跟踪双方 SYN 序列号，排除携带数据、SACK、重复确认和纯窗口更新。计时由独立异步 verdict 控制，不改包内容及生产 SYN 引擎。

完整运行入口：

```sh
sudo bash experiments/tcp-rtt/run.sh temp/tcp-rtt-probe /path/to/mihomo temp/tcp-rtt/full
```

入口覆盖 ACK 延迟阶梯、两种时间戳设置、三种响应大小、握手等待对照和整条服务端链路延迟对照。单个条件失败后继续其他条件，最后以非零退出码报告存在未完成的条件。客户端记录直接写入 JSONL，超时前的样本保留。

## 本地 WireGuard 与指纹对照

`wireguard.py` 在 Linux / WSL 内创建 `wg-client-lab → wg-server-lab → wg-site-lab` 三个隔离网络空间，比较 Mihomo SOCKS 代理与独立 WireGuard 转发。客户端到服务器每个方向模拟 100 ms，服务器到目标每个方向模拟 25 ms；目标运行可观察 `TCP_INFO` 的 HTTPS 服务。客户端验证实验 CA，记录新建与复用连接的请求耗时。实验无需 Tailscale 账户或公网 VPS。

除前述依赖外，需要 `wireguard-tools` 和支持 WireGuard 的 Linux 内核。先在 Linux 中执行准备部分的 `go build`；同目录的 `info_linux.go` 会自动编入探针，提供目标端 TCP_INFO 采样。运行：

```sh
sudo python3 experiments/tcp-rtt/wireguard.py \
  --mihomo /path/to/mihomo --probe temp/tcp-rtt-probe \
  --output temp/tcp-rtt/wireguard --count 30
uv run python experiments/tcp-rtt/report.py temp/tcp-rtt/wireguard
```

同时检查三层转发的 SYN 指纹时，先构建项目的 `mirage-syn`，再指定引擎及配置：

```sh
sudo python3 experiments/tcp-rtt/wireguard.py \
  --mihomo /path/to/mihomo --probe temp/tcp-rtt-probe \
  --fingerprint build/mirage-syn --profile windows \
  --output temp/tcp-rtt/wireguard-windows --count 30
```

`--profile ios` 选择 Apple 选项布局。引擎仅附着在隔离服务器到目标的转发路径，不修改宿主或生产服务。输出包含两条客户端 JSONL、目标的 `server.jsonl`、`destination.pcap`、进程日志和 `environment.json`；可用抓包分析工具检查 SYN 选项、TTL 与 TCP 校验和。正常结束或中断后清理实验进程、空间和临时密钥，保留指定输出目录。

## 三层出口对照

在隔离的 Linux / WSL 中运行，主机原有默认路由保持不变。准备[官方 Tailscale Linux 静态包](https://pkgs.tailscale.com/stable/)中的二进制目录，并确认 VPS 已宣告和获批出口能力：

```sh
sudo bash experiments/tcp-rtt/layer3.sh /path/to/tailscale-binaries eth0
```

脚本打印 socket 路径，保持该终端运行。在另一个终端，将 `SOCKET` 设为打印的路径，`EXIT_IP` 设为 VPS 的 `tailscale ip -4` 地址，然后授权临时节点。必须选择与 VPS 相同的 Tailscale 网络。

```sh
sudo ip netns exec rtt-exit /path/to/tailscale-binaries/tailscale --socket="$SOCKET" up \
  --hostname=vps-ops-rtt-lab --accept-dns=false --accept-routes=false --exit-node="$EXIT_IP"
sudo ip netns exec rtt-exit temp/tcp-rtt-probe -ca '' -url https://fp.cleanip.io:8443/api/probe -count 31
sudo ip netns exec rtt-exit /path/to/tailscale-binaries/tailscale --socket="$SOCKET" ping --c=2 --until-direct=false "$EXIT_IP"
```

记录实际直连或 DERP 路径。若 WSL 外层仍经过 Windows 的代理，这一条件也要保留在结果中。VPS 使用内核转发；`--tun=userspace-networking` 的出口会重新建 TCP，不用于这项对照。

脚本使用内存状态注册临时节点。Ctrl+C 或正常结束后，清理实验空间、NAT、临时状态并恢复先前的 WSL 转发设置。

## 输出、分析和清理

- 客户端 JSONL：请求 ID、总耗时、TTFB、连接复用、HTTP 版本、错误及观测站原始响应。
- 服务端 JSONL：accept、TLS 后、请求到达、首次响应、写完及确认到达后的 TCP_INFO；确认等待最多 2 秒。
- 抓包、队列事件、qdisc 计数及环境 JSON：用于关联 ACK、丢包、版本和实验参数。`run_completed` 表示该条件是否跑完，不表示性能通过。
- `report.py` 默认输出表格；加 `--json` 输出同一份汇总数据。`--source observer` 读取检测站结果。Cloudflare 的 0 ms 保留为有效数值，HTTP/3 不使用 TCP RTT 字段。

```sh
uv run --group tcp-rtt python experiments/tcp-rtt/packets.py temp/tcp-rtt/ack100/rtt-site.pcap
uv run --group tcp-rtt python experiments/tcp-rtt/packets.py temp/tcp-rtt/ack100/rtt-site.pcap --acks
uv run python experiments/tcp-rtt/report.py temp/tcp-rtt/ack100 --json
sudo python3 experiments/tcp-rtt/lab.py cleanup
```

抓包分析默认端口 4433，真实观测站可用 `--port` 指定。分析 VPS 公网接口上的 SYN-ACK 到 ACK 间隔时，量到的是该接口之后的确认等待，不是目标端完整 RTT。

实验自动清理进程与五个空间；强制终止后可运行 `cleanup`。输出目录保留供研究使用，真实 IP、抓包及客户端材料不提交仓库。
