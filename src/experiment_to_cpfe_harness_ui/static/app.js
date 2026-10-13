'use strict';
// Thin browser client over /api/tools/<tool>. Every decision is the core's: the page only
// formats returned values, shows hints, and never computes scientific results or retries mutations.
(function () {
  const TOKEN_KEY = 'harness.ui.token';
  const CREATE_KEY = 'harness.ui.create';
  const REASON_PREFIX = 'harness.ui.reason:';
  const WORKFLOW = 'paramaterial_tensile.v1';
  const POLL_MS = 1500;
  const ACTIVE = new Set(['queued', 'waiting_resource', 'running', 'pause_requested', 'cancel_requested', 'reconciling']);
  const TERMINAL = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
  const RUN_ID = /^run_[a-f0-9]{32}$/;

  const STATE = {
    ready: ['已冻结，未提交', 'gray', '○'], queued: ['已排队', 'run', '●'], waiting_resource: ['等待计算槽位', 'warn', '◷'],
    running: ['计算中', 'run', '●'], pause_requested: ['已请求暂停', 'warn', '⏸'], paused: ['已在阶段边界暂停', 'warn', '⏸'],
    cancel_requested: ['正在取消', 'warn', '◷'], reconciling: ['待核对', 'warn', '?'], waiting_human: ['等待人工审核', 'warn', '⏸'],
    blocked: ['已阻塞', 'bad', '✕'], completed: ['计算完成', 'ok', '✓'], failed: ['失败', 'bad', '✕'],
    cancelled: ['已取消', 'gray', '■'], interrupted: ['已中断', 'bad', '✕'], unknown: ['未知', 'gray', '?'],
  };
  const ACCEPTANCE = {
    not_assessed: ['未评估', 'gray', '○'], not_evaluated: ['未评估', 'gray', '○'], accepted: ['已通过', 'ok', '✓'],
    rejected: ['未通过', 'bad', '✕'], blocked: ['受阻', 'bad', '✕'], criteria_met: ['判据满足', 'ok', '✓'],
    failed_evidence: ['证据失败', 'bad', '✕'],
  };
  const STAGES = { paramaterial_case: '计算与内置验收', acceptance: '验收' };
  const FROZEN = '这个任务冻结时的代码、依赖、输入或策略与当前不同，只能查看，不能继续。请新建任务（必要时在新工作区）。';
  const ERRORS = {
    STATE_CONFLICT: '任务状态已被其他操作更新（可能来自其他窗口、CLI 或 MCP）。已重新读取，请按当前状态操作。',
    PLAN_STALE: '输入或环境在生成计划后发生变化，请从第 ① 步重新预检。',
    ENVIRONMENT_CHANGED: FROZEN, INPUT_CHANGED: FROZEN, POLICY_CHANGED: FROZEN,
    IDEMPOTENCY_CONFLICT: '同一操作已用不同内容提交过。请刷新页面后重新操作。',
    BUDGET_EXCEEDED: '超出预算：重试次数或墙钟预算已用完，或申请值超过授权上限。不能追加预算。',
    RETRY_NOT_ALLOWED: '仅失败或中断的任务可重试；执行状态不确定时不能重试。',
    EXECUTION_UNCERTAIN: '无法确认上一个 worker 已停止，请先核对。',
    PRECONDITION_FAILED: '当前状态不满足该操作的前提条件。',
    UNSUPPORTED: '本平台或本版本不支持该操作（计算只在 Windows 上验证）。',
    NOT_FOUND: '任务或对象不存在。',
    APPROVAL_REQUIRED: '需要先用操作者命令批准。',
    EVIDENCE_STALE: '证据与当前 attempt 或已批准的证据不一致。',
    EVIDENCE_INVALID: '证据无效。',
    INTEGRITY_MISMATCH: '证据完整性校验失败：当前文件与封存记录不一致。旧文件已保留。',
    HASH_MISMATCH: '哈希不一致。',
    INVALID_REQUEST: '请求不符合接口定义。',
    WORKSPACE_DENIED: '工作区未授权。',
    FILE_UNAVAILABLE: '授权文件缺失或无法访问。',
    STORE_UNAVAILABLE: '任务存储不可用，需要操作者排查。',
    INTERNAL_RESPONSE_INVALID: '核心返回了不符合接口定义的结果。',
    INTERNAL_ERROR: '核心未能得到可验证的结果。',
    COMPUTATION_FAILED: '计算失败。',
    PATH_NOT_ALLOWED: '路径不在授权范围内。', MISSING_INPUT: '缺少输入文件。', INPUT_TOO_LARGE: '输入文件过大。',
    SOURCE_HASH_MISMATCH: '来源哈希不一致：文件与审定版本不同。', INPUT_UNREADABLE: '输入文件无法读取。',
    MISSING_METADATA: '缺少元数据。', SPECIMEN_IDENTITY_MISMATCH: '试样身份不一致。',
    INVALID_UNITS: '单位不合规：应变须为 1、应力须为 MPa。', ROW_COUNT_MISMATCH: '行数与审定版本不一致。',
    INVALID_MANIFEST: '清单无效。', INVALID_CURVE: '曲线数据无效。',
    // Acceptance report issue codes (acceptance.py); the core's safe_message is the same English sentence for all of them.
    EXECUTION_NOT_COMPLETED: '计算没有正常完成。', EXECUTION_SCOPE_MISMATCH: '执行范围与约定不符（不应有求解或模型拟合）。',
    SPECIMEN_SET_MISMATCH: '试样集合与约定不符。', CODE_IDENTITY_MISMATCH: '处理代码身份与审定版本不符。',
    SOURCE_CONTEXT_MISMATCH: '数据集来源信息与清单不符。', REFERENCE_SCOPE_MISMATCH: '参考值性质与约定不符。',
    RUN_EVIDENCE_INVALID: 'run.json 缺失或无法解析。', ARTIFACT_BINDING_MISMATCH: '产物路径与登记位置不符。',
    IDENTITY_UNITS_MISMATCH: '试样身份或单位不符。', NORMALIZATION_NOT_COMPLETED: '规范化没有完成。',
    ARTIFACT_HASH_MISMATCH: '产物哈希与规范化收据不符。', CONFIG_HASH_MISMATCH: '配置文件哈希与收据不符。',
    INPUT_BINDING_MISMATCH: '输入文件绑定不符。', NUMERIC_READBACK_MISMATCH: 'HDF5 数值回读与原始数据不一致。',
    SOURCE_BINDING_MISMATCH: '来源绑定不符。', ROW_BINDING_MISMATCH: '逐行来源绑定不符。',
    SAMPLE_EVIDENCE_INVALID: '试样证据无效。', METRIC_SET_MISMATCH: '指标集合与约定不符。',
    DERIVED_CURVE_MISMATCH: '导出曲线与原始数据不一致。', METRIC_EVIDENCE_INVALID: '指标证据无效。',
    VERIFICATION_RECEIPT_INVALID: '独立回读收据无效。', REPORT_ARTIFACT_INVALID: '图表文件无效。',
    VERIFICATION_EVIDENCE_INVALID: '回读证据无效。',
  };
  const REASONS = {
    CHECKPOINT_UNSUPPORTED: '计算中断，且不支持从检查点续算；只能整案重跑（新 attempt）。',
    STOP_UNCONFIRMED: '停止尚未确认。可以核对，或再次取消。',
    EXECUTION_UNCERTAIN: '无法确认 worker 状态。',
    CANCELLED_BY_REQUEST: '按请求取消。',
    COMPUTATION_FAILED: '计算失败。',
    BUDGET_EXCEEDED: '预算耗尽。',
    WORKER_LAUNCH_UNCONFIRMED: 'worker 启动未确认，需要核对并重新派发。',
  };
  const EVENTS = {
    task_frozen: '已冻结任务', attempt_queued: '已排队新的 attempt', control_requested: '已请求操作',
    budget_settled: '已结算墙钟用量', handoff_opened: '已打开人工审核', handoff_submitted: '已提交已批准证据',
    operator_approved: '操作者已批准', recovery_rejected: '恢复被拒绝，旧收据保留',
    worker_stopped_without_seal: 'worker 已停止且没有封存结果', dispatch_unconfirmed: '派发未确认，需要核对并重新派发',
    worker_registered: '已登记 worker', resource_enforcement: '已应用资源约束', stop_unconfirmed: '停止未确认，需要核对',
  };
  const LAYER = {
    passed: ['通过', 'ok', '✓'], failed: ['未通过', 'bad', '✕'], not_evaluated: ['未评估', 'gray', '○'],
    valid: ['有效', 'ok', '✓'], invalid: ['无效', 'bad', '✕'], met: ['满足', 'ok', '✓'], not_met: ['不满足', 'bad', '✕'],
  };
  const METRICS = { UTS_MPa: '抗拉强度 UTS', E_MPa: '弹性模量 E', Rp02_MPa: '规定塑性延伸强度 Rp0.2' };
  const SCOPE = {
    'Fixed AA6061-T651 20 C lot A three-specimen transfer and calculation reproduction.': '仅为固定的 AA6061-T651、20 °C、A 批次三个试样的数据转换与计算复现。',
    'Independent arithmetic references are not author per-specimen truth.': '独立复算的参考值不是作者给出的逐试样真值。',
    'No solver, training, calibration, physical validation or generalization claim.': '不涉及求解器、模型拟合或标定，也不声称物理验证或可推广。',
  };
  const REFERENCE_KIND = { independent_recalculation_not_author_truth: '独立复算（不是作者真值）' };
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const ACTIONS = { pause: '暂停', cancel: '取消', resume: '恢复', retry: '重试' };
  const UNSUPPORTED = {
    abaqus: 'Abaqus 求解', training: '模型训练', checkpoint_resume: '检查点续算', model_calls: '模型调用',
    remote_execution: '远程执行', gpu: 'GPU',
  };

  const app = document.getElementById('app');
  const banners = document.getElementById('banners');
  const connection = document.getElementById('connection');
  let token = null;
  let session = null;
  let capabilities = null;
  let offline = false;
  let generation = 0;
  let pollTimer = null;
  let reconnectTimer = null;

  // ---------- small helpers
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') el.className = value;
      else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
      else el.setAttribute(key, value === true ? '' : String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : String(child));
    }
    return el;
  }
  function badge(map, key, suffix) {
    const [label, tone, mark] = map[key] || [key, 'gray', '?'];
    return h('span', { class: 'badge ' + tone }, mark + ' ' + label + (suffix || ''));
  }
  function randomId(prefix) {
    const bytes = new Uint8Array(12);
    crypto.getRandomValues(bytes);
    return prefix + Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  }
  // Per-tab state only: the token and in-flight keys must not outlive the tab or leak across windows.
  function store() {
    try { return window.sessionStorage; } catch (e) { return null; }
  }
  function getItem(key) { try { return store().getItem(key); } catch (e) { return null; } }
  function setItem(key, value) { try { store().setItem(key, value); } catch (e) { /* per-tab convenience only */ } }
  function removeItem(key) { try { store().removeItem(key); } catch (e) { /* ignore */ } }
  function pad(n) { return String(n).padStart(2, '0'); }
  function fmtTime(iso, withSeconds) {
    const d = new Date(iso);
    if (!iso || isNaN(d.getTime())) return iso || '—';
    const base = `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    return withSeconds ? base + ':' + pad(d.getSeconds()) : base;
  }
  function fmtSeconds(value) { return value === null || value === undefined ? '—' : Number(value).toFixed(1) + ' s'; }
  function fmtBytes(value) {
    if (value >= 1073741824 && value % 1073741824 === 0) return value / 1073741824 + ' GiB';
    if (value >= 1048576) return (value / 1048576).toFixed(value % 1048576 === 0 ? 0 : 1) + ' MiB';
    return value + ' B';
  }
  function fingerprint(text) {
    // FNV-1a, only to keep idempotency keys short; not a security boundary.
    let hash = 0x811c9dc5;
    for (const ch of new TextEncoder().encode(text)) hash = Math.imul(hash ^ ch, 0x01000193) >>> 0;
    return hash.toString(16).padStart(8, '0');
  }
  function fmtNum(raw) {
    const n = Number(raw);
    if (raw === null || raw === undefined || raw === '' || !isFinite(n)) return raw === undefined || raw === null || raw === '' ? '—' : String(raw);
    if (n === 0) return '0';
    const abs = Math.abs(n);
    if (abs < 1e-4 || abs >= 1e7) return n.toExponential(5).replace(/\.?0+e/, 'e');
    return String(Number(n.toPrecision(6)));
  }
  function num(raw) { return h('span', { title: String(raw) }, fmtNum(raw)); }
  function yesNo(value) { return value === true ? '是' : value === false ? '否' : '—'; }
  function shortHash(hash) { return hash ? h('code', { title: hash }, hash.slice(0, 12) + '…') : '—'; }
  function shortId(id) { return id ? id.slice(0, id.indexOf('_') + 9) + '…' : '—'; }
  function errorText(error) {
    if (!error) return '';
    const zh = ERRORS[error.code] || '操作未完成。';
    return `${zh}（${error.code}${error.field ? '，字段 ' + error.field : ''}）`;
  }
  function errorBlock(error) {
    return h('div', { class: 'banner bad' }, errorText(error),
      error.safe_message ? h('div', { class: 'small' }, '核心原文：' + error.safe_message) : null);
  }
  function reasonText(code) { return code ? (REASONS[code] || ERRORS[code] || '') : ''; }
  function keepOpenDetails(fn) {
    const open = new Set(Array.from(app.querySelectorAll('details[data-keep][open]'), (d) => d.dataset.keep));
    fn();
    for (const d of app.querySelectorAll('details[data-keep]')) if (open.has(d.dataset.keep)) d.open = true;
  }

  // ---------- transport
  class TransportError extends Error {}

  async function api(tool, fields) {
    if (offline) throw new TransportError('与本地服务断开');
    const body = JSON.stringify(Object.assign({ schema_version: 'harness.v1', request_id: randomId('ui-'), workspace_id: 'local' }, fields || {}));
    let response;
    let payload;
    try {
      response = await fetch('/api/tools/' + tool, {
        method: 'POST', cache: 'no-store', credentials: 'omit',
        headers: { 'Content-Type': 'application/json', 'X-Harness-Token': token }, body,
      });
      payload = await response.json();
    } catch (e) {
      goOffline();
      throw new TransportError('与本地服务断开');
    }
    if (response.status !== 200) {
      if (payload && payload.transport_error === 'TOKEN_DENIED') tokenDenied();
      throw new TransportError((payload && payload.safe_message) || '请求被本地服务拒绝。');
    }
    return payload;
  }

  async function fetchSession() {
    const response = await fetch('/api/session', { cache: 'no-store', credentials: 'omit', headers: { 'X-Harness-Token': token } });
    const payload = await response.json();
    if (response.status !== 200) {
      if (payload && payload.transport_error === 'TOKEN_DENIED') tokenDenied();
      throw new TransportError(payload.safe_message || '会话不可用');
    }
    return payload;
  }

  function setBanner(id, tone, ...content) {
    let el = document.getElementById(id);
    if (!content.length) { if (el) el.remove(); return; }
    const next = h('div', { id, class: 'banner ' + tone }, ...content);
    if (el) el.replaceWith(next); else banners.append(next);
  }

  function goOffline() {
    if (offline) return;
    offline = true;
    stopPolling();
    connection.dataset.state = 'lost';
    connection.textContent = '与本地服务断开';
    setBanner('offline', 'bad', '与本地服务断开。所有变更按钮已禁用，正在自动重连；重连后会重新读取状态，不会自动重发任何操作。',
      ' 计算任务不受页面影响。');
    setBanner('active', 'warn');
    for (const button of document.querySelectorAll('button.mutation')) button.disabled = true;
    const loading = app.querySelector('p.muted:only-child');
    if (loading) loading.textContent = '等待重连后重新读取…';
    scheduleReconnect(1000);
  }

  function scheduleReconnect(delay) {
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(async () => {
      try {
        session = await fetchSession();
        offline = false;
        markConnected();
        setBanner('offline', 'bad');
        route();
      } catch (e) {
        if (!(e instanceof TransportError) || offline) scheduleReconnect(Math.min(delay * 2, 10000));
      }
    }, delay);
  }

  function markConnected() {
    connection.dataset.state = 'ok';
    connection.textContent = '已连接本地服务';
    document.getElementById('workspace-path').textContent = '工作区：' + session.workspace;
  }

  function tokenDenied() {
    stopPolling();
    removeItem(TOKEN_KEY);
    connection.dataset.state = 'lost';
    connection.textContent = '访问令牌无效';
    app.replaceChildren(h('div', { class: 'banner bad' }, '访问令牌无效或已过期（本地服务重启后会生成新令牌）。请使用终端里最新打印的完整地址重新打开界面。'));
  }

  // ---------- routing
  function stopPolling() { clearTimeout(pollTimer); pollTimer = null; }

  function route() {
    generation += 1;
    stopPolling();
    if (offline || !session) return;
    const hash = location.hash.replace(/^#/, '') || '/';
    const [path, query] = hash.split('?');
    const parts = path.split('/').filter(Boolean);
    window.scrollTo(0, 0);
    if (parts.length === 0) return renderHome(generation);
    if (parts[0] === 'new') return renderWizard(generation, new URLSearchParams(query || ''));
    if (parts[0] === 'run' && RUN_ID.test(parts[1] || '')) {
      const tab = ['events', 'results', 'artifacts'].includes(parts[2]) ? parts[2] : 'overview';
      return renderRun(generation, parts[1], tab, new URLSearchParams(query || ''));
    }
    app.replaceChildren(h('div', { class: 'panel' }, '页面不存在。', h('a', { href: '#/' }, '返回首页')));
  }

  function current(gen) { return gen === generation && !offline; }

  function poll(gen, fn, delay) {
    stopPolling();
    pollTimer = setTimeout(async () => {
      if (!current(gen) || document.hidden) { if (current(gen)) poll(gen, fn, delay); return; }
      try { await fn(); } catch (e) { if (!(e instanceof TransportError)) console.error(e); }
      if (current(gen)) poll(gen, fn, delay);
    }, delay);
  }

  // ---------- capabilities dialog
  async function loadCapabilities() {
    if (capabilities) return capabilities;
    const result = await api('capabilities.get');
    if (result.ok) capabilities = result.data;
    return capabilities;
  }

  async function openCapabilities() {
    const dialog = document.getElementById('capabilities-dialog');
    const body = document.getElementById('capabilities-body');
    body.replaceChildren(h('p', { class: 'muted' }, '正在读取…'));
    dialog.showModal();
    try {
      const caps = await loadCapabilities();
      if (!caps) { body.replaceChildren(h('p', null, '无法读取能力说明。')); return; }
      const verification = caps.platform_verification || {};
      body.replaceChildren(
        h('dl', { class: 'facts' },
          h('dt', null, '工作流'), h('dd', null, caps.workflows.join('、')),
          h('dt', null, '执行后端'), h('dd', null, caps.backends.join('、')),
          h('dt', null, '可读取格式'), h('dd', null, caps.formats.join('、')),
          h('dt', null, '执行平台'), h('dd', null, (caps.execution_platforms || []).join('、') || '—',
            Object.keys(verification).length ? h('span', { class: 'muted small' }, '（验证情况：' +
              Object.entries(verification).map(([k, v]) => `${k} ${v}`).join('；') + '）') : null),
          h('dt', null, '暂停'), h('dd', null, '只在阶段边界生效（', h('code', null, caps.controls.pause), '）'),
          h('dt', null, '取消'), h('dd', null, '停止本任务拥有的进程树（', h('code', null, caps.controls.cancel), '）'),
          h('dt', null, '重试'), h('dd', null, '新建 attempt，旧 attempt 保留（', h('code', null, caps.controls.retry), '）'),
          h('dt', null, '资源约束'), h('dd', null, Object.entries(caps.resource_enforcement).map(([k, v]) => h('div', null, k + '：', h('code', null, v)))),
          h('dt', null, '授权上限'), h('dd', null, limitsText(caps.limits)),
          h('dt', null, 'Python'), h('dd', null, h('code', null, caps.environment.python_executable), ' ', caps.environment.python_version.join('.')),
          h('dt', null, '访问边界'), h('dd', null, h('code', null, caps.access_boundary))),
        h('h3', null, '未支持（本界面没有任何入口）'),
        h('ul', null, caps.unsupported.map((item) => h('li', null, h('code', null, item), ' ', UNSUPPORTED[item] || '', ' — 未支持'))),
        h('p', { class: 'muted small' }, '本地界面只接受本机访问，但不是操作系统沙箱：同一账户的其他进程仍可直接读写工作区。初始化工作区和批准人工审核只能由操作者在终端完成。'));
    } catch (e) {
      body.replaceChildren(h('p', null, e.message));
    }
  }

  function limitsText(limits) {
    return `墙钟 ${limits.wall_seconds} s · 存储 ${fmtBytes(limits.storage_bytes)} · 重试 ${limits.retries} 次 · CPU ${limits.cpu} · GPU 不支持`;
  }

  // ---------- home
  async function renderHome(gen) {
    app.replaceChildren(h('p', { class: 'muted' }, '正在读取工作区…'));
    let caps;
    let validation;
    let runs;
    try {
      [caps, validation, runs] = await Promise.all([loadCapabilities(), api('inputs.validate'), api('runs.list', { limit: 200 })]);
    } catch (e) { return; }
    if (!current(gen)) return;
    const state = { filter: getItem('harness.ui.filter') || 'all', runs: runs.ok ? runs.data : null, validation };
    const draw = () => keepOpenDetails(() => app.replaceChildren(homeOverview(caps, state), homeRuns(gen, state)));
    draw();
    updateActiveBanner(state.runs);
    const refresh = async () => {
      const next = await api('runs.list', { limit: 200 });
      if (!current(gen) || !next.ok) return;
      state.runs = next.data;
      draw();
      updateActiveBanner(state.runs);
    };
    state.refresh = refresh;
    state.revalidate = async () => {
      state.validation = await api('inputs.validate');
      if (current(gen)) draw();
    };
    state.redraw = draw;
    const loop = async () => { if (state.runs && state.runs.items.some((r) => ACTIVE.has(r.execution_status))) await refresh(); };
    poll(gen, loop, 3000);
  }

  function updateActiveBanner(page) {
    const active = page && page.items.some((r) => ACTIVE.has(r.execution_status));
    if (active) setBanner('active', 'warn', '有任务正在进行。关闭本地服务可能中断计算（取决于启动方式），请保持终端窗口打开直到任务结束。关闭或刷新浏览器页面不影响任务。');
    else setBanner('active', 'warn');
  }

  function validationSummary(validation) {
    if (!validation.ok) return h('span', null, badge(ACCEPTANCE, 'rejected'), ' 预检未完成：', errorText(validation.error));
    const data = validation.data;
    if (data.valid) return h('span', null, h('span', { class: 'badge ok' }, '✓ 通过'), ` ${data.specimen_ids.length} 个试样，共 ${data.total_rows} 行`);
    return h('span', null, h('span', { class: 'badge bad' }, `✕ 未通过：${data.issues.length} 项问题`));
  }

  function homeOverview(caps, state) {
    const validation = state.validation;
    const valid = validation.ok && validation.data.valid;
    const windows = session.platform === 'nt';
    const newButton = valid
      ? h('button', { type: 'button', class: 'primary', onclick: () => { location.hash = '#/new'; } }, '＋ 新建任务')
      : h('div', { class: 'action' }, h('button', { type: 'button', class: 'primary', disabled: true }, '＋ 新建任务'),
        h('span', { class: 'why' }, '输入预检未通过，不能新建任务'));
    return h('section', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', null, '工作区概况'), newButton),
      h('dl', { class: 'facts' },
        h('dt', null, '工作流'), h('dd', null, 'Paramaterial 拉伸三试样（', h('code', null, caps ? caps.workflows.join(', ') : WORKFLOW), '）'),
        h('dt', null, '平台'), h('dd', null, windows ? 'Windows ✓' : h('span', { class: 'badge warn' }, '非 Windows：本平台只能查看，不能提交计算'),
          '　并发上限 1（固定）　CPU 1　GPU 不支持'),
        h('dt', null, '授权上限'), h('dd', null, caps ? limitsText(caps.limits) : '—'),
        h('dt', null, '输入预检'), h('dd', null, validationSummary(validation), ' ',
          h('button', { type: 'button', class: 'secondary', onclick: () => state.revalidate() }, '重新预检'))),
      !valid && validation.ok ? issueList(validation.data.issues) : null);
  }

  function issueList(issues) {
    return h('div', null,
      h('ul', { class: 'issues' }, issues.map((issue) => h('li', null,
        issue.field ? h('code', null, issue.field) : null, ' ', ERRORS[issue.code] || issue.code, ' ',
        h('span', { class: 'small' }, `（${issue.code}：${issue.safe_message}）`)))),
      h('p', { class: 'muted' }, '界面不能修改输入。请让操作者恢复原始案例文件后重新预检。'));
  }

  const FILTERS = {
    all: ['全部', () => true],
    active: ['进行中', (r) => ACTIVE.has(r.execution_status) || r.execution_status === 'ready'],
    attention: ['需处理', (r) => ['waiting_human', 'paused', 'blocked', 'failed', 'interrupted', 'reconciling', 'cancel_requested'].includes(r.execution_status)],
    done: ['已结束', (r) => TERMINAL.has(r.execution_status)],
  };

  function homeRuns(gen, state) {
    const page = state.runs;
    const select = h('select', { 'aria-label': '筛选', onchange: (e) => { state.filter = e.target.value; setItem('harness.ui.filter', state.filter); state.redraw(); } },
      Object.entries(FILTERS).map(([key, [label]]) => h('option', { value: key, selected: key === state.filter }, label)));
    const head = h('div', { class: 'panel-head' }, h('h2', null, '任务'),
      h('div', null, '筛选：', select, ' ', h('button', { type: 'button', class: 'secondary', onclick: () => state.refresh() }, '刷新')));
    if (!page) return h('section', { class: 'panel' }, head, h('p', null, '无法读取任务列表。'));
    if (page.total === 0) {
      return h('section', { class: 'panel' }, head,
        h('p', null, '这个工作区还没有任务。'),
        h('ol', null,
          h('li', null, '先检查固定案例的输入是否完整、未被修改（上方“重新预检”）。'),
          h('li', null, '查看执行计划并确认预算。'),
          h('li', null, '冻结并提交计算，然后在任务详情中查看状态和验收。')),
        h('p', { class: 'muted' }, '说明：本版只支持一个固定的三试样流程，不能上传或修改实验数据。'));
    }
    const rows = page.items.filter(FILTERS[state.filter] ? FILTERS[state.filter][1] : () => true);
    return h('section', { class: 'panel' }, head,
      h('table', null,
        h('thead', null, h('tr', null, ['创建时间', '执行', '验收', 'attempt', '当前阶段', '审核', '标识'].map((t) => h('th', null, t)))),
        h('tbody', null, rows.map((r) => h('tr', { class: 'clickable', onclick: () => { location.hash = '#/run/' + r.run_id; } },
          h('td', null, h('a', { href: '#/run/' + r.run_id }, fmtTime(r.created_at))),
          h('td', null, badge(STATE, r.execution_status)),
          h('td', null, badge(ACCEPTANCE, r.acceptance_status)),
          h('td', { class: 'num' }, r.attempt_count),
          h('td', null, r.current_stage ? STAGES[r.current_stage] || r.current_stage : '—'),
          h('td', null, r.review_required ? '需要' : '—'),
          h('td', { onclick: (e) => e.stopPropagation() }, h('details', { 'data-keep': 'ids-' + r.run_id },
            h('summary', null, shortId(r.run_id)),
            h('div', { class: 'mono' }, 'run_id ' + r.run_id), h('div', { class: 'mono' }, 'task_id ' + r.task_id))))))),
      rows.length === 0 ? h('p', { class: 'muted' }, '没有符合筛选条件的任务。') : null,
      page.next_cursor !== null ? h('p', { class: 'muted small' }, `只显示最近 ${page.items.length} 个，共 ${page.total} 个。`) : null);
  }

  // ---------- new task wizard
  async function renderWizard(gen, query) {
    const caps = await loadCapabilities().catch(() => null);
    if (!current(gen)) return;
    if (!caps) { app.replaceChildren(h('p', null, '无法读取授权上限。')); return; }
    const limits = caps.limits;
    const w = {
      validation: null, plan: null, planError: null, busy: false, receipt: null, error: null,
      wall: limits.wall_seconds, storageMiB: Math.floor(limits.storage_bytes / 1048576), retries: limits.retries,
      review: false, replicate: query.get('replicate') === '1',
    };
    const draw = () => { if (current(gen)) keepOpenDetails(() => app.replaceChildren(wizardView(gen, w, limits, draw))); };
    w.validate = async () => {
      w.validation = null; w.plan = null; draw();
      try { w.validation = await api('inputs.validate'); } catch (e) { return; }
      draw();
    };
    draw();
    await w.validate();
  }

  function budgetFromForm(w, limits) {
    const errors = {};
    const wall = Number(w.wall);
    const storage = Math.round(Number(w.storageMiB) * 1048576);
    const retries = Number(w.retries);
    if (!(wall > 0) || wall > limits.wall_seconds) errors.wall = `须大于 0 且不超过 ${limits.wall_seconds}`;
    if (!Number.isInteger(Number(w.storageMiB)) || !(storage > 0) || storage > limits.storage_bytes) errors.storage = `须为正整数 MiB 且不超过 ${fmtBytes(limits.storage_bytes)}`;
    if (!Number.isInteger(retries) || retries < 0 || retries > limits.retries) errors.retries = `须为 0 到 ${limits.retries} 的整数`;
    return { budget: { wall_seconds: wall, storage_bytes: storage, retries }, errors };
  }

  function wizardView(gen, w, limits, draw) {
    const validated = w.validation && w.validation.ok && w.validation.data.valid;
    const { budget, errors } = budgetFromForm(w, limits);
    const budgetValid = Object.keys(errors).length === 0;
    const step = w.receipt ? 3 : w.plan ? 3 : validated ? 2 : 1;
    const invalidate = () => { w.plan = null; w.planError = null; w.error = null; };
    // A slider and a number box edit the same value; the bar shows the share of the operator's limit.
    // The core accepts only these budget fields, and only at or below the limit.
    const field = (key, label, value, max, unit, hint) => {
      const min = key === 'retries' ? 0 : 1;
      const locked = !validated || w.busy || !!w.receipt;
      const error = errors[key === 'storageMiB' ? 'storage' : key];
      const share = h('span', { class: 'share' });
      const meter = h('meter', { min: 0, max, value: Math.min(Number(value) || 0, max), 'aria-hidden': 'true' });
      const show = (v) => { meter.value = Math.min(Number(v) || 0, max); share.textContent = max ? `${Math.round(Math.min(Number(v) || 0, max) / max * 100)}%` : ''; };
      const number = h('input', { id: 'f-' + key, type: 'number', min, max, step: key === 'wall' ? 'any' : 1, value, disabled: locked,
        oninput: (e) => { slider.value = e.target.value; show(e.target.value); },
        onchange: (e) => { w[key] = e.target.value; invalidate(); draw(); } });
      const slider = h('input', { type: 'range', min, max, step: 1, value, disabled: locked, 'aria-label': label,
        oninput: (e) => { number.value = e.target.value; show(e.target.value); },
        onchange: (e) => { w[key] = e.target.value; invalidate(); draw(); } });
      show(value);
      return [h('label', { for: 'f-' + key }, label),
        h('div', { class: 'budget-input' }, slider, number),
        h('div', { class: 'budget-share' }, meter, share,
          h('span', { class: error ? 'field-error' : 'hint' }, error || `${unit}（上限 ${hint}）`))];
    };

    const stepOne = h('section', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', null, '① 输入预检'),
        w.validation ? validationSummary(w.validation) : h('span', { class: 'muted' }, '正在检查…')),
      w.validation && w.validation.ok ? [
        h('dl', { class: 'facts' },
          h('dt', null, '试样'), h('dd', null, w.validation.data.specimen_ids.join(' · '), `　共 ${w.validation.data.total_rows} 行`),
          h('dt', null, '工作流'), h('dd', null, h('code', null, w.validation.data.workflow_id))),
        h('details', { 'data-keep': 'files' }, h('summary', null, `文件与哈希（${Object.keys(w.validation.data.files).length} 个）`),
          h('table', null, h('tbody', null, Object.entries(w.validation.data.files).map(([path, sha]) =>
            h('tr', null, h('td', { class: 'mono' }, path), h('td', { class: 'mono' }, sha)))))),
        w.validation.data.valid ? null : issueList(w.validation.data.issues),
      ] : null,
      w.validation && !w.validation.ok ? errorBlock(w.validation.error) : null,
      h('div', { class: 'actions' }, h('button', { type: 'button', class: 'secondary', disabled: w.busy || !!w.receipt, onclick: () => w.validate() }, '重新预检')));

    const planBox = w.plan ? h('div', null,
      h('h3', null, '计划'),
      h('dl', { class: 'facts' },
        h('dt', null, '阶段'), h('dd', null, w.plan.stages.map((s, i) => `${i + 1} ${STAGES[s.id] || s.id}（${s.id}）`).join(' → ')),
        h('dt', null, '预算'), h('dd', null, `墙钟 ${w.plan.budget.wall_seconds} s · 存储 ${fmtBytes(w.plan.budget.storage_bytes)} · 重试 ${w.plan.budget.retries} 次`),
        h('dt', null, '资源'), h('dd', null, `CPU ${w.plan.estimates.cpu} · GPU ${w.plan.estimates.gpu} · 模型调用 ${w.plan.estimates.model_calls}`),
        h('dt', null, '预计耗时'), h('dd', null, w.plan.estimates.wall_seconds === null ? '未做基准测试，不提供预计时间' : fmtSeconds(w.plan.estimates.wall_seconds)),
        h('dt', null, '需要确认'), h('dd', null, w.plan.confirmations.length ? '人工审核（计算稳定后等待操作者批准）' : '无')),
      h('details', { 'data-keep': 'digest' }, h('summary', null, '计划摘要 plan_digest'), h('div', { class: 'mono' }, w.plan.plan_digest))) : null;

    const stepTwo = h('section', { class: 'panel' + (validated ? '' : ' muted') },
      h('h2', null, '② 计划确认'),
      validated ? null : h('p', { class: 'why' }, '输入预检通过后才能确认计划。'),
      h('div', { class: 'form-grid' },
        field('wall', '墙钟预算', w.wall, limits.wall_seconds, '秒', limits.wall_seconds + ' s'),
        field('storageMiB', '存储预算', w.storageMiB, Math.floor(limits.storage_bytes / 1048576), 'MiB', fmtBytes(limits.storage_bytes)),
        field('retries', '重试次数', w.retries, limits.retries, '次', limits.retries + ' 次')),
      h('p', { class: 'muted small' }, '拖动滑块或输入数值；只能在操作者授权上限内调低，修改后需要重新生成计划。'),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: w.review, disabled: !validated || w.busy || !!w.receipt,
        onchange: (e) => { w.review = e.target.checked; invalidate(); draw(); } }),
        h('span', null, '要求人工审核（计算稳定后等待操作者批准）')),
      h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: w.replicate, disabled: !validated || w.busy || !!w.receipt,
        onchange: (e) => { w.replicate = e.target.checked; w.error = null; draw(); } }),
        h('span', null, '独立重复计算（replicate）', h('div', { class: 'muted small' }, '不勾选时，输入、环境和计划完全相同的请求会打开已有任务，不会新建。'))),
      h('div', { class: 'actions' }, h('div', { class: 'action' },
        h('button', { type: 'button', disabled: !validated || !budgetValid || w.busy || !!w.receipt, onclick: () => makePlan(gen, w, budget, draw) }, w.plan ? '重新生成计划' : '生成计划'),
        !budgetValid ? h('span', { class: 'why' }, '预算不在授权范围内') : null)),
      w.planError ? errorBlock(w.planError) : null,
      planBox,
      fixedPanel(w));

    const stepThree = h('section', { class: 'panel' },
      h('h2', null, '③ 提交'),
      w.receipt ? w.receipt : h('div', { class: 'actions' },
        h('div', { class: 'action' },
          h('button', { type: 'button', class: 'primary mutation', disabled: !w.plan || w.busy || offline, onclick: () => freezeAndStart(gen, w, budget, draw) },
            w.busy ? '处理中…' : '冻结并提交计算'),
          !w.plan ? h('span', { class: 'why' }, '请先生成并确认计划') : null),
        h('button', { type: 'button', class: 'secondary', onclick: () => { location.hash = '#/'; } }, '取消')),
      w.error ? errorBlock(w.error) : null);

    return h('div', null,
      h('p', null, h('a', { href: '#/' }, '← 返回')),
      h('h1', null, '新建任务'),
      h('div', { class: 'steps' }, ['① 输入预检', '② 计划确认', '③ 提交'].map((label, i) =>
        h('span', { class: i + 1 === step ? 'current' : i + 1 < step ? 'done' : '' }, label))),
      stepOne, stepTwo, stepThree);
  }

  // Everything the core does not accept as a request field is fixed by the reviewed case and shown read-only.
  function fixedPanel(w) {
    const data = w.validation && w.validation.ok ? w.validation.data : null;
    return h('details', { class: 'fixed', 'data-keep': 'fixed' }, h('summary', null, '固定参数（只读，不能在界面调整）'),
      h('dl', { class: 'facts' },
        h('dt', null, '工作流'), h('dd', null, h('code', null, WORKFLOW)),
        h('dt', null, '试样'), h('dd', null, data ? `${data.specimen_ids.join('、')}（共 ${data.total_rows} 行）` : '—'),
        h('dt', null, '输入文件'), h('dd', null, data ? `${Object.keys(data.files).length} 个，哈希锁定` : '—'),
        h('dt', null, '资源'), h('dd', null, w.plan ? `CPU ${w.plan.estimates.cpu} · GPU ${w.plan.estimates.gpu} · 模型调用 ${w.plan.estimates.model_calls} · 并发上限 1` : 'CPU 1 · GPU 不支持 · 并发上限 1'),
        h('dt', null, '处理与验收参数'), h('dd', null, '应力-应变处理、指标计算和验收判据都固定在已审定的代码里并按哈希锁定；数值容差在“结果”标签按验收报告显示。')),
      h('p', { class: 'muted small' }, '这些参数一旦改变，任务就不再是对固定案例的复现，核心会拒绝或判为不通过。如需调整，应作为新的工作流版本单独评审。'));
  }

  async function makePlan(gen, w, budget, draw) {
    w.busy = true; w.planError = null; w.plan = null; draw();
    try {
      const result = await api('task.plan', { workflow_id: WORKFLOW, budget, require_review: w.review });
      if (result.ok) w.plan = result.data; else w.planError = result.error;
    } catch (e) { /* offline banner already shown */ }
    w.busy = false;
    draw();
  }

  function createKey(args) {
    const fingerprint = JSON.stringify(args);
    try {
      const saved = JSON.parse(getItem(CREATE_KEY) || 'null');
      if (saved && saved.fingerprint === fingerprint) return saved.key;
    } catch (e) { /* ignore */ }
    const key = randomId('ui:create:');
    setItem(CREATE_KEY, JSON.stringify({ key, fingerprint }));
    return key;
  }

  async function freezeAndStart(gen, w, budget, draw) {
    const args = { workflow_id: WORKFLOW, budget, require_review: w.review, expected_plan_digest: w.plan.plan_digest, replicate: w.replicate };
    w.busy = true; w.error = null; draw();
    let created;
    try { created = await api('task.create', Object.assign({ idempotency_key: createKey(args) }, args)); } catch (e) { w.busy = false; draw(); return; }
    if (!created.ok) {
      w.busy = false; w.error = created.error;
      if (created.error.code === 'PLAN_STALE') { w.plan = null; draw(); await w.validate(); return; }
      draw();
      return;
    }
    removeItem(CREATE_KEY);
    const run = created.data;
    const link = h('a', { href: '#/run/' + run.run_id }, '打开任务详情 →');
    const lines = [h('div', null, run.deduplicated
      ? '已打开已有的同一冻结任务 ✓（输入、环境和计划完全相同，核心返回了已有任务，没有新建）'
      : '已冻结任务 ✓')];
    if (run.execution_status === 'ready') {
      let started;
      try {
        started = await api('task.start', { run_id: run.run_id, idempotency_key: `ui:start:${run.run_id}:v${run.state_version}`, expected_state_version: run.state_version });
      } catch (e) { started = null; }
      if (started && started.ok) lines.push(h('div', null, '→ 已提交排队 ✓（这不表示计算完成）'));
      else if (started) lines.push(h('div', null, '→ 提交计算未完成：', errorText(started.error)));
      else lines.push(h('div', null, '→ 提交计算时与本地服务断开；重连后请在任务详情中查看状态，界面不会自动重发。'));
    } else {
      lines.push(h('div', null, '该任务当前状态：', badge(STATE, run.execution_status), '（未重复提交）'));
    }
    w.busy = false;
    w.receipt = h('div', { class: 'receipt' }, lines, h('div', null, link));
    draw();
  }

  // ---------- run detail
  async function renderRun(gen, runId, tab, query) {
    const view = { runId, tab, status: null, statusError: null, events: [], cursor: 0, notice: null, busy: null, runs: null,
      artifacts: null, artifactsError: null, artifactsVersion: null, report: null, reportError: null, reportVersion: null,
      evidence: {}, handoffs: null, review: {}, attemptChoice: null, viewer: null, chart: { x: 'corrected', sample: 'all' } };
    const wanted = query && query.get('artifact');
    app.replaceChildren(h('p', { class: 'muted' }, '正在读取任务…'));
    const load = async () => {
      const [status, events] = await Promise.all([api('task.status', { run_id: runId }), loadEvents(view)]);
      if (!current(gen)) return;
      if (status.ok) { view.status = status.data; view.statusError = null; } else view.statusError = status.error;
      const s = view.status;
      if (!s) return;
      if (s.execution_status === 'waiting_resource') {
        const list = await api('runs.list', { limit: 200 });
        if (list.ok) view.runs = list.data.items;
      }
      const review = s.execution_status === 'waiting_human';
      if (review || view.events.some((e) => e.kind === 'handoff_opened')) {
        const page = await api('handoffs.list', { run_id: runId, limit: 100 });
        if (page.ok) view.handoffs = page.data.items;
      }
      // Registered artifacts change only when the state changes; reports.get re-hashes every file, so it is read
      // only when the results tab is open, once per state version.
      if ((tab === 'artifacts' || review || tab === 'results') && view.artifactsVersion !== s.state_version) await loadArtifacts(view);
      if (tab === 'results' && view.reportVersion !== s.state_version) await loadReport(view);
      if (wanted && !view.viewer && view.artifacts) {
        const target = view.artifacts.find((a) => a.artifact_id === wanted);
        if (target) { view.attemptChoice = target.attempt_id; openViewer(view, target); }
      }
    };
    const draw = () => { if (current(gen)) keepOpenDetails(() => app.replaceChildren(runView(gen, view, draw, refresh))); };
    view.draw = draw;
    const refresh = async () => {
      try { await load(); } catch (e) { return; }
      if (!view.busy) draw();
      updateRunBanner(view);
      schedule();
    };
    const schedule = () => {
      const s = view.status;
      if (s && (ACTIVE.has(s.execution_status) || s.required_action)) poll(gen, refresh, POLL_MS);
      else stopPolling();
    };
    view.refresh = refresh;
    await refresh();
  }

  async function loadEvents(view) {
    for (let i = 0; i < 50; i += 1) {
      const page = await api('events.list', { run_id: view.runId, cursor: view.cursor, limit: 500 });
      if (!page.ok) return page;
      view.events.push(...page.data.items);
      const moved = page.data.next_cursor !== null && page.data.next_cursor !== view.cursor;
      if (moved) view.cursor = page.data.next_cursor;
      if (!moved || page.data.items.length < 500) return page;
    }
    return null;
  }

  function updateRunBanner(view) {
    const s = view.status;
    if (s && ACTIVE.has(s.execution_status)) setBanner('active', 'warn', '本任务正在进行。关闭本地服务可能中断计算（取决于启动方式），请保持终端窗口打开直到任务结束。关闭或刷新浏览器页面不影响任务。');
    else setBanner('active', 'warn');
  }

  function stateNote(s, view) {
    const stage = s.attempts.length ? STAGES[s.attempts[s.attempts.length - 1].stage] : null;
    switch (s.execution_status) {
      case 'ready': return '已冻结，尚未提交计算。';
      case 'queued': return '已排队，等待 worker 启动。若长时间没有进展，可以“核对并重新派发”；nonce 机制保证不会重复计算。';
      case 'waiting_resource': {
        const busy = (view.runs || []).find((r) => r.run_id !== s.run_id && ['running', 'pause_requested', 'cancel_requested'].includes(r.execution_status));
        return h('span', null, '工作区内另一任务正在计算（并发上限 1）。', busy ? h('a', { href: '#/run/' + busy.run_id }, '查看占用槽位的任务') : null);
      }
      case 'running': return `当前阶段：${stage || '—'}。进度只到阶段粒度，不提供百分比或预计完成时间。`;
      case 'pause_requested': return '已请求暂停：当前阶段结束后生效，计算仍在进行。本案例的计算阶段包含全部三个试样，因此会等这次计算跑完。';
      case 'paused': return '已在阶段边界暂停。恢复后从阶段边界继续；若要求人工审核但尚未批准，会进入等待人工审核，不能绕过。';
      case 'cancel_requested': return '正在取消：停止尚未确认（STOP_UNCONFIRMED）。可以核对，或再次取消。';
      case 'reconciling': return '无法确认 worker 状态，需要核对。执行状态不确定时不能重试。';
      case 'waiting_human': return '计算已完成并已稳定，等待人工审核。请按下方“人工审核”面板操作；批准只能由操作者在终端完成，浏览器不能代为批准。';
      case 'blocked': return '恢复被拒绝，旧收据保留。可以重试（新 attempt），或新建独立重复计算。';
      case 'completed': return h('span', null, '计算完成。分层验收、曲线和指标对照见', h('a', { href: '#/run/' + s.run_id + '/results' }, '“结果”标签'), '；科学结论始终为“未建立”。');
      case 'failed': return '计算失败。重试会新建 attempt 和新目录，旧 attempt 及其失败证据完整保留，不追加预算。';
      case 'interrupted': return '计算已中断。重试会整案重跑（新 attempt），旧 attempt 保留。';
      case 'cancelled': return '已取消。已生成的文件不会删除。';
      default: return '';
    }
  }

  function retryInfo(s) {
    const attempt = s.attempts[s.attempts.length - 1];
    if (!attempt) return { used: 0, allowed: s.budget.retries, exhausted: false, attempt: null };
    const sameStage = s.attempts.filter((a) => a.stage === attempt.stage).length;
    const exhausted = sameStage > s.budget.retries || s.consumed_wall_seconds >= s.budget.wall_seconds;
    return { used: sameStage - 1, allowed: s.budget.retries, exhausted, attempt };
  }

  function actionList(s) {
    const st = s.execution_status;
    const retry = retryInfo(s);
    const needsReconcile = s.required_action === 'task.reconcile';
    const list = [];
    const add = (id, label, enabled, why, tone) => list.push({ id, label, enabled, why, tone });
    add('start', '提交计算', st === 'ready', '仅已冻结、尚未提交的任务可提交', st === 'ready' ? 'primary' : '');
    add('pause', st === 'running' ? '请求暂停' : '暂停', ['ready', 'queued', 'waiting_resource', 'running'].includes(st),
      st === 'pause_requested' ? '已请求暂停，等待阶段边界' : '当前状态不能暂停', '');
    add('resume', '恢复', st === 'paused', st === 'pause_requested' ? '尚未到达阶段边界' : '仅已在阶段边界暂停的任务可恢复', st === 'paused' ? 'primary' : '');
    const retryEnabled = ['failed', 'interrupted', 'blocked'].includes(st) && !retry.exhausted && retry.attempt && ['failed', 'interrupted'].includes(retry.attempt.execution_status);
    let retryWhy = '仅失败或中断的任务可重试';
    if (st === 'reconciling' || needsReconcile) retryWhy = '执行状态不确定时不能重试';
    else if (['failed', 'interrupted', 'blocked'].includes(st) && retry.exhausted) retryWhy = '重试次数或墙钟预算已用完，不能追加';
    add('retry', `重试（新 attempt，已用 ${retry.used} / 允许 ${retry.allowed} 次）`, retryEnabled, retryWhy, retryEnabled ? 'primary' : '');
    const reconcileEnabled = needsReconcile || ['queued', 'cancel_requested', 'reconciling'].includes(st);
    add('reconcile', st === 'queued' && !needsReconcile ? '核对并重新派发' : '核对', reconcileEnabled, '仅在需要确认 worker 状态时使用',
      needsReconcile || ['cancel_requested', 'reconciling'].includes(st) ? 'primary' : '');
    add('evaluate', '重新验收', st === 'completed', '仅计算完成的任务可重新验收', '');
    add('cancel', '取消任务', !TERMINAL.has(st), '已结束的任务不可变', 'danger');
    // At most one primary action per screen.
    let primary = false;
    for (const item of list) {
      if (item.tone === 'primary' && item.enabled) { if (primary) item.tone = ''; primary = true; }
    }
    return list;
  }

  function runView(gen, view, draw, refresh) {
    const s = view.status;
    const back = h('p', null, h('a', { href: '#/' }, '← 返回'));
    if (!s) return h('div', null, back, view.statusError ? errorBlock(view.statusError) : h('p', { class: 'muted' }, '正在读取…'));
    const frozenAt = view.events.find((e) => e.kind === 'task_frozen');
    const needsReconcile = s.required_action === 'task.reconcile';
    const worker = { running: '运行中', stopped: '已停止', unknown: '无法确认' }[s.worker_observation] || '—';
    const actions = actionList(s);
    const enabled = actions.filter((a) => a.enabled);
    const disabled = actions.filter((a) => !a.enabled);
    const busy = !!view.busy;
    const head = h('section', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h1', null, '任务 ' + (frozenAt ? fmtTime(frozenAt.time) : shortId(s.run_id))),
        h('details', { 'data-keep': 'tech' }, h('summary', null, '技术标识'),
          h('div', { class: 'mono' }, 'run_id ' + s.run_id), h('div', { class: 'mono' }, 'task_id ' + s.task_id),
          h('div', { class: 'mono' }, 'attempt_id ' + (s.attempt_id || '—')))),
      h('div', { class: 'status-head' },
        h('span', null, h('span', { class: 'label' }, '执行'), badge(STATE, s.execution_status)),
        h('span', null, h('span', { class: 'label' }, '验收'), needsReconcile ? h('span', { class: 'badge gray' }, '— 核对前不显示')
          : view.reportError && view.reportError.code === 'INTEGRITY_MISMATCH' ? h('span', { class: 'badge bad' }, '✕ 证据完整性校验失败')
            : badge(ACCEPTANCE, s.acceptance_status)),
        h('span', null, h('span', { class: 'label' }, '科学结论'), h('span', { class: 'badge gray' }, '— 未建立（本流程不评估）'))),
      h('div', { class: 'muted' }, `已用墙钟 ${fmtSeconds(s.consumed_wall_seconds)} / 预算 ${s.budget.wall_seconds} s　worker：${worker}　状态版本 v${s.state_version}`),
      needsReconcile ? h('div', { class: 'banner warn' }, 'worker 已不在运行，需要核对。核对前不显示任何结论。') : null,
      h('p', null, stateNote(s, view)),
      s.reason_code ? h('p', null, h('code', null, s.reason_code), ' ', reasonText(s.reason_code)) : null,
      view.notice && (view.noticeSticky || view.noticeVersion === s.state_version) ? view.notice : null,
      h('div', { class: 'actions' }, enabled.map((a) => h('div', { class: 'action' },
        h('button', { type: 'button', class: ['mutation', a.tone].join(' ').trim(), disabled: busy || offline,
          onclick: () => runAction(gen, view, a, draw) }, view.busy === a.id ? '处理中…' : a.label))),
        ['failed', 'interrupted', 'cancelled', 'blocked'].includes(s.execution_status)
          ? h('button', { type: 'button', class: 'secondary', onclick: () => { location.hash = '#/new?replicate=1'; } }, '新建独立重复计算') : null),
      disabled.length ? h('ul', { class: 'unavailable' }, disabled.map((a) => h('li', null, `${a.label.replace(/（.*$/, '')}：${a.why}`))) : null);

    const base = '#/run/' + s.run_id;
    const tabs = h('nav', { class: 'tabs' },
      h('a', { href: base, class: view.tab === 'overview' ? 'current' : '' }, '概览'),
      h('a', { href: base + '/results', class: view.tab === 'results' ? 'current' : '' }, '结果'),
      h('a', { href: base + '/artifacts', class: view.tab === 'artifacts' ? 'current' : '' }, '产物'),
      h('a', { href: base + '/events', class: view.tab === 'events' ? 'current' : '' }, `事件（${view.events.length}）`));
    let body;
    if (view.tab === 'events') body = eventsPanel(view.events);
    else if (view.tab === 'results') body = resultsPanel(s, view);
    else if (view.tab === 'artifacts') body = artifactsPanel(s, view);
    else body = overviewPanel(s, view);
    const review = view.tab === 'overview' ? reviewPanel(gen, s, view, draw) : null;
    return h('div', null, back, head, tabs, review, body);
  }

  function attemptMark(state) { return (STATE[state] || ['', '', '?'])[2]; }

  function overviewPanel(s, view) {
    const firstEvent = (kind) => view.events.find((e) => e.kind === kind);
    const lastOf = (stage) => [...s.attempts].reverse().find((a) => a.stage === stage);
    const caseAttempt = lastOf('paramaterial_case');
    const acceptanceAttempt = lastOf('acceptance');
    const acceptanceDone = ['accepted', 'rejected', 'criteria_met', 'failed_evidence', 'blocked'].includes(s.acceptance_status);
    const queued = firstEvent('attempt_queued');
    const frozen = firstEvent('task_frozen');
    const line = (mark, label, when) => h('li', null, h('span', { class: 'mark' }, mark), h('span', null, label), when ? h('span', { class: 'when' }, when) : null);
    return h('section', { class: 'panel' },
      h('h2', null, '阶段'),
      h('ul', { class: 'timeline' },
        line('✓', '冻结', frozen ? fmtTime(frozen.time, true) : null),
        line(s.attempts.length ? '✓' : '○', '排队', queued ? fmtTime(queued.time, true) : null),
        line(caseAttempt ? attemptMark(caseAttempt.execution_status) : '○', `${STAGES.paramaterial_case}（paramaterial_case）`,
          caseAttempt ? (STATE[caseAttempt.execution_status] || [caseAttempt.execution_status])[0] + ' · ' + fmtSeconds(caseAttempt.elapsed_seconds) : null),
        line(acceptanceDone ? (ACCEPTANCE[s.acceptance_status] || ['', '', '?'])[2] : acceptanceAttempt ? attemptMark(acceptanceAttempt.execution_status) : '○',
          '验收发布', acceptanceDone ? (ACCEPTANCE[s.acceptance_status] || [s.acceptance_status])[0] : acceptanceAttempt ? (STATE[acceptanceAttempt.execution_status] || [''])[0] : null)),
      h('h2', null, 'attempt'),
      s.attempts.length ? h('table', null,
        h('thead', null, h('tr', null, ['#', '阶段', '执行', '墙钟', '原因'].map((t) => h('th', null, t)))),
        h('tbody', null, s.attempts.map((a) => h('tr', null,
          h('td', null, '#' + a.number), h('td', null, STAGES[a.stage] || a.stage), h('td', null, badge(STATE, a.execution_status)),
          h('td', { class: 'num' }, fmtSeconds(a.elapsed_seconds)),
          h('td', null, a.reason_code ? [h('code', null, a.reason_code), ' ', reasonText(a.reason_code)] : '—'))))) : h('p', { class: 'muted' }, '尚未分配 attempt。'),
      h('h2', null, '最近事件'),
      view.events.length ? eventTable(view.events.slice(-5).reverse(), false) : h('p', { class: 'muted' }, '暂无事件。'),
      h('p', null, h('a', { href: '#/run/' + s.run_id + '/events' }, '查看全部事件 →')));
  }

  function eventLabel(e) {
    const base = EVENTS[e.kind];
    const data = e.data || {};
    if (e.kind === 'attempt_queued') return `${base}（#${data.number}，${STAGES[data.stage] || data.stage}）`;
    if (e.kind === 'control_requested') return `${base}：${ACTIONS[data.action] || data.action}（原因：${data.reason}）`;
    if (e.kind === 'recovery_rejected') return `${base}（${data.code}）`;
    if (e.kind === 'state_changed') return '状态：' + ((STATE[data.state] || [data.state])[0]) + (data.reason_code ? `（${data.reason_code}）` : '');
    if (e.kind === 'execution_started') return '开始执行' + (data.stage ? `（${STAGES[data.stage] || data.stage}）` : '');
    if (e.kind === 'acceptance_completed') return `验收完成：${(ACCEPTANCE[data.overall_acceptance] || [data.overall_acceptance])[0]}，科学结论未建立`;
    if (e.kind === 'attempt_failed') return `attempt 失败（${data.code}），失败证据已保留`;
    if (e.kind === 'operator_approved') return `${base}（审核人：${data.reviewer}，证据 ${(data.evidence_ids || []).length} 项）`;
    if (e.kind === 'handoff_submitted') return `${base}（证据 ${(data.evidence_ids || []).length} 项）`;
    if (base) return base;
    return '';
  }

  function eventTable(events, raw) {
    return h('table', null,
      h('thead', null, h('tr', null, ['#', '时间', '事件', raw ? '原始数据' : null].filter(Boolean).map((t) => h('th', null, t)))),
      h('tbody', null, events.map((e) => h('tr', null,
        h('td', { class: 'num' }, e.seq), h('td', null, fmtTime(e.time, true)),
        h('td', null, eventLabel(e), ' ', h('code', { class: 'muted' }, e.kind)),
        raw ? h('td', null, h('details', { 'data-keep': 'event-' + e.seq }, h('summary', null, 'JSON'), h('pre', { class: 'raw' }, JSON.stringify(e, null, 2)))) : null))));
  }

  function eventsPanel(events) {
    return h('section', { class: 'panel' },
      h('h2', null, '事件（新到旧）'),
      events.length ? eventTable([...events].reverse(), true) : h('p', { class: 'muted' }, '暂无事件。'));
  }

  // ---------- artifacts and report loading
  async function loadArtifacts(view) {
    const items = [];
    let cursor = 0;
    for (let i = 0; i < 20; i += 1) {
      const page = await api('artifacts.list', { run_id: view.runId, cursor, limit: 500 });
      if (!page.ok) { view.artifactsError = page.error; return; }
      items.push(...page.data.items);
      if (page.data.next_cursor === null || page.data.next_cursor === cursor) break;
      cursor = page.data.next_cursor;
    }
    view.artifacts = items;
    view.artifactsError = null;
    view.artifactsVersion = view.status.state_version;
  }

  async function loadReport(view) {
    const result = await api('reports.get', { run_id: view.runId });
    view.reportVersion = view.status.state_version;
    if (!result.ok) { view.report = null; view.reportError = result.error; return; }
    view.report = result.data;
    view.reportError = null;
    if (result.data.overall_acceptance === 'not_assessed' || !view.artifacts) return;
    const attemptId = reportAttempt(view);
    if (attemptId && !view.evidence[attemptId]) {
      view.evidence[attemptId] = { loading: true };
      loadEvidence(view, attemptId).then((evidence) => {
        view.evidence[attemptId] = evidence;
        if (view.draw) view.draw();
      });
    }
  }

  function reportAttempt(view) {
    if (view.report && view.report.attempt_id) return view.report.attempt_id;
    const done = view.status.attempts.filter((a) => a.execution_status === 'completed');
    return done.length ? done[done.length - 1].attempt_id : null;
  }

  function byPath(list) { return [...list].sort((a, b) => (a.relative_path < b.relative_path ? -1 : a.relative_path > b.relative_path ? 1 : 0)); }

  async function readAll(artifactId, fields) {
    const rows = [];
    let offset = 0;
    for (let i = 0; i < 40; i += 1) {
      const page = await api('artifacts.read', Object.assign({ artifact_id: artifactId, offset, limit: 500 }, fields));
      if (!page.ok) return { error: page.error };
      rows.push(...page.data.items);
      if (page.data.next_offset === null) return { rows };
      offset = page.data.next_offset;
    }
    return { rows };
  }

  // Reads the registered evidence files of one attempt. Values are shown as saved; the page computes nothing.
  async function loadEvidence(view, attemptId) {
    const files = view.artifacts.filter((a) => a.attempt_id === attemptId);
    const find = (path) => files.find((a) => a.relative_path === path);
    const evidence = { metrics: null, comparison: null, run: null, curves: [], errors: [] };
    try {
      const metrics = find('metrics.csv');
      if (metrics) { const r = await readAll(metrics.artifact_id, { view: 'csv' }); if (r.error) evidence.errors.push(['metrics.csv', r.error]); else evidence.metrics = r.rows; }
      const comparison = find('metrics_comparison.csv');
      if (comparison) { const r = await readAll(comparison.artifact_id, { view: 'csv' }); if (r.error) evidence.errors.push(['metrics_comparison.csv', r.error]); else evidence.comparison = r.rows; }
      const run = find('run.json');
      if (run) {
        const r = await api('artifacts.read', { artifact_id: run.artifact_id, view: 'json', offset: 0, limit: 1 });
        if (!r.ok) evidence.errors.push(['run.json', r.error]); else if (r.data.data) evidence.run = r.data.data;
      }
      for (const file of byPath(files.filter((a) => /^curves\/[^/]+\.csv$/.test(a.relative_path)))) {
        const r = await readAll(file.artifact_id, { view: 'csv', columns: ['original_strain', 'corrected_strain', 'engineering_stress_MPa'] });
        if (r.error) { evidence.errors.push([file.relative_path, r.error]); continue; }
        evidence.curves.push({ sample: file.relative_path.slice(7, -4),
          points: r.rows.map((row) => [Number(row.original_strain), Number(row.corrected_strain), Number(row.engineering_stress_MPa)]) });
      }
    } catch (e) {
      evidence.errors.push(['', { code: 'INTERNAL_ERROR' }]);
    }
    return evidence;
  }

  // ---------- results tab
  function layerRow(label, key, note) {
    return h('tr', null, h('th', null, label), h('td', null, badge(LAYER, key)), h('td', { class: 'muted small' }, note || ''));
  }

  function resultsPanel(s, view) {
    const panel = (...children) => h('section', { class: 'panel' }, ...children);
    if (view.reportError) {
      // Never show an older conclusion when the current evidence cannot be verified.
      return panel(h('h2', null, '分层验收'), errorBlock(view.reportError),
        view.reportError.code === 'INTEGRITY_MISMATCH' ? h('p', null, '当前文件与封存记录不一致，界面不显示任何验收结论、曲线或指标。可以“重新验收”或新建任务；原文件不会被删除。') : null);
    }
    const report = view.report;
    if (!report) return panel(h('p', { class: 'muted' }, '正在读取验收报告（核心会重新核对全部登记产物的哈希）…'));
    if (report.overall_acceptance === 'not_assessed') {
      return panel(h('h2', null, '分层验收'), h('p', null, '尚无验收报告。', ACTIVE.has(s.execution_status) ? '计算结束后会自动显示。' : '任务没有产生可验收的结果。'),
        h('p', null, h('span', { class: 'label muted' }, '科学结论 '), h('span', { class: 'badge gray' }, '— 未建立（本流程不评估）')));
    }
    const criteria = report.criterion_results || [];
    const met = criteria.filter((c) => c.status === 'met').length;
    const tol = report.numerical_checks.absolute_tolerance;
    const layers = panel(
      h('div', { class: 'panel-head' }, h('h2', null, '分层验收'),
        h('span', { class: 'muted small' }, report.evidence_integrity === 'verified_now' ? '证据已在本次读取时重新核对 ✓' : '')),
      h('table', { class: 'layers' }, h('tbody', null,
        h('tr', null, h('th', null, '执行'), h('td', null, badge(STATE, report.execution_status)), h('td', null)),
        layerRow('工程执行', report.engineering_status, '代码身份、执行范围、回读收据和图表文件'),
        layerRow('数据身份 / 单位 / 来源', report.data_status, '试样集合、行数、单位、来源哈希与逐行绑定'),
        layerRow('数值一致性', report.numerical_checks.status, criteria.length ? `${met} / ${criteria.length} 项在 ${tol} MPa 内与独立复算一致` : ''),
        layerRow('协议', report.protocol_status, '冻结时的输入与清单'),
        h('tr', { class: 'total' }, h('th', null, '总体验收'), h('td', null, badge(ACCEPTANCE, report.overall_acceptance)), h('td', null)),
        h('tr', null, h('th', null, '科学结论'), h('td', null, h('span', { class: 'badge gray' }, '— 未建立')),
          h('td', { class: 'muted small' }, '本流程只复现固定数据的处理与计算，不评估科学结论'))),
      ),
      report.issues && report.issues.length ? [h('h3', null, '问题'), h('ul', { class: 'issues' }, report.issues.map((i) =>
        h('li', null, h('code', null, i.code), i.field ? ` · ${i.field} ` : ' ', ERRORS[i.code] || '')))] : null,
      h('h3', null, '适用范围'),
      h('ul', { class: 'scope' }, (report.scope_limits || []).map((text) => h('li', null, SCOPE[text] || text, SCOPE[text] ? h('div', { class: 'muted small' }, text) : null))),
      h('details', { 'data-keep': 'report-tech' }, h('summary', null, '技术信息'),
        h('dl', { class: 'facts' },
          h('dt', null, '报告格式'), h('dd', null, h('code', null, report.format)),
          h('dt', null, 'attempt'), h('dd', null, h('code', null, report.attempt_id || '—')),
          h('dt', null, 'semantic_sha256'), h('dd', null, h('code', null, report.semantic_sha256 || '—')),
          h('dt', null, '验收范围'), h('dd', null, h('code', null, report.acceptance_scope || '—')))));
    const attemptId = reportAttempt(view);
    const evidence = attemptId ? view.evidence[attemptId] : null;
    if (!evidence || evidence.loading) return h('div', null, layers, panel(h('p', { class: 'muted' }, '正在读取曲线、指标和来源文件…')));
    return h('div', null, layers,
      evidence.errors.length ? panel(h('h2', null, '部分文件无法读取'), evidence.errors.map(([path, error]) => h('div', null, h('code', null, path), ' ', errorText(error)))) : null,
      chartPanel(view, evidence),
      comparisonPanel(report, evidence),
      provenancePanel(evidence.run));
  }

  function svgEl(tag, attrs, ...children) {
    const el = document.createElementNS(SVG_NS, tag);
    for (const [key, value] of Object.entries(attrs || {})) if (value !== null && value !== undefined) el.setAttribute(key, String(value));
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : String(child));
    }
    return el;
  }

  function niceTicks(min, max, count) {
    const span = max - min || 1;
    const raw = span / count;
    const power = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((m) => m >= raw);
    const ticks = [];
    for (let t = Math.ceil(min / step) * step; t <= max + step * 1e-9; t += step) ticks.push(Number(t.toPrecision(12)));
    return ticks;
  }

  function chartPanel(view, evidence) {
    if (!evidence.curves.length) return null;
    const chart = view.chart;
    const xi = chart.x === 'original' ? 0 : 1;
    const shown = evidence.curves.filter((c) => chart.sample === 'all' || c.sample === chart.sample);
    const metric = chart.sample !== 'all' && evidence.metrics ? evidence.metrics.find((m) => m.sample_id === chart.sample) : null;
    const W = 760; const H = 380; const L = 62; const R = 18; const T = 14; const B = 46;
    let xmin = Infinity; let xmax = -Infinity; let ymax = 0;
    for (const c of shown) for (const p of c.points) {
      if (isFinite(p[xi])) { xmin = Math.min(xmin, p[xi]); xmax = Math.max(xmax, p[xi]); }
      if (isFinite(p[2])) ymax = Math.max(ymax, p[2]);
    }
    if (!isFinite(xmin)) { xmin = 0; xmax = 1; }
    const ymin = 0;
    ymax *= 1.06;
    const sx = (x) => L + (x - xmin) / ((xmax - xmin) || 1) * (W - L - R);
    const sy = (y) => H - B - (y - ymin) / ((ymax - ymin) || 1) * (H - T - B);
    const xt = niceTicks(xmin, xmax, 6);
    const yt = niceTicks(ymin, ymax, 6);
    const grid = [
      xt.map((t) => [svgEl('line', { x1: sx(t), x2: sx(t), y1: T, y2: H - B, class: 'grid' }),
        svgEl('text', { x: sx(t), y: H - B + 16, class: 'tick', 'text-anchor': 'middle' }, fmtNum(t))]),
      yt.map((t) => [svgEl('line', { x1: L, x2: W - R, y1: sy(t), y2: sy(t), class: 'grid' }),
        svgEl('text', { x: L - 6, y: sy(t) + 4, class: 'tick', 'text-anchor': 'end' }, fmtNum(t))]),
      svgEl('line', { x1: L, x2: W - R, y1: H - B, y2: H - B, class: 'axis' }),
      svgEl('line', { x1: L, x2: L, y1: T, y2: H - B, class: 'axis' }),
      svgEl('text', { x: (L + W - R) / 2, y: H - 8, class: 'label', 'text-anchor': 'middle' }, chart.x === 'original' ? '原始应变（1）' : '修正后应变（1）'),
      svgEl('text', { x: 14, y: (T + H - B) / 2, class: 'label', 'text-anchor': 'middle', transform: `rotate(-90 14 ${(T + H - B) / 2})` }, '工程应力（MPa）')];
    const lines = shown.map((c) => svgEl('polyline', { class: 'curve s' + evidence.curves.indexOf(c),
      points: c.points.filter((p) => isFinite(p[xi]) && isFinite(p[2])).map((p) => sx(p[xi]).toFixed(1) + ',' + sy(p[2]).toFixed(1)).join(' ') },
    svgEl('title', null, c.sample)));
    const marks = [];
    if (metric) {
      const level = (value, name) => {
        const y = sy(Number(value));
        marks.push(svgEl('line', { x1: L, x2: W - R, y1: y, y2: y, class: 'ref' }),
          svgEl('text', { x: W - R - 4, y: y - 5, class: 'ref-label', 'text-anchor': 'end' }, `${name} = ${fmtNum(value)} MPa`));
      };
      const point = (x, y, name, raw) => marks.push(svgEl('circle', { cx: sx(Number(x)), cy: sy(Number(y)), r: 5, class: 'mark' },
        svgEl('title', null, `${name}：应变 ${raw}，应力 ${y} MPa`)));
      level(metric.Rp02_MPa, 'Rp0.2');
      level(metric.UTS_MPa, 'UTS');
      if (chart.x === 'corrected' && metric.proof_corrected_strain !== undefined) point(metric.proof_corrected_strain, metric.Rp02_MPa, 'Rp0.2', metric.proof_corrected_strain);
      if (chart.x === 'original' && metric.UTS_original_strain !== undefined) point(metric.UTS_original_strain, metric.UTS_MPa, 'UTS', metric.UTS_original_strain);
    }
    const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, class: 'chart', role: 'img', 'aria-label': '工程应力-应变曲线' }, grid, lines, marks);
    const pick = (key, value, label) => h('button', { type: 'button', class: chart[key] === value ? 'chip current' : 'chip',
      onclick: () => { chart[key] = value; view.draw(); } }, label);
    return h('section', { class: 'panel' },
      h('div', { class: 'panel-head' }, h('h2', null, '工程应力-应变曲线'),
        h('div', { class: 'chips' }, pick('x', 'corrected', '修正后应变'), pick('x', 'original', '原始应变'))),
      h('div', { class: 'chips' }, pick('sample', 'all', '全部试样'), evidence.curves.map((c) => pick('sample', c.sample, c.sample))),
      svg,
      h('div', { class: 'legend' }, shown.map((c) => h('span', null, h('span', { class: 'swatch s' + evidence.curves.indexOf(c) }), c.sample, `（${c.points.length} 行）`))),
      h('p', { class: 'muted small' }, chart.sample === 'all'
        ? '选择单个试样可标出 Rp0.2 和 UTS。曲线直接取自登记的 curves/*.csv，界面只绘图，不重新计算。'
        : '水平虚线和圆点的数值直接取自 metrics.csv，界面不重新计算。Rp0.2 的应变是修正后应变，UTS 的应变是原始应变，所以圆点只在对应的横轴下显示。'));
  }

  function comparisonPanel(report, evidence) {
    const criteria = new Map((report.criterion_results || []).map((c) => [c.criterion_id, c]));
    const rows = evidence.comparison || (report.criterion_results || []).map((c) => {
      const [sample, metric] = c.criterion_id.split('.');
      return { sample_id: sample, metric, pipeline_readback_method: c.value, independent_recalculation: c.reference };
    });
    if (!rows.length) return null;
    return h('section', { class: 'panel' },
      h('h2', null, '指标对照'),
      h('div', { class: 'scroll' }, h('table', { class: 'compare' },
        h('thead', null, h('tr', null, ['试样', '指标', '本流程（HDF5 回读）', '作者方法直算', '两者之差', '独立复算参考', '与参考之差', '容差', '判据'].map((t) => h('th', null, t)))),
        h('tbody', null, rows.map((row) => {
          const c = criteria.get(`${row.sample_id}.${row.metric}`);
          return h('tr', null, h('td', null, row.sample_id), h('td', null, METRICS[row.metric] || row.metric, h('div', { class: 'muted small' }, (c && c.unit) || 'MPa')),
            h('td', { class: 'num' }, num(row.pipeline_readback_method)), h('td', { class: 'num' }, num(row.direct_author_method)),
            h('td', { class: 'num' }, num(row.pipeline_minus_direct)), h('td', { class: 'num' }, num(row.independent_recalculation)),
            h('td', { class: 'num' }, num(row.minus_independent)), h('td', { class: 'num' }, c ? num(c.absolute_tolerance) : '—'),
            h('td', null, c ? badge(LAYER, c.status) : h('span', { class: 'badge gray' }, '— 无判据')));
        })))),
      h('p', { class: 'muted small' }, '数值保留 6 位有效数字，悬停可看保存的原值。判据来自验收报告；独立复算参考不是作者给出的逐试样真值。'),
      evidence.metrics ? h('details', { 'data-keep': 'metrics-all' }, h('summary', null, '全部指标（metrics.csv）'),
        h('div', { class: 'scroll' }, h('table', null,
          h('thead', null, h('tr', null, Object.keys(evidence.metrics[0] || {}).map((k) => h('th', null, k)))),
          h('tbody', null, evidence.metrics.map((m) => h('tr', null, Object.values(m).map((v) => h('td', { class: 'num' }, num(v))))))))) : null);
  }

  function provenancePanel(run) {
    if (!run) return null;
    const dataset = run.dataset || {};
    const pipeline = run.pipeline || {};
    const contributors = Array.isArray(dataset.contributors)
      ? dataset.contributors.map((c) => (typeof c === 'string' ? c : c && c.name ? c.name : JSON.stringify(c))).join('、') : dataset.contributors;
    const fact = (label, value) => [h('dt', null, label), h('dd', null, value === undefined || value === null || value === '' ? '—' : value)];
    return h('section', { class: 'panel' },
      h('h2', null, '来源与可追溯性'),
      h('dl', { class: 'facts' },
        fact('数据集', dataset.title), fact('DOI', dataset.doi ? h('code', null, dataset.doi) : null),
        fact('许可', dataset.license), fact('贡献者', contributors), fact('数据集地址', dataset.url ? h('code', null, dataset.url) : null),
        fact('示例提交', run.examples_commit ? h('code', null, run.examples_commit) : null),
        fact('参考值性质', REFERENCE_KIND[run.reference_kind] || run.reference_kind),
        fact('流程版本', pipeline.version), fact('Paramaterial 版本', run.paramaterial_version),
        fact('处理代码哈希', shortHash(run.processing_sha256)), fact('规范化代码哈希', shortHash(pipeline.normalization_sha256)),
        fact('运行时间', `${fmtTime(run.started_at_utc, true)} 至 ${fmtTime(run.finished_at_utc, true)}（${fmtSeconds(run.elapsed_seconds)}）`),
        fact('试样 / 总行数', `${run.cases_processed ?? '—'} / ${run.total_rows ?? '—'}`),
        fact('执行范围', `training_executed ${yesNo(run.training_executed)} · solver_executed ${yesNo(run.solver_executed)}`),
        fact('计算脚本自检', `来源哈希未变 ${yesNo(run.source_hashes_unchanged)} · 直算与回读一致 ${yesNo(run.pipeline_direct_metrics_exact)} · 独立回读通过 ${yesNo(run.independent_readback_passed)}`)),
      h('p', { class: 'muted small' }, '“计算脚本自检”是 run.json 中的自报字段；上方分层验收由核心独立核对，不信任这些标志。本机绝对路径不在界面显示。'),
      Array.isArray(run.cases) ? h('table', null,
        h('thead', null, h('tr', null, ['试样', '行数', '单位', '原始文件名'].map((t) => h('th', null, t)))),
        h('tbody', null, run.cases.map((c) => h('tr', null, h('td', null, c.sample_id), h('td', { class: 'num' }, c.rows),
          h('td', null, Object.entries(c.units || {}).map(([k, v]) => `${k}: ${v}`).join('，')), h('td', null, c.source_filename || '—'))))) : null,
      run.source_hashes ? h('details', { 'data-keep': 'source-hashes' }, h('summary', null, '来源文件哈希'),
        h('table', null, h('tbody', null, Object.entries(run.source_hashes).map(([name, hash]) => h('tr', null, h('td', null, name), h('td', { class: 'mono' }, hash)))))) : null);
  }

  // ---------- artifacts tab
  function viewKind(a) {
    const path = a.relative_path.toLowerCase();
    if (path.endsWith('.csv')) return 'csv';
    if (path.endsWith('.json')) return 'json';
    if (/\.(txt|log|md|ya?ml)$/.test(path)) return 'text';
    if (a.datasets && a.datasets.length) return 'hdf5';
    if (/\.(png|pdf)$/.test(path)) return 'image';
    return 'summary';
  }

  const PAGE = { csv: 100, json: 100, text: 200, hdf5: 100 };

  function openViewer(view, artifact) {
    const kind = viewKind(artifact);
    view.viewer = { artifact, kind, offset: 0, dataset: artifact.datasets ? artifact.datasets[0] : null, page: null, error: null, loading: kind !== 'image' && kind !== 'summary' };
    if (view.viewer.loading) loadViewerPage(view);
  }

  async function loadViewerPage(view) {
    const v = view.viewer;
    v.loading = true;
    if (view.draw) view.draw();
    const fields = { artifact_id: v.artifact.artifact_id, view: v.kind, offset: v.offset, limit: PAGE[v.kind] };
    if (v.kind === 'hdf5') fields.dataset = v.dataset;
    let result;
    try { result = await api('artifacts.read', fields); } catch (e) { v.loading = false; return; }
    if (view.viewer !== v) return;
    v.loading = false;
    if (result.ok) { v.page = result.data; v.error = null; } else { v.page = null; v.error = result.error; }
    if (view.draw) view.draw();
  }

  function attemptLabel(s, attemptId) {
    const a = s.attempts.find((x) => x.attempt_id === attemptId);
    return a ? `#${a.number} ${STAGES[a.stage] || a.stage}` : shortId(attemptId);
  }

  function artifactsPanel(s, view) {
    if (view.artifactsError) return h('section', { class: 'panel' }, errorBlock(view.artifactsError));
    if (!view.artifacts) return h('section', { class: 'panel' }, h('p', { class: 'muted' }, '正在读取登记产物…'));
    const groups = new Map();
    for (const a of view.artifacts) { if (!groups.has(a.attempt_id)) groups.set(a.attempt_id, []); groups.get(a.attempt_id).push(a); }
    if (!groups.size) {
      return h('section', { class: 'panel' }, h('h2', null, '产物'), h('p', { class: 'muted' }, '还没有登记的产物。只有完成封存（或失败留证）的 attempt 才会登记文件；进行中的文件不算产物。'));
    }
    const order = s.attempts.map((a) => a.attempt_id).filter((id) => groups.has(id));
    for (const id of groups.keys()) if (!order.includes(id)) order.push(id);
    if (!view.attemptChoice || !groups.has(view.attemptChoice)) view.attemptChoice = order[order.length - 1];
    const files = byPath(groups.get(view.attemptChoice));
    const select = h('select', { id: 'attempt-select', onchange: (e) => { view.attemptChoice = e.target.value; view.viewer = null; view.draw(); } },
      order.map((id) => h('option', { value: id, selected: id === view.attemptChoice }, `${attemptLabel(s, id)} · ${groups.get(id).length} 个文件`)));
    const chosen = view.viewer && view.viewer.artifact.attempt_id === view.attemptChoice ? view.viewer.artifact.artifact_id : null;
    return h('div', null,
      h('section', { class: 'panel' },
        h('div', { class: 'panel-head' }, h('h2', null, '登记产物'), h('label', null, 'attempt ', select)),
        h('p', { class: 'muted small' }, '只列出核心登记并封存的文件，按路径排序。重新验收会把同一批输出文件再登记到新的 attempt 下。'),
        h('table', null,
          h('thead', null, h('tr', null, ['路径', '类型', '大小', '验收', 'SHA-256'].map((t) => h('th', null, t)))),
          h('tbody', null, files.map((a) => h('tr', { class: 'clickable' + (a.artifact_id === chosen ? ' selected' : ''), tabindex: 0,
            onclick: () => { openViewer(view, a); view.draw(); },
            onkeydown: (e) => { if (e.key === 'Enter') { openViewer(view, a); view.draw(); } } },
          h('td', { class: 'mono' }, a.relative_path), h('td', { class: 'small' }, a.media_type), h('td', { class: 'num' }, fmtBytes(a.size_bytes)),
          h('td', null, badge(ACCEPTANCE, a.acceptance_status)), h('td', null, shortHash(a.sha256))))))),
      chosen ? viewerPanel(view) : null);
  }

  function viewerPanel(view) {
    const v = view.viewer;
    const a = v.artifact;
    const head = h('div', { class: 'panel-head' }, h('h2', null, a.relative_path),
      h('span', { class: 'muted small' }, `${a.media_type} · ${fmtBytes(a.size_bytes)}`));
    const panel = (...children) => h('section', { class: 'panel', id: 'viewer' }, head, ...children);
    if (v.kind === 'image') return panel(h('p', null, '第一版不在浏览器中预览图片和 PDF。曲线可在“结果”标签查看（由登记的 CSV 绘制）。'),
      h('p', { class: 'muted small' }, '文件位于任务目录对应 attempt 的 output 文件夹中，可在资源管理器中打开。'));
    if (v.kind === 'summary') return panel(h('p', null, '这种文件只提供摘要，不能在浏览器中读取内容。'));
    const datasetPicker = v.kind === 'hdf5' ? h('label', null, '数据集 ', h('select', { onchange: (e) => { v.dataset = e.target.value; v.offset = 0; loadViewerPage(view); } },
      a.datasets.map((d) => h('option', { value: d, selected: d === v.dataset }, d)))) : null;
    if (v.error) return panel(datasetPicker, errorBlock(v.error));
    if (!v.page) return panel(datasetPicker, h('p', { class: 'muted' }, '正在读取…'));
    const page = v.page;
    const go = (offset) => { v.offset = offset; loadViewerPage(view); };
    const pager = page.items ? h('div', { class: 'pager' },
      h('button', { type: 'button', class: 'secondary', disabled: v.loading || page.offset === 0, onclick: () => go(Math.max(0, page.offset - PAGE[v.kind])) }, '上一页'),
      h('span', { class: 'muted small' }, `第 ${page.offset + 1}–${page.offset + page.items.length} ${v.kind === 'text' ? '行' : '条'}${page.total !== null && page.total !== undefined ? '，共 ' + page.total : ''}`),
      h('button', { type: 'button', class: 'secondary', disabled: v.loading || page.next_offset === null, onclick: () => go(page.next_offset) }, '下一页')) : null;
    let body;
    if (page.view === 'csv') {
      body = h('div', { class: 'scroll' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, '#'), page.columns.map((c) => h('th', null, c)))),
        h('tbody', null, page.items.map((row, i) => h('tr', null, h('td', { class: 'num muted' }, page.offset + i + 1), page.columns.map((c) => h('td', { class: 'num' }, row[c])))))));
    } else if (page.view === 'json' && page.data) {
      body = h('pre', { class: 'raw tall' }, JSON.stringify(page.data, null, 2));
    } else if (page.view === 'json') {
      body = h('pre', { class: 'raw tall' }, page.items.map((item, i) => `[${page.offset + i}] ` + JSON.stringify(item)).join('\n'));
    } else if (page.view === 'text') {
      body = h('pre', { class: 'raw tall' }, page.items.join('\n'));
    } else if (page.view === 'hdf5') {
      body = h('div', null, h('p', { class: 'muted small' }, `形状 [${page.shape.join(', ')}] · ${page.dtype}`),
        h('div', { class: 'scroll' }, h('table', null, h('thead', null, h('tr', null, h('th', null, '索引'), h('th', null, '值'))),
          h('tbody', null, page.items.map((item, i) => h('tr', null, h('td', { class: 'num muted' }, page.offset + i),
            h('td', { class: 'num' }, Array.isArray(item) ? item.join(', ') : String(item))))))));
    } else {
      body = h('p', { class: 'muted' }, '摘要：' + JSON.stringify(page));
    }
    return panel(datasetPicker, pager, body);
  }

  // ---------- human review (waiting_human)
  function approvedNote(approved, state, draw) {
    const ids = approved.data.evidence_ids || [];
    const same = ids.length === state.selected.size && ids.every((id) => state.selected.has(id));
    return h('div', null,
      h('div', { class: 'receipt' }, `操作者已批准 ✓ 审核人：${approved.data.reviewer}；依据：${approved.data.basis}；证据 ${ids.length} 项`,
        same ? '（已按批准记录勾选）' : ''),
      same ? null : h('div', { class: 'banner warn' }, '当前勾选与批准记录不一致，提交会被核心拒绝（EVIDENCE_STALE）。 ',
        h('button', { type: 'button', class: 'secondary', onclick: () => { state.selected = new Set(ids); state.touched = false; state.synced = approved.seq; draw(); } }, '按批准记录重新勾选')));
  }

  function reviewPanel(gen, s, view, draw) {
    if (s.execution_status !== 'waiting_human' || !view.handoffs) return null;
    const handoff = view.handoffs.find((x) => x.state === 'pending' || x.state === 'approved');
    if (!handoff) return null;
    const approved = [...view.events].reverse().find((e) => e.kind === 'operator_approved' && e.data && e.data.handoff_id === handoff.handoff_id);
    let state = view.review[handoff.handoff_id];
    if (!state) state = view.review[handoff.handoff_id] = { selected: new Set(), approvalId: '', touched: false, synced: null };
    if (approved && !state.touched && state.synced !== approved.seq) {
      state.selected = new Set(approved.data.evidence_ids || []);
      state.synced = approved.seq;
    }
    const files = byPath((view.artifacts || []).filter((a) => a.attempt_id === handoff.attempt_id));
    const command = h('pre', { class: 'command', id: 'approve-command' });
    const submit = h('button', { type: 'button', class: 'mutation primary', id: 'submit-handoff' }, view.busy === 'submit' ? '处理中…' : '提交已批准证据');
    const countNote = h('span', { class: 'muted small' });
    const sync = () => {
      const ids = [...state.selected].sort();
      command.textContent = ids.length
        ? ['pipeline harness approve', `--workspace "${session.workspace}"`, `--handoff-id ${handoff.handoff_id}`,
          ...ids.map((id) => `--evidence-id ${id}`), '--reviewer "<审核人>"', '--basis "<审核依据>"'].join(' ')
        : '（请先在第 1 步勾选证据）';
      countNote.textContent = `已选 ${ids.length} / 最多 30 项`;
      submit.disabled = !!view.busy || offline || !ids.length || ids.length > 30 || !state.approvalId.trim();
    };
    const toggle = (id, on) => { state.touched = true; if (on) state.selected.add(id); else state.selected.delete(id); sync(); };
    const boxes = files.map((a) => h('li', null, h('label', { class: 'check' },
      h('input', { type: 'checkbox', checked: state.selected.has(a.artifact_id), onchange: (e) => toggle(a.artifact_id, e.target.checked) }),
      h('span', null, h('span', { class: 'mono' }, a.relative_path), ' ', h('span', { class: 'muted small' }, fmtBytes(a.size_bytes)))),
    h('a', { href: `#/run/${s.run_id}/artifacts?artifact=${a.artifact_id}`, class: 'small' }, '查看')));
    const approval = h('input', { type: 'text', id: 'approval-id', maxlength: 128, autocomplete: 'off', spellcheck: 'false', placeholder: '终端返回的 approval_id',
      oninput: (e) => { state.approvalId = e.target.value; sync(); } });
    approval.value = state.approvalId;
    const copy = h('button', { type: 'button', class: 'secondary', onclick: async () => {
      if (!state.selected.size) return;
      try { await navigator.clipboard.writeText(command.textContent); copy.textContent = '已复制 ✓'; } catch (e) { copy.textContent = '复制失败，请手动选中'; }
    } }, '复制');
    submit.addEventListener('click', async () => {
      const ids = [...state.selected].sort();
      const ok = await confirmDialog('提交已批准证据', '确认提交', h('div', null,
        h('p', null, `将把 ${ids.length} 项证据和 approval_id 提交给核心。核心会核对它们与操作者的批准记录完全一致，然后重新核对证据并进入验收。`),
        h('p', { class: 'muted small' }, '这不表示验收通过；如果证据与批准记录不一致，核心会拒绝（EVIDENCE_STALE）。')), false);
      if (!ok || !current(gen)) return;
      runAction(gen, view, { id: 'submit', payload: { handoff_id: handoff.handoff_id, attempt_id: handoff.attempt_id, approval_id: state.approvalId.trim(), evidence_ids: ids } }, draw);
    });
    sync();
    return h('section', { class: 'panel review' },
      h('div', { class: 'panel-head' }, h('h2', null, '⏸ 人工审核'), h('span', { class: 'muted small' }, `handoff 已打开（计算已稳定） · ${attemptLabel(s, handoff.attempt_id)}`)),
      h('p', null, '这是对固定结果的审核，不是修改材料参数的授权。浏览器不能批准；批准由操作者在终端执行命令完成。'),
      h('h3', null, '1 选择证据'),
      files.length ? [h('div', { class: 'actions' },
        h('button', { type: 'button', class: 'secondary', onclick: () => { state.touched = true; state.selected = new Set(files.slice(0, 30).map((a) => a.artifact_id)); draw(); } }, '全选'),
        h('button', { type: 'button', class: 'secondary', onclick: () => { state.touched = true; state.selected = new Set(); draw(); } }, '清空'), countNote),
      h('ul', { class: 'evidence' }, boxes)] : h('p', { class: 'muted' }, '正在读取本 attempt 的登记产物…'),
      h('h3', null, '2 操作者命令（在终端执行）'),
      h('div', { class: 'command-row' }, command, copy),
      h('p', { class: 'muted small' }, '“审核人”和“审核依据”由你在终端填写，界面不预填。命令会打印 approval_id。'),
      approved ? approvedNote(approved, state, draw) : h('div', { class: 'actions' },
        h('span', { class: 'muted small' }, '在终端批准后，点“重新读取”可按批准记录预填证据。'),
        h('button', { type: 'button', class: 'secondary', onclick: () => view.refresh() }, '重新读取')),
      h('h3', null, '3 粘贴 approval_id 并提交'),
      h('div', { class: 'actions' }, approval, submit));
  }

  // ---------- mutations
  function confirmDialog(title, okLabel, body, danger) {
    const dialog = document.getElementById('confirm-dialog');
    document.getElementById('confirm-title').textContent = title;
    const okButton = document.getElementById('confirm-ok');
    okButton.textContent = okLabel;
    okButton.className = danger ? 'danger' : 'primary';
    document.getElementById('confirm-body').replaceChildren(body);
    return new Promise((resolve) => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true });
      dialog.returnValue = '';
      dialog.showModal();
    });
  }

  async function runAction(gen, view, action, draw) {
    const s = view.status;
    const v = s.state_version;
    const attempt = s.attempts[s.attempts.length - 1];
    let tool;
    let fields;
    const control = (name, reason, extra) => {
      tool = 'task.control';
      fields = Object.assign({ run_id: s.run_id, idempotency_key: `ui:control:${name}:${s.run_id}:v${v}`, expected_state_version: v, action: name, reason }, extra || {});
    };
    if (action.id === 'cancel') {
      const key = `ui:control:cancel:${s.run_id}:v${v}`;
      const locked = getItem(REASON_PREFIX + key);
      const reason = h('textarea', { id: 'cancel-reason', required: true, maxlength: 1024, readonly: locked !== null, placeholder: '必填，例如：参数设置错误' });
      reason.value = locked || '';
      const ok = await confirmDialog('取消任务', '确认取消', h('div', null,
        h('p', null, '停止本任务拥有的进程树。只有确认停止后才显示“已取消”。已生成的文件不会删除。'),
        h('label', { for: 'cancel-reason' }, '原因'), reason,
        locked !== null ? h('p', { class: 'muted small' }, '同一状态下的取消请求已提交过，原因已锁定，重发会得到相同结果。') : null), true);
      if (!ok || !current(gen) || !reason.value.trim()) return;
      setItem(REASON_PREFIX + key, reason.value.trim());
      control('cancel', reason.value.trim());
    } else if (action.id === 'pause') control('pause', '界面请求暂停');
    else if (action.id === 'resume') control('resume', '界面请求恢复');
    else if (action.id === 'retry') control('retry', '界面请求重试', { stage: attempt.stage, attempt_id: attempt.attempt_id });
    else if (action.id === 'start') { tool = 'task.start'; fields = { run_id: s.run_id, idempotency_key: `ui:start:${s.run_id}:v${v}`, expected_state_version: v }; }
    else if (action.id === 'evaluate') { tool = 'evaluation.start'; fields = { run_id: s.run_id, idempotency_key: `ui:evaluate:${s.run_id}:v${v}`, expected_state_version: v }; }
    else if (action.id === 'reconcile') { tool = 'task.reconcile'; fields = { run_id: s.run_id, idempotency_key: `ui:reconcile:${s.run_id}:v${v}` }; }
    else if (action.id === 'submit') {
      // The approval id and evidence are part of the key, so a corrected paste is a new request rather than a conflict.
      const p = action.payload;
      tool = 'handoffs.submit';
      fields = Object.assign({ run_id: s.run_id, idempotency_key: `ui:handoff:${s.run_id}:v${v}:${fingerprint(p.approval_id + '|' + p.evidence_ids.join(','))}`, expected_state_version: v }, p);
    } else return;

    view.busy = action.id; view.notice = null; draw();
    let result;
    try { result = await api(tool, fields); } catch (e) { view.busy = null; return; }
    if (!current(gen)) return;
    view.busy = null;
    if (result.ok) {
      view.status = result.data;
      const done = { start: '已提交排队 ✓（这不表示计算完成）', evaluate: '已提交重新验收 ✓（这不表示验收通过）',
        reconcile: '已核对 ✓（结果以上方执行状态为准）', retry: '已新建 attempt 并排队 ✓（这不表示计算完成）',
        pause: '已请求暂停 ✓（在阶段边界生效）', resume: '已请求恢复 ✓', cancel: '已提交取消请求 ✓（以上方执行状态为准）',
        submit: '已提交已批准证据 ✓（核心会按批准记录重新核对证据并验收；这不表示验收通过）' }[action.id];
      view.notice = h('div', { class: 'receipt' }, done);
    } else {
      view.notice = errorBlock(result.error);
    }
    await view.refresh();
    // A receipt belongs to the state it was produced in and clears on the next change; an error stays until the next action.
    view.noticeVersion = view.status.state_version;
    view.noticeSticky = !result.ok;
    draw();
  }

  // ---------- boot
  async function boot() {
    document.getElementById('open-capabilities').addEventListener('click', openCapabilities);
    document.getElementById('close-capabilities').addEventListener('click', () => document.getElementById('capabilities-dialog').close());
    const match = /^#token=([A-Za-z0-9_-]+)/.exec(location.hash);
    if (match) {
      setItem(TOKEN_KEY, match[1]);
      history.replaceState(null, '', location.pathname + '#/');
    }
    token = getItem(TOKEN_KEY);
    if (!token) {
      connection.dataset.state = 'lost';
      connection.textContent = '缺少访问令牌';
      app.replaceChildren(h('div', { class: 'banner bad' }, '缺少访问令牌。请使用启动界面时终端打印的完整地址（含 #token=…）打开。'));
      return;
    }
    try {
      session = await fetchSession();
    } catch (e) {
      if (e instanceof TransportError) return;
      goOffline();
      return;
    }
    markConnected();
    window.addEventListener('hashchange', route);
    route();
  }

  boot();
}());
