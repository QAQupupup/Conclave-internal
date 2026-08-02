"""密码哈希与验证单元测试。

这是认证系统最核心的安全功能。此前 verify_password 存在段数检查 bug
（hash_password 生成 4 段但 verify_password 检查 5 段），导致所有登录返回 401。
本测试覆盖完整的 hash → verify 往返链路，防止此类 bug 再次发生。
"""

import hashlib

from app.auth import (
    PBKDF2_ITERATIONS,
    PBKDF2_ITERATIONS_LEGACY,
    client_hash_password,
    hash_password,
    verify_password,
)


class TestHashFormat:
    """验证存储格式的结构正确性。"""

    def test_hash_has_4_segments(self):
        """hash_password 输出按 $ 分割必须恰好 4 段。

        这是此前 bug 的直接回归测试：
        hash_password 生成 4 段，但 verify_password 曾错误检查 5 段。
        """
        h = hash_password("test_password")
        parts = h.split("$")
        assert len(parts) == 4, f"期望 4 段，实际 {len(parts)} 段: {h}"

    def test_hash_prefix_is_pbkdf2_ch_sha256(self):
        """新格式前缀必须是 pbkdf2_ch_sha256。"""
        h = hash_password("test_password")
        assert h.startswith("pbkdf2_ch_sha256$"), f"前缀错误: {h[:30]}"

    def test_hash_contains_iterations(self):
        """第二段必须是迭代次数整数。"""
        h = hash_password("test_password")
        parts = h.split("$")
        assert parts[1].isdigit(), f"迭代次数不是数字: {parts[1]}"
        assert int(parts[1]) == PBKDF2_ITERATIONS

    def test_hash_contains_valid_base64(self):
        """第三段 salt 和第四段 hash 必须是合法 base64。"""
        import base64

        h = hash_password("test_password")
        parts = h.split("$")
        # salt 和 hash 都应能 base64 解码
        base64.b64decode(parts[2])  # 不抛异常即可
        base64.b64decode(parts[3])


class TestVerifyRoundTrip:
    """hash_password → verify_password 完整往返测试。"""

    def test_correct_password_verifies(self):
        """正确密码必须验证通过。"""
        password = "my_secret_password_123"
        stored = hash_password(password)
        valid, _needs_rehash = verify_password(password, stored)
        assert valid is True, "正确密码验证失败 — 这是最核心的安全 bug"

    def test_wrong_password_rejected(self):
        """错误密码必须验证失败。"""
        stored = hash_password("correct_password")
        valid, _ = verify_password("wrong_password", stored)
        assert valid is False

    def test_empty_password_rejected_if_hashed_with_nonempty(self):
        """空密码不能匹配非空密码的哈希。"""
        stored = hash_password("nonempty_password")
        valid, _ = verify_password("", stored)
        assert valid is False

    def test_similar_password_rejected(self):
        """近似密码不能匹配。"""
        stored = hash_password("admin123")
        valid, _ = verify_password("admin1234", stored)
        assert valid is False

    def test_different_salts_produce_different_hashes(self):
        """相同密码不同 salt 产生不同哈希。"""
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        assert h1 != h2, "不同 salt 应产生不同哈希"

    def test_same_salt_produces_same_hash(self):
        """相同密码和 salt 产生相同哈希（确定性）。"""
        salt = b"\x00" * 16
        h1 = hash_password("same_password", salt=salt)
        h2 = hash_password("same_password", salt=salt)
        assert h1 == h2


class TestClientHashChain:
    """模拟前端 SHA-256 预哈希 → 后端 PBKDF2 的完整安全链路。

    真实流程：
    1. 前端: client_hash = SHA-256(明文密码)
    2. 前端发送 client_hash 到后端
    3. 后端: stored_hash = PBKDF2(client_hash)  ← hash_password
    4. 登录时: verify_password(client_hash, stored_hash)  ← verify_password
    """

    def test_full_chain_admin123(self):
        """模拟 admin 默认密码的完整链路。"""
        plaintext = "admin123"
        client_hash = client_hash_password(plaintext)  # SHA-256 hex
        stored = hash_password(client_hash)  # PBKDF2(client_hash)

        # 登录验证
        valid, _ = verify_password(client_hash, stored)
        assert valid is True, "admin123 完整链路验证失败"

    def test_full_chain_custom_password(self):
        """模拟自定义密码的完整链路。"""
        plaintext = "MyStr0ngP@ssw0rd!"
        client_hash = client_hash_password(plaintext)
        stored = hash_password(client_hash)

        valid, _ = verify_password(client_hash, stored)
        assert valid is True

    def test_full_chain_wrong_plaintext(self):
        """错误明文的 client_hash 不能通过验证。"""
        client_hash_correct = client_hash_password("correct_pw")
        stored = hash_password(client_hash_correct)

        client_hash_wrong = client_hash_password("wrong_pw")
        valid, _ = verify_password(client_hash_wrong, stored)
        assert valid is False

    def test_sha256_hex_length(self):
        """client_hash_password 输出必须是 64 字符十六进制（SHA-256）。"""
        h = client_hash_password("test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestNeedsRehash:
    """needs_rehash 标志测试。"""

    def test_current_iterations_no_rehash(self):
        """当前迭代次数不需要 rehash。"""
        stored = hash_password("pw", iterations=PBKDF2_ITERATIONS)
        _, needs_rehash = verify_password("pw", stored)
        assert needs_rehash is False

    def test_legacy_iterations_triggers_rehash(self):
        """旧迭代次数需要 rehash。"""
        stored = hash_password("pw", iterations=PBKDF2_ITERATIONS_LEGACY)
        valid, needs_rehash = verify_password("pw", stored)
        assert valid is True
        assert needs_rehash is True, "旧迭代次数应触发 needs_rehash"


class TestLegacyFormatCompat:
    """旧格式 pbkdf2_sha256$... 兼容性测试。"""

    def test_legacy_format_with_client_hash(self):
        """旧格式存储 + client_hash 输入应能匹配（路径 B 兼容）。"""
        import base64
        import secrets

        password = "test_legacy_pw"
        salt = secrets.token_bytes(16)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS_LEGACY)
        legacy_hash = f"pbkdf2_sha256${PBKDF2_ITERATIONS_LEGACY}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"

        valid, needs_rehash = verify_password(password, legacy_hash)
        assert valid is True, "旧格式兼容验证失败"
        assert needs_rehash is True, "旧格式匹配后应触发迁移"

    def test_invalid_format_returns_false(self):
        """无法识别的格式返回 (False, False)。"""
        valid, needs_rehash = verify_password("pw", "unknown_format$data")
        assert valid is False
        assert needs_rehash is False

    def test_malformed_hash_returns_false(self):
        """格式错误不抛异常，返回 (False, False)。"""
        valid, _ = verify_password("pw", "pbkdf2_ch_sha256$not_a_number$abc$def")
        assert valid is False
