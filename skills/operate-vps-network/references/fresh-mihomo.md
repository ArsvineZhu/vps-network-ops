# 新VPS部署 mihomo：逐项执行

这是可审阅的部署模板，不是已经在本次VPS执行过的自动安装器。适用 Ubuntu24、systemd、UFW、systemd-resolved(127.0.0.53)、IPv4出口。需要调整的前提不匹配就停止。配置含凭据，始终在服务器或本地私有目录操作，不贴回聊天。

## 1. 安装已核实的发行资产

在官方 MetaCubeX/mihomo Releases选择与 `uname -m` 匹配的稳定版本。本例按历史v1.19.33，不承诺它仍是最新。把资产和官方SHA256清单下载到受限目录，确认清单来源后比较 `sha256sum`。解压后先在临时位置运行 `mihomo -v`，再：
```bash
sudo install -m 755 /已验证的解压文件/mihomo /usr/local/bin/mihomo
getent passwd mihomo || sudo useradd --system --home-dir /var/lib/mihomo --shell /usr/sbin/nologin mihomo
sudo install -d -m 750 -o root -g mihomo /etc/mihomo
sudo install -d -m 750 -o mihomo -g mihomo /var/lib/mihomo
sudo install -d -m 755 /etc/nftables.d
id mihomo
```
不要硬编码UID997，重新读取实际UID。不在此自动下载未知版本/架构。

## 2. 建配置和出站防护

使用同目录 `templates/server-config.json`，替换UUID、REALITY私钥、short-id及已验证目标站。生成密钥的命令以安装内核 `mihomo -h` 支持的 `generate` 子命令为准；不要用随机32字节冒充X25519私钥/公钥配对。生成器或官方工具输出仅留在受限终端，不贴聊天。v1.19.33已核实命令如下，在不录屏、不共享输出的私有终端运行：
```bash
umask 077
/usr/local/bin/mihomo generate reality-keypair
python3 -c "import uuid; print(uuid.uuid4())"
openssl rand -hex 8
```
第一条密钥工具产生配对密钥，private key只填服务端，public key填客户端；UUID填用户条目，16位hex short-id填服务端数组及客户端同值。不要把命令输出留在公开日志中。

本机写好私有配置后安装：
```bash
sudo install -m 640 -o root -g mihomo /私有路径/config.json /etc/mihomo/config.yaml
sudo /usr/local/bin/mihomo -t -d /var/lib/mihomo -f /etc/mihomo/config.yaml
```
JSON可用yaml后缀。模板监听8443，规则仅DIRECT表示服务端替已认证客户出站，不是客户端默认直连。

复制 `templates/mihomo-guard.nft` 至私有工作文件，替换三个标记：MIHOMO_UID实际数字、VPS_IPV4实际公网IPv4、LISTEN_PORT实际端口。若DNS不是127.0.0.53，先确定精确解析路径再修改例外。此guard禁止代理UID访问私网、本机和IPv6，但保留已建立客户端TCP的回复；不能当成所有进程或整个VPS的防火墙。
```bash
sudo nft -c -f /私有路径/mihomo-guard.nft
sudo install -m 600 -o root -g root /私有路径/mihomo-guard.nft /etc/nftables.d/mihomo-guard.nft
```
模板自有表 add/delete/recreate在单次事务应用，不清空其他规则。应在目标nft版本通过语法检查后才能应用。已有生产表先备份；不能把此新机流程覆盖现有实例。

## 3. 安装服务，先防护后代理
```bash
sudo install -m 644 references/templates/mihomo-guard.service /etc/systemd/system/mihomo-guard.service
sudo install -m 644 references/templates/mihomo.service /etc/systemd/system/mihomo.service
sudo systemd-analyze verify /etc/systemd/system/mihomo-guard.service /etc/systemd/system/mihomo.service
sudo systemctl daemon-reload
sudo systemctl start mihomo-guard
sudo nft list table inet mihomo_guard
sudo systemctl start mihomo
sudo python3 scripts/wait_listener.py mihomo.service 8443 --seconds 10
```
此模板只用于高端口8443。改443时需审阅并添加必要的CAP_NET_BIND_SERVICE，不能改为root运行。BindsTo在guard unit失活时停止代理，但不能探知他人直接删除nft表；规则变更后必须显式核查，绝不声称有持续完整性监控。

失败分支：保留SSH，查看 `journalctl -u mihomo -u mihomo-guard -n 60 --no-pager`，先脱敏再分享；不要为启动成功暂时移除guard。尚未开放公网前测试代理UID公网HTTPS可达，私网/本机被阻止，并核对drop计数。

## 4. 放行、外网验收、自启

在已批准端口上：
```bash
sudo ufw allow 8443/tcp comment 'mihomo Reality'
sudo ufw status numbered
```
同时核对供应商面板的端口/安全组，不能从UFW推断外部放行。使用本包生成完整客户端配置，按mihomo-clash.md首次导入并做真实HTTPS。选择没有经过此VPS Tailscale出口的独立网络验证，保留原联网恢复路径。验证通过后：
```bash
sudo systemctl enable mihomo-guard mihomo
sudo systemctl is-enabled mihomo-guard mihomo
```
完整重启验收需要另一次维护窗口。本套模板目前只供部署前审核，不能写作已完成实机验收。

## 5. 回退新机部署

仅限本流程刚新建、尚无其他用户依赖的服务：停止mihomo，再停止guard；撤销本次新增的8443 UFW规则，确认无监听。保留配置备份待排障，不删除既有用户数据。若已有生产配置必须恢复先前文件与服务启用状态，不能使用“清空重装”。

## 本模板的验证边界

合成服务端配置（将占位替换成测试值后的上述 listener/REALITY/users 结构）已在用户安装的 Mihomo v1.19.33 上运行 `-t` 成功。仓库模板中的 `REPLACE_...` 本来就不是可运行凭据，不能直接启动。此项仅证明该合成结构可解析，不验证私钥配对、真实目标站、实际客户端认证、nft规则、systemd权限、公网入口或重启恢复。另有生成客户端结构通过同版本校验的记录，两者不能相互替代。
