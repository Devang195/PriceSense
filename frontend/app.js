/* PriceSense web frontend. No React, npm, compilation or external chart library.
   Charts are created with plain SVG so the project works without the internet. */
'use strict';

const $ = (id) => document.getElementById(id);
const state = {
  demoCatalog: null, catalog: null, result: null, uploadFile: null,
  tab: 'forecast', running: false, requestId: 0, page: 1, perPage: 20, booting: true,
};
const colors = {history:'#a48aff', future:'#65ead2', band:'#968aff'};
// Fixed model colors: the same model has the same color even when others fail.
const modelStyles = {
  'Naive (last price)': {color:'#b8c1d1',dash:'2 5'},
  "Holt's Trend": {color:'#ffb454',dash:'8 3'},
  'Seasonal Holt-Winters': {color:'#ff7597',dash:'3 3'},
  'ARIMA': {color:'#69b5ff',dash:'10 4 2 4'},
  'Gradient Boosting': {color:'#e1ed76',dash:'5 3'},
  'PriceSense Adaptive (PAF)': {color:'#f0a4ff',dash:''},
};
const modelStyle = name => modelStyles[name] || {color:'#ffffff',dash:'4 3'};
const chartViews = {};
const hiddenModels = new Set();
const DAY = 86400000;
const stamp = p => Date.parse(p.date+'T00:00:00Z');
function resetChartViews(){for(const key of Object.keys(chartViews)) delete chartViews[key];}

const money = (x, maximumFractionDigits=2) => Number.isFinite(Number(x))
  ? new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',minimumFractionDigits:Math.min(2,maximumFractionDigits),maximumFractionDigits}).format(Number(x)) : '—';
