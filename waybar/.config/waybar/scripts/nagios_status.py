#!/usr/bin/env python3
"""
Nagios Waybar status script

Reads Nagios service status and outputs Waybar-compatible JSON.

Config file location:
    ~/.ssh/nagios-waybar.ini

Save the password into your keyring:
# secret-tool store --label="waybar_nagios_pass" app waybar_nagios key pass

Example config file:

[nagios]
# URL returning the service list
status_url = https://nagios.example.com/nagios/cgi-bin/statusjson.cgi?query=servicelist

# Base Nagios web URL (no trailing slash)
base_url = https://nagios.example.com/nagios

# Optional authentication
username = nagiosuser

# Verify SSL certificates
verify_ssl = true

# Total timeout budget in seconds.
# This is used:
#   1. as the timeout for the initial status request
#   2. as the total time budget for plugin_output lookups
timeout = 10

# Number of alerts to fetch plugin_output for at once
batch_size = 5
"""

import configparser
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import subprocess

import requests

CONFIG_FILE = Path.home() / ".ssh" / "nagios-waybar.ini"

STATUS_ORDER = {
    "CRITICAL": 0,
    "WARNING": 1,
    "UNKNOWN": 2,
}

def get_secret(*attrs: str) -> str:
    cmd = ["secret-tool", "lookup", *attrs]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "secret-tool lookup failed")
    return result.stdout.rstrip("\n")

def load_config():
    config = configparser.ConfigParser()

    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")

    config.read(CONFIG_FILE)

    if "nagios" not in config:
        raise KeyError("Missing [nagios] section in config")

    section = config["nagios"]

    status_url = section.get("status_url", "").strip()
    base_url = section.get("base_url", "").strip().rstrip("/")
    username = section.get("username", "").strip() or None
    password = section.get("password", "").strip() or None
    verify_ssl = section.getboolean("verify_ssl", fallback=True)
    timeout = section.getint("timeout", fallback=10)
    batch_size = section.getint("batch_size", fallback=5)

    if not status_url:
        raise ValueError("status_url must be set in config")
    if not base_url:
        raise ValueError("base_url must be set in config")
    if timeout <= 0:
        raise ValueError("timeout must be > 0")
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")

    return {
        "status_url": status_url,
        "base_url": base_url,
        "username": username,
        "password": password,
        "verify_ssl": verify_ssl,
        "timeout": timeout,
        "batch_size": batch_size,
    }


def get_auth(cfg):
    if cfg["username"] and cfg["password"]:
        return (cfg["username"], cfg["password"])
    return None


def get_status(cfg):
    r = requests.get(
        cfg["status_url"],
        auth=get_auth(cfg),
        verify=cfg["verify_ssl"],
        timeout=cfg["timeout"],
    )
    r.raise_for_status()
    return r.json()


def get_plugin_output(cfg, hostname, service, request_timeout):
    r = requests.get(
        f'{cfg["base_url"]}/cgi-bin/statusjson.cgi',
        params={
            "query": "service",
            "hostname": hostname,
            "servicedescription": service,
        },
        auth=get_auth(cfg),
        verify=cfg["verify_ssl"],
        timeout=request_timeout,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("service", {}).get("plugin_output", "")


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def parse_services(data):
    problems = []

    hosts = data.get("data", {}).get("servicelist", {})

    for host, host_services in hosts.items():
        if not isinstance(host_services, dict):
            continue

        for service, state in host_services.items():
            if state == 16:
                status = "CRITICAL"
            elif state == 4:
                status = "WARNING"
            elif state == 8:
                status = "UNKNOWN"
            else:
                continue

            problems.append((status, host, service, ""))

    return problems


def enrich_plugin_outputs_batched(cfg, problems, deadline):
    """
    Fetch plugin outputs in batches. Still one request per alert, but only a limited
    number are in flight at once. Once the deadline is exceeded, stop fetching outputs
    and return the remaining alerts without plugin output.
    """
    enriched = []
    skipped_plugin_output = False

    for batch in chunked(problems, cfg["batch_size"]):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            skipped_plugin_output = True
            enriched.extend(batch)
            continue

        # Keep each request within the remaining global budget.
        request_timeout = max(1, min(cfg["timeout"], int(remaining)))

        batch_results = {(status, host, service): "" for status, host, service, _ in batch}

        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            future_map = {
                executor.submit(get_plugin_output, cfg, host, service, request_timeout): (status, host, service)
                for status, host, service, _ in batch
            }

            for future in as_completed(future_map):
                status, host, service = future_map[future]
                try:
                    batch_results[(status, host, service)] = future.result()
                except Exception:
                    batch_results[(status, host, service)] = "[plugin output unavailable]"

        for status, host, service, _ in batch:
            enriched.append((status, host, service, batch_results[(status, host, service)]))

    return enriched, skipped_plugin_output


def sort_problems(problems):
    return sorted(
        problems,
        key=lambda p: (
            STATUS_ORDER.get(p[0], 99),
            p[1].lower(),
            p[2].lower(),
        ),
    )


def build_waybar_json(problems, skipped_plugin_output):
    problems = sort_problems(problems)

    critical_count = sum(1 for p in problems if p[0] == "CRITICAL")
    warning_count = sum(1 for p in problems if p[0] == "WARNING")
    unknown_count = sum(1 for p in problems if p[0] == "UNKNOWN")

    parts = []

    if critical_count > 0:
        parts.append(f'<span foreground="#f38ba8" weight="bold"> {critical_count}</span>')

    if warning_count > 0:
        parts.append(f'<span foreground="#f9e2af">⚠ {warning_count}</span>')

    if unknown_count > 0:
        parts.append(f'<span foreground="#94e2d5"> {unknown_count}</span>')

    if not parts:
        text = '<span foreground="#a6e3a1">󰄬 OK</span>'
        tooltip = "No service problems"
    else:
        text = "  ".join(parts)
        tooltip_lines = []

        if skipped_plugin_output:
            tooltip_lines.append(
                "[Some plugin outputs were skipped because the timeout limit was exceeded]"
            )

        for status, host, check, output in problems:
            if output:
                tooltip_lines.append(f"{status} | {host} | {check}\n{output}")
            else:
                tooltip_lines.append(f"{status} | {host} | {check}")

        tooltip = "\n\n".join(tooltip_lines)

    return {
        "text": text,
        "tooltip": tooltip,
        "class": "nagios",
    }


def build_error_json(message):
    return {
        "text": "󰅚 ERR",
        "tooltip": message,
        "class": "critical",
    }


def main():
    secret = False
    try:
        secret = get_secret("app", "waybar_nagios", "key", "pass")
    except:
        pass
    try:
        cfg = load_config()
        if secret:
            cfg["password"] = secret

        data = get_status(cfg)
        problems = parse_services(data)

        deadline = time.monotonic() + cfg["timeout"]
        problems, skipped = enrich_plugin_outputs_batched(cfg, problems, deadline)

        print(json.dumps(build_waybar_json(problems, skipped)))
    except Exception as e:
        print(json.dumps(build_error_json(f"Nagios script error: {e}")))


if __name__ == "__main__":
    main()
