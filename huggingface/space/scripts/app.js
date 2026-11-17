const frame = document.querySelector('#chart-frame');
const description = document.querySelector('#chart-description');
const preview = document.querySelector('#preview-link');
const tabs = [...document.querySelectorAll('[role="tab"]')];

function selectTab(tab) {
  const chart = tab.dataset.chart;
  tabs.forEach((item) => {
    item.setAttribute('aria-selected', String(item === tab));
    item.tabIndex = item === tab ? 0 : -1;
  });
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  tab.scrollIntoView({ block: 'nearest', inline: 'center', behavior: reducedMotion ? 'auto' : 'smooth' });
  document.querySelector('#chart-panel').setAttribute('aria-labelledby', tab.id);
  frame.src = `charts/${chart}.html`;
  frame.title = `${tab.textContent.trim()} interactive chart`;
  description.textContent = tab.dataset.description;
  preview.href = `previews/${chart}.png`;
  preview.textContent = `${tab.textContent.trim()} static PNG preview`;
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => selectTab(tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    let target = index;
    if (event.key === 'ArrowLeft') target = (index - 1 + tabs.length) % tabs.length;
    if (event.key === 'ArrowRight') target = (index + 1) % tabs.length;
    if (event.key === 'Home') target = 0;
    if (event.key === 'End') target = tabs.length - 1;
    tabs[target].focus(); selectTab(tabs[target]);
  });
});

const railLinks = [...document.querySelectorAll('.story-rail a')];
const chapters = [...document.querySelectorAll('[data-chapter]')];
const observer = new IntersectionObserver((entries) => {
  const active = entries.filter((entry) => entry.isIntersecting)
    .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
  if (!active) return;
  railLinks.forEach((link) => link.setAttribute('aria-current',
    String(link.hash === `#${active.target.id}`)));
}, { rootMargin: '-25% 0px -55%', threshold: [0, .25, .5] });
chapters.forEach((chapter) => observer.observe(chapter));
