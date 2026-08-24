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
  'Unknown': '#484f58',
};

const STAR_LABELS = {
  daily: 'stars today', weekly: 'stars this week', monthly: 'stars this month'
};

function catColor(cat) {
  return CAT_COLORS[cat] || '#8b949e';
}

function fmt(n) {
  if (!n && n !== 0) return '—';
  return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
}

function escHtml(s) {
  if (!s) return '';
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

const REPO_MENTION_RE = /(^|[^A-Za-z0-9-])([A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9_.-]+)(?=$|[^A-Za-z0-9_.-])/gm;

function repoUrl(repoName) {
  const [owner, repo] = String(repoName || '').split('/');
  if (!owner || !repo) return '#';
  return `https://github.com/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
}

function isLikelyRepoName(repoName, allowedRepos = new Set()) {
  if (!repoName) return false;
  if (allowedRepos.has(repoName)) return true;
  return /[a-z0-9_.-]/.test(repoName);
}

function linkifyRepoMentions(text, allowedRepos = new Set()) {
  if (!text) return '';

  let html = '';
  let lastIndex = 0;

  for (const match of text.matchAll(REPO_MENTION_RE)) {
    const prefix = match[1];
    const repoName = match[2];
    const repoStart = match.index + prefix.length;

    html += escHtml(text.slice(lastIndex, repoStart));
    if (isLikelyRepoName(repoName, allowedRepos)) {
      html += `<a href="${repoUrl(repoName)}" target="_blank" rel="noopener">${escHtml(repoName)}</a>`;
    } else {
      html += escHtml(repoName);
    }
    lastIndex = repoStart + repoName.length;
  }

  html += escHtml(text.slice(lastIndex));
  return html;
}

function renderDigest(digest) {
  const el = document.getElementById('digest-section');
  if (!digest) {
    el.innerHTML = '<div class="card-label">Weekly Signal</div><p style="color:var(--text-muted);font-size:.85rem">No digest available yet — runs weekly on Sundays.</p>';
    return;
  }

  const prose = digest.digest || '';
  const paras = prose.split(/\n\n+/).filter(Boolean);
  const preview = paras.slice(0, 2).join('\n\n');
  const hasMore = paras.length > 2;
  const explicitRepos = new Set((digest.top_repos || []).filter(Boolean));
  const renderedPreview = linkifyRepoMentions(preview, explicitRepos);
  const renderedProse = linkifyRepoMentions(prose, explicitRepos);

  const week = digest.week_start
    ? new Date(digest.week_start).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) + ' – ' +
      new Date(digest.week_end).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : '';

  const confidenceLabel = digest.confidence_label;
  const confidencePill = (confidenceLabel === 'low' || confidenceLabel === 'medium')
    ? '<span class="digest-confidence">⚠ Limited data — early analysis</span>'
    : '';

  el.innerHTML = `
    <div class="card-label">Weekly Signal</div>
    <div class="digest-meta"><span>Week of ${escHtml(week)}</span>${confidencePill}</div>
    <div class="digest-headline">${escHtml(digest.headline || '')}</div>
    <div class="digest-prose truncated" id="digest-prose">${renderedPreview}</div>
    ${hasMore ? '<button class="read-more-btn" id="read-more-btn">Read more ↓</button>' : ''}
  `;

  if (hasMore) {
    document.getElementById('read-more-btn').onclick = function() {
      document.getElementById('digest-prose').classList.remove('truncated');
      document.getElementById('digest-prose').innerHTML = renderedProse;
      this.remove();
    };
  }
}

function renderRepoCard(repo, period) {
  const color = catColor(repo.category);
  const ghUrl = `https://github.com/${escHtml(repo.repo_name)}`;
  const [owner, name] = (repo.repo_name || '/').split('/');
  const themes = (repo.key_themes || []).slice(0, 4).map(t =>
    `<span class="kw-pill">${escHtml(t)}</span>`
  ).join('');
  const starLabel = STAR_LABELS[period] || 'stars';
  const historyBadge = repo.first_seen
    ? `<span class="repo-history" title="First seen in trending ${escHtml(repo.first_seen)}">first seen ${fmtDate(repo.first_seen)} · ${repo.days_trended}d in trending</span>`
    : '';

  return `
    <div class="repo-card" style="--cat-color:${color}">
      <div class="repo-card-top">
        <div class="repo-name">
          <a href="${ghUrl}" target="_blank" rel="noopener">
            <span class="owner">${escHtml(owner)}/</span><strong>${escHtml(name)}</strong>
          </a>
        </div>
        <span class="cat-badge" style="background:${color}">${escHtml(repo.category)}</span>
      </div>
      ${repo.description ? `<div class="repo-desc">${escHtml(repo.description)}</div>` : ''}
      <div class="repo-stats">
        <span class="repo-stars">★ ${fmt(repo.stars_in_period)} ${starLabel}</span>
        ${repo.forks ? `<span class="repo-forks">⑂ ${fmt(repo.forks)}</span>` : ''}
        ${repo.language ? `<span class="lang-pill">${escHtml(repo.language)}</span>` : ''}
      </div>
      ${historyBadge}
      ${themes ? `<div class="repo-themes">${themes}</div>` : ''}
      ${repo.notable_because
        ? `<div class="repo-notable"><div class="repo-notable-label">✦ Why notable</div>${escHtml(repo.notable_because)}</div>`
        : repo.purpose ? `<div class="repo-purpose">${escHtml(repo.purpose)}</div>` : ''
      }
    </div>
  `;
}

function fmtDate(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function renderRepos(todayData, period) {
  const grid = document.getElementById('repo-grid');
  const repos = todayData[period] || [];
  if (!repos.length) {
    grid.innerHTML = `<div class="no-data">No ${period} data for this date.</div>`;
    return;
  }
  grid.innerHTML = repos.map((repo, index) => {
    const card = renderRepoCard(repo, period);
    return card.replace('class="repo-card"', `class="repo-card" style="--cat-color:${catColor(repo.category)};animation-delay:${index * 0.03}s"`);
  }).join('');
}

function renderOwners(todayData) {
  const allRepos = [
    ...(todayData.daily || []),
    ...(todayData.weekly || []),
    ...(todayData.monthly || []),
  ];

  const byOwner = {};
  for (const repo of allRepos) {
    const owner = repo.owner_name;
    if (!owner) continue;
    if (!byOwner[owner]) byOwner[owner] = { type: repo.owner_type, repos: new Map() };
    byOwner[owner].repos.set(repo.repo_name, repo);
  }

  const top4 = Object.entries(byOwner)
    .sort((a, b) => b[1].repos.size - a[1].repos.size)
    .slice(0, 4);

  if (!top4.length) return;

  const grid = document.getElementById('owner-grid');

  grid.innerHTML = top4.map(([owner, value]) => {
    const repoLinks = [...value.repos.values()].map(repo =>
      `<a class="owner-repo-link" href="https://github.com/${escHtml(repo.repo_name)}" target="_blank" rel="noopener">
        ${escHtml(repo.repo_name.split('/')[1])}
        ${repo.category !== 'Unknown' ? `<span style="color:${catColor(repo.category)};font-size:.68rem"> · ${escHtml(repo.category)}</span>` : ''}
      </a>`
    ).join('');
    const badge = value.repos.size > 1
      ? `<span style="color:var(--accent);font-size:.72rem;font-weight:600">${value.repos.size} repos trending</span>`
      : '<span style="color:var(--text-muted);font-size:.72rem">1 repo trending</span>';
    return `
      <div class="owner-card">
        <div class="owner-name"><a href="https://github.com/${escHtml(owner)}" target="_blank" rel="noopener">@${escHtml(owner)}</a></div>
        <div class="owner-type">${escHtml((value.type || 'unknown').replace(/_/g, ' '))} · ${badge}</div>
        <div class="owner-repos">${repoLinks}</div>
      </div>
    `;
  }).join('');
}

const CLUSTER_PALETTE = [
  '#58a6ff', '#3fb950', '#f85149', '#e3b341', '#bc8cff',
  '#79c0ff', '#ffa657', '#56d364', '#ff7b72', '#d2a8ff',
  '#a5d6ff', '#7ee787', '#ffdcd7', '#ffe585', '#cae8ff',
];

let clusterChart;
let clusterChartMode = 'scatter';
let lastClusterData = null;
let clusterColorMap = {};
const mapState = { focus: null, hover: null, query: '' };

function clusterColor(index) {
  const hue = (index * 137.508) % 360;
  return `hsl(${hue.toFixed(1)}, 68%, 62%)`;
}

function withAlpha(color, alpha) {
  return color.replace('hsl(', 'hsla(').replace(')', `, ${alpha})`);
}

function buildColorMap(clusters) {
  const map = {};
  clusters.forEach((cluster, index) => {
    map[cluster.id] = clusterColor(index);
  });
  return map;
}

function clusterRepoCount(cluster) {
  return cluster.size || (cluster.repos || []).length || 0;
}

function starRadius(stars) {
  if (!stars || stars <= 0) return 3;
  return Math.min(12, 3 + Math.log10(stars) * 1.8);
}

function fmtStars(n) {
  if (!n) return '0';
  if (n >= 1000) return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
  return String(n);
}

function pointMatches(point) {
  const q = mapState.query.trim().toLowerCase();
  return !q || (point.repo || '').toLowerCase().includes(q);
}

function activeFocus() {
  return mapState.hover !== null ? mapState.hover : mapState.focus;
}

function buildScatterDatasets(clusters, scatter) {
  const focus = activeFocus();
  const searching = mapState.query.trim() !== '';
  return clusters.map(cluster => {
    const points = scatter
      .filter(point => point.cluster_id === cluster.id)
      .map(point => ({ x: point.x, y: point.y, repo: point.repo_name, stars: point.total_stars || 0, cid: cluster.id }));
    const dimmed = focus !== null && focus !== cluster.id;
    return {
      label: cluster.label,
      cid: cluster.id,
      data: points,
      pointRadius: points.map(p => (searching && pointMatches(p) ? starRadius(p.stars) + 2.5 : starRadius(p.stars))),
      pointHoverRadius: points.map(p => starRadius(p.stars) + 4),
      pointBackgroundColor: points.map(p => {
        if (dimmed) return 'rgba(139, 148, 158, 0.10)';
        if (searching) return pointMatches(p) ? clusterColorMap[cluster.id] : 'rgba(139, 148, 158, 0.14)';
        return clusterColorMap[cluster.id];
      }),
      pointBorderColor: points.map(p => (searching && pointMatches(p) && !dimmed ? '#f0f6fc' : 'transparent')),
      pointBorderWidth: 1.5,
      pointHoverBorderColor: '#f0f6fc',
      pointHoverBorderWidth: 1.5,
    };
  });
}

function buildPieDataset(clusters, colorMap) {
  return {
    labels: clusters.map(cluster => cluster.label),
    datasets: [{
      data: clusters.map(cluster => clusterRepoCount(cluster)),
      backgroundColor: clusters.map(cluster => withAlpha(clusterColorMap[cluster.id], 0.8)),
      borderColor: clusters.map(cluster => colorMap[cluster.id]),
      borderWidth: 1,
      hoverOffset: 8,
    }],
  };
}

const clusterLabelsPlugin = {
  id: 'clusterLabels',
  afterDatasetsDraw(chart) {
    const opts = chart.options.plugins.clusterLabels;
    if (!opts || chart.config.type !== 'scatter') return;
    const { ctx, chartArea } = chart;
    ctx.save();
    ctx.font = '600 11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.lineWidth = 3;
    ctx.strokeStyle = 'rgba(13, 17, 23, 0.85)';
    const priority = cluster => {
      if (mapState.hover === cluster.id) return 0;
      if (mapState.focus === cluster.id) return 1;
      if (meta[cluster.id] && meta[cluster.id].hasMatch) return 2;
      return 3;
    };
    const meta = opts.meta;
    const drawn = [];
    const visible = opts.clusters
      .filter(c => meta[c.id] && meta[c.id].show)
      .sort((a, b) => priority(a) - priority(b) || clusterRepoCount(b) - clusterRepoCount(a));
    for (const cluster of visible) {
      const m = meta[cluster.id];
      const px = chart.scales.x.getPixelForValue(m.cx);
      const py = chart.scales.y.getPixelForValue(m.cy);
      if (px < chartArea.left + 30 || px > chartArea.right - 30 || py < chartArea.top + 14 || py > chartArea.bottom) continue;
      const w = ctx.measureText(cluster.label).width;
      const box = { x1: px - w / 2 - 3, x2: px + w / 2 + 3, y1: py - 22, y2: py - 7 };
      if (drawn.some(b => !(box.x2 < b.x1 || box.x1 > b.x2 || box.y2 < b.y1 || box.y1 > b.y2))) continue;
      drawn.push(box);
      ctx.strokeText(cluster.label, px, py - 9);
      ctx.fillStyle = opts.colors[cluster.id];
      ctx.fillText(cluster.label, px, py - 9);
    }
    ctx.restore();
  },
};

function computeLabelMeta(clusters, scatter) {
  const byCluster = {};
  scatter.forEach(point => {
    (byCluster[point.cluster_id] = byCluster[point.cluster_id] || []).push(point);
  });
  const topN = new Set(
    [...clusters].sort((a, b) => clusterRepoCount(b) - clusterRepoCount(a)).slice(0, 14).map(c => c.id)
  );
  const meta = {};
  clusters.forEach(cluster => {
    const points = byCluster[cluster.id] || [];
    if (!points.length) {
      meta[cluster.id] = { show: false };
      return;
    }
    const cx = points.reduce((sum, p) => sum + p.x, 0) / points.length;
    const cy = points.reduce((sum, p) => sum + p.y, 0) / points.length;
    const hasMatch = mapState.query.trim() !== '' && points.some(p => pointMatches({ repo: p.repo_name }));
    meta[cluster.id] = {
      cx,
      cy,
      show: topN.has(cluster.id) || mapState.focus === cluster.id || mapState.hover === cluster.id || hasMatch,
    };
  });
  return meta;
}

function renderClusters(clusterData) {
  const section = document.getElementById('cluster-section');
  const listEl = document.getElementById('cluster-list');

  if (!clusterData || !clusterData.clusters || !clusterData.clusters.length) {
    section.style.display = 'none';
    return;
  }

  section.style.display = '';
  lastClusterData = clusterData;
  clusterColorMap = buildColorMap(clusterData.clusters);

  const clusters = clusterData.clusters;
  const scatter = clusterData.scatter || [];

  renderClusterChart(clusters, scatter, clusterChartMode);

  listEl.innerHTML = clusters.map(cluster => {
    const color = clusterColorMap[cluster.id];
    const repoLinks = (cluster.repos || []).slice(0, 6).map(repo => {
      const name = repo.split('/')[1] || repo;
      return `<a class="cluster-repo-pill" href="https://github.com/${escHtml(repo)}" target="_blank" rel="noopener">${escHtml(name)}</a>`;
    }).join('');
    const moreCount = (cluster.repos || []).length - 6;
    const more = moreCount > 0
      ? `<span class="cluster-repo-pill" style="color:var(--text-muted)">+${moreCount} more</span>`
      : '';
    return `
      <div class="cluster-item" style="--cl-color:${color}" data-cid="${cluster.id}">
        <div class="cluster-item-header">
          <span class="cluster-dot"></span>
          <span class="cluster-label">${escHtml(cluster.label)}</span>
          <span class="cluster-size">${cluster.size} repos</span>
        </div>
        ${cluster.description ? `<div class="cluster-desc">${escHtml(cluster.description)}</div>` : ''}
        <div class="cluster-repos">${repoLinks}${more}</div>
      </div>
    `;
  }).join('');
  updateListHighlight();
}

function renderClusterChart(clusters, scatter, mode) {
  const ctx = document.getElementById('cluster-chart').getContext('2d');
  const titleEl = document.getElementById('cluster-chart-title');
  if (clusterChart) clusterChart.destroy();

  if (titleEl) {
    titleEl.firstChild.textContent = mode === 'pie' ? 'Cluster Share' : 'Semantic Map';
  }

  const datasets = buildScatterDatasets(clusters, scatter);
  const pieData = buildPieDataset(clusters, clusterColorMap);

  clusterChart = new Chart(ctx, {
    type: mode === 'pie' ? 'pie' : 'scatter',
    data: mode === 'pie' ? pieData : { datasets },
    plugins: mode === 'pie' ? [] : [clusterLabelsPlugin],
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: {
          display: mode === 'pie' || clusters.length <= 8,
          position: 'bottom',
          labels: { color: '#7d8590', font: { size: 10 }, boxWidth: 10, padding: 8 },
        },
        tooltip: {
          callbacks: {
            label(ctx) {
              if (mode === 'pie') {
                const count = ctx.raw || 0;
                const total = pieData.datasets[0].data.reduce((sum, value) => sum + value, 0);
                const pct = total ? Math.round((count / total) * 100) : 0;
                return `${ctx.label}: ${count} repos (${pct}%)`;
              }
              const pt = ctx.raw;
              const name = (pt.repo || '').split('/')[1] || pt.repo;
              return ` ${name} · ★ ${fmtStars(pt.stars)}`;
            },
            afterLabel(ctx) {
              if (mode === 'pie') return '';
              return ctx.dataset.label;
            },
          },
        },
        zoom: {
          pan: { enabled: true, mode: 'xy' },
          zoom: {
            wheel: { enabled: true, speed: 0.7 },
            pinch: { enabled: true },
            mode: 'xy',
          },
          limits: {
            x: { min: 'original', max: 'original' },
            y: { min: 'original', max: 'original' },
          },
        },
        clusterLabels: {
          clusters,
          meta: computeLabelMeta(clusters, scatter),
          colors: clusterColorMap,
        },
      },
      scales: mode === 'pie' ? {} : {
        x: { ticks: { display: false }, grid: { color: '#21262d' } },
        y: { ticks: { display: false }, grid: { color: '#21262d' } },
      },
      onClick(event, elements) {
        if (mode === 'pie' || !elements.length) return;
        const cid = datasets[elements[0].datasetIndex].cid;
        setClusterFocus(mapState.focus === cid ? null : cid);
      },
      onHover(event, elements) {
        if (mode !== 'scatter') return;
        const cid = elements.length ? datasets[elements[0].datasetIndex].cid : null;
        setHotCard(cid);
      },
    },
  });
}

