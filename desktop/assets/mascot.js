// ============================================================================
// cc-tracker 萌宠（苹果造型）—— 从 AI 洞察萌宠组件派生，独立演进。
// 三态：进行中(雷达扫描) / 已完成(绿气泡+蹦跳+绿徽章) / 等你输入(红色急态徽章)。
// 「等你输入」是相对生态"叮一声"工具的核心差异 —— 用与"完成绿"区分的红色脉动徽章显眼提示。
// 暴露 API：window.Mascot = { show, hide, toggle, setBusy, notify, setBadge, setAttention, setOnView, setPeek }
// ============================================================================
(function () {
  if (window.Mascot) return;
  const RED = '#e11d32', RED_DARK = '#b91c2e', INK = '#1f2024';
  const HIDDEN_KEY = 'mascot_hidden';

  const selfScript = document.currentScript;
  const HOME_URL = (selfScript && selfScript.getAttribute('data-home')) || '/';

  const style = document.createElement('style');
  style.textContent = `
.mascot {
  position: fixed; right: 26px; bottom: 26px;
  width: 78px; height: 92px;
  border: none; background: transparent; cursor: pointer;
  padding: 0; z-index: 2147483000;
  filter: drop-shadow(0 8px 16px rgba(225,29,50,.22));
  animation: mascot-bob 3.2s ease-in-out infinite;
}
.mascot[hidden] { display: none; }
.mascot { touch-action: none; user-select: none; -webkit-user-select: none; }
.mascot:hover { animation-play-state: paused; }
.mascot:hover .mascot-body { transform: scale(1.05); }
.mascot.dragging { animation: none; cursor: grabbing; }
.mascot.dragging .mascot-body { transform: scale(1.08); }
@keyframes mascot-bob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-6px)} }
.mascot-body { width: 100%; height: 100%; display: block; transition: transform .18s ease; }
.mascot .m-head { fill: ${RED}; }
.mascot .m-visor { fill: #fff; opacity:.18; }
.mascot .m-leaf { fill: #16a34a; }
.mascot .m-eye-white { fill: #fff; }
.mascot .m-pupil { fill: ${INK}; transition: cx .12s linear, cy .12s linear; }
.mascot .m-spark { fill: #fff; }
.mascot .m-antenna { stroke: #7c4a22; stroke-width: 3; stroke-linecap: round; }
.mascot .m-emitter { fill: ${RED_DARK}; }
.mascot .m-hand { fill: ${RED_DARK}; display: none; }
.mascot.peek { animation: none; }
.mascot.peek .m-hand { display: inline; }
.mascot.peek .mascot-body { transition: transform .25s ease; }
.mascot.peek-bottom .mascot-body { transform: translateY(46%); }
.mascot.peek-top    .mascot-body { transform: translateY(-46%) rotate(180deg); }
.mascot.peek-left   .mascot-body { transform: translateX(-46%) rotate(90deg); }
.mascot.peek-right  .mascot-body { transform: translateX(46%) rotate(-90deg); }
.mascot.peek .m-eyes { transform-box: fill-box; transform-origin: center; transform: translateY(-8px) scale(1.2); transition: transform .25s ease; }
.mascot .m-eye { transform-box: fill-box; transform-origin: center; animation: mascot-blink 4.6s infinite; }
@keyframes mascot-blink { 0%,92%,100%{transform:scaleY(1)} 96%{transform:scaleY(.1)} }
.mascot .m-ping { fill: none; stroke: ${RED}; stroke-width: 2; transform-box: fill-box; transform-origin: center;
  opacity: 0; animation: mascot-ping 2.4s ease-out infinite; }
.mascot .m-ping.p2 { animation-delay: 1.2s; }
@keyframes mascot-ping { 0%{transform:scale(.4);opacity:.7} 70%{opacity:.15} 100%{transform:scale(3.2);opacity:0} }
.mascot.busy .m-ping { animation-duration: 1s; }
.mascot.busy { animation-play-state: paused; }
.mascot-bubble {
  position: absolute; right: 50%; bottom: 100%; transform: translate(50%, -8px);
  background: ${INK}; color: #fff; font-size: 12px; white-space: nowrap;
  font-family: -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  padding: 5px 10px; border-radius: 8px; opacity: 0; pointer-events: none; transition: opacity .15s;
}
.mascot-bubble::after { content:''; position:absolute; top:100%; right:50%; transform:translateX(50%);
  border: 5px solid transparent; border-top-color: ${INK}; }
.mascot:hover .mascot-bubble, .mascot.busy .mascot-bubble, .mascot.attention .mascot-bubble { opacity: 1; }
/* 等你输入：气泡转红，强提示 */
.mascot.attention .mascot-bubble { background: ${RED}; }
.mascot.attention .mascot-bubble::after { border-top-color: ${RED}; }
.mascot-ring {
  position: absolute; top: -2px; right: -2px; width: 22px; height: 22px; border-radius: 50%;
  background: #fff; border: 2.5px solid #edeef1; border-top-color: ${RED};
  box-shadow: 0 2px 6px rgba(0,0,0,.15); opacity: 0; animation: mascot-spin .7s linear infinite;
}
.mascot.busy .mascot-ring { opacity: 1; }
@keyframes mascot-spin { to { transform: rotate(360deg); } }
.mascot.notify .mascot-bubble { opacity: 1; background: #16a34a; }
.mascot.notify .mascot-bubble::after { border-top-color: #16a34a; }
.mascot.notify { animation: mascot-celebrate .5s ease 3; }
@keyframes mascot-celebrate { 0%,100%{transform:translateY(0) scale(1)} 35%{transform:translateY(-12px) scale(1.1)} }
/* 天线头未读徽章：默认绿色(已完成未看)；带 .attention 时转红色脉动(有会话在等你) */
.mascot-badge {
  position: absolute; left: 50%; top: 11%;
  transform: translate(-50%, -50%) scale(0);
  min-width: 18px; height: 18px; padding: 0 4px; box-sizing: border-box;
  border-radius: 9px; background: #16a34a; color: #fff;
  font: 700 11px/16px -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
  text-align: center; border: 2px solid #fff;
  box-shadow: 0 2px 6px rgba(0,0,0,.28);
  cursor: pointer; pointer-events: auto; z-index: 3;
  transition: transform .22s cubic-bezier(.34,1.56,.64,1);
}
.mascot-badge.show { transform: translate(-50%, -50%) scale(1); }
.mascot-badge:hover { background: #15803d; }
.mascot-badge.attention { background: ${RED}; animation: mascot-badge-pulse 1.1s ease-in-out infinite; }
.mascot-badge.attention:hover { background: ${RED_DARK}; }
@keyframes mascot-badge-pulse {
  0%,100% { box-shadow: 0 2px 6px rgba(0,0,0,.28), 0 0 0 0 rgba(225,29,50,.55); }
  60%     { box-shadow: 0 2px 6px rgba(0,0,0,.28), 0 0 0 8px rgba(225,29,50,0); }
}
`;
  document.head.appendChild(style);

  const btn = document.createElement('button');
  btn.className = 'mascot';
  btn.id = 'mascot';
  btn.title = '点我看各会话状态（右键可隐藏）';
  btn.setAttribute('aria-label', 'Claude Code 任务状态');
  btn.innerHTML = `
    <span class="mascot-bubble" id="mascotBubble">点我看任务</span>
    <span class="mascot-ring"></span>
    <svg class="mascot-body" viewBox="0 0 100 104" aria-hidden="true">
      <circle class="m-ping" cx="50" cy="12" r="6"/>
      <circle class="m-ping p2" cx="50" cy="12" r="6"/>
      <path class="m-leaf" d="M53 27 C60 16 72 16 77 21 C72 30 59 32 53 27 Z"/>
      <line class="m-antenna" x1="50" y1="32" x2="50" y2="15"/>
      <circle class="m-emitter" cx="50" cy="12" r="4"/>
      <ellipse class="m-hand" cx="12" cy="60" rx="8" ry="6"/>
      <ellipse class="m-hand" cx="88" cy="60" rx="8" ry="6"/>
      <path class="m-head" d="M50 32 C43 23 31 22 23 28 C13 35 11 48 13 60 C15 74 29 90 50 90 C71 90 85 74 87 60 C89 48 87 35 77 28 C69 22 57 23 50 32 Z"/>
      <ellipse class="m-visor" cx="32" cy="46" rx="7" ry="12" transform="rotate(-18 32 46)"/>
      <g class="m-eyes">
        <g class="m-eye">
          <ellipse class="m-eye-white" cx="36" cy="55" rx="13.5" ry="15.5"/>
          <circle class="m-pupil" id="mPupilL" cx="36" cy="56" r="7.5"/>
          <circle class="m-spark" cx="33" cy="51" r="2.8"/>
        </g>
        <g class="m-eye">
          <ellipse class="m-eye-white" cx="64" cy="55" rx="13.5" ry="15.5"/>
          <circle class="m-pupil" id="mPupilR" cx="64" cy="56" r="7.5"/>
          <circle class="m-spark" cx="61" cy="51" r="2.8"/>
        </g>
      </g>
    </svg>`;
  document.body.appendChild(btn);

  const badge = document.createElement('span');
  badge.className = 'mascot-badge';
  badge.setAttribute('aria-label', '待处理');
  btn.appendChild(badge);

  const bubble = btn.querySelector('#mascotBubble');
  const pupils = [btn.querySelector('#mPupilL'), btn.querySelector('#mPupilR')];
  const base = { mPupilL: { x: 36, y: 56 }, mPupilR: { x: 64, y: 56 } };

  const IDLE_TXT = '点我看任务', BUSY_TXT = '任务进行中…';

  function goHome() {
    if (typeof window.MascotHome === 'function') window.MascotHome();
    else window.location.assign(HOME_URL);
  }
  function hide() { btn.hidden = true; try { localStorage.setItem(HIDDEN_KEY, '1'); } catch (e) {} }
  function show() { btn.hidden = false; try { localStorage.removeItem(HIDDEN_KEY); } catch (e) {} }
  function toggle() { btn.hidden ? show() : hide(); }
  function setBusy(on) {
    btn.classList.toggle('busy', !!on);
    if (!btn.classList.contains('notify') && !btn.classList.contains('attention'))
      bubble.textContent = on ? BUSY_TXT : IDLE_TXT;
  }

  let unread = 0, onViewCb = null;
  function setBadge(n) {
    unread = Math.max(0, n | 0);
    badge.textContent = unread > 99 ? '99+' : String(unread);
    badge.classList.toggle('show', unread > 0);
  }
  function setOnView(cb) { onViewCb = (typeof cb === 'function') ? cb : null; }

  // 等你输入急态：红色脉动徽章 + 红气泡文案。n<=0 解除。
  function setAttention(n, opts) {
    opts = opts || {};
    const on = (n | 0) > 0;
    btn.classList.toggle('attention', on);
    badge.classList.toggle('attention', on);
    if (on) {
      setBadge(n);
      if (typeof opts.onView === 'function') onViewCb = opts.onView;
      if (!btn.classList.contains('notify'))
        bubble.textContent = opts.text || (n + ' 个会话在等你');
    } else {
      bubble.textContent = btn.classList.contains('busy') ? BUSY_TXT : IDLE_TXT;
    }
  }

  badge.addEventListener('pointerdown', e => e.stopPropagation());
  badge.addEventListener('click', e => {
    e.stopPropagation();
    // 不在这里清零——交给回调决定开哪个会话、还剩几个（支持"按时间逐个打开"）。
    if (typeof onViewCb === 'function') onViewCb();
  });

  let notifyTimer = null, peekRestore = null;
  function notify(text, opts) {
    if (typeof opts === 'number') opts = { duration: opts };
    opts = opts || {};
    if (typeof opts.count === 'number') setBadge(opts.count);
    if (typeof opts.onView === 'function') onViewCb = opts.onView;
    if (notifyTimer) clearTimeout(notifyTimer);
    if (peekRestore === null) {
      const m = btn.className.match(/peek-(left|right|top|bottom)/);
      peekRestore = m ? m[1] : '';
    }
    clearPeek();
    bubble.textContent = text || '完成 ✅';
    btn.classList.remove('notify');
    void btn.offsetWidth;
    btn.classList.add('notify');
    notifyTimer = setTimeout(() => {
      btn.classList.remove('notify');
      if (btn.classList.contains('attention')) { /* 急态文案由 setAttention 维护 */ }
      else bubble.textContent = btn.classList.contains('busy') ? BUSY_TXT : IDLE_TXT;
      if (peekRestore) setPeek(peekRestore);
      peekRestore = null;
      notifyTimer = null;
    }, opts.duration || 4200);
  }

  // ---- 位置记忆 + 拖拽 + 扒边折叠态 ----
  const POS_KEY = 'mascot_pos';
  const SNAP = 30;
  function applyPos(left, top) {
    btn.style.left = left + 'px'; btn.style.top = top + 'px';
    btn.style.right = 'auto'; btn.style.bottom = 'auto';
  }
  function clearPeek() { btn.classList.remove('peek', 'peek-left', 'peek-right', 'peek-top', 'peek-bottom'); }
  function setPeek(dir) { clearPeek(); btn.classList.add('peek', 'peek-' + dir); }
  function settle(rawLeft, rawTop, w, h) {
    const vw = window.innerWidth, vh = window.innerHeight;
    let left = Math.max(4, Math.min(vw - w - 4, rawLeft));
    let top  = Math.max(4, Math.min(vh - h - 4, rawTop));
    const dist = { left: left - 0, right: vw - (left + w), top: top - 0, bottom: vh - (top + h) };
    const dir = Object.keys(dist).reduce((a, b) => dist[a] <= dist[b] ? a : b);
    if (dist[dir] <= SNAP) {
      if (dir === 'left') left = 0;
      else if (dir === 'right') left = vw - w;
      else if (dir === 'top') top = 0;
      else top = vh - h;
      return { left, top, peek: dir };
    }
    return { left, top, peek: null };
  }
  function restore() {
    try {
      const p = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
      if (!p || typeof p.left !== 'number') return;
      applyPos(p.left, p.top);
      if (p.peek) setPeek(p.peek);
    } catch (e) {}
  }
  restore();
  window.addEventListener('resize', () => { if (!btn.hidden && localStorage.getItem(POS_KEY)) restore(); });

  const host = () => (window.MascotHost && window.MascotHost.windowDrag) ? window.MascotHost : null;

  let drag = null;
  btn.addEventListener('pointerdown', e => {
    if (e.button !== 0) return;
    const r = btn.getBoundingClientRect();
    drag = { sx: e.clientX, sy: e.clientY, ox: r.left, oy: r.top, moved: false };
    btn.setPointerCapture(e.pointerId);
    const H = host(); if (H && H.dragStart) H.dragStart(e.screenX, e.screenY);
  });
  btn.addEventListener('pointermove', e => {
    if (!drag) return;
    const dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true; btn.classList.add('dragging');
    const H = host();
    if (H) { if (H.dragMove) H.dragMove(e.screenX, e.screenY); return; }
    clearPeek();
    const w = btn.offsetWidth, h = btn.offsetHeight;
    const left = Math.max(4, Math.min(window.innerWidth - w - 4, drag.ox + dx));
    const top  = Math.max(4, Math.min(window.innerHeight - h - 4, drag.oy + dy));
    applyPos(left, top);
  });
  btn.addEventListener('pointerup', () => {
    if (!drag) return;
    const H = host();
    if (drag.moved) {
      btn.classList.remove('dragging');
      if (H) { if (H.dragEnd) H.dragEnd(); }
      else {
        const r = btn.getBoundingClientRect();
        const s = settle(r.left, r.top, btn.offsetWidth, btn.offsetHeight);
        applyPos(s.left, s.top);
        if (s.peek) setPeek(s.peek); else clearPeek();
        try { localStorage.setItem(POS_KEY, JSON.stringify(s)); } catch (e) {}
      }
    } else {
      goHome();
    }
    drag = null;
  });
  btn.addEventListener('contextmenu', e => { e.preventDefault(); hide(); });

  window.addEventListener('mousemove', e => {
    if (btn.hidden) return;
    const r = btn.getBoundingClientRect();
    const a = Math.atan2(e.clientY - (r.top + r.height / 2), e.clientX - (r.left + r.width / 2));
    const dx = Math.cos(a) * 2.6, dy = Math.sin(a) * 2.6;
    pupils.forEach(p => { const b = base[p.id]; p.setAttribute('cx', b.x + dx); p.setAttribute('cy', b.y + dy); });
  }, { passive: true });

  try { if (localStorage.getItem(HIDDEN_KEY) === '1') btn.hidden = true; } catch (e) {}

  window.Mascot = {
    show, hide, toggle, setBusy, notify, setBadge, setAttention, setOnView,
    setPeek: (dir) => (dir ? setPeek(dir) : clearPeek()),
  };
})();
