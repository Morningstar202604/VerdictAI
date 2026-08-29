from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.data import generate_case
from app.data.store import list_cases, load_case, validate_id
from app.agents.roles import role_list
from app.agents import agent_config
from app.graph.runner import run_debate
from app.runtime import current as current_settings, update as update_settings
from app.ws.manager import manager

log = logging.getLogger("verdictai")

app = FastAPI(title="VerdictAI", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8787", "http://127.0.0.1:8787"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态资源：生成的图表/图片
data_dir = os.path.abspath(settings.data_dir)
app.mount("/static/data", StaticFiles(directory=data_dir), name="data")

# 沙箱产物（图表等）对外提供
sandbox_out_dir = os.path.abspath(settings.sandbox_out_dir)
os.makedirs(sandbox_out_dir, exist_ok=True)
app.mount("/sandbox", StaticFiles(directory=sandbox_out_dir), name="sandbox")

INDEX_HTML = os.path.join(os.path.dirname(__file__), "static", "index.html")
FLOW_HTML = os.path.join(os.path.dirname(__file__), "static", "flow.html")


@app.get("/")
def index():
    return FileResponse(INDEX_HTML, media_type="text/html; charset=utf-8")


@app.get("/flow.html")
@app.get("/static/flow.html")
def flow():
    if not os.path.exists(FLOW_HTML):
        return JSONResponse({"error": "流程图不存在"}, status_code=404)
    return FileResponse(FLOW_HTML, media_type="text/html; charset=utf-8")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "mock": settings.llm_provider == "mock",
    }


@app.get("/api/roles")
def roles():
    return {"roles": role_list()}


@app.get("/api/cases")
def cases():
    return {"cases": list_cases()}


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    c = load_case(case_id)
    if c is None:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    return c


@app.get("/api/debates")
def list_debates():
    """列出已落盘的辩论记录，供复盘。"""
    d = os.path.join(settings.data_dir, "debates")
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d), reverse=True):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                rec = json.load(fh)
        except Exception:
            continue
        out.append(
            {
                "session_id": rec.get("session_id"),
                "case_title": rec.get("case_title"),
                "started_at": rec.get("started_at"),
                "model": rec.get("model"),
                "rounds": rec.get("rounds"),
                "truth": (rec.get("final_verdict") or {}).get("truth_hypothesis", ""),
            }
        )
    return out


@app.get("/api/debates/{session_id}")
def get_debate(session_id: str):
    if not validate_id(session_id):
        return JSONResponse({"error": "无效的会话 ID"}, status_code=400)
    p = os.path.join(settings.data_dir, "debates", f"{session_id}.json")
    if not os.path.exists(p):
        return JSONResponse({"error": "未找到该辩论记录"}, status_code=404)
    with open(p, encoding="utf-8") as fh:
        return JSONResponse(json.load(fh))


@app.post("/api/cases/generate")
async def regenerate():
    """生成一个示例案件并加入案例库（用唯一 ID，不再硬编码 case_001）。"""
    from app.intake.processor import preprocess

    path = generate_case.generate()
    case = load_case("case_001")
    # 给示例案件一个新 ID，避免覆盖
    new_id = "case_" + uuid.uuid4().hex[:8]
    case["id"] = new_id
    case["title"] = case.get("title", "示例案件") + " (副本)"
    try:
        case["brief"] = await preprocess(case)
    except Exception:
        pass
    new_path = os.path.join(os.path.dirname(path), f"{new_id}.json")
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(case, f, ensure_ascii=False, indent=2)
    return {"path": new_path, "case": case}


@app.get("/api/settings")
def get_settings():
    return current_settings()


@app.post("/api/settings")
def post_settings(payload: dict):
    return update_settings(payload)


@app.get("/api/agent-config")
def get_agent_config():
    return {"agents": agent_config.effective_list()}


@app.post("/api/agent-config")
def post_agent_config(payload: dict):
    data = payload.get("agents", payload) if isinstance(payload, dict) else {}
    return {"agents": agent_config.save(data)}


@app.post("/api/sandbox/install")
def sandbox_install(payload: dict):
    from app.agents.tools import install_package

    pkg = (payload or {}).get("package", "")
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    result = install_package.invoke({"package": pkg})
    return {"result": result}


@app.post("/api/sandbox/run")
def sandbox_run(payload: dict):
    from app.agents.tools import run_code

    code = (payload or {}).get("code", "")
    if not settings.code_sandbox_enabled:
        return JSONResponse(status_code=400, content={"error": "代码沙箱未启用。"})
    result = run_code.invoke({"code": code})
    return {"result": result}