function refreshMap() {
  if (!clusterChart || clusterChartMode !== 'scatter' || !lastClusterData) return;
  const clusters = lastClusterData.clusters;
  const scatter = lastClusterData.scatter || [];
  clusterChart.data.datasets = buildScatterDatasets(clusters, scatter);
  clusterChart.options.plugins.clusterLabels.meta = computeLabelMeta(clusters, scatter);
  clusterChart.update();
  updateListHighlight();
}

function setClusterFocus(cid) {
  mapState.focus = cid;
  refreshMap();
}

let hotCid = null;
function setHotCard(cid) {
  if (hotCid === cid) return;
  hotCid = cid;
  const listEl = document.getElementById('cluster-list');
  listEl.querySelectorAll('.cluster-item').forEach(item => {
    item.classList.toggle('hot', Number(item.dataset.cid) === cid);
  });
  if (cid === null) return;
  const card = listEl.querySelector(`.cluster-item[data-cid="${cid}"]`);
  if (card) card.scrollIntoView({ block: 'nearest' });
}

function updateListHighlight() {
  const listEl = document.getElementById('cluster-list');
  listEl.querySelectorAll('.cluster-item').forEach(item => {
    const cid = Number(item.dataset.cid);
    item.classList.toggle('focused', mapState.focus === cid);
    item.classList.toggle('dimmed', mapState.focus !== null && mapState.focus !== cid);
  });
}

