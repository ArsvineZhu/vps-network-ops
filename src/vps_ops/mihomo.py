"""Shared Mihomo API payload contracts."""


def connection_rows(payload):
    if not isinstance(payload, dict) or "connections" not in payload:
        raise ValueError("Mihomo connections response must contain a connections field")
    rows = payload["connections"]
    if rows is None:
        return []
    if not isinstance(rows, list):
        raise ValueError("Mihomo connections must be a list or null")
    if any(
        not isinstance(row, dict) or not isinstance(row.get("metadata", {}), dict) for row in rows
    ):
        raise ValueError("Mihomo connection entries and metadata must be objects")
    return rows
