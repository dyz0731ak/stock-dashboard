/* Load only the clicked instrument and period. Native OHLC for cash indices/FX;
   official TradingView spot-gold widget where redisplay is available. */
(() => {
  const instruments = {
    nk225: ['TVC:NI225', '日経225'],
    dow: ['DJ:DJI', 'NYダウ'],
    nasdaq: ['NASDAQ:IXIC', 'NASDAQ総合指数'],
    usdjpy: ['FX_IDC:USDJPY', 'USD/JPY'],
    sox: ['NASDAQ:SOX', 'SOX指数'],
    gold: ['FX_IDC:XAUUSD', '金スポット（XAU/USD）'],
  };
  const periods = [['1M','1ヶ月'], ['3M','3ヶ月'], ['6M','6ヶ月'], ['12M','1年'], ['36M','3年']];
  let dialog, host, timer, opener, active, request, generation=0;
  const cache = new Map();
  function cleanup() {
    clearTimeout(timer);
    request?.abort();
    generation++;
    host?.replaceChildren(); // Close sockets and release chart resources with its frame.
  }
  function mount(range) {
    cleanup();
    const [symbol, name] = instruments[active];
    dialog.querySelectorAll('[data-range]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.range===range)));
    const status = dialog.querySelector('.market-chart-status');
    status.textContent = '日足ローソク足を読み込み中…';
    if(active!=='gold') {
      dialog.querySelector('.market-chart-note').textContent='実際の始値・高値・安値・終値による日足。休日や欠損した足は補間しません。足に触れるか、チャート内で左右キーを押すと四本値を確認できます。';
      loadHistory(active,range,generation);
      return;
    }
    dialog.querySelector('.market-chart-note').textContent='チャート提供：TradingView / ICE。金はXAU/USDのスポット参考価格です。カードとは取得元・更新時刻が異なります。';
    const container = document.createElement('div');
    container.className = 'tradingview-widget-container';
    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    container.append(widget);
    const credit = document.createElement('div');
    credit.className = 'tradingview-widget-copyright';
    const link = document.createElement('a');
    link.href = 'https://www.tradingview.com/symbols/'+symbol.replace(':','-')+'/';
    link.target = '_blank'; link.rel = 'noopener noreferrer';
    link.textContent = name+'チャート — TradingViewで開く';
    credit.append(link); container.append(credit);
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.textContent = JSON.stringify({symbol,interval:'D',range,timezone:'Asia/Tokyo',theme:'dark',
      style:'1',locale:'ja',autosize:true,allow_symbol_change:false,hide_volume:true,
      hide_side_toolbar:false,hide_top_toolbar:false,withdateranges:false,save_image:false,
      backgroundColor:'#0b1726',gridColor:'rgba(117,156,183,0.08)'});
    script.onerror = () => {status.textContent='チャートを読み込めませんでした。期間を選び直すか、TradingViewのリンクから確認してください。';};
    // Embedding is cross-origin. Do not claim that a frame load proves data availability.
    script.onload = () => {status.textContent='表示期間：'+periods.find(p=>p[0]===range)[1]+' ｜ 日足・ローソク足';};
    host.append(container); container.append(script);
    timer = setTimeout(() => {
      if (!host.querySelector('iframe')) script.onerror();
    },15000);
  }
  async function loadHistory(id,range,version) {
    const key=id+'-'+range;
    const status=dialog.querySelector('.market-chart-status');
    try {
      let data=cache.get(key);
      if(!data || Date.now()-data.loaded>15*60000) {
        for(let attempt=0;attempt<2;attempt++) {
          request=new AbortController();
          const timeout=setTimeout(()=>request?.abort(),12000);
          try {
            const response=await fetch('data/market_history/'+key+'.json',{signal:request.signal,cache:attempt?'reload':'default'});
            if(!response.ok)throw new Error('HTTP '+response.status);
            data={payload:await response.json(),loaded:Date.now()};
            break;
          } catch(error) {
            if(version!==generation) return;
            if(attempt)throw error;
          } finally {clearTimeout(timeout);}
        }
        cache.set(key,data);
      }
      if(version!==generation)return;
      const d=data.payload;
      if(d.id!==id || d.period!==range || !Array.isArray(d.bars) || !d.bars.length)throw new Error('四本値がありません');
      const bars=d.bars;
      if(bars.some(b=>!/^\d{4}-\d{2}-\d{2}$/.test(b.t) || ![b.o,b.h,b.l,b.c].every(v=>Number.isFinite(v)&&v>0) || b.h<Math.max(b.o,b.c) || b.l>Math.min(b.o,b.c)))throw new Error('四本値を検証できません');
      if(Date.now()-Date.parse(d.fetched_at)>7*86400000)throw new Error('履歴データの更新を確認できません');
      const stale=Date.now()-Date.parse(d.fetched_at)>8*3600000;
      status.textContent=`${periods.find(p=>p[0]===range)[1]} ｜ 日足 ${bars.length}本 ｜ ${bars[0].t} ～ ${bars.at(-1).t}${stale?' ｜ 前回取得データ':''}`;
      draw(bars,instruments[id][1],id==='usdjpy'?3:2);
      const source=document.createElement('a');
      source.href='https://finance.yahoo.com/quote/'+encodeURIComponent(d.ticker)+'/history/';
      source.target='_blank';source.rel='noopener noreferrer';source.className='market-history-source';
      source.textContent=`Yahoo Finance ｜ 取得 ${new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(d.fetched_at))} JST`;
      host.append(source);
    } catch(error) {
      if(version!==generation)return;
      status.textContent='チャートを取得できませんでした。期間ボタンを押すと再取得します。';
      cache.delete(key);
    }
  }
  function draw(bars,name,decimals) {
    const W=Math.max(320,Math.round(host.clientWidth)),H=Math.max(240,Math.round(host.clientHeight-65)),L=12,R=86,T=18,B=30,plot=W-L-R;
    const low=Math.min(...bars.map(b=>b.l)),high=Math.max(...bars.map(b=>b.h));
    const pad=(high-low)*.07 || high*.01, min=low-pad,max=high+pad;
    const y=v=>T+(max-v)/(max-min)*(H-T-B),step=plot/bars.length,bw=Math.max(.65,Math.min(14,step*.65));
    const fmt=v=>v.toLocaleString('en-US',{minimumFractionDigits:decimals,maximumFractionDigits:decimals});
    let content='';
    for(let i=0;i<=5;i++) {
      const value=min+(max-min)*i/5,pos=y(value);
      content+=`<path d="M ${L} ${pos} H ${W-R}" stroke="#23364b"/><text x="${W-R+10}" y="${pos+4}" fill="#93aabe" font-size="12">${fmt(value)}</text>`;
    }
    bars.forEach((b,i)=>{
      const x=L+(i+.5)*step,color=b.c>=b.o?'#f06a78':'#32c79c';
      content+=`<path d="M ${x} ${y(b.h)} V ${y(b.l)}" stroke="${color}" stroke-width="${Math.min(1,bw)}"/><rect x="${x-bw/2}" y="${Math.min(y(b.o),y(b.c))}" width="${bw}" height="${Math.max(.8,Math.abs(y(b.o)-y(b.c)))}" fill="${color}"/>`;
    });
    [0,Math.floor((bars.length-1)/2),bars.length-1].forEach((i,n)=>{
      content+=`<text x="${L+(i+.5)*step}" y="${H-5}" text-anchor="${n===0?'start':n===2?'end':'middle'}" fill="#93aabe" font-size="12">${bars[i].t}</text>`;
    });
    const readout=document.createElement('p');readout.className='market-ohlc';
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox',`0 0 ${W} ${H}`);svg.setAttribute('preserveAspectRatio','none');
    svg.setAttribute('role','img');svg.setAttribute('aria-label',name+'の日足ローソク足チャート');svg.setAttribute('tabindex','0');
    svg.innerHTML=content+'<path class="chart-crosshair" stroke="#93aabe" stroke-dasharray="3 4"/>';
    let current=bars.length-1;
    const select=i=>{
      current=Math.max(0,Math.min(bars.length-1,i));const b=bars[current],x=L+(current+.5)*step;
      readout.textContent=`${b.t}　始 ${fmt(b.o)}　高 ${fmt(b.h)}　安 ${fmt(b.l)}　終 ${fmt(b.c)}`;
      svg.querySelector('.chart-crosshair').setAttribute('d',`M ${x} ${T} V ${H-B}`);
    };
    const point=e=>{const rect=svg.getBoundingClientRect();select(Math.floor(((e.clientX-rect.left)/rect.width*W-L)/step));};
    svg.addEventListener('pointermove',point);svg.addEventListener('pointerdown',point);
    svg.addEventListener('keydown',e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();select(current+(e.key==='ArrowLeft'?-1:1));}});
    select(current);host.append(readout,svg);
  }
  function open(id, button) {
    if (!instruments[id]) return;
    if (!dialog) {
      dialog = document.createElement('dialog');
      dialog.className = 'market-chart-dialog';
      dialog.setAttribute('aria-labelledby','marketChartTitle');
      dialog.innerHTML = '<div class="market-chart-head"><h2 id="marketChartTitle"></h2><button type="button" class="market-chart-close" aria-label="チャートを閉じる">✕</button></div>'+
        '<div class="market-chart-periods" aria-label="表示期間">'+periods.map(([range,label])=>`<button type="button" data-range="${range}" aria-pressed="false">${label}</button>`).join('')+'</div>'+
        '<p class="market-chart-status" role="status"></p><div class="market-chart-host"></div>'+
        '<p class="market-chart-note">チャート提供：TradingView。カードとは取得元・更新時刻が異なります。金はXAU/USDのスポット参考価格です。</p>';
      document.body.append(dialog); host = dialog.querySelector('.market-chart-host');
      dialog.querySelector('.market-chart-close').onclick = () => dialog.close();
      dialog.querySelectorAll('[data-range]').forEach(button=>{button.onclick=()=>mount(button.dataset.range);});
      dialog.addEventListener('close',()=>{cleanup();document.body.classList.remove('market-chart-open');opener?.focus();});
      dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
    }
    active=id; opener=button;
    dialog.querySelector('h2').textContent=instruments[id][1];
    document.body.classList.add('market-chart-open');
    dialog.showModal();
    mount('12M');
  }
  document.addEventListener('click',event=>{
    const button=event.target.closest('[data-market-chart]');
    if(button)open(button.dataset.marketChart,button);
  });
})();
