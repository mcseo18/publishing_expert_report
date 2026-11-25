"""중앙 플랫폼 설정 및 경로 로더.

- 수집 원문·정제·근거 패킷·인덱스: E:\\SMC_Report_Platform_Data (워크스페이스 data/* 정션과 동일)
- 지식그래프 통합 저장소: C:\\SMC_GRAPHRAG (기존 graph_*.json / Neo4j + 신규 lightrag_store)
- 로컬 LLM / 임베딩: Ollama (127.0.0.1:11434, gemma4:26b / bge-m3)
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parent.parent


def load_env_file(env_path: Path | None = None) -> None:
    """워크스페이스 .env 파일을 환경변수로 로드한다 (기존 환경변수 우선)."""
    target = env_path or (WORKSPACE_ROOT / ".env")
    if not target.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(target, override=False)
        return
    except ImportError:
        pass
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class PlatformConfig:
    workspace_root: Path
    collected_data_root: Path
    smc_graphrag_root: Path
    lightrag_working_dir: Path
    lightrag_workspace: str
    lightrag_api_url: str
    ollama_host: str
    ollama_llm_model: str
    ollama_fast_model: str
    ollama_embed_model: str
    ollama_num_ctx: int
    active_project: str = "soil_organic_matter"

    # E:\ 수집 자료 하위 경로
    @property
    def raw_web_dir(self) -> Path:
        return self.collected_data_root / "raw" / "web"

    @property
    def raw_docs_dir(self) -> Path:
        return self.collected_data_root / "raw" / "docs"

    @property
    def raw_captures_dir(self) -> Path:
        return self.collected_data_root / "raw" / "captures"

    @property
    def parsed_dir(self) -> Path:
        return self.collected_data_root / "parsed"

    @property
    def evidence_dir(self) -> Path:
        return self.collected_data_root / "evidence"

    @property
    def index_dir(self) -> Path:
        return self.collected_data_root / "index"

    @property
    def e_projects_dir(self) -> Path:
        return self.collected_data_root / "projects"

    @property
    def exports_dir(self) -> Path:
        """활성 프로젝트의 E:\\ 산출물 미러 폴더 (E:\\SMC_Report_Platform_Data\\projects\\<slug>\\exports)."""
        return self.e_projects_dir / self.active_project / "exports"

    def project_e_exports_dir(self, project_slug: str) -> Path:
        return self.e_projects_dir / project_slug / "exports"

    def project_collected_dir(self, project_slug: str) -> Path:
        """프로젝트별 분리 수집 저장소 (E:\\SMC_Report_Platform_Data\\projects\\<slug>\\collected)."""
        return self.e_projects_dir / project_slug / "collected"

    def project_e_evidence_dir(self, project_slug: str) -> Path:
        """프로젝트별 전용 근거 패킷 폴더 (E:\\SMC_Report_Platform_Data\\projects\\<slug>\\evidence)."""
        return self.e_projects_dir / project_slug / "evidence"

    @property
    def logs_dir(self) -> Path:
        return self.collected_data_root / "logs"

    @property
    def sources_registry_path(self) -> Path:
        return self.index_dir / "sources.jsonl"

    @property
    def smc_catalog_db_path(self) -> Path:
        return self.index_dir / "smc_graphrag_catalog.sqlite"

    # C:\SMC_GRAPHRAG 하위 경로
    @property
    def smc_graphrag_output_dir(self) -> Path:
        return self.smc_graphrag_root / "output"

    @property
    def smc_graphrag_backup_dir(self) -> Path:
        return self.smc_graphrag_root / "output" / "backup"

    @property
    def smc_incremental_graph_path(self) -> Path:
        return self.smc_graphrag_root / "output" / "graph_platform_incremental.json"

    @property
    def smc_unified_rag_dir(self) -> Path:
        return self.smc_graphrag_root / "unified_rag"

    @property
    def smc_unified_rag_db_path(self) -> Path:
        return self.smc_unified_rag_dir / "unified_rag_corpus.sqlite"

    # 워크스페이스 하위 경로 (프로젝트별 격리 폴더 구조: projects/<project_slug>/)
    @property
    def schemas_dir(self) -> Path:
        return self.workspace_root / "schemas"

    @property
    def evidence_schema_path(self) -> Path:
        return self.schemas_dir / "evidence_packet.schema.json"

    @property
    def glossary_path(self) -> Path:
        return self.schemas_dir / "glossary.json"

    @property
    def reports_dir(self) -> Path:
        return self.workspace_root / "reports"

    @property
    def projects_dir(self) -> Path:
        """v2 신규 프로젝트 전용 루트 (기존 projects/ 폴더는 그대로 보존)."""
        return self.workspace_root / "projects_v2"

    @property
    def legacy_projects_dir(self) -> Path:
        """보존된 구버전 프로젝트 폴더 (읽기 전용 참고용)."""
        return self.workspace_root / "projects"

    @property
    def publishing_db_dir(self) -> Path:
        """프로젝트별 캡처·PDF·참고이미지·웹문서·지식그래프 통합 DB 루트 (publishing_DB/)."""
        return self.workspace_root / "publishing_DB"

    def project_publishing_db_dir(self, project_slug: str) -> Path:
        return self.publishing_db_dir / project_slug

    def project_dir(self, project_slug: str) -> Path:
        return self.projects_dir / project_slug

    @property
    def active_project_dir(self) -> Path:
        return self.projects_dir / self.active_project

    @property
    def chapters_dir(self) -> Path:
        return self.active_project_dir / "chapters"

    @property
    def blueprints_dir(self) -> Path:
        return self.active_project_dir / "blueprints"

    @property
    def assets_dir(self) -> Path:
        return self.active_project_dir / "assets"

    @property
    def workspace_exports_dir(self) -> Path:
        return self.active_project_dir / "exports"

    def ensure_directories(self) -> None:
        for path in (
            self.raw_web_dir,
            self.raw_docs_dir,
            self.raw_captures_dir,
            self.parsed_dir,
            self.evidence_dir,
            self.index_dir,
            self.e_projects_dir,
            self.exports_dir,
            self.logs_dir,
            self.lightrag_working_dir,
            self.smc_unified_rag_dir,
            self.reports_dir,
            self.projects_dir,
            self.publishing_db_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def get_config(active_project: str | None = None) -> PlatformConfig:
    load_env_file()
    collected = Path(os.environ.get("COLLECTED_DATA_ROOT", r"E:\SMC_Report_Platform_Data"))
    smc_root = Path(os.environ.get("SMC_GRAPHRAG_ROOT", r"C:\SMC_GRAPHRAG"))
    lightrag_dir = Path(
        os.environ.get("LIGHTRAG_WORKING_DIR", str(smc_root / "lightrag_store"))
    )
    proj = active_project or os.environ.get("ACTIVE_PROJECT", "soil_organic_matter")
    cfg = PlatformConfig(
        workspace_root=WORKSPACE_ROOT,
        collected_data_root=collected,
        smc_graphrag_root=smc_root,
        lightrag_working_dir=lightrag_dir,
        lightrag_workspace=os.environ.get("WORKSPACE", "smc_default"),
        lightrag_api_url=os.environ.get("LIGHTRAG_API_URL", "http://127.0.0.1:9621").rstrip("/"),
        ollama_host=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/"),
        ollama_llm_model=os.environ.get("OLLAMA_LLM_MODEL", "gemma4:26b"),
        ollama_fast_model=os.environ.get("OLLAMA_FAST_MODEL", "gemma4:latest"),
        ollama_embed_model=os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3"),
        ollama_num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "32768")),
        active_project=proj,
    )
    cfg.ensure_directories()
    return cfg


if __name__ == "__main__":
    import json

    c = get_config()
    print(
        json.dumps(
            {
                "workspace_root": str(c.workspace_root),
                "collected_data_root": str(c.collected_data_root),
                "smc_graphrag_root": str(c.smc_graphrag_root),
                "lightrag_working_dir": str(c.lightrag_working_dir),
                "lightrag_workspace": c.lightrag_workspace,
                "lightrag_api_url": c.lightrag_api_url,
                "ollama_host": c.ollama_host,
                "ollama_llm_model": c.ollama_llm_model,
                "ollama_embed_model": c.ollama_embed_model,
                "ollama_num_ctx": c.ollama_num_ctx,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