function updateMatchCount() {
  const el = document.getElementById('map-match-count');
  if (!el) return;
  const q = mapState.query.trim().toLowerCase();
  if (!q || !lastClusterData) {
    el.textContent = '';
    return;
  }
  const n = (lastClusterData.scatter || []).filter(p => (p.repo_name || '').toLowerCase().includes(q)).length;
  el.textContent = n === 1 ? '1 match' : `${n} matches`;
}

document.getElementById('btn-scatter').addEventListener('click', () => {
  if (clusterChartMode === 'scatter' || !lastClusterData) return;
  clusterChartMode = 'scatter';
  document.getElementById('btn-scatter').classList.add('active');
  document.getElementById('btn-pie').classList.remove('active');
  renderClusterChart(lastClusterData.clusters, lastClusterData.scatter || [], 'scatter');
});

document.getElementById('btn-pie').addEventListener('click', () => {
  if (clusterChartMode === 'pie' || !lastClusterData) return;
  clusterChartMode = 'pie';
  document.getElementById('btn-pie').classList.add('active');
  document.getElementById('btn-scatter').classList.remove('active');
  renderClusterChart(lastClusterData.clusters, lastClusterData.scatter || [], 'pie');
});

const clusterListEl = document.getElementById('cluster-list');
clusterListEl.addEventListener('click', event => {
  const item = event.target.closest('.cluster-item');
  if (!item || event.target.closest('a')) return;
  const cid = Number(item.dataset.cid);
  setClusterFocus(mapState.focus === cid ? null : cid);
});
clusterListEl.addEventListener('mouseover', event => {
  const item = event.target.closest('.cluster-item');
  if (!item) return;
  mapState.hover = Number(item.dataset.cid);
  refreshMap();
});
clusterListEl.addEventListener('mouseleave', () => {
  mapState.hover = null;
  refreshMap();
});

