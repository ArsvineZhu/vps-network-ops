# 在新主机部署系统

本入口面向本人和团队使用的独立 VPS，不提供公开注册、计费或租户管理界面。支持基线为 **Ubuntu 24.04、x86_64、systemd**。本仓库的离线测试不代表已经在新 VPS 完成部署、重启或公网验收。

## 1. 先明确部署边界

- `system/build.py` 只在本机生成配置和部署包。`system/ansible/deploy.yml` 才会修改指定远程主机；默认拒绝运行，必须显式提供 `apply_changes=true`。
- 安装器只接受新主机。已有项目目录、用户/权限组、同名文件、Mihomo 服务、Caddy 覆写文件或正在运行的 Caddy 会使预检失败；它不是原地升级器，也不是接管现有服务器的脚本。
- 不改 SSH、UFW、Tailscale、现有防火墙文件或云厂商安全组。TCP 指纹功能会建立专用 namespace、veth、tc/eBPF 和 nftables 对象，并启用 IPv4 转发；遇到不兼容的现有转发规则时应停止审查，不能靠清空规则解决。
- 宿主 BBR 只有在配置明确启用后，才会安装并加载 `/etc/sysctl.d/80-vps-network-bbr.conf`。未启用时不写这份文件。BBR 不等于 Hysteria2 的 QUIC 拥塞控制，也不证明公网速度改善。
- 本轮没有自动签发证书、修改 DNS、开放入站端口、创建云主机或分发成员凭据。相应操作需由操作者按自己的权限另行完成。

## 2. 准备控制机与私有输入

- 控制机使用 Python 和独立虚拟环境安装 Ansible，目标主机不需要安装 Ansible。部署只用 `ansible.builtin`，不依赖 Galaxy 插件。Ubuntu 24.04 控制机上的 Python 3.12 可使用以下依赖范围。
- 将主机清单、密钥 JSON、TLS 证书和生成包放在仓库外，目录 `0700`、私有文件 `0600`。使用真实文件路径，不通过符号链接传入包或二进制。
- 可以用 Ansible Vault 保存私有输入，但解密后仍须写入受限临时目录。不要把 Vault 密码、解密后的文件、真实地址或订阅链接提交到 Git。
- 已有生产服务器不适合作为第一次测试目标。准备可丢弃的全新 VPS，保留云控制台或独立管理入口，先确认 SSH 和系统恢复方式。

```sh
python3 -m venv /你的私有目录/ansible-venv
/你的私有目录/ansible-venv/bin/pip install -r system/ansible/requirements.txt
cp system/ansible/inventory.example.ini /你的私有目录/inventory.ini
chmod 600 /你的私有目录/inventory.ini
```

将示例保留地址换成新主机地址，使用既有 SSH 密钥和正常的主机指纹校验。不要关闭 `host_key_checking` 来绕过首次连接核对。

## 3. 准备固定版本二进制与证书

- Mihomo 固定为 **v1.19.33、Linux amd64**。从经过核对的上游发布取得二进制，在控制机解压后以 `mihomo_binary` 指定本地文件。仓库不携带二进制，部署器也不在线下载它。
- 本版本已核对的解压后二进制 SHA256 是：

```text
817f50b3ac6a8b1c4360c5cf2961906057f3a883d970ebbcb0028a01632b620f
```

- 哈希不是压缩包哈希，也不适用于另一个架构或任意同版本构建。换版本时应一起更新依赖记录、校验器与测试，不能临时关闭校验。
- Caddy 使用 Ubuntu 软件源提供的包，不安装自定义 DNS 插件。证书由仓库之外的 DNS-01 流程签发后导入；不得把 DNS API 密钥塞进部署包。
- 开启订阅、Hysteria2 或 AnyTLS 时必须提供完整证书链和匹配私钥。部署前检查证书域名、有效期和信任链。安装器额外检查密钥匹配及至少七天剩余有效期，但这不代替客户端的主机名和信任校验。

## 4. 生成并离线检查

先阅读配置模型，复制 `system/examples/site.json` 到私有目录，再运行构建器帮助查看当前参数。生成目录必须是新目录，构建器不覆盖既有输出。

```sh
python3 system/build.py --help
python3 system/build.py \
  --site /你的私有目录/site.json \
  --secrets /你的私有目录/secrets.json \
  --output /你的私有目录/bundle \
  --certificate /你的私有目录/fullchain.pem \
  --certificate-key /你的私有目录/privkey.pem
python3 system/ansible/validate_bundle.py /你的私有目录/bundle \
  --mihomo-binary /你的私有目录/mihomo
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s system/ansible -p 'test_*.py' -v
/你的私有目录/ansible-venv/bin/ansible-playbook \
  -i system/ansible/inventory.example.ini system/ansible/deploy.yml --syntax-check
```

- 未启用订阅或 TLS 协议时可省略两个证书参数。输入格式与更完整的构建示例见仓库主说明。
- 校验器只读取本地文件，不连接主机。它检查清单版本、允许的文件目标、目录穿越、源文件符号链接、文件所有者和权限、服务白名单、TLS 必需项及所有文件与二进制的哈希。
- 默认输出仅有数量与功能摘要。`--json` 输出是供 Ansible 使用的私有清单，不要转贴到工单或公开日志。
- 审阅包中的 `plan.json` 和配置差异，确认端口、设备身份、TCP 出口、UDP 策略、管理直连例外、BBR 与证书来源。生成后不要在部署途中修改包内容。
- `--syntax-check` 不执行任务、也不证明远程模块或服务能工作。`--check` 被明确拒绝，因为网络创建、BPF、证书、用户和服务的状态无法用一次模拟完整验证。

