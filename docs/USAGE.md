# vps-ops 使用手册

## 新节点部署

从出厂 Ubuntu 24.04 AMD64 起步：

```powershell
uv run vps-ops deploy init C:/private/node.yaml
uv run vps-ops deploy apply C:/private/node.yaml
```

选择 tailscale、mihomo 或 both；仅 Tailscale 不需要域名和 DNS 凭据。首次密码登录、公钥切换、DNSPod 凭据和重启恢复见[部署指南](DEPLOYMENT.md)。部署成功后进入交互会话；已安装代理时用 `deploy show subscriptions` 明确读取私有订阅地址，使用 `deploy show subscriptions --json` 获取 JSON。 当前自动部署展示一条共享订阅 URL；Windows 和 iPhone 可使用同一 URL，在各自客户端内更新时自动领取对应的身份配置。

## 安装与运行位置

本机需要 Python 3.12 及以上版本、uv 和 OpenSSH。在仓库根目录执行：

```powershell
uv sync --locked
uv run vps-ops --help
```

本机可连接服务器、生成成员材料与客户端配置、处理订阅文件。系统检查、日志、服务控制、用量、DNS、软件更新和重启在 Ubuntu VPS 上执行。服务器安装见[部署指南](DEPLOYMENT.md)。服务器操作以 root 身份执行；普通 SSH 用户先登录系统终端，再运行 sudo vps-ops shell。

下面的 IP、域名和私有路径均为示例。替换为自己的配置；输入输出的父目录应已存在且只允许自己的账户访问。Linux 可用 install -d -m 0700 /private 创建目录；Windows 使用账户私有目录并检查 ACL。

## 登录和连续操作

本机运行：

```powershell
uv run vps-ops connect root@203.0.113.10 --port 23899
```

出现 vps-ops> 后，只输入子命令：

```text
status
check
usage report
logs mihomo --since "1 hour ago" --lines 30
help
```

每条命令结束后回到同一提示符，继续复用此次认证。exit 或 quit 退出。已登录普通 SSH 终端时，可执行 vps-ops shell 进入相同界面。

| connect 参数    | 含义                                    |
| --------------- | --------------------------------------- |
| target          | SSH 配置别名、主机或用户@主机           |
| --port PORT     | SSH 端口；省略时使用 OpenSSH 配置       |
| --user USER     | SSH 用户                                |
| --identity PATH | 本机密钥文件路径；空格路径加引号        |
| --wait SECONDS  | 等待 SSH TCP 端口恢复后登录；默认不等待 |

连接遵循本机 OpenSSH 配置和主机密钥验证，保活间隔 30 秒，连续失联 6 次后断开。安全密钥在登录时认证。远端必须已安装 vps-ops，且用户 PATH 能找到该命令。

交互会话只接受工具子命令。需要编辑配置或任意系统命令时，保留普通 SSH 终端并直接调用 vps-ops。持续日志期间 Ctrl+C 会结束当前 CLI 进程，通过 connect 登录时需重新连接。

## 服务器配置

默认读取 /etc/vps-ops/config.yaml，格式为 UTF-8 YAML。下面是完整字段及默认值：

```yaml
subscription_host: sub.example.com
subscription_port: 9443
subscription_root: /srv/vps-subscriptions
probe_url: https://www.cloudflare.com/cdn-cgi/trace
frontend_config: /etc/mihomo/config.yaml
services:
  - mihomo
  - mihomo-guard
  - caddy
  - tailscaled
  - mihomo-observed
  - tcpfp-network
  - tcpfp-windows-test
  - tcpfp-ios-test
  - tcpfp-syn-windows
  - tcpfp-syn-capture-windows
  - vps-rules.path
```

只写需要覆盖的字段即可。subscription_host 必须改为真实订阅域名；subscription_port 为 Caddy HTTPS 端口；subscription_root 为订阅目录。probe_url 必须返回 HTTP 200。frontend_config 指向入口配置，供日志过滤读取已知认证值。services 若提供会替换整个默认列表，也决定服务控制和日志查询允许使用的名称。

