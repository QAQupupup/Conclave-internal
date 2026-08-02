"""JWT create/verify 往返测试。

覆盖 P0 审计发现：认证心脏函数零测试防护。
测试策略遵循 AGENTS.md §5.7.3 配对函数往返测试规范。
"""

from __future__ import annotations

import time
from unittest.mock import patch

from app.auth import _b64url_decode, _b64url_encode, create_jwt, verify_jwt

# ── 往返测试 ──────────────────────────────────────────────


class TestJWTRoundTrip:
    """create_jwt → verify_jwt 正向/反向验证。"""

    def test_valid_token_passes_verification(self) -> None:
        """有效 token 必须能被 verify_jwt 正确解析。"""
        payload = {"sub": "user-1", "role": "admin", "tid": 1}
        token = create_jwt(payload)
        result = verify_jwt(token)
        assert result is not None
        assert result["sub"] == "user-1"
        assert result["role"] == "admin"
        assert result["tid"] == 1
        # 标准声明必须存在
        assert "iss" in result
        assert "aud" in result
        assert "jti" in result
        assert "iat" in result
        assert "exp" in result

    def test_tampered_signature_rejected(self) -> None:
        """篡改签名的 token 必须返回 None。"""
        token = create_jwt({"sub": "user-1"})
        parts = token.split(".")
        s_b64 = parts[2]
        # 翻转签名段倒数第二个字符（确保影响解码后的字节，避免最后字符的填充位问题）
        # 最后一个 base64 字符只有 4 位有效，低 2 位被丢弃，翻转它可能不改变解码结果
        flip_idx = len(s_b64) - 2 if len(s_b64) >= 2 else 0
        orig = s_b64[flip_idx]
        tampered_sig = s_b64[:flip_idx] + ("A" if orig != "A" else "B") + s_b64[flip_idx + 1 :]
        tampered = f"{parts[0]}.{parts[1]}.{tampered_sig}"
        assert verify_jwt(tampered) is None

    def test_tampered_payload_rejected(self) -> None:
        """篡改 payload（中间段）的 token 必须返回 None。"""
        token = create_jwt({"sub": "user-1", "role": "user"})
        parts = token.split(".")
        # 修改 payload 段
        tampered_payload = parts[1][:-1] + ("A" if parts[1][-1] != "A" else "B")
        tampered = f"{parts[0]}.{tampered_payload}.{parts[2]}"
        assert verify_jwt(tampered) is None

    def test_expired_token_rejected(self) -> None:
        """已过期 token 必须返回 None。"""
        token = create_jwt({"sub": "user-1"}, expires_in=-1)  # 已过期
        # 确保过期
        time.sleep(0.1)
        assert verify_jwt(token) is None

    def test_malformed_token_returns_none(self) -> None:
        """格式错误（非3段）返回 None。"""
        assert verify_jwt("not-a-jwt") is None
        assert verify_jwt("only.two") is None
        assert verify_jwt("") is None

    def test_b64url_encode_decode_roundtrip(self) -> None:
        """base64url 编解码往返。"""
        for data in [b"hello", b"", b"\x00\x01\x02\xff", b"a" * 100]:
            encoded = _b64url_encode(data)
            decoded = _b64url_decode(encoded)
            assert decoded == data

    def test_different_secret_rejects_token(self) -> None:
        """使用不同密钥签发的 token 验证失败。"""
        token = create_jwt({"sub": "user-1"})
        with patch("app.auth._ensure_jwt_secret", return_value="different-secret"):
            assert verify_jwt(token) is None

    def test_iss_mismatch_rejected(self) -> None:
        """iss 声明不匹配必须拒绝。"""
        token = create_jwt({"sub": "user-1"})
        with patch("app.auth.JWT_ISSUER", "fake-issuer"):
            assert verify_jwt(token) is None

    def test_aud_mismatch_rejected(self) -> None:
        """aud 声明不匹配必须拒绝。"""
        token = create_jwt({"sub": "user-1"})
        with patch("app.auth.JWT_AUDIENCE", "fake-audience"):
            assert verify_jwt(token) is None

    def test_jti_is_unique(self) -> None:
        """每次创建的 jti 必须唯一。"""
        t1 = create_jwt({"sub": "u1"})
        t2 = create_jwt({"sub": "u1"})
        jti1 = verify_jwt(t1)["jti"]
        jti2 = verify_jwt(t2)["jti"]
        assert jti1 != jti2

    def test_custom_expires_in(self) -> None:
        """自定义过期时间必须生效。"""
        token = create_jwt({"sub": "u1"}, expires_in=3600)
        result = verify_jwt(token)
        assert result is not None
        assert result["exp"] - result["iat"] == 3600


class TestJWTSecurity:
    """JWT 安全边界测试。"""

    def test_none_algorithm_attack_rejected(self) -> None:
        """none 算法攻击（将 alg 改为 none 并去掉签名）必须被拒绝。"""
        import base64
        import json

        header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
        payload = (
            base64.urlsafe_b64encode(json.dumps({"sub": "admin", "exp": int(time.time()) + 3600}).encode())
            .decode()
            .rstrip("=")
        )
        attack_token = f"{header}.{payload}."
        assert verify_jwt(attack_token) is None

    def test_empty_string_rejected(self) -> None:
        """空字符串返回 None 而非抛异常。"""
        assert verify_jwt("") is None

    def test_garbage_bytes_rejected(self) -> None:
        """随机垃圾字符串不抛异常，返回 None。"""
        assert verify_jwt("!!!.@@@.###") is None
