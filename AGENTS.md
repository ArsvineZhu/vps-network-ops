# VPS Network Ops 开发指南

先阅读并遵循 [AntiRLHF 宪法](docs/agents/CONSTITUTION.zh-CN.md)。按任务使用本地 Skills；用户要求优先于 Skill 流程。

这是个人 VPS 的部署与运维仓库。[README](README.md) 说明使用入口，[INDEX](INDEX.md) 标明代码与文档的职责，[系统架构](docs/ARCHITECTURE.md) 说明真实数据路径。修改前读取受影响的实现和调用方；生产状态以实际服务器为准。

直接维护当前实现。内部结构变化时同步修改调用方、配置、文档与有效测试，删除淘汰代码和专属支撑，不保留兼容层、迁移脚本、备份或过程记录。用户配置、证书、订阅和真实凭据是业务数据，不能作为开发残留处理。

生产凭据、订阅地址和真实连接数据留在仓库外。管理服务器时复用已有 SSH 会话，按用户明确的工作范围操作；变更后检查实际服务路径。

Python 使用 `uv`、Ruff 和 BasedPyright；Go 使用 goimports、`go vet`、Staticcheck 和 `go test`；Shell 使用 shfmt 和 ShellCheck；C 使用 clang-format 和 clang；配置及 Markdown 使用 Prettier。命令见 [开发指南](docs/DEVELOPMENT.md)。只运行与当前修改有关的检查；测试保护真实行为与独立失败，不为测试增加生产接口或重复实现。

涉及依赖、工具链和外部服务的版本时，核对当前官方资料及实际环境，再确定要求和锁定版本；不要凭记忆假定版本仍然有效。

文档写当前能力、配置和操作。经验手册集中在 `docs/materials/`；不要把历史过程、旧方案和任务报告写进现行文档。临时下载、实验、日志和构建结果放在忽略的 `temp/` 或 `build/`，不进入版本控制。
