# Prompt 模板已迁移至 conclave_core.prompts 进行编译保护
# 此文件为 re-export 入口，保持现有 import 路径不变
# 开源版中 conclave_core/prompts.py 被编译为 .so/.pyd，源码不暴露
from conclave_core.prompts import (  # noqa: F401
    ARBITRATE,
    ARCHITECT_INTRA,
    CODE_FIX_PROMPT,
    CODE_REVIEW_PROMPT,
    CROSS_TEAM,
    ENGINEER_INTRA,
    EVIDENCE_CHECK,
    MODERATOR_CLARIFY,
    PRODUCE,
    PRODUCE_BUSINESS_REPORT,
    PRODUCE_CODE_ANALYSIS,
    PRODUCE_COMPREHENSIVE,
    PRODUCE_DATA_SCIENCE,
    PRODUCE_DEPLOYABLE_SERVICE,
    PRODUCE_DESIGN_DOC,
    PRODUCE_RESEARCH_REPORT,
    PRODUCE_TEMPLATES,
    PRODUCE_TESTED_SYSTEM,
    get_produce_template,
    render,
)
