# 开发与检查

在仓库根目录执行。Python 项目依赖由 `uv.lock` 固定，Node 工具由 `package-lock.json` 固定，Go 模块依赖由 `go.sum` 固定。

开发环境使用 Python 3.14、uv、Go 1.27、Node.js 24、clang、clang-format、libbpf 头文件、ShellCheck、shfmt 和 Caddy。服务器运行 Python 3.12，代码支持 Python 3.12 及以上版本。在 Ubuntu 中可安装系统工具：

```sh
sudo apt install clang clang-format libbpf-dev shellcheck shfmt
uv sync --locked
npm ci
```

```sh
make fmt        # 格式化 Python、Go、Shell、C 和配置文档
make lint       # 格式、lint、go vet、Staticcheck、ShellCheck 和 clang 静态分析
make typecheck  # BasedPyright
make build      # 构建 Linux AMD64 队列进程和 eBPF 对象，编译检查 Python
make test       # Python 和 Go 测试
make check      # 运行以上检查及构建
uv run --python 3.12 pytest  # 检查服务器的 Python 版本
```

`build/mirage-syn` 和 `build/syn_rewrite.o` 是部署产物。Windows 上可在 WSL 中运行完整命令；Python 与 Go 的格式化和类型工具也可直接在 Windows 运行。VS Code 的推荐扩展、保存时格式化和构建任务位于 `.vscode/`。

Python 的配置与测试在 `pyproject.toml`，Go 模块在 `system/tcpfp/mirage-syn/`。按修改范围运行相关检查；涉及服务器路径时使用实际服务进行验证。
