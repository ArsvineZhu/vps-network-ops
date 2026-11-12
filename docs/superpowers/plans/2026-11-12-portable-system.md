# Portable VPS System Implementation Plan

> For agentic workers: execute and review each isolated component; do not deploy or publish as a side effect of local implementation.

**Goal:** 将运维材料和可重建系统合并为一份可协作仓库。

**Architecture:** Python 只编译受限配置；Ansible 管理新主机文件和服务；systemd 管理网络、后端、前端和运维生命周期。全部秘密留在仓库外。

**Tech Stack:** Ubuntu 24.04, Python 3.12 standard library, Ansible, systemd, Mihomo v1.19.33, Caddy, nftables, tc/eBPF.

**Spec:** ../specs/2026-11-12-portable-system-design.md

## Global Constraints

- 不连接现网、不推送、不覆盖已有工作区变更。
- 凭据、证书私钥和生成结果不得入 Git。
- 只声明实际完成的验证层级；现网状态与离线构建分开记录。

## Review Focus

- 错误/重复凭据、未知出口、重复端口须拒绝。
- 秘密输入或输出经符号链接、宽松权限泄漏须拒绝。
- UDP 不支持时明确 REJECT，不依赖隐式规则退回 DIRECT。
- 网络对象冲突和部分失败须停止，不能删除不属于自己的对象。
- 现有服务、UFW/Tailscale 与正在进行的现场修改不得被覆盖。

## Task 1: 单一配置与构建器

- [x] 创建 `system/build.py`, `system/config.py`, `system/render.py`, `system/examples/site.json`。
- [x] 用 `system/tests/test_system.py` 校验输入、秘密权限、三协议、订阅例外和输出模式。
- [x] 用真实固定 Mihomo `-t` 验证合成配置。

## Task 2: 运行时与指纹源

- [x] 导入 `system/tcpfp/ebpf` 和原源码测试，记录哈希来源，不复制私有记录。
- [x] 创建网络、guard、证书导入与检查工具；默认只读或 plan。
- [x] 测试对象所有权、启动顺序和拒绝无审阅覆盖。

## Task 3: 新主机部署和迁移

- [x] 创建 `system/ansible`，只消费已校验构建清单，默认不变更。
- [x] 写 `docs/deployment.md`, `docs/migration.md`；分清离线、测试主机与生产验收。
- [x] 执行语法、链接、秘密扫描和既有测试，记录结果。

## Task 4: 仓库交付

- [x] 更新 README、Skill 路由和验证报告，不删除历史边界。
- [x] 添加 CI 和可重复检查入口；保留现有 Git 历史与工作区。
- [ ] 仅在主代理确认公开范围和授权后由主代理安排远程发布。
