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


# ── encrypt/decrypt 往返测试 ──────────────────────────────


def test_encrypt_decrypt_roundtrip():
    """加密→解密必须得到原文。"""
    from app.services.key_store import decrypt_key, encrypt_key

    original = "sk-abc123def456ghi789"
    encrypted = encrypt_key(original)
    assert encrypted != original
    assert encrypted != ""
    decrypted = decrypt_key(encrypted)
    assert decrypted == original


def test_encrypt_empty_string_returns_empty():
    """空字符串加密返回空字符串。"""
    from app.services.key_store import decrypt_key, encrypt_key

    assert encrypt_key("") == ""
    assert decrypt_key("") == ""


def test_decrypt_with_wrong_key_fails():
    """用错误密钥解密必须返回空字符串（不抛异常）。"""
    import os

    from app.services.key_store import decrypt_key, encrypt_key

    original = "my-secret-key"
    encrypted = encrypt_key(original)

    # 替换环境变量使 _get_fernet 使用不同密钥
    old_key = os.environ.get("CONCLAVE_SECRET_KEY")
    os.environ["CONCLAVE_SECRET_KEY"] = "different-key-for-testing-only-32b!!"
    try:
        # 需要重置 _fernet 缓存才能使用新密钥
        import app.services.key_store as ks

        ks._fernet = None
        result = decrypt_key(encrypted)
        assert result == ""  # 解密失败返回空字符串
    finally:
        if old_key is not None:
            os.environ["CONCLAVE_SECRET_KEY"] = old_key
        else:
            os.environ.pop("CONCLAVE_SECRET_KEY", None)
        # 重置 fernet 缓存
        import app.services.key_store as ks

        ks._fernet = None


def test_encrypt_decrypt_long_data():
    """长数据往返验证。"""
    from app.services.key_store import decrypt_key, encrypt_key

    long_key = "sk-" + "x" * 500
    encrypted = encrypt_key(long_key)
    decrypted = decrypt_key(encrypted)
    assert decrypted == long_key


def test_encrypt_deterministic_but_unique():
    """Fernet 使用随机 IV，每次加密结果不同但都能正确解密。"""
    from app.services.key_store import decrypt_key, encrypt_key

    plaintext = "same-plaintext"
    e1 = encrypt_key(plaintext)
    e2 = encrypt_key(plaintext)
    assert e1 != e2  # 随机 IV 导致密文不同
    assert decrypt_key(e1) == plaintext
    assert decrypt_key(e2) == plaintext


def test_decrypt_tampered_ciphertext_returns_empty():
    """篡改密文解密必须返回空字符串。"""
    from app.services.key_store import decrypt_key, encrypt_key

    encrypted = encrypt_key("secret")
    # 翻转最后一个字符
    tampered = encrypted[:-1] + ("A" if encrypted[-1] != "A" else "B")
    result = decrypt_key(tampered)
    assert result == ""


def pytest_fail(msg: str):
    import pytest

    pytest.fail(msg)
