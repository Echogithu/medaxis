"""LLM 错误到患者可见稳定契约的映射。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import ValidationError


class LLMConfigurationError(ValueError):
    """Provider 配置缺失或无效。"""


class LLMInvalidResponseError(ValueError):
    """模型多种输出模式均未提供有效结构化报告。"""


class MedicalEvidenceUnavailableError(ValueError):
    """没有实际可核验资料，不能生成或保存诊断报告。"""


def patient_llm_error(exc: BaseException) -> dict[str, str]:
    """返回不含上游原文、密钥或内部配置的稳定 SSE 错误字段。"""
    if isinstance(exc, MedicalEvidenceUnavailableError):
        code, message = "MEDICAL_EVIDENCE_UNAVAILABLE", "未获得可核验的医学参考资料，本次未生成诊断报告。请重试检索；如有不适，请联系医护人员。"
    elif isinstance(exc, (APITimeoutError, TimeoutError, asyncio.TimeoutError)):
        code, message = "LLM_TIMEOUT", "AI 服务响应超时，请保留当前内容后重试。"
    elif isinstance(exc, RateLimitError) or (
        isinstance(exc, APIStatusError) and exc.status_code == 429
    ):
        code, message = "LLM_RATE_LIMITED", "AI 服务当前繁忙，请稍后重试。"
    elif isinstance(exc, APIStatusError) and exc.status_code in (401, 403):
        code, message = "LLM_CONFIGURATION_ERROR", "AI 服务暂不可用，请稍后重试或联系支持。"
    elif isinstance(exc, (APIConnectionError,)) or (
        isinstance(exc, APIStatusError) and exc.status_code >= 500
    ):
        code, message = "LLM_PROVIDER_UNAVAILABLE", "AI 服务暂时不可用，请稍后重试。"
    elif isinstance(exc, APIStatusError):
        code, message = "LLM_PROVIDER_REJECTED", "AI 服务暂时无法处理本次请求，请稍后重试。"
    elif isinstance(exc, (LLMInvalidResponseError, json.JSONDecodeError, ValidationError, IndexError, KeyError)):
        code, message = "LLM_INVALID_RESPONSE", "AI 暂未能生成有效结果，请保留当前内容后重试。"
    elif isinstance(exc, LLMConfigurationError):
        code, message = "LLM_CONFIGURATION_ERROR", "AI 服务暂不可用，请稍后重试或联系支持。"
    elif isinstance(exc, asyncio.CancelledError):
        code, message = "LLM_REQUEST_INTERRUPTED", "本次请求已中断，您的输入仍保留，请重试。"
    elif isinstance(exc, ValueError):
        code, message = "LLM_INTERNAL_ERROR", "AI 服务暂时无法完成请求，请稍后重试。"
    else:
        code, message = "LLM_INTERNAL_ERROR", "AI 服务暂时无法完成请求，请稍后重试。"

    return {"code": code, "error": message}


def safe_llm_failure_fields(exc: BaseException) -> dict[str, Any]:
    """提供仅含分类信息的日志字段，避免记录上游响应正文或凭证。"""
    payload = patient_llm_error(exc)
    return {"code": payload["code"], "exception_type": type(exc).__name__}


def supports_structured_output_fallback(exc: BaseException) -> bool:
    """只对明确不支持 JSON Schema 的 400 响应执行普通 JSON fallback。"""
    if not isinstance(exc, APIStatusError) or exc.status_code != 400:
        return False

    body_text = str(exc.body or "").lower()
    unsupported = (
        "unsupported", "not supported", "not_support", "unrecognized",
        "unknown", "unavailable",
    )
    return ("response_format" in body_text or "json_schema" in body_text) and any(
        marker in body_text for marker in unsupported
    )