清单可写入的目标仅为 `/etc/vps-network/`、`/usr/local/lib/vps-network/`、`/srv/vps-network/` 和指定的 systemd 单元。宿主 BBR 另允许上文那一个明确启用的 sysctl 文件。目标范围限制不能把任意部署包变成可信软件：单元、Python 和 BPF 都可能以高权限运行，只使用审阅过源码产生的包。

## 5. 明确批准后执行一次安装

以下命令会修改指定的新主机。先完成上述审查，并在实际操作前取得所需批准；此处提供命令不代表已经执行。

```sh
/你的私有目录/ansible-venv/bin/ansible-playbook \
  -i /你的私有目录/inventory.ini system/ansible/deploy.yml \
  --limit new-vps \
  -e '{"bundle_dir":"/你的私有目录/bundle","mihomo_binary":"/你的私有目录/mihomo","apply_changes":true}'
```

安装分为以下阶段，任一阶段失败即停止后续启动：

1. 本机验证私有包与二进制；远端只读检查 Ubuntu 版本、架构、现有服务、文件冲突和符号链接。
2. 从 Ubuntu 软件源安装 Caddy、nftables、iproute2、Clang/BPF 头文件、构建工具、Python 和 OpenSSL。通过包安装策略阻止安装脚本提前启动服务。
3. 创建独立服务用户与目录，复制固定版本 Mihomo、配置及源码。代码树和 systemd 单元归 root 所有，服务用户不能改写可执行程序。
4. 按需编译 BPF，对 Mihomo、Caddy、TLS 文件、防护规则和 systemd 单元做检查。
5. 按依赖顺序启动专用网络、TCP 后端、防护和前端。随后启动可选用量采集、Caddy 和证书检查定时器。失败时不添加 DIRECT 回退。

操作系统、既有目录、用户和服务冲突在安装前检查；网络与防火墙检查依赖已安装的工具和运行脚本，因此在包、用户和文件安装后执行。即使因不兼容防火墙而拒绝启动网络，主机也可能已经留下这些安装变化。配置解析使用临时私有数据目录，结束或失败后清理，不以 root 写入服务的长期数据目录。

凭据复制、私有配置检查使用 `no_log`，文件任务关闭差异输出。不要为了调试自行去掉这些保护，也不要将完整 Ansible 调试输出或系统日志公开分享。

### 权限分工

- `vps-mihomo` 运行前端，`vps-usage` 运行私有采集器。二者共享 `vps-controller`，访问 `/run/vps-mihomo/control.sock`；不新增公开 controller TCP 端口。
- `caddy` 与 `vps-mihomo` 共享 `vps-tls` 读取所需 TLS 文件。Caddy 不加入 controller 组。
- 私有状态分别存放于 `/var/lib/vps-mihomo` 和 `/var/lib/vps-usage`。订阅目录由 root 管理，Caddy 只读；URL 中的随机路径仍是需要保护的凭据。
- 指纹后端由自身 systemd 单元进入专用网络空间；它不是前端启动脚本里顺手启动的后台进程。

## 6. 新主机逐层验收

服务 `active` 只表示进程或 oneshot 状态正常。切换用户前至少完成下列项目，并保存脱敏记录：

1. **管理可用：** 第二个独立 SSH 会话、云控制台、已有 UFW/Tailscale 规则均与预期一致。重启后再确认，而不是只看安装结束的一次连接。
2. **监听与身份：** 只出现计划中的监听；每设备和每协议分别验证正确凭据成功、错误凭据失败、撤销单一设备不影响其他设备。
3. **出口隔离：** 私网、元数据、VPS 自身和 Tailscale 地址不可经代理访问；后端停机时对应设备失败，而非退回原生出口。
4. **TCP 与 UDP：** 用受控远端抓包核对 SYN 选项和 TTL。`windows`/`ios` 是指定模板名称，不表示完整模拟设备。UDP deny 必须真实失败；显式 direct 必须单独测试 DNS、QUIC 与目标地址限制。
5. **TLS 与订阅：** 外部客户端验证证书名称和完整链；正确订阅路径成功，错误路径返回拒绝或 404；客户端导入后再实际请求目标，不能以“下载成功”代替出口验证。
6. **用量与持续运行：** 检查非授权用户无法访问 controller，两个设备归属正确，采样服务失败可察觉，重启后累计连续。该数据仍是近似已观测量，不是计费依据。
7. **续期与恢复：** 在测试环境完成证书更新、服务 reload、失败恢复和整机重启。定期检查只表示会检查证书，不等于自动签发或续期已经完成。

## 7. 失败、升级与清理

- 安装失败后可能已留下包、用户、文件或已启动的专用组件。安装器不会自动撤销这些变化；自动撤销网络变更本身也可能破坏管理连接。
- 再次运行会因已有项目目录而停止。不要删除目录来消除报错。审查已完成阶段与真实状态；可丢弃测试机优先重新创建，而不是假装失败安装仍是新主机。
- 当前版本没有通用原地升级、接管或卸载流程。生产迁移使用[独立新主机切换流程](migration.md)，对现场已有改动逐项比较，不以本模板覆盖。
- 仓库来源、离线检查与生产事实的区别见 [VALIDATION.md](../VALIDATION.md)。首次真实部署完成后另行记录实际版本、验收日期及尚未通过的项目。
