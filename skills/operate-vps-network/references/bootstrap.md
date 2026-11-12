# 从购机到安全管理

## 选型与盘点

纯个人网络节点优先考察实际线路、端口政策、带宽和流量计费、管理控制台与救援能力。1 核 1 GB 通常能承载轻量代理，但吞吐仍取决于 CPU、线路和协议；标称带宽不是端到端保证。核实是否独立公网 IP、NAT 映射产品及 IPv6 分配，不能从商品名推断。

盘点命令：
```bash
cat /etc/os-release
uname -r
ip -br address
ip -4 route
ss -lntup
systemctl --failed
apt list --upgradable
```

记录系统、内核、软件来源及版本。Ubuntu LTS 的内核主版本旧不等于未修安全漏洞；看发行版支持和补丁。用户要求保留现有 LTS 时，不顺带做发行版升级。

## 更新

使用发行版仓库和软件官方发行来源，校验下载资产。先检查磁盘空间、包管理状态、可恢复控制台，再更新软件包。重启和服务重启的影响单独说明；更新后核对运行内核、SSH、Tailscale、mihomo、路由及防火墙。不要把包已安装当成新内核已经运行。

## SSH

1. 保持已登录会话，确认正确 SSH 端口与主机密钥。
2. 在客户端建立密钥。安全密钥公钥形如 `sk-ecdsa-sha2-nistp256@openssh.com`；公钥可安装，私钥/口令不进入聊天或日志。硬件密钥的触碰、PIN 和本地密钥文件口令是不同步骤。
3. 将公钥追加到目标账户 `authorized_keys`，保留已有有效密钥，核对目录/文件所有权与权限。
4. 启用公钥认证并 `sshd -t` 校验，用第二个会话实测成功；日志应出现 `Accepted publickey`。
5. 用户批准后关闭密码与键盘交互认证。root 可用 `PermitRootLogin prohibit-password`，也可在另建管理员账户验证后禁用 root 登录；按实际用途选择。
6. 检查最终有效配置，而非只看单个文件：
```bash
sshd -t
sshd -T | grep -E 'permitrootlogin|pubkeyauthentication|passwordauthentication|kbdinteractiveauthentication|authorizedkeysfile'
```

`Match` 条件存在时用 `sshd -T -C ...` 核查实际用户/来源。服务可能由 socket 激活，端口变化还需检查 `ssh.socket`。密码 SSH 关闭不代表控制台密码失效；曾放进普通文件的密码仍建议轮换，删除文件不能替代轮换。

## 防火墙与防护

先核对 nftables/iptables 后端、现有 UFW 及 Tailscale 规则。禁止全局 `flush ruleset`、重置 UFW 或清空 Tailscale 链作为快捷修复。允许管理 SSH、必要 Tailscale UDP 和生产代理端口；出站与转发策略分开核查。

启用 UFW 前安排自动恢复，并用新 SSH 会话及出口请求证明正常后取消恢复计时器。`ufw status` 只展示 UFW 管理的规则，不代表整个内核规则集。非必要不在公网暴露 DNS、管理控制接口或配置文件。

## 空 Ubuntu 24 VPS 的逐步执行清单

下列写操作由操作者在已授权VPS执行。先保留控制台救援方式和当前 SSH 会话。每阶段验收后再进行下一阶段，不一次粘贴整篇。

### A. 系统包更新
```bash
df -h / /boot
sudo dpkg --audit
sudo apt update
sudo apt full-upgrade
```
认真阅读 apt 的删除/新增包与服务重启提示，不加自动确认掩盖异常。磁盘不足、dpkg中断先修复再继续。完成后：
```bash
systemctl --failed
apt list --upgradable
if test -f /var/run/reboot-required; then cat /var/run/reboot-required; fi
```
需要重启时确认可恢复登录，再 `sudo reboot`。重新登录核对 `uname -r` 和服务，不做 `do-release-upgrade`。自动安全更新可在安装发行版 `unattended-upgrades` 后使用其交互配置；不要默认允许无人值守自动重启。

### B. Windows 创建硬件密钥

在本地 PowerShell，不是在远程 Bash：
```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
ssh-keygen -t ecdsa-sk -f "$env:USERPROFILE\.ssh\vps-security-key"
Get-Content "$env:USERPROFILE\.ssh\vps-security-key.pub"
```
若当前OpenSSH不支持硬件密钥，停下检查客户端版本/支持，不降级为聊天传递密码。选择本地文件口令并安全保存。仅复制 `.pub` 公钥到VPS，用已登录终端追加：
```bash
install -d -m 700 ~/.ssh
cat >> ~/.ssh/authorized_keys
```
粘贴一行公钥，回车再Ctrl+D。然后 `chmod 600 ~/.ssh/authorized_keys`。用新终端指定私钥文件及实际端口登录；核对主机指纹，不能自动忽略主机密钥变化。只有日志确认 publickey 成功后才关闭密码认证。

### C. 防火墙首启

按实际SSH端口修改变量，以下仅在UFW尚未启用且已有规则经审阅时执行。只增加必要规则，不reset：
```bash
SSH_PORT=23899
sudo ufw allow "$SSH_PORT/tcp"
sudo ufw allow 41641/udp
sudo systemd-run --unit=ufw-rescue --on-active=10m /usr/sbin/ufw disable
sudo ufw enable
sudo ufw status verbose
```
这是“10分钟自动停用UFW”的临时救援，会降低防护，应仅限首启验证窗口。新SSH和出口都通过后 `sudo systemctl stop ufw-rescue.timer`，确认inactive。原本已启用的防火墙不能用这种方式替代精确原状态恢复。Tailscale的转发/NAT链单独检查，禁止清空。

### D. 分路部署与最后验收

先按 tailscale.md 建管理与出口路径，再按 mihomo-clash.md 建独立代理路径。若只需其中一个，不安装另一个。安装资产须按官方指定版本、架构与checksum核实；没有核实的资产不curl管道直接执行。mihomo用户、配置、guard和systemd模板都先审阅再应用，不从历史快照反向猜完整配置。

最后记录：系统版本、软件版本、服务enabled/active、入站端口、防护规则、恢复方法。完整重启验收应在有救援通道时计划执行，重启后用新的SSH、Tailscale与Clash外网请求逐项验证。未做重启就标“未验证”，不能只凭enabled宣称完成。
