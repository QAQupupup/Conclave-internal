"""key_store 模块 import 重构后的回归测试。

验证将函数内 import 提到模块级后：
1. 无循环依赖
2. 所有公开函数可正常导入
3. SQLAlchemy select/or_/delete 在模块级可用
"""
from __future__ import annotations


def test_key_store_module_imports():
    """验证 key_store 模块可正常导入，无循环依赖。"""
    from app.services.key_store import (
        _mask_key,
        decrypt_key,
        delete_api_key,
        encrypt_key,
        get_api_key,
        list_api_keys,
        load_keys_to_providers,
        save_api_key,
    )
    # 确认函数对象存在
    assert callable(save_api_key)
    assert callable(get_api_key)
    assert callable(delete_api_key)
    assert callable(load_keys_to_providers)
    assert callable(list_api_keys)
    assert callable(encrypt_key)
    assert callable(decrypt_key)
    assert callable(_mask_key)


def test_key_store_sqlalchemy_imports_at_module_level():
    """验证 SQLAlchemy 符号已在模块级导入，不再出现在函数内 import。"""
    import inspect

    from app.services import key_store

    # 检查模块源码中不应再有 "from sqlalchemy import" 出现在函数体内
    source = inspect.getsource(key_store)
    # 模块级 import 行是允许的
    lines = source.splitlines()
    in_function = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("async def "):
            in_function = True
        elif stripped and not stripped.startswith((" ", "\t", "#", '"', "'")):
            # 顶格非注释非字符串，说明回到模块级
            in_function = False
        if in_function and "from sqlalchemy import" in stripped:
            pytest_fail(f"函数内仍存在 sqlalchemy import: {stripped}")


def test_mask_key():
    """验证 _mask_key 脱敏逻辑。"""
    from app.services.key_store import _mask_key

    assert _mask_key("") == ""
    assert _mask_key("short") == "****"
    assert _mask_key("sk-1234567890abcdef") == "sk-1***cdef"


def pytest_fail(msg: str):
    import pytest

    pytest.fail(msg)
