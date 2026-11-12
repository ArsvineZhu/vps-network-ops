# Tailscale 出口维护

Tailscale 是设备组网与路由系统；VPS 是其中一台设备。退出节点接管被选择客户端的互联网路由。Linux 内核转发与 userspace/netstack 代理是两条不同数据路径。

## 部署顺序

1. 从官方来源安装，记录版本。用户在正规认证页面登录并批准设备加入，勿把 auth key 放进会话或脚本库。
2. 明确设备身份与访问权限。给 VPS 单独标签；基于用户、组或标签限定允许的方向。默认全互通规则应按需求收紧。测试终端到 VPS 的管理访问、使用退出节点的权限，以及 VPS 主动访问其他设备是否被阻止。
3. 按官方 Linux 出口说明启用 IPv4/IPv6 转发、广告退出节点，再由管理面批准。客户端明确选择该节点。
4. 实测出口、DNS、IPv6与连接稳定性。不要仅凭管理面设备 online 认定客户端正在使用退出节点；核对客户端运行状态和退出节点选择。

## IPv6

无公网 IPv6 的 VPS 不等于可以在客户端放任 IPv6 直连。目标是客户端的 IPv6 要么经过隧道成功，要么在隧道内失败，而非绕过。关闭服务器 IPv6、取消 IPv6 路由和禁止转发的效果不同；先读取实际路由，再做用户批准的变更。本次保留 IPv6 转发是特定部署决定，不作为所有 VPS 默认模板。

## MTU 与故障

调 MTU 前确认真实路径及连接是否直连/中继。MSS 是 TCP 协商字段，MTU 是链路包大小。只改一侧或只改 MSS 可能制造大包黑洞。重试下载、小包/大包请求并观察重传，不能仅为检测站评分提高数值。

本次曾使用 MTU 1400 调试配置；这不是 Tailscale 的通用推荐，也不是本轮重新读取的当前值。默认 TUN MTU 及调试覆盖的版本依据见[网络研究](network-research.md)。复用时核实当前版本支持方式、持久化位置、重启行为和客户端兼容性。保留原值和独立管理通道。调试环境变量随版本可能变化，不把未核实变量写入自动脚本。

## 常用只读检查
```bash
tailscale status
tailscale netcheck
ip link show tailscale0
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding
systemctl status tailscaled --no-pager
```
输出可能包含用户、设备和公网 IP，分享前脱敏。Tailscale ACL/grants、内核防火墙和退出节点本身的权限分别生效，不能相互替代。

## Linux 已安装官方包后的出口开通

安装步骤以当前官方Ubuntu仓库说明为准，确认仓库签名与版本。以下是后续配置，不包含自动登录密钥：
```bash
sudo tailscale up
```
在输出的官方认证页面完成本人授权，设备加入后先执行 `tailscale status`。然后在已授权的出口VPS启用转发：
```bash
printf '%s\n' 'net.ipv4.ip_forward = 1' 'net.ipv6.conf.all.forwarding = 1' | sudo tee /etc/sysctl.d/99-tailscale-forwarding.conf
sudo sysctl -p /etc/sysctl.d/99-tailscale-forwarding.conf
sudo tailscale set --advertise-exit-node
```
这会覆盖同名文件，已有部署必须先读取并备份，不直接粘贴。管理面批准该设备作为出口，客户端选中它。不要同时广告不需要的家庭子网，也不要把“可用作出口”当作“客户端已经选择出口”。

权限策略最少验证三点：允许本人客户端使用出口；只让指定管理员到VPS的管理端口；VPS不主动连其他私人设备。具体标签、本人身份和现有grants先读取，不能把未知策略整份替换。规则有状态，返回流量与主动发起不同。原默认 `* → *` 若保留，会抵消新增限制的意图。

从另一网络用客户端开启出口后访问IP检测，再关闭出口比较。DNS/WebRTC/IPv6分别测，保留实际浏览器、路由和TUN状态。初次部署使用默认MTU；本次历史1400不作为这一流程的必做项。


## 出口授权与主机访问分开核对

历史策略曾允许 `autogroup:member` 到 `autogroup:self`、`tag:exit-node` 和 `autogroup:internet` 的全部端口；后续标签已报告生效。这比默认全网互通收窄了范围，但不等于“只有 owner 可访问 VPS SSH”。本轮未重新读取现行策略；以后若加入 tailnet 成员，要检查宽规则是否也授予 VPS 全端口访问。熟人的 VLESS 凭据本身不代表其已加入 tailnet。

未来获批后将几项权限分别表达：谁可用互联网出口、谁可到 VPS 管理端口、个人设备之间允许什么、VPS 是否可以主动访问私人设备。新增窄规则不能抵消仍保留的宽规则。保存应允许和应拒绝的方向测试，见[出口授权](https://tailscale.com/docs/features/exit-nodes/how-to/setup)、[ACL 机制](https://tailscale.com/docs/features/access-control/acls)、[策略测试](https://tailscale.com/docs/reference/syntax/policy-file)。

UFW、Tailscale netfilter 与 Mihomo UID guard 的范围不同。`ufw status` 不等于完整 tailnet 防护证据；Tailscale 默认可安排自己的规则，见[netfilter 模式](https://tailscale.com/docs/reference/netfilter-modes)。只读检查实际规则，不清空整个规则集来“统一”。

默认避免让 Tailscale Exit Node 与 Clash TUN 同时争夺默认路由。确需共存时先设计路由排除与 DNS，再获批实验；不因为工具失联擅自切换用户网络。参考[其他 VPN 兼容说明](https://tailscale.com/docs/reference/faq/other-vpns)。
