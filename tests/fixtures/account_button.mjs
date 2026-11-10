// Exercise the real native mod's action callback without drawing a window.
import vm from 'node:vm';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';

const config = JSON.parse(process.env.HERDR_TEST_MOD_CONFIG);
const launches = [];
const tasks = [];
let canAdopt = false, adopted = false, focused = false;
const exports = {
  View: class {}, div() {}, svg() {}, h_flex() {}, v_flex() {},
  appHome: () => '', readTextFile() {}, openOverlay() {}, closeOverlay() {},
  props: () => ({}), theme: () => ({}), focused: () => ({cwd: process.cwd()}),
  terminals: () => [], spaces: () => [], home: () => process.cwd(), nextCommand() {},
  panes: () => adopted ? [{pane: 'p-fixture', terminal: 't-fixture'}] : [],
  run(name, args) {
    if (name === 'terminal.keep') throw new Error('Terminal is not registered in the app snapshot yet');
    if (name === 'pane.focus') {
      if (!adopted) throw new Error('Pane does not exist until asynchronous adoption finishes');
      focused = true;
    }
    if (name === 'tab.new') launches.push({route: 'agent-menu', argv: args.argv});
  },
  async exec(command, args) {
    const r = spawnSync(command, args, {env: process.env, encoding: 'utf8'});
    return {code: r.status, stdout: r.stdout, stderr: r.stderr};
  },
  async hc(args) {
    canAdopt = args.some(v => v.startsWith('herdr.space=')) && args.some(v => v.startsWith('herdr.tab='));
    launches.push({route: 'core', argv: args.slice(args.indexOf('--') + 1)});
    return {code: 0, stdout: JSON.stringify({address: 't-fixture'}), stderr: ''};
  },
};
const context = vm.createContext({console});
const source = new vm.SourceTextModule(fs.readFileSync(process.argv[2], 'utf8'), {context});
await source.link(async (specifier) => {
  const names = specifier === 'gpui-kit' ? ['View', 'div', 'svg']
    : specifier === 'gpui-base' ? ['h_flex', 'v_flex']
    : Object.keys(exports).filter(k => !['View','div','svg','h_flex','v_flex'].includes(k));
  return new vm.SyntheticModule(names, function () {
    for (const name of names) this.setExport(name, exports[name]);
  }, {context});
});
await source.evaluate();
const view = new source.namespace.default();
view.config = config;
view.buttons = {};
const cx = {notify() {}, focus_handle() { return {}; }, async sleep() { adopted = canAdopt; }, spawn(fn) { tasks.push(fn(cx)); }};
view.action('enrol', [], cx);
for (const task of tasks) await task;
if (view.error) throw new Error(view.error);
if (!focused) throw new Error('New account pane was not focused');
console.log(JSON.stringify(launches));
