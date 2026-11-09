import { View, div, svg } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { appHome, readTextFile, exec, openOverlay, closeOverlay, props, theme, run, focused, terminals, spaces, home, nextCommand } from "herdr";

export default class CodexAccounts extends View {
  init(_props, cx) {
    this.state = null;
    this.config = null;
    this.busy = false;
    this.error = null;
    this.handle = cx.focus_handle();
    this.buttons = Object.fromEntries(["connect", "cancel-login", "open-codex", "open-shell"]
      .map(id => [id, cx.focus_handle()]));
    if (props()?.picker) this.handle.focus();
    cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand();
        if (command === "focus") this.handle.focus();
        if (command === "open" && !props()?.picker) this.openPicker();
        if (command === "connect" && !props()?.picker && !this.remote()) this.action("enrol", [], cx);
      }
    });
    cx.spawn(async (cx) => {
      try {
        this.config = JSON.parse(await readTextFile(appHome() + "/mods/codex-accounts/config.json"));
        await this.refresh();
      } catch (_error) {
        this.error = "No se pudo cargar el selector. Revisa su instalación.";
      }
      cx.notify();
    });
    cx.timer.every(3000, (cx) => {
      if (this.busy || !this.config) return;
      cx.spawn(async (cx) => { await this.refresh(); cx.notify(); });
    });
  }

  async call(action, args = []) {
    const c = this.config;
    const result = await exec(c.python, [c.controller, "--home", c.accounts_home, action, ...args]);
    let data;
    try { data = JSON.parse(result.stdout); }
    catch (_error) { throw new Error("El gestor no respondió. Vuelve a intentarlo."); }
    if (result.code !== 0 || data.error) throw new Error(data.error ?? "No se pudo completar la operación.");
    return data;
  }

  async refresh() {
    try { this.state = await this.call("status"); this.error = null; }
    catch (error) { this.error = error.message; }
  }

  action(name, args, cx) {
    if (this.busy || !this.config) return;
    this.busy = true;
    this.error = null;
    cx.notify();
    cx.spawn(async (cx) => {
      try {
        const result = await this.call(name, args);
        if (name === "enrol" && result.command) {
          run("tab.new", { name: "Cuenta de Codex · Iniciar sesión", argv: result.command });
          if (props()?.overlay) closeOverlay(props().overlay);
        }
        await this.refresh();
      } catch (error) { this.error = error.message; }
      this.busy = false;
      cx.notify();
    });
  }

  launch(command) {
    const c = this.config;
    if (!c || !this.state?.active) return;
    run("tab.new", { name: command === "shell" ? "Terminal de Codex" : "Codex · " + this.state.active.label,
      folder: focused()?.cwd ?? home(),
      argv: [c.python, c.controller, "--home", c.accounts_home, command] });
    if (props()?.overlay) closeOverlay(props().overlay);
  }

  openPicker() {
    openOverlay({ mod: "codex-accounts", props: { picker: true }, kind: "popup", width: 410, height: 330 });
  }

  managed() {
    const address = focused()?.terminal;
    if (!address) return null;
    const terminal = terminals().find(t => t.address === address || t.id === address);
    return terminal?.labels?.["herdr.accounts"] === this.config?.accounts_home;
  }

  remote() { return Boolean(spaces().find(s => s.active)?.machine); }

  button(id, text, primary, disabled, action) {
    const t = theme();
    const handle = this.buttons[id];
    return h_flex().id(id).track_focus(handle).tab_index(0).tab_stop(!disabled)
      .h(34).px(12).items_center().justify_center().rounded(8).border_1()
      .border_color(handle.is_focused() ? t.accent : primary ? t.solid : t.raised)
      .bg(primary ? t.solid : t.raised).text_color(primary ? t.solid_foreground : t.foreground)
      .text_size(12.5).font_medium().opacity(disabled ? 0.45 : 1).cursor_pointer()
      .hover(s => s.opacity(disabled ? 0.45 : 0.85))
      .on_key_down((event, cx) => {
        if (!disabled && (event.key === "enter" || event.key === "space")) {
          action(cx);
          cx.stop_propagation();
        }
      })
      .on_click((_event, cx) => { if (!disabled) action(cx); }).child(text);
  }

  render(cx) {
    const t = theme();
    const pending = this.state?.state === "enrolling";
    const active = this.state?.active;
    const unavailable = this.state && !this.state.available;
    const disabled = this.busy || !this.config || !this.state || unavailable || this.remote();
    if (!props()?.picker) {
      const label = this.error ? "Revisar cuenta" : unavailable ? "No disponible" : pending ? "Iniciando sesión" : active?.label ?? "Conectar cuenta";
      return h_flex().track_focus(this.handle).size_full().px(8).items_center().justify_end()
        .bg(t.chrome).border_b(1).border_color(t.border)
        .on_key_down((e, cx) => {
          if (e.key === "enter" || e.key === "space") { this.openPicker(); cx.stop_propagation(); }
        })
        .child(h_flex().id("codex-account-picker").h(28).px(9).gap(7).items_center().rounded(7)
          .border_1().border_color(this.handle.is_focused() ? t.accent : t.chrome)
          .hover(s => s.bg(t.hover)).cursor_pointer().text_size(12).text_color(t.foreground)
          .on_click(() => this.openPicker())
          .child(svg("mods/codex-accounts/account.svg").size(14).text_color(t.muted))
          .child(div().truncate().child("Codex · " + label))
          .child(svg("mods/codex-accounts/chevron.svg").size(12).text_color(t.dim)));
    }
    const note = this.remote() ? "El selector está disponible en este equipo."
      : this.managed() === false ? "Esta pestaña usa una sesión no administrada. Abre Codex desde aquí para usar esta cuenta."
      : "Cuenta para Codex en Herdr.";
    const actionIds = disabled ? [] : pending ? ["cancel-login"]
      : active ? ["open-codex", "open-shell"] : ["connect"];
    return v_flex().id("codex-accounts-panel").track_focus(this.handle)
      .on_key_down((e, cx) => {
        if (e.key === "escape") { closeOverlay(props().overlay); cx.stop_propagation(); }
        if (actionIds.length && ["tab", "left", "right"].includes(e.key)) {
          const index = actionIds.findIndex(id => this.buttons[id].is_focused());
          const backwards = e.key === "left" || (e.key === "tab" && e.modifiers.shift);
          const next = index < 0 ? (backwards ? actionIds.length - 1 : 0)
            : (index + (backwards ? -1 : 1) + actionIds.length) % actionIds.length;
          this.buttons[actionIds[next]].focus();
          cx.notify();
          cx.stop_propagation();
        }
        if ((e.key === "enter" || e.key === "space") && !disabled && this.handle.is_focused()) {
          if (pending) this.action("cancel", [this.state.login.id], cx);
          else if (active) this.launch("launch");
          else this.action("enrol", [], cx);
          cx.stop_propagation();
        }
      }).w(410).h(330).p(18).gap(14).bg(t.popover).text_color(t.foreground)
      .child(h_flex().items_center().gap(10)
        .child(svg("mods/codex-accounts/account.svg").size(19).text_color(t.accent))
        .child(div().flex_1().text_size(16).font_semibold().child("Cuenta de Codex"))
        .child(div().text_size(11).text_color(t.muted).child("Esc para cerrar")))
      .child(v_flex().h(190).flex_shrink_0().gap(14).overflow_y_scrollbar()
      .child(div().text_size(12.5).text_color(t.muted).child(note))
      .when(Boolean(unavailable), el => el.child(v_flex().gap(5)
        .child(div().text_size(14).font_medium().child("Codex no está disponible"))
        .child(div().text_size(12.5).text_color(t.muted).child("Instala Codex y vuelve a intentarlo. Tu cuenta guardada se conserva."))))
      .when(Boolean(active), el => el.child(v_flex().gap(5).py(10)
        .child(h_flex().gap(8).items_center()
          .child(div().size(6).rounded(3).bg(t.done))
          .child(div().text_size(14).font_medium().truncate().child(active.label)))
        .child(div().text_size(12).text_color(t.muted).truncate().child(active.email ?? "Cuenta conectada"))))
      .when(!active && !pending && !unavailable, el => el.child(v_flex().gap(5).py(8)
        .child(div().text_size(14).font_medium().child("Conecta tu cuenta de ChatGPT"))
        .child(div().text_size(12.5).text_color(t.muted).child("El inicio de sesión se abrirá en tu navegador."))))
      .when(Boolean(pending), el => el.child(v_flex().gap(6).py(10)
        .child(div().text_size(14).font_medium().child("Completa el inicio de sesión"))
        .child(div().text_size(12.5).text_color(t.muted).child("Continúa en el navegador. Esta ventana se actualizará al terminar."))))
      .when(Boolean(this.error || this.state?.login?.error), el => el.child(div().text_size(12).text_color(t.blocked)
        .child(this.error ?? this.state.login.error))))
      .child(h_flex().gap(8)
        .when(!active && !pending, el => el.child(this.button("connect", "Conectar cuenta", true, disabled, cx => this.action("enrol", [], cx))))
        .when(Boolean(pending), el => el.child(this.button("cancel-login", "Cancelar inicio de sesión", false, disabled, cx => this.action("cancel", [this.state.login.id], cx))))
        .when(Boolean(active) && !pending, el => el
          .child(this.button("open-codex", "Abrir Codex", true, disabled, () => this.launch("launch")))
          .child(this.button("open-shell", "Abrir terminal", false, disabled, () => this.launch("shell")))));
  }
}
