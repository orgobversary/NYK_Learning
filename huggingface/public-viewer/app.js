const state = { games: [], seasons: [], summary: [], opponents: [], series: [], predictions: [], manifest: null, view: 'pulse' };
const $ = (selector) => document.querySelector(selector);
const formatSigned = (value) => `${value > 0 ? '+' : ''}${d3.format('.1f')(value)}`;
const TEXT_FIELDS = new Set([
  'game_key', 'season', 'season_type', 'game_date', 'opponent',
  'opponent_abbrev', 'venue_side', 'result', 'round',
]);

function typedRow(row) {
  const typed = d3.autoType({ ...row });
  for (const field of TEXT_FIELDS) if (field in row) typed[field] = row[field];
  return typed;
}

async function optionalCsv(path) {
  try { return await d3.csv(path, typedRow); } catch (_) { return []; }
}

async function load() {
  if (!window.d3) throw new Error('D3 could not be loaded.');
  const [manifest, games, summary, opponents, series, predictions] = await Promise.all([
    fetch('data/release-manifest.json').then((response) => {
      if (!response.ok) throw new Error('No reviewed public release is bound to this viewer.');
      return response.json();
    }), d3.csv('data/games.csv', typedRow), d3.csv('data/season_summary.csv', typedRow),
    d3.csv('data/opponent_summary.csv', typedRow), optionalCsv('data/playoff_series.csv'),
    optionalCsv('data/model_predictions.csv'),
  ]);
  Object.assign(state, { manifest, games, summary, opponents, series, predictions });
  state.seasons = [...new Set(games.map((row) => row.season))].sort();
  const season = $('#season-select');
  season.replaceChildren(...state.seasons.map((value) => new Option(value, value)));
  season.value = state.seasons.at(-1); season.disabled = false; $('#phase-select').disabled = false;
  $('#release-status').textContent = `${manifest.provider} · ${manifest.seasons[0]}–${manifest.seasons.at(-1)} · ${manifest.files ? Object.keys(manifest.files).length : 0} verified files`;
  $('#release-status').classList.add('ready');
  render();
}

function selectedGames() {
  return state.games.filter((row) => row.season === $('#season-select').value && row.season_type === $('#phase-select').value);
}

function svgFrame(label) {
  const width = 1100, height = 430, margin = { top: 25, right: 30, bottom: 55, left: 60 };
  const svg = d3.select('#chart').append('svg').attr('viewBox', `0 0 ${width} ${height}`).attr('aria-label', label);
  return { svg, width, height, margin, innerWidth: width - margin.left - margin.right, innerHeight: height - margin.top - margin.bottom };
}

function pulse(games) {
  const f = svgFrame('Game-by-game Knicks and opponent scores with cumulative point margin');
  let cumulative = 0; const values = games.map((row) => ({ ...row, cumulative: cumulative += row.point_margin }));
  const x = d3.scaleLinear().domain([1, d3.max(values, (d) => d.game_number)]).range([f.margin.left, f.width - f.margin.right]);
  const y = d3.scaleLinear().domain(d3.extent(values.flatMap((d) => [d.nyk_score, d.opponent_score]))).nice().range([f.height - f.margin.bottom, f.margin.top]);
  f.svg.append('g').attr('transform', `translate(0,${f.height - f.margin.bottom})`).call(
    d3.axisBottom(x).ticks(Math.min(10, values.length)).tickFormat(d3.format('d')),
  );
  f.svg.append('g').attr('transform', `translate(${f.margin.left},0)`).call(d3.axisLeft(y));
  const line = (field) => d3.line().x((d) => x(d.game_number)).y((d) => y(d[field]))(values);
  f.svg.append('path').attr('d', line('nyk_score')).attr('fill', 'none').attr('stroke', '#39a7ff').attr('stroke-width', 3);
  f.svg.append('path').attr('d', line('opponent_score')).attr('fill', 'none').attr('stroke', '#ff7a18').attr('stroke-width', 2).attr('opacity', .75);
  f.svg.selectAll('circle').data(values).join('circle').attr('cx', (d) => x(d.game_number)).attr('cy', (d) => y(d.nyk_score)).attr('r', 4).attr('fill', (d) => d.result === 'W' ? '#69f0ff' : '#ff55c8').append('title').text((d) => `${d.game_date} · ${d.venue_side === 'home' ? 'vs.' : '@'} ${d.opponent_abbrev} · NYK ${d.nyk_score}–${d.opponent_score} · ${d.result} ${formatSigned(d.point_margin)}`);
  $('#chart-note').textContent = `Blue: NYK score · Orange: opponent score · Cyan dots: wins · Pink dots: losses · Final cumulative margin ${formatSigned(values.at(-1).cumulative)}.`;
}

