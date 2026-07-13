# 信源可信度注册表
#
# 分级体系（5 tier）：
#   S - 官方源：域名与实体名匹配，官方维护（如 python.org 对应 Python）
#   A - 权威参考：知名参考站，有编辑审核（如 MDN, Wikipedia, W3C）
#   B - 优质社区：声誉系统，社区审核（如 GitHub, Stack Overflow）
#   C - 普通第三方：无审核但内容可能有价值（默认，对未知公网域名）
#   D - 低质量：采集站、营销号、SEO 农场
#
# Phase 1 范围：静态注册表 + Bing 排除 + 结果分级标注
# Phase 2 范围：canonical URL 验证 + 版权检测 + 内容深度
# Phase 3 范围：交叉验证（当前仅"不同域名"≠真正独立性）
#
# 评审修正（来自 Claude 交叉评审）：
# - SSL 证书不作为评分因子（Let's Encrypt 普及后零信息量）
# - 域名年龄仅作 C-tier 内部 tiebreaker，不影响 S/A/B 判定
# - canonical 必须验证目标域名在 S/A 注册表中才加分
# - ICP 备案查询移除（无干净公开 API）
# - credibility_score 使用确定性公式，非手工赋值
# - 实体识别用子串匹配，不用 NER/LLM（零额外开销）
from __future__ import annotations

from enum import Enum
from urllib.parse import urlparse


class DomainTier(str, Enum):
    """信源等级"""
    S = "S"  # 官方源
    A = "A"  # 权威参考
    B = "B"  # 优质社区
    C = "C"  # 普通第三方（默认）
    D = "D"  # 低质量/注水


# ================================================================
# 实体 → 官方域名映射（用于子串匹配后 boost + S-tier 标注）
# ================================================================

# 实体别名（小写子串匹配，避免 NER/LLM 开销）
# 格式：entity_key → [alias1, alias2, ...]
ENTITY_ALIASES: dict[str, list[str]] = {
    "python": ["python", "cpython", "pip install", "py3", "django", "flask", "fastapi"],
    "typescript": ["typescript", "tsconfig", "tsc "],
    "javascript": ["javascript", "node.js", "nodejs", "npm ", "ecmascript"],
    "rust": ["rust", "cargo ", "crates.io", "rustup"],
    "golang": ["golang", "go module", "go build", "go mod"],
    "java": ["java ", "jvm", "maven", "gradle", "spring boot", "springboot"],
    "csharp": ["c#", "csharp", "dotnet", ".net", "asp.net"],
    "ruby": ["ruby ", "ruby on rails", "rails ", "gemfile"],
    "php": ["php ", "laravel", "composer "],
    "swift": ["swift ", "swiftui", "swiftlang"],
    "kotlin": ["kotlin", "kotlinlang", "jetbrains compose"],
    "react": ["react", "reactjs", "jsx", "next.js", "nextjs"],
    "vue": ["vue ", "vuejs", "nuxt", "vuex", "pinia"],
    "angular": ["angular", "ngmodule"],
    "svelte": ["svelte", "sveltekit"],
    "docker": ["docker", "dockerfile", "docker-compose", "containerd"],
    "kubernetes": ["kubernetes", "k8s", "kubectl", "helm chart"],
    "terraform": ["terraform", "hcl ", "terraform-provider"],
    "postgresql": ["postgresql", "postgres", "psql"],
    "mysql": ["mysql", "mariadb"],
    "mongodb": ["mongodb", "mongoose", "mongo atlas"],
    "redis": ["redis", "redis-cli", "redisson"],
    "sqlite": ["sqlite", "sqlalchemy"],
    "git": ["git ", "gitlab", "github actions", "gitflow"],
    "pytorch": ["pytorch", "torch ", "torchvision", "tensorboard"],
    "tensorflow": ["tensorflow", "keras ", "tf.dataset"],
    "elasticsearch": ["elasticsearch", "elastic search", "kibana", "logstash"],
    "kafka": ["kafka", "confluent", "kafka streams"],
    "rabbitmq": ["rabbitmq", "amqp"],
    "nginx": ["nginx", "openresty"],
    "graphql": ["graphql", "apollo graphql", "gql "],
    "grpc": ["grpc", "protobuf", "proto3", "protoc"],
    "nodejs": ["node.js", "nodejs", "nvm ", "npx "],
    "bun": ["bun.sh", "bun.js", "bun install"],
    "deno": ["deno ", "deno.land"],
    "vite": ["vite ", "vitejs", "vitest"],
    "webpack": ["webpack", "webpack5"],
    "tailwind": ["tailwind", "tailwindcss"],
    "aws": ["aws ", "amazon web services", "s3 bucket", "lambda function", "ec2 "],
    "azure": ["azure ", "microsoft azure", "azuredevops"],
    "gcp": ["gcp ", "google cloud", "gke ", "bigquery"],
    "cloudflare": ["cloudflare", "wrangler ", "cloudflare workers"],
    "vercel": ["vercel", "next.js deployment"],
    "fastapi": ["fastapi", "uvicorn", "pydantic"],
    "django": ["django", "django-rest", "django admin"],
    "flask": ["flask ", "werkzeug", "jinja2"],
    "spring": ["spring boot", "spring framework", "springboot", "spring-cloud"],
    "express": ["express.js", "expressjs", "express router"],
    "nestjs": ["nestjs", "nest.js", "@nestjs"],
    "linux": ["linux ", "ubuntu", "debian", "centos", "systemd", "bash "],
    "prometheus": ["prometheus", "grafana", "promql"],
}

