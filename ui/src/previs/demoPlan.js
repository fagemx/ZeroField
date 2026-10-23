import { defaultPlan } from './plan.js';

// A reusable rehearsal, authored with the same skills, acting keys and contacts as any shot.
// The contact is the wrist target; the scene places the visible pad under the rendered palm.
export const MOTION_DEMO_SCENE = {
  from: [0, -2.4], stop: [0, -0.25], listener: [1.5, 0.35], contact: [0.28, 1.15, 0.12],
  camera: [3.4, 2.45, 5.8], aim: [0.35, 1.0, -0.65],
};

export function createMotionDemoPlan() {
  const s = MOTION_DEMO_SCENE, yaw = Math.atan2(s.listener[0] - s.stop[0], s.listener[1] - s.stop[1]);
  const listenerTurn = Math.atan2(s.stop[0] - s.listener[0], s.stop[1] - s.listener[1]) * 180 / Math.PI;
  return {
    ...defaultPlan(), set: 'empty', presentation: 'rehearsal', demo: 'motion-rehearsal-v1', action: 'stand', move: 'static',
    seconds: 10, lens: 35, mark: [...s.from], facing: 'console', beacon: false,
    figure: { build: 'man', outfit: 'jacket', hair: 'short', tone: 0 },
    keys: [[0, [...s.camera], [...s.aim]], [96, [...s.camera], [...s.aim]]],
    cast: [{ figure: { build: 'woman', outfit: 'jacket', hair: 'bun', tone: 1 }, mark: [...s.listener], turn: listenerTurn,
      acts: [{ at: 0, body: 'stand' }, { at: 1, body: 'stand' }] }],
    props: [
      { id: 'touch-base', shape: 'cylinder', radius: 0.19, height: 0.035, position: [0.25, 0.0175, 0.245], color: '#6c7985' },
      { id: 'touch-stand', shape: 'cylinder', radius: 0.055, height: 0.96, position: [0.25, 0.48, 0.245], color: '#778797' },
      { id: 'touch-pad', shape: 'cylinder', radius: 0.11, height: 0.115, position: [0.25, 1.0175, 0.245], color: '#d4aa65', contact: true },
    ],
    use: [
      { skill: 'walkTo', f0: 0, frames: 96, args: { from: [...s.from], to: [...s.stop], steps: 6 } },
      { skill: 'standIdle', f0: 96, frames: 144, args: { at: [...s.stop], plant: true } },
      { skill: 'reachGrip', f0: 156, args: { anchor: [...s.contact], side: 'R', reach: 48, hold: 36, release: 0 } },
    ],
    acts: [{ at: 0, headYaw: 0 }, { at: 0.5, headYaw: 0 }, { at: 0.65, headYaw: yaw }, { at: 1, headYaw: yaw }],
    fix: { ground: true, slide: true, penetration: true },
  };
}
