const CAT_COLORS = {
  'AI/ML': '#58a6ff',
  'Developer Tools': '#3fb950',
  'Security': '#f85149',
  'Infrastructure': '#e3b341',
  'Education': '#bc8cff',
  'Web Framework': '#79c0ff',
  'Data Science': '#ffa657',
  'Productivity': '#56d364',
  'Game/Creative': '#ff7b72',
  'Other': '#8b949e',
};

const SERIES_PALETTE = ['#58a6ff', '#3fb950', '#f85149', '#e3b341', '#bc8cff', '#79c0ff', '#ffa657', '#56d364', '#ff7b72', '#d2a8ff', '#7ee787', '#ffdcd7'];

function catColor(cat) { return CAT_COLORS[cat] || '#8b949e'; }

function fmt(n) {
  if (n === null || n === undefined) return '—';
  return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
}

function escHtml(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function repoUrl(repoName) { return `https://github.com/${repoName}`; }

function shortDate(iso) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

const GRID = '#21262d';
const TICK = '#7d8590';

const BASE_OPTS = {
  responsive: true,
  maintainAspectRatio: false,
  animation: { duration: 600 },
  plugins: {
    legend: {
      position: 'bottom',
      labels: { color: TICK, font: { size: 10 }, boxWidth: 10, padding: 10 },
    },
  },
  scales: {
    x: { ticks: { color: TICK, font: { size: 10 }, maxTicksLimit: 10 }, grid: { color: GRID } },
    y: { ticks: { color: TICK, font: { size: 10 } }, grid: { color: GRID }, beginAtZero: true },
  },
};

// ---------- records ----------

function renderRecords(data) {
  const { weeks, meta } = data;
  const grid = document.getElementById('records-grid');

  let streak = null, mostDays = null, velocity = null, debut = null, biggestWeek = null;

  for (const [name, m] of Object.entries(meta || {})) {
    if (!streak || m.longest_streak > streak.m.longest_streak) streak = { name, m };
    if (!mostDays || m.days_trended > mostDays.m.days_trended) mostDays = { name, m };
  }
  for (const w of weeks || []) {
    if (!biggestWeek || w.repo_count > biggestWeek.w.repo_count) biggestWeek = { w };
    for (const r of w.top_repos || []) {
      if (!velocity || r.max_stars_today > velocity.r.max_stars_today) velocity = { r, w };
    }
  }
  // biggest all-time debut week: repos whose first_seen falls within each week
  const weekList = (weeks || []).map(w => w.week);
  const debutsPerWeek = {};
  for (const [name, m] of Object.entries(meta || {})) {
    const fs = m.first_seen || '';
    const wk = weekList.find(w => fs >= w && fs <= addDays(w, 6));
    if (wk) debutsPerWeek[wk] = (debutsPerWeek[wk] || 0) + 1;
  }
  for (const [wk, n] of Object.entries(debutsPerWeek)) {
    if (!debut || n > debut.n) debut = { wk, n };
  }

  const cards = [];
  if (streak) cards.push({
    label: 'Longest trending streak',
    value: `<a href="${repoUrl(streak.name)}" target="_blank" rel="noopener">${escHtml(streak.name)}</a>`,
    detail: `${streak.m.longest_streak} consecutive days · ${streak.m.days_trended} days total`,
  });
  if (mostDays) cards.push({
    label: 'Iron repo — most days trended',
    value: `<a href="${repoUrl(mostDays.name)}" target="_blank" rel="noopener">${escHtml(mostDays.name)}</a>`,
    detail: `${mostDays.m.days_trended} days across ${mostDays.m.weeks_trended} weeks`,
  });
  if (velocity) cards.push({
    label: 'Fastest single-repo week',
    value: `<a href="${repoUrl(velocity.r.repo_name)}" target="_blank" rel="noopener">${escHtml(velocity.r.repo_name)}</a>`,
    detail: `${fmt(velocity.r.max_stars_today)} stars/day · week of ${shortDate(velocity.w.week)}`,
  });
  if (debut) cards.push({
    label: 'Biggest debut week',
    value: `${debut.n} first-ever repos`,
    detail: `week of ${shortDate(debut.wk)}`,
  });
  if (biggestWeek) cards.push({
    label: 'Widest trending week',
    value: `${biggestWeek.w.repo_count} unique repos`,
    detail: `week of ${shortDate(biggestWeek.w.week)}`,
  });

  grid.innerHTML = cards.map(c => `
    <div class="record-card">
      <div class="record-label">${c.label}</div>
      <div class="record-value">${c.value}</div>
      <div class="record-detail">${escHtml(c.detail)}</div>
    </div>
  `).join('');
}

function addDays(iso, n) {
  const d = new Date(iso);
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
}

// ---------- charts ----------

function renderExpansionChart(weeks) {
  new Chart(document.getElementById('expansion-chart'), {
    type: 'bar',
    data: {
      labels: weeks.map(w => shortDate(w.week)),
      datasets: [{
        label: 'Unique repos trending',
        data: weeks.map(w => w.repo_count),
        backgroundColor: '#58a6ff99',
        borderColor: '#58a6ff',
        borderWidth: 1,
        borderRadius: 3,
      }],
    },
    options: BASE_OPTS,
  });
}

function renderCategoryChart(weeks) {
  const totals = {};
  for (const w of weeks) {
    for (const [cat, n] of Object.entries(w.category_counts || {})) {
      totals[cat] = (totals[cat] || 0) + n;
    }
  }
  const topCats = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([c]) => c);

  new Chart(document.getElementById('category-chart'), {
    type: 'line',
    data: {
      labels: weeks.map(w => shortDate(w.week)),
      datasets: topCats.map(cat => ({
        label: cat,
        data: weeks.map(w => (w.category_counts || {})[cat] || 0),
        borderColor: catColor(cat),
        backgroundColor: catColor(cat) + '22',
        tension: 0.3,
        pointRadius: 2,
        borderWidth: 2,
        fill: false,
      })),
    },
    options: BASE_OPTS,
  });
}