# 实体 → 官方域名列表（S-tier 候选）
OFFICIAL_DOMAINS: dict[str, list[str]] = {
    "python": ["python.org", "docs.python.org", "peps.python.org"],
    "typescript": ["typescriptlang.org", "devblogs.microsoft.com/typescript"],
    "javascript": ["developer.mozilla.org", "tc39.es"],
    "rust": ["rust-lang.org", "doc.rust-lang.org"],
    "golang": ["go.dev", "pkg.go.dev"],
    "java": ["docs.oracle.com", "openjdk.org"],
    "csharp": ["dotnet.microsoft.com", "learn.microsoft.com/dotnet"],
    "ruby": ["ruby-lang.org", "docs.ruby-lang.org"],
    "php": ["php.net", "secure.php.net"],
    "swift": ["swift.org", "developer.apple.com/swift"],
    "kotlin": ["kotlinlang.org", "kotlinlang.org/docs"],
    "react": ["react.dev", "reactjs.org"],
    "vue": ["vuejs.org"],
    "angular": ["angular.io", "angular.dev"],
    "svelte": ["svelte.dev"],
    "docker": ["docker.com", "docs.docker.com"],
    "kubernetes": ["kubernetes.io"],
    "terraform": ["terraform.io", "developer.hashicorp.com"],
    "postgresql": ["postgresql.org", "www.postgresql.org"],
    "mysql": ["mysql.com", "dev.mysql.com"],
    "mongodb": ["mongodb.com"],
    "redis": ["redis.io"],
    "sqlite": ["sqlite.org"],
    "git": ["git-scm.com"],
    "pytorch": ["pytorch.org"],
    "tensorflow": ["tensorflow.org"],
    "elasticsearch": ["elastic.co", "www.elastic.co"],
    "kafka": ["kafka.apache.org"],
    "rabbitmq": ["rabbitmq.com"],
    "nginx": ["nginx.org", "nginx.com"],
    "graphql": ["graphql.org"],
    "grpc": ["grpc.io"],
    "nodejs": ["nodejs.org"],
    "bun": ["bun.sh"],
    "deno": ["deno.land"],
    "vite": ["vitejs.dev"],
    "webpack": ["webpack.js.org"],
    "tailwind": ["tailwindcss.com"],
    "aws": ["aws.amazon.com", "docs.aws.amazon.com"],
    "azure": ["azure.microsoft.com", "learn.microsoft.com/azure"],
    "gcp": ["cloud.google.com"],
    "cloudflare": ["developers.cloudflare.com"],
    "vercel": ["vercel.com"],
    "fastapi": ["fastapi.tiangolo.com"],
    "django": ["djangoproject.com", "docs.djangoproject.com"],
    "flask": ["flask.palletsprojects.com"],
    "spring": ["spring.io", "docs.spring.io"],
    "express": ["expressjs.com"],
    "nestjs": ["nestjs.com"],
    "linux": ["kernel.org", "www.kernel.org"],
    "prometheus": ["prometheus.io"],
}


