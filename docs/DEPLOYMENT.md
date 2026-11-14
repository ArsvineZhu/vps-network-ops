# 部署

## 从出厂系统部署新节点

自动部署支持 Ubuntu 24.04 AMD64，以 root 登录，至少需要 4 GiB 可用磁盘空间。先准备初始 SSH 地址、端口和自己的管理公钥；支持首次密码登录，公钥登录验证成功后再禁用密码。保留供应商的 SSH 端口。

本机在仓库根目录执行：

```powershell
uv sync --locked
uv run vps-ops deploy init C:/private/node.yaml
uv run vps-ops deploy apply C:/private/node.yaml
```

`init` 提示填写以下模式之一：

| 模式        | 安装内容                                                | 额外准备                            |
| ----------- | ------------------------------------------------------- | ----------------------------------- |
| `tailscale` | 系统更新、SSH、防火墙、Tailscale 出口节点               | 登录 Tailscale 并批准出口节点       |
| `mihomo`    | 系统更新、SSH、防火墙、三种协议、双指纹出口、订阅与证书 | 域名、公网 IPv4、邮箱、DNS API 凭据 |
| `both`      | 两组能力，共用系统初始化                                | 上述全部                            |

仅 Tailscale 无需域名或证书。Mihomo 即 Clash 内核，服务器安装代理入口；设备上的 Clash 客户端由你导入订阅。

配置示例（仅 Tailscale）：

```yaml
mode: tailscale
target: root@203.0.113.10
port: 22
name: my-vps
public_key: C:/Users/YourName/.ssh/id_ecdsa_sk.pub
identity: C:/Users/YourName/.ssh/id_ecdsa_sk
```

Mihomo 或 both 另需：

```yaml
mode: both
domain: node.example.com
public_ipv4: 203.0.113.10
email: you@example.com
dns_provider: dnspod
# 可选：不指定时在 apply 中隐藏输入凭据。
credential_file: C:/private/dns-credentials.json
```

域名 A 记录应只指向节点公网 IPv4，不使用 CDN 代理；IPv4 节点不要发布该域名的 AAAA 记录。配置、凭据文件放在仓库外的受限目录。Windows 需确认 ACL 仅允许自己的账户访问。

### DNS 服务商与凭据

DNS 插件是 acme.sh 与解析服务商联系的适配器；选择服务商即可，无需编写 API 调用。

| dns_provider | acme.sh 插件 | 凭据 JSON 字段                      |
| ------------ | ------------ | ----------------------------------- |
| cloudflare   | dns_cf       | CF_Token（可另提供 CF_Account_ID）  |
| aliyun       | dns_ali      | Ali_Key、Ali_Secret                 |
| dnspod       | dns_tencent  | Tencent_SecretId、Tencent_SecretKey |
| dnspod-token | dns_dp       | DP_Id、DP_Key                       |

