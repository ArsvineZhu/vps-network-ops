"""Present operational results as readable text or JSON."""

import json
import re
from datetime import datetime


def _lines(label, value):
    if isinstance(value, bool):
        return [f"{label}：{'是' if value else '否'}"]
    if value is None:
        return [f"{label}：未知"]
    lines = str(value).splitlines()
    if not lines:
        return [f"{label}：无"]
    if len(lines) == 1:
        return [f"{label}：{lines[0]}"]
    return [f"{label}：", *("  " + line for line in lines)]


def _service(raw):
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    state = fields.get("ActiveState", "")
    substate = fields.get("SubState", "")
    if not state:
        return raw or "状态未知", "unknown", False
    if state == "active":
        label = {"running": "运行中", "exited": "已生效", "waiting": "等待中"}.get(substate) or (
            f"活动（{substate}）" if substate else "活动"
        )
        kind = "active"
    else:
        label = {
            "inactive": "未运行",
            "failed": "失败",
            "activating": "启动中",
            "deactivating": "停止中",
            "reloading": "重载中",
        }.get(state) or state
        if substate and substate not in ("dead", "failed"):
            label += f"（{substate}）"
        kind = "attention"
    restarts = fields.get("NRestarts")
    if restarts is not None:
        label += f"（重启 {restarts} 次）"
    needs_attention = restarts is not None and restarts.isdecimal() and int(restarts) > 0
    return label, kind, needs_attention


def _listeners(value):
    lines = value.splitlines()
    if lines and lines[0].lstrip().lower().startswith("state"):
        lines = lines[1:]
    if not lines:
        return ["无"]
    rows = [line.split(maxsplit=5) for line in lines]
    if any(len(row) < 5 or row[0] != "LISTEN" for row in rows):
        return value.splitlines() or ["无"]
    output = []
    for state, received, sent, address, peer, *extra in rows:
        output.extend(
            [
                f"{address}（{state}）",
                f"  接收队列：{received}；发送队列：{sent}",
                f"  对端：{peer}",
            ]
        )
        if extra:
            output.append(f"  {extra[0]}")
    return output


def _size(value):
    match = re.fullmatch(r"([0-9]+(?:[.,][0-9]+)?)([KMGTPE]?)(?:i?B?)?", value)
    if not match:
        return value
    number, unit = match.groups()
    return f"{number} {unit + 'iB' if unit else 'B'}"


def _uptime(value):
    match = re.fullmatch(
        r"\s*(\d{1,2}:\d{2}:\d{2})\s+up\s+(.+?),\s+(\d+)\s+users?,\s+load averages?:\s*(.+?)\s*",
        value,
    )
    if not match:
        return _lines("运行与负载", value)
    clock, duration, users, load = match.groups()
    duration = re.sub(r"(\d+)\s+days?", r"\1 天", duration)
    duration = re.sub(r"(\d+)\s+hours?", r"\1 小时", duration)
    duration = re.sub(r"(\d+)\s+mins?", r"\1 分钟", duration)
    duration = re.sub(
        r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])",
        lambda part: f"{int(part[1])} 小时 {int(part[2])} 分钟",
        duration,
    )
    return [
        f"服务器时间：{clock}",
        f"运行时间：{duration}",
        f"登录用户：{users}",
        f"平均负载（1/5/15 分钟）：{' / '.join(part.strip() for part in load.split(','))}",
    ]


def _memory(value, summary):
    rows = [line.split() for line in value.splitlines()]
    memory = next((row for row in rows if row and row[0] == "Mem:"), None)
    swap = next((row for row in rows if row and row[0] == "Swap:"), None)
    if not memory or len(memory) < 7 or not swap or len(swap) < 4:
        return _lines("内存", value)
    total, used, free, shared, cache, available = map(_size, memory[1:7])
    lines = ["内存：", f"  已用：{used} / {total}", f"  可用：{available}"]
    if not summary:
        lines.extend([f"  空闲：{free}；共享：{shared}", f"  缓存及缓冲：{cache}"])
    swap_total, swap_used, swap_free = map(_size, swap[1:4])
    if swap[1] in ("0", "0B"):
        lines.append("  交换空间：未配置")
    else:
        lines.append(f"  交换空间：已用 {swap_used} / {swap_total}")
        if not summary:
            lines.append(f"    空闲：{swap_free}")
    return lines


