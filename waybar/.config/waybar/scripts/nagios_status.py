#!/usr/bin/env python3

import configparser
import json
import time
from pathlib import Path

import requests

CONFIG_FILE = Path.home() / ".ssh" / "nagios-waybar.ini"
MAX_PLUGIN_OUTPUT_TIME = 5.0


def load_config():
    config = configparser.ConfigParser()
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")

    config.read(CONFIG_FILE)

    if "nagios" not in config:
        raise KeyError("Missing [nagios] section in config file")

    section = config["nagios"]

    status_url = section.get("status_url", "").strip()
    base_url = section.get("base_url", "").strip().rstrip("/")
    username = section.get("username", "").strip() or None
    password = section.get("password", "").strip() or None
    verify_ssl = section.getboolean("verify_ssl", fallback=True)
    timeout = section.getint("timeout", fallback=10)

    if not status_url:
        raise ValueError("status_url is required in config")
    if not base_url:
        raise ValueError("base_url is required in config")

    return {
        "status_url": status_url,
        "base_url": base_url,
        "username": username,
        "password": password,
        "verify_ssl": verify_ssl,
        "timeout": timeout,
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


def get_plugin_output(cfg, hostname, service):
    r = requests.get(
        f'{cfg["base_url"]}/cgi-bin/statusjson.cgi',
        params={
            "query": "service",
            "hostname": hostname,
            "servicedescription": service,
        },
        auth=get_auth(cfg),
        verify=cfg["verify_ssl"],
        timeout=cfg["timeout"],
    )
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("service", {}).get("plugin_output", "")


def parse_services(cfg, data, plugin_output_deadline):
    problems = []
    skipped_plugin_output = False

    hosts = data.get("data", {}).get("servicelist", {})

    for host, host_services in hosts.items():
        if not isinstance(host_services, dict):
            continue

        for service, state in host_services.items():
            if state == 4:
                status = "WARNING"
            elif state == 16:
                status = "CRITICAL"
            elif state == 8:
                status = "UNKNOWN"
            else:
                continue

            plugin_output = ""

            # Only try plugin_output lookups while still inside the deadline.
            if time.monotonic() < plugin_output_deadline:
                try:
                    plugin_output = get_plugin_output(cfg, host, service)
                except Exception:
                    plugin_output = "[plugin output unavailable]"
            else:
                skipped_plugin_output = True
                plugin_output = "[plugin output skipped: time limit exceeded]"

            problems.append((status, host, service, plugin_output))

    return problems, skipped_plugin_output


def build_waybar_json(problems, skipped_plugin_output=False):
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
            tooltip_lines.append("[Some plugin outputs were skipped because the 10s limit was exceeded]")

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
    try:
        cfg = load_config()
        data = get_status(cfg)

        start_time = time.monotonic()
        plugin_output_deadline = start_time + MAX_PLUGIN_OUTPUT_TIME

        problems, skipped_plugin_output = parse_services(cfg, data, plugin_output_deadline)

        print(json.dumps(build_waybar_json(problems, skipped_plugin_output)))
    except Exception as e:
        print(json.dumps(build_error_json(f"Nagios script error: {e}")))


if __name__ == "__main__":
    main()
