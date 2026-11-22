"""H3 Story API keys: one per host, kept in a ComfyUI system user folder that is never served over HTTP."""

import ipaddress
import json
import os
from urllib.parse import urlsplit

import folder_paths

FOLDER = "h3c_story"
MAX_KEY_LENGTH = 4096
BAD_URL = "Enter a base URL that starts with http:// or https://."
PRIVATE_NETWORKS = [ipaddress.ip_network(network) for network in (
    "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10",
    "::1/128", "fc00::/7", "fe80::/10")]


def host_of(base_url):
    """The lowercase host of `base_url`, with ":port" when the URL names one; raises ValueError for other URLs."""
    try:
        parts = urlsplit(str(base_url).strip())
        port = parts.port
    except ValueError:
        raise ValueError(BAD_URL) from None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(BAD_URL)
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return host if port is None else f"{host}:{port}"


def _path():
    return os.path.join(folder_paths.get_system_user_directory(FOLDER), "keys.json")


def _load():
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {host: key for host, key in data.items() if isinstance(host, str) and isinstance(key, str)}


def hosts():
    """The hosts that have a saved key."""
    return sorted(_load())


def save(base_url, key):
    """Saves `key` for the host of `base_url`, or forgets that host's key when `key` is empty; returns hosts()."""
    host = host_of(base_url)
    key = str(key or "").strip()
    if len(key) > MAX_KEY_LENGTH:
        raise ValueError(f"The key is longer than {MAX_KEY_LENGTH} characters.")
    keys = _load()
    if key:
        keys[host] = key
    else:
        keys.pop(host, None)
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(keys, f)
    os.replace(path + ".tmp", path)
    return sorted(keys)


def may_send(base_url):
    """Whether a key may go to `base_url`: over https, or over http to this machine or a private address."""
    parts = urlsplit(str(base_url).strip())
    if parts.scheme.lower() == "https":
        return True
    host = parts.hostname or ""
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in PRIVATE_NETWORKS)


def key_for(base_url):
    """The key to send to `base_url`, or None when its host has none; raises ValueError when the connection isn't
    safe for it."""
    host = host_of(base_url)
    key = _load().get(host)
    if key is not None and not may_send(base_url):
        raise ValueError(f"Use https for {host}, or a private network address, to send its key.")
    return key
