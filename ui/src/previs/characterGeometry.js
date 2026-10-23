// Original procedural character surfaces. A smooth implicit garment is triangulated once in its bind pose;
// its shared vertices then follow the same semantic rig as the pose/skeleton passes. No external model assets.
import * as THREE from 'three';

const clamp = x => Math.max(0, Math.min(1, x));
const smooth = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const mix = (a, b, t) => a + (b - a) * t;
const blend = (a, b, k = 0.035) => { const h = clamp(0.5 + 0.5 * (b - a) / k); return mix(b, a, h) - k * h * (1 - h); };
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const sub = (a, b) => a.map((v, i) => v - b[i]);
const len = a => Math.hypot(...a);
function segment(p, a, b) {
  const ab = sub(b, a), t = clamp(dot(sub(p, a), ab) / dot(ab, ab));
  return { t, distance: len(p.map((v, i) => v - mix(a[i], b[i], t))) };
}
const tube = (p, a, b, ra, rb) => { const s = segment(p, a, b); return s.distance - mix(ra, rb, s.t); };
const egg = (p, c, r) => { const q = p.map((v, i) => (v - c[i]) / r[i]); return (len(q) - 1) * Math.min(...r); };

// Marching tetrahedra with an edge cache: adjacent cells really share vertices, so bent sleeves and trouser knees
// remain one surface. Gradient normals retain the soft sculpted silhouette without facet or ball-joint seams.
export function implicitGeometry(field, min, max, step = 0.022) {
  const count = min.map((v, i) => Math.ceil((max[i] - v) / step) + 1), [nx, ny, nz] = count;
  const point = id => { const x = id % nx, y = Math.floor(id / nx) % ny, z = Math.floor(id / (nx * ny)); return [min[0] + x * step, min[1] + y * step, min[2] + z * step]; };
  const values = new Float32Array(nx * ny * nz);
  for (let i = 0; i < values.length; i++) values[i] = field(point(i));
  const positions = [], normals = [], indices = [], cache = new Map();
  const gradient = p => { const e = 0.001, d = [0, 1, 2].map(i => { const a = [...p], b = [...p]; a[i] += e; b[i] -= e; return field(a) - field(b); }); const l = len(d) || 1; return d.map(v => v / l); };
  const vertex = (a, b) => {
    const key = a < b ? `${a}:${b}` : `${b}:${a}`;
    if (cache.has(key)) return cache.get(key);
    const t = values[a] / (values[a] - values[b]), pa = point(a), pb = point(b), p = pa.map((v, i) => mix(v, pb[i], t));
    const id = positions.length / 3; positions.push(...p); normals.push(...gradient(p)); cache.set(key, id); return id;
  };
  const tetrahedra = [[0, 5, 1, 6], [0, 1, 2, 6], [0, 2, 3, 6], [0, 3, 7, 6], [0, 7, 4, 6], [0, 4, 5, 6]];
  const edges = [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]];
  const V = id => new THREE.Vector3().fromArray(positions, id * 3);
  for (let z = 0; z < nz - 1; z++) for (let y = 0; y < ny - 1; y++) for (let x = 0; x < nx - 1; x++) {
    const a = x + nx * (y + ny * z), corners = [a, a + 1, a + nx + 1, a + nx, a + nx * ny, a + nx * ny + 1, a + nx * ny + nx + 1, a + nx * ny + nx];
    if (corners.every(i => values[i] >= 0) || corners.every(i => values[i] < 0)) continue;
    for (const t of tetrahedra) {
      const ids = t.map(i => corners[i]), polygon = edges.filter(([i, j]) => (values[ids[i]] < 0) !== (values[ids[j]] < 0)).map(([i, j]) => vertex(ids[i], ids[j]));
      if (polygon.length < 3) continue;
      const center = polygon.reduce((s, id) => s.add(V(id)), new THREE.Vector3()).multiplyScalar(1 / polygon.length);
      const normal = new THREE.Vector3(...gradient(center.toArray())), u = V(polygon[0]).sub(center).normalize(), v = new THREE.Vector3().crossVectors(normal, u);
      polygon.sort((a0, b0) => { const a1 = V(a0).sub(center), b1 = V(b0).sub(center); return Math.atan2(a1.dot(v), a1.dot(u)) - Math.atan2(b1.dot(v), b1.dot(u)); });
      for (let i = 1; i < polygon.length - 1; i++) indices.push(polygon[0], polygon[i], polygon[i + 1]);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3)); g.setAttribute('normal', new THREE.Float32BufferAttribute(normals, 3)); g.setIndex(indices);
  return g;
}

function skin(geometry, influences, boneIndex) {
  const p = geometry.attributes.position, ids = [], weights = [];
  for (let i = 0; i < p.count; i++) {
    const entries = Object.entries(influences([p.getX(i), p.getY(i), p.getZ(i)])).filter(([, w]) => w > 1e-6).sort((a, b) => b[1] - a[1]).slice(0, 4);
    const sum = entries.reduce((n, [, w]) => n + w, 0);
    for (let j = 0; j < 4; j++) { ids.push(j < entries.length ? boneIndex[entries[j][0]] : 0); weights.push(j < entries.length ? entries[j][1] / sum : 0); }
  }
  geometry.setAttribute('skinIndex', new THREE.Uint16BufferAttribute(ids, 4)); geometry.setAttribute('skinWeight', new THREE.Float32BufferAttribute(weights, 4));
  return geometry;
}
const merge = (a, b, t) => {
  const r = {}; for (const [k, w] of Object.entries(a)) r[k] = w * (1 - t);
  for (const [k, w] of Object.entries(b)) r[k] = (r[k] || 0) + w * t; return r;
};

