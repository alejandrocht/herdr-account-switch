import { View, div, svg } from "gpui-kit";
import { h_flex, v_flex } from "gpui-base";
import { appHome, readTextFile, exec, hc, openOverlay, closeOverlay, props, theme, run, focused, spaces, panes, home, nextCommand } from "herdr";

export default class CodexAccounts extends View {
  init(_props, cx) {
    this.state = null;
    this.config = null;
    this.busy = false;
    this.error = null;
    this.statusError = null;
    this.handle = cx.focus_handle();
    this.buttons = Object.fromEntries(["connect", "cancel-login", "open-codex", "open-shell", "resume"]
      .map(id => [id, cx.focus_handle()]));
    if (props()?.picker) this.handle.focus();
    cx.spawn(async (cx) => {
      for (;;) {
        const command = await nextCommand();
        if (command === "focus") this.handle.focus();
        if (command === "open" && !props()?.picker) this.openPicker();
        if (command === "connect" && !props()?.picker && !this.remote()) this.action("enrol", [], cx);
        if (command === "launch" && !props()?.picker && !this.remote()) this.launch("launch", cx);
      }
    });
    cx.spawn(async (cx) => {
      try {
        this.config = JSON.parse(await readTextFile(appHome() + "/mods/codex-accounts/config.json"));
        await this.refresh(cx);
      } catch (_error) {
        this.error = "No se pudo cargar el selector. Revisa su instalación.";
      }
      cx.notify();
    });
    cx.timer.every(3000, (cx) => {
      if (this.busy || !this.config) return;
      cx.spawn(async (cx) => { await this.refresh(cx); cx.notify(); });
    });
  }

  async call(action, args = []) {
    const c = this.config;
    const result = await exec(c.python, [c.controller, "--home", c.accounts_home, action, ...args], { timeout: 120000 });
    let data;
    try { data = JSON.parse(result.stdout); }
    catch (_error) { throw new Error("El gestor no respondió. Vuelve a intentarlo."); }
    if (result.code !== 0 || data.error) throw new Error(data.error ?? "No se pudo completar la operación.");
    return data;
  }

