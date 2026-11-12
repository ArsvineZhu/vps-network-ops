# 熟人独立节点、规则与用量

目标是给少数熟人独立凭据和可撤销配置，不建设用户管理平台。任何生成操作都不自动注册服务端、不分享文件、不开放控制接口。

## 1. 生成一人一份配置

在私有目录建立 `public-template.json`，内容与下文节点描述相同，但去掉 `uuid`。`public_key` 是 REALITY 公钥，不是私钥。使用不含真实姓名的唯一标签：
```bash
python3 scripts/new_member.py public-template.json colleague1 ./private/colleague1
python3 scripts/new_member.py public-template.json colleague2 ./private/colleague2 --rules categorized
```
每个目录包含独立 UUID 的 `record.json`、`profile.yaml`、`provider.yaml` 与 `server-user.pending.json`。pending 文件只是候选 users 条目，不是可直接启动的配置。Windows 必须使用仅当前用户可访问的目录；POSIX 0600 不等于 NTFS 权限保护。

## 2. 注册并验收

1. 备份实际服务端配置，记录目标 VLESS listener 的名称/端口，不能盲选第一个监听。
2. 将 pending 对象追加到该 listener 的 `users` 数组，保留其他条目。检查 `username` 和 `uuid` 各自唯一、`flow` 符合客户端。不要把客户端 public key 放到服务端 private-key 字段。
3. 执行已安装版本的校验，确认防护还在。受控重启会中断现有连接，应按批准范围执行：
```bash
sudo /usr/local/bin/mihomo -t -d /var/lib/mihomo -f /etc/mihomo/config.yaml
sudo systemctl restart mihomo
sudo python3 scripts/wait_listener.py mihomo.service 8443 --seconds 10
```
这里 8443 仅是示例，必须匹配本次监听。失败恢复备份并再次校验/等待，不要重复追加同一用户。
4. 仅用新人的配置走外网完成 HTTPS 请求，确认认证身份和节点路径。旧用户也做一次回归。只生成 UUID 不会让新配置立即可用。
5. 仅把其 `profile.yaml` 或 `provider.yaml` 交给指定收件人，不分享管理记录、完整服务端配置或其他用户文件。

## 3. 撤销

从正确 listener 删除该 UUID，校验并受控重启以断开旧会话，然后用旧凭据确认新连接被拒绝，同时验证其他用户正常。删除本地文件、撤掉订阅链接或改用户名均不等于撤销节点访问。不要承诺 API 热更新能立即撤销活动连接。

## 4. 订阅 URL 是独立交付

本包生成器默认交付本地文件，不自动部署托管服务。案例后续已另行发布owner与friend01两份HTTPS远程订阅，具体完成边界见deployment-record.md；真实URL与凭据不随仓库分发。新部署若需自动更新，先明确托管方、域名、收件人和数据范围，再上传每人独立文件。使用 HTTPS、不可猜的独立访问凭据、最小访问日志和撤销机制；URL 本身通常也是凭据。不要公开 GitHub/Gist、在线转换站或全员共用文件。访问控制是否与客户端兼容必须实测，不能只提供一个需要网页登录的下载页。

验收：该人客户端可下载并刷新；未授权请求不能取得内容；另一人的 URL/身份不同；撤销订阅访问与撤销节点 UUID 分别验证。备用本地文件仍可泄露或被转发，不能承诺阻止二次分享。

## 5. 丰富规则但默认全代理

```bash
python3 scripts/clash_profile.py private-node.json categories.yaml --rules categorized
```
按应用提供可选分组，默认全部指向 VPS-Select，包括 China 与 private。仅在使用者明确选择 DIRECT 后直连；私网目标经受保护 VPS 失败是预期。单节点无需虚构故障切换组。

规则采用 MetaCubeX meta-rules-dat 的 MRS provider，当前生成器只提供域名MRS：GitHub、YouTube、Google、Telegram、Netflix、Spotify、Bilibili、China、Private；YouTube 优先于 Google，具体服务优先于中国大集合，最后 MATCH 到 VPS-Select。尚未自动加入geoip规则；若以后加入，IP规则应后置并使用no-resolve，不能声称现有模板已经覆盖。远程规则在客户端运行后下载，下载失败或仓库更新可能改变匹配；这不是完全离线配置。记录来源、核对当前许可和实际下载结果，不把本次可解析当成远程规则已加载。不要叠加多个综合库制造优先级冲突。