# ================================================================
# 域名 → Tier 映射（用于标注搜索结果）
# ================================================================
# 检查顺序：精确匹配 → 父域匹配 → 默认 C
# 子域名自动继承父域的 tier（如 docs.python.org 继承 python.org 的 S）

_TIER_MAP: dict[str, DomainTier] = {
    # ---- S tier: 官方源 ----
    "python.org": DomainTier.S,
    "docs.python.org": DomainTier.S,
    "peps.python.org": DomainTier.S,
    "typescriptlang.org": DomainTier.S,
    "rust-lang.org": DomainTier.S,
    "doc.rust-lang.org": DomainTier.S,
    "go.dev": DomainTier.S,
    "pkg.go.dev": DomainTier.S,
    "docs.oracle.com": DomainTier.S,
    "openjdk.org": DomainTier.S,
    "dotnet.microsoft.com": DomainTier.S,
    "learn.microsoft.com": DomainTier.S,
    "ruby-lang.org": DomainTier.S,
    "php.net": DomainTier.S,
    "swift.org": DomainTier.S,
    "kotlinlang.org": DomainTier.S,
    "react.dev": DomainTier.S,
    "reactjs.org": DomainTier.S,
    "vuejs.org": DomainTier.S,
    "angular.io": DomainTier.S,
    "angular.dev": DomainTier.S,
    "svelte.dev": DomainTier.S,
    "docker.com": DomainTier.S,
    "docs.docker.com": DomainTier.S,
    "kubernetes.io": DomainTier.S,
    "terraform.io": DomainTier.S,
    "developer.hashicorp.com": DomainTier.S,
    "postgresql.org": DomainTier.S,
    "mysql.com": DomainTier.S,
    "mongodb.com": DomainTier.S,
    "redis.io": DomainTier.S,
    "sqlite.org": DomainTier.S,
    "git-scm.com": DomainTier.S,
    "pytorch.org": DomainTier.S,
    "tensorflow.org": DomainTier.S,
    "elastic.co": DomainTier.S,
    "kafka.apache.org": DomainTier.S,
    "rabbitmq.com": DomainTier.S,
    "nginx.org": DomainTier.S,
    "graphql.org": DomainTier.S,
    "grpc.io": DomainTier.S,
    "nodejs.org": DomainTier.S,
    "bun.sh": DomainTier.S,
    "deno.land": DomainTier.S,
    "vitejs.dev": DomainTier.S,
    "webpack.js.org": DomainTier.S,
    "tailwindcss.com": DomainTier.S,
    "aws.amazon.com": DomainTier.S,
    "docs.aws.amazon.com": DomainTier.S,
    "cloud.google.com": DomainTier.S,
    "azure.microsoft.com": DomainTier.S,
    "developers.cloudflare.com": DomainTier.S,
    "vercel.com": DomainTier.S,
    "fastapi.tiangolo.com": DomainTier.S,
    "djangoproject.com": DomainTier.S,
    "docs.djangoproject.com": DomainTier.S,
    "flask.palletsprojects.com": DomainTier.S,
    "spring.io": DomainTier.S,
    "docs.spring.io": DomainTier.S,
    "expressjs.com": DomainTier.S,
    "nestjs.com": DomainTier.S,
    "kernel.org": DomainTier.S,
    "prometheus.io": DomainTier.S,
    "www.rfc-editor.org": DomainTier.S,
    "ietf.org": DomainTier.S,

    # ---- A tier: 权威参考 ----
    "developer.mozilla.org": DomainTier.A,
    "en.wikipedia.org": DomainTier.A,
    "zh.wikipedia.org": DomainTier.A,
    "wikipedia.org": DomainTier.A,
    "w3.org": DomainTier.A,
    "www.w3.org": DomainTier.A,
    "ecma-international.org": DomainTier.A,
    "tc39.es": DomainTier.A,
    "whatwg.org": DomainTier.A,
    "chromium.org": DomainTier.A,
    "developer.chrome.com": DomainTier.A,
    "webkit.org": DomainTier.A,
    "developer.apple.com": DomainTier.A,  # 非 Swift 通用文档也是权威

    # ---- B tier: 优质社区 ----
    "github.com": DomainTier.B,
    "stackoverflow.com": DomainTier.B,
    "arxiv.org": DomainTier.B,
    "npmjs.com": DomainTier.B,
    "www.npmjs.com": DomainTier.B,
    "pypi.org": DomainTier.B,
    "crates.io": DomainTier.B,
    "rubygems.org": DomainTier.B,
    "packagist.org": DomainTier.B,
    "hub.docker.com": DomainTier.B,
    "raw.githubusercontent.com": DomainTier.B,
    "gist.github.com": DomainTier.B,
    "discuss.python.org": DomainTier.B,
    "users.rust-lang.org": DomainTier.B,
    "forum.swift.org": DomainTier.B,
    "dev.to": DomainTier.B,
    "hackernews.com": DomainTier.B,
    "news.ycombinator.com": DomainTier.B,
    "lobste.rs": DomainTier.B,
    "engineering.fb.com": DomainTier.B,
    "engineering.atspotify.com": DomainTier.B,
    "netflixtechblog.com": DomainTier.B,

    # ---- D tier: 低质量/注水 ----
    # 仅标注真正的内容农场 / 纯采集站
    # 注意：CSDN/博客园等内容质量参差不齐，不标 D（保持默认 C），
    # 仅在 SPAM_DOMAINS 中排除最差的子域
    "360doc.com": DomainTier.D,
    "360doc.cn": DomainTier.D,
    "xindear.com": DomainTier.D,
    "168seo.cn": DomainTier.D,
    "111cn.net": DomainTier.D,
    "php.cn": DomainTier.D,
    "jb51.net": DomainTier.D,  # 脚本之家，大量采集
    "yisu.com": DomainTier.D,  # 速云之家中大量 SEO 注水
    "zhangqiaokeyan.com": DomainTier.D,  # 掌桥科研，采集站
}