自动部署还会写入 mode，取 tailscale、mihomo 或 both。mode 缺省时按 both 处理；未显式提供 services 时根据模式派生服务列表。check all 对未启用能力显示“跳过”，不会把未安装 Mihomo 或 Tailscale 当作故障。

全局参数放在子命令之前：

```sh
vps-ops --config /private/ops.yaml status
vps-ops --json check dns
vps-ops --json usage report
```

JSON 支持 status、check、DNS 结果、usage report、logs、packages list 和订阅地址。交互会话内可写为 `--json check`，也可以使用 `status --json`、`usage report --json` 或 `logs caddy --json`。自定义服务器配置的会话从普通 SSH 终端启动：`vps-ops --config /private/ops.yaml shell`。connect 使用远端默认配置。

## 状态和功能检查

```sh
vps-ops status
vps-ops status --all
vps-ops status --service mihomo --service caddy
vps-ops status --network --firewall
vps-ops status --updates --errors
vps-ops --json status --all
vps-ops check
vps-ops check dns
vps-ops check proxy
vps-ops check subscription
vps-ops check certificate
vps-ops check tailscale
```

不带参数时，`status` 显示系统与负载、内存、根分区、服务摘要、失败单元和重启提示；需要关注的服务会单独列出。默认概览只查询这些内容。按需选择一个或多个分类：

| 参数             | 内容                                       |
| ---------------- | ------------------------------------------ |
| `--system`       | 内核、运行时间、负载、启动标识和重启提示   |
| `--resources`    | 内存、交换空间和全部挂载的磁盘             |
| `--services`     | 配置中全部服务的状态和系统失败单元         |
| `--service 名称` | 指定服务的状态，可重复；服务名必须在配置中 |
| `--network`      | TCP 监听、路由和网络空间                   |
| `--firewall`     | 防火墙规则                                 |
| `--updates`      | 待更新软件包和重启提示                     |
| `--errors`       | 最近 24 小时的系统错误数量                 |
| `--all`          | 查看全部分类                               |

分类参数可以组合，例如 `status --network --firewall`。`--service` 可与其他分类组合，限制服务列表；同名服务允许带或不带 `.service` 后缀。`status --help` 显示参数说明。报告中的“读取失败”表示该项采集未成功，其他项目仍会显示。

`--json` 输出所选范围的机器数据，和文本显示的数据来源一致。`--json status` 现在输出默认概览；需要原先的完整字段时，使用 `--json status --all`。完整 JSON 中的 `服务` 值保留原有 systemd 字段格式。

check 默认等同 check all，单项失败后继续检查其他项：

| 范围         | 实际检查                                                                                                |
| ------------ | ------------------------------------------------------------------------------------------------------- |
| all          | 配置服务均 active，并执行以下全部检查                                                                   |
| dns          | 两个网络空间解析 www.cloudflare.com，并访问 probe_url                                                   |
| proxy        | 两个认证 SOCKS 出口、Windows 队列与捕获、iPhone eBPF，以及三个协议各一个订阅节点的临时客户端 HTTPS 请求 |
| subscription | 对目录中每份 YAML 请求 /s/文件名，连接本机 Caddy，校验域名和 TLS，要求 HTTP 200                         |
| certificate  | Mihomo 运行凭据中的证书主机名和有效期，要求剩余超过 7 天                                                |
| tailscale    | 本机 Tailscale BackendState 为 Running                                                                  |

结果显示“通过”“警告”“失败”或“跳过”；警告表示仍需操作，例如批准 Tailscale 出口能力。JSON 每项包含 name、state、detail。check 成功返回 0，有失败返回 1。参数错误通常返回 2；底层命令可能保留自己的退出码。status 返回成功表示报告生成，仍需阅读其中的失败状态。

