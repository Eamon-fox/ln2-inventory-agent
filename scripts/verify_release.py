#!/usr/bin/env python3
"""发布后校验：比对线上 latest.json 与本地 latest.json 是否一致。

校验内容：
1. 线上 latest.json 可获取且为合法 JSON
2. version 与本地一致
3. 顶层 download_url（旧客户端兼容字段）与本地一致
4. platforms.windows / platforms.macos 的 download_url 与 asset_name 与本地一致
5. （可选，默认开启）双平台安装包 URL 可访问（HEAD 请求）

任何不一致都会明确报错并以非零退出码结束。

注意：OSS 若开启防盗链，匿名 GET/HEAD 可能返回 403，这不一定代表上传失败。
本脚本会把安装包 HEAD 的 403 视为警告；但 latest.json 拉不下来时无法完成
比对，会按校验失败处理，此时请改用有权限的环境或认证工具复核。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://snowfox-release.oss-cn-beijing.aliyuncs.com"
USER_AGENT = "SnowFox-Release-Verify/1.0"


def _request(url: str, *, method: str, timeout: float):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - 固定 https 发布域名


def _fetch_remote_latest(url: str, timeout: float) -> dict:
    try:
        with _request(url, method="GET", timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SystemExit(
                f"[ERROR] 拉取线上 latest.json 被拒绝 (403): {url}\n"
                "        OSS 防盗链可能拦截了匿名请求，无法完成比对。\n"
                "        请改用允许来源的环境或认证工具（如 oss_upload.py 所在环境）复核。"
            ) from exc
        raise SystemExit(f"[ERROR] 拉取线上 latest.json 失败 (HTTP {exc.code}): {url}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise SystemExit(f"[ERROR] 拉取线上 latest.json 失败: {url}\n        {exc}") from exc

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[ERROR] 线上 latest.json 不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("[ERROR] 线上 latest.json 顶层不是对象")
    return data


def _head_status(url: str, timeout: float) -> tuple[int, str]:
    try:
        with _request(url, method="HEAD", timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return -1, str(exc)


def _platform_fields(payload: dict, platform: str) -> dict[str, str]:
    entry = payload.get("platforms")
    entry = entry.get(platform) if isinstance(entry, dict) else None
    if not isinstance(entry, dict):
        entry = {}
    return {
        "download_url": str(entry.get("download_url", "")).strip(),
        "asset_name": str(entry.get("asset_name", "")).strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="校验线上 latest.json 与本地是否一致")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"发布桶公网地址（默认 {DEFAULT_BASE_URL}）",
    )
    parser.add_argument(
        "--local",
        default=str(Path(__file__).resolve().parent.parent / "latest.json"),
        help="本地 latest.json 路径（默认仓库根目录）",
    )
    parser.add_argument("--timeout", type=float, default=15.0, help="网络超时秒数（默认 15）")
    parser.add_argument(
        "--skip-assets",
        action="store_true",
        help="跳过双平台安装包 URL 的 HEAD 可达性检查",
    )
    args = parser.parse_args()

    local_path = Path(args.local)
    if not local_path.is_file():
        raise SystemExit(f"[ERROR] 找不到本地 latest.json: {local_path}")
    local = json.loads(local_path.read_text(encoding="utf-8"))

    remote_url = f"{args.base_url.rstrip('/')}/latest.json"
    print(f"[校验] 线上 latest.json: {remote_url}")
    remote = _fetch_remote_latest(remote_url, args.timeout)

    errors: list[str] = []
    warnings: list[str] = []

    checks: list[tuple[str, str, str]] = [
        (
            "version",
            str(local.get("version", "")).strip(),
            str(remote.get("version", "")).strip(),
        ),
        (
            "download_url",
            str(local.get("download_url", "")).strip(),
            str(remote.get("download_url", "")).strip(),
        ),
    ]
    for platform in ("windows", "macos"):
        local_fields = _platform_fields(local, platform)
        remote_fields = _platform_fields(remote, platform)
        for field in ("download_url", "asset_name"):
            checks.append(
                (
                    f"platforms.{platform}.{field}",
                    local_fields[field],
                    remote_fields[field],
                )
            )

    for label, local_value, remote_value in checks:
        if not local_value:
            errors.append(f"本地 latest.json 缺少 {label}")
            continue
        if local_value != remote_value:
            errors.append(
                f"{label} 不一致:\n"
                f"    本地: {local_value or '(空)'}\n"
                f"    线上: {remote_value or '(空)'}"
            )
        else:
            print(f"  [OK] {label}: {local_value}")

    if not args.skip_assets:
        print("[校验] 安装包 URL 可达性 (HEAD)")
        for platform in ("windows", "macos"):
            asset_url = _platform_fields(local, platform)["download_url"]
            if not asset_url:
                errors.append(f"本地 latest.json 缺少 platforms.{platform}.download_url")
                continue
            status, detail = _head_status(asset_url, args.timeout)
            if status == 200:
                print(f"  [OK] {platform}: {asset_url}")
            elif status == 403:
                warnings.append(
                    f"{platform} 安装包 HEAD 返回 403（可能是 OSS 防盗链），"
                    f"不视为失败，请用认证工具复核: {asset_url}"
                )
            elif status == -1:
                errors.append(f"{platform} 安装包 URL 请求失败: {asset_url}\n    {detail}")
            else:
                errors.append(f"{platform} 安装包 URL 返回 HTTP {status}: {asset_url}")

    print()
    for warning in warnings:
        print(f"[WARN] {warning}")
    if errors:
        print("[ERROR] 发布校验未通过:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"[OK] 线上发布元数据与本地一致: v{local.get('version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
