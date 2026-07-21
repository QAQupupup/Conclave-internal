# CAPTCHA 值守管理器（Human-in-the-loop）
#
# 架构：
#   当检测到验证码且值守模式开启时：
#   1. 截取当前页面截图（base64）
#   2. 通过系统事件总线广播 captcha.pending 事件
#   3. 暂停浏览器操作，等待用户通过前端介入
#   4. 用户在 noVNC 窗口中手动完成验证码后点击"已完成"
#   5. 后端收到 resolve 信号后，恢复页面检测，继续流程
#
# 浏览器访问方式：
#   - 值守模式下 Chromium 以有头模式（headless=False）在 Xvfb 虚拟显示器中运行
#   - x11vnc 将 Xvfb 显示导出为 VNC 协议
#   - websockify + noVNC 提供 Web 端 VNC 客户端
#   - 前端通过 iframe 嵌入 noVNC，用户直接在网页中操作浏览器
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.lazy_asyncio import LazyLock

logger = logging.getLogger("app.tools.captcha_guard")


class CaptchaStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class CaptchaSession:
    """一个待人工处理的验证码会话"""

    session_id: str
    url: str
    captcha_types: list[str]
    page_title: str
    screenshot_b64: str  # base64 encoded PNG
    created_at: float
    meeting_id: str | None = None
    status: CaptchaStatus = CaptchaStatus.PENDING
    resolved_at: float | None = None
    # 恢复事件：被设置时表示用户已处理完验证码
    _resume_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    # 关联的页面对象（Playwright Page，由调用方设置）
    _page: Any = field(default=None, repr=False)
    # VNC 端口（noVNC WebSocket 端口）
    vnc_port: int = 6080
    # 超时时间（秒）
    timeout: int = 300

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "url": self.url,
            "captcha_types": self.captcha_types,
            "page_title": self.page_title,
            "screenshot": self.screenshot_b64[:100] + "..." if self.screenshot_b64 else "",
            "created_at": self.created_at,
            "meeting_id": self.meeting_id,
            "status": self.status.value,
            "resolved_at": self.resolved_at,
            "vnc_url": "/vnc/vnc.html?autoconnect=true&resize=scale",
            "vnc_port": self.vnc_port,
            "timeout": self.timeout,
            "elapsed": round(time.time() - self.created_at, 1),
        }


