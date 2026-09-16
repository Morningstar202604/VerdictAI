      const $ = (id) => document.getElementById(id);
      // 转义 panic-safe：原实现（textContent→innerHTML / 手写部分替换）均不转义引号，
      // 而本函数的结果会被拼进 title / data-q 等属性里（app-ui.js:44、core:64），
      // 含引号文本会截断属性。统一补 " 与 ' 两种引号的转义。
      function escapeHtml(s){
        return String(s==null?"":s)
          .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
          .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
      }
      // 后端异常时返回的是 {error:...} 而非 {cases:[...]}，直接取 .cases 得 undefined，
      // 后续 forEach 抛 TypeError 会中断 init()，导致案件下拉/chips/名册全部不渲染。
      function pickCases(json){ return Array.isArray(json && json.cases) ? json.cases : []; }
      let intakeOverrides = {}; let serverBrief = null; let lastVerdict = null; let contraList = []; let recNotes = []; let qaHistory = []; let nsDone = new Set(); let lastUsage = null; let lastTrace = null;

      /* ================= 法条引用核查（幻觉防火墙 / 引用信号灯） =================
         与后端 app/legal/cite_check.py 同一套规范化逻辑的 JS 移植：
         《中华人民共和国刑法》第二百六十六条 / 刑法第266条 / 刑诉法第56条
         全部归一为 "刑法|第266条" 形式的 key，与 knownStatutes 比对：
         命中 → ✓ 已核实（卷宗法条/内置法条库）；未命中 → ⚠ 待人工核对。 */
      let knownStatutes = {};
      const CN_DIG = {"零":0,"〇":0,"一":1,"二":2,"两":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9};
      const CN_UNIT = {"十":10,"百":100,"千":1000};
      const LAW_NOISE = /^(?:同时|此外|而且|并且|并|另|另据|又|及|或|且|但|而|则|即|也|还|再|依照|依据|根据|参照|按照|关于|对于|适用|符合|违反|触犯|引用|参见|援引|如|若|凡|据|按|涉|涉及|我国|本)+/;
      const LAW_ALIAS = {"刑诉法":"刑事诉讼法","民诉法":"民事诉讼法"};
      const CITE_RE = /(?:《([^《》]{2,25}?)》|([\u4e00-\u9fff]{1,12}?法))\s*第\s*([零〇一二两三四五六七八九十百千\d]{1,10})\s*条(之[一二三四])?/g;
      function chnToInt(s){
        s = String(s||"").trim().replace(/^第+/,"").replace(/条+$/,"").trim();
        if(/^\d+$/.test(s)) return parseInt(s,10);
        let total=0, num=0, seen=false;
        for(const ch of s){
          if(ch in CN_DIG){ num=CN_DIG[ch]; seen=true; }
          else if(ch in CN_UNIT){ if(!seen) num=1; total+=num*CN_UNIT[ch]; num=0; seen=false; }
          else return null;
        }
        if(!(seen||total)) return null;
        return total+num;
      }
      function normLaw(law){
        law = String(law||"").replace(/[《》〈〉「」\s\u3000]/g,"").replace(/中华人民共和国/g,"");
        let prev=null;
        while(prev!==law){ prev=law; law=law.replace(LAW_NOISE,""); }
        return LAW_ALIAS[law]||law;
      }
      function statuteKey(law, art, alt){
        const n=chnToInt(art);
        if(!law||n==null) return "";
        return normLaw(law)+"|第"+n+"条"+(alt||"");
      }
      function extractCites(text){
        const out=[], seen={};
        CITE_RE.lastIndex=0;
        let m;
        while((m=CITE_RE.exec(String(text||"")))){
          const key=statuteKey(m[1]||m[2], m[3], m[4]||"");
          if(!key||seen[key]) continue;
          seen[key]=1;
          out.push({raw:m[0].trim(), key, law:normLaw(m[1]||m[2])});
        }
        return out;
      }
      async function loadKnownStatutes(caseId){
        try{
          const d=await (await fetch("/api/legal/known-statutes"+(caseId?("?case_id="+encodeURIComponent(caseId)):""))).json();
          const map={};
          (d.statutes||[]).forEach(s=>{ map[s.key]={name:s.name, source:s.source}; });
          knownStatutes=map;
        }catch(e){ /* 静默：核查面板非关键路径，失败仅不显示信号灯 */ }
      }
      function citeBadge(c){
        const hit=knownStatutes[c.key];
        const short=c.key.replace("|"," · ");
        if(hit){
          const from=hit.source==="case"?"卷宗法条":"内置法条库";
          return '<span class="cite-lg cite-ok" title="已核实：'+escapeHtml(hit.name||"")+'（'+from+'）">✓ '+escapeHtml(short)+'</span>';
        }
        return '<span class="cite-lg cite-warn" title="未在卷宗法条与内置法条库中命中，可能为模型杜撰或库外条文，请人工核对">⚠ '+escapeHtml(short)+' · 待核对</span>';
      }
      function citeAuditHtml(text){
        const cites=extractCites(text);
        if(!cites.length||!Object.keys(knownStatutes).length) return "";
        const v=cites.filter(c=>knownStatutes[c.key]).length, u=cites.length-v;
        return '<div class="cite-audit-line">'+cites.map(citeBadge).join("")+
          (cites.length>1?'<span class="muted" style="font-size:10.5px">'+v+'/'+cites.length+' 已核实</span>':"")+
          '</div>';
      }

      /* ================= 深度思考过程可视化（<think> 折叠面板） ================= */
      function splitThink(t){
        t=String(t||"");
        let m=t.match(/<think>([\s\S]*?)(?:<\/think>|$)/i);
        if(!m) m=t.match(/<thinking>([\s\S]*?)(?:<\/thinking>|$)/i);
        if(!m) return {think:"", body:t};
        return {think:m[1].trim(), body:(t.slice(0,m.index)+t.slice(m.index+m[0].length)).trim()};
      }
      const TOOL_LABELS = { read_evidence:"查阅物证", timeline_check:"核校时间线", list_contradictions:"调取矛盾", search_case_law:"检索法条", web_search:"联网检索", cite_source:"要求举证", run_code:"Python 沙箱", install_package:"安装依赖" };
      const ALL_TOOLS = ["read_evidence","timeline_check","list_contradictions","search_case_law","web_search","cite_source","run_code"];
      const GROUP_LABELS = { investigation:"侦查阶段", trial:"庭审阶段", other:"其他" };
      let ws=null, session="", activeRole=null, currentId=null;
      let messages=[], round=0, maxRounds=3, running=false;
      let agentsCfg={}, roleMap={}, selectedCase="case_001", caseDetail=null;
      let settingsCache={}, enabledAgents=new Set();

      async function init() {
        try { settingsCache = await (await fetch("/api/settings")).json(); } catch(e){ settingsCache={}; }
        applyModelBadge();
        await applyAuthBadge();
        try { const ac = await (await fetch("/api/agent-config")).json(); ac.agents.forEach(a => agentsCfg[a.key]=a); } catch(e){ toast("加载专家配置失败"); }
        roleMap = {}; Object.values(agentsCfg).forEach(a => roleMap[a.key]=a);
        let cases = [];
        try { cases = pickCases(await (await fetch("/api/cases")).json()); } catch(e) { toast("加载案例列表失败: "+e.message); cases=[]; }
        // 标题去重：若存在同名案件，自动追加 ID 后辍以便区分
        const _titleCount={}; cases.forEach(c=>{_titleCount[c.title]=(_titleCount[c.title]||0)+1;});
        const _titleDup={}; cases.forEach(c=>{if(_titleCount[c.title]>1)_titleDup[c.id]=c.title;});
        const land = $("landCase");
        land.innerHTML="";
        cases.forEach(c => {
          const label = _titleDup[c.id] ? c.title+" ["+c.id.slice(-4)+"]" : c.title;
          const o=document.createElement("option"); o.value=c.id; o.textContent=label; land.appendChild(o);
        });
        selectedCase = cases[0]?.id || "case_001"; land.value = selectedCase;
        land.onchange = () => { selectedCase = land.value; loadCase(); };
        Object.values(agentsCfg).filter(a=>a.enabled).forEach(a => enabledAgents.add(a.key));
        renderCaseChips(cases, _titleDup);
        renderLandRoster();
        await loadCase();
      }

      function applyModelBadge() {
        const s = settingsCache||{}; const mock = s.llm_provider==="mock";
        const txt = mock ? "离线模拟" : `${s.llm_provider||"?" } · ${s.llm_model||"?"}`;
        $("modelBadge").textContent = "模型: "+txt; $("landModel").textContent = txt;
      }

      // P1-6 多用户 RBAC：展示当前用户与角色；viewer 只读门禁
      let currentRole = "admin";
      async function applyAuthBadge(){
        try{
          const me = await (await fetch("/api/auth/me")).json();
          currentRole = (me&&me.role)||"admin";
          const badge=$("userBadge");
          if(badge && me && me.auth_enabled){
            const tag = currentRole==="viewer" ? "👁 只读" : "🛡 管理员";
            badge.textContent = escapeHtml(me.user||"") + " " + tag;
            badge.style.display="";
            badge.title="当前登录角色："+tag+"（viewer 仅可浏览与参与庭审，管理设置需管理员）";
          }
          if(currentRole!=="admin") applyViewerGating();
        }catch(e){ /* 开放模式无 /api/auth/me 权限差异，保持默认 admin */ }
      }
      function applyViewerGating(){
        // viewer：隐藏管理入口（设置；案例库管理类按钮由各渲染处按角色隐藏）
        // （已移除 .btn-admin 批量隐藏：全项目无任何元素使用该类名，属死代码）
        const gs=$("btnSettings"); if(gs) gs.style.display="none";
        const gsc=$("btnSettingsChip"); if(gsc) gsc.style.display="none";
        // 修复：原实现漏了移动端底部导航的「设置」入口，
        // viewer 在窄屏下可从 #navSettings 绕过门禁直接打开设置。
        const nav=$("navSettings"); if(nav) nav.style.display="none";
        if(window._applyViewerHooks) window._applyViewerHooks();
      }

      function sortedAgents() { return Object.values(agentsCfg).slice().sort((a,b)=>a.order-b.order); }
      function isDebatable(k){ return k!=="judge" && k!=="critic"; }
      function renderCaseChips(cases, _titleDup){
        const box=$("caseChips"); if(!box) return; box.innerHTML="";
        cases.slice(0,6).forEach(c=>{ const b=document.createElement("button"); b.className="chip"; b.textContent=_titleDup&&_titleDup[c.id] ? c.title+" ["+c.id.slice(-4)+"]" : c.title; b.setAttribute("aria-label","选择案件："+b.textContent); b.onclick=()=>{ const land=$("landCase"); land.value=c.id; selectedCase=c.id; loadCase(); }; box.appendChild(b); });
        const set=document.createElement("button"); set.className="chip"+(currentRole!=="admin"?" hidden":""); set.id="btnSettingsChip"; set.textContent="⚙ 设置"; set.setAttribute("aria-label","打开设置"); set.onclick=()=>openSettings(); box.appendChild(set);
      }
      function renderLandRoster(){
        const box=$("landRoster"); if(!box) return; box.innerHTML="";
        sortedAgents().filter(a=>isDebatable(a.key)).forEach(a=>{
          const on=enabledAgents.has(a.key);
          const el=document.createElement("div"); el.className="roster-pick"+(on?"":" off");
          el.innerHTML=`<span class="ainit" style="background:${escapeHtml(a.color)}">${escapeHtml(a.name.slice(0,1))}</span><span>${escapeHtml(a.name)}</span>`;
          el.title="点击切换出庭 / 不出庭";
          el.onclick=()=>{ if(enabledAgents.has(a.key)) enabledAgents.delete(a.key); else enabledAgents.add(a.key); a.enabled=enabledAgents.has(a.key); el.classList.toggle("off",!enabledAgents.has(a.key)); };
          box.appendChild(el);
        });
      }
      function onPickCase(sel){ selectedCase=sel.value; loadCase(); }
      function hideLanding(){ $("landing").classList.add("hidden"); $("workspace").classList.remove("hidden"); }

      async function loadCase() {
        try {
          caseDetail = await (await fetch("/api/cases/"+selectedCase)).json();
          loadKnownStatutes(selectedCase); // 后台刷新法条索引（不阻塞渲染）
          renderCase();
        } catch(e) {
          toast("加载案件失败: "+e.message);
        }
      }
      async function regen(btn) {
        btn.disabled=true; const old=btn.textContent; btn.textContent="生成中…";
        try { const d=await (await fetch("/api/cases/generate",{method:"POST"})).json();
          const cases=pickCases(await (await fetch("/api/cases")).json()); const land=$("landCase"); land.innerHTML="";
          cases.forEach(c=>{const o=document.createElement("option");o.value=c.id;o.textContent=c.title;land.appendChild(o);});
          selectedCase=d.case.id; land.value=selectedCase; caseDetail=d.case; renderCase();
        } catch(e){ toast("生成失败: "+e.message); } finally { btn.disabled=false; btn.textContent=old; }
      }
      function fileToB64(file){
        return file.arrayBuffer().then(buf => {
          let s=""; const bytes=new Uint8Array(buf); for(let i=0;i<bytes.length;i++) s+=String.fromCharCode(bytes[i]); return btoa(s);
        });
      }
      async function uploadCase(evt) {
        const file = evt.target.files[0]; if(!file) return;
        const name = file.name.toLowerCase();
        if (name.endsWith(".pdf") || name.endsWith(".docx") || name.endsWith(".doc")
            || name.endsWith(".txt") || name.endsWith(".md")) { await uploadDocFile(file); evt.target.value=""; return; }
        if (/\.(png|jpe?g|webp|gif)$/.test(name)) { await uploadImageFile(file); evt.target.value=""; return; }
        try {
          const text = await file.text(); const data = JSON.parse(text);
          showPdfDropMain(false);
          await startPreprocessing(data, file.name);
        } catch(err){ toast("上传失败："+err.message); }
        evt.target.value="";
      }

      async function uploadPdfMain(evt) {
        const file = evt.target.files[0]; if(!file) return;
        await uploadDocFile(file);
        evt.target.value="";
      }
      function handlePdfDropMain(evt) { const f=evt.dataTransfer.files[0]; if(f) uploadDocFile(f); }
      function showPdfDropMain(show) { const el=$("pdfDropMain"); if(el) el.classList.toggle("hidden",!show); }

      function docFileType(name){
        const n = (name||"").toLowerCase();
        if (n.endsWith(".pdf")) return "pdf";
        if (n.endsWith(".docx")) return "docx";
        if (n.endsWith(".doc")) return "doc";
        if (n.endsWith(".png")) return "png";
        if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "jpeg";
        if (n.endsWith(".webp")) return "webp";
        return "txt";
      }
      async function uploadDocFile(file) {
        if (!file) return;
        const ext = (file.name||"").split(".").pop().toLowerCase();
        if (!["pdf","docx","doc","txt","md"].includes(ext)) { toast("请选择 PDF / DOCX / TXT 文档"); return; }
        const infoEl=$("pdfFileInfoMain");
        if(infoEl){ infoEl.innerHTML=`<span style="font-size:20px">📄</span><span class="fname">${escape(file.name)}</span><span class="fsize">${(file.size/1024).toFixed(0)} KB</span><span class="fok">✓ 已选择</span>`; infoEl.classList.remove("hidden"); }
        showPdfDropMain(false);
        const b64 = await fileToB64(file);
        await startPreprocessing({ file_type: docFileType(file.name), file_content: b64, file_name: file.name, title: file.name.replace(/\.[^.]+$/, "") }, file.name);
      }
      async function uploadImageFile(file) {
        if (!file) return;
        toast("图片将走 OCR/视觉描述识别，稍候…");
        const b64 = await fileToB64(file);
        await startPreprocessing({ file_type: docFileType(file.name), file_content: b64, file_name: file.name, title: file.name.replace(/\.[^.]+$/, "") }, file.name);
      }

      const PP_STEPS = [
        { icon:"📥", label:"文档解析", desc:"提取 PDF 文本与结构" },
        { icon:"🔍", label:"AI 意图识别", desc:"调用大模型分析案件性质" },
        { icon:"🧠", label:"思考强度评估", desc:"模型判断推理深度需求" },
        { icon:"📋", label:"专家提示词生成", desc:"模型生成总体分析指导" },
        { icon:"📦", label:"分角色材料分发", desc:"按职责为每位专家定制卷宗" },
      ];

      async function startPreprocessing(caseData, fileName) {
        showPdfDropMain && showPdfDropMain(false);
        const stage = $("ppStage"); stage.classList.remove("hidden");
        const modelName = settingsCache.intake_model || settingsCache.llm_model || "AI";
        stage.innerHTML = `<div class="pp-header"><h2>卷宗预处理</h2><p>正在分析「${escape(fileName||caseData.title||"案件")}」· 使用模型 ${escape(modelName)}</p></div><div class="pp-steps" id="ppSteps"></div>`;
        const stepsEl = $("ppSteps");
        PP_STEPS.forEach((s,i) => {
          const el=document.createElement("div"); el.className="pp-step"; el.id="ppStep"+i;
          el.innerHTML=`<div class="pp-icon"><span class="pp-icon-txt">${s.icon}</span><span class="pp-spinner"></span></div><div class="pp-body"><div class="pp-label">${s.label} <span class="pp-spinner"></span></div><div class="pp-status">${s.desc}</div></div>`;
          stepsEl.appendChild(el);
        });

        // 第1步：文档解析（客户端，几乎瞬间）
        await animateStep(0, "正在读取文件…");
        const t0=Date.now();
        if (!caseData.file_type && caseData.summary) {
          setPpStep(0,"done",`文本已解析 · ${caseData.summary.length} 字`);
        } else {
          setPpStep(0,"done",`PDF 文本提取完成 · ${(caseData.file_name||"").split(".").pop().toUpperCase()}`);
        }

        // 调用后端 AI 做真正的推理（意图识别 + 强度评估 + 提示词生成 + 材料分派全在一次性请求中完成）
        await animateStep(1, `正在调用 ${modelName} 进行深度分析…`);
        const t1=Date.now();
        let d;
        try {
          const r = await fetch("/api/cases/upload",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(caseData)});
          if(!r.ok) throw new Error("HTTP "+r.status);
          d = await r.json();
        } catch(err) {
          setPpStep(1,"error","AI 调用失败: "+err.message);
          toast("预处理失败: "+err.message); return;
        }
        const elapsed=((Date.now()-t1)/1000).toFixed(1);
        const b=d.case.brief||{};

        // 展示真实结果
        setPpStep(1,"done",`AI 分析完成 · ${elapsed}s · "${(b.intent||"").slice(0,30)}"`);

        setPpStep(2,"done",`强度: ${({low:"低",medium:"中",high:"高"}[b.reasoning_intensity]||b.reasoning_intensity||"—")}`);

        setPpStep(3,"done",`提示词已生成 · ${(b.global_guidance||"").length} 字`);

        const roleCount = b.per_role_material ? Object.keys(b.per_role_material).length : 0;
        setPpStep(4,"done",`已分发到 ${roleCount} 位专家`);
        showPreprocessingResult(d.case, fileName, elapsed);
        // 刷新案件列表
        const cases=pickCases(await(await fetch("/api/cases")).json());
        const _tc={}; cases.forEach(c=>{_tc[c.title]=(_tc[c.title]||0)+1;});
        const _td={}; cases.forEach(c=>{if(_tc[c.title]>1)_td[c.id]=c.title;});
        const land=$("landCase"); land.innerHTML="";
        cases.forEach(c=>{const o=document.createElement("option");o.value=c.id;o.textContent=_td[c.id]?c.title+" ["+c.id.slice(-4)+"]":c.title;land.appendChild(o);});
        selectedCase=d.case.id; land.value=selectedCase; caseDetail=d.case; renderCase();
      }

      function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }
      function setPpStep(i, state, statusText) {
        const el=$("ppStep"+i); if(!el) return;
        el.className="pp-step "+state;
        if(statusText) el.querySelector(".pp-status").textContent=statusText;
      }
      async function animateStep(i) {
        setPpStep(i,"active");
        await sleep(300);
        setPpStep(i,"done","完成");
      }

      async function showPreprocessingResult(c, fileName, elapsed) {
        const b = (c&&c.brief)||{};
        if(b.error){
          const stage=$("ppStage"); const header=stage.querySelector(".pp-header");
          header.innerHTML=`<h2 style="color:var(--bad)">✗ 预处理失败</h2><p>${escapeHtml(b.error)}</p><p style="margin-top:8px"><button class="ghost" onclick="location.reload()">重新上传</button></p>`;
          return;
        }
        if(!b||!b.intake_done) return;
        const stage=$("ppStage");
        const header=stage.querySelector(".pp-header");
        header.innerHTML=`<h2>✓ 卷宗分析完成</h2><p>「${escape(fileName||c.title||"")}」· AI 推理耗时 ${elapsed||"—"}s · 共 ${Object.keys(b.per_role_material||{}).length} 位专家获得材料</p>`;

        // 提取文本预览（如果有 PDF 原文）
        if(c.pdf_text) {
          const preview=c.pdf_text.slice(0,500).replace(/\n+/g,"\n");
          const txtEl=document.createElement("div"); txtEl.className="pp-result"; txtEl.style.marginTop="10px";
          txtEl.innerHTML=`<div style="margin-bottom:6px"><b>📄 提取的文本（前500字）：</b></div><pre style="white-space:pre-wrap;font-size:11.5px;color:var(--text-2);background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:8px;max-height:160px;overflow:auto;margin:0">${escape(preview)}${c.pdf_text.length>500?"…":""}</pre>`;
          stage.appendChild(txtEl);
        }

        // 意图识别结果
        let tags=(b.intent_tags||[]).map(t=>`<span style="display:inline-block;background:var(--surface-2);border:1px solid var(--line-strong);border-radius:4px;padding:1px 6px;font-size:11px;color:var(--navy);margin:2px">${escape(t)}</span>`).join("");
        const causeTxt = (b.cause || "案件审查");
        const conf = Math.round((b.cause_confidence!=null?b.cause_confidence:0.5)*100);
        const presetHint = b.suggested_preset ? `<div style="margin-top:6px"><b>🎯 建议策略：</b><span class="tchip" style="cursor:default">${escape(b.suggested_preset)}</span><span style="font-size:11px;color:var(--muted)">（可在审理前于专家配置中应用）</span></div>` : "";
        const res=document.createElement("div"); res.className="pp-result"; res.style.marginTop="10px";
        res.innerHTML=`<div style="margin-bottom:8px"><b>🔍 调查意图：</b><span id="ppIntent"></span></div>`
          +`<div style="margin-bottom:8px"><b>⚖️ 案件类型（案由推定）：</b>${escape(causeTxt)} <span style="font-size:11px;color:var(--muted)">· 置信度 ${conf}%</span></div>`
          +`${tags?`<div style="margin-bottom:8px"><b>🏷 标签：</b>${tags}</div>`:""}`
          +`<div style="margin-bottom:8px"><b>🧠 思考强度：</b>${{low:"低 · 简明推理",medium:"中 · 条理分析",high:"高 · 深度链式推理"}[b.reasoning_intensity]||b.reasoning_intensity}</div>`
          +`<div><b>📋 总体分析提示：</b><span id="ppGuidance"></span></div>${presetHint}`;
        stage.appendChild(res);
        // 文档结构摘要（表格 / OCR 页）
        if((c.tables&&c.tables.length) || (c.ocr_pages&&c.ocr_pages.length)){
          const ds=document.createElement("div"); ds.className="pp-result"; ds.style.marginTop="8px";
          const tblTxt=(c.tables||[]).slice(0,2).map(t=>`<div style="font-size:11.5px;margin:3px 0"><b>表格·第${t.page}页</b>：${(t.rows||[]).slice(0,3).map(r=>r.join(" | ")).join("；")}</div>`).join("");
          const ocrTxt=`<div style="font-size:11.5px;margin:3px 0"><b>扫描页 OCR 识别 ${(c.ocr_pages||[]).length} 页</b>（已并入待分析文本）</div>`;
          ds.innerHTML=`<b>📑 文档结构：</b>${(c.tables&&c.tables.length?`提取到 ${c.tables.length} 张表格`:"")} ${(c.ocr_pages&&c.ocr_pages.length?`· OCR ${c.ocr_pages.length} 页`:"")}${tblTxt}${ocrTxt}`;
          stage.appendChild(ds);
        }
        // 打字机
        await typewrite("ppIntent", b.intent||"未识别");
        await typewrite("ppGuidance", b.global_guidance||"请基于卷宗客观分析");

        // 分角色分发
        const pm=b.per_role_material||{}; const keys=Object.keys(pm);
        if(keys.length){
          const disp=document.createElement("div"); disp.className="pp-result"; disp.style.marginTop="8px";
          disp.innerHTML=`<div style="margin-bottom:6px"><b>📦 已分发到 ${keys.length} 位专家（每人获得差异化材料）：</b></div>`+keys.map(k=>{const a=roleMap[k]||{name:k};const snip=(pm[k]||"").replace(/\s+/g," ").slice(0,100);return`<div style="margin:4px 0;padding:6px 8px;background:var(--surface);border:1px solid var(--line);border-radius:6px"><b style="color:${a.color||'var(--navy)'}">${escape(a.name)}</b><span style="font-size:11px;color:var(--muted)"> · ${(GROUP_LABELS[a.group]||"")}</span><div style="font-size:11.5px;color:var(--text-2);margin-top:3px">${escape(snip)}…</div></div>`;}).join("");
          stage.appendChild(disp);
        }

        // 确认按钮
        const btn=document.createElement("div"); btn.className="pp-confirm";
        btn.innerHTML=`<button class="primary" onclick="confirmPreprocessing()">确认并准备开庭</button>`;
        stage.appendChild(btn);
        serverBrief=b;
        intakeOverrides={intent:b.intent||"",reasoning_intensity:b.reasoning_intensity||"medium",global_guidance:b.global_guidance||""};
      }

      async function typewrite(elId, text) {
        const el=$(elId); if(!el) return;
        el.textContent="";
        el.classList.add("pp-typewriter");
        for(let i=0;i<text.length;i++){
          el.textContent+=text[i];
          await sleep(18+Math.random()*12);
        }
        el.classList.remove("pp-typewriter");
      }

      function confirmPreprocessing() {
        $("ppStage").classList.add("hidden");
        renderIntake();
        $("intakeCard").classList.remove("hidden");
        toast("预处理完成，请确认后点击「开庭审理」");
      }

      function toggleCaseSum(){
        const box = $("caseSumBox");
        const full = window.__caseSummaryFull || "";
        const open = box.dataset.open === "1";
        if (open) {
          box.innerHTML = escapeHtml(full.slice(0,360)) + "…" +
            '<button class="linkbtn" style="border:0;background:none;padding:0;font-size:11.5px" onclick="toggleCaseSum()"> 展开全文</button>';
          box.dataset.open = "0";
        } else {
          box.innerHTML = escapeHtml(full) +
            '<button class="linkbtn" style="border:0;background:none;padding:0;font-size:11.5px" onclick="toggleCaseSum()"> 收起</button>';
          box.dataset.open = "1";
        }
      }
      function renderCase() {
        const d=caseDetail; if(!d){ $("casePanel").innerHTML='<div class="muted">加载案件中…</div>'; return; }
        const e=escapeHtml;
        const sumFull = d.summary||"";
        window.__caseSummaryFull = sumFull;
      const sumShort = sumFull.length>360 ? sumFull.slice(0,360)+"…" : sumFull;
      const aiTag = d.ai_extracted ? '<span class="ai-tag" title="结构化字段（人员/证据/时间线/法条）由 AI 从文档自动提取">✨ AI 自动提取</span>' : "";
      const sumBtn = sumFull.length>360 ? '<button class="linkbtn" style="border:0;background:none;padding:0;font-size:11.5px" onclick="toggleCaseSum()"> 展开全文</button>' : "";
      let h=`<div class="card"><div class="case-head"><div class="case-no">案号 ${d.id?("〔2026〕"+e(d.id.toUpperCase())):"—"}</div><div class="case-title">${e(d.title)} ${aiTag}</div><div class="muted" id="caseSumBox">${e(sumShort)}${sumBtn}</div></div>`;
        if(d.persons&&d.persons.length){ h+='<div class="sec-title">涉案人员</div>'; d.persons.forEach(p=>{ h+=`<div class="person"><div><div><span class="pname">${e(p.name)}</span> <span class="prole">${e(p.role)}</span></div><div class="pdesc">${e(p.desc||"")}</div></div></div>`; }); }
        if(d.evidence&&d.evidence.length){ h+='<div class="sec-title">证据清单 <button class="ghost" style="float:right;font-size:10.5px;padding:2px 8px" onclick="auditEvidence()" aria-label="一键核验证据">🔍 一键核验</button></div><div id="evAudit"></div>'; d.evidence.forEach(ev=>{ const col=ev.chain_intact?"var(--ok)":"var(--bad)"; h+=`<div class="evi"><div class="evi-top"><span class="evi-id">${e(ev.id)}</span><span class="evi-type">${e(ev.type)}</span></div><div class="evi-desc">${e(ev.desc)}</div><div class="bar"><div style="width:${(ev.reliability||0)*100}%"></div></div><span class="chain ${ev.chain_intact?'ok':'no'}">${ev.chain_intact?'● 保管链完整':'● 保管链瑕疵'} · 可靠性 ${((ev.reliability||0)*100).toFixed(0)}%</span></div>`; }); }
        if(d.contradictions&&d.contradictions.length){ h+='<div class="sec-title">争议焦点 <span class="muted" style="font-weight:400">（卷宗预梳理 · MetaLaw 式焦点先行）</span></div>'; d.contradictions.forEach(c=>{ h+=`<div class="focus-item"><span class="focus-id">${e(c.id||"焦点")}</span><div class="focus-body"><div class="focus-desc">${e(c.desc||c.issue||"")}</div>${c.impact?`<div class="focus-impact">🎯 影响：${e(c.impact)}</div>`:""}</div></div>`; }); }
        if(d.statutes&&d.statutes.length){ h+='<div class="sec-title">法条依据</div>'; d.statutes.forEach(s=>{ h+=`<div class="statute"><div class="st-topic">${e(s.name||s.topic)}</div><div class="st-text">${e(s.text)}</div></div>`; }); }
        if(d.timeline&&d.timeline.length){ h+='<div class="sec-title">关键时间线</div><div class="tl">'; d.timeline.forEach(t=>{ h+=`<div class="tl-item"><div class="tl-time">${e(t.time)}</div><div class="tl-ev">${e(t.event)}</div><div class="tl-src">来源：${e(t.source||"—")}</div></div>`; }); h+='</div>'; }
        h+='<div class="sec-title">现场勘验图表</div>';
        const charts=d.charts||{};
        const chartItems=Object.entries(charts);
        if(chartItems.length){ chartItems.forEach(([label,url])=>{ h+=`<div class="muted" style="font-size:11px;margin:0 0 4px">${escapeHtml(label)}</div><img class="chart" src="${escapeHtml(url)}" alt="${escapeHtml(label)}" loading="lazy" decoding="async" onerror="this.style.display='none'">`; }); }
        else { h+='<div class="muted">暂无足够数据生成图表（需要证据/时间线/通讯/资金等结构化字段）。</div>'; }
        h+='</div>'; $("casePanel").innerHTML=h; renderRoster(); renderIntake();
      }

      function renderIntake(){
        const b = (caseDetail && caseDetail.brief) || {};
        const card = $("intakeCard"); if(!card) return;
        if(!b || !b.intake_done){ card.classList.add("hidden"); return; }
        card.classList.remove("hidden");
        $("ivIntent").value = intakeOverrides.intent || b.intent || "";
        $("ivIntensity").value = intakeOverrides.reasoning_intensity || b.reasoning_intensity || "medium";
        $("ivGuidance").value = intakeOverrides.global_guidance || b.global_guidance || "";
        $("ivJudge").value = (settingsCache && settingsCache.judge_mode) || "ai";
        onIntake();
        renderDispatchPreview(b);
      }
      function onIntake(){ intakeOverrides = { intent:$("ivIntent").value.trim(), reasoning_intensity:$("ivIntensity").value, global_guidance:$("ivGuidance").value.trim() }; }
      function intakePayload(){ const p={}; if(intakeOverrides.intent) p.intent=intakeOverrides.intent; if(intakeOverrides.reasoning_intensity) p.reasoning_intensity=intakeOverrides.reasoning_intensity; if(intakeOverrides.global_guidance) p.global_guidance=intakeOverrides.global_guidance; const j=$("ivJudge").value; if(j) p.judge_mode=j; if(enabledAgents.size) p.agents=Array.from(enabledAgents); return p; }
      function renderRoster() {
        const box=$("roster"); box.innerHTML="";
        sortedAgents().forEach(a => {
          const st = a.key===activeRole ? "speaking" : (running && a.key!==activeRole && messages.some(m=>m.role===a.key) ? "done":"");
          const stTxt = st==="speaking"?"举证中":st==="done"?"已陈述":"待席";
          const tools=(a.tools||[]).map(t=>`<span class="tchip">${TOOL_LABELS[t]||t}</span>`).join("");
          const el=document.createElement("div"); el.className="agent-row"+(st==="speaking"?" speaking":""); el.style.borderLeftColor=a.color;
          el.innerHTML=`<div class="ar-top"><div class="ainit" style="background:${escapeHtml(a.color)}">${escapeHtml(a.name.slice(0,1))}</div><div style="flex:1;min-width:0"><div class="an">${escapeHtml(a.name)}</div><div class="ad">${escapeHtml(a.duty)}</div></div><span class="astatus ${st}">${stTxt}</span></div><div class="tools">${tools}</div><details class="strategy"><summary>查看策略</summary><pre>${escapeHtml(a.system_prompt||a.default_prompt||a.stance)}</pre></details>`;
          box.appendChild(el);
        });
      }

      function setPhase(t){ const map={idle:["待命","var(--muted)"],running:["审理进行中","var(--seal)"],verdict:["裁决形成中","var(--gold)"],review:["等待人类复核","var(--gold)"],done:["审理终结","var(--ok)"]}; const [txt,c]=map[t]||[t,"var(--muted)"]; $("phase").textContent=txt; $("phase").style.color=c; updateStepper(t); }
      function updateStepper(t){
        const order=["open","debate","verdict","done"];
        const cur = t==="idle"?"open" : t==="running"?"debate" : (t==="verdict"||t==="review")?"verdict" : "done";
        const idx = order.indexOf(cur);
        document.querySelectorAll("#stepper span").forEach(el=>{
          const i = order.indexOf(el.dataset.s);
          el.classList.toggle("on", i===idx);
          el.classList.toggle("done", i<idx);
        });
      }
      function goHome(){
        manualClose = true; try{ if(ws && ws.readyState<=1) ws.close(); }catch(e){}
        running=false; $("landStart").disabled=false;
        $("workspace").classList.add("hidden");
        $("landing").classList.remove("hidden");
        setConn("off"); hideBanner(); reset();
        toast("已返回案件受理，可选择案件重新开庭");
      }
      function setConn(s){ const dot=$("connDot"),txt=$("connText"); dot.className="dot"+(s==="on"?" on":s==="busy"?" busy":""); txt.textContent=s==="on"?"已连接":s==="busy"?"连接中":"未连接"; }
      function setSpeak(t, live){ const el=$("speak"); el.innerHTML=(live?'<span class="live-dot"></span>':"")+escapeHtml(t||""); }
      function toggleRail(side){ const m=$("workspace"); if(side==="left"){ m.classList.toggle("no-left"); $("btnLeft").textContent=m.classList.contains("no-left")?"案卷 ›":"案卷 ‹"; } else { m.classList.toggle("no-right"); $("btnRight").textContent=m.classList.contains("no-right")?"‹ 合议":"› 合议"; } }
      function isMobile(){ return window.innerWidth <= 768; }
      function toggleMobilePanel(side){
        const m=$("workspace");
        if(side==="center"){ closeMobilePanels(); return; }
        const cls = side==="left"?"show-left":"show-right";
        const other = side==="left"?"show-right":"show-left";
        m.classList.remove(other);
        m.classList.toggle(cls);
        // 更新底部导航高亮
        document.querySelectorAll(".mobile-nav button").forEach(b=>b.classList.remove("active"));
        if(m.classList.contains(cls)){
          $("nav"+(side==="left"?"Left":"Right")).classList.add("active");
        } else {
          $("navCenter").classList.add("active");
        }
      }
      function closeMobilePanels(){
        const m=$("workspace");
        m.classList.remove("show-left","show-right");
        document.querySelectorAll(".mobile-nav button").forEach(b=>b.classList.remove("active"));
        $("navCenter").classList.add("active");
      }
      let _ipvTimer=null;
      async function loadUsage(){
        const box=$("usageCard"); if(!box) return;
        try{
          const d=await (await fetch("/api/admin/usage")).json();
          const fmt=n=>n>=1e4?(n/1e4).toFixed(1)+"万":n;
          box.innerHTML=`<div class="uc-grid"><div class="uc"><b>${d.sessions||0}</b><span>场审理</span></div><div class="uc"><b>${fmt(d.calls||0)}</b><span>模型调用</span></div><div class="uc"><b>${fmt(d.out_chars||0)}</b><span>输出字符</span></div><div class="uc"><b>${d.audit_entries||0}</b><span>审计条目</span></div></div>`+
            ((d.recent||[]).length?`<div class="uc-recent muted">最近：${d.recent.slice(0,3).map(r=>`<span title="${escapeHtml(r.case_title||"")}">${escapeHtml((r.case_title||r.session_id||"").slice(0,12))}·${r.calls}次</span>`).join("　")}</div>`:"")+
            `<div class="muted" style="font-size:10.5px;margin-top:6px">（${d.audit_enabled?"审计记录中":"审计未开启（AUDIT_PROMPTS=false）"}）</div>`;
        }catch(e){ box.innerHTML=`<div class="muted">用量统计加载失败：${escape(e.message)}</div>`; }
      }
      function startVoiceInput(){
        const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
        const hint=$("voiceHint");
        if(!SR){ hint.textContent="当前浏览器不支持 Web Speech API（建议 Chrome/Edge）"; return; }
        try{
          const rec=new SR(); rec.lang="zh-CN"; rec.interimResults=false; rec.maxAlternatives=1;
          rec.onstart=()=>{ hint.textContent="正在聆听…点击并出声描述案情"; };
          rec.onresult=(ev)=>{ const t=ev.results[0][0].transcript||""; const box=$("landQuery"); if(box) box.value=t; onIntentPreview(); hint.textContent="已识别："+t.slice(0,30); };
          rec.onerror=(ev)=>{ hint.textContent="语音识别失败："+(ev.error||"未知错误")+"（请允许麦克风权限）"; };
          rec.onend=()=>{ if((hint.textContent||"").includes("正在聆听")) hint.textContent=""; };
          rec.start();
        }catch(e){ hint.textContent="语音识别不可用："+e.message; }
      }
      function renderReflex(){
        const box=$("reflexBox"); if(!box) return;
        const r=window._reflections||[];
        if(!r.length){ box.classList.add("hidden"); return; }
        box.classList.remove("hidden");
        box.innerHTML=`<div class="reflex"><div class="reflex-t">可证伪性审查（裁决前反思）<span class="muted" style="font-weight:400">——每项主张均须接受反证检验</span></div>`+
          r.map(x=>{ const nm=x.role==="critic"?"纠错官":((roleMap[x.role]||{}).name||x.role); return `<div class="reflex-item"><b>${escapeHtml(nm)}</b><span class="reflex-subj">${escapeHtml(String(x.subject||"").slice(0,60))}</span><div class="reflex-o">↳ 待核验：${escapeHtml(x.objection||"")}</div></div>`; }).join("")+
          `</div>`;
      }
      function renderTrace(){
        const box=$("traceBox"); if(!box) return;
        const tr=lastTrace||{}; const spans=(tr.spans||[]);
        if(!spans.length){ box.classList.add("hidden"); return; }
        box.classList.remove("hidden");
        const LABEL={round:"专家发言轮",critic:"矛盾纠错",reflect:"可证伪性审查",judge:"审判长裁决",human:"人类落槌"};
        const rows=spans.map(s=>{
          const kind=String(s.kind||"");
          const label=(kind==="round"?"第 "+String(s.span.split("|")[1])+" 轮 · ":LABEL[kind]||kind+" · ")+(kind==="round"?"专家发言":"");
          const us=s.usage||{}; const lu=us.calls?" · "+us.calls+" 次推理":"";
          return `<div class="tr-row"><span class="tr-k">${escapeHtml(label)}</span><span class="tr-bar" style="width:${Math.min(100,Math.max(4,(s.ms||0)/(tr.total_ms||1)*100))}%"></span><span class="tr-ms">${Math.round(s.ms||0)}ms${lu}</span></div>`;
        }).join("");
        box.innerHTML=`<div class="trace">`+
          `<div class="trace-t">会话时间线 <span class="muted" style="font-weight:400">——各审判节点耗时与调用量，总 ${((tr.total_ms||0)/1000).toFixed(1)}s</span></div>`+
          rows+`</div>`;
      }
      function renderIvPlan(){
        const box=$("ivPlan"); if(!box) return;
        const plan=(serverBrief&&serverBrief.investigation_plan)||[];
        if(!plan.length){ box.classList.add("hidden"); return; }
        box.classList.remove("hidden");
        box.innerHTML=`<div class="iv-plan"><div class="ip-t">侦查计划 · 待证问题清单</div>`+plan.map(p=>`<div class="ip-i">☐ ${escapeHtml(String(p))}</div>`).join("")+`</div>`;
      }
      async function onIntentPreview(){
        const q=(((()=>{try{return ($("landQuery")||{}).value||""}catch(e){return ""}})()||"")).trim();
        const box=$("intentPreview"); if(!box) return;
        if(q.length<4){ box.classList.add("hidden"); return; }
        clearTimeout(_ipvTimer);
        _ipvTimer=setTimeout(async ()=>{
          try{
            const d=await (await fetch("/api/intent/preview?text="+encodeURIComponent(q))).json();
            box.classList.remove("hidden");
            if(d.relevant===false){ box.innerHTML='<div class="ipv ipv-bad">⚠ '+escapeHtml(d.reject_reason||"输入无法识别为案件描述")+'</div>'; return; }
            const ent=d.entities||{};
            const chips=(k)=>(ent[k]||[]).slice(0,4).map(x=>'<span class="ipv-chip">'+escapeHtml(x)+'</span>').join("");
            const conf=Math.round((d.confidence||0)*100);
            const extraCauses=((d.causes||[]).filter(c=>c.cause!==d.cause).slice(0,3)||[]);
            box.innerHTML='<div class="ipv ipv-ok">'+
              '<span class="ipv-tag">案由</span><span class="ipv-val">'+escapeHtml(d.cause||"案件审查")+'</span>'+
              (extraCauses.length?'<div class="ipv-chips" style="flex-basis:100%"><b>涉及案由</b>'+extraCauses.map(c=>'<span class="ipv-chip">'+escapeHtml(c.cause)+'</span>').join("")+'</div>':"")+
              '<span class="ipv-tag">置信度</span><span class="ipv-val">'+conf+'%</span>'+
              (d.suggested_preset?'<span class="ipv-tag">预设</span><span class="ipv-val">'+escapeHtml(d.suggested_preset)+'</span>':"")+
              (chips("parties")?'<div class="ipv-chips"><b>当事人</b>'+chips("parties")+'</div>':"")+
              (chips("datetimes")?'<div class="ipv-chips"><b>时间</b>'+chips("datetimes")+'</div>':"")+
              (chips("amounts")?'<div class="ipv-chips"><b>金额</b>'+chips("amounts")+'</div>':"")+
              (chips("places")?'<div class="ipv-chips"><b>地点</b>'+chips("places")+'</div>':"")+
              '</div>';
          }catch(e){ box.classList.add("hidden"); }
        }, 450);
      }
      async function landStart(){
        if(enabledAgents.size===0){ toast("请先在设置中至少选择一位出庭专家"); return; }
        // 粘贴文本开庭：填了案情文字就以粘贴内容新建案件——
        // 明确输入的新案情优先于下拉里被动选中的旧案件（此前该输入框从未被读取）
        const pasted=($("landQuery")&&$("landQuery").value||"").trim();
        if(!selectedCase && !pasted){ toast("请先选择案件，或在文本框粘贴案情后再开庭"); return; }
        if(pasted){
          $("landStart").disabled=true;
          try{
            const r=await fetch("/api/cases/upload",{method:"POST",headers:{"Content-Type":"application/json"},
              body:JSON.stringify({title:pasted.split(/[。\n]/)[0].slice(0,24)||"粘贴案件", summary:pasted.slice(0,2000)})});
            const d=await r.json();
            if(d.case){ selectedCase=d.case.id; caseDetail=d.case; $("landQuery").value=""; if(typeof refreshCaseLibrary==="function") refreshCaseLibrary(); }
            else { toast("建案失败："+(d.error||"未知错误")); return; }
          }catch(e){ toast("建案失败："+e.message); return; }
          finally{ $("landStart").disabled=false; }
        }
        applyMode();
        // 将落地页的预处理结果同步到工作区
        const b = (caseDetail && caseDetail.brief) || {};
        if(b && b.intake_done) {
          $("ivIntent").value = intakeOverrides.intent || b.intent || "";
          $("ivIntensity").value = intakeOverrides.reasoning_intensity || b.reasoning_intensity || "medium";
          $("ivGuidance").value = intakeOverrides.global_guidance || b.global_guidance || "";
          $("ivJudge").value = (settingsCache && settingsCache.judge_mode) || "ai";
          renderDispatchPreview(b);
        }
        $("landing").classList.add("hidden");
        $("workspace").classList.remove("hidden");
        start();
      }
      function applyMode(){
        const m=$("ivMode").value; const iv=$("intervene");
        if(m==="observe"){ iv.classList.add("hidden"); $("ivJudge").value="ai"; }
        else if(m==="intervene"){ iv.classList.remove("hidden"); $("ivJudge").value="ai"; }
        else if(m==="collaborate"){ iv.classList.remove("hidden"); $("ivJudge").value="human"; }
      }
      function renderDispatchPreview(b) {
        const disp=$("ivDispatch"); if(!disp) return; disp.innerHTML="";
        const pm=b.per_role_material||{};
        Object.keys(pm).forEach(k=>{
          const a=roleMap[k]||{name:k,group:""};
          const snip=(pm[k]||"").replace(/\s+/g," ").slice(0,140);
          const el=document.createElement("div"); el.className="dp";
          el.innerHTML=`<b>${escape(a.name)}</b><span> · ${(GROUP_LABELS[a.group]||"")}</span><br><span>${escape(snip)}…</span>`;
          disp.appendChild(el);
        });
      }
      let wsRetries=0; let manualClose=false; let resumeMode=false; window._replaying=false;
      function showBanner(t){ const b=$("connBanner"); if(b){ b.textContent=t; b.style.display="block"; } }
      function hideBanner(){ const b=$("connBanner"); if(b) b.style.display="none"; }
      function doConnect(resume=false){
        reset(); running=true; wsRetries++; $("landStart").disabled=true;
        if(!resume) session=Math.random().toString(36).slice(2);
        resumeMode=resume;
        const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
        ws=new WebSocket(`${wsProto}//${location.host}/ws/${session}`);
        ws.onopen=()=>{
          setConn("on"); hideBanner();
          ws.send(JSON.stringify(resume ? {type:"resume"} : Object.assign({type:"start",case_id:selectedCase}, intakePayload())));
          if(resume){
            // 服务端无该会话缓冲（如服务重启）→ 提示重新开庭而不是停在空屏
            setTimeout(()=>{ if(!messages.length && !document.querySelector(".closure-card")){ showBanner("该场审理的实时数据已不可恢复，请重新开庭。"); running=false; $("landStart").disabled=false; } }, 1800);
          }
        };
        ws.onclose=()=>{ setConn("off"); const _sb5=$("btnStop"); if(_sb5) _sb5.style.display="none"; if(!manualClose && running){ showBanner("连接已断开。<button onclick=\"retryConnect()\" style='margin-left:8px;padding:3px 10px;border-radius:4px;border:none;background:#f6efdd;color:#b03a2e;cursor:pointer;font-weight:600'>接续观看</button>"); running=false; $("landStart").disabled=false; } else if(!manualClose){ showBanner("连接失败，请刷新页面重试。"); } };
        ws.onerror=()=>{ setConn("off"); console.error("WebSocket error"); };
        ws.onmessage=(e)=>{ try { handle(JSON.parse(e.data)); } catch(err) { console.error("WS parse error:", err); } };
      }
      function start(){ if(running) return; wsRetries=0; manualClose=false; doConnect(false); }
      async function stopDebate(){
        if(!running || !ws){ return; }
        if(!await confirmDialog("确定要停止当前辩论吗？已生成的发言和裁决将保留。")){ return; }
        try{ ws.send(JSON.stringify({type:"stop"})); }catch(e){}
        manualClose=true;
        try{ ws.close(); }catch(e){}
        running=false;
        $("landStart").disabled=false;
        const btn=$("btnStop"); if(btn) btn.style.display="none";
        $("intervene").classList.add("hidden");
        $("ivChips").classList.add("hidden");
        setPhase("done");
        setSpeak("辩论已由用户停止", false);
        toast("辩论已停止");
      }
      async function retryConnect(){
        hideBanner();
        // 重连改为接续观看：服务端补发历史事件快照，辩论绝不重启
        wsRetries=0; manualClose=false; doConnect(true);
      }
      function reset(){ messages=[]; activeRole=null; currentId=null; round=0; serverBrief=null; lastVerdict=null; contraList=[]; recNotes=[]; qaHistory=[]; nsDone=new Set(); $("debate").innerHTML='<div class="empty">⚖️ 准备就绪，等待开庭。</div>'; $("contra").innerHTML='<div class="muted">尚未记录矛盾点。</div>'; $("recording").innerHTML='<div class="muted">辩论开始后，各专家主张将实时记录于此。</div>'; $("verdictBox").innerHTML=""; $("verdictTools").classList.add("hidden"); $("nextSteps").classList.add("hidden"); $("qaBox").classList.add("hidden"); const _jb=$("jumpBottom"); if(_jb) _jb.classList.add("hidden"); $("hitl").innerHTML=""; $("prog").style.width="0%"; setSpeak("", false); $("intervene").classList.add("hidden"); $("ivChips").classList.add("hidden"); $("dlReport").classList.add("hidden"); setPhase("idle"); renderRoster(); }
      function handle(ev){
        switch(ev.kind){
          case "batch": { /* 断线重连水合：一次性重放历史事件，抑制 toast，最后统一渲染 */ window._replaying=true; try{ (ev.events||[]).forEach(x=>{ if(x.kind!=="batch") handle(x); }); } finally { window._replaying=false; } renderDebate(); break; }
           case "session_start": setPhase("running"); $("intervene").classList.remove("hidden"); $("ivChips").classList.remove("hidden"); const _sb=$("btnStop"); if(_sb) _sb.style.display=""; if(!messages.length){ $("debate").innerHTML='<div class="thread"><div class="skeleton"><div class="sk-ava"></div><div class="sk-body"><div class="sk-line"></div><div class="sk-line"></div><div class="sk-line"></div></div></div><div style="text-align:center;color:var(--faint);font-size:12px;margin-top:8px">专家们正在阅卷、准备首轮举证…</div></div>'; } break;
          case "intake": serverBrief={intent:ev.intent,intent_tags:ev.intent_tags,reasoning_intensity:ev.reasoning_intensity,global_guidance:ev.global_guidance,summary:ev.summary,investigation_plan:ev.investigation_plan||[]}; renderIvPlan(); break;
          case "human_inject": { const id="human-"+Date.now(); messages.push({id, role:"human", name:"人类法官介入", color:"#8a6d3b", stance:"", text:ev.text, tools:[], done:true, time:Date.now()}); renderDebate(); break; }
          case "round_start": round=ev.round; maxRounds=ev.max_rounds||3; activeRole=null; $("prog").style.width=((round-1)/maxRounds*100)+"%"; renderRoster(); break;
          case "agent_start": { const mid=ev.id||(ev.role+"-"+round); currentId=mid; activeRole=ev.role; setSpeak(ev.name+" 正在举证", true); const color=(roleMap[ev.role]||{}).color||"#1f3a5f"; const a=roleMap[ev.role]||{}; messages.push({id:mid,role:ev.role,name:ev.name,color,stance:a.stance,text:"",tools:[],done:false,time:Date.now()}); renderDebate(); renderRoster(); break; }
          case "token": { const m=messages.find(x=>x.id===ev.id); if(m) m.text+=ev.text; scheduleRender(); } break;
          case "tool": { const m=messages.find(x=>x.id===ev.id); if(m) m.tools.push({tool:ev.tool,args:ev.args,result:ev.result}); renderDebate(); } break;
          case "agent_end": { const m=messages.find(x=>x.id===ev.id); if(m) m.done=true; renderDebate(); renderRoster(); break; }
          case "round_end": $("prog").style.width=(round/maxRounds*100)+"%"; break;
            case "critic_start": setSpeak("纠错官 正在比对各方主张、梳理矛盾", true); break;
            case "critic_end": (ev.contradictions||[]).forEach(c=>addContra(c)); break;
            case "judge_start": setPhase("verdict"); setSpeak("审判长 正在综合全案、形成裁决", true); break;
            case "agent_note": addRecording(ev.role, ev.name, ev.note||{}); break;
          case "citations": { const _mc=messages.find(x=>x.id===ev.id); if(_mc){ _mc.citations=(ev.citations||[]).slice(0,8); renderDebate(); } break; }
          case "reflect": window._reflections=(ev.reflections||[]); renderReflex(); break;
          case "selfcheck": window._selfcheck=(ev.selfcheck||null); if(lastVerdict) renderVerdict(lastVerdict); break;
          case "verdict": setPhase("verdict"); lastVerdict=ev.verdict; renderVerdict(ev.verdict); $("dlReport").classList.remove("hidden"); break;
          case "awaiting_human": setPhase("review"); renderHitl(ev.draft||null, ev.final); break;
          case "human_reminder": setPhase("review"); break;
          case "judge_end": setSpeak(ev.consensus ? "审判长已落槌，裁决达成" : "未达成完全共识，转入人类法官复核", false); break;
          case "human_done": setPhase("running"); $("hitl").innerHTML=""; break;
          case "human_timeout": { toast("⏱ " + (ev.message||"落槌超时，已采纳 AI 草案")); const id="to-"+Date.now(); messages.push({id, role:"system", name:"超时归档", color:"#b45309", stance:"", text:(ev.message||"")+"\n\n如需人工重新裁决，可在复盘记录中重新开庭。", tools:[], done:true}); renderDebate(); break; }
          case "usage": lastUsage=ev.usage||null; break;
          case "trace": lastTrace=ev||null; renderTrace(); break;
          case "done": setPhase("done"); running=false; $("landStart").disabled=false; $("intervene").classList.add("hidden"); $("ivChips").classList.add("hidden"); const _sb2=$("btnStop"); if(_sb2) _sb2.style.display="none"; if(lastUsage&&lastUsage.calls){ const _in=Math.round((lastUsage.in_chars||0)/1000), _out=Math.round((lastUsage.out_chars||0)/1000); setSpeak("本次审理共推理 "+lastUsage.calls+" 次，读取 "+_in+"k 字、产出 "+_out+"k 字"); } appendClosureCard(); toast("✅ 审理终结 · 裁决已归档，可导出结案报告"); break;
          case "stopped": running=false; $("landStart").disabled=false; $("intervene").classList.add("hidden"); $("ivChips").classList.add("hidden"); const _sb3=$("btnStop"); if(_sb3) _sb3.style.display="none"; setSpeak(ev.message||"辩论已停止", false); break;
          case "error": { running=false; $("landStart").disabled=false; $("intervene").classList.add("hidden"); const _sb4=$("btnStop"); if(_sb4) _sb4.style.display="none"; setPhase("done"); const id="err-"+Date.now(); messages.push({id, role:"system", name:"系统错误", color:"#ef4444", stance:"", text:"辩论中断："+(ev.message||"未知错误")+"\n\n建议：检查模型是否可用 / API 是否限流，或改用更稳定的模型（设置→审理引擎）。", tools:[], done:true}); renderDebate(); break; }
        }
      }
      function cleanText(s){
        s = (s||"");
        s = s.replace(/<think>[\s\S]*?<\/think>/gi,"").replace(/<thinking[\s\S]*?<\/thinking>/gi,"");
        s = s.replace(/\n{3,}/g,"\n\n");
        // 按标点补软换行，保证渲染时一行一句；但跳过代码块与 markdown 表格行，避免破坏结构。
        const lines = s.split("\n");
        const sep = /^\s*\|?[\s:|-]+\|?\s*$/;
        let inCode = false;
        const out = [];
        for (let i = 0; i < lines.length; i++) {
          const line = lines[i];
          if (/^```/.test(line.trim())) { inCode = !inCode; out.push(line); continue; }
          if (inCode) { out.push(line); continue; }
          const prev = lines[i - 1] || "", next = lines[i + 1] || "";
          const isTableLine = line.includes("|") && (sep.test(prev.trim()) || sep.test(next.trim()));
          if (isTableLine) { out.push(line); continue; }
          out.push(line.replace(/([。！？；])(?![\n\s)】」』」’"])([^。！？；\n]{2,})/g, "$1\n$2"));
        }
        return out.join("\n").trim();
      }
      function escapeHtml(s){
        return String(s==null?"":s)
          .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
          .replace(/"/g,"&quot;").replace(/'/g,"&#39;");
      }
      function inlineMd(s){
        // 先把图片/链接提取为占位符，避免 URL 中的下划线被斜体规则改写
        // （如 /sandbox/evidence_reliability_1.png 会变成 evidence<em>reliability</em>_1.png 导致图片 404）
        const stash = [];
        const keep = (html) => "\u0000" + (stash.push(html) - 1) + "\u0000";
        s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m,a,u)=>keep('<img src="'+u+'" alt="'+a+'" loading="lazy" decoding="async" />'));
        s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (m,t,u)=>keep('<a href="'+u+'" target="_blank" rel="noopener">'+t+"</a>"));
        s = s.replace(/`([^`]+)`/g, (m,c)=>keep("<code>"+c+"</code>"));
        s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
        s = s.replace(/__([^_]+)__/g, "<strong>$1</strong>");
        s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
        s = s.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
        s = s.replace(/\u0000(\d+)\u0000/g, (m,i)=>stash[+i]);
        return s;
      }
      function splitRow(line){ return line.trim().replace(/^\|/,"").replace(/\|$/,"").split("|").map(c=>c.trim()); }
      function mdToHtml(src){
        src = cleanText(src);
        const lines = src.split(/\n/);
        let html = "", para = [], i = 0;
        const flush = () => { if(para.length){ html += "<p>"+para.map(l=>inlineMd(escapeHtml(l))).join("<br>")+"</p>"; para = []; } };
        while(i < lines.length){
          const line = lines[i];
          if(/^```/.test(line.trim())){
            flush(); const code = []; i++;
            while(i < lines.length && !/^```/.test(lines[i].trim())){ code.push(lines[i]); i++; }
            i++;
            html += "<pre><code>"+escapeHtml(code.join("\n"))+"</code></pre>"; continue;
          }
          if(/^\s*([-*_])\1{2,}\s*$/.test(line)){ flush(); html += "<hr>"; i++; continue; }
          const h = line.match(/^(#{1,6})\s+(.*)$/);
          if(h){ flush(); const l=h[1].length; html += "<h"+l+">"+inlineMd(escapeHtml(h[2]))+"</h"+l+">"; i++; continue; }
          if(/^>\s?/.test(line)){
            flush(); const q = [];
            while(i < lines.length && /^>\s?/.test(lines[i])){ q.push(lines[i].replace(/^>\s?/,"")); i++; }
            html += "<blockquote>"+mdToHtml(q.join("\n"))+"</blockquote>"; continue;
          }
          if(line.includes("|") && i+1 < lines.length && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i+1]) && lines[i+1].includes("-")){
            flush();
            const header = splitRow(line);
            const aligns = splitRow(lines[i+1]).map(c=> (c.startsWith(":")&&c.endsWith(":"))?"center":c.endsWith(":")?"left":c.startsWith(":")?"right":"");
            i += 2; const rows = [];
            while(i < lines.length && lines[i].includes("|") && lines[i].trim()!==""){ rows.push(splitRow(lines[i])); i++; }
            let t = "<table><thead><tr>"+header.map((c,j)=>'<th style="text-align:'+(aligns[j]||"left")+'">'+inlineMd(escapeHtml(c))+"</th>").join("")+"</tr></thead><tbody>";
            t += rows.map(r=>"<tr>"+r.map((c,j)=>'<td style="text-align:'+(aligns[j]||"left")+'">'+inlineMd(escapeHtml(c))+"</td>").join("")+"</tr>").join("")+"</tbody></table>";
            html += t; continue;
          }
          if(/^\s*([-*+])\s+/.test(line) || /^\s*\d+\.\s+/.test(line)){
            flush(); const items = []; const ordered = /^\s*\d+\.\s+/.test(line);
            while(i < lines.length && (/^\s*([-*+])\s+/.test(lines[i]) || /^\s*\d+\.\s+/.test(lines[i]))){
              const m = lines[i].match(/^\s*(?:[-*+]|\d+\.)\s+(.*)$/); items.push(inlineMd(escapeHtml(m[1]))); i++;
            }
            html += (ordered?"<ol>":"<ul>")+items.map(it=>"<li>"+it+"</li>").join("")+(ordered?"</ol>":"</ul>"); continue;
          }
          if(line.trim()===""){ flush(); i++; continue; }
          para.push(line); i++;
        }
        flush();
        return html;
      }
      function renderMarkdown(s){ return mdToHtml(s); }
      function renderSandbox(s){
        const raw = s || "";
        const parts = raw.split(/(\[stderr\]|\[exit code \d+\])/g);
        return parts.map(p => {
          if (p === "[stderr]") return '<div class="sb-err-h">⚠ 标准错误（stderr）</div>';
          if (/^\[exit code \d+\]$/.test(p)) return '<div class="sb-err-h">'+escapeHtml(p)+'</div>';
          if (!p) return "";
          const isErr = /Traceback \(|Error:|Exception|exit code/.test(p);
          return '<div class="'+(isErr?"sb-err":"")+'">'+renderMarkdown(p)+"</div>";
        }).join("");
      }
      let _renderQueued = false;
      let _lastRenderSig = "";
      function _msgSig(){ let s=messages.length+""; for(const m of messages) s+="|"+m.id+":"+(m.done?"1":"0")+":"+(m.tools?m.tools.length:0); return s; }
      function _patchLastMessage(){ // 增量快路径：仅最后一条发言在流式变化时，只重绘它的正文
        const m = messages[messages.length-1];
        if(!m || m.done) return false;
        const nodes = document.querySelectorAll("#debate .rec");
        const last = nodes[nodes.length-1];
        if(!last) return false;
        const rt = last.querySelector(".rtext");
        if(!rt) return false;
        const sp = (m.text||"").includes("<th") ? splitThink(m.text) : {think:"", body:m.text};
        rt.innerHTML = renderMarkdown(sp.body||"") + '<span class="cursor"></span>';
        const tb = last.querySelector(".think-body");
        if(tb && sp.think) tb.innerHTML = renderMarkdown(sp.think);
        return true;
      }
      function scheduleRender(){ // token 事件每秒可达上百次，逐次全量重绘会卡死主线程；按动画帧合并。
        // 单专家顺序发言时，token 间隔约 4ms；16ms 刷新间隔可做到接近逐字显示，
        // 叠加 80ms 兜底确保后台切回时看起来流畅不冻结。
        if(_renderQueued) return; _renderQueued = true;
        const flush = () => {
          if(!_renderQueued) return; _renderQueued = false;
          // 消息结构未变（无新专家发言/工具调用/状态翻转）→ 走 O(1) 增量补丁，
          // 避免长辩论（40+ 条）时每帧重建上千个 DOM 节点。
          const sig = _msgSig();
          if(sig === _lastRenderSig && _patchLastMessage()) return;
          renderDebate();
          _lastRenderSig = sig;
        };
        requestAnimationFrame(flush);
        setTimeout(flush, 80);
      }
      function fmtTime(ts){ if(!ts) return ""; const d=new Date(ts); return d.getHours().toString().padStart(2,"0")+":"+d.getMinutes().toString().padStart(2,"0")+":"+d.getSeconds().toString().padStart(2,"0"); }
      function renderDebate(){
        const box=$("debate"); const wrap=document.createElement("div"); wrap.className="thread"; let last=-1;
        messages.forEach((m,mi)=>{ // 仅 role-round 形式的 id（如 scene-2）渲染轮次分隔；human-<ts> / err-<ts> 不计
          const rk=parseInt(m.id.split("-")[1]); const isRoundId=Number.isInteger(rk)&&rk>=1&&rk<=maxRounds+2;
          if(isRoundId&&rk!==last){ const sep=document.createElement("div"); sep.className="round-sep"; sep.textContent=`第 ${rk} 轮审理`; wrap.appendChild(sep); last=rk; }
           const tools=(m.tools&&m.tools.length)?`<div class="sandbox"><summary>⚙ 工具调用 · ${m.tools.length} 次</summary>${m.tools.map(t=>`<div class="sb-row"><span class="sb-k">调用</span>${TOOL_LABELS[t.tool]||t.tool}</div><div class="sb-row"><span class="sb-k">入参</span><pre class="md">${escapeHtml(JSON.stringify(t.args||{}, null, 2))}</pre></div><div class="sb-row"><span class="sb-k">返回</span><div class="md sandbox-result">${renderSandbox(t.result||"")}</div></div>`).join("")}</div>`:"";
          const cite=m.citations&&m.citations.length?`<div class="cites">来源${m.citations.map(c=>`<span class="cite-chip" title="${escapeHtml(c)}">${escapeHtml(String(c).slice(0,26))}</span>`).join("")}</div>`:"";
          // 法条引用信号灯（发言结束后计算一次并缓存；重绘零开销）
          let citeAudit="";
          if(m.done && m.text){
            if(m.__citeAudit===undefined) m.__citeAudit=citeAuditHtml(m.text);
            citeAudit=m.__citeAudit;
          }
          // 深度思考过程（<think> 内容剥离出正文，折叠展示）
          const sp=m.text&&m.text.includes("<th")?splitThink(m.text):{think:"",body:m.text};
          const thinkBox=sp.think?`<details class="think-box"${m.done?"":" open"}><summary>🧠 深度思考过程${m.done?"（点击展开）":" · 进行中…"}</summary><div class="think-body md">${renderMarkdown(sp.think)}</div></details>`:"";
          const el=document.createElement("div"); el.className="rec";
           el.innerHTML=`<div class="ava${m.done?"":" live"}" style="background:${escapeHtml(m.color)}">${escapeHtml(m.name.slice(0,1))}</div><div class="body"><button class="copy-btn" data-copy="${mi}" title="复制发言原文">复制</button><div class="rname">${escapeHtml(m.name)}<span class="rtag">${roleMap[m.role]?.group?GROUP_LABELS[roleMap[m.role].group]:""}</span>${m.time?`<span class="rtime">${fmtTime(m.time)}</span>`:""}</div>${m.stance?`<div class="rstance">${escapeHtml(m.stance)}</div>`:""}${thinkBox}<div class="rtext md">${renderMarkdown(sp.body||"")}${!m.done?'<span class="cursor"></span>':''}</div>${tools}${citeAudit}${cite}</div>`;
          wrap.appendChild(el);
        });
        box.innerHTML="";
        // 结案卡片挂在渲染流水线内：任何一次重绘都自动补挂，不会被冲掉
        if(!running && lastVerdict && messages.length) appendClosureCard(wrap);
        box.replaceChildren(wrap);
        _lastRenderSig = _msgSig(); // 全量重绘后同步增量签名，避免下次 token 重复全量
        const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 140;
        if (nearBottom) box.scrollTop = box.scrollHeight;
        const jb = $("jumpBottom"); if (jb) jb.classList.toggle("hidden", nearBottom || !messages.length);
      }
