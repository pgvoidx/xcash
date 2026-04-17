from ipaddress import ip_address
from urllib.parse import urlsplit


INTERNAL_API_ROOT = "/internal/v1"
INTERNAL_API_PREFIX = f"{INTERNAL_API_ROOT}/"


def normalize_ip_host(value: str) -> str:
    raw = str(value).strip()
    if not raw:
        return ""

    try:
        return ip_address(raw).compressed
    except ValueError as exc:
        raise ValueError(f"INTERNAL_API_IP 包含无效 IP: {raw}") from exc


def extract_hostname(host: str) -> str:
    return urlsplit(f"//{host}").hostname or ""


def is_internal_api_path(path: str) -> bool:
    return path == INTERNAL_API_ROOT or path.startswith(INTERNAL_API_PREFIX)
