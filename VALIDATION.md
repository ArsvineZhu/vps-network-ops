# 验证范围与交付检查

更新：2026-11-12（UTC）；前一轮复盘日期为 2026-11-11。本次仓库整理仅在本地打包环境进行，不访问或修改生产VPS。生产情况来自既有会话的实际输出/用户报告，不与本次离线测试混用。

## 2026-11-12：统一系统源码整合

- 新增 `system/` 的严格输入校验、三协议/设备策略构建、TCP 指纹源、运行时服务、Ansible 新机部署与回归检查；源码整理与发布检查没有连接或修改 VPS。
- 最终聚合检查：系统 58 项、Ansible 31 项、旧工具 30 项（29 通过、1 项 AF_UNIX 夹具因环境限制跳过）、指纹 Python 21 项全部按预期完成。合计 140 项中 139 通过、1 跳过。
- 实际修复 C 源码测试通过 32,972 cases；源码 SHA256 与导入时一致。指纹 Python 测试包含本机回环上传下载，不访问公网。
- 固定官方 Mihomo v1.19.33（解压后 SHA256 `817f50b3ac6a8b1c4360c5cf2961906057f3a883d970ebbcb0028a01632b620f`）实际解析完整三协议前端、Windows/iOS 后端及两份客户端配置。TLS 测试使用临时证书；生产构建拒绝不可信证书，不沿用测试替代。
- Ansible-core 2.19.15 `--syntax-check` 通过；Python AST、Bash 语法与 `git diff --check` 通过。
- 独立审查后补齐 REALITY 公私钥配对、私网域名在身份路由前解析拒绝、证书链/主机名/到期校验、秘密路径父级穿越拒绝、Mihomo 0666 socket 的真实目录边界及网络对象身份检查。
- 这里只完成源码与离线验证，不代表真实主机上的 nft/systemd/netns/tc、外网认证/UDP、订阅 TLS、整机重启或迁移切换已通过。自动续期、原地升级和二次部署尚未统一实现；当前新机部署拒绝覆盖既有系统。
- 先前现网双指纹出口已有新的公网验证报告；下方旧“仅回环”记录描述历史阶段，不代表当前服务器事实。此轮未重新核验现网。

## 2026-11-12：私有 GitHub 发布前检查

