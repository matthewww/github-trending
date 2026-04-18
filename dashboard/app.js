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
      ${themes ? `<div class="repo-themes">${themes}</div>` : ''}
      ${repo.notable_because
        ? `<div class="repo-notable"><div class="repo-notable-label">✦ Why notable</div>${escHtml(repo.notable_because)}</div>`
        : repo.purpose ? `<div class="repo-purpose">${escHtml(repo.purpose)}</div>` : ''
      }
    </div>
  `;
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

let trendChart;
let langChart;

function renderTrendChart(history) {
  const ctx = document.getElementById('trend-chart').getContext('2d');
  if (trendChart) trendChart.destroy();

  const days = history.slice(0, 30).reverse();
  const labels = days.map(day => {
    const dt = new Date(day.date);
    return dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
  });

  const totals = {};
  for (const day of days) {
    for (const [cat, count] of Object.entries(day.category_counts || {})) {
      totals[cat] = (totals[cat] || 0) + count;
    }
  }

  const topCats = Object.entries(totals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([cat]) => cat)
    .filter(cat => cat !== 'Unknown');

  const datasets = topCats.map(cat => ({
    label: cat,
    data: days.map(day => (day.category_counts || {})[cat] || 0),
    borderColor: catColor(cat),
    backgroundColor: catColor(cat) + '22',
    tension: 0.3,
    pointRadius: 2,
    borderWidth: 2,
    fill: false,
  }));

  trendChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600 },
      plugins: {
        legend: {
          labels: { color: '#7d8590', font: { size: 11 }, boxWidth: 12, padding: 12 },
          position: 'bottom',
        },
        tooltip: { mode: 'index', intersect: false },
      },
      scales: {
        x: {
          ticks: { color: '#7d8590', maxTicksLimit: 8, font: { size: 10 } },
          grid: { color: '#21262d' },
        },
        y: {
          ticks: { color: '#7d8590', font: { size: 10 }, stepSize: 1 },
          grid: { color: '#21262d' },
          beginAtZero: true,
        },
      },
    },
  });
}

function renderLangChart(history) {
  const ctx = document.getElementById('lang-chart').getContext('2d');
  if (langChart) langChart.destroy();

  const thisWeek = {};
  const lastWeek = {};

  (history || []).slice(0, 7).forEach(day => {
    for (const [lang, count] of Object.entries(day.language_counts || {})) {
      thisWeek[lang] = (thisWeek[lang] || 0) + count;
    }
  });

  (history || []).slice(7, 14).forEach(day => {
    for (const [lang, count] of Object.entries(day.language_counts || {})) {
      lastWeek[lang] = (lastWeek[lang] || 0) + count;
    }
  });

  const allLangs = new Set([...Object.keys(thisWeek), ...Object.keys(lastWeek)]);
  const langs = [...allLangs]
    .sort((a, b) => (thisWeek[b] || 0) - (thisWeek[a] || 0))
    .slice(0, 8)
    .reverse();

  langChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: langs,
      datasets: [
        {
          label: 'This week',
          data: langs.map(lang => thisWeek[lang] || 0),
          backgroundColor: '#58a6ff99',
          borderColor: '#58a6ff',
          borderWidth: 1,
          borderRadius: 3,
        },
        {
          label: 'Last week',
          data: langs.map(lang => lastWeek[lang] || 0),
          backgroundColor: '#3fb95055',
          borderColor: '#3fb950',
          borderWidth: 1,
          borderRadius: 3,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600 },
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#7d8590', font: { size: 11 }, boxWidth: 12, padding: 10 },
        },
        tooltip: {
          callbacks: {
            afterLabel(ctx) {
              const lang = ctx.label;
              const tw = thisWeek[lang] || 0;
              const lw = lastWeek[lang] || 0;
              if (!lw) return '';
              const delta = tw - lw;
              return delta > 0 ? `▲ +${delta} vs last week` : delta < 0 ? `▼ ${delta} vs last week` : '→ no change';
            },
          },
        },
      },
      scales: {
        x: {
          ticks: { color: '#7d8590', font: { size: 10 }, stepSize: 1 },
          grid: { color: '#21262d' },
          beginAtZero: true,
        },
        y: {
          ticks: { color: '#e6edf3', font: { size: 11 } },
          grid: { color: '#21262d' },
        },
      },
    },
  });
}

const CLUSTER_PALETTE = [
  '#58a6ff', '#3fb950', '#f85149', '#e3b341', '#bc8cff',
  '#79c0ff', '#ffa657', '#56d364', '#ff7b72', '#d2a8ff',
  '#a5d6ff', '#7ee787', '#ffdcd7', '#ffe585', '#cae8ff',
];

let clusterChart;
let clusterChartMode = 'scatter';
let lastClusterData = null;

function buildScatterDatasets(clusters, scatter) {
  return clusters.map(cluster => {
    const points = scatter.filter(point => point.cluster_id === cluster.id);
    return {
      label: cluster.label,
      data: points.map(point => ({ x: point.x, y: point.y, repo: point.repo_name })),
      backgroundColor: CLUSTER_PALETTE[clusters.indexOf(cluster) % CLUSTER_PALETTE.length] + 'cc',
      pointRadius: 6,
      pointHoverRadius: 9,
    };
  });
}

function buildPieDataset(clusters, colorMap) {
  return {
    labels: clusters.map(cluster => cluster.label),
    datasets: [{
      data: clusters.map(cluster => cluster.size || (cluster.repos || []).length || 0),
      backgroundColor: clusters.map(cluster => colorMap[cluster.id] + 'cc'),
      borderColor: clusters.map(cluster => colorMap[cluster.id]),
      borderWidth: 1,
      hoverOffset: 8,
    }],
  };
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

  const clusters = clusterData.clusters;
  const scatter = clusterData.scatter || [];

  const colorMap = {};
  clusters.forEach((cluster, index) => {
    colorMap[cluster.id] = CLUSTER_PALETTE[index % CLUSTER_PALETTE.length];
  });

  renderClusterChart(clusters, scatter, clusterChartMode, colorMap);

  listEl.innerHTML = clusters.map(cluster => {
    const color = colorMap[cluster.id];
    const repoLinks = (cluster.repos || []).slice(0, 6).map(repo => {
      const name = repo.split('/')[1] || repo;
      return `<a class="cluster-repo-pill" href="https://github.com/${escHtml(repo)}" target="_blank" rel="noopener">${escHtml(name)}</a>`;
    }).join('');
    const moreCount = (cluster.repos || []).length - 6;
    const more = moreCount > 0
      ? `<span class="cluster-repo-pill" style="color:var(--text-muted)">+${moreCount} more</span>`
      : '';
    return `
      <div class="cluster-item" style="--cl-color:${color}">
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
}

