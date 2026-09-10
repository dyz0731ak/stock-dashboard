/* Company descriptions are cached separately from market quotes. */
(() => {
  'use strict';
  let companies = {}, loading = true, activeCode = null, opener = null;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const safeURL = value => {
    try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) && !u.username ? u.href : ''; }
    catch { return ''; }
  };
  const usable = p => p?.description && Date.now() >= Date.parse(p.fetched_at) && Date.now() - Date.parse(p.fetched_at) < 30 * 86400000;
  const summary = code => usable(companies[code]) ? companies[code].summary : '事業内容は企業詳細へ';
  const link = (url, label) => safeURL(url) ? `<a href="${esc(safeURL(url))}" target="_blank" rel="noopener noreferrer">${esc(label)} <span aria-hidden="true">↗</span></a>` : '';
  const dateLabel = value => {
    const date = new Date(value);
    return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat('ja-JP', {timeZone:'Asia/Tokyo', year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', hour12:false}).format(date) + ' JST' : '未取得';
  };
  const dialog = document.createElement('dialog');
  dialog.className = 'company-dialog';
  dialog.setAttribute('aria-labelledby', 'companyTitle');
  document.body.appendChild(dialog);

  function paint() {
    const p = companies[activeCode] || {};
    const name = opener?.dataset.companyName || p.name || activeCode;
    const hasInfo = usable(p);
    const unavailable = loading ? '企業情報を読み込んでいます…' : '企業概要を取得できていません。下の企業情報リンクから確認できます。';
    dialog.innerHTML = `<div class="company-dialog-head"><div><span class="company-eyebrow">COMPANY PROFILE · 企業詳細</span><h2 id="companyTitle">${esc(name)}</h2><span class="company-code">${esc(activeCode)}${p.sector ? ' · ' + esc(p.sector) : ''}</span></div><button type="button" class="company-close" aria-label="企業詳細を閉じる" autofocus>閉じる <span aria-hidden="true">×</span></button></div>
      <div class="company-dialog-body"><p class="company-lead">${esc(hasInfo ? p.summary : unavailable)}</p>
      ${hasInfo ? `<section><h3>どんな会社？</h3><p class="company-description">${esc(p.description)}</p></section>` : ''}
      ${hasInfo && p.themes?.length ? `<section><h3>関連する事業・テーマ</h3><div class="company-themes">${p.themes.map(t=>`<span>${esc(t)}</span>`).join('')}</div><small>取得元による分類。今回の株価上昇理由を示すものではありません。</small></section>` : ''}
      <section><h3>企業・業績を詳しく見る</h3><div class="company-links">${hasInfo ? link(p.website, '企業公式サイト') : ''}${link(`https://s.kabutan.jp/stocks/${activeCode}/finance/`, '決算・業績')}${link(`https://s.kabutan.jp/stocks/${activeCode}/news/`, '企業ニュース・開示')}${link(`https://s.kabutan.jp/stocks/${activeCode}/`, '株価・企業基本情報')}</div></section>
      <footer class="company-source">${hasInfo ? link(p.source_url, '企業概要の出典：株探') : ''}<span>企業情報の最終取得 ${esc(dateLabel(p.fetched_at))}</span>${p.fetch_status === 'error' ? '<span class="company-warning">再取得に失敗しています。取得済みの企業情報です。</span>' : ''}${p.description && !hasInfo ? '<span class="company-warning">企業情報の確認期限を過ぎたため、古い説明は表示していません。</span>' : ''}</footer></div>`;
    dialog.querySelector('.company-close').onclick = () => dialog.close();
  }

  dialog.addEventListener('close', () => {
    document.documentElement.classList.remove('company-modal-open');
    const target = opener?.isConnected ? opener : document.querySelector(`[data-company-code="${activeCode}"]`);
    target?.focus();
    activeCode = null;
  });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const r = dialog.getBoundingClientRect();
    if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close();
  });
  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-company-code]');
    if (!trigger || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || typeof dialog.showModal !== 'function') return;
    const code = trigger.dataset.companyCode;
    if (!/^[0-9][0-9A-Z]{3}$/.test(code)) return;
    event.preventDefault();
    opener = trigger; activeCode = code;
    paint(); dialog.showModal();
    document.documentElement.classList.add('company-modal-open');
  });

  window.CompanyProfiles = {summary};
  function refreshProfiles() { return fetch('/data/company_profiles.json', {signal:AbortSignal.timeout(15000), cache:'no-cache'})
    .then(response => {if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json();})
    .then(data => {companies = data.companies || {};})
    .catch(error => console.error('company_profiles_load_failed', String(error)))
    .finally(() => {
      loading = false;
      document.querySelectorAll('[data-company-summary]').forEach(node => {node.textContent = summary(node.dataset.companySummary);});
      if (dialog.open && dialog.querySelector('.company-lead')?.textContent.includes('読み込んでいます')) {paint(); dialog.querySelector('.company-close').focus();}
    });
  }
  refreshProfiles();
  setInterval(refreshProfiles, 300000);
})();
