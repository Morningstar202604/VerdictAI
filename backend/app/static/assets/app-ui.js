      document.addEventListener("click", (e)=>{
        const chip = e.target && e.target.closest && e.target.closest("#qaChips .chip-mini");
        if(chip){ $("qaInput").value = chip.dataset.q || chip.textContent; askVerdict(); return; }
        const btn = e.target && e.target.closest && e.target.closest(".copy-btn");
        if(!btn) return;
        const m = messages[+btn.dataset.copy];
        if(!m) return;
        const t = m.text || "";
        const done=()=>toast(`已复制「${m.name}」的发言`);
        if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(t).then(done).catch(()=>fallbackCopy(t,done)); }
        else fallbackCopy(t,done);
      });
      function addContra(c){
        contraList.push(c); const wrap=$("contra"); if(wrap.querySelector(".muted")) wrap.innerHTML="";
        const parties=(c.parties||[]).map(k=>(roleMap[k]||{}).name||k).join(" ↔ ");
        const el=document.createElement("details"); el.className="contra contra-fold";
        // 当事人常显，长段论证默认折叠，展开才阅读
        el.innerHTML=`<summary class="cp"><span>⚠ ${parties?escape(parties):"矛盾点"}</span><span class="fold-hint">展开论证</span></summary><div class="ci md">${renderMarkdown(c.issue)}</div>`;
        wrap.appendChild(el);
        const hint=$("contraHint"); if(hint) hint.textContent = contraList.length + " 项 · ";
        const cf=wrap.closest(".card-fold"); if(cf && !cf.open && contraList.length===1) cf.open=true;
      }
      function addRecording(role, name, note){
        recNotes.push({role, name, note});
        const wrap=$("recording"); if(!wrap) return;
        if(wrap.querySelector(".muted")) wrap.innerHTML="";
        const color=(roleMap[role]||{}).color||"#1f3a5f";
        const evs=(note.evidence_ids||[]).map(e=>`<span class="ev-tag">${escape(e)}</span>`).join("");
        const ds=(note.doubts||[]).map(d=>`${escape(d)}`).join("；");
        const imp=(note.implicates||[]).map(k=>`${escape((roleMap[k]||{}).name||k)}`).join("、");
        const el=document.createElement("details"); el.className="rec-note rec-fold";
        // 专家与核心主张常显（阅读主线），证据/指向/存疑默认折叠
        el.innerHTML=`<summary class="rn-head"><span class="rn-dot" style="background:${color}"></span><span class="rn-name">${escape(name||role)}</span><span class="rn-caret"></span></summary>`+
          `<div class="rn-sec">核心主张</div><div class="rn-claim md">${renderMarkdown(note.claim||"（无摘要）")}</div>`+
          (evs?`<details class="rc-sub"><summary>🔗 依据证据 · ${(note.evidence_ids||[]).length} 项</summary><div class="rn-evs">${evs}</div></details>`:"")+
          (imp?`<details class="rc-sub"><summary>👤 指向人员</summary><div class="rn-imp">${imp}</div></details>`:"")+
          (ds?`<details class="rc-sub"><summary>⚠ 存疑事项</summary><div class="rn-doubt">${ds}</div></details>`:"");
        wrap.appendChild(el);
      }
      function renderVerdict(v){ if(!v) return;
        // 恢复已持久化的「后续流程」勾选（复盘/刷新后不丢）
        if(Array.isArray(v.ns_done)){ nsDone=new Set(v.ns_done.map(Number).filter(i=>i>=0)); }
        const mdList=(arr)=>(arr&&arr.length)?`<ul>${arr.map(x=>`<li class="md">${renderMarkdown(x)}</li>`).join("")}</ul>`:"";
        // 证据链强度条：百分比常显，主要问题默认收起
        const es=v.evidence_strength||{}; const pct=Math.round((es.score||0)*100);
        const bar=(es.score!=null)?`<details class="vfold vfold-strength st-${pct>=75?"ok":pct>=45?"warn":"bad"}"><summary><span class="sf-title">证据链强度 <b class="st-pct">${pct}%</b></span><span class="st-bar mini"><i style="width:${pct}%"></i></span></summary>${(es.issues||[]).length?`<div class="rn-sec">主要问题</div><ul class="st-issues">${es.issues.map(x=>`<li class="md">${renderMarkdown(x)}</li>`).join("")}</ul>`:""}</details>`:"";
        const secFold=(icon,t,n,arr)=>(arr&&arr.length)?`<details class="vfold"><summary>${icon} ${t} · ${n} 项 <span class="fold-hint">点击展开</span></summary>${mdList(arr)}</details>`:"";
        const fold=(icon,t,body)=>body?`<details class="vfold"><summary>${icon} ${t} <span class="fold-hint">点击展开</span></summary>${body}</details>`:"";
        // 判决式裁决书：事实认定与裁决主文常显，质证/说理/法条/量刑等过程内容折叠
        const facts=(v.findings_of_fact||v.truth_hypothesis||"")?`<div class="vsec">经审理查明</div><div class="vcore md">${renderMarkdown(v.findings_of_fact||v.truth_hypothesis)}</div>`:"";
        const ef=(v.evidence_findings||[]);
        const efTable=ef.length?`<table class="vf-table"><thead><tr><th>编号</th><th>证据</th><th>三性意见</th><th>认定</th></tr></thead><tbody>${ef.map(f=>`<tr class="${f.admitted?"adm":"rej"}"><td>${escape(f.id||"—")}</td><td class="md">${renderMarkdown(f.name||"")}${f.reason?`<div class="vf-reason md">${renderMarkdown(f.reason)}</div>`:""}</td><td class="md">${renderMarkdown(f.opinion||"")}</td><td><span class="vf-tag ${f.admitted?"ok":"no"}">${f.admitted?"采信":"排除"}</span></td></tr>`).join("")}</tbody></table>`:"";
        const lc=(v.law_citations||[]);
        // B 阶段引用核验徽标：selfcheck.verification.citations 按 title+article 对齐
        const ver=(window._selfcheck&&window._selfcheck.verification)||null;
        const verOf=(c)=>{ if(!ver||!(ver.citations||[]).length) return null;
          const norm=s=>String(s||"").replace(/[《》\s]/g,"");
          return ver.citations.find(r=>norm(r.title).includes(norm(c.title))||norm(c.title).includes(norm(r.title)))||null; };
        const verTag=(c)=>{ const r=verOf(c); if(!r) return "";
          const map={verified:["ok","✓ 已核验"],not_in_library:["no","✗ 疑似虚构"],unknown_law:["warn","? 待人工核验"]};
          const m=map[r.status]; return m?`<span class="vf-verify ${m[0]}" title="${escape(r.note||"")}">${m[1]}</span>`:""; };
        const lcList=lc.length?`<ul class="vf-cites">${lc.map(c=>`<li>《${escape(String(c.title||"").replace(/[《》]/g,""))}》${escape(c.article||"")} ${verTag(c)}<span class="muted"> · ${renderMarkdown(c.purpose||"")}</span></li>`).join("")}</ul>`+(ver?`<div class="ver-sum ${ver.flagged?"bad":"ok"}">${ver.flagged?`⚠ ${ver.verified} 条已核验，${ver.flagged} 条待复核（详见下方主要问题）`:`✓ ${ver.verified} 条引用全部通过内置法条库核验`}</div>`:""):"";
        const rulingMain=(v.ruling||"")?`<div class="vsec">裁决主文</div><div class="vruling md">${renderMarkdown(v.ruling)}</div>`:"";
        const sent=(v.sentencing||"")?`<div class="vsec">量刑与责任承担</div><div class="vsent md">${renderMarkdown(v.sentencing)}${(ver&&ver.sentencing_check)?`<div class="ver-sum ${ver.sentencing_check.ok?"ok":"bad"}">${ver.sentencing_check.ok?"✓":"⚠"} ${escape(ver.sentencing_check.note||"")}（${escape(ver.sentencing_check.range_text||"")}）</div>`:""}</div>`:"";
        const extras=[
          fold("🧾","证据认定 · "+ef.length+" 项",efTable),
          fold("⚖️","裁判说理",v.reasoning?`<div class="md">${renderMarkdown(v.reasoning)}</div>`:""),
          fold("📜","引用法条 · "+lc.length+" 条",lcList),
          rulingMain,sent,
          secFold("❓","存疑点",v.doubts.length,v.doubts),
          secFold("🔗","证据链",v.evidence_chain.length,v.evidence_chain),
          (v.recommendation)?`<details class="vfold"><summary>📋 处置建议 <span class="fold-hint">点击展开</span></summary><div class="md">${renderMarkdown(v.recommendation)}</div></details>`:"",
          bar,
        ].join("");
        $("verdictBox").innerHTML=`<div class="verdict"><div class="vhead"><span class="seal">裁</span><span>审判长裁决书</span></div>${facts}${extras}${v.disclaimer?`<div class="disc">${v.disclaimer}</div>`:""}</div>`;
        // 裁决后处理工具条 + 质询面板
        $("verdictTools").classList.remove("hidden");
        $("qaBox").classList.remove("hidden");
        // 推荐追问：从存疑点自动生成
        const qc=$("qaChips"); if(qc){ qc.innerHTML=((v.doubts||[]).slice(0,3)).map(function(d){ return '<span class="chip-mini" data-q="为什么：'+escapeHtml(String(d).slice(0,26))+'…？">'+escapeHtml("为什么："+String(d).slice(0,18)+"…")+'</span>'; }).join(""); }
        renderNextSteps(v.next_steps||[]);
      }
      function appendClosureCard(container){
        /* 结案卡片：辩论终结后在笔录末尾给出明确的收束时刻与结案动作。
           由 renderDebate 在「已终结且有裁决」时挂载，重绘自动保留。 */
        const wrap=container||$("debate"); if(!wrap) return;
        if(wrap.querySelector(".closure-card")) return;
        const rounds=round||new Set(messages.map(m=>m.roundLabel).filter(Boolean)).size;
        const calls=(lastUsage&&lastUsage.calls)?lastUsage.calls:0;
        const div=document.createElement("div");
        div.className="closure-card";
        div.innerHTML='<div class="cl-icon">🔨</div>' +
          '<div class="cl-title">本 案 审 理 终 结</div>' +
          '<div class="cl-sub">' + escapeHtml((caseDetail&&caseDetail.title)||"案件") +
          " · " + rounds + " 轮审理" + (calls ? " · 推理 " + calls + " 次" : "") + '</div>' +
          '<div class="cl-actions">' +
          '<button class="primary" onclick="downloadReport()" aria-label="下载完整结案报告">⬇ 完整结案报告</button>' +
          '<button class="ghost" onclick="printReport()" aria-label="打印结案报告或导出 PDF">🖨 打印 / PDF</button>' +
          '<button class="ghost" onclick="goHome()" aria-label="结束本案并开始新庭审">🏛 新庭审</button>' +
          '</div>' +
          '<div class="cl-note">裁决与全程笔录已自动归档 · 「设置 → 案例库 → 复盘记录」可随时调阅</div>';
        wrap.appendChild(div);
        wrap.scrollTop = wrap.scrollHeight;
      }
      function renderNextSteps(steps){
        const box=$("nextSteps");
        if(!steps || !steps.length){ box.classList.add("hidden"); return; }
        box.classList.remove("hidden");
        const items = steps.map((s,i)=>`<label class="ns-item${nsDone.has(i)?" done":""}"><input type="checkbox" data-i="${i}" ${nsDone.has(i)?"checked":""} onchange="toggleNs(this)"><span><span class="no">${i+1}.</span>${escapeHtml(s)}</span></label>`).join("");
        const pct = steps.length ? Math.round(nsDone.size/steps.length*100) : 0;
        // 清单默认收起，进度常显；勾选或点开时再展开明细
        box.innerHTML=`<details class="ns-fold"><summary><span>后续流程清单</span><span class="ns-prog" id="nsProg">${nsDone.size}/${steps.length} 已完成 · ${pct}%</span><span class="fold-hint">点击展开</span></summary><div class="ns-bar"><div style="width:${pct}%"></div></div>${items}</details>`;
        box.dataset.total = steps.length;
      }
      let _nsTimer=null;
      function persistNextSteps(){
        if(!session || currentRole!=="admin"){ return; }
        clearTimeout(_nsTimer);
        _nsTimer=setTimeout(async()=>{
          try{
            const r=await fetch(`/api/debates/${session}/next-steps`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({done:[...nsDone]})});
            if(!r.ok){ toast("后续流程勾选保存失败（需管理员）"); }
          }catch(e){ /* 网络断时不阻塞交互，下次勾选再试 */ }
        }, 600);
      }
      function toggleNs(cb){
        const i = +cb.dataset.i;
        if(cb.checked) nsDone.add(i); else nsDone.delete(i);
        const box=$("nextSteps");
        cb.closest(".ns-item").classList.toggle("done", cb.checked);
        // 折叠头同步进度；首次勾选时自动展开明细便于继续勾选
        const total=box.dataset.total||1; const pct=Math.round(nsDone.size/total*100);
        const p=$("nsProg"); if(p) p.textContent = `${nsDone.size}/${total} 已完成 · ${pct}%`;
        const bar=$("nextSteps").querySelector(".ns-bar > div");
        if(bar) bar.style.width = pct + "%";
        const fold=$("nextSteps").querySelector(".ns-fold");
        if(fold && cb.checked && !fold.open && nsDone.size===1){ fold.open=true; }
        persistNextSteps();
      }
      function speakVerdict(){
        if(!("speechSynthesis" in window)){ toast("当前浏览器不支持语音朗读"); return; }
        if(window.__speaking){ speechSynthesis.cancel(); window.__speaking=false; $("btnSpeak").textContent="🔊 朗读"; return; }
        const t = (lastVerdict||{}).ruling || (lastVerdict||{}).findings_of_fact || (lastVerdict||{}).truth_hypothesis || "裁决尚未生成";
        const u = new SpeechSynthesisUtterance(t);
        u.lang = "zh-CN"; u.rate = 1;
        u.onend = ()=>{ window.__speaking=false; const b=$("btnSpeak"); if(b) b.textContent="🔊 朗读"; };
        window.__speaking = true;
        $("btnSpeak").textContent = "⏹ 停止";
        speechSynthesis.speak(u);
      }
      function verdictPlainText(){
        const v = lastVerdict||{};
        const list=(a)=>(a&&a.length)?a.map((x,i)=>`${i+1}. ${x}`).join("\n"):"（无）";
        let t="";
        if(v.findings_of_fact) t+=`【经审理查明】\n${v.findings_of_fact}\n\n`;
        if((v.evidence_findings||[]).length) t+=`【证据认定】\n${v.evidence_findings.map(f=>`- [${f.id||""}] ${f.name||""}：${f.opinion||""}（${f.admitted?"采信":"排除"}${f.reason?"，"+f.reason:""}）`).join("\n")}\n\n`;
        if(v.reasoning) t+=`【裁判说理】\n${v.reasoning}\n\n`;
        if((v.law_citations||[]).length) t+=`【引用法条】\n${v.law_citations.map(c=>`- ${c.title||""}${c.article||""}${c.purpose?"（"+c.purpose+"）":""}`).join("\n")}\n\n`;
        if(v.ruling) t+=`【裁决主文】\n${v.ruling}\n\n`;
        else if(v.truth_hypothesis) t+=`【真相推定】\n${v.truth_hypothesis}\n\n`;
        if(v.sentencing) t+=`【量刑与责任承担】\n${v.sentencing}\n\n`;
        if((v.evidence_chain||[]).length) t+=`【证据链】\n${list(v.evidence_chain)}\n\n`;
        t+=`【存疑点】\n${list(v.doubts)}\n\n【处置建议】\n${v.recommendation||""}\n\n【后续流程】\n${list(v.next_steps||[])}\n\n${v.disclaimer||""}`;
        return t;
      }
      function copyVerdict(){
        const t = verdictPlainText();
        const done=()=>toast("裁决全文已复制到剪贴板");
        if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(t).then(done).catch(()=>fallbackCopy(t,done)); }
        else fallbackCopy(t,done);
      }
      function fallbackCopy(t,done){ const ta=document.createElement("textarea"); ta.value=t; document.body.appendChild(ta); ta.select(); try{ document.execCommand("copy"); done(); }catch(e){ toast("复制失败，请手动选择文本"); } ta.remove(); }
      function reportMarkdown(){
        const b = serverBrief || (caseDetail && caseDetail.brief) || {};
        const c = caseDetail || {};
        let md = `# 审判报告 · ${c.title||""}\n\n> **模拟参考文书 · 供合议庭审阅**：本报告由 AI 审查角色辅助生成，不具有法律效力，最终认定以合议庭评议为准。\n\n`
        md += `## 一、案件概要\n\n${c.summary||""}\n\n`;
        if((c.persons||[]).length) md += `## 二、涉案人员\n\n${c.persons.map(p=>`- **${p.name}**（${p.role||""}）：${p.desc||""}`).join("\n")}\n\n`;
        if((c.evidence||[]).length) md += `## 三、证据材料\n\n${c.evidence.map(e=>`- [${e.id}] ${e.type}：${e.desc}（可靠性${Math.round((e.reliability||0)*100)}%，保管链${e.chain_intact?"完整":"瑕疵"}）`).join("\n")}\n\n`;
        md += `## 四、合议庭审理笔录\n\n`;
        messages.forEach(m=>{ md += `### ${m.name}${m.roundLabel?`（第${m.roundLabel}轮）`:""}\n\n${m.text||"（无文本输出）"}\n\n`; });
        if(recNotes.length) md += `## 五、合议记录（摘要）\n\n${recNotes.map(r=>`- **${r.name}**：${r.note.claim||""}${(r.note.evidence_ids||[]).length?` ［${r.note.evidence_ids.join("、")}］`:""}`).join("\n")}\n\n`;
        if(contraList.length) md += `## 六、矛盾与纠错清单\n\n${contraList.map(x=>`- ⚠ ${x.issue||""}`).join("\n")}\n\n`;
        const v = lastVerdict||{};
        md += `## 七、审判长裁决\n\n**经审理查明**：${v.findings_of_fact||v.truth_hypothesis||""}\n\n`;
        if((v.evidence_findings||[]).length) md += `**证据认定**\n\n${v.evidence_findings.map(f=>`- [${f.id||""}] ${f.name||""}：${f.opinion||""}（${f.admitted?"采信":"排除"}${f.reason?"，"+f.reason:""}）`).join("\n")}\n\n`;
        if(v.reasoning) md += `**裁判说理**：${v.reasoning}\n\n`;
        if((v.law_citations||[]).length) md += `**引用法条**\n\n${v.law_citations.map(c=>`- ${c.title||""}${c.article||""}${c.purpose?"（"+c.purpose+"）":""}`).join("\n")}\n\n`;
        const _ver=(window._selfcheck&&window._selfcheck.verification)||null;
        if(_ver&&(_ver.citations||[]).length){
          const _mark={verified:"✓",not_in_library:"✗",unknown_law:"?"};
          md += `**引用核验**（内置法条库确定性比对，供人工复核）\n\n${_ver.citations.map(r=>`- ${_mark[r.status]||"·"} ${r.title||""}${r.article||""}：${r.note||""}`).join("\n")}\n`;
          if(_ver.sentencing_check&&_ver.sentencing_check.note) md += `- 量刑区间校验：${_ver.sentencing_check.ok?"通过":"不通过"}——${_ver.sentencing_check.note}\n`;
          md += "\n";
        }
        if(v.ruling) md += `**裁决主文**：${v.ruling}\n\n`;
        if(v.sentencing) md += `**量刑与责任承担**：${v.sentencing}\n\n`;
        if((v.evidence_chain||[]).length) md += `**证据链**\n\n${v.evidence_chain.map((x,i)=>`${i+1}. ${x}`).join("\n")}\n\n`;
        if((v.doubts||[]).length) md += `**存疑点**\n\n${v.doubts.map(x=>`- ${x}`).join("\n")}\n\n`;
        if(v.recommendation) md += `**处置建议**：${v.recommendation}\n\n`;
        if((v.next_steps||[]).length) md += `**后续流程**\n\n${v.next_steps.map((x,i)=>`- [${nsDone.has(i)?"x":" "}] ${x}`).join("\n")}\n\n`;
        if(qaHistory.length) md += `## 八、裁决质询记录\n\n${qaHistory.map(q=>`**问：** ${q.q}\n\n**审判长：** ${q.a}\n`).join("\n")}\n`;
        if(v.disclaimer) md += `---\n\n${v.disclaimer}\n`;
        return md;
      }
      async function auditEvidence(){
        if(!selectedCase){ toast("请先选择案件"); return; }
        const box=document.getElementById("evAudit"); if(!box) return;
        box.innerHTML='<div class="muted" style="font-size:11px">核验中…</div>';
        try{
          const d=await (await fetch(`/api/cases/${selectedCase}/evidence-audit`)).json();
          if(d.error){ box.innerHTML=`<div class="muted" style="font-size:11px">${escape(d.error)}</div>`; return; }
          const items=(d.issues||[]).map(i=>`<div style="margin:2px 0;font-size:11.5px">· ${escape(i.msg)}</div>`).join("");
          const s=d.stats||{};
          box.innerHTML=`<div style="border:1px solid ${d.ok?'var(--ok)':'var(--bad)'};border-radius:8px;padding:7px 9px;margin:4px 0;font-size:11.5px">`
            +`<b style="color:${d.ok?'var(--ok)':'var(--bad)'}">${d.ok?'✓ 未发现硬伤':'⚠ 发现 '+d.issues.length+' 处问题'}</b>`
            +`<span class="muted">　证据 ${s.count} 件 · 保管链瑕疵 ${s.chain_flawed} · 平均可靠性 ${s.avg_reliability} · 时间线 ${s.timeline_events} 条</span>`
            +(items?`<div style="margin-top:4px">${items}</div>`:"")+`</div>`;
        }catch(e){ box.innerHTML='<div class="muted" style="font-size:11px">核验失败：'+escape(e.message)+'</div>'; }
      }
      function downloadMarkdown(){
        const blob = new Blob([reportMarkdown()], {type:"text/markdown;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href=url; a.download = safeFname(`审判报告_${caseTitle(caseDetail)||"case"}`) + ".md"; a.click();
        setTimeout(()=>URL.revokeObjectURL(url), 2000);
        toast("Markdown 报告已导出");
      }
      function verdictDocHtml(){
        /* 正式裁决书：仅裁决要素，判决书式排版（区别于含全文笔录的审判报告） */
        const b = serverBrief || (caseDetail && caseDetail.brief) || {};
        const c = caseDetail || {}; const v = lastVerdict || {};
        const li = (t, arr) => (arr && arr.length) ? `<h2>${t}</h2><ul>${arr.map(x=>`<li>${renderMarkdown(x)}</li>`).join("")}</ul>` : "";
        const sec = (t, html) => html ? `<h2>${t}</h2><div class="sec">${html}</div>` : "";
        let h = `<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>审理裁决书 - ${escape(c.title||"")}</title>`;
        h += `<style>body{font-family:"Noto Serif SC","Songti SC","SimSun",serif;max-width:800px;margin:32px auto;padding:0 22px;color:#1a1a1a;line-height:2} h1{text-align:center;font-size:22px;letter-spacing:4px;margin-bottom:4px} .sub{text-align:center;color:#666;font-size:12px;margin-bottom:18px} .mark{text-align:center;color:#8a6d3b;font-size:12px;margin:10px 0 4px;letter-spacing:1px} h2{font-size:15px;margin:20px 0 6px} .meta{border-top:1px solid #999;border-bottom:1px solid #999;padding:8px 0;font-size:13px;margin:12px 0} .sec{margin:8px 0} .main{font-size:15px;font-weight:700} ul{margin:4px 0;padding-left:22px} li{margin:3px 0} .sign{margin-top:36px;text-align:right;color:#333;font-size:13px} .disc{margin-top:24px;color:#888;font-size:11px;border-top:1px dashed #bbb;padding-top:8px} @media print{body{margin:0 auto}}</style></head><body>`;
        h += `<h1>审 理 裁 决 书</h1><div class="mark">— 模拟参考文书 · 供合议庭审阅 —</div><div class="sub">VerdictAI 多智能体合议系统 · 辅助研究文书</div>`;
        h += `<div class="meta">案号：${escape(c.id||"")}　｜　案件：${escape(c.title||"")}<br>调查意图：${escape(b.intent||"")}　｜　审理轮次：${round||"—"} 轮　｜　合议庭：八位庭审角色 + 纠错官 + 审判长</div>`;
        h += `<h2>一、案件事实</h2><div class="sec">${renderMarkdown(c.summary||"（无）")}</div>`;
        if(c.persons&&c.persons.length) h += `<h2>二、涉案当事人</h2><div class="sec">${c.persons.map(p=>`${escape(p.name||"")}（${escape(p.role||"")}）`).join("　")}</div>`;
        const ef=(v.evidence_findings||[]);
        if(ef.length) h += `<h2>三、证据认定（质证结论）</h2><div class="sec"><table style="width:100%;border-collapse:collapse;font-size:13px"><tr><th style="border:1px solid #999;padding:4px">编号</th><th style="border:1px solid #999;padding:4px">证据</th><th style="border:1px solid #999;padding:4px">三性意见</th><th style="border:1px solid #999;padding:4px">认定</th></tr>${ef.map(f=>`<tr><td style="border:1px solid #999;padding:4px;text-align:center">${escape(f.id||"—")}</td><td style="border:1px solid #999;padding:4px">${renderMarkdown(f.name||"")}${f.reason?`<br><span style="color:#666">${renderMarkdown(f.reason)}</span>`:""}</td><td style="border:1px solid #999;padding:4px">${renderMarkdown(f.opinion||"")}</td><td style="border:1px solid #999;padding:4px;text-align:center;color:${f.admitted?"#166534":"#991b1b"}">${f.admitted?"采信":"排除"}</td></tr>`).join("")}</table></div>`;
        h += li("四、经审理采信的证据链", v.evidence_chain||[]);
        if(v.doubts&&v.doubts.length) h += `<h2>五、存疑事项（不予认定或需查证）</h2><div class="sec"><ul>${v.doubts.map(x=>`<li>${renderMarkdown(x)}</li>`).join("")}</ul></div>`;
        h += sec("六、裁判说理", v.reasoning?renderMarkdown(v.reasoning):"");
        if(v.law_citations&&v.law_citations.length) h += `<h2>七、引用法条</h2><ul>${v.law_citations.map(c=>`<li>${renderMarkdown((c.title||"")+(c.article||""))}${c.purpose?`（${renderMarkdown(c.purpose)}）`:""}</li>`).join("")}</ul>`;
        const _ver=(window._selfcheck&&window._selfcheck.verification)||null;
        if(_ver&&(_ver.citations||[]).length){
          const _mark={verified:"✓",not_in_library:"✗",unknown_law:"?"};
          h += `<h2>引用核验（供人工复核）</h2><ul style="font-size:12px;color:#555">${_ver.citations.map(r=>`<li>${_mark[r.status]||"·"} ${escape(String(r.title||""))} ${escape(String(r.article||""))}：${escape(r.note||"")}</li>`).join("")}${(_ver.sentencing_check&&_ver.sentencing_check.note)?`<li>量刑区间校验：${_ver.sentencing_check.ok?"通过":"不通过"}——${escape(_ver.sentencing_check.note)}</li>`:""}</ul>`;
        }
        h += `<h2>八、裁决主文</h2><div class="sec main">${renderMarkdown(v.ruling||v.truth_hypothesis||"（无）")}</div>`;
        h += sec("九、量刑与责任承担", v.sentencing?renderMarkdown(v.sentencing):"");
        if(v.recommendation) h += `<h2>十、处理建议</h2><div class="sec">${renderMarkdown(v.recommendation)}</div>`;
        if(v.next_steps&&v.next_steps.length) h += `<h2>十一、后续事项</h2><ul>${v.next_steps.map(x=>`<li>${renderMarkdown(x)}</li>`).join("")}</ul>`;
        h += `<div class="sign">合议庭：VerdictAI 多智能体系统<br>${new Date().toLocaleDateString("zh-CN")}</div>`;
        if(v.disclaimer) h += `<div class="disc">${escape(v.disclaimer)}</div>`;
        h += `</body></html>`;
        return h;
      }
      function downloadVerdictDoc(){
        if(!lastVerdict){ toast("裁决尚未生成"); return; }
        const blob = new Blob([verdictDocHtml()], {type:"text/html;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href=url; a.download = safeFname(`审理裁决书（模拟参考）_${caseTitle(caseDetail)||"case"}`) + ".html"; a.click();
        setTimeout(()=>URL.revokeObjectURL(url), 2000);
        toast("裁决书已导出（浏览器打开可打印为 PDF）");
      }
      function printReport(){
        const brief = serverBrief || (caseDetail && caseDetail.brief) || {};
        const c = caseDetail || {}; const v = lastVerdict || {};
        let h = downloadReportHtml();
        h = h.replace("</body>", `<script>window.onload=function(){setTimeout(function(){window.print();},300);}<\/script></body>`);
        const w = window.open("", "_blank");
        if(!w){ toast("浏览器拦截了弹出窗口，请允许弹窗后重试"); return; }
        w.document.write(h); w.document.close();
      }
      async function askVerdict(){
        const inp=$("qaInput"); const q=(inp.value||"").trim(); if(!q) return;
        if(!lastVerdict){ toast("裁决尚未生成"); return; }
        inp.value=""; qaHistory.push({q, a:"…"});
        renderQa();
        try {
          const r = await fetch("/api/verdict-qa",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({question:q, verdict:lastVerdict, case_id:selectedCase})});
          const d = await r.json();
          qaHistory[qaHistory.length-1].a = d.answer || ("（答复失败："+(d.error||("HTTP "+r.status))+"）");
        } catch(e){ qaHistory[qaHistory.length-1].a = "（网络错误："+e.message+"）"; }
        renderQa();
      }
      function renderQa(){
        const box=$("qaList"); if(!box) return;
        box.innerHTML = qaHistory.map(x=>`<div class="qa-item"><div class="qa-q">问：${escapeHtml(x.q)}</div><div class="qa-a md">${renderMarkdown(x.a)}</div></div>`).join("");
      }
      function fillIv(t){ $("ivInput").value = t; $("ivInput").focus(); }
      function renderHitl(draft, final){
        const draftHtml = draft ? `<div class="hitl-draft md">${renderMarkdown(JSON.stringify(draft,null,2))}</div>` : "";
        const title = final ? "🧑‍⚖ 人类审判长落槌" : "🧑‍⚖ 人类法官复核";
        $("hitl").innerHTML=`<div class="hitl-box"><div class="ht">${title}</div>${draftHtml}<textarea id="huText" rows="4" placeholder="确认采纳请点左侧；或在此写下你的最终裁决（JSON 或自然语言）"></textarea><div style="display:flex;gap:8px;margin-top:9px"><button class="ghost" style="flex:1" onclick="sendHuman('confirm')">采纳 AI 草案</button><button class="primary" style="flex:1" onclick="sendHuman()">落槌提交</button></div></div>`;
      }
      function sendHuman(force){ const t = force==="confirm" ? "confirm" : ($("huText").value.trim()); if(!t||!ws) return; ws.send(JSON.stringify({type:"human",text:t,subtype:"final"})); $("hitl").innerHTML=""; }
      function sendIntervene(){ const t=$("ivInput").value.trim(); if(!t||!ws) return; ws.send(JSON.stringify({type:"human",text:t,subtype:"intervene"})); $("ivInput").value=""; toast("已向合议庭插话，下一轮生效"); }
      function downloadReportHtml(){
        const brief = serverBrief || (caseDetail && caseDetail.brief) || {};
        const c = caseDetail || {};
        const v = lastVerdict || {};
        let h = `<!doctype html><html lang="zh"><head><meta charset="utf-8"><title>审判报告 - ${escape(c.title||"")}</title>`;
        h += `<style>body{font-family:-apple-system,'Microsoft YaHei',sans-serif;max-width:880px;margin:24px auto;padding:0 18px;color:#0f172a;line-height:1.75} h1{border-bottom:3px solid #7f1d1d;padding-bottom:8px} h2{margin-top:28px;color:#7f1d1d;border-left:4px solid #7f1d1d;padding-left:10px} .meta{color:#64748b;font-size:13px} .rec{border:1px solid #e2e8f0;border-radius:10px;padding:12px 14px;margin:10px 0} .rec .n{font-weight:700} .sec{background:#f8fafc;border-radius:8px;padding:10px 14px;margin:6px 0} .seal{display:inline-block;border:2px solid #7f1d1d;color:#7f1d1d;border-radius:50%;width:30px;height:30px;line-height:26px;text-align:center;font-weight:700;font-size:13px} pre{white-space:pre-wrap;background:#fff7ed;padding:8px;border-radius:8px} .disc{color:#64748b;font-size:12px;margin-top:10px} ul{margin:4px 0;padding-left:20px} li{margin:2px 0} .qa-a{border-left:3px solid #b45309;padding-left:10px;margin:6px 0} @media print{ body{margin:0 auto} h2{page-break-after:avoid} .rec{page-break-inside:avoid} }</style></head><body>`;
        h += `<h1>审判报告</h1><div style="text-align:center;color:#8a6d3b;font-size:12px;letter-spacing:1px;margin:6px 0 14px">— 模拟参考文书 · 供合议庭审阅 —</div><div class="meta">案号：${escape(c.id||"")} ｜ 标题：${escape(c.title||"")}<br>调查意图：${escape(brief.intent||"")} ｜ 思考强度：${escape(brief.reasoning_intensity||"")}</div>`;
        h += `<h2>一、案件概要</h2><div class="sec">${renderMarkdown(c.summary||"")}</div>`;
        if(c.persons&&c.persons.length){ h+="<h2>二、涉案人员</h2><div class='sec'>"+c.persons.map(p=>`<div><b>${escape(p.name)}</b>（${escape(p.role||"")}）：${escape(p.desc||"")}</div>`).join("")+"</div>"; }
        if(c.evidence&&c.evidence.length){ h+="<h2>三、证据材料</h2><div class='sec'>"+c.evidence.map(e=>`<div><b>[${escape(e.id||"")}]${escape(e.type||"")}</b>：${escape(e.desc||"")}（可靠性${e.reliability}，保管链${e.chain_intact?"完整":"瑕疵"}）</div>`).join("")+"</div>"; }
        h += `<h2>四、合议庭审理笔录</h2>`;
        messages.forEach(m=>{ if(m.role==="human"){ h+=`<div class="rec" style="border-color:#facc15"><div class="n">${escape(m.name)}</div><div>${renderMarkdown(m.text)}</div></div>`; return; } const a=roleMap[m.role]||{}; h+=`<div class="rec"><div class="n" style="color:${m.color}">${escape(m.name)}</div><div>${renderMarkdown(m.text)||"<i>（无文本输出）</i>"}</div></div>`; });
        h += `<h2>五、合议记录（实时摘要）</h2><div class="sec">${recNotes.length?recNotes.map(r=>`<div><b style="color:#1f3a5f">${escape(r.name)}</b>：${renderMarkdown(r.note.claim||"")}${r.note.evidence_ids&&r.note.evidence_ids.length?` ［证据：${r.note.evidence_ids.join("、")}］`:""}${r.note.doubts&&r.note.doubts.length?` <span style="color:#b45309">⚠ ${r.note.doubts.join("；")}</span>`:""}</div>`).join(""):"<div>无</div>"}</div>`;
        h += `<h2>六、矛盾与纠错清单</h2><div class="sec">${contraList.length?contraList.map(c=>{const parties=(c.parties||[]).map(k=>(roleMap[k]||{}).name||k).join(" ↔ "); return `<div>⚠ ${parties?parties+"：":""}${renderMarkdown(c.issue||"")}</div>`;}).join(""):"<div>无</div>"}</div>`;
        h += `<h2>七、审判长裁决</h2><div class="rec" style="border-color:#7f1d1d"><div class="n"><span class="seal">裁</span> 审判长裁决书</div>`;
        h += `<div class="sec"><b>经审理查明：</b>${renderMarkdown(v.findings_of_fact||v.truth_hypothesis||"")}</div>`;
        if(v.evidence_findings&&v.evidence_findings.length) h += `<div class="sec"><b>证据认定：</b><ul>${v.evidence_findings.map(f=>`<li>[${escape(f.id||"")}] ${escape(f.name||"")}：${renderMarkdown(f.opinion||"")} <b style="color:${f.admitted?"#166534":"#991b1b"}">${f.admitted?"采信":"排除"}</b>${f.reason?`（${renderMarkdown(f.reason)}）`:""}</li>`).join("")}</ul></div>`;
        if(v.reasoning) h += `<div class="sec"><b>裁判说理：</b>${renderMarkdown(v.reasoning)}</div>`;
        if(v.law_citations&&v.law_citations.length) h += `<div class="sec"><b>引用法条：</b><ul>${v.law_citations.map(c=>`<li>${escape(c.title||"")}${escape(c.article||"")}${c.purpose?`（${escape(c.purpose)}）`:""}</li>`).join("")}</ul></div>`;
        const _ver=(window._selfcheck&&window._selfcheck.verification)||null;
        if(_ver&&(_ver.citations||[]).length){
          const _mark={verified:"✓",not_in_library:"✗",unknown_law:"?"};
          h += `<div class="sec"><b>引用核验（供人工复核）：</b><ul style="font-size:12px;color:#555">${_ver.citations.map(r=>`<li>${_mark[r.status]||"·"} ${escape(String(r.title||""))} ${escape(String(r.article||""))}：${escape(r.note||"")}</li>`).join("")}${(_ver.sentencing_check&&_ver.sentencing_check.note)?`<li>量刑区间校验：${_ver.sentencing_check.ok?"通过":"不通过"}——${escape(_ver.sentencing_check.note)}</li>`:""}</ul></div>`;
        }
        if(v.ruling) h += `<div class="sec"><b>裁决主文：</b>${renderMarkdown(v.ruling)}</div>`;
        if(v.sentencing) h += `<div class="sec"><b>量刑与责任承担：</b>${renderMarkdown(v.sentencing)}</div>`;
        if(v.evidence_chain&&v.evidence_chain.length) h += `<div class="sec"><b>证据链：</b><ul>${v.evidence_chain.map(x=>`<li>${renderMarkdown(x)}</li>`).join("")}</ul></div>`;
        if(v.doubts&&v.doubts.length) h += `<div class="sec"><b>存疑点：</b><ul>${v.doubts.map(x=>`<li>${renderMarkdown(x)}</li>`).join("")}</ul></div>`;
        if(v.recommendation) h += `<div class="sec"><b>处置建议：</b>${renderMarkdown(v.recommendation)}</div>`;
        if(v.next_steps&&v.next_steps.length) h += `<div class="sec"><b>后续流程（可执行清单）：</b><ul>${v.next_steps.map((x,i)=>`<li>${nsDone.has(i)?"☑":"☐"} ${renderMarkdown(x)}</li>`).join("")}</ul></div>`;
        if(qaHistory&&qaHistory.length) h += `<h2>八、裁决质询记录</h2>${qaHistory.map(q=>`<div class="sec"><b>问：</b>${escape(q.q)}<div class="qa-a">${renderMarkdown(q.a)}</div></div>`).join("")}`;
        if(v.disclaimer) h += `<div class="disc">${escape(v.disclaimer)}</div>`;
        h += `</div><div class="disc">本报告由多智能体系统自动生成，仅供研究与演示，不构成法律意见。</div></body></html>`;
        return h;
      }
      function downloadReport(){
        const blob = new Blob([downloadReportHtml()], {type:"text/html;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a"); a.href=url; a.download = safeFname(`审判报告_${caseTitle(c)||"case"}`) + ".html"; a.click();
        setTimeout(()=>URL.revokeObjectURL(url), 2000);
      }
      function safeFname(name){
        return String(name||"export").replace(/[\\/:*?"<>|]/g, "").trim().slice(0, 80) || "export";
      }
      function caseTitle(c){ return ((c && c.title) || "").trim(); }
      function escape(s){ return String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c])); }

      /* 设置 */
      function openSettings(){ $("setMsg").textContent=""; switchTab("engine");
        $("s_provider").value=settingsCache.llm_provider||"openai_compatible"; syncSettingsFields();
        $("s_rounds").value=settingsCache.max_rounds??3; $("s_temp").value=settingsCache.temperature??0.3; $("s_judge").value=settingsCache.judge_mode||"ai"; $("s_hitl").value=settingsCache.hitl_timeout??300; $("s_intake").value=settingsCache.intake_model||"";
        $("s_sandbox").checked=!!settingsCache.code_sandbox_enabled; $("s_py").value=settingsCache.code_sandbox_python||"python3";
        $("s_sbbackend").value=settingsCache.code_sandbox_backend||"auto"; $("s_sbimage").value=settingsCache.code_sandbox_docker_image||"python:3.12-slim";
        $("s_stream").value=settingsCache.stream_experts||"auto"; $("s_parallel").value=settingsCache.parallel_experts||"auto";
        $("s_mem").value=settingsCache.memory_rounds??2; $("s_ctx").value=settingsCache.context_char_limit??12000;
        $("s_conc").value=settingsCache.max_concurrency??4; $("s_lto").value=settingsCache.llm_timeout??180;
        $("s_web").checked=!!settingsCache.web_search_enabled;
        loadPresets();
        renderBoard(); renderAgentConfig();
        if(typeof loadUsage==="function") loadUsage();
        $("settingsModal").classList.remove("hidden");
      }
      function closeSettings(){ $("settingsModal").classList.add("hidden"); }
      /* ---------- 案件管理（案例库 + 复盘，一级入口） ---------- */
      function openCaseManager(){ closeSettings(); switchCaseTab("lib"); refreshCaseLibrary(); refreshDebates(); $("caseModal").classList.remove("hidden"); }
      function closeCaseManager(){ $("caseModal").classList.add("hidden"); }
      function switchCaseTab(name){
        document.querySelectorAll("[data-ctab]").forEach(t=>t.classList.toggle("on",t.dataset.ctab===name));
        const lib=$("ctab-lib"), deb=$("ctab-debates");
        if(lib) lib.classList.toggle("on", name==="lib");
        if(deb){ deb.classList.toggle("on", name==="debates"); deb.style.display = name==="debates" ? "" : "none"; }
        if(lib) lib.style.display = name==="lib" ? "" : "none";
      }
      function switchTab(name){ document.querySelectorAll(".tab").forEach(t=>t.classList.toggle("on",t.dataset.tab===name)); document.querySelectorAll(".tabpane").forEach(p=>p.classList.toggle("on",p.id==="tab-"+name)); if(name==="board") renderBoard(); if(name==="agents") renderAgentConfig(); }
      function syncSettingsFields(){ const p=$("s_provider").value, local=p==="ollama", mock=p==="mock";
        if(local){ $("s_base").value=settingsCache.ollama_base_url||"http://localhost:11434/v1"; $("s_model").value=settingsCache.ollama_model||"qwen2.5:14b"; $("s_key").value=""; $("s_key").disabled=true; $("s_key").style.opacity=.4; $("lblKey").textContent="API Key（本地无需）"; $("lblBase").textContent="Ollama Base URL"; $("lblModel").textContent="Ollama 模型"; }
        else if(mock){ ["s_base","s_key","s_model"].forEach(id=>{$(id).value="";$(id).disabled=true;$(id).style.opacity=.4;}); $("lblBase").textContent="API Base URL"; $("lblKey").textContent="API Key"; $("lblModel").textContent="模型名称"; }
        else { $("s_base").value=settingsCache.llm_base_url||""; $("s_model").value=settingsCache.llm_model||""; $("s_key").value=settingsCache.llm_api_key||""; ["s_base","s_key","s_model"].forEach(id=>{$(id).disabled=false;$(id).style.opacity=1;}); $("lblBase").textContent="API Base URL"; $("lblKey").textContent="API Key"; $("lblModel").textContent="模型名称"; }
      }
      function renderBoard(){ const box=$("boardList"); box.innerHTML=""; sortedAgents().filter(a=>isDebatable(a.key)).forEach(a=>{ const el=document.createElement("div"); el.className="ac-item"; el.innerHTML=`<div class="ac-top"><div class="ainit" style="background:${a.color}">${a.name.slice(0,1)}</div><div class="an">${a.name}</div><input class="ord" type="number" min="0" max="20" value="${a.order}" data-k="${a.key}" onchange="onOrderChange(this)"><input type="checkbox" ${a.enabled?"checked":""} data-k="${a.key}" onchange="onEnableChange(this)" style="width:16px;height:16px;accent-color:var(--navy);margin-left:12px"></div><div class="ad" style="font-size:11px;color:var(--muted);margin-top:4px">${a.duty}</div>`; box.appendChild(el); }); }
      function onOrderChange(e){ const k=e.dataset.k; agentsCfg[k].order=parseInt(e.value)||0; renderBoard(); }
      function onEnableChange(e){ const k=e.dataset.k; agentsCfg[k].enabled=e.checked; }
      function renderAgentConfig(){ const box=$("agentList"); box.innerHTML=""; sortedAgents().forEach(a=>{ const noTools = (a.key==="judge"||a.key==="critic"); const tools=(a.tools||ALL_TOOLS).slice(); const toolChk= noTools ? `<span class="muted" style="font-size:11.5px">该角色不调用工具</span>` : ALL_TOOLS.map(t=>`<label><input type="checkbox" data-k="${a.key}" data-t="${t}" ${tools.includes(t)?"checked":""} onchange="onToolChange(this)">${TOOL_LABELS[t]||t}</label>`).join(""); const el=document.createElement("div"); el.className="ac-item"; el.innerHTML=`<div class="ac-top"><div class="ainit" style="background:${a.color}">${a.name.slice(0,1)}</div><div class="an">${a.name}</div>${a.key==="critic"?'<span class="rtag" style="margin-left:auto">纠错官</span>':a.key==="judge"?'<span class="rtag" style="margin-left:auto">审判长</span>':""}</div><div class="ad" style="font-size:11px;color:var(--muted);margin:4px 0 6px">${a.stance||a.duty}</div><label style="font-size:12px;color:var(--muted);font-weight:600">系统提示词</label><textarea data-k="${a.key}" rows="4" placeholder="${(a.default_prompt||"").replace(/"/g,"&quot;")}">${a.system_prompt||""}</textarea><label style="font-size:12px;color:var(--muted);font-weight:600;margin-top:8px">模型覆盖（留空=主模型，如 gpt-4o / deepseek-chat）</label><input data-model="${a.key}" value="${a.model||""}" placeholder="留空使用审理引擎主模型" style="width:100%;padding:8px 10px;" onchange="onModelChange(this)" />${noTools?"":`<label style="font-size:12px;color:var(--muted);font-weight:600;margin-top:8px">可用工具</label><div class="ac-tools">${toolChk}</div>`}`; box.appendChild(el); }); }
      function onToolChange(e){ const k=e.dataset.k; const has=(agentsCfg[k].tools||ALL_TOOLS.slice()); if(e.checked){ if(!has.includes(e.dataset.t)) has.push(e.dataset.t); } else { const i=has.indexOf(e.dataset.t); if(i>=0) has.splice(i,1); } agentsCfg[k].tools=has; }
      function onModelChange(e){ const k=e.dataset.k; agentsCfg[k].model = e.value.trim() || null; }
      async function installPkg(){
        const pkg=$("s_pkg").value.trim(); const out=$("pkgOut"); out.style.display="block"; out.textContent="安装中…";
        try {
          const r=await fetch("/api/sandbox/install",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({package:pkg})});
          const d=await r.json(); out.textContent=d.result||d.error||("HTTP "+r.status);
        } catch(e){ out.textContent="请求失败: "+e.message; }
      }
      async function runTry(){
        const code=$("s_try").value; const out=$("tryOut"); out.innerHTML="运行中…";
        try {
          const r=await fetch("/api/sandbox/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({code})});
          const d=await r.json(); out.innerHTML = (d.result!=null)? renderSandbox(d.result) : ("<span class='muted'>"+(d.error||("HTTP "+r.status))+"</span>");
        } catch(e){ out.innerHTML="<span class='muted'>请求失败: "+escape(e.message)+"</span>"; }
      }
      async function testSettings(){
        const p=$("s_provider").value;
        const payload={ llm_provider:p };
        if(p==="ollama"){ payload.ollama_base_url=$("s_base").value.trim(); payload.ollama_model=$("s_model").value.trim(); }
        else if(p==="openai_compatible"||p==="openai"){ payload.llm_base_url=$("s_base").value.trim(); payload.llm_api_key=$("s_key").value.trim(); payload.llm_model=$("s_model").value.trim(); }
        const btn=$("btnTest"); btn.disabled=true; btn.textContent="测试中…"; $("testResult").textContent="";
        try {
          const r=await fetch("/api/settings/test",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
          const d=await r.json();
          const el=$("testResult");
          if(d.ok){ el.innerHTML=`✅ <b>${d.model||p}</b> · ${d.elapsed_s??0}s · <span style="color:var(--success)">${d.message||"连接正常"}</span>`; }
          else { el.innerHTML=`❌ ${escape(d.error||"未知错误")}`; }
        } catch(e){ $("testResult").innerHTML=`❌ 请求失败: ${escape(e.message)}`; }
        finally { btn.disabled=false; btn.textContent="🔌 测试连接"; }
      }
      async function saveSettings(){
        const p=$("s_provider").value;
        const temp=parseFloat($("s_temp").value); const rounds=parseInt($("s_rounds").value);
        if(isNaN(temp)||temp<0||temp>2){ $("setMsg").textContent="温度须为 0-2"; $("setMsg").style.color="var(--bad)"; return; }
        if(isNaN(rounds)||rounds<1||rounds>10){ $("setMsg").textContent="审理轮次须为 1-10"; $("setMsg").style.color="var(--bad)"; return; }
        const hitl=parseInt($("s_hitl").value);
        if(isNaN(hitl)||hitl<0||hitl>86400){ $("setMsg").textContent="落槌等待须为 0-86400 秒"; $("setMsg").style.color="var(--bad)"; return; }
        const memR=parseInt($("s_mem").value), ctxL=parseInt($("s_ctx").value), conc=parseInt($("s_conc").value), lto=parseInt($("s_lto").value);
        if(isNaN(memR)||memR<0||memR>6){ $("setMsg").textContent="记忆窗口须为 0-6 轮"; $("setMsg").style.color="var(--bad)"; return; }
        if(isNaN(ctxL)||ctxL<0){ $("setMsg").textContent="上下文上限须为非负"; $("setMsg").style.color="var(--bad)"; return; }
        if(isNaN(conc)||conc<1||conc>7){ $("setMsg").textContent="并行数须为 1-7"; $("setMsg").style.color="var(--bad)"; return; }
        if(isNaN(lto)||lto<0||lto>1800){ $("setMsg").textContent="超时须为 0-1800 秒"; $("setMsg").style.color="var(--bad)"; return; }
        const engine={ llm_provider:p, temperature:temp, max_rounds:rounds, judge_mode:$("s_judge").value, hitl_timeout:hitl, memory_rounds:memR, context_char_limit:ctxL, max_concurrency:conc, llm_timeout:lto, web_search_enabled:$("s_web").checked, intake_model:$("s_intake").value.trim(), code_sandbox_enabled:$("s_sandbox").checked, code_sandbox_python:$("s_py").value.trim()||"python3", code_sandbox_backend:$("s_sbbackend").value, code_sandbox_docker_image:$("s_sbimage").value.trim()||"python:3.12-slim", stream_experts:$("s_stream").value, parallel_experts:$("s_parallel").value };
        if(p==="ollama"){ engine.ollama_base_url=$("s_base").value.trim(); engine.ollama_model=$("s_model").value.trim(); }
        else if(p==="openai_compatible"||p==="openai"){ engine.llm_base_url=$("s_base").value.trim(); engine.llm_api_key=$("s_key").value.trim(); engine.llm_model=$("s_model").value.trim(); }
        const agentMap={}; Object.values(agentsCfg).forEach(a=>{ const ta=document.querySelector(`textarea[data-k="${a.key}"]`); const mi=document.querySelector(`input[data-model="${a.key}"]`); const prompt=ta?ta.value.trim():""; agentMap[a.key]={ enabled:a.enabled, order:a.order, system_prompt: prompt||null, tools:a.tools||null, model: (mi&&mi.value.trim())||null }; });
        try {
          const r1=await fetch("/api/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(engine)}); if(!r1.ok) throw new Error("引擎保存失败"); settingsCache=await r1.json();
          const r2=await fetch("/api/agent-config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({agents:agentMap})}); if(!r2.ok) throw new Error("专家配置保存失败");
          const d=await r2.json(); agentsCfg={}; d.agents.forEach(a=>agentsCfg[a.key]=a);
          applyModelBadge(); enabledAgents=new Set(Object.values(agentsCfg).filter(a=>a.enabled).map(a=>a.key));
          renderLandRoster(); closeSettings(); toast("设置已保存，对下一场审理生效");
        } catch(e){ $("setMsg").textContent="保存失败: "+e.message; $("setMsg").style.color="var(--bad)"; }
      }

      // ---------- 专家配置导入导出 ----------
      async function exportAgentConfig(){
        try {
          const d = await (await fetch("/api/agent-config")).json();
          const blob = new Blob([JSON.stringify(d, null, 2)], {type:"application/json"});
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a"); a.href=url; a.download="verdictai-agent-config.json"; a.click();
          setTimeout(()=>URL.revokeObjectURL(url), 2000);
          toast("专家配置已导出");
        } catch(e){ toast("导出失败: "+e.message); }
      }
      async function importAgentConfig(evt){
        const f = evt.target.files[0]; if(!f) return;
        try {
          const data = JSON.parse(await f.text());
          if(!data.agents) throw new Error("格式不符（缺少 agents 字段）");
          const r = await fetch("/api/agent-config",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
          if(!r.ok) throw new Error("HTTP "+r.status);
          const d = await r.json();
          agentsCfg={}; d.agents.forEach(a=>agentsCfg[a.key]=a);
          enabledAgents=new Set(Object.values(agentsCfg).filter(a=>a.enabled).map(a=>a.key));
          renderAgentConfig(); renderLandRoster();
          toast("专家配置已导入并生效");
        } catch(e){ toast("导入失败: "+e.message); }
        evt.target.value="";
      }

      // ---------- 策略模板（Presets） ----------
      async function loadPresets(){
        const sel=$("s_preset"); if(!sel) return;
        try {
          const d=await (await fetch("/api/presets")).json();
          sel.innerHTML = Object.keys(d.presets||{}).map(n=>`<option>${escapeHtml(n)}</option>`).join("");
        } catch(e){ sel.innerHTML=""; }
      }
      async function applyPreset(){
        const name=$("s_preset").value; if(!name){ toast("请先选择模板"); return; }
        $("presetMsg").textContent="应用中…";
        try {
          const r=await fetch("/api/presets/apply",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name})});
          const d=await r.json();
          if(!r.ok){ $("presetMsg").textContent="应用失败: "+(d.error||r.status); return; }
          if(d.agents){ agentsCfg={}; d.agents.forEach(a=>agentsCfg[a.key]=a); renderAgentConfig(); }
          $("presetMsg").textContent="已应用。总体指导语：" + (d.guidance||"（无）").slice(0,80);
          toast("策略模板「"+name+"」已应用，下一场审理生效");
        } catch(e){ $("presetMsg").textContent="请求失败: "+e.message; }
      }
      async function savePreset(){
        const name=$("presetName").value.trim(); if(!name){ toast("请填写模板名称"); return; }
        const agents={}; Object.values(agentsCfg).forEach(a=>{ agents[a.key]= a.system_prompt || a.default_prompt || ""; });
        try {
          const r=await fetch("/api/presets",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name, guidance:"", agents})});
          if(!r.ok){ const d=await r.json(); toast("保存失败: "+(d.error||r.status)); return; }
          $("presetMsg").textContent="已另存模板「"+name+"」";
          loadPresets();
        } catch(e){ toast("请求失败: "+e.message); }
      }
      async function deletePreset(){
        const name=$("s_preset").value; if(!name) return;
        if(!await confirmDialog("删除模板「"+name+"」？")) return;
        try {
          const r=await fetch("/api/presets/"+encodeURIComponent(name),{method:"DELETE"});
          const d=await r.json().catch(()=>({}));
          if(!r.ok){ toast("删除失败: "+(d.error||r.status)); return; }
          toast("已删除模板"); loadPresets();
        } catch(e){ toast("请求失败: "+e.message); }
      }

      // ---------- 知识库 ----------
      let kbDebounce=null;
      function kbSearchInput(){ clearTimeout(kbDebounce); kbDebounce=setTimeout(loadKnowledge, 320); }
      async function loadKnowledge(){
        const box=$("kbList"); if(!box) return;
        const q=($("kbSearch")||{}).value||"";
        const semantic = !!($("kbSemantic")||{}).checked ? 1 : 0;
        try {
          const d=await (await fetch("/api/knowledge?q="+encodeURIComponent(q)+(semantic?"&semantic=1":""))).json();
          const list=d.entries||[];
          if(!list.length){ box.innerHTML="<div class='muted'>无匹配条目。</div>"; return; }
          box.innerHTML="";
          list.forEach(e=>{
            const el=document.createElement("div"); el.className="kb-item";
            const kws=(e.keywords||[]).map(k=>" <span style='color:var(--gold)'>#"+escapeHtml(k)+"</span>").join("");
            const sim = e.semantic ? `<span class="badge" style="background:#eaf6ee;color:#1e7d3c">语义</span>` : "";
            el.innerHTML=`<div class="kb-title">${escapeHtml(e.title)}${sim}</div><div class="kb-meta">${escapeHtml(e.category||"")}${kws}</div><div class="kb-text md">${escapeHtml(e.text||"")}</div>`;
            if(e.source==="custom"){
              if(currentRole==="admin"){
                const btn=document.createElement("button"); btn.className="ghost danger"; btn.textContent="删除"; btn.style.marginTop="8px"; btn.style.fontSize="11px";
                btn.onclick=async()=>{ if(!await confirmDialog("删除该自定义条目？")) return; await fetch("/api/knowledge/"+e.id,{method:"DELETE"}); loadKnowledge(); };
                el.appendChild(btn);
              }
            } else {
              const tag=document.createElement("span"); tag.className="badge"; tag.textContent="内置"; tag.style.marginTop="8px"; tag.style.fontSize="10px";
              el.appendChild(tag);
            }
            box.appendChild(el);
          });
        } catch(e){ box.innerHTML="<div class='muted'>加载失败: "+escape(e.message)+"</div>"; }
      }
      async function addKnowledge(){
        const t=$("kbTitle").value.trim(), kw=$("kbKw").value.trim(), tx=$("kbText").value.trim();
        if(!t||!tx){ toast("标题与正文不能为空"); return; }
        try {
          const r=await fetch("/api/knowledge",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:t,text:tx,keywords:kw})});
          if(!r.ok){ const d=await r.json(); toast("保存失败: "+(d.error||r.status)); return; }
          $("kbTitle").value=""; $("kbKw").value=""; $("kbText").value="";
          toast("已加入知识库，下次辩论即可被专家引用");
          loadKnowledge();
        } catch(e){ toast("请求失败: "+e.message); }
      }

      let libDebounce = null;
      function libFilterInput(){ clearTimeout(libDebounce); libDebounce = setTimeout(refreshCaseLibrary, 300); }
      let libTagsLoaded = false;
      async function loadLibTags(){
        if (libTagsLoaded) return;
        try {
          const d = await (await fetch("/api/cases/tags")).json();
          const sel = $("libTag"); if(!sel) return;
          const cur = sel.value || "";
          const opts = (d.tags||[]).map(t=>`<option value="${escapeHtml(t)}">${escapeHtml(t)}</option>`).join("");
          sel.innerHTML = `<option value="">全部案由/标签</option>` + opts;
          if (cur) sel.value = cur;
          libTagsLoaded = true;
        } catch(e){ /* 静默：标签面板非关键 */ }
      }
      function importDocs(){ const inp=$("libImport"); if(inp) inp.click(); }
      async function importDocsFiles(inp){
        const files = (inp.files||[]);
        if(!files.length) return;
        toast("批量导入 " + files.length + " 个文件，预处理中…");
        const filesPayload = [];
        for (const f of files) {
          const name = f.name.toLowerCase();
          let ft = "txt";
          if (name.endsWith(".pdf")) ft = "pdf";
          else if (name.endsWith(".docx")) ft = "docx";
          else if (name.endsWith(".doc")) ft = "doc";
          else if (name.endsWith(".png")) ft = "png";
          else if (name.endsWith(".jpg") || name.endsWith(".jpeg")) ft = "jpeg";
          else if (name.endsWith(".webp")) ft = "webp";
          filesPayload.push({ file_type: ft, file_content: await fileToB64(f), file_name: f.name });
        }
        inp.value = "";
        try {
          const r = await fetch("/api/cases/import_batch", { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({ files: filesPayload }) });
          const d = await r.json();
          if(d.imported>0){ toast("✓ 导入成功 " + d.imported + "/" + d.total + " 份"); }
          else { toast("导入失败：" + ((d.results||[]).map(x=>x.error).filter(Boolean).join("；") || "未知错误")); }
        } catch(e){ toast("批量导入请求失败: " + e.message); }
        refreshCaseLibrary();
      }
      async function refreshCaseLibrary(){
        const box=$("libList"); box.innerHTML="<div class='muted'>加载中…</div>";
        loadLibTags();
        const q = (($("libQ")||{}).value||"").trim();
        const tag = (($("libTag")||{}).value||"").trim();
        const hb = !!($("libOnlyBrief")||{}).checked ? 1 : 0;
        try {
          const params = new URLSearchParams();
          if (q) params.set("q", q);
          if (tag) params.set("tag", tag);
          if (hb) params.set("has_brief", "1");
          const qs = params.toString();
          const d=await (await fetch("/api/cases"+(qs?"?"+qs:""))).json();
          renderCaseLibrary(d.cases||[]);
        } catch(e){ box.innerHTML="<div class='muted' style='color:var(--bad)'>加载失败: "+escape(e.message)+"</div>"; }
        refreshDebates();
      }
      function fmtDateTime(ts){ if(!ts) return ""; const d=new Date(ts); if(isNaN(d.getTime())) return String(ts); const p=n=>String(n).padStart(2,"0"); return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; }
      async function refreshDebates(){
        const box=$("debateList"); if(!box) return; box.innerHTML="<div class='muted'>加载中…</div>";
        let list=[]; try{ list=await (await fetch("/api/debates")).json(); }catch(e){ list=[]; }
        if(!list.length){ box.innerHTML="<div class='muted'>暂无复盘记录。</div>"; return; }
        box.innerHTML="";
        list.forEach(d=>{
          const el=document.createElement("div"); el.className="lib-item";
          const t=escape((d.truth||"无结论").slice(0,70));
          const u=(d.usage&&d.usage.calls)?(" · 推理 "+d.usage.calls+" 次"):"";
          el.innerHTML=`<div class="lib-main"><div class="lib-title">${escape(d.case_title||"案件")}</div><div class="lib-meta">${fmtDateTime(d.started_at)||""} · ${d.rounds||0}轮 · ${d.model||""}${u}</div></div><div class="lib-sub" style="margin:4px 0">${t}</div>`;
          const btn=document.createElement("button"); btn.className="ghost"; btn.textContent="打开复盘"; btn.style.marginTop="6px";
          btn.onclick=()=>openReplay(d.session_id);
          el.appendChild(btn); box.appendChild(el);
        });
      }
      async function openReplay(sid){
        closeSettings();
        manualClose = true; try { if (ws && ws.readyState <= 1) ws.close(); } catch(e){}
        running = false; wsRetries = 0; $("landStart").disabled = false;
        let rec=null; try{ rec=await (await fetch("/api/debates/"+sid)).json(); }catch(e){ toast("加载复盘记录失败"); return; }
        if(!rec || !Array.isArray(rec.events)){ toast("复盘记录不可用"); return; }
        hideLanding();
        // 载入案件卷宗，保证复盘视图与报告正确
        if(rec.case_id){ try{ const c=await (await fetch("/api/cases/"+rec.case_id)).json(); if(c && c.id){ selectedCase=c.id; caseDetail=c; renderCase(); } }catch(e){ toast("加载复盘案件失败"); } }
        session=sid; // 后续流程清单勾选持久化用
        reset();
        // 上万条事件逐条重渲染会长期冻结 UI：回放期间挂起渲染，最后一次性重建
        const _rd = window.renderDebate;
        if(typeof _rd === "function"){ window.renderDebate = function(){}; }
        try{
          // 把落盘的「后续流程」勾选挂到裁决事件上，replay 时 renderVerdict 自动恢复
          const nsSaved = Array.isArray(rec.ns_done) ? rec.ns_done : null;
          rec.events.forEach(ev=>{
            if(ev && ev.kind==="verdict" && nsSaved && ev.verdict){ ev.verdict.ns_done = nsSaved; }
            handle(ev);
          });
        } finally { if(typeof _rd === "function"){ window.renderDebate = _rd; } }
        renderDebate();
        setPhase("done");
        $("dlReport").classList.remove("hidden");
        toast("已载入复盘：" + (rec.case_title||sid));
      }
      function renderCaseLibrary(cases){
        const box=$("libList"); box.innerHTML="";
        if(!cases.length){ box.innerHTML="<div class='muted'>案例库为空。上传 PDF 或点击「生成示例案件」开始。</div>"; return; }
        cases.forEach(c=>{
          const el=document.createElement("div"); el.className="lib-item";
          const hasBrief = c.brief && c.brief.intake_done;
          const delBtn = currentRole==="admin" ? `<button class="ghost danger" onclick="deleteCase('${escape(c.id)}')">删除</button>` : "";
          el.innerHTML=`<div class="lib-main"><div class="lib-title">${escape(c.title||"无标题")}</div><div class="lib-meta">ID: ${escape(c.id||"")} · ${c.persons?.length||0}人 · ${c.evidence?.length||0}证 · ${c.timeline?.length||0}时刻 ${hasBrief?"· ✓已预处理":""}</div></div><div class="lib-actions"><button class="ghost" onclick="openTimelineModal('${escape(c.id)}')">⏱ 时间线</button><button class="ghost" onclick="viewCase('${escape(c.id)}')">查看</button><button class="primary" onclick="selectCaseFromLib('${escape(c.id)}')">选中</button>${delBtn}</div>`;
          box.appendChild(el);
        });
      }
      async function generateSampleCase(btn){
        btn.disabled=true; const old=btn.textContent; btn.textContent="生成中…";
        try {
          const r=await fetch("/api/cases/generate",{method:"POST"}); if(!r.ok) throw new Error("HTTP "+r.status);
          const d=await r.json(); toast("示例案件已生成: "+d.case.id); await refreshCaseLibrary();
        } catch(e){ toast("生成失败: "+e.message); } finally { btn.disabled=false; btn.textContent=old; }
      }
      async function deleteCase(id){
        if(!await confirmDialog("确定删除案件 "+id+"？此操作不可恢复。")) return;
        try {
          const r=await fetch("/api/cases/"+id,{method:"DELETE"}); if(!r.ok) throw new Error("HTTP "+r.status);
          toast("已删除: "+id); await refreshCaseLibrary();
          // 如果当前选中的是被删除的案件，重置
          if(selectedCase===id){ selectedCase=""; const land=$("landCase"); land.value=""; caseDetail=null; renderCase(); }
        } catch(e){ toast("删除失败: "+e.message); }
      }
      function timelineSvg(items){
        /* 横向证据时间线（M1.5）：节点=时间，下方=事件摘要；横向滚动。 */
        const n=Math.min(items.length||0, 20), W=Math.max(420, n*150+60), H=170, y=70;
        if(!n) return '<div class="muted">该案件暂无时间线节点。</div>';
        let s=`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" style="display:block;min-width:${W}px">`;
        s+=`<line x1="24" y1="${y}" x2="${W-24}" y2="${y}" stroke="#c9b98a" stroke-width="2"/>`;
        items.slice(0,n).forEach((it,i)=>{
          const x=44+i*150;
          s+=`<circle cx="${x}" cy="${y}" r="6" fill="#9c7c43" stroke="#e9ddc0" stroke-width="2"/>`;
          s+=`<line x1="${x}" y1="${y}" x2="${x}" y2="${y+16}" stroke="#c9b98a" stroke-width="1.5" stroke-dasharray="3,3"/>`;
          s+=`<text x="${x}" y="${y-16}" text-anchor="middle" font-size="11" fill="#8a6d3b">${escape(it.time||"-")}</text>`;
          const ev=String(it.event||""); s+=`<text x="${x}" y="${y+34}" text-anchor="middle" font-size="11" fill="#4a5560">${escape(ev.length>20?ev.slice(0,19)+"…":ev)}</text>`;
          if(it.source) s+=`<text x="${x}" y="${y+50}" text-anchor="middle" font-size="9.5" fill="#9aa5b1">${escape(String(it.source).slice(0,14))}</text>`;
        });
        return s+"</svg>";
      }
      async function openTimelineModal(id){
        const ov=document.createElement("div"); ov.className="tl-overlay";
        ov.innerHTML='<div class="tl-modal"><div class="tl-load">加载时间线…</div></div>';
        document.body.appendChild(ov);
        try{
          const [tl, sim]=await Promise.all([
            fetch("/api/cases/"+encodeURIComponent(id)+"/timeline").then(r=>r.json()),
            fetch("/api/cases/"+encodeURIComponent(id)+"/similar").then(r=>r.json())
          ]);
          const title=tl.case_id||id;
          const similar=(sim.similar||[]).map(s=>
            `<div class="tl-sim"><span class="tl-sim-t">${escape(s.title||"")}</span><span class="tl-sim-s">相似度 ${Math.round((s.score||0)*100)}% · ${escape(s.cause||"未归类")}</span></div>`).join("") || '<div class="muted">暂无其他案例可对比</div>';
          ov.innerHTML=`<div class="tl-modal"><div class="tl-head"><b>证据时间线 · ${escape(title)}</b>（${tl.count||0} 个时间节点）<button class="ghost" onclick="this.closest('.tl-overlay').remove()" style="margin-left:auto">✕</button></div><div class="tl-scroll">${timelineSvg(tl.timeline||[])}</div><div class="tl-sec">相似案例推荐（基于语义/案由匹配）</div><div>${similar}</div><div class="tl-foot muted">时间线按时间排序 · 数据来自卷宗 timeline 字段</div></div>`;
          ov.onclick=(e)=>{ if(e.target===ov) ov.remove(); };
        }catch(e){ ov.innerHTML=`<div class="tl-modal"><div class="tl-load">加载失败：${escape(e.message)}</div></div>`; setTimeout(()=>ov.remove(), 1600); }
      }
      function viewCase(id){
        // "查看"= 选中案件并直接进入工作区研读卷宗（与落地页停留区分开）
        selectCaseFromLib(id);
        closeSettings();
        hideLanding();
        $("landStart").disabled = false;
        toast("已载入案件卷宗，可点击「开庭审理」开始辩论");
      }
      function selectCaseFromLib(id){
        selectedCase=id;
        const land=$("landCase");
        if(land){
          // 落地页下拉只预载了部分案件；从案例库选中新上传/新生成的案件时动态补齐选项，保证 value 能设置成功
          if(!Array.from(land.options).some(o=>o.value===id)){
            const o=document.createElement("option"); o.value=id; o.textContent=id; land.appendChild(o);
          }
          land.value=id;
        }
        loadCase();
      }

      let _focused = false;
      function focusMode(){
        _focused = !_focused;
        const m = $("workspace");
        m.classList.toggle("no-left", _focused);
        m.classList.toggle("no-right", _focused);
        $("btnFocus").textContent = _focused ? "⤢ 退出聚焦" : "⛶ 聚焦";
        $("btnLeft").style.display = _focused ? "none" : "";
        $("btnRight").style.display = _focused ? "none" : "";
      }
      function copyTranscript(){
        if(!messages.length){ toast("笔录还是空的"); return; }
        const t = messages.map(m => "【" + m.name + "】\n" + (m.text || "")).join("\n\n");
        const done = () => toast("全文笔录已复制（" + messages.length + " 条发言）");
        if(navigator.clipboard && navigator.clipboard.writeText){ navigator.clipboard.writeText(t).then(done).catch(()=>fallbackCopy(t,done)); }
        else fallbackCopy(t,done);
      }
      function openHelp(){ $("helpModal").classList.remove("hidden"); }
      function closeHelp(){ $("helpModal").classList.add("hidden"); }
      function toast(msg){ const t=document.createElement("div"); t.className="toast"; t.textContent=msg; document.body.appendChild(t); setTimeout(()=>t.remove(),2600); }

      // ---------- 明暗主题 ----------
      function applyTheme(dark){
        document.body.classList.toggle("dark", dark);
        $("btnTheme").textContent = dark ? "☀️" : "🌙";
      }
      function toggleTheme(){
        const dark = !document.body.classList.contains("dark");
        applyTheme(dark);
        try { localStorage.setItem("vai_theme", dark ? "dark" : "light"); } catch(e){}
        toast(dark ? "已切换到深色模式" : "已切换到浅色模式");
      }
      (function(){
        let pref = "light";
        try { pref = localStorage.getItem("vai_theme") || "light"; } catch(e){}
        applyTheme(pref === "dark");
      })();

      // 全局错误处理
      window.addEventListener('unhandledrejection', e => {
        console.error('[UnhandledRejection]', e.reason);
        e.preventDefault();
        toast("⚠️ 系统错误: "+(e.reason?.message||String(e.reason)));
      });
      window.addEventListener('error', e => {
        console.error('[GlobalError]', e.message, e.filename+':'+e.lineno);
        toast("⚠️ 系统错误，请刷新页面");
      });

      // 轻量级 confirm modal
      function confirmDialog(msg){
        return new Promise(resolve=>{
          const overlay=document.createElement("div"); overlay.className="modal"; overlay.innerHTML=`
            <div class="modal-card" style="width:min(400px,90vw)">
              <div class="modal-head"><span>确认操作</span><button class="ghost" onclick="this.closest('.modal').remove();resolve(false)" style="font-size:16px" aria-label="关闭确认弹窗">✕</button></div>
              <div class="modal-body"><p style="margin:0;line-height:1.7">${escapeHtml(msg)}</p></div>
              <div class="modal-foot"><div style="margin-left:auto"><button class="ghost" id="cd-no" aria-label="取消操作">取消</button><button class="primary" id="cd-yes" aria-label="确认操作">确认</button></div></div>
            </div>`;
          document.body.appendChild(overlay);
          const close=()=>{ overlay.remove(); };
          overlay.querySelector("#cd-no").onclick=()=>{ close(); resolve(false); };
          overlay.querySelector("#cd-yes").onclick=()=>{ close(); resolve(true); };
          overlay.addEventListener("click",e=>{ if(e.target===overlay){ close(); resolve(false); }});
        });
      }

      // 键盘快捷键
      document.addEventListener("keydown", (e) => {
        // 输入框中不触发全局快捷键
        const tag = (e.target.tagName || "").toLowerCase();
        if (tag === "input" || tag === "textarea" || tag === "select") return;
        if (e.key === "Escape") {
          // 关闭弹窗 / 关闭移动端面板
          const modals = document.querySelectorAll(".modal:not(.hidden)");
          if (modals.length) { modals.forEach(m => m.classList.add("hidden")); return; }
          if (isMobile()) closeMobilePanels();
        } else if (e.key === "s" && !e.ctrlKey && !e.metaKey) {
          if (running) stopDebate();
        } else if (e.key === "?" || e.key === "/") {
          e.preventDefault();
          openHelp();
        } else if (e.key === "1" && isMobile()) {
          toggleMobilePanel("left");
        } else if (e.key === "2" && isMobile()) {
          closeMobilePanels();
        } else if (e.key === "3" && isMobile()) {
          toggleMobilePanel("right");
        }
      });

      // 窗口大小变化时重置移动端面板状态
      let resizeTimer;
      window.addEventListener("resize", () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          if (!isMobile()) closeMobilePanels();
        }, 200);
      });

      window.addEventListener("beforeunload", () => { manualClose = true; try { if (ws) ws.close(); } catch (e) {} });
      init();
