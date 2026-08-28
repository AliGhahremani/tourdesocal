/* ---------------------------------------------------------------------------
   The jersey races, animated.

   Plotted as raw cumulative totals these are unreadable: Randee and Jose are
   18 miles apart on a 3,400 mile axis, which is one pixel. So the y axis is
   GAP TO THE LEADER. Whoever leads at that moment rides along zero, everyone
   else hangs below, and a lead change is a line touching the top.

   The race plays out rather than appearing finished: a clip rect sweeps left
   to right, each rider's face rides the head of their own line, and the legend
   ticks the real numbers for the day being drawn. Nothing is pre-rendered, so
   it is current the moment data/history.js is, and there is no weekly step to
   forget.

   Two measures, two charts. Never one chart with two y scales.
--------------------------------------------------------------------------- */
const SERIES = ["#2a78d6","#eb6834","#1baf7a","#eda100","#e87ba4"];
// Pace, not duration. A fixed duration silently speeds up as the season grows,
// because the same sweep that covers 240 days in August has to cover 365 by
// December. This holds roughly 16 days per second and clamps both ends.
const raceMs = days => Math.max(9000, Math.min(21000, 62 * days));
// prefers-reduced-motion is about motion a viewer did not ask for. Nothing
// here ever autoplays: the race only starts when somebody presses Play or
// clicks a jersey card, and refusing to animate what they just asked to watch
// is not an accessibility win, it is a broken button. So the setting is
// honoured where it belongs, on the scroll, and not on the race itself.
const REDUCED = !!(window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches);

function buildRace(H, key){
  const R = H.riders, n = H.days.length;
  const lead = new Array(n);
  for (let i=0;i<n;i++){ let m=-Infinity; for(const r of R){const v=H[key][r][i]; if(v>m)m=v;} lead[i]=m; }
  const gap = {}; let worst = 0;
  for (const r of R){
    const a = new Array(n);
    for (let i=0;i<n;i++){ a[i] = H[key][r][i] - lead[i]; if (a[i] < worst) worst = a[i]; }
    gap[r] = a;
  }
  return {gap, worst};
}

function niceStep(span, want){
  const raw = span/want, p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1,2,2.5,5,10]) if (raw/p <= m) return m*p;
  return 10*p;
}