const count = x => Number.isFinite(Number(x)) ? new Intl.NumberFormat('en-IN').format(Number(x)) : '—';
const percent = x => Number.isFinite(Number(x)) ? `${x>=0?'+':''}${Number(x).toFixed(2)}%` : '—';
const shortDate = (s) => s ? new Date(`${s}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'}) : '—';
const compactDate = (s) => s ? new Date(`${s}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short'}) : '—';

// Full-screen market animation is visual only; forecasts are computed by the Python API.
const marketLoader = { startedAt: performance.now() };
function showMarketLoader(title, message) {
  const overlay = $('marketLoader');
  $('marketLoaderTitle').textContent = title;
  $('marketLoaderStatus').textContent = message;
  marketLoader.startedAt = performance.now();
  overlay.classList.remove('hidden', 'is-exiting');
  document.body.classList.add('market-loader-active');
}
async function hideMarketLoader(minimumMs = 800) {
  const overlay = $('marketLoader');
  const elapsed = performance.now() - marketLoader.startedAt;
  if (elapsed < minimumMs) await new Promise(resolve => setTimeout(resolve, minimumMs - elapsed));
  overlay.classList.add('is-exiting');
  // Keep it mounted for the fade-out, then release the dashboard.
  await new Promise(resolve => setTimeout(resolve, window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 30 : 430));
  overlay.classList.add('hidden');
  document.body.classList.remove('market-loader-active');
}

function showError(message) { $('errorBanner').textContent = message; $('errorBanner').classList.remove('hidden'); }
function hideError() { $('errorBanner').classList.add('hidden'); }
async function jsonFetch(url, options={}) {
  const response = await fetch(url, options);
  let payload;
  try { payload=await response.json(); } catch { throw new Error(`Server returned HTTP ${response.status}`); }
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (HTTP ${response.status})`);
  return payload;
}

function updateCatalog(catalog) {
  state.catalog = catalog;
  const categories = [...new Set(catalog.products.map(p=>p.category||'Uncategorized'))].sort();
  const select = $('categorySelect'); select.replaceChildren();
  select.add(new Option('All categories','all'));
  categories.forEach(c=>select.add(new Option(c,c)));
  $('productSearch').value = '';
  updateProducts(false);
  const o=catalog.overview;
  $('totalRecords').textContent = count(o.observations);
  $('totalProducts').textContent = count(o.products);
  $('totalCategories').textContent = o.categories == null ? '—' : count(o.categories);
  const [startEnd,endEnd] = [shortDate(o.date_start),shortDate(o.date_end)];
  $('dataPeriod').textContent = `${startEnd.split(' ').slice(1).join(' ')} – ${endEnd.split(' ').slice(1).join(' ')}`;
  $('sourceBadge').textContent = catalog.synthetic ? '◉ Price catalogue' : '◉ Uploaded CSV';
  $('dataSourceDetail').textContent = catalog.synthetic
    ? 'Source: synthetic price history'
    : 'Source: uploaded CSV';
}
function updateProducts(preserve=true) {
  if (!state.catalog) return;
  const selected = preserve ? $('productSelect').value : '';
  const query = $('productSearch').value.trim().toLowerCase();
  const category = $('categorySelect').value;
  const items = state.catalog.products.filter(p=>(category==='all'||(p.category||'Uncategorized')===category)
    && (`${p.product_name} ${p.product_id}`).toLowerCase().includes(query));
  const select = $('productSelect'); select.replaceChildren();
  items.forEach(p=>select.add(new Option(`${p.product_name} (${p.product_id})`,p.product_id)));
  if (selected && items.some(p=>p.product_id===selected)) select.value=selected;
  $('runBtn').disabled = !items.length || state.running;
  if (!items.length) select.add(new Option('No matching products',''));
}

async function useDemo() {
  state.uploadFile=null;
  $('demoBtn').classList.add('selected'); $('uploadBtn').classList.remove('selected');
  $('uploadPanel').classList.add('hidden'); $('fileInput').value='';
  updateCatalog(state.demoCatalog);
  await runForecast();
}
function showUpload() {
  $('uploadBtn').classList.add('selected'); $('demoBtn').classList.remove('selected');
  $('uploadPanel').classList.remove('hidden');
  $('chooseFileBtn').focus();
}
async function receiveUpload(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.csv')) {showError('Please choose a .csv file.');return;}
  if (file.size>10*1024*1024) {showError('CSV files must be 10 MB or smaller.');return;}
  $('uploadFilename').textContent=file.name;
  $('chooseFileBtn').textContent='Reading CSV...';
  const data=new FormData();data.append('file',file);
  try {
    hideError();
    const preview=await jsonFetch('/api/upload/preview',{method:'POST',body:data});
    state.uploadFile=file;
    updateCatalog(preview);
    await runForecast();
  } catch(err) {showError(err.message);state.uploadFile=null;}
  finally {$('chooseFileBtn').textContent='Choose file';}
}

async function runForecast() {
  const productId=$('productSelect').value;
  if (!productId || state.running) return;
  hideError(); state.running=true;
  const requestId=++state.requestId;
  if (state.booting) {
    $('marketLoaderTitle').textContent = 'Finding the best price patterns';
    $('marketLoaderStatus').textContent = 'Preparing your first forecast with Python models...';
  } else {
    showMarketLoader('Analyzing price movement', 'Fitting forecasting models and preparing your charts...');
  }
  $('loading').classList.remove('hidden'); $('runBtn').disabled=true;
  $('runBtn').innerHTML='<span>◌</span> Calculating...';
  const horizon=Number($('horizon').value);
  try {
    let payload;
    if(state.uploadFile){
      const form=new FormData();form.append('file',state.uploadFile);
      payload=await jsonFetch(`/api/forecast-upload?product_id=${encodeURIComponent(productId)}&horizon=${horizon}`,{method:'POST',body:form});
    } else {
      payload=await jsonFetch(`/api/forecast?product_id=${encodeURIComponent(productId)}&horizon=${horizon}`);
    }
    if(requestId !== state.requestId) return;
    state.result=payload;state.page=1;resetChartViews();
    render();
  } catch(err) {showError(`Unable to generate forecast: ${err.message}`);}
  finally {
    if (!state.booting) await hideMarketLoader(950);
    state.running=false;$('loading').classList.add('hidden');
    $('runBtn').innerHTML='<span>↗</span> Generate forecast';updateProducts();
  }
}

function switchTab(tab) {
  state.tab=tab;
  document.querySelectorAll('.nav-item').forEach(button=>button.classList.toggle('active',button.dataset.tab===tab));
  document.querySelectorAll('.tab-content').forEach(content=>content.classList.toggle('active',content.id===`tab-${tab}`));
  const labels={forecast:'Overview & forecast',evaluation:'Model evaluation',data:'Product data'};
  $('breadcrumbCurrent').textContent=labels[tab];
  $('sectionHeading').innerHTML=tab==='forecast'?'Overview <span class="title-muted">& insights</span>'
    :tab==='evaluation'?'Performance <span class="title-muted">& evaluation</span>'
    :'Your data <span class="title-muted">& history</span>';
  $('sidebar').classList.remove('open');
  if(state.result && tab==='forecast') {requestAnimationFrame(drawCharts);}
}
function setText(id,text) {$(id).textContent=text;}
function setDelta(id,value) {
  const el=$(id);el.textContent=`${percent(value)} vs latest`;
  el.classList.toggle('good-text',value<0);el.classList.toggle('bad-text',value>0);
}
function render() {
  if (!state.result) return;
  const r=state.result,p=r.product,s=r.summary;
  setText('productName',p.name);
  setText('productId',`ID: ${p.id}`);
  setText('productCategory',p.category);
  setText('latestDate',`Last updated ${shortDate(p.latest_date)}`);
  setText('currentPrice',money(p.latest_price));setText('currentPriceNote',`Recorded ${shortDate(p.latest_date)}`);
  setText('nextPrice',money(s.next_day));setText('endPrice',money(s.horizon_price));
  setText('horizonLabel',`${r.horizon}-DAY ESTIMATE`);
  setText('rangePrice',`${money(s.range_last_day[0],0)} – ${money(s.range_last_day[1],0)}`);
  setDelta('nextDelta',s.next_change_pct);setDelta('endDelta',s.horizon_change_pct);
  const signal=$('signal');signal.className='signal';
  if(s.horizon_change_pct>1){ signal.classList.add('up');setText('signalIcon','↗');setText('signalMessage',`Prices are predicted to rise ${percent(s.horizon_change_pct)} over the next ${r.horizon} days.`);}
  else if(s.horizon_change_pct< -1){ signal.classList.add('down');setText('signalIcon','↘');setText('signalMessage',`Prices are predicted to fall ${percent(s.horizon_change_pct)} over the next ${r.horizon} days.`);}
  else{signal.classList.add('neutral');setText('signalIcon','≈');setText('signalMessage',`Prices are predicted to remain relatively stable (${percent(s.horizon_change_pct)}) over the next ${r.horizon} days.`);}
  setText('minPrice',money(p.min_price));setText('maxPrice',money(p.max_price));
  setText('avgPrice',money(p.mean_price));setText('volatility',p.volatility_pct==null?'—':`${p.volatility_pct.toFixed(2)}%`);
  document.querySelectorAll('.horizonInline').forEach(e=>e.textContent=r.horizon);
  setText('detailDescription',`Forecast range: ${money(s.lowest_forecast)} to ${money(s.highest_forecast)} · spread ${money(s.highest_forecast-s.lowest_forecast)} (${((s.highest_forecast-s.lowest_forecast)/p.latest_price*100).toFixed(2)}% of latest price).`);
  const a=r.adaptive, paf=a && r.models[a.name];
  setText('adaptivePrice',paf?.length ? money(paf[paf.length-1].price) : 'Unavailable');
  setText('adaptiveWeight',a?.available ? `${((r.deployment_weights[a.name]||0)*100).toFixed(1)}%` : '—');
  setText('adaptiveWindows',a?.windows?.length ? a.windows.map(w=>`${compactDate(w.start)} – ${compactDate(w.end)} · up to ${w.expected_peak_discount_pct.toFixed(1)}% below regular price`).join(' · ') : 'No recurring discounts detected in this horizon');
  setText('adaptiveNote',a?.windows?.length ? a.windows.map(w=>`Evidence: ${w.observed_dates.map(shortDate).join(', ')} (${w.observed_years} years). Typical historical discount: ${w.typical_discount_pct.toFixed(1)}%.`).join(' ')+' Discount estimates are applied once to the advanced forecasts; dates are uncertain.' : 'The detector requires repeated multi-day discounts in different years. If evidence is insufficient, no sale effect is added.');
  renderEvaluation();renderData();
  if(state.tab==='forecast') requestAnimationFrame(drawCharts);
}

function renderEvaluation(){
  const r=state.result; if(!r)return;
  const e=r.evaluation;
  setText('bestModelName',e.best_model);
  setText('evaluationDescription',`${e.folds} walk-forward calibration splits · ${e.test_days}-day untouched holdout (${shortDate(e.test_start)} – ${shortDate(e.test_end)}).`);
  const body=$('modelTableBody');body.replaceChildren();
  for(const m of r.metrics){
    const tr=document.createElement('tr');
    const cells=[m.name,money(m.mae),money(m.rmse),`${m.mape.toFixed(3)}%`,m.r2==null?'n/a':m.r2.toFixed(3),`${m.weight.toFixed(1)}%`];
    cells.forEach((val,i)=>{const td=document.createElement('td');td.textContent=val;if(i===5) td.className='model-weight-cell';tr.append(td);});body.append(tr);
  }
  renderBars('maeBars',r.metrics.map(m=>({label:m.name,value:m.mae,formatted:money(m.mae)})),true);
  const weights=Object.entries(r.weights).map(([name,weight])=>({label:name,value:weight*100,formatted:`${(weight*100).toFixed(1)}%`}));
  if(weights.length)renderBars('weightBars',weights,false,100);
  else $('weightBars').textContent='All advanced models unavailable — using naive fallback.';
  const skipped=Object.entries(r.skipped);
  $('evalFootnote').textContent=`The naive last-price model is a baseline and is not normally part of the ensemble. Recurring discount effects, when supported by past data, are applied once to each advanced forecast. Weights are derived from earlier calibration observations only. Final model performance is measured on separate holdout data.${skipped.length?' Models unavailable: '+skipped.map(([name,reason])=>name+' ('+reason+')').join('; '):''}`;
}
function renderBars(id,items,isMae=false,fixedMax=null){
  const el=$(id);el.replaceChildren();const max=fixedMax??Math.max(...items.map(item=>item.value),1);
  for(const item of items){
    const group=document.createElement('div');
    const title=document.createElement('div');title.className='bar-title';
    const span=document.createElement('span');span.textContent=item.label;
    const strong=document.createElement('strong');strong.textContent=item.formatted;
    title.append(span,strong);
    const track=document.createElement('div');track.className='bar-track';
    const fill=document.createElement('div');fill.className=`bar-fill${isMae?' mae':''}`;
    fill.style.width=`${Math.min(100,Math.max(0,(item.value/max)*100))}%`;
    track.append(fill);group.append(title,track);el.append(group);
  }
}
function getFilteredData(){
  if(!state.result)return [];
  let rows=[...state.result.history].reverse();
  const q=$('dataSearch').value.trim().toLowerCase();
  if(q)rows=rows.filter(r=>`${r.date} ${shortDate(r.date)} ${r.price.toFixed(2)}`.toLowerCase().includes(q));
  return rows;
}
function renderData(){
  if(!state.result)return;
  const rows=getFilteredData();
  const start=(state.page-1)*state.perPage;
  const pageRows=rows.slice(start,start+state.perPage);
  const tbody=$('dataTableBody');tbody.replaceChildren();
  const history=state.result.history;
  const previousPrices=new Map(history.map((r,i)=>[r.date,i>0?history[i-1].price:null]));
  for(const row of pageRows){
    const tr=document.createElement('tr');
    const previous=previousPrices.get(row.date);
    const delta=previous?100*(row.price/previous-1):null;
    for(const val of [shortDate(row.date),state.result.product.id,state.result.product.name,state.result.product.category,money(row.price),delta==null?'—':percent(delta)]){
      const td=document.createElement('td');td.textContent=val;tr.append(td);
    }
    if(delta!==null)tr.lastChild.className=delta<0?'good-text':delta>0?'bad-text':'';
    tbody.append(tr);
  }
  $('dataRowsCount').textContent=`${count(rows.length)} observations`;
  $('pageLabel').textContent=rows.length?`Showing ${start+1}–${Math.min(start+pageRows.length,rows.length)} of ${rows.length}`:'No matching rows';
  $('prevPage').disabled=state.page<=1;
  $('nextPage').disabled=state.page*state.perPage>=rows.length;
}
function downloadCsv(){
  if(!state.result)return;
  const r=state.result;
  const rows=[['date','product_id','product_name','category','price'],...r.history.map(h=>[h.date,r.product.id,r.product.name,r.product.category,h.price])];
  const csv=rows.map(row=>row.map(v=>`"${String(v).replaceAll('"','""')}"`).join(',')).join('\r\n');
  const blob=new Blob(['\ufeff',csv],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob);
  const a=document.createElement('a');a.href=url;a.download=`${r.product.id}_price_history.csv`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

// --------- Dependency-free SVG charts ---------
const ns='http://www.w3.org/2000/svg';
function el(name,attrs={},text=null){const node=document.createElementNS(ns,name);for(const [key,val] of Object.entries(attrs))node.setAttribute(key,String(val));if(text!==null)node.textContent=String(text);return node;}
function pathFrom(points,x,y){return points.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(2)},${y(p.price).toFixed(2)}`).join(' ');}
function polygon(pointsA,pointsB,x,y){
  const all=[...pointsA,...pointsB.slice().reverse()];return all.map((p,i)=>`${i?'L':'M'}${x(p).toFixed(2)},${y(p.price).toFixed(2)}`).join(' ')+' Z';
}
function axisMoney(v,step){if(step<1)return `₹${v.toFixed(Math.min(5,Math.max(2,Math.ceil(-Math.log10(step))+1)))}`;if(step<100)return `₹${v.toFixed(0)}`;if(Math.abs(v)>=100000)return `₹${(v/100000).toFixed(step<10000?3:1)}L`;if(Math.abs(v)>=1000)return `₹${(v/1000).toFixed(1)}k`;return `₹${v.toFixed(0)}`;}
// Each chart has its own horizontal viewport; the price axis follows visible values.
function setViewport(id, start, end) {
  const v=chartViews[id]; if(!v)return;
  const total=v.fullEnd-v.fullStart;
  const span=Math.min(total,Math.max(Math.min(2*DAY,total),end-start));
  start=Math.max(v.fullStart,Math.min(start,v.fullEnd-span));
  v.start=start;v.end=start+span;
  $('tooltip').classList.add('hidden');
  drawCharts();
}
function zoomChart(id, factor, anchor=.5) {
  const v=chartViews[id];if(!v)return;
  const focus=v.start+(v.end-v.start)*anchor;
  const length=Math.max(Math.min(2*DAY,v.fullEnd-v.fullStart),Math.min(v.fullEnd-v.fullStart,(v.end-v.start)*factor));
  setViewport(id,focus-length*anchor,focus+length*(1-anchor));
}
function moveChart(id, direction){const v=chartViews[id];if(v){const shift=(v.end-v.start)*.35*direction;setViewport(id,v.start+shift,v.end+shift);}}
function resetChart(id){const v=chartViews[id];if(v)setViewport(id,v.fullStart,v.fullEnd);}
function updateChartControls(id,v){
  const controls=document.querySelector(`[data-chart-controls="${id}"]`);if(!controls)return;
  const tolerance=1;
  controls.querySelector('[data-action="in"]').disabled=v.end-v.start<=Math.min(2*DAY,v.fullEnd-v.fullStart)+tolerance;
  controls.querySelector('[data-action="out"]').disabled=v.end-v.start>=v.fullEnd-v.fullStart-tolerance;
  controls.querySelector('[data-action="reset"]').disabled=v.start<=v.fullStart+tolerance&&v.end>=v.fullEnd-tolerance;
  controls.querySelector('[data-action="left"]').disabled=v.start<=v.fullStart+tolerance;
  controls.querySelector('[data-action="right"]').disabled=v.end>=v.fullEnd-tolerance;
  const fmt=t=>shortDate(new Date(t).toISOString().slice(0,10));
  controls.querySelector('.chart-range').textContent=`${fmt(v.start)} – ${fmt(v.end)}`;
}
function drawChart(containerId,history,forecast,band,models={},options={}){
  const container=$(containerId);container.replaceChildren();
  if(!forecast.length && !history.length)return;
  const small=!!options.small;
  const w=Math.max(310,container.clientWidth-10||650),h=small?210:310;
  const margin={left:69,right:18,top:17,bottom:33};const innerW=w-margin.left-margin.right,innerH=h-margin.top-margin.bottom;
  const today=history.length?history[history.length-1].date:forecast[0].date;
  const points=[...history.map(p=>({...p,kind:'Recorded'})),...forecast.map(p=>({...p,kind:'Ensemble'}))];
  const ts=points.map(stamp);
  const fullStart=Math.min(...ts),fullEnd=Math.max(Math.max(...ts),fullStart+DAY);
  let view=chartViews[containerId];
  if(!view || view.fullStart!==fullStart || view.fullEnd!==fullEnd){view={fullStart,fullEnd,start:fullStart,end:fullEnd};chartViews[containerId]=view;}
  const mint=view.start,maxt=view.end;
  const x=p=>margin.left+(stamp(p)-mint)/(maxt-mint)*innerW;
  const visible=arr=>arr.filter(p=>stamp(p)>=mint && stamp(p)<=maxt);
  // Include edge-interpolated prices for continuous paths crossing the viewport.
  const visiblePrices=arr=>{
    const vals=visible(arr).map(p=>p.price);
    for(let i=1;i<arr.length;i++)for(const edge of [mint,maxt]){
      const a=stamp(arr[i-1]),b=stamp(arr[i]);
      if(a<edge && b>edge) vals.push(arr[i-1].price+(arr[i].price-arr[i-1].price)*(edge-a)/(b-a));
    }
    return vals;
  };
  const joined=history.length?[history[history.length-1],...forecast]:forecast;
  const values=[...visiblePrices(history),...visiblePrices(joined)];
  const lo=band.map(p=>({date:p.date,price:p.lower})),hi=band.map(p=>({date:p.date,price:p.upper}));
  if(options.showBand)values.push(...visiblePrices(lo),...visiblePrices(hi));
  for(const line of Object.values(models)) values.push(...visiblePrices(line));
  if(!values.length)values.push(...points.map(p=>p.price));
  const actualMin=Math.min(...values),actualMax=Math.max(...values);
  const padding=Math.max((actualMax-actualMin)*0.12,Math.abs(actualMax)*0.00005,.01);
  let min=Math.max(0,actualMin-padding),max=actualMax+padding;if(min===max)max=min+1;
  const y=v=>margin.top+innerH-(v-min)/(max-min)*innerH;
  const svg=el('svg',{viewBox:`0 0 ${w} ${h}`,role:'img','aria-label':small?'Interactive future price chart':'Interactive recorded price history and forecast chart'});
  const defs=el('defs');const gradient=el('linearGradient',{id:containerId+'Grad',x1:'0',y1:'0',x2:'0',y2:'1'});
  gradient.append(el('stop',{offset:'0%','stop-color':small?colors.future:colors.history,'stop-opacity':'.2'}),el('stop',{offset:'100%','stop-color':small?colors.future:colors.history,'stop-opacity':'0'}));
  const clip=el('clipPath',{id:containerId+'Clip'});clip.append(el('rect',{x:margin.left,y:margin.top,width:innerW,height:innerH}));defs.append(gradient,clip);svg.append(defs);
  const grid=el('g');
  for(let i=0;i<5;i++){const price=min+(max-min)*i/4,py=y(price);grid.append(el('line',{x1:margin.left,y1:py,x2:w-margin.right,y2:py,class:'svg-grid'}));grid.append(el('text',{x:margin.left-12,y:py+3,'text-anchor':'end',class:'svg-axis'},axisMoney(price,(max-min)/4)));}
  svg.append(grid);
  const tickCount=Math.min(5,Math.max(2,Math.floor((maxt-mint)/DAY)+1));
  for(let i=0;i<tickCount;i++){
    const t=mint+(maxt-mint)*(i/Math.max(1,tickCount-1));
    const label=(maxt-mint>180*DAY?shortDate:compactDate)(new Date(t).toISOString().slice(0,10));
    svg.append(el('text',{x:margin.left+innerW*i/Math.max(1,tickCount-1),y:h-9,'text-anchor':i===0?'start':i===tickCount-1?'end':'middle',class:'svg-axis'},label));
  }
  const plot=el('g',{'clip-path':`url(#${containerId}Clip)`});svg.append(plot);
  for(const event of state.result?.adaptive?.windows || []){
    const start=Math.max(mint,stamp({date:event.start}),forecast.length?stamp(forecast[0]):mint),end=Math.min(maxt,stamp({date:event.end})+DAY);
    if(end>start){const left=margin.left+(start-mint)/(maxt-mint)*innerW,right=margin.left+(end-mint)/(maxt-mint)*innerW;const zone=el('rect',{x:left,y:margin.top,width:right-left,height:innerH,fill:'#65ead2','fill-opacity':'.09'});zone.append(el('title',{},`Estimated discount window: ${event.start} to ${event.end}`));plot.append(zone);}
  }
  if(history.length){
    let d=pathFrom(history,x,y);let area=d+` L${x(history[history.length-1])},${y(min)} L${x(history[0])},${y(min)} Z`;
    plot.append(el('path',{d:area,fill:`url(#${containerId}Grad)`}));
    plot.append(el('path',{d,fill:'none',stroke:colors.history,'stroke-width':small?2.3:2.7,'stroke-linecap':'round','stroke-linejoin':'round'}));
  }
  if(options.showBand && band.length)plot.append(el('path',{d:polygon(lo,hi,x,y),fill:colors.band,'fill-opacity':'.20',stroke:'none'}));
  if(history.length && forecast.length && !small){
    const divider=x({date:today});plot.append(el('line',{x1:divider,y1:margin.top,x2:divider,y2:margin.top+innerH,stroke:'#7585a2','stroke-width':1.2,'stroke-dasharray':'4 6'}));
    plot.append(el('text',{x:divider+6,y:margin.top+14,'text-anchor':'start',class:'svg-label'},'Forecast begins'));
  }
  Object.entries(models).forEach(([name,pts])=>{if(!pts.length)return;const style=modelStyle(name);const p=el('path',{d:pathFrom(pts,x,y),fill:'none',stroke:style.color,'stroke-width':2,'stroke-dasharray':style.dash,'stroke-linejoin':'round','stroke-linecap':'round','data-model':name});plot.append(p);if(pts.length===1)plot.append(el('circle',{cx:x(pts[0]),cy:y(pts[0].price),r:4,fill:style.color}));});
  if(forecast.length){
    const p=el('path',{d:pathFrom(joined,x,y),fill:'none',stroke:colors.future,'stroke-width':small?2.8:2.6,'stroke-linejoin':'round','stroke-linecap':'round','stroke-dasharray':small?'none':'7 4'});plot.append(p);
    forecast.forEach((point,index)=>{
      if(!small && maxt-mint>17*DAY && forecast.length>17 && index%3!==0 && index!==forecast.length-1)return;
      plot.append(el('circle',{cx:x(point),cy:y(point.price),r:small?3.5:3,fill:colors.future,stroke:'#0b1324','stroke-width':1.2}));
    });
  }
  const hit=el('rect',{x:margin.left,y:margin.top,width:innerW,height:innerH,fill:'transparent',class:'chart-hit'});
  svg.append(hit);
  let guide=null;
  const localX=evt=>{const rect=svg.getBoundingClientRect();return (evt.clientX-rect.left)*w/rect.width;};
  hit.addEventListener('pointermove',evt=>{
    if(container.dataset.dragging==='true'||evt.pointerType==='touch')return;
    const mouseX=localX(evt);
    let nearest=null,distance=Infinity;
    for(const p of visible(points)){const d=Math.abs(x(p)-mouseX);if(d<distance){distance=d;nearest=p;}}
    if(!nearest)return;
    if(guide)guide.remove();
    guide=el('line',{x1:x(nearest),x2:x(nearest),y1:margin.top,y2:margin.top+innerH,stroke:'#acb5cf','stroke-opacity':'.5','stroke-dasharray':'3 4'});
    svg.insertBefore(guide,hit);
    const tip=$('tooltip');tip.replaceChildren();
    const d=document.createElement('strong');d.textContent=shortDate(nearest.date);tip.append(d);
    function addRow(label,price,color){const t=document.createElement('span');t.textContent=`${label}: ${money(price)}`;t.style.color=color;tip.append(t);}
    addRow(nearest.kind,nearest.price,nearest.kind==='Recorded'?colors.history:colors.future);
    for(const [name,pts] of Object.entries(models)){const p=pts.find(p=>p.date===nearest.date);if(p)addRow(name,p.price,modelStyle(name).color);}
    tip.classList.remove('hidden');const tw=tip.offsetWidth,th=tip.offsetHeight;
    tip.style.left=`${Math.max(6,Math.min(window.innerWidth-tw-6,evt.clientX+14))}px`;
    tip.style.top=`${Math.max(8,Math.min(window.innerHeight-th-8,evt.clientY-35))}px`;
  });
  hit.addEventListener('pointerleave',()=>{if(guide)guide.remove();guide=null;$('tooltip').classList.add('hidden');});
  container.append(svg);container.chartGeometry={w,margin,innerW};updateChartControls(containerId,view);
}
function drawCharts(){
  const r=state.result;if(!r)return;
  const days=$('historyWindow').value;
  const history=days==='all'?r.history:r.history.slice(-Number(days));
  const band=$('showBand').checked?r.interval:[];
  const models={},allModels=$('showModels').checked?Object.entries(r.models):[];
  const legend=$('modelLegend');legend.replaceChildren();legend.hidden=!allModels.length;
  allModels.forEach(([name,values])=>{
    const active=!hiddenModels.has(name);if(active)models[name]=values;
    const item=document.createElement('button');item.type='button';item.className='model-legend-toggle';item.dataset.model=name;item.setAttribute('aria-pressed',String(active));item.title=`${active?'Hide':'Show'} ${name}`;
    const mark=document.createElement('i');mark.className='legend-line';mark.style.borderTopColor=modelStyle(name).color;mark.style.borderTopStyle=modelStyle(name).dash?'dashed':'solid';
    item.append(mark,document.createTextNode(name));item.addEventListener('click',()=>{if(hiddenModels.has(name))hiddenModels.delete(name);else hiddenModels.add(name);drawCharts();legend.querySelectorAll('button').forEach(b=>{if(b.dataset.model===name)b.focus();});});legend.append(item);
  });
  drawChart('historyChart',history,r.forecast,band,models,{showBand:$('showBand').checked});
  drawChart('detailChart',[],r.forecast,[],models,{small:true,showBand:false});
}
function installChartInteractions(id){
  const container=$(id);const controls=document.querySelector(`[data-chart-controls="${id}"]`);
  controls.addEventListener('click',evt=>{const button=evt.target.closest('button[data-action]');if(!button)return;const action=button.dataset.action;
    if(action==='in')zoomChart(id,.5);if(action==='out')zoomChart(id,2);if(action==='reset')resetChart(id);if(action==='left')moveChart(id,-1);if(action==='right')moveChart(id,1);
  });
  container.addEventListener('wheel',evt=>{
    // Ctrl/Command + wheel zooms; ordinary wheel still scrolls the page.
    if(!(evt.ctrlKey||evt.metaKey)||!evt.target.classList.contains('chart-hit'))return;
    evt.preventDefault();const svg=container.querySelector('svg');const g=container.chartGeometry;if(!svg||!g)return;
    const rect=svg.getBoundingClientRect();const a=Math.max(0,Math.min(1,((evt.clientX-rect.left)*g.w/rect.width-g.margin.left)/g.innerW));zoomChart(id,evt.deltaY<0?.8:1.25,a);
  },{passive:false});
  let drag=null;
  container.addEventListener('pointerdown',evt=>{
    if(!evt.target.classList.contains('chart-hit')||evt.button!==0)return;
    const v=chartViews[id],g=container.chartGeometry,svg=container.querySelector('svg');if(!v||!g||!svg||v.end-v.start>=v.fullEnd-v.fullStart-1)return;
    const plotWidth=svg.getBoundingClientRect().width*g.innerW/g.w;
    drag={id:evt.pointerId,x:evt.clientX,start:v.start,end:v.end,width:plotWidth};container.setPointerCapture(evt.pointerId);container.dataset.dragging='true';$('tooltip').classList.add('hidden');
  });
  container.addEventListener('pointermove',evt=>{if(!drag||evt.pointerId!==drag.id)return;const shift=-(evt.clientX-drag.x)*(drag.end-drag.start)/drag.width;setViewport(id,drag.start+shift,drag.end+shift);});
  function finish(evt){if(!drag||evt.pointerId!==drag.id)return;drag=null;container.dataset.dragging='false';if(container.hasPointerCapture(evt.pointerId))container.releasePointerCapture(evt.pointerId);}
  container.addEventListener('pointerup',finish);container.addEventListener('pointercancel',finish);container.addEventListener('lostpointercapture',finish);
}

async function init(){
  $('todayDate').textContent=new Date().toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'});
  document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>switchTab(b.dataset.tab)));
  $('mobileMenu').addEventListener('click',()=>$('sidebar').classList.toggle('open'));
  $('demoBtn').addEventListener('click',useDemo);
  $('uploadBtn').addEventListener('click',showUpload);
  $('chooseFileBtn').addEventListener('click',()=>$('fileInput').click());
  $('fileInput').addEventListener('change',ev=>receiveUpload(ev.target.files[0]));
  $('productSearch').addEventListener('input',()=>updateProducts());
  $('categorySelect').addEventListener('change',()=>updateProducts(false));
  $('productSelect').addEventListener('change',runForecast);
  $('horizon').addEventListener('input',()=>{$('horizonValue').textContent=$('horizon').value;});
  $('horizon').addEventListener('change',runForecast);
  $('runBtn').addEventListener('click',runForecast);
  $('historyWindow').addEventListener('change',()=>{delete chartViews.historyChart;drawCharts();});
  installChartInteractions('historyChart');installChartInteractions('detailChart');
  $('showBand').addEventListener('change',drawCharts);
  $('showModels').addEventListener('change',drawCharts);
  $('dataSearch').addEventListener('input',()=>{state.page=1;renderData();});
  $('prevPage').addEventListener('click',()=>{state.page--;renderData();});
  $('nextPage').addEventListener('click',()=>{state.page++;renderData();});
  $('downloadCsv').addEventListener('click',downloadCsv);
  window.addEventListener('resize',()=>{if(state.result && state.tab==='forecast')drawCharts();});
  try{
    state.demoCatalog=await jsonFetch('/api/catalog');updateCatalog(state.demoCatalog);await runForecast();
  }catch(err){showError('Unable to load PriceSense. '+err.message);}
  finally {
    await hideMarketLoader(1900);
    state.booting=false;
  }
}
window.addEventListener('DOMContentLoaded',init);
