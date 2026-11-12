# mihomo 与 Clash 操作手册

## 建立 REALITY 节点

1. 核对 CPU 架构、发行资产和校验值，安装指定版本。确认目标公网端口空闲。创建专用无登录用户，不以 root 运行代理。
2. 本地生成独立用户 UUID、REALITY 密钥对及 short-id，私钥只保存在服务端受限文件。客户端仅带所需访问凭据；分享配置等于分享节点访问能力。按设备/使用者分开凭据，便于撤销。
3. 按当前版本的官方 listener/schema 生成配置。区分三种端口：VPS 入站端口、REALITY 目标站端口、客户端本地代理端口。不要全文件替换端口。
4. 检查候选目标站的证书、TLS1.3及协议支持。此检查只证明目标站可作为候选，不能替代真实 REALITY 客户端请求。
5. 先建立专用 UID 出站防护，再启动代理。封锁私网、CGNAT、回环、本机地址、元数据地址等；给本机 DNS 的精确例外，以及已建立入站连接的回复例外。检查 IPv6 的实际策略。
6. 创建 systemd 服务：专用用户、必要的低端口绑定能力、`NoNewPrivileges`、配置语法预检；主服务依赖防护服务并在其后启动。防护服务失活时应停止代理。BindsTo 不监测任意外部删表，oneshot active 也不证明规则仍存在；变更后必须另查实际 guard，不能声称持续完整性监控。
7. 校验后启动，等待属于该服务 PID 的监听出现。打开所需公网 TCP 入站；VLESS 经 TCP 承载 UDP不等于要开放同号公网 UDP。
8. 用独立客户端做 HTTPS 请求，再从外网验证。只有内核 `-t` 通过或本机回环成功，仍不能算公网节点就绪。
9. 全链通过后启用自启，记录来源、版本、更新和回滚方法。

常见目录可沿用本次部署，但首先确认存在：
```text
/etc/mihomo/config.yaml
/etc/nftables.d/mihomo-guard.nft
/var/lib/mihomo
/etc/systemd/system/mihomo.service
/etc/systemd/system/mihomo-guard.service
```

## 只读验收
```bash
systemctl is-active mihomo mihomo-guard
systemctl is-enabled mihomo mihomo-guard
systemctl show mihomo -p MainPID -p After -p BindsTo
ss -lntpe '( sport = :8443 )'
nft list chain inet mihomo_guard guard
ufw status numbered
```
将 8443 替换为实际端口。规则输出可能包含实例地址，提交报告前脱敏。

## 迁移端口

目标：保留凭据与 REALITY 目标，仅换公网监听。

1. 核实新端口空闲、旧临时清理计时器已结束。读取当前配置格式；本次 `.yaml` 实际存放 JSON，可用 JSON解析。
2. 创建仅管理员可读的备份，保存原配置、防护文件、启用状态及回滚脚本。
3. 精确修改目标 listener 的 `port`。同步 guard 的已建立入站回复例外（TCP source port），可在过渡期同时保留新旧端口。
4. 用 `mihomo -t` 和 `nft -c -f` 校验。nft 文件只替换自己的表，禁止清空整个规则集。
5. 复用或新增已批准的新端口 UFW 规则；记录本次真正新增的规则，回滚只撤销本次新增项。不能因已有规则就直接删除重加。
6. 重启，等待最长一个明确时限（例如10秒），核实监听属于当前 MainPID。再核验运行 guard；nft JSON 比文本服务名更适合程序检查。
7. 更新客户端配置源、实际加载配置和运行内核，再做真实请求。公网验证由独立网络执行。
8. 验收后再清理旧监听/旧规则。若失败，恢复原文件与启用状态，同样等待旧端口就绪。保持管理 SSH/Tailscale。

本次旧脚本在服务重启后立即检查监听，随后触发回滚；“检查过早”符合现象，但未证明为唯一原因。新版等待就绪后迁移成功。

## 生成与使用 Clash 配置

离线配置生成器应接受公开地址、服务端端口、UUID、SNI、REALITY public key、short-id、流控及节点名称。秘密从受限输入文件或交互输入取得，不放进命令行参数、Git或公开URL。输出使用安全权限，避免打印整份配置。

最低交付包括节点、选择组和明确的规则。`MATCH → 指定组` 是全部流量走节点，不能称为国内外分流。可提供单节点 provider 文件和完整客户端配置，标明区别。

