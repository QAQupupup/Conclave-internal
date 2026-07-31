/**
 * 客户端密码预哈希工具
 *
 * 安全设计：密码在浏览器端先做 SHA-256 哈希，再发送到后端。
 * 后端收到的是 client_hash = SHA-256(password)，再对其做 PBKDF2 存储。
 * 这样即使 HTTPS 被中间人破解，攻击者拿到的也只是 SHA-256(password)，
 * 而非明文密码（用户在其他站点可能复用同一密码）。
 *
 * 使用 Web Crypto API（SubtleCrypto），所有现代浏览器原生支持，无需第三方库。
 */

/**
 * 对密码做 SHA-256 预哈希，返回十六进制字符串。
 *
 * @param password - 用户输入的明文密码
 * @returns SHA-256(password) 的十六进制表示（64 字符）
 */
export async function sha256Hash(password: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(password);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = new Uint8Array(hashBuffer);
  // 转为十六进制字符串
  return Array.from(hashArray)
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
}