完整检查使用项目当前部署：网络空间 tcpfp-windows-test 和 tcpfp-ios-test，指纹工具在 /usr/local/lib/tcpfp，Mihomo 在 /usr/local/bin/mihomo。两个后端须运行并提供 systemd 凭据；订阅中须有 vless、hysteria2、anytls 节点。临时客户端配置结束后删除。协议探测从服务器发起；设备到 VPS 的连接问题还需在对应设备重现。

## 日志、服务和用量

```sh
vps-ops logs mihomo --since "1 hour ago" --lines 50
vps-ops logs tcpfp-syn-windows --follow
vps-ops logs caddy --json --lines 10
vps-ops service status mihomo
vps-ops service restart mihomo
vps-ops usage report
vps-ops --json usage report
```

logs 默认最近 24 小时、最多 50 行；--since 使用 journalctl 时间表达式；--follow 持续输出。普通日志按原行显示，应用输出的 JSON 对象会分层排版。`--json` 改用 journalctl 的 JSON 字段，每行一个对象，适合程序读取。两种方式都会过滤入口配置中的已知认证值、订阅路径和 HTTP URL；系统日志仍按私有数据处理。

service 支持 status、start、stop、restart，服务名使用配置条目，如 mihomo 或 vps-rules.path。`service status` 显示 systemd 的详细服务状态；查看最近日志使用 `logs`。修改入口配置后先在普通终端检查：

```sh
/usr/local/bin/mihomo -t -d /var/lib/mihomo -f /etc/mihomo/config.yaml
vps-ops service restart mihomo
vps-ops check proxy
```

用量默认按用户分行显示采样状态、上次成功时间、上传和下载量及活跃连接；数值同时显示易读单位和精确字节数。机器输出中的 fresh 表示近期采样成功，last_success 带时区，upload_bytes、download_bytes 为累计字节数；active_connections 在采样过期时为 null；ever_observed 表示用户是否曾被观察。近似计数保存在原有 SQLite 数据库。数据未更新时查看 logs mihomo-observed，并确认控制套接字可用。

usage serve [--config PATH] 由 systemd 运行采集器；usage report [--config PATH] 指定采集配置，默认 /etc/mihomo-observed/collector.json。已有采集服务运行时只调用 report。

## DNS 诊断和修复

```sh
vps-ops dns diagnose
vps-ops dns repair
vps-ops check proxy
```

diagnose 检查默认解析与 HTTPS；repair 为两个空间写入 /etc/netns/空间名称/resolv.conf，指定 nameserver 1.1.1.1 和超时，再执行检查。指纹网络初始化也维护这些文件；宿主机解析配置保持原状。

如果仍失败，普通终端运行 ip netns list，查询 vps-ops logs tcpfp-network。空间不存在时先处理初始化失败；空间存在时检查上游 DNS、公网和转发规则。不要将宿主机的 127.0.0.53 复制进空间。

## 更新、重启和恢复

```sh
vps-ops check
vps-ops packages list
vps-ops packages upgrade
vps-ops reboot
```

packages list 使用现有索引。upgrade 检查 dpkg、刷新索引、显示模拟结果，然后直接更新；禁止删除包，保留本地配置，遵循保留和分阶段发布策略。它不升级 Ubuntu 大版本、不自动清理。由包管理器管理的 Caddy 等也会按候选版本更新；独立安装的二进制不在更新范围。

reboot 直接重启，SSH 断开。回到本机执行：

```powershell
uv run vps-ops connect root@203.0.113.10 --port 23899 --wait 300
```

登录后运行 status、check、usage report。确认启动标识改变、失败服务为 0、出口和入口检查通过、订阅可读、fresh 为 true。--wait 只等待管理端口，服务恢复由 check 验证。

按失败项查日志：初始化查 tcpfp-network，Windows 队列查 tcpfp-syn-windows，后端查 tcpfp-windows-test 或 tcpfp-ios-test，订阅查 caddy。修复后运行相应检查。

## 生成客户端配置

准备 /private/node.json：