def _extract_pdf_text(
    b64_content: str, max_pages: int = 50, max_chars: int = 60000
) -> str:
    """从 base64 编码的 PDF 中提取文本。

    对超大文档做截断保护，避免无限撑爆模型上下文：最多取前 max_pages 页、
    拼接后最多保留 max_chars 字符，并在超限时附加提示。
    """
    import base64

    try:
        import fitz  # PyMuPDF
    except ImportError:
        return ""
    try:
        raw = base64.b64decode(b64_content)
        doc = fitz.open(stream=raw, filetype="pdf")
        pages = []
        truncated_pages = False
        for i, page in enumerate(doc):
            if i >= max_pages:
                truncated_pages = True
                break
            pages.append(page.get_text())
        doc.close()
        text = "\n\n".join(pages).strip()
        truncated_chars = False
        if len(text) > max_chars:
            text = text[:max_chars].rstrip()
            truncated_chars = True
        if truncated_pages or truncated_chars:
            text += (
                "\n\n[注意：原始文档较大，已自动截断（"
                + ("页数" if truncated_pages else "")
                + ("字符" if truncated_chars else "")
                + "上限）以保证分析可行，关键事实请以来源原件为准。]"
            )
        return text
    except Exception:
        return ""


def _text_to_case(text: str, filename: str = "") -> dict:
    """从纯文本构建案件 JSON 结构（PDF 上传时使用）。"""
    title = filename.replace(".pdf", "").replace(".PDF", "") or "上传案件"
    return {
        "title": title,
        "summary": text[:2000],
        "persons": [],
        "evidence": [],
        "timeline": [],
        "statutes": [],
        "images": [],
    }


@app.post("/api/cases/upload")
async def upload_case(payload: dict):
    from app.intake.processor import preprocess

    if not isinstance(payload, dict):
        return JSONResponse({"error": "案件须为 JSON 对象"}, status_code=400)
    data = dict(payload)

    # PDF 文件：从 base64 提取文本并构建案件结构
    if data.get("file_type") == "pdf" and data.get("file_content"):
        pdf_text = _extract_pdf_text(data["file_content"])
        if not pdf_text:
            return JSONResponse(
                {"error": "PDF 文本提取失败，请确认文件未加密"}, status_code=400
            )
        case_from_pdf = _text_to_case(pdf_text, data.get("file_name", ""))
        for k, v in case_from_pdf.items():
            if k not in data or not data[k]:
                data[k] = v
        data["pdf_text"] = pdf_text

    cid = data.get("id") or ("case_" + uuid.uuid4().hex[:8])
    data["id"] = cid
    cases_dir = os.path.join(data_dir, "cases")
    os.makedirs(cases_dir, exist_ok=True)
    try:
        data["brief"] = await preprocess(data)
    except Exception:
        data["brief"] = None
    with open(os.path.join(cases_dir, cid + ".json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"case": data}


@app.delete("/api/cases/{case_id}")
async def delete_case(case_id: str):
    """删除案件（案例库管理）。"""
    if not validate_id(case_id):
        return JSONResponse({"error": "无效的案件 ID"}, status_code=400)
    cases_dir = os.path.join(data_dir, "cases")
    path = os.path.join(cases_dir, f"{case_id}.json")
    if not os.path.exists(path):
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    os.remove(path)
    return {"deleted": case_id}


@app.websocket("/ws/{session_id}")
async def ws_endpoint(websocket: WebSocket, session_id: str):
    await manager.connect(session_id, websocket)
    debate_task = None

    async def receiver():
        nonlocal debate_task
        while True:
            try:
                msg = await websocket.receive_json()
            except Exception:
                break
            if msg.get("type") == "start":
                case_id = msg.get("case_id", "case_001")
                case = load_case(case_id)
                agents = msg.get("agents") or None
                overrides = {
                    k: msg[k]
                    for k in (
                        "intent",
                        "reasoning_intensity",
                        "global_guidance",
                        "judge_mode",
                    )
                    if msg.get(k)
                }
                debate_task = asyncio.create_task(
                    run_debate(case, session_id, agents, overrides or None)
                )
            elif msg.get("type") == "human":
                await manager.push_human(session_id, msg.get("text", ""))

    task = asyncio.create_task(receiver())
    try:
        await task
    finally:
        manager.disconnect(session_id)
        # 客户端断开后取消仍在后台跑的辩论，避免白白消耗 API 额度
        if debate_task is not None and not debate_task.done():
            debate_task.cancel()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