class CaptchaGuard:
    """CAPTCHA 值守管理器（单例）"""

    def __init__(self) -> None:
        self._sessions: dict[str, CaptchaSession] = {}
        self._lock = asyncio.Lock()
        # 值守模式开关：可通过 API 动态切换
        self._guard_mode: bool = os.environ.get("CONCLAVE_GUARD_MODE", "0") == "1"
        # VNC 是否已启动
        self._vnc_ready: bool = False
        # VNC 启动锁
        self._vnc_lock = asyncio.Lock()
        logger.info("CaptchaGuard 初始化: guard_mode=%s", self._guard_mode)

    @property
    def guard_mode(self) -> bool:
        return self._guard_mode

    def set_guard_mode(self, enabled: bool) -> None:
        """动态切换值守模式"""
        self._guard_mode = enabled
        logger.info("CAPTCHA 值守模式: %s", "开启" if enabled else "关闭")

    async def start_vnc(self) -> bool:
        """启动 Xvfb + x11vnc + websockify（按需启动，仅值守模式使用）

        启动流程：
        1. Xvfb :99 -screen 0 1280x800x24 &
        2. x11vnc -display :99 -forever -nopw -rfbport 5900 -shared &
        3. websockify --web /usr/share/novnc/ 6080 localhost:5900 &

        浏览器通过 DISPLAY=:99 启动到虚拟显示器。
        用户通过 http://host:6080/vnc.html 访问 noVNC。
        """
        if self._vnc_ready:
            return True

        async with self._vnc_lock:
            if self._vnc_ready:
                return True

            try:
                # 检查必要的二进制是否存在
                for cmd in ["Xvfb", "x11vnc", "websockify"]:
                    result = await asyncio.create_subprocess_exec(
                        "which",
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    await result.wait()
                    if result.returncode != 0:
                        logger.warning("VNC 依赖缺失: %s，值守VNC功能不可用", cmd)
                        return False

                # 设置 DISPLAY 环境变量
                os.environ["DISPLAY"] = ":99"

                # 启动 Xvfb（虚拟 X 服务器）
                await asyncio.create_subprocess_exec(
                    "Xvfb",
                    ":99",
                    "-screen",
                    "0",
                    "1280x800x24",
                    "-ac",
                    "-nolisten",
                    "tcp",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.sleep(1)  # 等待 Xvfb 启动

                # 启动 x11vnc（VNC 服务器）
                await asyncio.create_subprocess_exec(
                    "x11vnc",
                    "-display",
                    ":99",
                    "-forever",
                    "-nopw",
                    "-rfbport",
                    "5900",
                    "-shared",
                    "-noxdamage",
                    "-wait",
                    "50",
                    "-bg",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.sleep(1)

                # 启动 websockify（WebSocket 代理 + noVNC 静态文件服务）
                novnc_web_dir = "/usr/share/novnc/"
                if not os.path.isdir(novnc_web_dir):
                    novnc_web_dir = "/usr/share/novnc"
                # 查找系统中 noVNC 的安装路径
                for candidate in ["/usr/share/novnc", "/usr/local/share/novnc", "/opt/novnc"]:
                    if os.path.isdir(candidate):
                        novnc_web_dir = candidate
                        break

                await asyncio.create_subprocess_exec(
                    "websockify",
                    "6080",
                    "localhost:5900",
                    "--web",
                    novnc_web_dir,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await asyncio.sleep(1)

                self._vnc_ready = True
                logger.info("VNC 值守环境启动成功: DISPLAY=:99, noVNC 端口=6080")
                return True

            except Exception as e:
                logger.error("VNC 环境启动失败: %s", str(e)[:200])
                self._vnc_ready = False
                return False

    def is_vnc_ready(self) -> bool:
        return self._vnc_ready

    async def intercept_captcha(
        self,
        page: Any,
        url: str,
        captcha_types: list[str],
        page_title: str = "",
        meeting_id: str | None = None,
        timeout: int = 300,
    ) -> CaptchaStatus:
        """拦截验证码，等待用户处理

        流程：
        1. 截图
        2. 创建 CaptchaSession
        3. 广播 captcha.pending 事件
        4. 等待 _resume_event 或超时
        5. 返回结果状态

        Args:
            page: Playwright Page 对象
            url: 当前 URL
            captcha_types: 检测到的验证码类型列表
            page_title: 页面标题
            meeting_id: 关联的会议 ID
            timeout: 超时秒数

        Returns:
            CaptchaStatus: RESOLVED / TIMEOUT / SKIPPED
        """
        # 非值守模式：直接跳过
        if not self._guard_mode:
            return CaptchaStatus.SKIPPED

        session_id = f"captcha-{uuid.uuid4().hex[:12]}"

        try:
            # 截图
            screenshot_b64 = ""
            try:
                screenshot_bytes = await page.screenshot(type="png", full_page=False)
                screenshot_b64 = base64.b64encode(screenshot_bytes).decode("ascii")
            except Exception as e:
                logger.warning("CAPTCHA 截图失败: %s", str(e)[:100])

            session = CaptchaSession(
                session_id=session_id,
                url=url,
                captcha_types=captcha_types,
                page_title=page_title,
                screenshot_b64=screenshot_b64,
                created_at=time.time(),
                meeting_id=meeting_id,
                timeout=timeout,
                _page=page,
            )

            async with self._lock:
                self._sessions[session_id] = session

            # 确保 VNC 环境已启动
            if not self._vnc_ready:
                await self.start_vnc()

            # 广播 captcha.pending 事件到系统总线
            try:
                from app.events import bus, make_event

                await bus.publish(
                    make_event(
                        "captcha.pending",
                        meeting_id or "system",
                        {
                            "session_id": session_id,
                            "url": url,
                            "captcha_types": captcha_types,
                            "page_title": page_title,
                            "has_screenshot": bool(screenshot_b64),
                            "vnc_ready": self._vnc_ready,
                            "vnc_url": session.snapshot()["vnc_url"] if self._vnc_ready else None,
                            "timeout": timeout,
                        },
                    )
                )
            except Exception as e:
                logger.warning("广播 captcha.pending 事件失败: %s", str(e)[:100])

            logger.warning(
                "CAPTCHA 拦截: session=%s url=%s types=%s vnc=%s 等待人工处理...",
                session_id,
                url[:60],
                captcha_types,
                self._vnc_ready,
            )

            # 等待用户处理或超时
            try:
                await asyncio.wait_for(session._resume_event.wait(), timeout=timeout)
                session.status = CaptchaStatus.RESOLVED
                session.resolved_at = time.time()
                logger.info(
                    "CAPTCHA 已人工解决: session=%s 耗时%.1fs", session_id, session.resolved_at - session.created_at
                )

                # 通知前端验证码已解决
                try:
                    from app.events import bus, make_event

                    await bus.publish(
                        make_event(
                            "captcha.resolved",
                            meeting_id or "system",
                            {"session_id": session_id},
                        )
                    )
                except Exception:
                    pass

                # 等待一小段时间让页面跳转/加载完成
                await asyncio.sleep(2)
                return CaptchaStatus.RESOLVED

            except asyncio.TimeoutError:
                session.status = CaptchaStatus.TIMEOUT
                logger.warning("CAPTCHA 等待超时: session=%s (%ds)", session_id, timeout)

                try:
                    from app.events import bus, make_event

                    await bus.publish(
                        make_event(
                            "captcha.timeout",
                            meeting_id or "system",
                            {"session_id": session_id},
                        )
                    )
                except Exception:
                    pass

                return CaptchaStatus.TIMEOUT

        except Exception as e:
            logger.error("CAPTCHA 拦截异常: %s", str(e)[:200])
            return CaptchaStatus.SKIPPED
        finally:
            # 清理会话（保留一段时间供前端查询）
            pass

    def resolve(self, session_id: str) -> bool:
        """用户标记验证码已完成，恢复流程"""
        session = self._sessions.get(session_id)
        if not session:
            logger.warning("resolve: 未找到 CAPTCHA 会话 %s", session_id)
            return False
        if session.status != CaptchaStatus.PENDING:
            logger.warning("resolve: 会话 %s 状态为 %s，非 pending", session_id, session.status)
            return False
        session._resume_event.set()
        logger.info("CAPTCHA 会话已标记解决: %s", session_id)
        return True

    def get_session(self, session_id: str) -> CaptchaSession | None:
        return self._sessions.get(session_id)

    def get_pending_sessions(self) -> list[dict[str, Any]]:
        """获取所有待处理的验证码会话"""
        return [s.snapshot() for s in self._sessions.values() if s.status == CaptchaStatus.PENDING]

    def get_all_sessions(self) -> list[dict[str, Any]]:
        """获取所有验证码会话"""
        return [s.snapshot() for s in self._sessions.values()]

    async def get_screenshot(self, session_id: str) -> str | None:
        """获取会话的最新截图（base64）"""
        session = self._sessions.get(session_id)
        if not session or not session._page:
            return None
        try:
            if session.status == CaptchaStatus.PENDING:
                # 实时截图
                screenshot_bytes = await session._page.screenshot(type="png", full_page=False)
                b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                session.screenshot_b64 = b64
                return b64
            return session.screenshot_b64
        except Exception:
            return session.screenshot_b64

    def cleanup_old_sessions(self, max_age: float = 600) -> int:
        """清理过期会话（默认10分钟前的）"""
        now = time.time()
        to_remove = [
            sid
            for sid, s in self._sessions.items()
            if s.status != CaptchaStatus.PENDING and (now - s.created_at) > max_age
        ]
        for sid in to_remove:
            del self._sessions[sid]
        return len(to_remove)

    def get_display_env(self) -> dict[str, str]:
        """获取浏览器启动需要的 DISPLAY 环境变量（值守模式有头浏览器需要）"""
        if self._guard_mode and self._vnc_ready:
            return {"DISPLAY": ":99"}
        return {}


# 全局单例
_guard_instance: CaptchaGuard | None = None
_guard_lock = LazyLock()


async def get_captcha_guard() -> CaptchaGuard:
    """获取 CaptchaGuard 单例"""
    global _guard_instance
    if _guard_instance is None:
        async with _guard_lock:
            if _guard_instance is None:
                _guard_instance = CaptchaGuard()
    return _guard_instance
