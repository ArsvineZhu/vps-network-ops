# TCP 指纹出口

两个网络空间分别运行 Windows 和 iPhone 的 Mihomo SOCKS 后端。Windows 出口通过 NFQUEUE 调整 IPv4 TCP SYN 选项；iPhone 出口使用 tc/eBPF。设备认证与出口选择由前端 Mihomo 负责。

`fingerprint-engines.json` 定义各出口使用的引擎。`syn-windows.json` 定义 Windows 的队列、模板和故障策略。`network.py` 启动网络或检查现有网络，`network.sh` 创建网络空间和转发规则；`render_assets.py` 按服务器地址和出口网卡生成 nftables 配置。

```sh
python3 system/tcpfp/render_assets.py --public-ipv4 "$SERVER_IPV4" --wan "$WAN" --output /private/tcpfp-network
```

NFQUEUE 进程及其依赖许可见 [mirage-syn](mirage-syn/README.md)。服务单元位于 `systemd/`。后端的密码和服务端认证身份只放在 `/etc/tcpfp` 和 `/etc/mihomo`。