function opponents(games) {
  const grouped = d3.rollups(games, (values) => ({ games: values.length, wins: d3.sum(values, (d) => d.result === 'W'), margin: d3.sum(values, (d) => d.point_margin) }), (d) => d.opponent_abbrev).map(([opponent, values]) => ({ opponent, ...values })).sort((a, b) => d3.descending(a.margin, b.margin));
  const f = svgFrame('Total point margin by opponent');
  const x = d3.scaleBand().domain(grouped.map((d) => d.opponent)).range([f.margin.left, f.width - f.margin.right]).padding(.22);
  const extent = d3.max(grouped, (d) => Math.abs(d.margin)) || 1;
  const y = d3.scaleLinear().domain([-extent, extent]).nice().range([f.height - f.margin.bottom, f.margin.top]);
  f.svg.append('g').attr('transform', `translate(0,${y(0)})`).call(d3.axisBottom(x));
  f.svg.append('g').attr('transform', `translate(${f.margin.left},0)`).call(d3.axisLeft(y));
  f.svg.selectAll('rect').data(grouped).join('rect').attr('x', (d) => x(d.opponent)).attr('width', x.bandwidth()).attr('y', (d) => y(Math.max(0, d.margin))).attr('height', (d) => Math.abs(y(d.margin) - y(0))).attr('rx', 4).attr('fill', (d) => d.margin >= 0 ? '#39a7ff' : '#ff7a18').append('title').text((d) => `${d.opponent}: ${d.wins}–${d.games - d.wins}, ${formatSigned(d.margin)} total margin`);
  $('#chart-note').textContent = 'Bars aggregate only the selected season and phase. Height is total point differential, not average margin.';
}

function flow(games) {
  const f = svgFrame('Flow from venue to wins and losses');
  const counts = d3.rollup(games, (values) => values.length, (d) => d.venue_side, (d) => d.result);
  const nodes = [{ key: 'home', x: 120, y: 100 }, { key: 'away', x: 120, y: 300 }, { key: 'W', x: 900, y: 100 }, { key: 'L', x: 900, y: 300 }];
  const node = f.svg.selectAll('.node').data(nodes).join('g').attr('class', 'node').attr('transform', (d) => `translate(${d.x},${d.y})`);
  node.append('rect').attr('width', 120).attr('height', 64).attr('rx', 12).attr('fill', '#111c2e').attr('stroke', '#2b3a56');
  node.append('text').attr('x', 60).attr('y', 38).attr('text-anchor', 'middle').attr('fill', '#f7f8ff').text((d) => d.key === 'W' ? 'Wins' : d.key === 'L' ? 'Losses' : d.key[0].toUpperCase() + d.key.slice(1));
  for (const venue of ['home', 'away']) for (const result of ['W', 'L']) {
    const count = counts.get(venue)?.get(result) || 0; const y1 = venue === 'home' ? 132 : 332; const y2 = result === 'W' ? 132 : 332;
    f.svg.insert('path', ':first-child').attr('d', `M240,${y1} C500,${y1} 640,${y2} 900,${y2}`).attr('fill', 'none').attr('stroke', result === 'W' ? '#39a7ff' : '#ff55c8').attr('stroke-width', Math.max(2, count * 2)).attr('opacity', .55).append('title').text(`${venue} ${result}: ${count} games`);
  }
  $('#chart-note').textContent = 'This is a venue-to-result flow. It is not a player passing network.';
}

function playoffs(games) {
  if ($('#phase-select').value !== 'Playoffs') { empty('Choose Playoffs to inspect a postseason path.'); return; }
  const f = svgFrame('Chronological postseason scores and cumulative point margin');
  let cumulative = 0; const values = games.map((row) => ({ ...row, cumulative: cumulative += row.point_margin }));
  const x = d3.scalePoint().domain(values.map((d) => d.game_number)).range([f.margin.left, f.width - f.margin.right]).padding(.4);
  const y = d3.scaleLinear().domain(d3.extent([0, ...values.map((d) => d.cumulative)])).nice().range([f.height - f.margin.bottom, f.margin.top]);
  f.svg.append('line').attr('x1', f.margin.left).attr('x2', f.width - f.margin.right).attr('y1', y(0)).attr('y2', y(0)).attr('stroke', '#48526a');
  f.svg.append('path').datum(values).attr('d', d3.line().x((d) => x(d.game_number)).y((d) => y(d.cumulative))).attr('fill', 'none').attr('stroke', '#ff7a18').attr('stroke-width', 4);
  f.svg.selectAll('circle').data(values).join('circle').attr('cx', (d) => x(d.game_number)).attr('cy', (d) => y(d.cumulative)).attr('r', 7).attr('fill', (d) => d.result === 'W' ? '#69f0ff' : '#ff55c8').append('title').text((d) => `Game ${d.game_number} · ${d.venue_side === 'home' ? 'vs.' : '@'} ${d.opponent_abbrev} · ${d.result} · run margin ${formatSigned(d.cumulative)}`);
  $('#chart-note').textContent = `${values.length} postseason games · ${d3.sum(values, (d) => d.result === 'W')} wins · final cumulative margin ${formatSigned(values.at(-1).cumulative)}.`;
}