- 检查 79 个待发布源文件，以及早期九个本地提交中的全部 69 个历史文件版本。未发现真实节点地址、UUID、订阅 token、私钥或证书；发现的地址和凭据均为公开文档、保留地址、占位符或测试合成值。此结论来自人工与模式检查，不是完备秘密扫描保证。
- 排除 Python 缓存、二进制、证书、运行日志、数据库和生成的私有部署包；保留源码结构、现有许可说明和六个可执行文件的执行位。
- 协作目标为私有仓库 [ArsvineZhu/vps-network-ops](https://github.com/ArsvineZhu/vps-network-ops)。远端以完整整合快照建立初始版本，早期本地手册提交不作为远端祖先提交。
- 发布前重跑 `system/check.sh`；Mihomo 解析检查使用上文哈希匹配的 v1.19.33 二进制。普通 CI 没有设置 `MIHOMO_BINARY` 时会明确跳过实际 Mihomo 解析，不能把该跳过当作已测。
- 首次 GitHub Ubuntu 24.04 检查发现旧证书工具的兼容问题：该环境的 `openssl x509 -checkhost` 对主机名不匹配仍返回零退出码。现已要求输出明确的匹配结果，并增加零退出码但不匹配、空结果及异常结果的回归测试；不降低主机名检查要求。
- 修复后本地聚合复测共 142 项：141 通过、1 项 AF_UNIX 夹具因环境限制跳过；实际 Mihomo 解析与 C 源 32,972 cases 均通过。GitHub 检查使用独立 Ubuntu 24.04 环境，其实际结果应以对应提交的 Actions 记录为准。

## 2026-11-12：TCP 方案与回环实验

- 新增[可落地路线](skills/operate-vps-network/references/tcp-solution.md)及[独立实验目录](skills/operate-vps-network/experiments/tcp-device-routing/README.md)，保留原始脚本、结果和哈希来源。
- 研究实验与本次整合复测均通过 20/20 真实回环请求：每设备 UUID → VLESS/REALITY/Vision → IN-USER → SOCKS 身份选择。两个测试身份各 10 次，TTL 128/64；结果 JSON 完全一致。
- TCP options 仍为 Linux 的 2-4-8-1-3，两类 JA4T 字段相同。Windows/iOS 仅是实验身份名称；没有真实设备、外网或完整指纹改写验收。
- 未加载 SkyProxy/flash-relay。SkyProxy 的内核模块必须在获准的独立可丢弃 VM 验收；普通 Docker 不隔离宿主内核。本轮不把原始 SYN mirror、TTL 调整或代理启动当作完整效果。
- 脚本在独立 experiments 目录，普通 unittest 不导入、不执行它；本包不含二进制、模块、真实凭据、临时证书、私钥或日志。生产保持只读，本轮未连接现网。

## 2026-11-11 复盘与研究补充

- 新增全过程复盘及 MTU/TCP/CDN 研究参考，逐项区分官方机制、社区案例、历史证据、独立云测试和未完成实验。
- 本轮未登录或修改生产 VPS，没有读取实时 MTU、改变指纹、调整 DNS、刷新用户订阅或重启服务。历史 1400 不能写成当前值。
- 独立云浏览器的 Net.Coffee 实验得到七个可达目标 MSP、页面最小值 24–31 ms，及四个 Cloudflare 递归出口。它们不是用户客户端或 VPS 的数据；Egress 动态页面不可用，没有完成该站测试。
- 用户 Windows 设备当时未在线；另一个测试环境无 ping/tracepath/tailscale，netlink 只读调用受限。真实客户端的三路指纹、完整 PMTU 与 CDN 根因均未验证。
- 纯合成生成实验确认基础模板无 DNS 块、TUN 关闭、分类组默认经 VPS、未包含 owner SSH 定制；运行配置可能另有客户端覆写。
- 完整方案、出处、轻量测试参数及其解释限制见[网络研究](skills/operate-vps-network/references/network-research.md)。没有把研究建议变成生产变更。

## 本次可重复检查

- 30项unittest：29通过，1项真实AF_UNIX传输夹具因云环境禁止创建socket而跳过。模拟GET-only测试不能替代生产权限验证。
- 覆盖配置/成员生成8项、采样核心7项、证书检查5项、常驻采样10项。证书测试使用临时自签名证书，既不访问CA，也不证明链信任。
- 所有Python脚本AST解析、Bash快照脚本bash -n、git diff --check通过。
- Markdown本地链接和模板路径检查通过。Skill目录与frontmatter一致。
- 所有随包源文件和Git历史做已知实例标识/私钥标记筛查，未发现实际域名、节点IP、UUID、订阅URL或秘密；这是人工和模式检查，不是完备秘密扫描器证明。
- 前一轮交付 ZIP 包含当时 Git 跟踪文件、明确纳入的两份未跟踪研究文档与 .git，不含缓存、成员包、数据库或日志；当时完整性测试、解包后 Git 状态与 git fsck 通过。本轮文档修改后如重新打包，须再次检查，不沿用上次归档验收。该早期打包阶段没有 remote 或 push；后续协作入口见上方发布检查。

## 已报告的生产完成边界

完整顺序见[部署备忘](skills/operate-vps-network/references/deployment-record.md)。

- SSH硬件密钥及UFW已使用；Tailscale与独立REALITY链路曾分别通过真实请求。端口迁移、出站隔离和自启有历史检查证据。
- Caddy已部署DNS-01取得的证书；本机可信TLS与手机蜂窝9443 health通过。每日03:23续期检查已设置且首次检查成功。
- 两份HTTPS订阅已发布，owner远程配置已在CRV选择，9份MRS下载。最后记录为Direct、TUN关闭，不能称已验收规则路由。
- friend01本机认证正例通过，独立外网客户端仍待测。
- owner 手机订阅已加入仅 VPS IPv4 /32 + TCP + SSH 23899 的精确 DIRECT 例外，用户反馈可用；服务端 guard 未因此放宽，桌面 CRV 当前状态不能由此推定。
- 用户报告私有Unix controller及受限常驻采样服务上线：非特权访问被拒绝，Mihomo没有新增TCP监听，服务active且首次样本成功，5秒采样，vps-usage可用。
- 用户报告清理两份旧端口迁移目录，以及熟人注册的原配置副本、候选文件与重试目录。未独立核验；删除材料不能再用作相关回滚，也不等于撤销节点凭据。

## 仍未验证，不能从上述结果推导

- 未来真正证书续期、部署 hook、续期失败恢复与外部通知。当前交付脚本只写 syslog；同路径证书更新后的 Caddy reload 行为仍待核对，不称已知故障。
- 当前订阅规则模式下实际匹配及出口、friend独立公网认证、完整双用户归属/撤销。
- 统计长期稳定、机器重启后的持续采样与累计连续性；采样始终不是精确计费。
- 全面IPv6/UDP/WebRTC泄露、跨设备长期性能及完整重启恢复；先前一次成功不是永久保证。
- 此仓库新PowerShell探针自身的Windows执行验收；历史同类探针成功不能冒充本文件已测。
- 固定实例安装器未作为通用安装工具入仓。其原审核版有过早UID检查问题，后续已单独续装修复；文档旧哈希仅用于追溯，不能当作当前推荐安装件。

## 重新验收方式

在仓库根目录运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/operate-vps-network/scripts -p 'test_*.py' -v
bash -n skills/operate-vps-network/scripts/vps_snapshot.sh
git diff --check
git status --short
```

真实部署或远程访问仍按当次授权执行。首次目录权限/实际UID检查、空闲connections:null、首次失败gap、归档顶层目录与TTY输入经验分别见作业手册，不应靠删除检查或暴露秘密解决。