function renderClusterChart(clusters, scatter, mode, colorMap) {
  const ctx = document.getElementById('cluster-chart').getContext('2d');
  const titleEl = document.getElementById('cluster-chart-title');
  if (clusterChart) clusterChart.destroy();

  if (titleEl) {
    titleEl.firstChild.textContent = mode === 'pie' ? 'Cluster Share' : 'Semantic Map';
  }

  const datasets = buildScatterDatasets(clusters, scatter);
  const pieData = buildPieDataset(clusters, colorMap);

  clusterChart = new Chart(ctx, {
    type: mode === 'pie' ? 'pie' : 'scatter',
    data: mode === 'pie' ? pieData : { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 600 },
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
              return `${name} (${ctx.dataset.label})`;
            },
          },
        },
      },
      scales: mode === 'pie' ? {} : {
        x: { ticks: { display: false }, grid: { color: '#21262d' } },
        y: { ticks: { display: false }, grid: { color: '#21262d' } },
      },
      onClick(event, elements) {
        if (mode === 'pie') return;
        if (!elements.length) return;
        const element = elements[0];
        const point = datasets[element.datasetIndex].data[element.index];
        if (point.repo) window.open(`https://github.com/${point.repo}`, '_blank');
      },
    },
  });
}

document.getElementById('btn-scatter').addEventListener('click', () => {
  if (clusterChartMode === 'scatter' || !lastClusterData) return;
  clusterChartMode = 'scatter';
  document.getElementById('btn-scatter').classList.add('active');
  document.getElementById('btn-pie').classList.remove('active');
  const clusters = lastClusterData.clusters;
  const scatter = lastClusterData.scatter || [];
  const colorMap = {};
  clusters.forEach((cluster, index) => {
    colorMap[cluster.id] = CLUSTER_PALETTE[index % CLUSTER_PALETTE.length];
  });
  renderClusterChart(clusters, scatter, 'scatter', colorMap);
});

document.getElementById('btn-pie').addEventListener('click', () => {
  if (clusterChartMode === 'pie' || !lastClusterData) return;
  clusterChartMode = 'pie';
  document.getElementById('btn-pie').classList.add('active');
  document.getElementById('btn-scatter').classList.remove('active');
  const clusters = lastClusterData.clusters;
  const scatter = lastClusterData.scatter || [];
  const colorMap = {};
  clusters.forEach((cluster, index) => {
    colorMap[cluster.id] = CLUSTER_PALETTE[index % CLUSTER_PALETTE.length];
  });
  renderClusterChart(clusters, scatter, 'pie', colorMap);
});

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

  if ((data.history || []).length > 1) renderTrendChart(data.history);
  renderLangChart(data.history || []);
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
      const dates = await idxRes.json();
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