function models() {
  const values = state.predictions.filter((row) => row.season === $('#season-select').value);
  if (!values.length) { empty('No out-of-sample model predictions are available for this season. Earlier seasons are training history.'); return; }
  const f = svgFrame('Out-of-sample pregame win probabilities and actual results');
  const x = d3.scaleLinear().domain([1, values.length]).range([f.margin.left, f.width - f.margin.right]);
  const y = d3.scaleLinear().domain([0, 1]).range([f.height - f.margin.bottom, f.margin.top]);
  f.svg.append('g').attr('transform', `translate(0,${f.height - f.margin.bottom})`).call(
    d3.axisBottom(x).ticks(Math.min(10, values.length)).tickFormat(d3.format('d')),
  );
  f.svg.append('g').attr('transform', `translate(${f.margin.left},0)`).call(d3.axisLeft(y).tickFormat(d3.format('.0%')));
  f.svg.append('path').datum(values).attr('d', d3.line().x((_, i) => x(i + 1)).y((d) => y(d.predicted_win_probability))).attr('fill', 'none').attr('stroke', '#39a7ff').attr('stroke-width', 3);
  f.svg.selectAll('circle').data(values).join('circle').attr('cx', (_, i) => x(i + 1)).attr('cy', (d) => y(d.actual_win)).attr('r', 4).attr('fill', (d) => d.actual_win ? '#69f0ff' : '#ff55c8');
  $('#chart-note').textContent = 'Pregame-only expanding-window backtest. Blue line: predicted win probability. Dots: actual result. Not causal and not betting advice.';
}

function empty(message) { $('#chart').innerHTML = `<div class="empty"><p>${message}</p></div>`; $('#chart').setAttribute('aria-label', message); $('#chart-note').textContent = ''; }

function render() {
  const games = selectedGames(); $('#chart').replaceChildren();
  const summary = state.summary.find((row) => row.season === $('#season-select').value && row.season_type === $('#phase-select').value);
  $('#metric-games').textContent = summary?.games ?? 0; $('#metric-record').textContent = summary ? `${summary.wins}–${summary.losses}` : '—';
  $('#metric-margin').textContent = summary ? formatSigned(summary.mean_margin) : '—'; $('#metric-release').textContent = state.manifest?.source_manifest_sha256?.slice(0, 8) || '—';
  if (!games.length && state.view !== 'models') { empty('No completed games are available for this season and phase.'); return; }
  const details = {
    pulse: ['Season pulse', 'Momentum leaves a trace.', 'Game scores and cumulative point margin, ordered through the selected season.', pulse],
    opponents: ['Opponent gravity', 'Every matchup bends the shape.', 'Compare total point differential and results across opponents.', opponents],
    flow: ['Result flow', 'Venue changes the route.', 'Follow selected games from home or away into wins and losses.', flow],
    playoffs: ['Playoff path', 'Every series leaves a scar.', 'Trace postseason results and cumulative margin in chronological order.', playoffs],
    models: ['Model lab', 'Prediction, with the lights on.', 'Inspect out-of-sample probabilities against actual results.', models],
  }[state.view];
  $('#visual-kicker').textContent = details[0]; $('#visual-title').textContent = details[1]; $('#visual-description').textContent = details[2];
  details[3](games); $('#chart').setAttribute('aria-label', `${details[0]} for ${$('#season-select').value} ${$('#phase-select').value}`);
}

$('#season-select').addEventListener('change', render); $('#phase-select').addEventListener('change', render);
document.querySelectorAll('[role="tab"]').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('[role="tab"]').forEach((item) => item.setAttribute('aria-selected', String(item === button)));
  state.view = button.dataset.view; render();
}));
load().catch((error) => { $('#release-status').textContent = error.message; empty('A validated public release has not been staged.'); });