def _disks(value, summary):
    lines = value.splitlines()
    if lines and lines[0].lower().startswith("filesystem"):
        lines = lines[1:]
    rows = [line.split(maxsplit=6) for line in lines]
    if not rows or any(len(row) != 7 or not row[5].endswith("%") for row in rows):
        return _lines("根分区" if summary else "磁盘", value)
    output = ["根分区：" if summary else "磁盘："]
    for device, kind, size, used, available, percent, mount in rows:
        if not summary:
            output.append(f"  {mount}：")
        prefix = "  " if summary else "    "
        output.append(f"{prefix}已用：{_size(used)} / {_size(size)}（{percent}）")
        output.append(f"{prefix}可用：{_size(available)}")
        if not summary:
            output.append(f"{prefix}设备：{device}；类型：{kind}")
    return output


def _updates(value):
    lines = value.splitlines()
    if lines and lines[0].startswith("Listing..."):
        lines = lines[1:]
    if not lines:
        return ["待更新软件包：无"]
    output = ["待更新软件包："]
    for line in lines:
        match = re.fullmatch(r"(\S+)/(\S+)\s+(\S+)\s+(\S+)\s+\[upgradable from:\s*(.+?)\]", line)
        if match:
            name, source, available, architecture, installed = match.groups()
            output.extend(
                [
                    f"  {name}（{source}）",
                    f"    当前：{installed}",
                    f"    可更新：{available}（{architecture}）",
                ]
            )
        else:
            output.append("  " + line)
    return output


def _status_text(data, summary):
    groups = []

    def add_group(title, lines):
        if lines:
            groups.append(title + "\n" + "\n".join("  " + line for line in lines))

    system = []
    for key in ("系统", "运行", "启动标识"):
        if key in data:
            if key == "运行":
                system.extend(_uptime(data[key]))
            else:
                system.extend(_lines("内核" if key == "系统" else key, data[key]))
    if system and "需要重启" in data:
        system.extend(_lines("需要重启", data["需要重启"]))
    add_group("系统", system)

    resources = []
    if "内存" in data:
        resources.extend(_memory(data["内存"], summary))
    if "磁盘" in data:
        resources.extend(_disks(data["磁盘"], summary))
    add_group("资源", resources)

    services = []
    if "服务" in data:
        parsed = [(name, *_service(raw)) for name, raw in data["服务"].items()]
        if not parsed:
            services.append("未配置服务")
        elif summary:
            active = sum(kind == "active" for _, _, kind, _ in parsed)
            services.append(f"活动：{active}/{len(parsed)} 项")
            for name, label, kind, attention in parsed:
                if kind != "active" or attention:
                    services.extend(_lines(name, label))
        else:
            for name, label, _, _ in parsed:
                services.extend(_lines(name, label))
    if "失败服务" in data:
        failed = data["失败服务"]
        if not failed or re.search(r"(?:^|\n)\s*0 loaded units listed\.", failed):
            failed = "无"
        services.extend(_lines("系统失败单元", failed))
    add_group("服务", services)

    network = []
    if "监听" in data:
        network.append("TCP 监听：")
        network.extend("  " + line for line in _listeners(data["监听"]))
    for key in ("路由", "网络空间"):
        if key in data:
            network.extend(_lines(key, data[key]))
    add_group("网络", network)

    if "防火墙" in data:
        add_group("防火墙", _lines("规则", data["防火墙"]))
    updates = []
    if "更新" in data:
        updates.extend(_updates(data["更新"]))
    if not system and "需要重启" in data:
        updates.extend(_lines("需要重启", data["需要重启"]))
    add_group("更新", updates)
    if "最近24小时错误数" in data:
        value = data["最近24小时错误数"]
        detail = f"{value} 条" if isinstance(value, int) else value
        add_group("日志", _lines("最近 24 小时错误", detail))
    return "\n\n".join(groups)