function renderLanguageChart(daily) {
  // calendar-month buckets of daily language appearances
  const months = {};
  const order = [];
  for (const day of daily || []) {
    const m = day.date.slice(0, 7);
    if (!months[m]) { months[m] = {}; order.push(m); }
    for (const [lang, n] of Object.entries(day.language_counts || {})) {
      months[m][lang] = (months[m][lang] || 0) + n;
    }
  }
  const totals = {};
  for (const m of Object.values(months)) {
    for (const [lang, n] of Object.entries(m)) totals[lang] = (totals[lang] || 0) + n;
  }
  const topLangs = Object.entries(totals).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([l]) => l);

  const monthLabels = order.map(m => new Date(m + '-01').toLocaleDateString('en-GB', { month: 'short' }));

  new Chart(document.getElementById('language-chart'), {
    type: 'line',
    data: {
      labels: monthLabels,
      datasets: topLangs.map((lang, i) => ({
        label: lang,
        data: order.map(m => months[m][lang] || 0),
        borderColor: SERIES_PALETTE[i % SERIES_PALETTE.length],
        backgroundColor: SERIES_PALETTE[i % SERIES_PALETTE.length] + '22',
        tension: 0.3,
        pointRadius: 2,
        borderWidth: 2,
        fill: false,
      })),
    },
    options: BASE_OPTS,
  });
}

// ---------- leaderboards ----------

function repoRow(rank, name, sub, metricValue, metricLabel, barPct, color) {
  return `
    <div class="board-row">
      <span class="board-rank">${rank}</span>
      <div class="board-main">
        <div class="board-name"><a href="${repoUrl(name)}" target="_blank" rel="noopener">${escHtml(name)}</a></div>
        <div class="board-sub">${escHtml(sub)}</div>
        <div class="board-bar-wrap"><div class="board-bar" style="width:${barPct}%;background:${color}"></div></div>
      </div>
      <div class="board-metric">
        <div class="board-metric-strong">${metricValue}</div>
        <div class="board-metric-label">${metricLabel}</div>
      </div>
    </div>
  `;
}

function renderRepoBoard(meta, categoryMap) {
  const rows = Object.entries(meta)
    .sort((a, b) => b[1].days_trended - a[1].days_trended)
    .slice(0, 10);
  const max = rows[0]?.[1].days_trended || 1;
  document.getElementById('board-repos').innerHTML = rows.map(([name, m], i) =>
    repoRow(
      i + 1,
      name,
      `${categoryMap[name] || 'Unknown'} · first seen ${shortDate(m.first_seen)} · best streak ${m.longest_streak}d`,
      m.days_trended,
      'days',
      Math.round((m.days_trended / max) * 100),
      '#58a6ff',
    )
  ).join('');
}