const garmentCache = new Map();
export function garmentGeometries(points, boneIndex, figure = {}) {
  const radius = figure.build === 'woman' ? 0.96 : figure.build === 'child' ? 0.92 : 1;
  // Figure geometry is identical between shots; cache the bind surface, never a live mesh or skeleton. Every caller
  // owns its clone, so closing a shot cannot dispose another character's GPU buffers.
  const cacheKey = JSON.stringify([radius, points, boneIndex]);
  const cached = garmentCache.get(cacheKey);
  if (cached) return Object.fromEntries(Object.entries(cached).map(([name, g]) => [name, g.clone()]));
  const arm = side => [points['shoulder' + side], points['elbow' + side], points['wrist' + side]];
  const arms = ['L', 'R'].map(arm);
  const torso = p => {
    const y = p[1], upper = smooth(1.12, 1.41, y), lower = smooth(0.94, 1.12, y);
    const rx = (y < 1.12 ? mix(0.163, 0.145, lower) : mix(0.145, 0.194, upper)) * radius;
    const rz = y < 1.12 ? mix(0.104, 0.094, lower) : mix(0.094, 0.114, upper);
    const radial = (Math.hypot(p[0] / rx, (p[2] - 0.005) / rz) - 1) * rz;
    // Rounded hem and shoulders, tapering to a crew neck instead of a separate chest and belly.
    const shoulder = 1.565 - 0.245 * Math.abs(p[0]) - 0.10 * Math.abs(p[2] - 0.005);
    const cap = Math.max(0.918 - y, y - shoulder);
    const outside = Math.hypot(Math.max(radial, 0), Math.max(cap, 0));
    return outside + Math.min(Math.max(radial, cap), 0) - 0.012;
  };
  const shirtField = p => {
    let d = torso(p);
    for (const [s, e, w] of arms) {
      let sleeve = blend(tube(p, s, e, 0.060 * radius, 0.049), tube(p, e, w, 0.049, 0.034), 0.025);
      const along = sub(w, e), length = len(along); sleeve = Math.max(sleeve, dot(sub(p, w), along) / length + 0.018);
      d = blend(d, sleeve, 0.046);
    }
    return d;
  };
  const shirtSkin = p => {
    const h = smooth(1.04, 1.30, p[1]), lower = smooth(0.96, 1.12, p[1]);
    const trunk = merge({ pelvis: 1 }, merge({ spine: 1 }, { chest: 1 }, h), lower);
    const side = p[0] < 0 ? 'L' : 'R', [s, e, w] = arm(side), upper = segment(p, s, e), lowerArm = segment(p, e, w);
    const nearElbow = smooth(0.68, 1.25, upper.t + lowerArm.t * (lowerArm.distance < upper.distance ? 1 : 0));
    const limb = merge({ ['shoulder' + side]: 1 }, { ['elbow' + side]: 1 }, nearElbow);
    const onArm = smooth(0.14 * radius, 0.218, Math.abs(p[0])) * (1 - smooth(1.49, 1.57, p[1]));
    return merge(trunk, limb, onArm);
  };
  const leg = side => [points['hip' + side], points['knee' + side], points['ankle' + side]];
  const legs = ['L', 'R'].map(leg);
  const pantsField = p => {
    let d = egg(p, [0, 0.91, 0], [0.159 * radius, 0.116, 0.108]);
    for (const [h, k, a] of legs) {
      let trouser = blend(tube(p, h, k, 0.082 * radius, 0.061), tube(p, k, a, 0.061, 0.044), 0.025);
      trouser = Math.max(trouser, a[1] + 0.005 - p[1]); d = blend(d, trouser, 0.026);
    }
    return d;
  };
  const pantsSkin = p => {
    const side = p[0] < 0 ? 'L' : 'R', [h, k, a] = leg(side), upper = segment(p, h, k), lower = segment(p, k, a);
    const knee = smooth(0.75, 1.28, upper.t + lower.t * (lower.distance < upper.distance ? 1 : 0));
    return merge(merge({ ['hip' + side]: 1 }, { ['knee' + side]: 1 }, knee), { pelvis: 1 }, smooth(0.85, 0.975, p[1]));
  };
  const result = {
    shirt: skin(implicitGeometry(shirtField, [-0.40, 0.78, -0.23], [0.40, 1.58, 0.28]), shirtSkin, boneIndex),
    pants: skin(implicitGeometry(pantsField, [-0.24, 0.025, -0.19], [0.24, 1.04, 0.24]), pantsSkin, boneIndex),
  };
  if (garmentCache.size >= 4) garmentCache.delete(garmentCache.keys().next().value);
  garmentCache.set(cacheKey, result);
  return Object.fromEntries(Object.entries(result).map(([name, g]) => [name, g.clone()]));
}

// Smooth rings for the head and shoes. No UV map is required by these neutral material-only characters.
export function profileGeometry(rings, segments = 28, axis = 'y') {
  const positions = [], indices = [];
  rings.forEach(([at, a, b, center = 0], j) => {
    for (let i = 0; i <= segments; i++) {
      const t = i / segments * Math.PI * 2, x = Math.cos(t) * a, q = Math.sin(t) * b;
      positions.push(...(axis === 'y' ? [x, at, q + center] : [x, Math.max(-0.070, q + center), at]));
      if (j && i) { const n = j * (segments + 1) + i;
        if (axis === 'y') indices.push(n, n - segments - 2, n - 1, n, n - segments - 1, n - segments - 2);
        else indices.push(n, n - 1, n - segments - 2, n, n - segments - 2, n - segments - 1);
      }
    }
  });
  const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3)); g.setIndex(indices); g.computeVertexNormals(); return g;
}