const mapSearchEl = document.getElementById('map-search');
if (mapSearchEl) {
  mapSearchEl.addEventListener('input', () => {
    mapState.query = mapSearchEl.value;
    updateMatchCount();
    refreshMap();
  });
}

const mapResetBtn = document.getElementById('btn-map-reset');
if (mapResetBtn) {
  mapResetBtn.addEventListener('click', () => {
    mapState.focus = null;
    mapState.query = '';
    if (mapSearchEl) mapSearchEl.value = '';
    updateMatchCount();
    refreshMap();
    if (clusterChart && clusterChartMode === 'scatter') clusterChart.resetZoom();
  });
}

let currentData = null;

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', function() {
    document.querySelectorAll('.tab-btn').forEach(button => button.classList.remove('active'));
    this.classList.add('active');
    if (currentData) renderRepos(currentData.today, this.dataset.period);
  });
});

function renderSnapshot(data) {
  currentData = data;

  const d = new Date(data.as_of_date);
  document.getElementById('header-date').textContent =
    'As of ' + d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });

  const s = data.stats || {};
  document.getElementById('stats-pills').innerHTML = [
    s.total_repos ? `<span class="pill"><strong>${s.total_repos}</strong> repos tracked</span>` : '',
    s.days_tracked ? `<span class="pill"><strong>${s.days_tracked}</strong> days of data</span>` : '',
    (data.today?.daily?.length || 0) > 0
      ? `<span class="pill"><strong>${data.today.daily.length}</strong> trending today</span>` : '',
  ].join('');

  renderDigest(data.digest);

  document.querySelectorAll('.tab-btn').forEach(button => button.classList.remove('active'));
  document.querySelector('.tab-btn[data-period="daily"]').classList.add('active');
  renderRepos(data.today || {}, 'daily');

  renderOwners(data.today || {});

  renderClusters(data.clusters || null);

  const ts = new Date(data.generated_at);
  document.getElementById('footer-ts').textContent =
    'Updated ' + ts.toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC';
}