# ================================================================
# Spam 域名排除列表（Bing -site: 排除）
# ================================================================
# 仅排除几乎 100% 低质量的域名/子域
# 限制在 15 个以内，避免 Bing 查询 URL 过长
SPAM_DOMAINS: set[str] = {
    # 百度低质量子产品
    "tieba.baidu.com",       # 贴吧
    "zhidao.baidu.com",      # 知道
    "wenku.baidu.com",       # 文库
    "baijiahao.baidu.com",   # 百家号（大量营销号）
    # 采集站/内容农场
    "jb51.net",              # 脚本之家
    "360doc.com",
    "111cn.net",
    "yisu.com",
    # 其他
    "wenku.csdn.net",        # CSDN 文库（纯下载页，无内容）
    "download.csdn.net",     # CSDN 下载（需积分，无正文）
    "baike.baidu.com",       # 百度百科内容浅
    "docin.com",             # 豆丁网
    "book118.com",           # 道客巴巴
}


# ================================================================
# 核心函数
# ================================================================

# Tier 排序权重（用于结果重排，数值越小越靠前）
_TIER_ORDER: dict[DomainTier, int] = {
    DomainTier.S: 0,
    DomainTier.A: 1,
    DomainTier.B: 2,
    DomainTier.C: 3,
    DomainTier.D: 4,
}

# 确定性评分公式基础分
_BASE_SCORES: dict[DomainTier, float] = {
    DomainTier.S: 0.90,
    DomainTier.A: 0.75,
    DomainTier.B: 0.60,
    DomainTier.C: 0.35,
    DomainTier.D: 0.10,
}

# 验证标志增量（Phase 2 启用，Phase 1 全部为空集）
_VERIFICATION_BONUS: dict[str, float] = {
    # canonical URL resolve 到 S/A 注册表中的域名
    "canonical_verified": 0.05,
    # 页面版权声明与实体匹配
    "copyright_match": 0.03,
    # 内容深度 > 500 字符
    "content_depth": 0.02,
}


def get_domain_tier(hostname: str) -> DomainTier:
    """获取域名的 Tier 等级

    检查顺序：
    1. 精确匹配 _TIER_MAP
    2. 父域匹配（子域继承父域 tier，如 docs.python.org → python.org → S）
    3. 默认返回 C（普通第三方）

    注意：域名年龄不参与此判定（评审修正：新官方域名如 bun.sh 不应被年龄惩罚）
    """
    if not hostname:
        return DomainTier.C

    hostname = hostname.lower().strip()

    # 精确匹配
    if hostname in _TIER_MAP:
        return _TIER_MAP[hostname]

    # 父域匹配：逐级去除最左侧子域
    parts = hostname.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in _TIER_MAP:
            return _TIER_MAP[parent]

    return DomainTier.C


