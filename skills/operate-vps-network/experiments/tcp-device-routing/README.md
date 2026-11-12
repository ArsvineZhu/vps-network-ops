# 按设备身份选择出口：回环集成实验

本目录保存 2026-11-12 的原始实验脚本、脱敏结果与来源摘要。方案、第三方候选和生产接入边界见[可落地路线](../../references/tcp-solution.md)。

## 已验证的内容

官方 Mihomo v1.19.33 的两份临时配置通过检查，20 次真实回环 HTTP 请求经过 VLESS/REALITY/Vision → IN-USER → SOCKS 用户选择 → 目标连接。Windows/iOS 两个身份各 10 次正确选择，TTL 分别 128/64。TCP options 仍为 Linux 的 `2-4-8-1-3`，不能称为完整 Windows/iOS 指纹改写。

这些名称只标识测试凭据，不是真实 Windows/iPhone 客户端。收到的 MSS/窗口 65495 和缩放 10 来自 Linux 回环，不能作为公网模板。整合入仓时在另一私有临时目录重新运行一次，20/20 通过，结果与随包 JSON 完全一致。

## 文件

- [test_device_routing.py](test_device_routing.py)：原样保留的显式集成脚本，不是生产服务或通用 SOCKS 实现。
- [device-routing-results.json](device-routing-results.json)：已执行结果，只含版本、计数、SYN 字段和限制。
- [provenance.json](provenance.json)：固定官方下载地址、压缩包/解压二进制/脚本/结果的 SHA-256 与复测摘要。压缩资产哈希与可执行文件哈希是不同对象。

不附带 Mihomo 二进制、第三方源码、内核模块、运行密钥、临时证书或日志。`local-test-only` 是公开的合成回环 SOCKS 夹具口令，不是生产凭据；绝不能用于真实服务。

## 如何安全复现

1. 仅在允许普通回环 TCP socket 的 Linux 实验机使用。需要 Python 3、OpenSSL、curl，以及从官方发行源取得并核对资产摘要的 Mihomo v1.19.33。系统需要支持 TCP_SAVE_SYN/TCP_SAVED_SYN。
2. 建立仓库外、仅当前用户可访问的临时目录；复制本目录脚本进去，将已校验二进制命名为 `mihomo-v1.19.33` 放在同目录。不要直接在仓库内运行，以免覆盖归档结果。
3. 显式运行 `python3 -B test_device_routing.py`。它没有 `--help` 或导入保护，导入就会执行，不要将它移入 scripts 的 `test_*.py` 自动测试目录或使用 Python 优化模式关闭断言。
4. 脚本创建临时凭据、短期模拟握手目标证书和回环监听，最终使用 finally 清理进程与临时配置。输出 JSON 写在脚本旁边。作为实验夹具，它仍可能遇到端口竞争、启动等待过短或早期失败；失败时保留私有脱敏阶段信息，确认自己的临时进程已退出，不发布原始日志。
5. 复测应检查请求数、身份计数、TTL 与 TCP options，而不只看退出码。内核/环境变化可能改变回环 TCP 字段，失败需重新解释，不能为通过而把结果写成固定值。

普通仓库测试仍只运行 scripts 下的 unittest，不会启动本实验。实验脚本不加载内核模块、改 MTU、防火墙、路由、系统代理或 TUN，也不连接生产 VPS。没有执行 SkyProxy/flash-relay；完整改写必须在获准的可丢弃 VM 上另行验收，普通容器不能隔离宿主内核模块风险。