function drawRace(root, H, key, opts){
  const R = H.riders, days = H.days, n = days.length;
  const {gap, worst} = buildRace(H, key);
  const plot   = root.querySelector(".plot");
  const legend = root.querySelector(".lg");
  const stamp  = root.querySelector(".stamp");
  const scrub  = root.querySelector(".scrub");
  const play   = root.querySelector(".play");
  const fmt = opts.fmt;
  const AV = window.AVATARS || {};

  legend.innerHTML = R.map((r,si)=>{
    const c = SERIES[si%SERIES.length];
    const f = AV[r] ? `<img class="lgav" src="${AV[r]}" alt="" style="border-color:${c}">`
                    : `<i class="lgav nf" style="background:${c}"></i>`;
    return `<span class="lgi" data-r="${r}">${f}<b>${r}</b><em></em></span>`;
  }).join("");
  const cells = {};
  R.forEach(r => cells[r] = legend.querySelector(`.lgi[data-r="${r}"] em`));

  let G = null;          // geometry of the current render
  let raf = null, playing = false;

  const shortDay = d => new Date(d+"T12:00:00").toLocaleDateString("en",{month:"short",day:"numeric"});
  // "today" only when the last day in the file really is today. If the daily
  // rebuild has failed, the last point is some earlier date and labelling it
  // today would be a quiet lie about how current the chart is.
  const lastIsToday = (()=>{
    const t = new Date();
    const iso = t.getFullYear()+"-"+String(t.getMonth()+1).padStart(2,"0")+"-"+
                String(t.getDate()).padStart(2,"0");
    return days[n-1] === iso;
  })();

  function setReadout(i){
    stamp.textContent = (i===n-1 && lastIsToday) ? "today" : shortDay(days[i]);
    R.forEach(r=>{
      const g = gap[r][i];
      cells[r].textContent = g===0 ? "leading" : fmt(-g)+" back";
      cells[r].className = g===0 ? "lead" : "";
    });
  }

  // Move the clip edge, the riding faces and the readout to day i.
  function frame(i){
    if(!G) return;
    const {X, Y, pad, iw, reveal, riders, ends, narrow} = G;
    reveal.setAttribute("width", Math.max(0, X(i)-pad.l+0.5).toFixed(1));
    R.forEach((r,si)=>{
      const g = riders[si];
      g.setAttribute("transform", `translate(${X(i).toFixed(1)},${Y(gap[r][i]).toFixed(1)})`);
    });
    const done = i >= n-1;
    riders.forEach(g=>g.style.display = done ? "none" : "");
    if (ends) ends.style.opacity = done ? "1" : "0";
    setReadout(i);
    if (scrub) scrub.value = i;
  }

  function stop(){ if(raf) cancelAnimationFrame(raf); raf=null; playing=false; if(play) play.textContent="Replay"; }

  function start(){
    if(!G) return;
    stop(); playing = true; if(play) play.textContent = "Playing";
    frame(0);
    const t0 = performance.now();
    (function step(t){
      const p = Math.min(1, (t-t0)/raceMs(n));
      // Linear: a race is constant time, and an eased clock makes August look
      // slower than March for no reason. The last frame is forced rather than
      // computed, so the season always finishes ON the last day.
      if (p >= 1){ frame(n-1); stop(); return; }
      frame(Math.round(p*(n-1)));
      raf = requestAnimationFrame(step);
    })(t0);
  }

  function render(){
    const narrow = plot.clientWidth < 560;
    const W = narrow ? 460 : 900;
    const HGT = narrow ? 300 : 340;
    const pad = narrow ? {t:16,r:16,b:30,l:56} : {t:24,r:120,b:34,l:58};
    const iw = W-pad.l-pad.r, ih = HGT-pad.t-pad.b;
    const step = niceStep(Math.abs(worst)||1, narrow?3:4);
    const yMax = Math.ceil(Math.abs(worst)/step)*step || step;
    const X = i => pad.l + (n<2?0:i*iw/(n-1));
    const Y = v => pad.t + (-v)/yMax*ih;
    const fs = narrow ? 11 : 10.5;
    const AR = narrow ? 11 : 13;
    const RID = `${opts.id}`;

    let defs = `<clipPath id="rev-${RID}"><rect id="revr-${RID}" x="${pad.l}" y="0" width="0" height="${HGT}"/></clipPath>`;
    let s = `<svg viewBox="0 0 ${W} ${HGT}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${opts.aria}">`;

    for (let v=0; v<=yMax+1e-9; v+=step){
      const y = Y(-v);
      s += `<line x1="${pad.l}" y1="${y.toFixed(1)}" x2="${pad.l+iw}" y2="${y.toFixed(1)}" `+
           `stroke="${v===0?'#c3c3cd':'#eeeef2'}" stroke-width="1"/>`;
      s += `<text x="${pad.l-8}" y="${(y+4).toFixed(1)}" text-anchor="end" class="ax" style="font-size:${fs}px">${v===0?'leader':fmt(v)}</text>`;
    }
    let lastM=null;
    days.forEach((d,i)=>{
      const m=d.slice(0,7);
      if(m!==lastM){ lastM=m;
        if (narrow && Number(d.slice(5,7))%2===0) return;
        const x=X(i), lbl=new Date(d+"T12:00:00").toLocaleDateString("en",{month:"short"});
        s += `<line x1="${x.toFixed(1)}" y1="${pad.t}" x2="${x.toFixed(1)}" y2="${pad.t+ih}" stroke="#f4f4f8" stroke-width="1"/>`;
        s += `<text x="${x.toFixed(1)}" y="${pad.t+ih+18}" text-anchor="middle" class="ax" style="font-size:${fs}px">${lbl}</text>`;
      }
    });

    // the lines, revealed by the clip rect
    s += `<g clip-path="url(#rev-${RID})">`;
    R.forEach((r,si)=>{
      let d0="";
      for(let i=0;i<n;i++) d0 += (i?"L":"M")+X(i).toFixed(1)+" "+Y(gap[r][i]).toFixed(1);
      s += `<path d="${d0}" fill="none" stroke="${SERIES[si%SERIES.length]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    });
    s += `</g>`;

    // settled end labels, faded in when the race finishes
    const ends = R.map((r,si)=>({name:r, c:SERIES[si%SERIES.length], y:Y(gap[r][n-1]), v:gap[r][n-1]}));
    let endMarkup = "";
    if(!narrow){
      const MIN = AR*2+3;
      ends.sort((a,b)=>a.y-b.y);
      for(let i=1;i<ends.length;i++) if(ends[i].y-ends[i-1].y<MIN) ends[i].y=ends[i-1].y+MIN;
      const over = ends[ends.length-1].y-(pad.t+ih+AR);
      if(over>0) ends.forEach(e=>e.y-=over);
      if(ends[0].y < AR+2){ const up = AR+2-ends[0].y; ends.forEach(e=>e.y+=up); }
      ends.forEach((e,i)=>{
        const cid=`ec-${RID}-${i}`, fx=pad.l+iw+10+AR;
        defs += `<clipPath id="${cid}"><circle cx="${fx}" cy="${e.y.toFixed(1)}" r="${AR-1.5}"/></clipPath>`;
        endMarkup += `<path d="M${pad.l+iw} ${Y(e.v).toFixed(1)} L${pad.l+iw+7} ${e.y.toFixed(1)} L${(fx-AR).toFixed(1)} ${e.y.toFixed(1)}" fill="none" stroke="${e.c}" stroke-width="1" opacity=".5"/>`;
        endMarkup += `<circle cx="${pad.l+iw}" cy="${Y(e.v).toFixed(1)}" r="3" fill="${e.c}" stroke="#fff" stroke-width="1.5"/>`;
        endMarkup += AV[e.name]
          ? `<image href="${AV[e.name]}" x="${(fx-AR+1.5).toFixed(1)}" y="${(e.y-AR+1.5).toFixed(1)}" width="${(AR-1.5)*2}" height="${(AR-1.5)*2}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${cid})"/>`
          : `<circle cx="${fx}" cy="${e.y.toFixed(1)}" r="${AR-1.5}" fill="${e.c}" opacity=".25"/>`;
        endMarkup += `<circle cx="${fx}" cy="${e.y.toFixed(1)}" r="${AR-0.75}" fill="none" stroke="${e.c}" stroke-width="1.75"/>`;
        endMarkup += `<text x="${fx+AR+5}" y="${(e.y+4).toFixed(1)}" class="lbl" fill="${e.c}">${e.name}</text>`;
      });
    }
    s += `<g class="ends" style="opacity:0;transition:opacity .35s">${endMarkup}</g>`;

    // one face per rider, riding the head of its own line
    s += `<g class="riders">`;
    R.forEach((r,si)=>{
      const c = SERIES[si%SERIES.length], cid = `rc-${RID}-${si}`;
      defs += `<clipPath id="${cid}"><circle cx="0" cy="0" r="${AR-1.5}"/></clipPath>`;
      s += `<g class="rid">`;
      s += AV[r]
        ? `<image href="${AV[r]}" x="${-(AR-1.5)}" y="${-(AR-1.5)}" width="${(AR-1.5)*2}" height="${(AR-1.5)*2}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${cid})"/>`
        : `<circle r="${AR-1.5}" fill="${c}"/>`;
      s += `<circle r="${AR-0.75}" fill="none" stroke="${c}" stroke-width="2"/></g>`;
    });
    s += `</g>`;

    s += `<g class="cross" style="display:none"><line class="cx" y1="${pad.t}" y2="${pad.t+ih}"/></g>`;
    s += `<rect class="hit" x="${pad.l}" y="${pad.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
    plot.innerHTML = s.replace("<svg", "<svg").replace(">", `><defs>${defs}</defs>`, 1);

    const svg = plot.querySelector("svg");
    G = {X, Y, pad, iw, narrow,
         reveal: plot.querySelector(`#revr-${RID}`),
         riders: [...plot.querySelectorAll(".riders .rid")],
         ends: plot.querySelector(".ends")};

    // hover / scrub reads a day without disturbing the animation state
    const cross = plot.querySelector(".cross"), hit = plot.querySelector(".hit"),
          cx = cross.querySelector(".cx");
    function at(clientX){
      if (playing) return;
      const b = svg.getBoundingClientRect();
      let i = Math.round(((clientX-b.left)/b.width*W - pad.l)/iw*(n-1));
      i = Math.max(0, Math.min(n-1, i));
      cross.style.display="";
      cx.setAttribute("x1",X(i)); cx.setAttribute("x2",X(i));
      frame(i);
    }
    hit.addEventListener("mousemove", e=>at(e.clientX));
    hit.addEventListener("mouseleave", ()=>{ if(!playing){ cross.style.display="none"; frame(n-1);} });
    hit.addEventListener("touchmove", e=>{ at(e.touches[0].clientX); e.preventDefault(); },{passive:false});
    hit.addEventListener("touchstart", e=>at(e.touches[0].clientX));
  }

  if (scrub){
    scrub.max = n-1; scrub.value = n-1;
    scrub.addEventListener("input", ()=>{ stop(); frame(Number(scrub.value)); });
  }
  if (play) play.addEventListener("click", start);

  // freshness line, injected here so every page that draws a race gets it
  (function(){
    const built = H.updated || days[n-1];
    const age = Math.round((Date.now() - new Date(built+"T12:00:00").getTime())/86400000);
    const note = document.createElement("p");
    note.className = "built";
    if (age >= 2){
      note.classList.add("stale");
      note.textContent = "Heads up: the season history was last rebuilt on "
        + shortDay(built) + ", " + age + " days ago. It normally rebuilds every "
        + "morning, so this chart is behind the standings.";
    } else {
      note.textContent = "Rebuilt from Strava " + shortDay(built)
        + ". Updates every morning.";
    }
    root.appendChild(note);
  })();

  render();
  frame(n-1);
  let t=null;
  window.addEventListener("resize", ()=>{ clearTimeout(t); t=setTimeout(()=>{ const wasPlaying=playing; stop(); render(); wasPlaying?start():frame(n-1); }, 160); });

  return {play:start, stop, el:root};
}
