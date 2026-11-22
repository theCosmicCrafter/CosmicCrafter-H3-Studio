// Schematic pictures of the character sheet layouts a reference can follow. Dummies only: they show where the
// studies sit on the sheet, not what the character looks like.
export const SHEET_LAYOUT_CHOICES = [
  {id:'human', label:'Two head studies and four whole figures'},
  {id:'creature', label:'One head study and four body views'},
  {id:'grid', label:'Four views of the place'},
  {id:'custom', label:'Write your own layout'},
];

const INK = '#7f899b', FILL = '#c9d1dd', PANEL = '#232a35', PAGE = '#171b23';
const panel = (x, y, w, h) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="1.5" fill="${PANEL}" stroke="${INK}" stroke-width=".8"/>`;
const shape = (d) => `<path d="${d}" fill="${FILL}" fill-opacity=".7" stroke="${INK}" stroke-width=".6" stroke-linejoin="round"/>`;
const oval = (cx, cy, rx, ry) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${FILL}" fill-opacity=".7" stroke="${INK}" stroke-width=".6"/>`;

// A standing figure, front or side, in a column starting at x.
function figure(x, w, side) {
  const c = x + w / 2, top = 9, floor = 82;
  return [
    oval(c, top + 5, 4.2, 4.6),
    side ? shape(`M${c - 3.5} ${top + 11} h7 l1 24 l-2 8 l1 ${floor - top - 43} h-3 l-.5 -${floor - top - 40} l-.5 ${floor - top - 40} h-3 l1 -${floor - top - 43} l-2 -8 z`)
      : shape(`M${c - 7} ${top + 11} h14 l2 20 l-3 2 l-1 ${floor - top - 33} h-4 l-1 -${floor - top - 44} l-1 ${floor - top - 44} h-4 l-1 -${floor - top - 33} l-3 -2 z`),
  ].join('');
}

function human() {
  const columns = [0, 1, 2, 3].map(i => 56 + i * 25.5);
  return [
    panel(4, 4, 47, 39), panel(4, 47, 47, 39),
    oval(27.5, 22, 10, 12), shape('M23 33 h9 v7 h-9 z'),
    oval(26, 65, 10, 12), shape('M36 64 l4 3 l-4 2 z'), shape('M21 76 h9 v7 h-9 z'),
    ...columns.map((x, i) => panel(x, 4, 24, 82) + figure(x, 24, i === 1 || i === 3)),
  ].join('');
}

function creature() {
  const cells = [[56, 4], [108, 4], [56, 47], [108, 47]];
  const side = (x, y, flip) => {
    const f = flip ? -1 : 1, o = flip ? x + 48 : x;
    return shape(`M${o + f * 3} ${y + 14} h${f * 14} l${f * 14} -3 l${f * 8} 6 v${8} h${-f * 3} v9 h${-f * 3} v-8 h${-f * 22} v8 h${-f * 3} v-8 h${-f * 3} z`);
  };
  return [
    panel(4, 4, 47, 82),
    shape('M12 34 l-3 -12 l7 5 l5 -9 l7 9 l6 -9 l-1 14 l6 4 v16 l-8 12 h-16 l-8 -10 z'), oval(27, 58, 7, 4),
    ...cells.map(([x, y]) => panel(x, y, 48, 39)),
    side(56, 8, false), side(108, 8, true),
    oval(80, 66, 6, 14), shape('M74 78 h3 v6 h-3 z M83 78 h3 v6 h-3 z'),
    oval(132, 66, 17, 7), shape('M146 62 h4 v-2 M146 70 h4 v2 M118 62 h-3 M118 70 h-3'),
  ].join('');
}

// A place seen four ways in a 2 x 2: wide from the front, the reverse view, low at ground level, and from above.
function grid() {
  const pillar = (x, top, bottom, w = 3) => `<rect x="${x}" y="${top}" width="${w}" height="${bottom - top}" fill="${FILL}" fill-opacity=".7" stroke="${INK}" stroke-width=".5"/>`;
  const slab = (x, y, w) => `<rect x="${x}" y="${y}" width="${w}" height="3" fill="${FILL}" fill-opacity=".7" stroke="${INK}" stroke-width=".5"/>`;
  const ground = (y, x, w, bottom) => `<rect x="${x}" y="${y}" width="${w}" height="${bottom - y}" fill="${INK}" fill-opacity=".35"/>`;
  const cells = [[4, 4], [82, 4], [4, 47], [82, 47]];
  return [
    ...cells.map(([x, y]) => panel(x, y, 74, 39)),
    // 1: wide establishing view
    ground(28, 5, 72, 42), slab(12, 12, 58), pillar(18, 15, 31), pillar(36, 15, 31), pillar(54, 15, 31), pillar(66, 15, 31),
    // 2: the reverse view, the same place from the other side
    ground(30, 83, 72, 42), slab(90, 15, 52), pillar(96, 18, 33), pillar(112, 18, 33), pillar(130, 18, 33), pillar(144, 18, 33),
    // 3: low, at ground level
    ground(70, 5, 72, 85), slab(10, 52, 62), pillar(20, 54, 82, 6), pillar(52, 54, 82, 6),
    // 4: from above
    ground(47, 83, 72, 86), `<rect x="92" y="55" width="54" height="22" fill="${FILL}" fill-opacity=".45" stroke="${INK}" stroke-width=".6"/>`,
    ...[98, 112, 126, 140].map(x => `<rect x="${x}" y="52" width="3" height="28" fill="${FILL}" fill-opacity=".7"/>`),
  ].join('');
}

function custom() {
  return [
    `<rect x="14" y="10" width="132" height="70" rx="3" fill="${PANEL}" stroke="${INK}" stroke-width=".9" stroke-dasharray="3 2.5"/>`,
    ...[28, 40, 52, 64].map((y, i) => `<rect x="26" y="${y}" width="${[108, 88, 100, 64][i]}" height="3.5" rx="1.75" fill="${FILL}" fill-opacity=".5"/>`),
  ].join('');
}

export function sheetLayoutPicture(id) {
  const body = {human, creature, grid, custom}[id]?.() ?? '';
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><rect width="160" height="90" fill="${PAGE}"/>${body}</svg>`;
  return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}
