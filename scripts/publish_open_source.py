#!/usr/bin/env python3
"""开发仓库 -> 开源仓库发布脚本。

功能：
1. 基于清单（scripts/oss_manifest.json）增量同步文件。
2. 编译 conclave_core 为 Cython 扩展（.pyd / .so）。
3. 删除开源仓库中的敏感/内部文档。
4. 生成 AUDIT_REPORT.md 审计报告。
5. 可选自动提交并推送开源仓库。

用法：
    python scripts/publish_open_source.py \
        --dev-repo . \
        --oss-repo ../Conclave-Open \
        --version 0.9.0 \
        --push

干跑：
    python scripts/publish_open_source.py --oss-repo ../Conclave-Open --dry-run
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST = "scripts/oss_manifest.json"


def _log(msg: str) -> None:
    print(f"[publish] {msg}")


def _error(msg: str) -> None:
    print(f"[publish] ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _git_rev(repo: Path) -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=repo, text=True, stderr=subprocess.DEVNULL
            )
            .strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


def _git_status_dirty(repo: Path) -> bool:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=repo, text=True, stderr=subprocess.DEVNULL
        )
        return bool(out.strip())
    except Exception:
        return False


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


_SKIP_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    ".idea",
    ".pnpm-store",
    ".trash",
}


def _should_skip(rel: Path) -> bool:
    """跳过依赖/缓存/临时目录，避免跨目录遍历和无效同步。"""
    return any(part in _SKIP_DIRS for part in rel.parts)


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        _error(f"清单文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(path: Path, manifest: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)


def _build_core_extensions(dev_repo: Path, dry_run: bool) -> list[Path]:
    """在 dev_repo/backend 中编译 conclave_core，返回生成的二进制文件路径。"""
    backend = dev_repo / "backend"
    setup_py = backend / "conclave_core" / "setup.py"
    if not setup_py.exists():
        _log("未找到 conclave_core/setup.py，跳过核心编译")
        return []

    if dry_run:
        _log("[dry-run] 将执行核心编译")
        return []

    _log("正在编译 conclave_core ...")
    try:
        subprocess.run(
            [sys.executable, str(setup_py), "build_ext", "--inplace"],
            cwd=backend,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        _error(f"核心编译失败:\n{exc.output}")

    binaries: list[Path] = []
    core_dir = backend / "conclave_core"
    for ext in (".pyd", ".so"):
        binaries.extend(core_dir.glob(f"*{ext}"))
    # 清理中间生成的 .c 文件，保持工作区干净
    for c_file in core_dir.glob("*.c"):
        c_file.unlink()

    _log(f"核心编译完成，生成 {len(binaries)} 个二进制扩展")
    return binaries


def _apply_replacements(dest_path: Path, replacements: list[list[str]]) -> bool:
    if not replacements or not dest_path.is_file():
        return False
    try:
        text = dest_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return False
    original = text
    for old, new in replacements:
        text = text.replace(old, new)
    if text != original:
        dest_path.write_text(text, encoding="utf-8")
        return True
    return False


def _sync_copy_entry(
    src_root: Path,
    dst_root: Path,
    entry: dict[str, Any],
    manifest: dict[str, Any],
    dry_run: bool,
) -> tuple[list[str], list[str]]:
    """同步单个 copy 条目，返回 (copied_files, replaced_files)。"""
    src = src_root / entry["src"]
    dst = dst_root / entry["dst"]
    state = manifest.setdefault("state", {})
    copied: list[str] = []
    replaced: list[str] = []

    if not src.exists():
        _log(f"源路径不存在，跳过: {src}")
        return copied, replaced

    if src.is_file():
        rel_key = entry["src"]
        current_hash = _file_hash(src)
        previous_hash = state.get(rel_key)
        if current_hash == previous_hash and dst.exists():
            return copied, replaced
        if not dry_run:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            state[rel_key] = current_hash
        copied.append(entry["dst"])
        if rel_key in manifest.get("replacements", {}):
            if not dry_run and _apply_replacements(dst, manifest["replacements"][rel_key]):
                replaced.append(entry["dst"])
        return copied, replaced

    # directory
    replacements_map = manifest.get("replacements", {})
    for file_path, rel in _iter_files(src):
        rel_key = f"{entry['src']}/{rel.as_posix()}"
        dest_file = dst / rel

        current_hash = _file_hash(file_path)
        previous_hash = state.get(rel_key)
        if current_hash == previous_hash and dest_file.exists():
            continue

        if not dry_run:
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file_path, dest_file)
            state[rel_key] = current_hash
        copied.append(entry["dst"] + "/" + rel.as_posix())

        # 对文本文件应用替换规则
        if rel_key in replacements_map:
            if not dry_run and _apply_replacements(dest_file, replacements_map[rel_key]):
                replaced.append(entry["dst"] + "/" + rel.as_posix())

    return copied, replaced


def _iter_files(src: Path):
    """遍历目录，跳过依赖/缓存目录和符号链接，避免跨目录错误。"""
    for root, dirs, files in os.walk(src, topdown=True, followlinks=False):
        root_path = Path(root)
        rel_root = root_path.relative_to(src)
        # 在进入子目录前过滤掉需要跳过的目录
        dirs[:] = [d for d in dirs if not _should_skip(rel_root / d)]
        for name in files:
            file_path = root_path / name
            rel = file_path.relative_to(src)
            if _should_skip(rel):
                continue
            yield file_path, rel


def _remove_protected_sources(dst_root: Path, manifest: dict[str, Any], dry_run: bool) -> list[str]:
    """删除开源仓库中残留的 conclave_core 算法源码文件，只保留 __init__.py、二进制扩展和未编译的模型源码。"""
    removed: list[str] = []
    core_dst = dst_root / "backend" / "conclave_core"
    if not core_dst.exists():
        return removed

    # 这些模块因包含 Pydantic BaseModel 不编译，需保留源码供导入
    keep_sources = {"__init__.py"}

    for py_file in core_dst.rglob("*.py"):
        if py_file.name in keep_sources:
            continue
        if not dry_run:
            py_file.unlink()
        removed.append(py_file.relative_to(dst_root).as_posix())
    for setup_file in core_dst.rglob("setup.py"):
        if not dry_run:
            setup_file.unlink()
        removed.append(setup_file.relative_to(dst_root).as_posix())
    return removed


def _delete_patterns(dst_root: Path, patterns: list[str], dry_run: bool) -> list[str]:
    deleted: list[str] = []
    for pattern in patterns:
        target = dst_root / pattern
        if target.exists():
            if not dry_run:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            deleted.append(pattern)
        else:
            # 尝试 glob 匹配更深层路径
            for matched in dst_root.rglob(pattern):
                if not dry_run:
                    if matched.is_dir():
                        shutil.rmtree(matched)
                    else:
                        matched.unlink()
                deleted.append(matched.relative_to(dst_root).as_posix())
    return deleted


def _generate_audit_report(
    dst_root: Path,
    manifest: dict[str, Any],
    dev_rev: str,
    copied: list[str],
    replaced: list[str],
    deleted: list[str],
    core_binaries: list[str],
    version: str,
    dry_run: bool,
) -> Path:
    report_name = manifest.get("audit_report_name", "AUDIT_REPORT.md")
    report_path = dst_root / report_name
    now = datetime.now(timezone.utc).isoformat()

    lines = [
        "# 开源版本发布审计报告",
        "",
        f"- 版本: `{version or 'unversioned'}`",
        f"- 发布时间: {now}",
        f"- 开发仓库 commit: `{dev_rev}`",
        f"- 清单版本: `{manifest.get('version', 'unknown')}`",
        "",
        "## 同步文件统计",
        "",
        f"- 新增/更新文件数: {len(copied)}",
        f"- 应用替换规则文件数: {len(replaced)}",
        f"- 删除目录/文件数: {len(deleted)}",
        f"- 核心扩展二进制数: {len(core_binaries)}",
        "",
        "## 核心扩展二进制",
        "",
    ]
    if core_binaries:
        for b in sorted(core_binaries):
            lines.append(f"- `{b}`")
    else:
        lines.append("- 未生成核心扩展二进制")
    lines.append("")

    lines.extend(["## 新增/更新文件", ""])
    for item in sorted(copied):
        lines.append(f"- `{item}`")
    lines.append("")

    if replaced:
        lines.extend(["## 应用替换规则的文件", ""])
        for item in sorted(replaced):
            lines.append(f"- `{item}`")
        lines.append("")

    lines.extend(["## 删除的敏感/内部目录或文件", ""])
    for item in sorted(deleted):
        lines.append(f"- `{item}`")
    lines.append("")

    lines.extend([
        "## 说明",
        "",
        "本报告由 `scripts/publish_open_source.py` 自动生成，记录了从开发仓库到开源仓库的发布动作。",
        "核心算法逻辑以编译后的二进制扩展形式存在，源码保留在私有开发仓库。",
        "",
    ])

    content = "\n".join(lines)
    if not dry_run:
        report_path.write_text(content, encoding="utf-8")
    return report_path


def _git_commit_and_push(repo: Path, version: str, branch: str | None, dry_run: bool) -> None:
    if dry_run:
        _log("[dry-run] 跳过 git 提交与推送")
        return
    if not (repo / ".git").exists():
        _error(f"目标仓库不是 git 仓库: {repo}")
    msg = f"chore(release): publish open-source version {version or 'latest'}"
    try:
        # auto-sync 是机器自动维护分支，强制重置到当前 HEAD 后再提交。
        if branch:
            subprocess.run(["git", "checkout", "-B", branch], cwd=repo, check=True)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-m", msg], cwd=repo, check=True)
        if branch:
            # auto-sync 分支允许 force push，因为它完全由本脚本重新生成。
            subprocess.run(["git", "push", "--force", "origin", branch], cwd=repo, check=True)
            _log(f"已提交并强制推送分支 {branch}: {msg}")
        else:
            subprocess.run(["git", "push"], cwd=repo, check=True)
            _log(f"已提交并推送: {msg}")
    except subprocess.CalledProcessError as exc:
        _error(f"git 操作失败: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="开发仓库到开源仓库的增量发布脚本")
    parser.add_argument("--dev-repo", default=".", help="开发仓库路径")
    parser.add_argument("--oss-repo", required=True, help="开源仓库路径")
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST, help="同步清单路径（相对于开发仓库）")
    parser.add_argument("--version", default="", help="发布版本号")
    parser.add_argument("--push", action="store_true", help="同步后自动提交并推送开源仓库")
    parser.add_argument("--branch", default="auto-sync", help="推送到的开源仓库分支（默认 auto-sync）")
    parser.add_argument("--prune", action="store_true", help="删除目标仓库中已从清单移除的文件")
    parser.add_argument("--dry-run", action="store_true", help="干跑，不实际修改文件")
    parser.add_argument("--skip-core-build", action="store_true", help="跳过 conclave_core 编译（用于测试同步流程）")
    args = parser.parse_args()

    dev_repo = Path(args.dev_repo).resolve()
    oss_repo = Path(args.oss_repo).resolve()
    manifest_path = (dev_repo / args.manifest).resolve()

    if not dev_repo.exists():
        _error(f"开发仓库不存在: {dev_repo}")
    if not oss_repo.exists():
        _error(f"开源仓库不存在: {oss_repo}")
    if dev_repo == oss_repo:
        _error("开发仓库和开源仓库不能是同一个路径")

    manifest = _load_manifest(manifest_path)

    _log(f"开发仓库: {dev_repo}")
    _log(f"开源仓库: {oss_repo}")
    _log(f"清单文件: {manifest_path}")
    if args.dry_run:
        _log("当前为干跑模式，不会修改任何文件")

    dev_rev = _git_rev(dev_repo)
    _log(f"开发仓库当前 commit: {dev_rev}")
    if _git_status_dirty(dev_repo):
        _log("警告：开发仓库存在未提交改动，建议先提交或确认后再发布")

    # 1. 编译核心扩展
    core_binaries: list[Path] = []
    if manifest.get("build_core", True) and not args.skip_core_build:
        core_binaries = _build_core_extensions(dev_repo, args.dry_run)
    elif args.skip_core_build:
        _log("跳过核心编译")

    # 2. 增量同步文件
    all_copied: list[str] = []
    all_replaced: list[str] = []
    for entry in manifest.get("copy", []):
        copied, replaced = _sync_copy_entry(
            dev_repo, oss_repo, entry, manifest, args.dry_run
        )
        all_copied.extend(copied)
        all_replaced.extend(replaced)

    # 3. 复制核心扩展二进制到开源仓库
    binary_names: list[str] = []
    if core_binaries:
        core_dst = oss_repo / "backend" / "conclave_core"
        if not args.dry_run:
            core_dst.mkdir(parents=True, exist_ok=True)
        for binary in core_binaries:
            dest = core_dst / binary.name
            binary_names.append(dest.relative_to(oss_repo).as_posix())
            if not args.dry_run:
                shutil.copy2(binary, dest)

    # 4. 清理开源仓库中的核心源码
    removed_sources = _remove_protected_sources(oss_repo, manifest, args.dry_run)

    # 5. 删除敏感文档
    deleted = _delete_patterns(oss_repo, manifest.get("delete_patterns", []), args.dry_run)

    # 6. 可选 prune：删除已从清单中消失的目标文件
    if args.prune:
        current_keys = set()
        for entry in manifest.get("copy", []):
            src = dev_repo / entry["src"]
            if src.is_file():
                current_keys.add(entry["src"])
            elif src.is_dir():
                for f in src.rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(src)
                        current_keys.add(f"{entry['src']}/{rel.as_posix()}")
        state = manifest.get("state", {})
        for old_key in list(state.keys()):
            if old_key not in current_keys:
                dest_rel = old_key  # 简单映射：源相对路径即目标相对路径
                dest_file = oss_repo / dest_rel
                if dest_file.exists():
                    if not args.dry_run:
                        dest_file.unlink()
                    deleted.append(dest_rel)
                del state[old_key]

    # 8. 生成审计报告
    report_path = _generate_audit_report(
        oss_repo,
        manifest,
        dev_rev,
        all_copied,
        all_replaced,
        deleted + removed_sources,
        binary_names,
        args.version,
        args.dry_run,
    )
    if not args.dry_run:
        _save_manifest(manifest_path, manifest)
        _log(f"审计报告已生成: {report_path}")

    # 9. 提交推送
    if args.push:
        _git_commit_and_push(oss_repo, args.version, args.branch, args.dry_run)

    _log("发布完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