  async refresh(cx) {
    try {
      this.state = await this.call("status");
      for (const account of this.state.profiles ?? []) {
        this.buttons["account-" + account.slug] ??= cx.focus_handle();
      }
      this.statusError = null;
    }
    catch (error) { this.statusError = error.message; }
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
          await this.openTerminal(result.command, cx);
          if (props()?.overlay) closeOverlay(props().overlay);
        }
        await this.refresh(cx);
      } catch (error) { this.error = error.message; }
      this.busy = false;
      cx.notify();
    });
  }

  async openTerminal(argv, cx) {
    // tab.new's macOS agent launcher returns to a regular login shell.
    // Start the actual program in core so it exits with its private environment.
    const id = Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
    const space = spaces().find(s => s.active)?.id ?? "sp" + id;
    const result = await hc(["run", "--bg", "--json", "--no-parent", "--outlive-parent", "--no-notify",
      "--label", "herdr.space=" + space, "--label", "herdr.tab=tb" + id,
      "--cwd", focused()?.cwd ?? home(), "--", ...argv]);
    if (result.code !== 0) throw new Error("No se pudo abrir el terminal de Herdr. Vuelve a intentarlo.");
    const terminal = JSON.parse(result.stdout).address;
    if (!terminal) throw new Error("Herdr no confirmó el terminal. Revisa el estado del registro.");
    // Core labels request native adoption even before the app knows this
    // terminal. Wait only for this action's pane before asking it to focus.
    for (let attempt = 0; attempt < 100; attempt++) {
      const pane = panes().find(p => p.terminal === terminal);
      if (pane) { run("pane.focus", { pane: pane.pane }); return; }
      await cx.sleep(50);
    }
    throw new Error("El terminal se inició, pero Herdr no pudo mostrar su pestaña. Reabre esta ventana; tu cuenta sigue guardada.");
  }

  launch(command, cx, args = []) {
    const c = this.config;
    if (!c || !this.state?.active) return;
    this.busy = true;
    this.error = null;
    cx.notify();
    cx.spawn(async (cx) => {
      try {
        await this.openTerminal([c.python, c.controller, "--home", c.accounts_home, command, ...args], cx);
        if (props()?.overlay) closeOverlay(props().overlay);
      } catch (error) { this.error = error.message; }
      this.busy = false;
      cx.notify();
    });
  }

  openPicker() {
    openOverlay({ mod: "codex-accounts", props: { picker: true }, kind: "popup", width: 410, height: 430 });
  }

  managed() {
    const address = focused()?.terminal;
    if (!address) return null;
    return Boolean(this.state?.managed_terminals?.includes(address));
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
    const profiles = this.state?.profiles ?? [];
    const phase = this.state?.switch?.phase;
    const switching = ["requested", "waiting", "checking", "resuming"].includes(phase);
    const unavailable = this.state && !this.state.available;
    const disabled = this.busy || !this.config || !this.state || unavailable || this.remote();
    if (!props()?.picker) {
      const label = this.error || this.statusError ? "Revisar cuenta" : unavailable ? "No disponible" : pending ? "Iniciando sesión"
        : switching ? "Cambiando cuenta" : active && this.managed() === false ? "Sesión externa" : active?.label ?? "Conectar cuenta";
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
      : this.managed() === false ? "Esta pestaña está fuera del gestor. Abre Codex desde aquí o retoma una conversación guardada."
      : "Elige la cuenta para Codex en Herdr.";
    const actionIds = disabled ? [] : pending ? ["cancel-login"]
      : switching ? [] : active ? [...profiles.map(p => "account-" + p.slug), "connect", "open-codex", "open-shell", "resume"] : ["connect"];
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
          else if (active && !switching) this.launch("launch", cx);
          else this.action("enrol", [], cx);
          cx.stop_propagation();
        }
      }).w(410).h(430).p(18).gap(14).bg(t.popover).text_color(t.foreground)
      .child(h_flex().items_center().gap(10)
        .child(svg("mods/codex-accounts/account.svg").size(19).text_color(t.accent))
        .child(div().flex_1().text_size(16).font_semibold().child("Cuentas de Codex"))
        .child(div().text_size(11).text_color(t.muted).child("Esc para cerrar")))
      .child(v_flex().flex_1().min_h(0).gap(12).overflow_y_scrollbar()
      .child(div().text_size(12.5).text_color(t.muted).child(note))
      .when(Boolean(unavailable), el => el.child(v_flex().gap(5)
        .child(div().text_size(14).font_medium().child("Codex no está disponible"))
        .child(div().text_size(12.5).text_color(t.muted).child("Instala Codex y vuelve a intentarlo. Tu cuenta guardada se conserva."))))
      .children(profiles.map(account => {
        const id = "account-" + account.slug;
        const handle = this.buttons[id];
        const current = active?.slug === account.slug;
        const requested = switching && this.state.switch.requested === account.slug;
        const choose = cx => { if (!disabled && !pending && !switching) this.action("select", [account.slug], cx); };
        return h_flex().id(id).track_focus(handle).tab_index(0).tab_stop(!disabled && !pending && !switching)
          .p(10).gap(10).rounded(8).border_1().border_color(handle.is_focused() ? t.accent : current ? t.input : t.border)
          .bg(current ? t.selected : t.popover).items_center().cursor_pointer()
          .hover(s => s.bg(t.hover)).on_click((_event, cx) => choose(cx))
          .on_key_down((event, cx) => {
            if (event.key === "enter" || event.key === "space") { choose(cx); cx.stop_propagation(); }
          })
          .child(v_flex().flex_1().min_w(0).gap(4)
            .child(div().text_size(13).font_medium().truncate().child(account.label))
            .child(div().text_size(12).text_color(t.muted).truncate().child(account.email ?? "Cuenta guardada")))
          .child(div().text_size(11).text_color(t.muted).child(requested ? "Solicitada" : current ? "En uso" : "Usar"));
      }))
      .when(!active && !pending && !unavailable, el => el.child(v_flex().gap(5).py(8)
        .child(div().text_size(14).font_medium().child("Conecta tu cuenta de ChatGPT"))
        .child(div().text_size(12.5).text_color(t.muted).child("El inicio de sesión se abrirá en tu navegador."))))
      .when(Boolean(pending), el => el.child(v_flex().gap(6).py(10)
        .child(div().text_size(14).font_medium().child("Completa el inicio de sesión"))
        .child(div().text_size(12.5).text_color(t.muted).child("Continúa en el navegador. Esta ventana se actualizará al terminar."))))
      .when(Boolean(switching), el => el.child(div().text_size(12.5).text_color(t.muted)
        .child(phase === "waiting" ? "Esperando a que termine la respuesta o herramienta en curso…"
          : phase === "resuming" ? "Retomando la misma conversación…" : "Comprobando la cuenta elegida…")))
      .when(phase === "adopted", el => el.child(div().text_size(12).text_color(t.muted).child("Cambio confirmado en el mismo hilo.")))
      .when(phase === "prepared", el => el.child(div().text_size(12).text_color(t.muted).child("Cuenta lista para abrir Codex.")))
      .when(Boolean(this.state?.login?.duplicate) && !pending, el => el.child(div().text_size(12).text_color(t.muted).child("Esta cuenta ya estaba guardada.")))
      .when(Boolean(this.error || this.statusError || this.state?.login?.error || this.state?.switch?.error), el => el.child(div().text_size(12).text_color(t.blocked)
        .child(this.error ?? this.statusError ?? this.state?.login?.error ?? this.state?.switch?.error)))
      .when(Boolean(active) && !pending && !switching, el => el.child(this.button("resume", "Retomar conversación guardada", false, disabled,
        cx => this.launch("launch", cx, ["--", "resume"])))))
      .child(h_flex().gap(8)
        .when(!pending, el => el.child(this.button("connect", active ? "Añadir cuenta" : "Conectar cuenta", !active, disabled || switching, cx => this.action("enrol", [], cx))))
        .when(Boolean(pending), el => el.child(this.button("cancel-login", "Cancelar inicio de sesión", false, disabled, cx => this.action("cancel", [this.state.login.id], cx))))
        .when(Boolean(active) && !pending, el => el
          .child(this.button("open-codex", "Abrir Codex", true, disabled || switching, cx => this.launch("launch", cx)))
          .child(this.button("open-shell", "Terminal", false, disabled || switching, cx => this.launch("shell", cx)))));
  }
}
