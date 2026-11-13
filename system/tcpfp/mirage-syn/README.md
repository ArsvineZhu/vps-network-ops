# SYN 队列处理进程

该进程处理独立网络空间中的 IPv4 TCP 初始 SYN，按 Windows 或 iPhone 模板重排内核提供的选项，保留 MSS、窗口缩放、时间戳和原始头部字段。未支持的选项组合和带数据的 SYN 保持原样。

```sh
go build -o mirage-syn ./cmd/mirage-syn
mirage-syn run -c /etc/tcpfp/syn-windows.json
mirage-syn check -c /etc/tcpfp/syn-windows.json
```

捕获规则由 `system/tcpfp/syn_capture.py` 管理；队列进程不修改防火墙。`strict` 在队列不可用时阻断连接，`open` 允许原始 SYN 通过。状态日志包含改写、跳过、错误和内核丢包计数。

本目录包含 [HuanPP/Mirage](https://github.com/HuanPP/Mirage) `mangler/syn` 的 GPL-3.0 代码，来源提交为 `70f545f08061939fa4ac75b129bf081a4f6b965d`；完整许可见 [LICENSE](LICENSE)，依赖许可见 [licenses](licenses/)。