```json
{
  "server": "203.0.113.10",
  "port": 8443,
  "uuid": "11111111-1111-4111-8111-111111111111",
  "servername": "www.example.com",
  "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "short_id": "aabb",
  "name": "My-VPS",
  "fingerprint": "chrome"
}
```

替换全部示例连接值。server 为公网 IP 或域名，servername 为 REALITY 的 TLS 主机名，public_key 为服务端 REALITY 公钥，uuid 为已注册用户身份。short_id 为偶数位十六进制，最长 16 位。name、fingerprint 可省略，默认 node、chrome；指纹还支持 firefox、safari、ios、android、edge、random。不接受额外字段。本地文件生成仅使用输入 UUID，设备自动选择发生在服务器远程订阅更新时。

复制 system/subscriptions/rules.yaml 到 /private/rules.yaml，填写 base-url、variables.server_ipv4、variables.ssh_port，策略说明见[订阅与规则](RULES.md)。运行：

```sh
vps-ops profile generate /private/node.json /private/profile.yaml --policy /private/rules.yaml
vps-ops profile generate /private/node.json /private/provider.yaml --kind provider
```

默认 --kind profile 生成完整配置，必须提供 --policy。provider 只输出节点列表，可被其他配置引用。此离线命令不会检测设备，也不会为单个 UUID 自动生成两套服务器认证身份。自动部署生成的远程订阅提供一个共享链接，下载时通过客户端 User-Agent 在已有 WIN/Apple 身份间选择。输出文件必须不存在，父目录已存在。生成器提供 VLESS TCP REALITY 节点，文件为 JSON 形式的 YAML。生成后在客户端导入并启用。

## 创建成员材料

模板沿用节点描述，去掉 uuid、name，只保留 server、port、servername、public_key、short_id 和可选 fingerprint：

```sh
vps-ops member create /private/server.json tablet /private/tablet --policy /private/rules.yaml
```

标签为 1 至 40 位字母、数字、下划线或连字符。新成员生成与平台注册分离；此命令只生成待注册凭据，自动切换 WIN/Apple 出口需服务端已经给该订阅持有者配置相应的两套身份。输出目录必须不存在，父目录已存在。生成：

| 文件                     | 用途                             |
| ------------------------ | -------------------------------- |
| profile.yaml             | 使用新 UUID 的完整配置           |
| provider.yaml            | 同一身份的节点列表               |
| server-user.pending.json | 待加入 VLESS listener 的用户对象 |
| .gitignore               | 排除目录中的生成文件             |

将 pending 文件的用户对象加入目标 VLESS listener 的 users，再按设备身份配置对应路由。运行 Mihomo 配置检查、重启服务，从客户端导入并测试。远程订阅另外按 Caddy 约定发布；此命令只生成本地材料。

## 应用订阅策略

```sh
vps-ops subscription apply /private/profile.yaml --policy /private/rules.yaml
vps-ops subscription apply /private/profile.yaml --policy /private/rules.yaml --output /private/updated.yaml
vps-ops subscription apply --directory /srv/vps-subscriptions --policy /etc/vps-rules/rules.yaml
```

选择单文件或目录，目录处理其中所有 .yaml，不能配合 --output。省略 --output 时原位更新。保留节点和 node-group 指定的唯一选择组，替换其余组、规则源、规则和 hosts。写入采用原子替换，已有文件保留所有者与权限。更新后让客户端刷新订阅。

## 证书文件和监听等待

```sh
vps-ops certificate check --cert /private/fullchain.pem --hostname sub.example.com --min-days 7
vps-ops wait listener mihomo 8443 --seconds 10
```

证书文件检查需要 OpenSSL，验证首张证书主机名与有效期；--min-days 默认 7，范围 0 至 3650。实际 HTTPS 部署用 check subscription 验证。

监听等待依赖 Linux、systemd、ss，要求 TCP 监听归属于指定服务当前 MainPID，不发起连接。--seconds 默认 10，范围大于 0 且不超过 120。controller check-directory 是服务启动前的内部检查，由服务单元调用。