function renderOwnerBoard(meta) {
  const owners = {};
  for (const [name, m] of Object.entries(meta)) {
    const owner = name.split('/')[0];
    if (!owners[owner]) owners[owner] = { days: 0, repos: 0, best: null };
    const o = owners[owner];
    o.days += m.days_trended;
    o.repos += 1;
    if (!o.best || m.days_trended > o.best.days) o.best = { name, days: m.days_trended };
  }
  const rows = Object.entries(owners)
    .filter(([, o]) => o.repos >= 2 || o.days >= 8)
    .sort((a, b) => b[1].days - a[1].days)
    .slice(0, 10);
  const max = rows[0]?.[1].days || 1;
  document.getElementById('board-owners').innerHTML = rows.map(([owner, o], i) => `
    <div class="board-row">
      <span class="board-rank">${i + 1}</span>
      <div class="board-main">
        <div class="board-name"><a href="https://github.com/${escHtml(owner)}" target="_blank" rel="noopener">@${escHtml(owner)}</a></div>
        <div class="board-sub">${o.repos} repo${o.repos > 1 ? 's' : ''} · best: ${escHtml(o.best.name)} (${o.best.days}d)</div>
        <div class="board-bar-wrap"><div class="board-bar" style="width:${Math.round((o.days / max) * 100)}%;background:#bc8cff"></div></div>
      </div>
      <div class="board-metric">
        <div class="board-metric-strong">${o.days}</div>
        <div class="board-metric-label">repo-days</div>
      </div>
    </div>
  `).join('');
}

// ---------- sparklines ----------

