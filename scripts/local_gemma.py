"""로컬 Ollama GGUF (gemma4:26b) 호출 및 정형 JSON 정제 래퍼.

핵심 안전 장치 (구축 가이드 3장·5장 반영):
1. Ollama 버전(>= 0.21.1) 확인 (think=false + format 버그 Issue #15260 방지)
2. GGUF 러너(gemma4:26b) 기본 사용, MLX JSON 버그 회피
3. 정규식 기반 JSON 정제기(후행 쉼표·코드 펜스·이스케이프 오류 보정) + 스키마 재시도
4. 멀티턴 이력에서 <|channel>thought 블록 자동 제거
5. 이미지 판독 시 이미지를 텍스트보다 먼저 배치
6. /api/ps 텔레메트리로 GPU/VRAM 점유율 모니터링
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests

from config import PlatformConfig, get_config

FACT_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_id": {"type": "string"},
        "key_concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "definition_ko": {"type": "string"},
                    "evidence_quote_short": {"type": "string"},
                    "page_or_section": {"type": "string"},
                },
                "required": ["term", "definition_ko", "page_or_section"],
            },
        },
        "verified_metrics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string"},
                    "value": {"type": "string"},
                    "as_of_date": {"type": "string"},
                    "caveat": {"type": "string"},
                },
                "required": ["metric", "value"],
            },
        },
    },
    "required": ["source_id", "key_concepts", "verified_metrics"],
}

TRIPLE_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["PERSON", "ORG", "PLACE", "CONCEPT", "EVENT", "PRODUCT", "LAW", "METRIC", "OTHER"],
                    },
                },
                "required": ["name", "type"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "relation": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["source", "relation", "target"],
            },
        },
    },
    "required": ["entities", "relations"],
}


def _parse_semver(version_str: str) -> tuple[int, int, int]:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", version_str)
    if not m:
        return (0, 0, 0)
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def strip_thought_blocks(text: str) -> str:
    """Gemma 4 / 추론 모델의 사고 블록을 제거해 본문만 남긴다."""
    cleaned = re.sub(r"<\|channel>thought.*?<channel\|>", "", text, flags=re.S)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.S)
    return cleaned.strip()


def sanitize_json_text(raw: str) -> str:
    """간헐적 JSON 문법 오류(코드펜스·후행쉼표·앞뒤 설명문)를 보정한다."""
    text = strip_thought_blocks(raw).strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.I)
    if fence:
        text = fence.group(1).strip()
    # 첫 '{' 또는 '[' 부터 마지막 매칭 괄호까지 추출
    start_candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if start_candidates:
        start = min(start_candidates)
        end = max(text.rfind("}"), text.rfind("]"))
        if end > start:
            text = text[start : end + 1]
    # 후행 쉼표 제거: , } 또는 , ]
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return text.strip()


class LocalGemmaClient:
    def __init__(self, cfg: PlatformConfig | None = None):
        self.cfg = cfg or get_config()
        self.base_url = self.cfg.ollama_host

    def check_health(self) -> dict[str, Any]:
        """Ollama 버전(>=0.21.1), 설치 모델(다이제스트), 현재 GPU 점유 상태를 반환한다."""
        ver_r = requests.get(f"{self.base_url}/api/version", timeout=10)
        ver_r.raise_for_status()
        version = ver_r.json().get("version", "0.0.0")

        tags_r = requests.get(f"{self.base_url}/api/tags", timeout=10)
        tags_r.raise_for_status()
        models = [
            {
                "name": m.get("name"),
                "digest": (m.get("digest") or "")[:16],
                "size_gb": round((m.get("size") or 0) / (1024**3), 2),
            }
            for m in tags_r.json().get("models", [])
        ]

        ps_r = requests.get(f"{self.base_url}/api/ps", timeout=10)
        ps_r.raise_for_status()
        running = []
        for m in ps_r.json().get("models", []):
            size = m.get("size") or 0
            size_vram = m.get("size_vram") or 0
            gpu_pct = round((size_vram / size) * 100, 1) if size else 0.0
            running.append(
                {
                    "name": m.get("name"),
                    "size_gb": round(size / (1024**3), 2),
                    "vram_gb": round(size_vram / (1024**3), 2),
                    "gpu_percent": gpu_pct,
                    "context_length": m.get("context_length"),
                }
            )

        return {
            "ollama_host": self.base_url,
            "version": version,
            "version_ok_for_gemma4_format": _parse_semver(version) >= (0, 21, 1),
            "configured_llm_model": self.cfg.ollama_llm_model,
            "configured_embed_model": self.cfg.ollama_embed_model,
            "installed_models": models,
            "running_models": running,
        }

    def chat_structured(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.7,
        num_ctx: int | None = None,
        num_predict: int = 4096,
        max_retries: int = 3,
        timeout: int = 300,
    ) -> dict[str, Any]:
        """GGUF + think=false + format(JSON Schema) 구조화 호출 및 자동 정제·재시도."""
        target_model = model or self.cfg.ollama_llm_model
        ctx = num_ctx or self.cfg.ollama_num_ctx
        work_messages = [
            {**m, "content": strip_thought_blocks(str(m.get("content", "")))}
            for m in messages
        ]

        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            payload = {
                "model": target_model,
                "think": False,
                "stream": False,
                "format": schema,
                "options": {
                    "temperature": temperature,
                    "top_p": 0.95,
                    "top_k": 64,
                    "num_ctx": ctx,
                    "num_predict": num_predict,
                },
                "messages": work_messages,
            }
            resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
            resp.raise_for_status()
            raw_content = resp.json().get("message", {}).get("content", "")
            cleaned = sanitize_json_text(raw_content)
            try:
                parsed = json.loads(cleaned)
                try:
                    import jsonschema

                    jsonschema.validate(instance=parsed, schema=schema)
                except ImportError:
                    pass
                return parsed
            except Exception as exc:
                last_err = exc
                work_messages.append({"role": "assistant", "content": raw_content[:1500]})
                work_messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"이전 응답이 JSON 스키마 검증에 실패했습니다({exc}). "
                            "설명 없이 지정된 JSON 스키마에 맞는 순수 JSON 객체만 다시 출력하십시오."
                        ),
                    }
                )
        raise RuntimeError(f"Gemma structured JSON extraction failed after {max_retries} attempts: {last_err}")

    def extract_facts(
        self,
        source_id: str,
        markdown_text: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        """프롬프트 4A: 정제된 마크다운에서 핵심 개념과 검증 수치를 정형 JSON으로 추출한다."""
        clipped = markdown_text[:24000]
        messages = [
            {
                "role": "system",
                "content": (
                    "당신은 전문 분야 지식 추출기입니다. 제공된 원문에 명시된 사실과 수치만 추출해 "
                    "지정된 JSON 스키마로 출력하십시오. 원문에 없는 수치나 정의는 절대 추론·창작하지 말고 "
                    "빈 배열 또는 빈 문자열로 남기십시오. 원문 문장을 길게 복사하지 말고 한국어 전문 용어로 "
                    "간결하게 재정의하십시오."
                ),
            },
            {
                "role": "user",
                "content": f"source_id: {source_id}\n\n[원문 시작]\n{clipped}\n[원문 끝]",
            },
        ]
        result = self.chat_structured(messages=messages, schema=FACT_EXTRACTION_SCHEMA, model=model)
        result["source_id"] = source_id
        return result

    def extract_triples(self, chunk_text: str, model: str | None = None) -> dict[str, Any]:
        """지식그래프 증분 병합용 엔티티·관계 트리플 추출 (C:\\SMC_GRAPHRAG 호환)."""
        messages = [
            {
                "role": "system",
                "content": (
                    "다음 텍스트에서 핵심 개체(entities)와 개체 간 관계(relations)를 추출하십시오. "
                    "개체 이름은 텍스트에 나온 정확한 전문 용어를 사용하고, 관계는 짧은 동사구로 쓰십시오. "
                    "relations의 source/target은 반드시 entities에 존재하는 이름이어야 합니다."
                ),
            },
            {"role": "user", "content": chunk_text[:6000]},
        ]
        return self.chat_structured(
            messages=messages,
            schema=TRIPLE_EXTRACTION_SCHEMA,
            model=model,
            num_predict=2048,
        )

    def draft_text(
        self,
        system_prompt: str,
        user_prompt: str,
        history: list[dict[str, str]] | None = None,
        images: list[Path] | None = None,
        think: bool = True,
        model: str | None = None,
        temperature: float = 1.0,
        num_ctx: int | None = None,
        num_predict: int = 4096,
        timeout: int = 600,
    ) -> str:
        """프롬프트 4B: Thinking 모드 초안 집필 및 이미지 선배치 멀티모달 판독."""
        target_model = model or self.cfg.ollama_llm_model
        ctx = num_ctx or self.cfg.ollama_num_ctx

        sys_text = system_prompt
        if think and not sys_text.startswith("<|think|>"):
            sys_text = "<|think|>" + sys_text

        messages: list[dict[str, Any]] = [{"role": "system", "content": sys_text}]
        for turn in history or []:
            messages.append(
                {
                    "role": turn["role"],
                    "content": strip_thought_blocks(turn["content"]),
                }
            )

        user_msg: dict[str, Any] = {"role": "user", "content": user_prompt}
        if images:
            encoded = [base64.b64encode(p.read_bytes()).decode("ascii") for p in images]
            user_msg["images"] = encoded
        messages.append(user_msg)

        payload = {
            "model": target_model,
            "think": think,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 64,
                "num_ctx": ctx,
                "num_predict": num_predict,
            },
            "messages": messages,
        }
        resp = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return strip_thought_blocks(content)

    def embed(self, texts: list[str], model: str | None = None, timeout: int = 120) -> list[list[float]]:
        """로컬 Ollama /api/embed (bge-m3) 배치 임베딩."""
        target_model = model or self.cfg.ollama_embed_model
        resp = requests.post(
            f"{self.base_url}/api/embed",
            json={"model": target_model, "input": texts},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"]


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 Ollama Gemma 4 26B GGUF 래퍼")
    parser.add_argument("--health", action="store_true", help="Ollama 상태·버전·GPU 점유 확인")
    parser.add_argument("--smoke", action="store_true", help="gemma4:26b + bge-m3 구조화 출력 스모크 테스트")
    parser.add_argument("--model", default=None, help="모델 오버라이드 (예: gemma4:26b, gemma4:latest)")
    parser.add_argument("--extract-file", type=Path, default=None, help="정제 마크다운에서 사실·수치 JSON 추출")
    parser.add_argument("--source-id", default="SRC-01", help="추출 시 부여할 source_id")
    args = parser.parse_args()

    client = LocalGemmaClient()

    if args.health:
        print(json.dumps(client.check_health(), ensure_ascii=False, indent=2))
        return 0

    if args.smoke:
        health = client.check_health()
        sample_schema = {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "message_ko": {"type": "string"},
            },
            "required": ["status", "message_ko"],
        }
        res = client.chat_structured(
            messages=[
                {
                    "role": "user",
                    "content": '한국어로 한 줄 응답을 JSON으로 출력하세요: status="READY", message_ko="로컬 엔진 준비 완료"',
                }
            ],
            schema=sample_schema,
            model=args.model,
            num_ctx=4096,
            num_predict=128,
        )
        emb = client.embed(["로컬 지식그래프 임베딩 스모크 테스트"])
        post_health = client.check_health()
        print(
            json.dumps(
                {
                    "ollama_version": health["version"],
                    "version_ok": health["version_ok_for_gemma4_format"],
                    "structured_output": res,
                    "embed_dim": len(emb[0]) if emb else 0,
                    "running_models": post_health["running_models"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.extract_file:
        text = args.extract_file.read_text(encoding="utf-8")
        result = client.extract_facts(args.source_id, text, model=args.model)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
