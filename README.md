# 可迁移 VPS 网络系统与运维工具

一个可协作的 Git 仓库：系统代码、设备与协议配置模型、Ansible 新机部署、TCP 指纹源码、运维 Skill 和验证放在一起，面向本人及团队同伴。统一系统入口见 [system/README.md](system/README.md)。协作入口为私有仓库 [ArsvineZhu/vps-network-ops](https://github.com/ArsvineZhu/vps-network-ops)。此次整合包含脱敏资料、离线测试和显式回环实验，没有连接或修改生产服务器。

## 系统入口（2026-11-12）

- [统一系统与配置说明](system/README.md)：VLESS、可选 HY2/AnyTLS、设备 TCP/UDP 策略、订阅、证书和近似统计。
- [新主机部署](docs/deployment.md) 与 [迁移清单](docs/migration.md)：受限密钥包、版本校验、Ansible、systemd 和验收。
- `system/build.py`：只做离线构建，不自动登录、部署或发布。
- `system/check.sh`：旧工具、新配置、部署边界和指纹源的检查入口。
- 此版完成源码整合和离线验证，尚未完成干净 VPS 重建、整机重启或迁移切换验收。现有机器上的维护不受影响。
- 原手册保留历史事实。新系统不采用旧实例脚本中的硬编码 UID、地址或临时启动状态。

## 目录和 Skill 用法

- `skills/operate-vps-network/SKILL.md`：Skill 入口，frontmatter 的名称与目录一致。
- `skills/operate-vps-network/references/`：部署、维护、分享、排障与模板。
- `skills/operate-vps-network/scripts/USAGE.md`：详细参数、限制和验证记录。
- `skills/operate-vps-network/scripts/`：Python、Bash 和实验性 PowerShell 工具。

可直接让支持 Skill 的助手读取入口文件，再按任务读取相关参考。若工具支持项目级 Skills，将整个 `operate-vps-network` 目录放入它的 Skill 目录，例如项目的 `.agents/skills/`；安装路径应以所用客户端说明为准。本仓库不自动安装 Skill 或修改客户端设置。读取手册不是执行部署的授权，变更 SSH、防火墙、服务及凭据分发前仍需审阅和批准。

历史 `deployment-record.md` 是脱敏案例，不是实时状态或通用默认配置；历史端口、UID、MTU 等均须重新核实。模板包含占位符，不能直接投入生产。

## 当前入口

日常维护先看[maintenance.md](skills/operate-vps-network/references/maintenance.md)，事实边界看[deployment-record.md](skills/operate-vps-network/references/deployment-record.md)，测试证据看[VALIDATION.md](VALIDATION.md)。旧手册模板不是一键生产安装器；统一新机部署使用上方 `system/`，实例专用续装件没有冒充通用工具入仓。

## 复盘与研究

- [TCP 指纹可落地路线](skills/operate-vps-network/references/tcp-solution.md)：每设备凭据分流已完成 20/20 回环实验；TTL 可分开，完整 Windows/iOS TCP 模板仍待隔离 VM 验收。
- [搭建与排障复盘](skills/operate-vps-network/references/retrospective.md)：各阶段证据、改进方法和后续验收顺序。
- [MTU、TCP 指纹与 CDN 研究](skills/operate-vps-network/references/network-research.md)：分层原理、来源、已做实验与尚待真实路径验证的项目。

研究结论不等于生产变更。本轮不调整服务器已有服务，历史 1400 MTU 和检测站标签不能直接当作优化目标。通用配置生成器不会保留 owner 已部署的 SSH 精确 DIRECT 定制，替换订阅前必须核对差异。

## 本地工具快速开始

需要 Python 3（仅标准库）。Linux 只读脚本需要 Bash 和所检查系统的命令；PowerShell 探针需要 Windows PowerShell 5.1、可信的本机 mihomo 和 curl.exe。先读 USAGE.md 与各工具的 `--help`。

```sh
cd skills/operate-vps-network
python3 scripts/clash_profile.py /你的私有目录/private-node.json /你的私有目录/profile.yaml
python3 scripts/clash_profile.py /你的私有目录/private-node.json /你的私有目录/provider.yaml --kind provider
python3 scripts/new_member.py /你的私有目录/public-template.json friend1 /你的私有目录/friend1
```

节点描述字段和示例见 `references/mihomo-clash.md`。只使用客户端需要的公钥，绝不能填入服务端私钥。生成的新成员条目只是待注册内容，不会写入服务器；实际添加、重载、单凭据测试和撤销需另外执行获批流程。生成器拒绝覆盖已有输出。

**本地配置不等于托管订阅。** `profile.yaml` 是完整本地配置；`provider.yaml` 只是节点提供者内容，必须由完整配置引用。文件虽然以 YAML 命名，内容是 mihomo 可解析的 JSON 格式 YAML。下文旧版 `clash_profile.py` 生成器不提供 HTTP 订阅地址、订阅服务器、访问控制或自动凭据分发；新增 `system/` 已生成 Caddy 和受限订阅配置；实际案例已另行部署两份远程订阅，见部署记录；旧版 Clash 不保证支持 VLESS/REALITY。可选分类规则在客户端运行时会下载规则集，不能称为完全离线配置。

- `vps_snapshot.sh`：只读收集 Linux 状态；需按目标系统权限运行，输出可能含真实地址和主机名，分享前脱敏。
- `wait_listener.py`：检查指定 systemd 服务及实际监听就绪，不把 active 当作网络可用证明。
- `mihomo_probe.ps1`：隔离的 Windows SOCKS 探针，不切换系统代理或 TUN；执行时会发起用户指定的网络请求。尚未完成本脚本 Windows 实机验证。
- `observed_usage.py`：导入私有快照或读取现有私有 Unix socket，用 SQLite 累加已观测流量；不开放控制端口、不安装采集计划。只支持 POSIX 权限模型。

流量统计是采样估算，不是计费：会漏掉轮询间短连接和最后的增量，首次看见连接会计入它已有的累计量；“活跃”仅指最近样本看到连接，不代表设备在线。水位记录长期保留，数据库会增长。详见 `scripts/USAGE.md`。

## 凭据与版本控制

真实凭据、配置和成员包优先放在仓库外的受限目录（POSIX 0700/0600；Windows 设置实际 NTFS ACL）。根 `.gitignore` 防止常见的凭据、`private/`、快照、数据库、日志、成员包和缓存被普通 Git 操作加入。它不能保护已跟踪文件，不能阻止 `git add -f`，也不代替权限控制和人工检查。任意自定义文件名仍可能泄漏秘密。

提交前检查 `git status`、`git diff --cached` 及全部待提交文件。不要提交实际 UUID、IP、密码、私钥、令牌、订阅地址或连接快照。示例中的合成 UUID、保留/私网/回环网段以及占位符不代表真实节点。每次发布前重新检查待提交内容与完整历史；私有仓库也不存放生产秘密。

## 测试

在仓库根目录执行以下离线检查，不需要生产凭据，也不会连接 VPS：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/operate-vps-network/scripts -p 'test_*.py' -v
bash -n skills/operate-vps-network/scripts/vps_snapshot.sh
```

显式 TCP 回环实验另放在 [experiments/tcp-device-routing](skills/operate-vps-network/experiments/tcp-device-routing/README.md)，不会由以上 unittest 发现；它不是普通离线单元测试，复现需按实验说明单独运行。

本次打包实测结果见 `VALIDATION.md`。单元测试使用临时目录和合成数据，包括配置生成、成员 UUID 独立性、普通 Git 忽略保护、用量重复导入、计数变化、作用域绑定及异常输入。

测试通过只说明被测离线逻辑通过，不能推出真实公网可达、服务部署安全、Windows 探针可运行或无泄露。历史材料中的 mihomo 1.19.33 配置解析与真实链路成功是先前案例证据，不是本仓库每个模板、每个平台的重新验收。离线检查不重复验收生产；当前生产已完成与未完成范围集中记录于VALIDATION.md，避免把历史模式与当前模式混用。

## 搬迁与继续维护

有权限的协作者可克隆私有 GitHub 仓库，查看和修改完整系统源码。远端从整合版本开始；早期 ZIP 中的九个本地手册提交与远端不是同一条历史，不应直接互相覆盖。初始本地提交使用仓库范围的中性身份，不改全局 Git 配置。以后按需自行设置作者身份；推送源码不会自动部署或同步生产。未提供开源许可证，请勿把可携带误认为已获第三方再分发授权。

```sh
git clone https://github.com/ArsvineZhu/vps-network-ops.git
cd vps-network-ops
bash system/check.sh
```

## DNS-01与托管订阅

新增作业见 `references/dns01-subscription.md`（位于Skill目录）。证书部署与手机蜂窝9443 health验收已通过，每日续期检查已设置；两份正式订阅已发布，owner远程配置已在CRV选择且9份MRS已下载；真实规则匹配、friend外网认证与未来续期尚未验证。工具只读检查本地证书，不自动部署或授权DNS。

私有用量常驻服务后来已在目标VPS续装成功：5秒采样、首样本通过、`vps-usage`可用；这是近似已观测用量，双用户归属、长期运行与重启连续性仍待验收。用户报告已删除两份旧端口迁移材料，它们不能再用于旧443回滚；另已报告清理熟人注册的原/候选配置与重试目录；这些用户反馈均未独立复核，不扩大为其他备份已清理。
