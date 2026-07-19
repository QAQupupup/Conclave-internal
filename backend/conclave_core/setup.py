"""Cython 构建脚手架示例（conclave_core）。

本文件展示如何将 conclave_core 包下的纯 Python 模块编译为 C 扩展（.so / .pyd）。
当前项目默认仍以纯 Python 方式运行；如需启用编译，可将本 setup.py 提升到
backend/ 根目录执行：

    cd backend
    python conclave_core/setup.py build_ext --inplace

或在 pyproject.toml 中通过 [tool.setuptools.ext-modules] / setup.py 接入。
"""

from __future__ import annotations

import os
from pathlib import Path

from Cython.Build import cythonize
from setuptools import Extension, setup

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent


EXCLUDED_MODULES: set[str] = {
    # 纯 Pydantic 数据模型保持源码形式发布，业务逻辑已迁移到 *_logic 模块进行编译保护。
    "conclave_core.charter",
    "conclave_core.conclusion_chain",
}


def _collect_modules(package_dir: Path) -> list[str]:
    """收集包内需要编译为 Cython 扩展的 .py 模块（排除 __init__.py、setup.py 与 Pydantic 模型）。"""
    modules: list[str] = []
    for py_file in sorted(package_dir.rglob("*.py")):
        if py_file.name in {"__init__.py", "setup.py"}:
            continue
        rel = py_file.relative_to(BACKEND_DIR)
        module_name = str(rel.with_suffix("")).replace(os.sep, ".")
        if module_name in EXCLUDED_MODULES:
            continue
        modules.append(module_name)
    return modules


def _build_extensions() -> list[Extension]:
    """为每个目标模块构造 setuptools.Extension。"""
    modules = _collect_modules(PACKAGE_DIR)
    return [
        Extension(
            name=module,
            sources=[str(BACKEND_DIR / module.replace(".", os.sep)) + ".py"],
            extra_compile_args=["-O3"],
        )
        for module in modules
    ]


setup(
    name="conclave-core-cython",
    ext_modules=cythonize(
        _build_extensions(),
        compiler_directives={"language_level": "3"},
        annotate=False,
    ),
    zip_safe=False,
)