def _bytes(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return "未知"
    size = float(value)
    for unit in ("字节", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"):
        if size < 1024 or unit == "EiB":
            return f"{value:,} 字节" if unit == "字节" else f"{size:.2f} {unit}（{value:,} 字节）"
        size /= 1024
    return f"{value:,} 字节"


def _timestamp(value):
    if not value:
        return "暂无"
    try:
        return datetime.fromisoformat(value).isoformat(sep=" ", timespec="seconds")
    except (TypeError, ValueError):
        return str(value)


def _usage_text(data):
    lines = ["用量（近似观察值）"]
    fresh = data.get("fresh")
    freshness = "正常" if fresh is True else "未更新或不可用" if fresh is False else "未知"
    lines.append("  数据状态：" + freshness)
    latest = data.get("latest_state")
    if isinstance(latest, (list, tuple)) and len(latest) == 2:
        state = {
            "observed": "采集成功",
            "startup/gap": "启动或采样间断",
            "gap/error": "采集失败",
            "gap/delayed": "采样延迟",
            "stopped": "已停止",
        }.get(latest[1], latest[1])
        lines.append(f"  最近状态：{state}（{_timestamp(latest[0])}）")
    else:
        lines.append("  最近状态：暂无")
    lines.append(f"  最后成功：{_timestamp(data.get('last_success'))}")
    users = data.get("users") or []
    if not users:
        lines.append("  用户：无")
    for user in users:
        lines.append(f"\n  {user.get('user', '未知用户')}")
        lines.append(f"    上传：{_bytes(user.get('upload_bytes'))}")
        lines.append(f"    下载：{_bytes(user.get('download_bytes'))}")
        active = user.get("active_connections")
        lines.append(f"    活跃连接：{active if active is not None else '未知'}")
        observed = user.get("ever_observed")
        lines.append(
            f"    曾观察到：{'是' if observed is True else '否' if observed is False else '未知'}"
        )
    return "\n".join(lines)


def _log_fields(value, redact, indent=2):
    prefix = " " * indent
    lines = []
    items = value.items() if isinstance(value, dict) else (("-", item) for item in value)
    labels = {"level": "级别", "msg": "信息", "logger": "来源", "ts": "时间"}
    for name, item in items:
        name = redact(str(name))
        label = labels.get(name, name) if name != "-" else "-"
        if isinstance(item, (dict, list)) and item:
            lines.append(f"{prefix}{label}：" if label != "-" else f"{prefix}-")
            lines.extend(_log_fields(item, redact, indent + 2))
        else:
            value_text = "无" if item is None or item == {} or item == [] else redact(str(item))
            values = value_text.splitlines() or [""]
            lines.append(
                f"{prefix}{label}：{values[0]}" if label != "-" else f"{prefix}- {values[0]}"
            )
            lines.extend(" " * (indent + 2) + line for line in values[1:])
    return lines


def format_log(line, redact):
    """Render JSON application messages without changing ordinary journal lines."""
    if line.lstrip().startswith(("{", "[")):
        prefix, message = "", line
    else:
        prefix, separator, message = line.partition(": ")
        if not separator:
            return redact(line)
    message = message.strip()
    if not message.startswith(("{", "[")):
        return redact(line)
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        return redact(line)
    if not isinstance(data, (dict, list)):
        return redact(line)
    heading = redact(prefix) + ":" if prefix else "日志"
    indent = len(prefix) - len(prefix.lstrip()) + 2
    fields = _log_fields(data, redact, indent)
    return "\n".join([heading, *(fields or [" " * indent + "无"])]) + "\n"


def emit(data, machine=False, *, view="checks", summary=False):
    if machine:
        print(json.dumps(data, ensure_ascii=False))
    elif view == "status":
        print(_status_text(data, summary))
    elif view == "usage":
        print(_usage_text(data))
    elif view == "subscriptions":
        print("订阅地址\n" + "\n".join(f"  {name}：{url}" for name, url in data.items()))
    else:
        for item in data:
            detail = str(item["detail"])
            if "\n" in detail:
                print(f"[{item['state']}] {item['name']}：")
                for line in detail.splitlines():
                    print("  " + line)
            else:
                print(f"[{item['state']}] {item['name']}：{detail}")