“订阅”有两种含义：本地导入配置，或通过URL定期更新。先完成本地导入。托管订阅是额外的上传/数据分享动作，需要明确授权、访问控制和撤销方式。不要把含凭据配置默认发布到网站、GitHub或在线转换站。

本次 CRV：规则模式，组指向 Private-VPS，实际混合端口7897；关闭的系统代理曾遗留7890，开启时必须核实真实地址。服务模式使用 production IPC，配置文件里的 sidecar IPC 不一定是真实控制接口。

操作验收：
1. 修改实际本地配置源，备份，确认只有目标节点字段变化。
2. CRV“订阅”中对当前本地配置点“使用”，触发重载；读取运行内核端口确认生效。
3. 系统代理适合遵循代理设置的应用；TUN接管范围更广，改变路由需明确批准。不要为验证偷偷开启TUN。
4. HTTP200还要核对该请求的CRV连接记录，确认经过目标节点而非DIRECT。

## 随包工具的实际用法

先在自己的机器建立受限的 JSON 描述文件，包含 `server`、`port`、`uuid`、`servername`、`public_key`、`short_id`。内容来自实际服务端，字段填好后不再回传聊天。

```bash
python3 scripts/clash_profile.py private-node.json client-profile.yaml
python3 scripts/clash_profile.py --kind provider private-node.json nodes.yaml
python3 scripts/wait_listener.py mihomo.service 8443 --seconds 10
```

第一条生成完整本地配置，第二条只生成节点provider，两者均不联网。生成器拒绝覆盖已有文件；保存前先确定目标路径。文件虽然可用`.yaml`后缀，JSON也是YAML可接受的子集。生成后先用客户端内核测试配置，再导入CRV；上传托管另行处理。

只读服务器快照：
```bash
sudo bash scripts/vps_snapshot.sh > private-snapshot.txt
```
快照不更新软件源、不连接外部探针，但会包含IP、主机信息和规则，文件应留在私有位置。`wait_listener.py`只检查属于systemd当前主进程的监听，不建立连接；超时应收集日志，而非直接重跑整套迁移。

离线工具测试：
```bash
python3 -m unittest discover -s scripts -p 'test_tools.py'
```
测试不替代服务器公网可用性验收。

本包生成的合成完整配置已用 Windows mihomo v1.19.33 的 `-t` 校验通过。这项验证只覆盖格式解析，不代表合成节点可连接或已托管订阅。

## 完整的合成输入示例

以下地址/凭据全为示例，不能连接。只在私有文件替换真实值，不回传文件：
```json
{
  "name": "Private-VPS",
  "server": "vpn.example.com",
  "port": 8443,
  "uuid": "00000000-0000-4000-8000-000000000001",
  "servername": "www.example.com",
  "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "short_id": "0123456789abcdef"
}
```
映射：server/port 是外网可达的VPS地址及入站端口；uuid 对应所选 listener.users 中该人的 uuid；servername 是已验证 REALITY 目标允许的SNI；public_key 是服务端 REALITY private-key 对应公钥，绝不能填私钥；short_id 必须匹配服务端允许项。flow 由工具固定为 xtls-rprx-vision，服务端也必须匹配。目标站地址不等于 VPS 地址。

首次导入：CRV“订阅”→新建/导入本地配置→选择生成的完整 profile→“使用”，再到代理页选择 Private-VPS。菜单名称随客户端版本可能变化，必须以实际界面确认。provider 文件不是完整订阅页配置。先保持TUN和系统代理关闭，测试显式本地代理；实际端口以运行设置为准（本例7897）：
```powershell
curl.exe -q --proxy http://127.0.0.1:7897 --connect-timeout 10 --max-time 25 -o NUL -w "HTTP=%{http_code} exit=%{exitcode}\n" https://example.com/
```
HTTP200、exit0且连接记录指向新节点才通过此项。用直连公网测试时需要取消 Tailscale 出口并安排好恢复联网方式；Tailscale在线成功只能证明叠加路径。不要重复让用户断网再切回而不收集服务端证据。

监听归属检查必须以 root（sudo）运行，普通账户常看不到其他 UID 的 PID：
```bash
sudo python3 scripts/wait_listener.py mihomo.service 8443 --seconds 10
```
多人和规则模板见 [sharing-usage.md](sharing-usage.md)。