async function loadSnapshot(dateStr) {
  const url = dateStr ? `data/archive/${dateStr}.json` : 'data/snapshot.json';
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function init() {
  const picker = document.getElementById('date-picker');
  try {
    const idxRes = await fetch('data/archive/index.json');
    if (idxRes.ok) {
      const body = await idxRes.text();
      let dates;
      try {
        dates = JSON.parse(body);
      } catch (_) {
        // Tolerate a plain newline-separated date list
        dates = body.split('\n').map(s => s.trim()).filter(Boolean);
      }
      if (!Array.isArray(dates) || dates.length === 0) throw new Error('empty archive index');
      picker.innerHTML = dates.map((date, index) =>
        `<option value="${date}">${index === 0 ? '★ ' : ''}${date}</option>`
      ).join('');
      picker.addEventListener('change', async function() {
        try {
          const data = await loadSnapshot(this.value);
          renderSnapshot(data);
        } catch (error) {
          console.error('Failed to load archive:', error);
        }
      });
    }
  } catch (_) {
    picker.innerHTML = '<option value="">—</option>';
  }

  try {
    const data = await loadSnapshot('');
    renderSnapshot(data);
    if (picker.options.length > 0) picker.selectedIndex = 0;
  } catch (error) {
    document.getElementById('digest-section').innerHTML =
      '<div class="card-label">Weekly Signal</div>' +
      '<p style="color:var(--text-muted);font-size:.85rem">Data not yet available — the pipeline runs daily at 10:00 UTC.</p>';
    document.getElementById('repo-grid').innerHTML =
      '<div class="no-data">No snapshot found. Check back after the first pipeline run.</div>';
  }
}

init();