# 统一 VPS 系统

这是第一版可审阅实现，面向本人及团队同伴。它把同一份设备清单编译成服务端、客户端、订阅、防护和 systemd 文件，再由 Ansible 在新主机部署。没有 UI、公开注册或计费系统。

## 从这里开始

1. 读 [设计](../docs/superpowers/specs/2026-11-12-portable-system-design.md)、[新主机部署](../docs/deployment.md) 和 [迁移](../docs/migration.md)。
2. 复制 `examples/site.json` 到仓库外的受限目录，改成目标主机参数。示例域名和保留地址不能直接部署。
3. 在同一私有目录准备独立凭据。格式见下文；已有设备迁移时保留现有有效身份，不能凭设备顺序猜测身份。
4. 使用 `build.py` 生成全新候选目录，运行离线检查和差异审核。真正部署另行授权；脚本不会自行连服务器。

## 构建命令

需要 Python 3.12 和 OpenSSL。秘密输入及证书文件必须在仓库外、属于当前用户、权限 0600；输出父目录不能被其他用户写入。

```sh
python3 system/build.py \
  --site "$HOME/vps-private/site.json" \
  --secrets "$HOME/vps-private/credentials.json" \
  --certificate "$HOME/vps-private/fullchain.pem" \
  --certificate-key "$HOME/vps-private/privkey.pem" \
  --output "$HOME/vps-private/candidate-001"
```

- 无 TLS 协议且关闭订阅时可以省略证书参数。
- REALITY 公私钥必须配对，构建器通过 OpenSSL 验证。证书必须有效、可信、匹配订阅域名及私钥，并至少剩余 14 天。
- 输出全部按私有文件保存。`manifest.json` 包含目标路径、属主、权限和 SHA256；`plan.json` 是不含凭据的摘要，但仍按私有资料保护。
- 默认拒绝覆盖已存在的候选目录。构建失败留下的目录先检查，不要盲目重试。

## 输入说明

- `host`：公网 IPv4、客户端连接域名、WAN 接口、既有 SSH 端口、公共 IPv4 DNS。
- `protocols`：VLESS、Hysteria2、AnyTLS 各自启用状态和端口；同一个数字的 TCP/UDP 端口可以共存。
- `devices`：稳定设备 ID、协议列表、TCP 模板 native/windows/ios、UDP deny/direct、是否需要精确 SSH 直连。
- `tcpfp`：是否生成指纹出口以及经过测量的 MTU；示例 1500 不是对现网的测量结果。
- `subscription`：HTTPS 域名和端口。HY2/AnyTLS 目前使用同一证书域名；连接域名可以不同，但其 DNS 必须指向正确主机。
- `bbr.host` 与 `bbr.namespaces` 分别控制宿主 TCP 和出口 TCP；不调整 HY2 的 QUIC 拥塞控制，也不覆盖 qdisc。
- `usage`：近似采样，不是计费，也不表示设备在线。三协议各自数据库保留独立采样水位。

秘密 JSON 的结构如下，字段值只作占位说明：

```json
{
  "reality": {"private_key": "X25519_PRIVATE_KEY", "public_key": "MATCHING_X25519_PUBLIC_KEY", "short_id": "16_HEX_CHARACTERS"},
  "devices": {
    "owner-laptop": {"vless": "CANONICAL_UUID4", "subscription_token": "AT_LEAST_32_RANDOM_URL_SAFE_CHARACTERS"}
  },
  "backends": {}
}
```

- 每个设备只填它启用的协议字段。Hysteria2/AnyTLS 字段分别为 `hysteria2`、`anytls`，使用不同的至少 32 字符随机口令。
- 使用 windows/ios 时，`backends` 填入相应 `windows`/`ios` 的独立内部 SOCKS 口令。
- UUID、协议密码、订阅令牌、内部密码均不复用。此文件包含访问能力，不能发到聊天、提交到 Git 或放进普通日志。
- 可用 Ansible Vault 加密备份，但构建输入需解密到受限目录。Vault 口令与恢复包分开保管；Git 仓库本身不包含恢复所需秘密。

## 数据路径和边界

- 三协议认证映射到同一个设备 ID；该设备的 TCP 请求选择同一出口。
- `udp_policy=deny` 在客户端和服务端都拒绝。`direct` 是明确的前端原生 UDP 出口，仍有私网/本机防护，不经过 TCP 指纹后端。它不是故障时的自动回退。
- 尚未做 SOCKS UDP 后端整合。不要把 TCP 模板扩展称为 UDP/QUIC 指纹；也不要把服务器支持 UDP 当作真实客户端已接管 WebRTC/DNS/IPv6。
- 后端失败时该设备 TCP 失败关闭；无 DIRECT 备用节点。systemd 依赖失败恢复后，可能需要显式重新启动前端，不能声称无感自愈。
- owner SSH 直连仅在声明的设备订阅中生成“本 VPS IPv4 + TCP + 管理端口”规则。订阅刷新也生成精确域名/端口直连。
- controller 仅有私有 Unix socket。Mihomo 固定版会将 socket 设成 0666，父目录 0750 和专用组才是访问边界。`vps-controller` 成员拥有完整控制能力；采样程序只发 GET 不等于 API 是只读授权。

## 证书、备份与版本

- DNS-01 签发保留在 [已有流程](../skills/operate-vps-network/references/dns01-subscription.md) 中。DNS 凭据不交给 Caddy/Mihomo，不自动创建 DNS 授权。
- 本版导入可信证书并每日检查本地信任、有效期和密钥配对，不会自动续期。检查日志也不是外部通知。迁移时必须恢复原续期流程并验证更新后的实际服务证书。
- 证书轮换、现网升级、自动回滚和第二次部署仍需后续受控实现/验收；当前 Ansible 有意拒绝覆盖已有安装。
- 迁移需要仓库版本、秘密包、证书/续期资料和一致的 SQLite 备份。Tailscale 新机器身份单独登记，不复制旧节点身份文件。

## 检查

```sh
bash system/check.sh
MIHOMO_BINARY=/absolute/path/to/verified/mihomo-v1.19.33 bash system/check.sh
```

第一条执行离线测试；第二条额外调用固定官方二进制解析全部三协议合成配置。不会载入 tc/eBPF、连接 VPS 或打开实际代理监听。原指纹源码的独立测试含本机回环上传/下载，需要允许本机 socket；不访问公网。

真实新主机部署、二次部署、整机重启、协议公网认证、UDP、指纹和证书续期仍未由本仓库证明。完整验收清单见迁移文档。
