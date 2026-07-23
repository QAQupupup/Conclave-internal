# Playwright 搜索子包
# 反检测脚本（stealth_js / captcha_js）在开源版中被移除，import 优雅降级
try:
    from .stealth_js import _STEALTH_JS as _STEALTH_JS
except ImportError:
    _STEALTH_JS = ""

try:
    from .captcha_js import _CAPTCHA_DETECT_JS as _CAPTCHA_DETECT_JS
except ImportError:
    _CAPTCHA_DETECT_JS = ""

from .chunk_js import _CHUNK_EXTRACT_JS as _CHUNK_EXTRACT_JS
from .extract_js import _EXTRACT_JS as _EXTRACT_JS
from .jsonld_js import _JSONLD_EXTRACT_JS as _JSONLD_EXTRACT_JS
from .session_pool import SessionPool as SessionPool
