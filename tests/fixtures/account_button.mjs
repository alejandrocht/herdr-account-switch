// Exercise the real native mod's action callback without drawing a window.
import vm from 'node:vm';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';

const config = JSON.parse(process.env.HERDR_TEST_MOD_CONFIG);
const launches = [];
const tasks = [];
const exports = {
  View: class {}, div() {}, svg() {}, h_flex() {}, v_flex() {},
  appHome: () => '', readTextFile() {}, openOverlay() {}, closeOverlay() {},
  props: () => ({}), theme: () => ({}), focused: () => ({cwd: process.cwd()}),
  terminals: () => [], spaces: () => [], home: () => process.cwd(), nextCommand() {},
  run(name, args) { if (name === 'tab.new') launches.push({route: 'agent-menu', argv: args.argv}); },
  async exec(command, args) {
    const r = spawnSync(command, args, {env: process.env, encoding: 'utf8'});
    return {code: r.status, stdout: r.stdout, stderr: r.stderr};
  },
  async hc(args) {
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
const cx = {notify() {}, focus_handle() { return {}; }, spawn(fn) { tasks.push(fn(cx)); }};
view.action('enrol', [], cx);
for (const task of tasks) await task;
if (view.error) throw new Error(view.error);
console.log(JSON.stringify(launches));
