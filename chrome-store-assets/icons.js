// Packaged vector icons: no remote JavaScript, fonts, or network dependency.
export function icons() {
  const paths = {
    'sliders-horizontal': ['M4 6h16M4 12h16M4 18h16', 'M8 3v6M16 9v6M10 15v6'],
    search: ['M21 21l-5-5', 'M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0'],
    plus: ['M12 4v16M4 12h16'], x: ['M5 5l14 14M19 5L5 19'],
    'rotate-cw': ['M20 9a8 8 0 1 0 0 7M20 3v6h-6'],
    'bell-ring': ['M6 9a6 6 0 0 1 12 0v7l2 2H4l2-2ZM10 21h4M2 7l2-3M22 7l-2-3'],
    crown: ['M3 5l5 5 4-7 4 7 5-5-2 14H5ZM5 22h14']
  };
  document.querySelectorAll('[data-lucide]').forEach(node => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    for (const [k, v] of Object.entries({ viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '1.8', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', class: node.className })) svg.setAttribute(k, v);
    for (const d of paths[node.dataset.lucide] || []) {
      const path = document.createElementNS(svg.namespaceURI, 'path'); path.setAttribute('d', d); svg.append(path);
    }
    node.replaceWith(svg);
  });
}