这类规则不替代 TUN/浏览器 WebRTC 控制，也不能防止未进入代理的流量泄露。用户可逐组切换，先用连接记录证明具体请求匹配了预期规则。

## 6. 熟人用量只做观测估算

已核对 mihomo v1.19.33 的 `/connections` 中 `metadata.inboundUser` 可标识认证用户，连接含 upload/download；关闭连接即删除。轮询会遗漏短连接、最后一段与停机期间流量；采集器保留每个连接的高水位，重复快照和同一ID的计数回退不会重复累加；但首次见到的旧连接ID仍可能带入历史用量，内核重启也会清空运行时连接信息。因此显示“已观测用量估算”，不能用于精确计费、配额承诺或完整审计。

采集器只读取现有私有 Unix controller socket，或导入本地快照；不会创建或公开控制面。必须先确认当前版本/权限允许该入口，切勿为了统计开放 `0.0.0.0` 控制 API。controller 可控制代理，不只是读统计。
```bash
python3 scripts/observed_usage.py --db private/usage.sqlite --instance vps1 --snapshot private/connections.json --inbound reality-in --users-file private/users.json
python3 scripts/observed_usage.py --db private/usage.sqlite --instance vps1 --unix-socket /实际私有路径/mihomo.sock --inbound reality-in --users-file private/users.json
```
`--instance vps1` 是稳定的非敏感服务器标签，每个数据库只对应一个instance/inbound；不要把不同服务器或监听的数据混进同一个库，也不要随意改变标签。命令每次只采一轮，不自动建立常驻服务。需要定时采集时另行部署受限本地服务，运行频率与保存期限明确后再启用。可用 `--token-file` 读取现有受限令牌，不把令牌放命令行。SQLite持久保存已观测值；服务重启仍有遗漏，不能以持久文件弥补未采到的数据。private域名集合不完整覆盖IP字面量，不能代替服务端地址过滤。数据库保留用户标签、已观测流量、采样状态，以及用于去重的连接ID和计数水位；不记录目标域名、目的IP或节点认证UUID。连接ID不等于节点认证UUID。目录和数据库仅管理员/采集账号可读，备份也同样保护。

### 持续采集示例：管理员终端前台运行

先使用已授权的私有 Unix controller。若目前没有 controller，先停在此处，不为采集偷偷开放新接口。部署者可按当前官方版本配置 `external-controller-unix` 到仅 mihomo 与管理员可进入的目录，校验配置后受控重启；用 `stat` 核实目录/套接字权限，确认没有新增公网TCP监听。不要给普通用户 socket 访问权，这相当于代理管理权。

以下在 VPS root 终端执行，先将变量改成真实 socket 和 listener 名称；脚本路径应为实际本地仓库路径：
```bash
install -d -m 700 /var/lib/mihomo-observed
printf '%s\n' '["colleague1","colleague2"]' > /var/lib/mihomo-observed/users.json
chmod 600 /var/lib/mihomo-observed/users.json
SOCKET='/实际私有路径/mihomo.sock'
INBOUND='实际listener名称'
TOOL='/实际仓库路径/scripts/observed_usage.py'
while true; do
  python3 "$TOOL" --db /var/lib/mihomo-observed/usage.sqlite --instance vps1 \
    --unix-socket "$SOCKET" --inbound "$INBOUND" \
    --users-file /var/lib/mihomo-observed/users.json
  sleep 10
done
```
有控制令牌时追加 `--token-file /实际受限令牌文件`，不要复制令牌值。Ctrl+C停止；SSH退出会停止，故明确不承诺无人值守。每轮显示累计已观测字节和错误，失败后下一轮继续；不可同时运行多个采集器写同一个库。10秒只是轻量采样示例，更频繁也不保证完整。

后台服务化前先通过此验收：用某一人的配置产生已知下载，确认仅该标签增加；另一人独立增加；未知标签/其他listener不计入；重启采集命令后累计仍保留。数据流量与文件大小不会精确相等，不作计费校准。

停止采集后或只读查看报表：
```bash
python3 - <<'PY'
import sqlite3
c=sqlite3.connect('file:/var/lib/mihomo-observed/usage.sqlite?mode=ro',uri=True)
for user,up,down in c.execute('SELECT user,up,down FROM totals ORDER BY user'):
    print(user, '已观测上传MiB=',round(up/1048576,2),'下载MiB=',round(down/1048576,2))
print('最近采样：')
for row in c.execute('SELECT time,state,active,disappeared,resets FROM polls ORDER BY rowid DESC LIMIT 10'):
    print(row)
c.close()
PY
```
`gap/error`代表采集空窗，不是零用量。数据库备份用SQLite备份API或停止采集后复制；保留期限由使用者决定。