function renderSparks(series, meta) {
  const grid = document.getElementById('spark-grid');
  const entries = Object.entries(series || {})
    .map(([name, pts]) => {
      const first = pts[0]?.[1] || 0;
      const last = pts[pts.length - 1]?.[1] || 0;
      const span = pts.length > 1
        ? Math.round((new Date(pts[pts.length - 1][0]) - new Date(pts[0][0])) / 86400000) + 1
        : 1;
      return { name, pts, first, last, span, growth: first ? (last - first) / first : 0 };
    })
    .sort((a, b) => b.last - a.last)
    .slice(0, 12);

  if (!entries.length) {
    grid.innerHTML = '<div class="no-data">No growth series available.</div>';
    return;
  }

  grid.innerHTML = entries.map((e, i) => {
    const windowClass = e.span >= 45 ? ' long' : e.span <= 7 ? ' short' : '';
    const growthLabel = e.span <= 1
      ? '<span class="spark-growth new">new</span>'
      : `<span class="spark-growth">▲ ${(e.growth * 100).toFixed(0)}%</span>`;
    return `
    <div class="spark-card">
      <div class="spark-head">
        <span class="spark-name"><a href="${repoUrl(e.name)}" target="_blank" rel="noopener">${escHtml(e.name)}</a></span>
        ${growthLabel}
        <span class="spark-window${windowClass}">${e.span}d</span>
      </div>
      <div class="spark-canvas-wrap"><canvas id="spark-${i}"></canvas></div>
      <div class="spark-foot">
        <span>${shortDate(e.pts[0][0])} → ${shortDate(e.pts[e.pts.length - 1][0])}</span>
        <span>★ ${fmt(e.last)}</span>
      </div>
    </div>
  `;
  }).join('');

  entries.forEach((e, i) => {
    const chartPts = e.pts.length === 1
      ? [e.pts[0], [addDays(e.pts[0][0], 1), e.pts[0][1]]]
      : e.pts;
    new Chart(document.getElementById(`spark-${i}`), {
      type: 'line',
      data: {
        labels: chartPts.map(p => p[0]),
        datasets: [{
          data: chartPts.map(p => p[1]),
          borderColor: '#3fb950',
          backgroundColor: '#3fb95022',
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.25,
          fill: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: { legend: { display: false }, tooltip: { enabled: false } },
        scales: { x: { display: false }, y: { display: false } },
      },
    });
  });
}

function clusterColor(index) {
  const hue = (index * 137.508) % 360;
  return `hsl(${hue.toFixed(1)}, 68%, 62%)`;
}

function renderClusterTimeline(timeline) {
  const card = document.getElementById('cluster-timeline-card');
  const canvas = document.getElementById('cluster-timeline-chart');
  if (!card || !canvas) return;

  const weeks = (timeline && timeline.weeks) || [];
  const series = (timeline && timeline.series) || {};
  if (!weeks.length || !Object.keys(series).length) {
    card.style.display = 'none';
    return;
  }
  card.style.display = '';

  const latestWeek = weeks[weeks.length - 1];
  const entries = Object.entries(series)
    .map(([key, s]) => ({
      key,
      label: s.label || key,
      byWeek: Object.fromEntries((s.points || []).map(p => [p.week, p.size])),
      total: (s.points || []).reduce((sum, p) => sum + p.size, 0),
    }))
    .sort((a, b) => (b.byWeek[latestWeek] || 0) - (a.byWeek[latestWeek] || 0) || b.total - a.total);

  const top = entries.slice(0, 15);
  const datasets = top.map((e, i) => ({
    label: e.label,
    data: weeks.map(w => e.byWeek[w] || 0),
    backgroundColor: clusterColor(i) + '88',
    borderColor: clusterColor(i),
    borderWidth: 1,
    fill: true,
    pointRadius: 0,
    tension: 0.25,
  }));

  if (entries.length > top.length) {
    const otherByWeek = {};
    for (const e of entries.slice(top.length)) {
      for (const w of weeks) otherByWeek[w] = (otherByWeek[w] || 0) + (e.byWeek[w] || 0);
    }
    datasets.unshift({
      label: `Other themes (${entries.length - top.length})`,
      data: weeks.map(w => otherByWeek[w] || 0),
      backgroundColor: 'rgba(139, 148, 158, 0.15)',
      borderColor: 'rgba(139, 148, 158, 0.4)',
      borderWidth: 1,
      fill: true,
      pointRadius: 0,
      tension: 0.25,
    });
  }

  new Chart(canvas, {
    type: 'line',
    data: { labels: weeks.map(w => shortDate(w)), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600 },
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: TICK, font: { size: 9 }, boxWidth: 10, padding: 6 },
        },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            label(ctx) {
              return ` ${ctx.dataset.label}: ${ctx.raw} repos`;
            },
          },
        },
      },
      scales: {
        x: { stacked: true, ticks: { color: TICK, font: { size: 10 }, maxTicksLimit: 10 }, grid: { color: GRID } },
        y: { stacked: true, ticks: { color: TICK, font: { size: 10 } }, grid: { color: GRID }, beginAtZero: true },
      },
    },
  });
}

// ---------- init ----------

async function init() {
  let data;
  try {
    const res = await fetch('data/history.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (e) {
    document.getElementById('header-sub').textContent = 'history.json not found — run export_data.py first';
    document.getElementById('records-grid').innerHTML = '<div class="no-data">No long-horizon data available yet.</div>';
    return;
  }

  const days = (data.daily || []).length;
  const weeks = (data.weeks || []).length;
  const repos = Object.keys(data.meta || {}).length;

  document.getElementById('header-sub').textContent =
    `All-time view · ${days} days · ${weeks} weeks · since ${shortDate(data.first_date)}`;

  document.getElementById('stats-pills').innerHTML = [
    `<span class="pill"><strong>${repos}</strong> repos tracked</span>`,
    `<span class="pill"><strong>${days}</strong> days of data</span>`,
    `<span class="pill"><strong>${weeks}</strong> weeks</span>`,
  ].join('');

  renderRecords(data);
  renderExpansionChart(data.weeks || []);
  renderCategoryChart(data.weeks || []);
  renderLanguageChart(data.daily || []);
  renderClusterTimeline(data.cluster_timeline || null);
  renderRepoBoard(data.meta || {}, data.categories || {});
  renderOwnerBoard(data.meta || {});
  renderSparks(data.series || {}, data.meta || {});

  const ts = new Date(data.generated_at);
  document.getElementById('footer-ts').textContent =
    'Updated ' + ts.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC';
}

init();
