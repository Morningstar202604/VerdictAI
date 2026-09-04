#!/usr/bin/env python3
"""真实端到端测试：上传 PDF（非 demo 案例），触发 AI 解析。"""
import base64
import json
import sys
import urllib.request

BASE = "http://localhost:8787"

def call(method, path, body=None, raw=None):
    url = BASE + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:2000]
    except Exception as e:
        return -1, str(e)

if __name__ == "__main__":
    # 1) 读取 PDF 并 base64
    pdf_path = sys.argv[1]
    with open(pdf_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()

    # 2) 上传
    body = {
        "file_type": "pdf",
        "file_content": content,
        "file_name": "case_wang_ouhe_reports.pdf",
        "title": "王某强故意伤害致人死亡案——侦查终结报告",
    }
    status, resp = call("POST", "/api/cases/upload", body)
    print("UPLOAD STATUS:", status)
    if status != 200:
        print("UPLOAD ERROR:", resp)
        sys.exit(1)

    case = resp.get("case", resp)
    case_id = case.get("id") or case.get("case_id")
    print("CASE ID:", case_id)
    print("TITLE:", case.get("title"))
    print("intake_done:", (case.get("brief") or {}).get("intake_done"))
    persons = case.get("persons", [])
    evidence = case.get("evidence", [])
    timeline = case.get("timeline", [])
    statutes = case.get("statutes", [])
    print("persons:", len(persons))
    for p in persons[:8]:
        print("  -", p.get("name"), "|", p.get("role"), "|", (p.get("desc") or "")[:40])
    print("evidence:", len(evidence))
    for e in evidence[:8]:
        print("  -", e.get("id"), "|", (e.get("text") or e.get("desc") or "")[:50])
    print("timeline:", len(timeline))
    for t in timeline[:10]:
        print("  -", t.get("time"), "|", (t.get("event") or "")[:50])
    print("statutes:", len(statutes))
    for s in statutes[:6]:
        print("  -", (s.get("title") or s.get("name") or s.get("law") or "")[:40], "|", (s.get("content") or s.get("text") or "")[:40])
    print("charts:", list((case.get("charts") or {}).keys()))
    print("ai_extracted:", case.get("ai_extracted"))
    print("CASE_ID_FOR_NEXT=" + str(case_id))