## 入口与准入不要混为一谈

默认设计是多人共用同一个VLESS监听端口，每人独立UUID和username。每人获得一份客户端文件，不意味着每人拥有独立公网IP、独立端口或独立服务器；所有人仍共享线路、出口IP和性能。若必须分端口，需要另建listener并同步防火墙、防护回包例外、配置和采集筛选，这不是 `new_member.py` 的功能。

准入由服务器所选listener的users列表执行，客户端分组名称或订阅URL不负责认证。生成后先检查pending条目包含 `username`（不是 `name`）、`uuid`、`flow`，且username与统计白名单标签一致。若脚本输出字段不符合这一要求，停止注册，先修复生成器并重新生成；不要让格式检查通过的未知字段被误认为认证身份已生效。

### 尚未交付或尚未验证

- 本仓库不自动部署托管订阅站。案例已有两份托管订阅，但没有据此建立公开控制接口、用户门户、自动计费/限额或自动撤销服务。
- 用量采集入口仅在操作者明确配置且验证私有controller后可用；模板不默认打开该入口。
- 上面的前台命令本身不是守护进程。案例后来已另行部署受限常驻服务并通过首样本检查，见下节；重启和长期连续性仍待验收。
- 案例owner远程配置已在CRV选择，9份MRS已下载。Direct模式/TUN关闭时不能据此判定规则匹配有效；实际规则路由、friend独立外网认证、多人撤销、统计重启连续性仍需目标环境验收。
- 域名private规则不是完整私网隔离；服务端nft地址过滤才负责这里的出站限制。所有流量是否进入代理仍取决于使用者的客户端接管方式。

## 后续：私有socket常驻采集（生产首样本已通过）

新增 `usage_daemon.py` 与 `check_socket_dir.py`，配套模板在references/templates。
默认5秒采样，配置接受1至10秒；此前10至30秒是通用低频建议，不是这份守护进程的参数范围。另行交付的单机安装与续装修复已由用户在目标VPS执行，私有controller、受限常驻服务与首次采样检查通过。仓库模板本身不会自动应用变更。

v1.19.33官方实现会把Unix socket设为0666，并跳过secret验证。不能依赖socket权限或token来隔离；必须使用仅mihomo账户可进入的0700父目录，并在Mihomo启动前检查目录类型、属主和权限。此API拥有管理能力，不是只读API，创建它需要明确授权。脚本GET /connections是本采集器行为限制，不会缩减API本身权限。

服务模板以现有mihomo账户运行，限制AF_UNIX、独立网络命名空间、无capability、仅私有状态目录可写；使用前核对真实账户及路径。不要直接将模板中的固定路径迁移到另一环境并声称已验收。

采集器处理官方空闲 `connections:null` 为成功的零活跃样本；首次读失败也保留gap状态。启动、停止、延迟和失败分别记录；超过512MiB数据库上限停止而不是删记录。报告显示最后成功时间和新鲜度，陈旧数据不能显示为实时活跃。仍会漏掉短连接与采样后的最后字节，不能用于准确计费。

生产首轮已验证：私有Unix controller存在，非特权访问被拒绝，Mihomo无新增TCP监听，服务active并成功采到首次样本。仍待验证两人分别传输时归属正确、重启后累计保留与长期稳定性；friend外网认证本身也尚待验收。可在服务器运行 `vps-usage` 查看近似用量及新鲜度，不把零已观测字节解释为没有使用。

### 单机安装器与通用工具的边界

本次另行交付的安装器固定检查已审阅版本、8443监听、两名既有用户及标准安装路径，并在修改前后保持节点凭据和防护语义不变。它不是任意VPS通用安装器，因此未直接纳入此可复用仓库。不能移除这些保护性前置检查来强行迁移至其他服务器；应先为新实例形成明确部署参数、回滚和独立审阅。

首次审核版本SHA256：`d3d8d72aba3cdbbb6eb1106826e9abc5389d49c048a7a67192d5c50ca0847267`。该版本随后在重启UID就绪检查中暴露暂态问题，已由单独续装修复处理；不要把此旧哈希当作当前建议安装件。此处保留它仅用于故障追溯，不提供未经核实的最新版续装哈希。该安装器内嵌代码必须与审核源逐项一致；编辑外部同名源码不会改变已内嵌的安装器。仓库仅提供独立源与模板，勿宣称它们改变了已交付安装器。