def compute_credibility_score(
    tier: DomainTier,
    verification_flags: list[str] | None = None,
) -> float:
    """计算可信度分数（确定性公式，可复现可调试）

    公式：base_score(tier) + sum(verification_bonus[flag] for flag in flags)
    结果 clamp 到 [0, 1]

    Phase 1: verification_flags 始终为空，score = base_score(tier)
    Phase 2: 启用 canonical/copyright/content_depth 验证后传入 flags

    评审修正：不手工赋值，公式确定且可追溯
    """
    score = _BASE_SCORES[tier]
    if verification_flags:
        for flag in verification_flags:
            score += _VERIFICATION_BONUS.get(flag, 0.0)
    return round(min(1.0, score), 2)


def match_entity(query: str) -> str | None:
    """子串匹配查询中的技术实体（零 LLM 开销）

    评审修正：Phase 1 不用 NER，用简单子串匹配。
    在 50+ 实体规模下，准确率与 NER 相当，成本为零。

    匹配规则：query 小写化后检查是否包含任一别名子串
    返回第一个匹配的 entity key，或 None
    """
    if not query:
        return None
    q_lower = query.lower()
    for entity, aliases in ENTITY_ALIASES.items():
        for alias in aliases:
            if alias in q_lower:
                return entity
    return None


def get_official_domains(entity: str) -> list[str]:
    """获取实体的官方域名列表（S-tier 候选）"""
    return OFFICIAL_DOMAINS.get(entity, [])


def tag_url(url: str) -> dict[str, str | float]:
    """标注单个 URL 的信源元数据

    返回：
    {
        "source_tier": "S" | "A" | "B" | "C" | "D",
        "credibility_score": 0.0-1.0,
        "is_official": bool,  # 是否为已注册官方域名
    }

    Phase 1: verification_flags 为空，score = base_score
    Phase 2: 增加 canonical/copyright/content_depth 验证
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return {
            "source_tier": DomainTier.D.value,
            "credibility_score": 0.10,
            "is_official": False,
        }

    hostname = (parsed.hostname or "").lower()
    tier = get_domain_tier(hostname)

    # is_official: hostname 在 OFFICIAL_DOMAINS 的某个值列表中
    all_official = {d for domains in OFFICIAL_DOMAINS.values() for d in domains}
    is_official = hostname in all_official

    return {
        "source_tier": tier.value,
        "credibility_score": compute_credibility_score(tier),
        "is_official": is_official,
    }


def build_bing_query(query: str, entity: str | None = None) -> str:
    """构造 Bing 查询字符串（含 spam 排除）

    评审修正：
    - 不用 site: 限制官方域名（会过度收窄结果）
    - 用 -site: 排除已知 spam 域名
    - 限制排除域名数量避免 URL 过长

    Args:
        query: 原始查询
        entity: match_entity() 返回的实体 key（Phase 1 未使用 site: boost，
                Phase 1.5 可选增加 OR site:official）
    Returns:
        Bing 查询字符串
    """
    # 限制排除域名数量（Bing URL 长度限制）
    exclusions = list(SPAM_DOMAINS)[:12]
    exclude_clause = " ".join(f"-site:{d}" for d in exclusions)
    return f"{query} {exclude_clause}".strip()


def rank_by_tier(urls: list[str]) -> list[str]:
    """按 Tier 重排 URL 列表（S 优先，同 tier 保持原始顺序）

    评审修正：Phase 1/2 的"独立性"仅指"不同域名"，非真正引用链追溯。
    代码注释明确标注此限制，避免后续误用。
    """
    tagged = [(url, _TIER_ORDER[get_domain_tier(urlparse(url).hostname or "")], i)
              for i, url in enumerate(urls)]
    # 稳定排序：先按 tier 权重，再按原始索引
    tagged.sort(key=lambda x: (x[1], x[2]))
    return [url for url, _, _ in tagged]
