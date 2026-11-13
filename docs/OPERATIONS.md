# 日常运维

服务器已部署后的操作从这里开始。首次安装见[部署指南](DEPLOYMENT.md)，完整参数和文件格式见[CLI 使用手册](../skills/operate-vps-network/scripts/USAGE.md)。

## 连接并查看健康状态

本机在仓库根目录运行，替换 SSH 地址及端口：

```powershell
uv run vps-ops connect root@203.0.113.10 --port 23899
```

进入 vps-ops> 后连续输入：

```text
status
check
usage report
```

status 查看资源、服务状态、失败单元和是否需要重启；check 验证两个指纹出口、三个协议入口、DNS、订阅、证书和 Tailscale。确认检查全部通过，用量 fresh 为 true。后续操作复用当前登录，输入 exit 才退出。

已在普通 SSH 终端登录时，直接运行 vps-ops status、vps-ops check，无需新建连接。以下代码块均为普通服务器终端命令；在 CLI 提示符下省略 vps-ops 前缀。

## 定位故障

| 现象                     | 先执行                                                  |
| ------------------------ | ------------------------------------------------------- |
| 网络空间或两个后端未启动 | vps-ops logs tcpfp-network                              |
| Windows 出口失败         | vps-ops logs tcpfp-syn-windows，再查 tcpfp-windows-test |
| iPhone 出口失败          | vps-ops logs tcpfp-ios-test                             |
| 域名解析失败             | vps-ops dns diagnose                                    |
| 订阅返回失败             | vps-ops logs caddy                                      |
| 用量 fresh 为 false      | vps-ops logs mihomo-observed                            |

只复查受影响路径：

```sh
vps-ops check dns
vps-ops check proxy
vps-ops check subscription
vps-ops logs mihomo --since "1 hour ago" --lines 50
```

日志默认最近 24 小时、最多 50 行。查询服务名需在 CLI 配置的 services 列表中。需要编辑文件、查看防火墙规则等系统操作时，使用普通 SSH 终端。诊断输出含服务器地址，按私有资料保存。

## 修复网络空间 DNS

```sh
vps-ops dns diagnose
vps-ops dns repair
vps-ops check proxy
```

修复会为两个空间写入独立解析文件，使用现有规则允许的 1.1.1.1。配置由网络初始化维护，重启后仍生效。宿主机的解析配置保持原状。空间不存在时先检查 tcpfp-network 日志，处理网络初始化失败后再检查 DNS。

## 更新软件并重启

在同一会话执行：

```sh
vps-ops check
vps-ops packages list
vps-ops packages upgrade
vps-ops status
```

更新命令会刷新索引并直接安装当前发行版的候选更新，保留本地配置、禁止删除包。Ubuntu 分阶段更新可能暂时保留部分软件；不执行大版本升级和自动清理。确认更新成功，并从 status 记下启动标识后执行：

```sh
vps-ops reboot
```

SSH 断开后，在本机重新连接一次：

```powershell
uv run vps-ops connect root@203.0.113.10 --port 23899 --wait 300
```

登录后运行 status、check、usage report。启动标识应改变，失败服务应为 0，所有检查通过，用量采样恢复。端口恢复后其他服务可能仍在启动，按失败项查询日志并处理。检查完成后保留登录，供后续操作使用。

## 修改入口或添加用户

入口配置在 /etc/mihomo/config.yaml。客户端和新用户材料的生成步骤见[CLI 手册](../skills/operate-vps-network/scripts/USAGE.md#创建成员材料)。每种设备使用独立身份，并将该设备的 UDP 规则放在其 TCP 出口规则之前。

在普通 SSH 终端修改配置后检查，再重启：

```sh
/usr/local/bin/mihomo -t -d /var/lib/mihomo -f /etc/mihomo/config.yaml
vps-ops service restart mihomo
vps-ops check proxy
```

随后从新用户的真实客户端验证连接。member create 输出待注册用户材料，需手动加入目标 listener 并配置设备路由。

## 更新订阅策略

编辑 /etc/vps-rules/rules.yaml，vps-rules.path 会触发应用。需要立即手动应用时：

```sh
vps-ops subscription apply --directory /srv/vps-subscriptions --policy /etc/vps-rules/rules.yaml
vps-ops check subscription
```

客户端刷新订阅后接收配置变化。订阅发布目录为 /srv/vps-subscriptions，访问链接含令牌。策略字段、规则源和客户端刷新方式见[订阅与规则](RULES.md)。

## 证书与用量

证书由 acme.sh DNS-01 流程维护，Mihomo 通过 systemd 凭据读取。检查运行证书或指定证书文件：

```sh
vps-ops check certificate
vps-ops certificate check --cert /private/fullchain.pem --hostname sub.example.com --min-days 7
```

指定文件检查主机名与有效期；实际 HTTPS 部署通过 check subscription 验证。证书更新后执行配置好的续期回调，使 Mihomo 重启读取新凭据，并让 Caddy 加载更新。

用量采集器读取私有 Unix 套接字，数据保存在 /var/lib/mihomo-observed/usage.sqlite。用 vps-ops usage report 查看，JSON 用 vps-ops --json usage report。fresh 为 true 表示近期采样正常，累计字节是近似观察用量。更新 CLI 后重启 mihomo-observed 加载新代码，保留原数据库。
