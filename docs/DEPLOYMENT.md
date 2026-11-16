# 部署新节点

`Default` 是默认的普通出口，不套用 Windows 或 Apple 指纹模拟；Linux、Android 等设备可直接选择它。每台设备的订阅同时保留 Default、Windows、Apple 三种出口，识别到 Windows 或 Apple 客户端时可调整默认选择。

自动部署面向全新 Ubuntu 24.04 AMD64，也支持用同一份配置更新已由本工具管理的节点。部署入口会更新系统、保留 SSH 端口、安装管理公钥、验证公钥登录、禁用密码登录、开启防火墙，并按选择安装网络服务。需要重启时会等待 SSH 恢复后继续。

## 准备

服务器需要 root SSH 登录权限、至少 4 GiB 可用磁盘空间，以及供应商控制台访问方式。先准备服务器地址、初始 SSH 端口和自己的公钥文件；首次登录可以使用密码，后续使用公钥。安全密钥可直接通过系统 OpenSSH 使用。

本机安装 [uv](https://docs.astral.sh/uv/getting-started/installation/) 和 OpenSSH，下载仓库后进入根目录。uv 会自动下载项目所需的 Python 并准备依赖，无需先安装 Python，也无需本机安装 Go、Ansible 或 clang。配置与凭据放在仓库外的私人目录；Windows 下将该目录的 ACL 限制为自己的账户。

还没有 SSH 密钥时，在本机 PowerShell 或终端执行：

```sh
ssh-keygen -t ed25519
```

按回车使用默认文件位置，并为私钥设置口令。已有同名文件时选择新的文件名，保留原有密钥。在 Windows 上，新公钥通常为 `C:/Users/你的用户名/.ssh/id_ed25519.pub`，私钥为同目录的 `id_ed25519`；Linux 或 macOS 对应 `~/.ssh/id_ed25519.pub` 和 `~/.ssh/id_ed25519`。向导的公钥项填写 `.pub` 文件，私钥项填写无 `.pub` 后缀的文件。首次部署会把公钥安装到服务器；已有可用密钥可直接使用。

安装 Clash 服务还需准备：

- 一个由自己管理的域名，A 记录只指向这台服务器的公网 IPv4，关闭 CDN 代理，并移除该域名的 AAAA 记录。
- 证书联系邮箱。
- DNS 服务商的 API 凭据，权限覆盖这个域名的 TXT 记录。下文列出字段。

仅安装 Tailscale 无需域名、邮箱和 DNS 凭据。

## 一条命令开始

在本机仓库根目录执行：

```powershell
uv run vps-ops deploy setup C:/private/node.yaml
```

向导默认选择 `2 Clash（Mihomo）`，同时启用指纹和完整 TCP 链路（WireGuard），无需创建 Tailscale 账户。选择 `1` 可仅安装 Tailscale，选择 `3` 可同时安装。向导依次询问接入方式、网络能力、SSH、证书与首台设备名称及默认出口，然后保存私有配置并立即部署。按提示填写即可，不需要 AI 参与或手写 YAML：

| 接入方式    | 设备怎样使用                     | 安装内容                                      |
| ----------- | -------------------------------- | --------------------------------------------- |
| `tailscale` | 登录 Tailscale，选择这台出口节点 | Tailscale 出口与管理通道                      |
| `mihomo`    | 在 Clash 客户端导入一个订阅地址  | Mihomo 三种协议、设备订阅、证书续期和累计用量 |
| `both`      | 两种方式均可使用                 | 上述能力共用系统维护和防火墙                  |

Mihomo 是 Clash 内核。选择 Clash 时，服务器始终保留 VLESS、Hysteria2 和 AnyTLS 三种接入协议。两项能力独立选择，所需组件由部署自动安装：

| 能力                 | 选择后会发生什么                                                                                                                                       |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| TCP 指纹             | 为设备出口规范化 Windows 或 Apple 的 TCP 建连特征。Clash 三种代理协议使用独立出口；三层转发路径按设备支持的 TCP 选项选择适用指纹。                     |
| 完整 TCP 链路（RTT） | 每台设备的订阅增加 Default、Windows、Apple 三个 WireGuard 节点，并默认使用对应节点，让目标网站测得设备到目标的完整 TCP 往返路径。无需 Tailscale 账户。 |

Tailscale 使用原生三层转发，本身包含设备到服务器的 TCP 延迟；完整链路开关决定是否额外安装 Clash 使用的 WireGuard 节点。仅 Tailscale 时向导不再询问这一项。IPv4 出口启用指纹时，携带 TCP 时间戳的连接采用 Apple 选项布局，未携带时间戳的连接采用 Windows 布局。Windows 原生连接可继续使用未协商时间戳的方式。WireGuard 节点承载 IPv4 流量。

首次 SSH 主机密钥需要核对；公钥验证时可能需要再次触摸安全密钥。系统更新触发重启后会重新连接。其余部署步骤复用当前 SSH 连接。

## 先保存并查看计划

需要先检查选择时，分别执行：

```powershell
uv run vps-ops deploy init C:/private/node.yaml
uv run vps-ops deploy plan C:/private/node.yaml
uv run vps-ops deploy apply C:/private/node.yaml
```

计划列出已选服务、公网端口以及登录或证书准备。以下是仅 Clash、同时启用指纹和延迟的完整配置示例：

```yaml
mode: mihomo
features:
  fingerprint: true
  rtt: true
target: root@203.0.113.10
port: 22
name: my-vps
device:
  name: My device
  platform: Windows
public_key: C:/Users/YourName/.ssh/id_ed25519.pub
identity: C:/Users/YourName/.ssh/id_ed25519
public_ipv4: 203.0.113.10
domain: node.example.com
email: you@example.com
dns_provider: dnspod
credential_file: C:/private/dns-credentials.json
```

`identity` 可留空，使用本机 OpenSSH 配置。将 `mode` 改为 `both` 即增加 Tailscale。仅 Tailscale 的配置可删去 `public_ipv4`、`domain`、`email`、`dns_provider` 和 `credential_file`。`features.fingerprint` 和 `features.rtt` 分别控制两项能力；向导默认启用。原有未写 `features` 的配置保持原选择：Clash 开启指纹，WireGuard 不启用。

## DNS 服务商与证书

所有服务商使用同一套 acme.sh DNS-01 申请、安装与续期流程。DNS-01 会临时创建 TXT 记录，无需开放 HTTP 验证端口。

| `dns_provider` | acme.sh 插件  | 凭据 JSON 字段                          |
| -------------- | ------------- | --------------------------------------- |
| `cloudflare`   | `dns_cf`      | `CF_Token`，可另提供 `CF_Account_ID`    |
| `aliyun`       | `dns_ali`     | `Ali_Key`、`Ali_Secret`                 |
| `dnspod`       | `dns_tencent` | `Tencent_SecretId`、`Tencent_SecretKey` |
| `dnspod-token` | `dns_dp`      | `DP_Id`、`DP_Key`                       |

DNSPod 使用腾讯云 API 密钥，入口为 [API 密钥管理](https://console.cloud.tencent.com/cam/capi)。为获准管理目标域名解析的子账号创建密钥，写入私人 JSON 文件：

```json
{
  "Tencent_SecretId": "替换为自己的 SecretId",
  "Tencent_SecretKey": "替换为自己的 SecretKey"
}
```

已有 DNSPod Token 时选择 `dnspod-token`。其他服务商将 `dns_provider` 写为 acme.sh 的 `dns_插件名`，并在 `dns_credentials` 中列出对应环境变量名。字段要求见对应的 [acme.sh DNS 插件](https://github.com/acmesh-official/acme.sh/tree/master/dnsapi)。不指定凭据文件时，部署会隐藏输入所需字段；非交互部署必须提供文件。

证书和续期凭据保留在服务器，定时续期后自动刷新服务证书。重复部署复用仍有效的证书，剩余有效期不足 7 天时执行续期。

## 部署结果与设备导入

Clash 部署成功后会进入 `vps-ops>` 管理会话。首次向导登记的设备已保存，再次部署不会新增设备或恢复已经撤销的设备。在这个管理会话输入：

```text
status
check
device list
device show "My device"
usage report
```

`device list` 显示设备名称、ID、默认出口和状态，不显示私有链接。`device show 名称或ID` 明确读取该设备的订阅地址。将地址只导入这台物理设备的 Clash 客户端并启用 TUN/VPN。不同物理设备各自登记、各用各的链接；每个链接都包含 Default、Windows 和 Apple 三套出口配置，可同时使用。两台 Windows 设备也有独立 WireGuard 密钥与地址，可以同时连接。

启用完整 TCP 链路（RTT）时，每个设备链接共十二个节点；未启用时共九个节点。订阅更新请求的设备标识只调整默认节点和 TUN 设置，不改变此设备的认证凭据。识别失败时采用登记时保存的默认出口。在客户端的 `Nodes` 中可手动选择 `Default · WireGuard`、`Windows · WireGuard` 或 `Apple · WireGuard`，以及需要的其他协议。关闭 TCP 指纹时，这些标签用于选择此设备的不同认证配置，出口使用普通系统 TCP 栈。

为第二台设备登记独立订阅，在管理会话输入：

```text
device add
```

按提示填写唯一设备名称与默认出口，再用 `device show 名称或ID` 取链接。也可以直接输入 `device add "Second laptop" --platform Windows`。新增会即时更新代理认证、WireGuard peers 和订阅文件，其他设备继续连接。普通服务器 SSH 终端使用 `vps-ops device add`、`vps-ops device list` 和 `vps-ops device show "Second laptop"`；这些操作在服务器执行。

撤销丢失或不再使用的设备：

```text
device revoke "Second laptop"
```

撤销后，该设备的三协议凭据、现有代理连接、WireGuard peers 和私有订阅 URL 一并失效；旧地址返回 404。其他设备不受影响，撤销设备的累计用量与名称仍保留。撤销记录清除密钥、密码和订阅令牌；再次为物理设备登记会创建新的独立身份。全部设备撤销后，公网代理监听入口 停止提供认证入口，随后 `device add` 可重新开放有认证的入口。

如设备变更已保存而运行态更新报错，修正错误后在原管理会话运行 `device sync`。该命令同步已保存的注册表，无需重建安装包或重复添加设备。`deploy show subscriptions` 也可明确列出全部活跃设备的链接，按私人资料保存。

WireGuard 使用 UDP 51820。服务器或本地网络需要允许该端口；受限网络可在 `Nodes` 中选择 VLESS、AnyTLS 或 Hysteria2。这三种代理协议使用各自 TCP 连接，不提供 WireGuard 的完整 TCP 链路。`check` 对 WireGuard 读取 peer 配置和真实握手，不用设备私钥发起服务端探测；尚未连接的设备显示等待客户端，任一指纹配置出现握手即可满足该设备的握手检查。

Tailscale 安装后用约 5 秒发起登录，再显示网页登录地址。尚未授权时结果标为“节点已配置，Tailscale 等待授权”，并保留当前管理会话；同时选择 Clash 时，已通过检查的 Clash 和 WireGuard 可以立即使用。打开登录地址，在管理控制台批准出口能力，然后在当前会话执行 `check tailscale`，无需重新部署、编译或再次 SSH 认证。Tailscale 就绪后再在设备上选择此出口。仅 Tailscale 使用 `status` 和 `check`，无需导入 Clash 订阅。

默认公网端口：Clash 使用 TCP 8443、UDP 8443、TCP 9444、TCP 9443；WireGuard 使用 UDP 51820；Tailscale 使用 UDP 41641。现有 SSH 端口始终保留。

## 重试、改选与维护

失败后按错误修正 SSH、DNS 或网络问题，再执行相同的 `deploy apply`。`init` 只新建配置；已有配置可用 `configure` 修改，重试使用 `apply`。Tailscale 等待网页登录时保留会话，授权后直接运行 `check tailscale`；实际部署错误修正后才需要重试 `apply`。服务器更换后若 SSH 主机密钥改变，先通过供应商控制台核对指纹，再更新本机记录。

改变接入方式、指纹或完整链路时，再运行同一条 `deploy setup C:/private/node.yaml`。向导读取原有选择作为默认值，保留之前的 Tailscale、Clash 或两者同装选择，只需改选能力；默认保留 SSH、域名、邮箱和 DNS 凭据文件位置，确认需要修改这些信息时才再次询问。增加 Clash 而原配置缺少域名时，会自动补问所需信息。

只保存改选结果、暂不部署时，在本机执行：

```powershell
uv run vps-ops deploy configure C:/private/node.yaml
uv run vps-ops deploy plan C:/private/node.yaml
uv run vps-ops deploy apply C:/private/node.yaml
```

可选文件路径可输入 `-` 清除，其他项目按回车保留原值。配置通过校验后才替换保存。部署会停用不再选择的服务并关闭它们拥有的公网规则。已有设备注册表、各设备订阅令牌、WireGuard 密钥、Tailscale 登录、证书和累计用量保留，重新启用时继续使用。工具拒绝接管未由其管理的已有代理或 Tailscale 安装。

后续可通过一条命令进入同一个管理会话：

```powershell
uv run vps-ops connect root@203.0.113.10 --port 22
```

使用 `packages list`、`packages upgrade` 维护系统，`reboot` 重启，`service` 管理已启用服务，`logs` 查看脱敏日志。原始系统命令使用普通 SSH 终端。完整命令、成员配置和订阅策略见 [CLI 手册](USAGE.md)、[日常运维](OPERATIONS.md) 与 [订阅与规则](RULES.md)。

## 开发与手动构建

部署会构建并安装选中的项目指纹组件，更新安装包后会重新构建。Go 编译按低内存节点限制并发；仅 Tailscale 且关闭指纹时不安装代理、证书、Clash 用量服务或编译器。

开发者构建可安装包：

```sh
uv sync --locked
uv build --wheel
```

该安装包包含服务模板和网络源码，安装到 Python 3.12 以上环境后可使用相同的部署入口。源码构建与各语言检查见 [开发指南](DEVELOPMENT.md)。