DNSPod 推荐使用腾讯云 API 密钥，入口为 [API 密钥管理](https://console.cloud.tencent.com/cam/capi)。使用获准管理目标域名解析的子账号；插件字段见 [acme.sh 腾讯云插件](https://github.com/acmesh-official/acme.sh/blob/master/dnsapi/dns_tencent.sh)。凭据文件示例：

```json
{
  "Tencent_SecretId": "替换为自己的 SecretId",
  "Tencent_SecretKey": "替换为自己的 SecretKey"
}
```

已有 DNSPod Token 的用户选择 dnspod-token，文件字段改为 DP_Id、DP_Key。其他服务商将 dns_provider 设置为 acme.sh 的 dns_插件名，并通过 dns_credentials 列出对应环境变量名。所有服务商共用证书申请、安装及续期流程。

DNS-01 通过临时 TXT 记录验证域名控制权，单独测试签发无需新公网 IP。完整公网节点部署还需可访问的服务器和正确的 A 记录。本机虚拟机可验证系统和内部代理路径；公网设备到新节点的访问另行验证。不要改动正在使用的生产订阅域名，可另建测试子域。

### 执行过程与结果

apply 经原生 SSH 传输部署包，服务器本地 Ansible 安装和配置系统。部署会验证管理公钥、更新软件、按需重启，再连接并继续。首次密码登录切换到公钥和重启恢复时需要重新认证，其余任务复用连接。重装后如主机密钥发生变化，先从供应商控制台核对指纹，不跳过验证。

安装代理时自动生成两组新设备身份、独立密码和随机订阅地址。身份保存在 /etc/vps-ops/identity.json，重复执行相同配置时复用。证书申请需要 DNS API 有效权限；凭据由 acme.sh 保存用于续期；剩余有效期不足 7 天时，重复部署会触发续期。失败后修正原因，再执行同一条 apply，不删除身份和证书文件。

Tailscale 会给出网页登录地址，等待最多 15 分钟；登录后还需在控制台批准出口能力，再在设备端选择出口。超时可再次 apply 继续。

完成后进入 vps-ops>，使用：

```text
status
check
usage report
deploy show subscriptions
```

仅 Tailscale 不运行 usage report 或查看订阅。完整订阅地址仅在明确执行 show 时读取，按私有数据保存。check all 对未安装能力显示“跳过”，对已安装能力检查实际功能。原始系统命令和配置编辑使用普通 SSH 终端。

## 手工安装与高级配置

以下配置面向 Ubuntu、systemd 和 IPv4 出口。准备一台可管理的服务器、指向服务器的域名、DNS-01 证书，以及独立的设备认证信息。安装官方 Mihomo、Caddy、Tailscale、UFW、nftables、iproute2、Python 和 PyYAML；版本以各项目当前发布及服务器环境为准。

## 安装统一 CLI

本机在仓库根目录构建可安装包：

```sh
uv sync --locked
uv build --wheel
```

先在服务器普通 SSH 终端用 `sudo install -d -m 0700 /private` 创建安装包目录，再从本机上传。以下示例需要替换 IP 和 SSH 端口：

```powershell
scp -P 23899 dist/vps_network_ops-0.1.0-py3-none-any.whl root@203.0.113.10:/private/
```

同时将仓库源码放到服务器目录中。后续 `system/...` 路径均以服务器上的仓库根目录为当前目录。CLI 可单独用于已有部署；新服务器仍需继续完成下文的代理、证书与网络配置。

在服务器普通 SSH 终端执行：

```sh
sudo apt-get install python3-venv python3-yaml
sudo python3 -m venv --system-site-packages /opt/vps-ops
sudo /opt/vps-ops/bin/pip install /private/vps_network_ops-0.1.0-py3-none-any.whl
sudo ln -s /opt/vps-ops/bin/vps-ops /usr/local/bin/vps-ops
sudo install -D -m 0600 system/vps-ops.example.yaml /etc/vps-ops/config.yaml
sudoedit /etc/vps-ops/config.yaml
vps-ops --help
```

将 `subscription_host` 改为真实订阅域名，端口按 Caddy 的实际配置填写。全部配置字段见 [CLI 手册](USAGE.md)。该配置必须存在才能运行服务器检查。普通 SSH 用户执行管理命令时使用 sudo；`connect` 直接进入远程 CLI，因此需要可执行这些管理操作的登录账户。

以上为首次安装。更新已有 CLI 时只执行 pip 的安装命令并加 `--upgrade`，保留已有配置；随后重启 `mihomo-observed`，让采集器加载新代码。若 `/usr/local/bin/vps-ops` 已存在，先用 `ls -l` 确认安装位置，使用其对应 Python 环境更新，避免覆盖其他安装。

## 构建指纹组件

在 Linux 开发环境中按 [开发指南](DEVELOPMENT.md) 安装工具并运行 `make build`。将 `build/mirage-syn`、`build/syn_rewrite.o` 和仓库源码传到服务器，然后以仓库根目录为当前目录安装：

```sh
sudo install -d -m 0755 /usr/local/lib/tcpfp /usr/local/lib/tcpfp/ebpf
sudo install -d -m 0700 /etc/tcpfp
sudo install -m 0755 build/mirage-syn /usr/local/lib/tcpfp/mirage-syn
sudo install -m 0644 build/syn_rewrite.o /usr/local/lib/tcpfp/ebpf/syn_rewrite.o
sudo install -m 0755 /path/to/mihomo /usr/local/lib/tcpfp/mihomo
sudo install -m 0755 system/tcpfp/network.py system/tcpfp/resolver.py system/tcpfp/engines.py system/tcpfp/syn_capture.py system/tcpfp/syn_preflight.py /usr/local/lib/tcpfp/
sudo install -m 0700 system/tcpfp/network.sh /etc/tcpfp/network.sh
sudo install -m 0600 system/tcpfp/preflight.py system/tcpfp/fingerprint-engines.json system/tcpfp/syn-windows.json /etc/tcpfp/
```

用服务器的公网 IPv4 和出口网卡生成规则，将结果安装到 `/etc/tcpfp`：

```sh
python3 system/tcpfp/render_assets.py --public-ipv4 "$SERVER_IPV4" --wan "$WAN" --output /private/tcpfp-network
sudo install -m 0600 /private/tcpfp-network/host.nft /private/tcpfp-network/windows.nft /private/tcpfp-network/ios.nft /private/tcpfp-network/plan.json /etc/tcpfp/
```

根据 `system/tcpfp/backend.example.yaml` 分别创建 `/etc/tcpfp/windows.json` 与 `/etc/tcpfp/ios.json`。Windows 监听 `10.203.1.2:1080`，iPhone 监听 `10.203.2.2:1080`；各自使用独立 SOCKS 口令。后端文件归 root 所有，权限为 0600。

## 配置入口与防护

创建 `mihomo` 系统账户和工作目录，将官方 Mihomo 可执行文件安装为 `/usr/local/bin/mihomo`：

```sh
sudo useradd --system --user-group --home-dir /var/lib/mihomo --shell /usr/sbin/nologin mihomo
sudo install -d -o mihomo -g mihomo -m 0700 /var/lib/mihomo /var/lib/mihomo/controller
sudo install -d -o root -g mihomo -m 0750 /etc/mihomo /etc/mihomo-observed
sudo install -m 0755 /path/to/mihomo /usr/local/bin/mihomo
```

参考 `system/mihomo/config.example.yaml` 创建 `/etc/mihomo/config.yaml`，填入订阅域名、服务器公网 IPv4、REALITY 密钥、设备 UUID、各协议口令和 SOCKS 后端口令。为不同设备及协议使用不同认证信息。

配置写入后，使 Mihomo 和采集账户可读取各自文件：

```sh
sudo chown root:mihomo /etc/mihomo/config.yaml
sudo chmod 0640 /etc/mihomo/config.yaml
```

将 `system/mihomo/mihomo-guard.nft` 中的 `MIHOMO_UID`、`VPS_IPV4`、`LISTEN_PORT` 和 `SUBSCRIPTION_PORT` 替换为实际值，安装到 `/etc/nftables.d/mihomo-guard.nft`。确认 SSH 管理端口、VLESS TCP 8443、Hysteria2 UDP 8443、AnyTLS TCP 9444 和订阅 TCP 9443 的入站规则。启用 IPv4 转发，并使该设置在重启后生效。

通过 DNS-01 获取订阅域名证书。将 `system/mihomo/mihomo-tls.conf.in` 中的证书目录替换为实际目录，安装为 `mihomo.service` 的 drop-in；将 `renew-credential-refresh.sh.in` 的内容接入证书续期流程。参考 `system/caddy/Caddyfile.example` 配置 Caddy，并将订阅文件放在 `/srv/vps-subscriptions`。

安装规则配置、工具和服务单元，并在 `/etc/vps-rules/rules.yaml` 中设置订阅域名和 SSH 地址：

```sh
sudo install -d -m 0700 /etc/vps-rules
sudo install -m 0600 system/subscriptions/rules.yaml /etc/vps-rules/rules.yaml
sudo install -D -m 0644 system/subscriptions/vps-rules.service /etc/systemd/system/vps-rules.service
sudo install -D -m 0644 system/subscriptions/vps-rules.path /etc/systemd/system/vps-rules.path
sudo systemctl daemon-reload
sudo systemctl start vps-rules.service
sudo systemctl enable --now vps-rules.path
```

规则和客户端更新方式见[订阅与规则](RULES.md)。

## 安装并启动服务

```sh
sudo install -D -m 0644 system/mihomo/mihomo.service /etc/systemd/system/mihomo.service
sudo install -D -m 0644 system/mihomo/mihomo-guard.service /etc/systemd/system/mihomo-guard.service
sudo install -D -m 0644 system/mihomo/mihomo-observed.service /etc/systemd/system/mihomo-observed.service
sudo install -D -m 0644 system/mihomo/mihomo-private-controller.conf /etc/systemd/system/mihomo.service.d/40-private-controller.conf
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-network.service /etc/systemd/system/tcpfp-network.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-windows-test.service /etc/systemd/system/tcpfp-windows-test.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-ios-test.service /etc/systemd/system/tcpfp-ios-test.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-syn-windows.service /etc/systemd/system/tcpfp-syn-windows.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-syn-capture-windows.service /etc/systemd/system/tcpfp-syn-capture-windows.service
sudo install -D -m 0644 system/tcpfp/systemd/tcpfp-windows-test.service.d/20-syn-capture.conf /etc/systemd/system/tcpfp-windows-test.service.d/20-syn-capture.conf

```

按 `system/mihomo/collector.example.json` 创建 `/etc/mihomo-observed/collector.json`，设置实际监听名称和用户标签。

```sh
sudo chown root:mihomo /etc/mihomo-observed/collector.json
sudo chmod 0640 /etc/mihomo-observed/collector.json
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-guard tcpfp-network
sudo systemctl enable --now tcpfp-syn-windows tcpfp-syn-capture-windows
sudo systemctl enable --now tcpfp-windows-test tcpfp-ios-test mihomo
sudo systemctl enable --now mihomo-observed caddy tailscaled
```

服务启动后运行 `sudo vps-ops check` 和 `sudo vps-ops usage report`。完整检查需要订阅目录已有三种协议的实际节点；订阅准备方法见 [CLI 手册](USAGE.md)。确认所有检查通过、用量 fresh 为 true，再从真实设备验证连接和订阅刷新。日常更新与重启见[日常运维](OPERATIONS.md)。
