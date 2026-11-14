/* Outlook Dashboard: frontend logic (plain JavaScript, no build step).
 * Email data is only ever inserted with textContent, never innerHTML. */
(function () {
  "use strict";

  const PAGE_SIZE = 50;
  const AUTO_REFRESH_MS = 60_000;
  const MAX_REFRESH_ITEMS = 200;

  const $ = (id) => document.getElementById(id);

  const state = {
    folder: "INBOX",
    folders: [], // from /api/folders
    checked: new Set(), // ids of ticked emails (bulk actions)
    sort: "newest",
    group: "none", // none | sender | conversation | date
    collapsed: new Set(), // collapsed group keys
    category: "", // category filter (name)
    categories: [], // [{name, color, keyword}]
    colors: [],
    query: "",
    filters: { unread: false, flagged: false, attachments: false, from: "", to: "" },
    messages: [],
    total: 0,
    nextStart: null,
    selectedId: null,
    loading: false,
    requestSeq: 0,
  };

  // ------------------------------------------------------------------------
  // API helper
  // ------------------------------------------------------------------------

  class ApiError extends Error {
    constructor(status, code, message) {
      super(message);
      this.status = status;
      this.code = code;
    }
  }

  async function api(path, options = {}) {
    let res;
    try {
      res = await fetch(path, {
        ...options,
        headers: {
          Accept: "application/json",
          "X-Requested-With": "outlook-dashboard",
          // FormData (file uploads) sets its own multipart Content-Type.
          ...(options.body && !(options.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
          ...(options.headers || {}),
        },
      });
    } catch {
      throw new ApiError(0, "server_unreachable", "The dashboard has stopped. Open it again with the Outlook Dashboard icon on your desktop.");
    }
    let body = null;
    try { body = await res.json(); } catch { /* non-JSON */ }
    if (!res.ok) {
      throw new ApiError(res.status, body?.code || "error", body?.message || "Something went wrong. Please try again.");
    }
    return body;
  }

  const BACKEND = document.body.dataset.backend || "imap";
  const CONNECTION_CODES = new Set([
    "outlook_not_running", "outlook_not_installed", "outlook_busy", "server_unreachable",
    "service_unavailable", "consent_required", "not_signed_in",
  ]);

  // ------------------------------------------------------------------------
  // Connection status
  // ------------------------------------------------------------------------

  function setConnection(ok, label, bannerMessage) {
    $("conn-dot").className = "h-2 w-2 rounded-full " + (ok ? "bg-emerald-500" : "bg-amber-500");
    $("conn-label").textContent = label;
    $("conn-label").title = label;
    if (bannerMessage) {
      $("conn-message").textContent = bannerMessage;
      $("conn-banner").classList.remove("hidden");
    } else {
      $("conn-banner").classList.add("hidden");
    }
  }

  function handleError(err) {
    if (err.code === "not_signed_in") {
      showSignin(err.message);
      return true;
    }
    if (CONNECTION_CODES.has(err.code)) {
      setConnection(false, "Not connected", err.message);
      return true;
    }
    return false;
  }

  async function checkStatus() {
    try {
      const s = await api("/api/status");
      const who = (s.accounts && s.accounts[0]) || s.user || "Outlook";
      setConnection(true, (BACKEND === "imap" ? "Connected: " : "Classic Outlook: ") + who);
      $("signout-btn").classList.toggle("hidden", BACKEND !== "imap");
      return true;
    } catch (err) {
      if (!handleError(err)) setConnection(false, "Not connected", err.message);
      return false;
    }
  }

  // ------------------------------------------------------------------------
  // Sign-in (email + password for the mail server)
  // ------------------------------------------------------------------------

  let started = false;
  const DEFAULT_SIGNIN_MESSAGE = "Please sign in with your email address and password.";

  function showSignin(message, defaults) {
    $("signin").classList.add("open");
    if (message && message !== DEFAULT_SIGNIN_MESSAGE) {
      $("signin-error").textContent = message;
      $("signin-error").classList.remove("hidden");
    }
    if (defaults) {
      $("si-email").value = defaults.email || "";
      $("si-name").value = defaults.name || "";
      $("si-imap-host").value = defaults.imapHost || "";
      $("si-imap-port").value = defaults.imapPort || 993;
      $("si-smtp-host").value = defaults.smtpHost || "";
      $("si-smtp-port").value = defaults.smtpPort || 465;
    }
    ($("si-email").value ? $("si-password") : $("si-email")).focus();
  }

  // Fill the server names from the email domain (mail.<domain>) unless the user changed them.
  $("si-email").addEventListener("input", () => {
    const domain = ($("si-email").value.split("@")[1] || "").trim().toLowerCase();
    for (const id of ["si-imap-host", "si-smtp-host"]) {
      const box = $(id);
      if (!box.dataset.edited) box.value = domain ? `mail.${domain}` : "";
    }
  });
  for (const id of ["si-imap-host", "si-smtp-host"]) {
    $(id).addEventListener("input", () => { $(id).dataset.edited = "1"; });
  }

  $("signin-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("si-email").value.trim();
    const password = $("si-password").value;
    $("signin-error").classList.add("hidden");
    if (!email || !password) {
      $("signin-error").textContent = "Enter your email address and password.";
      $("signin-error").classList.remove("hidden");
      return;
    }
    $("signin-btn").disabled = true;
    $("signin-btn-label").textContent = "Checking with the mail server…";
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email,
          password,
          name: $("si-name").value.trim(),
          imapHost: $("si-imap-host").value.trim(),
          imapPort: Number($("si-imap-port").value) || 993,
          smtpHost: $("si-smtp-host").value.trim(),
          smtpPort: Number($("si-smtp-port").value) || 465,
        }),
      });
      $("si-password").value = "";
      $("signin").classList.remove("open");
      startApp();
    } catch (err) {
      $("signin-error").textContent = err.message;
      $("signin-error").classList.remove("hidden");
      if (err.code === "service_unavailable") $("si-advanced").open = true;
    } finally {
      $("signin-btn").disabled = false;
      $("signin-btn-label").textContent = "Sign in";
    }
  });

  $("signout-btn").addEventListener("click", async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } finally {
      location.reload();
    }
  });

  // ------------------------------------------------------------------------
  // Formatting
  // ------------------------------------------------------------------------

  function formatListDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    const now = new Date();
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const startThat = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const days = Math.round((startToday - startThat) / 86_400_000);
    if (days <= 0) return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    if (days < 7) return d.toLocaleDateString(undefined, { weekday: "short" });
    if (d.getFullYear() === now.getFullYear()) return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }

  function shortDay(value) {
    const [y, m, d] = value.split("-").map(Number);
    return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  // ------------------------------------------------------------------------
  // DOM helpers
  // ------------------------------------------------------------------------

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  const ICONS = {
    paperclip: '<path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
    flag: '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
    important: '<circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/>',
  };

  // Icons are static markup we control; no email data goes through innerHTML.
  function icon(name, className, label) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", name === "flag" ? "currentColor" : "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("class", className);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
    svg.innerHTML = ICONS[name];
    return svg;
  }

  // ------------------------------------------------------------------------
  // Rendering
  // ------------------------------------------------------------------------

  function renderSkeleton(rows = 8) {
    const list = $("message-list");
    list.replaceChildren();
    for (let i = 0; i < rows; i++) {
      const li = el("li", "space-y-2 border-b border-slate-200 px-4 py-3 dark:border-slate-800");
      li.setAttribute("aria-hidden", "true");
      const top = el("div", "flex justify-between gap-4");
      top.append(el("div", "skeleton h-4 w-1/3"), el("div", "skeleton h-3 w-12"));
      li.append(top, el("div", "skeleton h-4 w-3/4"), el("div", "skeleton h-3 w-full"));
      list.append(li);
    }
    $("list-empty").classList.add("hidden");
    $("load-more-wrap").classList.add("hidden");
  }

  function currentFolder() {
    return state.folders.find((f) => f.id === state.folder) || null;
  }

  /** Sent Items and Drafts show who the email is to, like Outlook. */
  function showsRecipients() {
    const f = currentFolder();
    return !!f && (f.key === "sentitems" || f.key === "drafts");
  }

  // Initials in a coloured circle; the colour is stable per sender.
  const AVATAR_COLORS = ["#1d4ed8", "#0f766e", "#7c3aed", "#b45309", "#be123c", "#0369a1", "#4d7c0f", "#9333ea", "#c2410c", "#334155"];
  function avatarFor(p) {
    const name = (p && (p.name || p.address)) || "?";
    const clean = name.replace(/["']/g, "").replace(/@.*/, "").replace(/[._-]+/g, " ").trim();
    const parts = clean.split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w));
    const initials = ((parts[0] || "?")[0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
    let h = 0;
    for (const ch of ((p && p.address) || name).toLowerCase()) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    const a = el("span", "msg-avatar", initials);
    a.style.setProperty("--av", AVATAR_COLORS[h % AVATAR_COLORS.length]);
    a.setAttribute("aria-hidden", "true");
    return a;
  }

  function messageRow(m) {
    const unread = !m.isRead;
    const checked = state.checked.has(m.id);
    const li = el("li", "msg-item");
    const box = el("input", "msg-check");
    box.type = "checkbox";
    box.checked = checked;
    box.dataset.id = m.id;
    box.setAttribute("aria-label", "Select email: " + m.subject);
    const btn = el("button", "msg" + (unread ? " unread" : "") + (m.id === state.selectedId ? " selected" : "") + (checked ? " checked" : ""));
    btn.type = "button";
    btn.dataset.id = m.id;
    btn.draggable = true;
    if (m.id === state.selectedId) btn.setAttribute("aria-current", "true");

    const row1 = el("div", "flex items-baseline gap-2");
    let sender, senderTitle;
    if (showsRecipients()) {
      const to = (m.toRecipients || []).map((p) => p.name || p.address);
      sender = to.length ? "To: " + to.join("; ") : "(no recipients)";
      senderTitle = (m.toRecipients || []).map((p) => p.address).join("; ");
    } else {
      sender = m.from ? m.from.name || m.from.address : "(unknown sender)";
      senderTitle = m.from && m.from.address;
    }
    const senderEl = el("span", "min-w-0 flex-1 truncate text-sm " + (unread ? "font-semibold" : "text-slate-700 dark:text-slate-300"), sender);
    if (senderTitle) senderEl.title = senderTitle;
    row1.append(
      senderEl,
      el("span", "shrink-0 text-xs " + (unread ? "font-semibold text-brand-600 dark:text-brand-400" : "text-slate-500"), formatListDate(m.receivedDateTime)),
    );

    const row2 = el("div", "mt-0.5 flex items-center gap-1.5");
    if (m.isDraft) row2.append(el("span", "shrink-0 text-xs font-semibold text-red-600 dark:text-red-400", "[Draft]"));
    if (m.importance === "high") row2.append(icon("important", "h-3.5 w-3.5 shrink-0 text-red-500", "High importance"));
    row2.append(el("span", "min-w-0 flex-1 truncate text-sm " + (unread ? "font-medium text-brand-600 dark:text-brand-400" : ""), m.subject));
    const cats = m.categories || [];
    cats.slice(0, 2).forEach((name) => row2.append(categoryPill(name)));
    if (cats.length > 2) {
      const more = el("span", "shrink-0 text-[11px] font-semibold text-slate-500", `+${cats.length - 2}`);
      more.title = cats.slice(2).join(", ");
      row2.append(more);
    }
    if (m.hasAttachments) row2.append(icon("paperclip", "h-3.5 w-3.5 shrink-0 text-slate-400", "Has attachments"));
    if (m.flagged) row2.append(icon("flag", "h-3.5 w-3.5 shrink-0 text-red-500", "Flagged"));

    const preview = el("p", "mt-0.5 truncate text-xs text-slate-500", m.preview || " ");
    const sr = el("span", "sr-only", unread ? "Unread" : "Read");

    const person = showsRecipients() ? (m.toRecipients || [])[0] : m.from;
    const main = el("div", "msg-main");
    main.append(row1, row2, preview, sr);
    const body = el("div", "msg-body");
    body.append(avatarFor(person), main);
    btn.append(body);
    li.append(box, btn);
    return li;
  }

  function filtersActive() {
    const f = state.filters;
    return f.unread || f.flagged || f.attachments || !!f.from || !!f.to || !!state.category;
  }

  function categoryColor(name) {
    const c = state.categories.find((x) => x.name === name);
    return c ? c.color : "gray";
  }

  function categoryPill(name) {
    const pill = el("span", `cat-pill shrink-0 cat-${categoryColor(name)}`);
    pill.append(el("span", "cat-dot"), el("span", "truncate", name));
    pill.title = `Category: ${name}`;
    return pill;
  }

  // ---- Grouping (sender / conversation / date) of the loaded emails ----

  function dateBucket(iso) {
    if (!iso) return ["older", "Older"];
    const d = new Date(iso);
    const today = localToday();
    const day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((today - day) / 86_400_000);
    const weekStart = new Date(today);
    weekStart.setDate(today.getDate() - ((today.getDay() + 6) % 7)); // Monday
    if (diff <= 0) return ["0today", "Today"];
    if (diff === 1) return ["1yesterday", "Yesterday"];
    if (day >= weekStart) return ["2week", "Earlier this week"];
    const lastWeek = new Date(weekStart);
    lastWeek.setDate(weekStart.getDate() - 7);
    if (day >= lastWeek) return ["3lastweek", "Last week"];
    if (d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth()) return ["4month", "Earlier this month"];
    const label = d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
    return [`m${d.getFullYear()}-${String(d.getMonth()).padStart(2, "0")}`, label];
  }

  function groupOf(m) {
    if (state.group === "sender") {
      const p = showsRecipients() ? (m.toRecipients || [])[0] : m.from;
      if (!p) return ["?", showsRecipients() ? "(no recipients)" : "(unknown sender)"];
      return [(p.address || p.name || "").toLowerCase(), (showsRecipients() ? "To: " : "") + (p.name || p.address)];
    }
    if (state.group === "conversation") {
      const key = m.conversationKey ?? (m.subject || "").replace(/^\s*((re|fw|fwd)\s*:\s*)+/i, "").trim().toLowerCase();
      return [key || "(no subject)", (m.subject || "").replace(/^\s*((re|fw|fwd|aw|wg)\s*(\[\d+\])?\s*:\s*)+/i, "").trim() || "(no subject)"];
    }
    return dateBucket(m.receivedDateTime);
  }

  function buildGroups() {
    const groups = new Map();
    for (const m of state.messages) {
      const [key, label] = groupOf(m);
      if (!groups.has(key)) groups.set(key, { key, label, items: [] });
      groups.get(key).items.push(m);
    }
    return [...groups.values()];
  }

  function groupHeader(g) {
    const li = el("li", "msg-item");
    const box = el("input", "msg-check group-check");
    box.type = "checkbox";
    box.dataset.group = g.key;
    const n = g.items.filter((m) => state.checked.has(m.id)).length;
    box.checked = n === g.items.length;
    box.indeterminate = n > 0 && n < g.items.length;
    box.setAttribute("aria-label", `Select all emails in group ${g.label}`);
    box.style.top = "0.45rem";
    const open = !state.collapsed.has(g.key);
    const btn = el("button", "group-head pl-8");
    btn.type = "button";
    btn.dataset.group = g.key;
    btn.setAttribute("aria-expanded", String(open));
    btn.innerHTML = '<svg viewBox="0 0 24 24" class="chev h-3.5 w-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    btn.append(el("span", "min-w-0 flex-1 truncate", g.label));
    const unread = g.items.filter((m) => !m.isRead).length;
    if (unread) btn.append(el("span", "text-brand-600 dark:text-brand-400", `${unread} unread`));
    btn.append(el("span", "font-normal text-slate-500", String(g.items.length)));
    li.append(box, btn);
    return li;
  }

  function renderRows() {
    if (state.group === "none") return state.messages.map(messageRow);
    const rows = [];
    for (const g of buildGroups()) {
      rows.push(groupHeader(g));
      if (!state.collapsed.has(g.key)) g.items.forEach((m) => rows.push(messageRow(m)));
    }
    return rows;
  }

  function renderList() {
    const list = $("message-list");
    list.replaceChildren(...renderRows());
    $("groups-toggle").classList.toggle("hidden", state.group === "none" || !state.messages.length);
    $("groups-toggle").textContent = state.collapsed.size ? "Expand all" : "Collapse all";

    const empty = state.messages.length === 0;
    $("list-empty").classList.toggle("hidden", !empty);
    $("list-empty").classList.toggle("flex", empty);
    if (empty) {
      const filtering = !!state.query || filtersActive();
      $("list-empty-title").textContent = filtering ? "No matching emails" : "Nothing here";
      $("list-empty-body").textContent = filtering ? "Try a different search or clear the filters." : "There's nothing in this folder.";
    }

    const more = state.nextStart !== null;
    $("load-more-wrap").classList.toggle("hidden", !more);
    $("load-more-wrap").classList.toggle("flex", more);

    $("list-count").textContent = state.total ? `${state.messages.length.toLocaleString()} of ${state.total.toLocaleString()}` : "";
    const folderName = currentFolder() ? currentFolder().name : "Inbox";
    $("list-title").textContent = state.query ? `"${state.query}" in ${folderName}` : folderName;
    renderBulkBar();
  }

  // ------------------------------------------------------------------------
  // Selection (tick boxes) and bulk actions
  // ------------------------------------------------------------------------

  function renderBulkBar() {
    // Forget ticks for emails no longer listed (moved, deleted, other folder).
    const listed = new Set(state.messages.map((m) => m.id));
    for (const id of state.checked) if (!listed.has(id)) state.checked.delete(id);
    const n = state.checked.size;
    $("bulk-bar").classList.toggle("hidden", !n);
    $("bulk-bar").classList.toggle("flex", n > 0);
    document.body.classList.toggle("selecting", n > 0);
    $("bulk-count").textContent = n === 1 ? "1 selected" : `${n} selected`;
    $("bulk-all").checked = n > 0 && n === state.messages.length;
    $("bulk-all").indeterminate = n > 0 && n < state.messages.length;
  }

  function setChecked(id, on) {
    if (on) state.checked.add(id);
    else state.checked.delete(id);
    const row = document.querySelector(`.msg[data-id="${CSS.escape(id)}"]`);
    if (row) row.classList.toggle("checked", on);
    const box = document.querySelector(`.msg-check[data-id="${CSS.escape(id)}"]`);
    if (box) box.checked = on;
  }

  function clearChecked() {
    for (const id of [...state.checked]) setChecked(id, false);
    renderBulkBar();
  }

  let lastCheckedId = null;
  $("message-list").addEventListener("click", (e) => {
    const head = e.target.closest(".group-head");
    if (head) {
      const key = head.dataset.group;
      if (state.collapsed.has(key)) state.collapsed.delete(key);
      else state.collapsed.add(key);
      renderList();
      return;
    }
    const box = e.target.closest(".msg-check");
    if (!box) return;
    e.stopPropagation();
    if (box.dataset.group !== undefined) {
      const g = buildGroups().find((x) => x.key === box.dataset.group);
      if (g) g.items.forEach((m) => state.checked[box.checked ? "add" : "delete"](m.id));
      renderList();
      return;
    }
    const id = box.dataset.id;
    // Shift+click ticks everything between the last ticked email and this one.
    if (e.shiftKey && lastCheckedId && lastCheckedId !== id) {
      const ids = state.messages.map((m) => m.id);
      const [a, b] = [ids.indexOf(lastCheckedId), ids.indexOf(id)].sort((x, y) => x - y);
      if (a >= 0) ids.slice(a, b + 1).forEach((x) => setChecked(x, box.checked));
    }
    setChecked(id, box.checked);
    lastCheckedId = id;
    if (state.group !== "none") renderList(); // keep the group tick boxes in step
    else renderBulkBar();
  });

  // ---- Sort / group / category filter ----
  const GROUP_SORT = { sender: "sender", conversation: "subject" };

  $("sort-select").addEventListener("change", () => {
    state.sort = $("sort-select").value;
    // Grouping by sender/conversation needs the matching sort to keep groups together.
    if (GROUP_SORT[state.group] && GROUP_SORT[state.group] !== state.sort) {
      state.group = "none";
      $("group-select").value = "none";
    }
    if (state.group === "date" && !["newest", "oldest"].includes(state.sort)) {
      state.group = "none";
      $("group-select").value = "none";
    }
    savePrefs();
    loadMessages("reset");
  });
  $("group-select").addEventListener("change", () => {
    state.group = $("group-select").value;
    state.collapsed.clear();
    let reload = false;
    const wanted = GROUP_SORT[state.group] || (state.group === "date" && !["newest", "oldest"].includes(state.sort) ? "newest" : null);
    if (wanted && wanted !== state.sort && BACKEND === "imap") {
      state.sort = wanted;
      $("sort-select").value = wanted;
      reload = true;
    }
    savePrefs();
    if (reload) loadMessages("reset");
    else renderList();
  });
  $("groups-toggle").addEventListener("click", () => {
    if (state.collapsed.size) state.collapsed.clear();
    else buildGroups().forEach((g) => state.collapsed.add(g.key));
    renderList();
  });
  $("cat-filter").addEventListener("change", () => {
    state.category = $("cat-filter").value;
    $("cat-filter").classList.toggle("active", !!state.category);
    updateFilterUi();
    loadMessages("reset");
  });

  function savePrefs() {
    try { localStorage.setItem("listPrefs", JSON.stringify({ sort: state.sort, group: state.group })); } catch { /* storage unavailable */ }
  }
  (function loadPrefs() {
    try {
      const p = JSON.parse(localStorage.getItem("listPrefs") || "{}");
      if (["newest", "oldest", "sender", "subject", "size"].includes(p.sort)) state.sort = p.sort;
      if (["none", "sender", "conversation", "date"].includes(p.group)) state.group = p.group;
    } catch { /* ignore */ }
    if (BACKEND !== "imap") state.sort = "newest"; // classic Outlook mode: date order only
    $("sort-select").value = state.sort;
    $("group-select").value = state.group;
  })();

  // ---- Bulk actions ----
  const BULK_DONE = {
    read: (n) => `${n} marked as read`, unread: (n) => `${n} marked as unread`,
    flag: (n) => `${n} flagged`, unflag: (n) => `${n} unflagged`,
  };

  /** Applies an action to emails and updates the list / reading pane in place. */
  async function runBulk(ids, action, category) {
    const r = await api("/api/messages/bulk", { method: "POST", body: JSON.stringify({ ids, action, category }) });
    const set = new Set(ids);
    if (action === "delete") {
      const openGone = reading.detail && set.has(reading.detail.id);
      state.messages = state.messages.filter((m) => !set.has(m.id));
      state.total = Math.max(0, state.total - r.changed);
      ids.forEach((id) => state.checked.delete(id));
      if (openGone) closeReading();
    } else {
      for (const m of state.messages.concat(reading.detail ? [reading.detail] : [])) {
        if (!set.has(m.id)) continue;
        if (action === "read" || action === "unread") m.isRead = action === "read";
        if (action === "flag" || action === "unflag") m.flagged = action === "flag";
        if (action === "categorize" && !m.categories.includes(category)) m.categories = [...m.categories, category];
        if (action === "uncategorize") m.categories = m.categories.filter((c) => c !== category);
      }
      if (reading.detail && set.has(reading.detail.id)) {
        renderActions(reading.detail);
        renderReadingCategories(reading.detail);
      }
      // A filter may no longer match (e.g. marked read while showing Unread only): refresh later.
    }
    renderList();
    if (["read", "unread", "delete"].includes(action)) loadFolders();
    return r;
  }

  async function bulkFromBar(action) {
    const ids = [...state.checked];
    if (!ids.length) return;
    const f = currentFolder();
    const doIt = async () => {
      const r = await runBulk(ids, action);
      let msg;
      if (action === "delete") msg = r.permanentlyDeleted ? `${r.changed} deleted permanently` : `${r.changed} moved to Deleted Items`;
      else msg = BULK_DONE[action](r.changed);
      if (r.skipped) msg += ` (${r.skipped} no longer there)`;
      toast(msg);
      if (action === "delete" || ["unread", "flagged"].some((k) => state.filters[k])) renderBulkBar();
    };
    if (action === "delete" && f && f.key === "deleteditems") {
      openDialog({
        title: `Delete ${ids.length} email${ids.length === 1 ? "" : "s"} permanently?`,
        text: "They're already in Deleted Items, so this removes them for good, also from Outlook.",
        okLabel: "Delete permanently",
        danger: true,
        onOk: doIt,
      });
      return;
    }
    try {
      await doIt();
    } catch (err) {
      if (!handleError(err)) toast(err.message, "error");
    }
  }
  document.querySelectorAll("[data-bulk]").forEach((b) => b.addEventListener("click", () => bulkFromBar(b.dataset.bulk)));
  $("bulk-all").addEventListener("change", () => {
    const on = $("bulk-all").checked;
    state.messages.forEach((m) => setChecked(m.id, on));
    renderBulkBar();
  });
  $("bulk-clear").addEventListener("click", clearChecked);
  $("bulk-move").addEventListener("click", () => chooseFolderAndMove([...state.checked]));

  function showListError(message) {
    const box = $("list-error");
    if (!message) {
      box.classList.add("hidden");
      return;
    }
    box.textContent = message;
    box.classList.remove("hidden");
  }

  function setRefreshing(on) {
    $("refresh-icon").classList.toggle("spin", on);
    $("refresh-btn").disabled = on;
  }

  // ------------------------------------------------------------------------
  // Data loading
  // ------------------------------------------------------------------------

  function queryString(start, limit) {
    const p = new URLSearchParams({ folder: state.folder, start: String(start), limit: String(limit) });
    if (state.query) p.set("q", state.query);
    const f = state.filters;
    if (f.unread) p.set("unread", "1");
    if (f.flagged) p.set("flagged", "1");
    if (f.attachments) p.set("attachments", "1");
    if (f.from) p.set("from", f.from);
    if (f.to) p.set("to", f.to);
    if (state.sort !== "newest") p.set("sort", state.sort);
    if (state.category) p.set("category", state.category);
    return p.toString();
  }

  /**
   * mode: "reset"   - new folder/search/filter: show skeleton, load first page
   *       "refresh" - reload what's already shown (keeps "Load more" progress)
   *       "more"    - append the next page
   */
  async function loadMessages(mode = "reset") {
    if (mode === "more" && (state.loading || state.nextStart === null)) return;
    const seq = ++state.requestSeq;
    state.loading = true;

    let start = 0;
    let limit = PAGE_SIZE;
    if (mode === "reset") renderSkeleton();
    if (mode === "refresh") {
      setRefreshing(true);
      limit = Math.min(Math.max(PAGE_SIZE, state.messages.length), MAX_REFRESH_ITEMS);
    }
    if (mode === "more") {
      start = state.nextStart;
      $("load-more").disabled = true;
      $("load-more").textContent = "Loading…";
    }

    try {
      const page = await api("/api/messages?" + queryString(start, limit));
      if (seq !== state.requestSeq) return; // a newer request superseded this one

      if (mode === "more") {
        // New mail can shift positions between pages; drop duplicates.
        const seen = new Set(state.messages.map((m) => m.id));
        state.messages = state.messages.concat(page.messages.filter((m) => !seen.has(m.id)));
      } else {
        state.messages = page.messages;
      }
      state.total = page.total;
      state.nextStart = page.nextStart;
      showListError(null);
      if (!$("conn-banner").classList.contains("hidden")) checkStatus();
      renderList();
    } catch (err) {
      if (seq !== state.requestSeq) return;
      if (!handleError(err)) showListError(err.message);
      if (mode === "reset") {
        state.messages = [];
        state.total = 0;
        state.nextStart = null;
        renderList();
        $("list-empty").classList.add("hidden");
      }
    } finally {
      if (seq === state.requestSeq) {
        state.loading = false;
        setRefreshing(false);
        $("load-more").disabled = false;
        $("load-more").textContent = "Load more";
      }
    }
  }

  // ------------------------------------------------------------------------
  // Folders (sidebar tree, create / rename / delete, move emails)
  // ------------------------------------------------------------------------

  const FOLDER_ICONS = {
    inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1Z"/>',
    drafts: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    sentitems: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    archive: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8M10 12h4"/>',
    junkemail: '<circle cx="12" cy="12" r="10"/><path d="m4.9 4.9 14.2 14.2"/>',
    deleteditems: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    folder: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.7-.9l-.8-1.2A2 2 0 0 0 7.9 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  };

  function folderIcon(key) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("class", "h-4 w-4 shrink-0");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = FOLDER_ICONS[key] || FOLDER_ICONS.folder; // static markup only
    return svg;
  }

  let currentView = "mail";

  function renderFolders() {
    const list = $("folder-list");
    const rows = state.folders.map((f) => {
      const li = el("li", "folder-row");
      const a = el("a", "folder-link" + (currentView === "mail" && f.id === state.folder ? " active" : ""));
      a.href = "#";
      a.dataset.folder = f.id;
      a.style.paddingLeft = `${0.5 + Math.min(f.depth, 6) * 0.9}rem`;
      if (!f.selectable) a.classList.add("opacity-60");
      a.title = f.path.join(" › ");
      a.append(folderIcon(f.key), el("span", "min-w-0 flex-1 truncate", f.name));
      // Drafts: show how many there are; other folders: unread count (like Outlook).
      const n = f.key === "drafts" ? f.totalCount : f.unreadCount;
      if (n) a.append(el("span", "folder-count text-xs font-semibold " + (f.key === "drafts" ? "text-slate-500" : "text-brand-600 dark:text-brand-400"), n.toLocaleString()));
      li.append(a);
      if (f.canModify || f.key === null) {
        const more = el("button", "folder-more");
        more.type = "button";
        more.dataset.folder = f.id;
        more.setAttribute("aria-label", `Actions for folder ${f.name}`);
        more.setAttribute("aria-haspopup", "menu");
        more.setAttribute("aria-expanded", "false");
        more.innerHTML = '<svg viewBox="0 0 24 24" class="h-4 w-4" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg>';
        li.append(more);
      }
      return li;
    });
    list.replaceChildren(...rows);
  }

  async function loadFolders() {
    try {
      const data = await api("/api/folders");
      state.folders = data.folders;
      // The open folder was renamed/deleted elsewhere (e.g. in Outlook): go back to the Inbox.
      if (!state.folders.some((f) => f.id === state.folder)) {
        const inbox = state.folders.find((f) => f.key === "inbox");
        if (inbox && state.folder !== inbox.id) {
          state.folder = inbox.id;
          loadMessages("reset");
        }
      }
      renderFolders();
      $("list-title").textContent = state.query ? $("list-title").textContent : (currentFolder() ? currentFolder().name : "Inbox");
    } catch (err) {
      if (err.code === "bad_request" && !state.folders.length) {
        // Classic Outlook mode: only the Inbox is available.
        state.folders = [{ id: "INBOX", key: "inbox", name: "Inbox", path: ["Inbox"], depth: 0, unreadCount: 0, totalCount: 0, selectable: true, canModify: false }];
        renderFolders();
      }
      /* otherwise the connection banner already explains the problem */
    }
  }

  function selectFolder(id) {
    const f = state.folders.find((x) => x.id === id);
    if (!f || !f.selectable) return;
    if (currentView !== "mail") setView("mail");
    closeSidebar();
    if (id === state.folder) return loadMessages("refresh");
    state.folder = id;
    state.checked.clear();
    closeReading();
    renderFolders();
    loadMessages("reset");
  }

  $("folder-list").addEventListener("click", (e) => {
    const more = e.target.closest(".folder-more");
    if (more) {
      e.preventDefault();
      e.stopPropagation();
      openFolderMenu(more.dataset.folder, more);
      return;
    }
    const link = e.target.closest(".folder-link");
    if (link) {
      e.preventDefault();
      selectFolder(link.dataset.folder);
    }
  });
  $("folder-list").addEventListener("contextmenu", (e) => {
    const row = e.target.closest(".folder-row");
    const more = row && row.querySelector(".folder-more");
    if (!more) return;
    e.preventDefault();
    openFolderMenu(more.dataset.folder, more);
  });

  // ---- Folder menu ----
  const folderMenu = { folder: null, anchor: null };

  function openFolderMenu(folderId, anchor) {
    const f = state.folders.find((x) => x.id === folderId);
    if (!f) return;
    closeFolderMenu();
    folderMenu.folder = f;
    folderMenu.anchor = anchor;
    anchor.setAttribute("aria-expanded", "true");
    const menu = $("folder-menu");
    menu.querySelector('[data-action="rename"]').classList.toggle("hidden", !f.canModify);
    menu.querySelector('[data-action="delete"]').classList.toggle("hidden", !f.canModify);
    menu.classList.remove("hidden");
    const r = anchor.getBoundingClientRect();
    const top = Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8);
    menu.style.top = `${Math.max(8, top)}px`;
    menu.style.left = `${Math.min(r.left, window.innerWidth - menu.offsetWidth - 8)}px`;
    menu.querySelector("button:not(.hidden)").focus();
  }

  function closeFolderMenu() {
    $("folder-menu").classList.add("hidden");
    if (folderMenu.anchor) folderMenu.anchor.setAttribute("aria-expanded", "false");
    folderMenu.anchor = null;
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#folder-menu")) closeFolderMenu();
  });
  $("folder-menu").addEventListener("keydown", (e) => {
    const items = [...$("folder-menu").querySelectorAll("button:not(.hidden)")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    } else if (e.key === "Escape" || e.key === "Tab") {
      e.stopPropagation();
      const anchor = folderMenu.anchor;
      closeFolderMenu();
      if (anchor) anchor.focus();
    }
  });
  $("folder-menu").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const f = folderMenu.folder;
    closeFolderMenu();
    if (!f) return;
    if (btn.dataset.action === "subfolder") newFolderDialog(f);
    if (btn.dataset.action === "rename") renameFolderDialog(f);
    if (btn.dataset.action === "delete") deleteFolderDialog(f);
  });

  // ---- Dialog ----
  const dialog = { onOk: null, picked: null, busy: false, returnFocus: null };

  /** opts: {title, text, input: {value, placeholder}, pickFolder: {exclude: Set}, okLabel, danger, onOk(value)} */
  function openDialog(opts) {
    dialog.onOk = opts.onOk;
    dialog.picked = null;
    dialog.busy = false;
    dialog.returnFocus = document.activeElement;
    $("dialog-title").textContent = opts.title;
    $("dialog-text").textContent = opts.text || "";
    $("dialog-text").classList.toggle("hidden", !opts.text);
    const input = $("dialog-input");
    input.classList.toggle("hidden", !opts.input);
    input.value = opts.input ? opts.input.value || "" : "";
    input.placeholder = opts.input ? opts.input.placeholder || "" : "";
    const picker = $("dialog-folders");
    picker.classList.toggle("hidden", !opts.pickFolder);
    if (opts.pickFolder) {
      picker.replaceChildren(...state.folders.filter((f) => f.selectable).map((f) => {
        const b = el("button", "pick-folder");
        b.type = "button";
        b.dataset.folder = f.id;
        b.setAttribute("role", "option");
        b.setAttribute("aria-pressed", "false");
        b.style.paddingLeft = `${0.6 + Math.min(f.depth, 6) * 0.9}rem`;
        b.append(folderIcon(f.key), el("span", "truncate", f.name));
        if (opts.pickFolder.exclude && opts.pickFolder.exclude.has(f.id)) {
          b.disabled = true;
          b.classList.add("opacity-40");
          b.title = "The email is already in this folder";
        }
        return b;
      }));
    }
    $("dialog-ok").textContent = opts.okLabel || "OK";
    $("dialog-ok").className = opts.danger ? "inline-flex h-9 items-center rounded-md bg-red-600 px-3.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50" : "btn-primary";
    $("dialog-ok").disabled = !!opts.pickFolder;
    setDialogError(null);
    $("dialog").classList.add("open");
    (opts.input ? input : opts.pickFolder ? picker.querySelector("button:not(:disabled)") || $("dialog-cancel") : $("dialog-cancel")).focus();
    if (opts.input) input.select();
  }

  function closeDialog() {
    if (dialog.busy) return;
    $("dialog").classList.remove("open");
    dialog.onOk = null;
    if (dialog.returnFocus && document.contains(dialog.returnFocus)) dialog.returnFocus.focus();
  }

  function setDialogError(message) {
    $("dialog-error").textContent = message || "";
    $("dialog-error").classList.toggle("hidden", !message);
  }

  $("dialog-folders").addEventListener("click", (e) => {
    const b = e.target.closest(".pick-folder");
    if (!b || b.disabled) return;
    $("dialog-folders").querySelectorAll(".pick-folder").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    dialog.picked = b.dataset.folder;
    $("dialog-ok").disabled = false;
  });
  $("dialog-folders").addEventListener("dblclick", (e) => {
    const b = e.target.closest(".pick-folder");
    if (b && !b.disabled) $("dialog-form").requestSubmit();
  });
  $("dialog-cancel").addEventListener("click", closeDialog);
  $("dialog").addEventListener("click", (e) => {
    if (e.target === $("dialog")) closeDialog();
  });
  $("dialog").addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      closeDialog();
    }
  });
  $("dialog-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (dialog.busy || !dialog.onOk) return;
    const value = $("dialog-input").classList.contains("hidden") ? dialog.picked : $("dialog-input").value.trim();
    if (!$("dialog-input").classList.contains("hidden") && !value) {
      setDialogError("Enter a folder name.");
      return $("dialog-input").focus();
    }
    dialog.busy = true;
    $("dialog-ok").disabled = true;
    setDialogError(null);
    try {
      await dialog.onOk(value);
      dialog.busy = false;
      closeDialog();
    } catch (err) {
      dialog.busy = false;
      $("dialog-ok").disabled = false;
      if (CONNECTION_CODES.has(err.code)) handleError(err);
      setDialogError(err.message);
    }
  });

  // ---- Folder actions ----
  function newFolderDialog(parent) {
    openDialog({
      title: parent ? `New folder inside "${parent.name}"` : "New folder",
      input: { placeholder: "Folder name" },
      okLabel: "Create",
      onOk: async (name) => {
        await api("/api/folders", { method: "POST", body: JSON.stringify({ name, parent: parent ? parent.id : null }) });
        await loadFolders();
        toast(`Folder "${name}" created`);
      },
    });
  }

  function renameFolderDialog(f) {
    openDialog({
      title: `Rename "${f.name}"`,
      input: { value: f.name, placeholder: "Folder name" },
      okLabel: "Rename",
      onOk: async (name) => {
        const r = await api("/api/folders/rename", { method: "POST", body: JSON.stringify({ folder: f.id, name }) });
        const wasOpen = state.folder === f.id || state.folder.startsWith(f.id + ".") || state.folder.startsWith(f.id + "/");
        if (wasOpen) {
          state.folder = r.id;
          closeReading();
        }
        await loadFolders();
        if (wasOpen) loadMessages("reset");
        toast("Folder renamed");
      },
    });
  }

  function deleteFolderDialog(f) {
    const count = f.totalCount;
    openDialog({
      title: `Delete "${f.name}"?`,
      text: count
        ? `Its ${count.toLocaleString()} email${count === 1 ? "" : "s"} will be moved to Deleted Items, then the folder is removed (also in Outlook).`
        : "The folder is empty. It will be removed (also in Outlook).",
      okLabel: "Delete folder",
      danger: true,
      onOk: async () => {
        await api("/api/folders/delete", { method: "POST", body: JSON.stringify({ folder: f.id }) });
        if (state.folder === f.id) {
          state.folder = "INBOX";
          closeReading();
          loadMessages("reset");
        }
        await loadFolders();
        toast(`Folder "${f.name}" deleted`);
      },
    });
  }

  $("folder-new-btn").addEventListener("click", () => newFolderDialog(null));

  // ---- Moving emails ----
  async function moveMessages(ids, destination) {
    if (!ids.length) return;
    const dest = state.folders.find((f) => f.id === destination);
    const r = await api("/api/messages/move", { method: "POST", body: JSON.stringify({ ids, destination }) });
    const gone = new Set(ids);
    const openGone = reading.detail && gone.has(reading.detail.id);
    const firstIndex = state.messages.findIndex((m) => gone.has(m.id));
    state.messages = state.messages.filter((m) => !gone.has(m.id));
    state.total = Math.max(0, state.total - r.moved);
    ids.forEach((id) => state.checked.delete(id));
    renderList();
    loadFolders();
    if (openGone) {
      const next = state.messages[firstIndex] || state.messages[firstIndex - 1];
      if (next && ids.length === 1 && window.matchMedia("(min-width: 768px)").matches) openMessage(next.id);
      else closeReading();
    }
    const name = dest ? dest.name : "the folder";
    let msg = r.moved === 1 ? `Moved to ${name}` : `${r.moved.toLocaleString()} emails moved to ${name}`;
    if (r.skipped) msg += ` (${r.skipped} already moved or deleted)`;
    toast(msg);
  }

  function chooseFolderAndMove(ids) {
    if (!ids.length) return;
    openDialog({
      title: ids.length === 1 ? "Move email to…" : `Move ${ids.length} emails to…`,
      pickFolder: { exclude: new Set([state.folder]) },
      okLabel: "Move",
      onOk: (destination) => moveMessages(ids, destination),
    });
  }

  $("act-move").addEventListener("click", () => reading.detail && chooseFolderAndMove([reading.detail.id]));

  // ---- Drag emails onto a folder ----
  let dragIds = null;
  $("message-list").addEventListener("dragstart", (e) => {
    const row = e.target.closest(".msg");
    if (!row) return;
    const id = row.dataset.id;
    dragIds = state.checked.has(id) ? [...state.checked] : [id];
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragIds.length === 1 ? "1 email" : `${dragIds.length} emails`);
    dragIds.forEach((x) => {
      const r = document.querySelector(`.msg[data-id="${CSS.escape(x)}"]`);
      if (r) r.classList.add("dragging");
    });
  });
  $("message-list").addEventListener("dragend", () => {
    document.querySelectorAll(".msg.dragging").forEach((r) => r.classList.remove("dragging"));
    document.querySelectorAll(".drop-target").forEach((r) => r.classList.remove("drop-target"));
    dragIds = null;
  });
  $("folder-list").addEventListener("dragover", (e) => {
    const link = e.target.closest(".folder-link");
    if (!dragIds || !link) return;
    const f = state.folders.find((x) => x.id === link.dataset.folder);
    if (!f || !f.selectable || f.id === state.folder) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    document.querySelectorAll(".drop-target").forEach((r) => r !== link && r.classList.remove("drop-target"));
    link.classList.add("drop-target");
  });
  $("folder-list").addEventListener("dragleave", (e) => {
    const link = e.target.closest(".folder-link");
    if (link && !link.contains(e.relatedTarget)) link.classList.remove("drop-target");
  });
  $("folder-list").addEventListener("drop", async (e) => {
    const link = e.target.closest(".folder-link");
    if (!dragIds || !link) return;
    e.preventDefault();
    link.classList.remove("drop-target");
    const ids = dragIds;
    dragIds = null;
    try {
      await moveMessages(ids, link.dataset.folder);
    } catch (err) {
      if (!handleError(err)) toast(err.message, "error");
    }
  });

  // ------------------------------------------------------------------------
  // Categories
  // ------------------------------------------------------------------------

  const catsAvailable = () => BACKEND === "imap";

  async function loadCategories() {
    if (!catsAvailable()) {
      ["cat-filter", "act-categorize", "bulk-categorize"].forEach((id) => $(id).classList.add("hidden"));
      $("sort-select").closest("label").classList.add("hidden");
      return;
    }
    try {
      const data = await api("/api/categories");
      state.categories = data.categories;
      state.colors = data.colors;
      renderCategoryFilter();
      if (!$("cat-manager").classList.contains("open")) return;
      renderCatManager();
    } catch (err) {
      handleError(err);
    }
  }

  function renderCategoryFilter() {
    const sel = $("cat-filter");
    const opts = [new Option("Category", "")];
    state.categories.forEach((c) => opts.push(new Option(c.name, c.name)));
    sel.replaceChildren(...opts);
    if (state.category && !state.categories.some((c) => c.name === state.category)) {
      state.category = "";
      updateFilterUi();
      loadMessages("reset");
    }
    sel.value = state.category;
    sel.classList.toggle("active", !!state.category);
  }

  function renderReadingCategories(detail) {
    const box = $("r-categories");
    const cats = detail.categories || [];
    box.replaceChildren(...cats.map(categoryPill));
    box.classList.toggle("hidden", !cats.length);
    box.classList.toggle("flex", cats.length > 0);
  }

  // ---- Category menu (for the open email or the ticked ones) ----
  const catMenu = { ids: [], anchor: null };

  function openCatMenu(ids, anchor) {
    if (!ids.length) return;
    closeCatMenu();
    catMenu.ids = ids;
    catMenu.anchor = anchor;
    anchor.setAttribute("aria-expanded", "true");
    const byId = new Map(state.messages.map((m) => [m.id, m]));
    if (reading.detail) byId.set(reading.detail.id, reading.detail);
    const targets = ids.map((id) => byId.get(id)).filter(Boolean);
    const menu = $("cat-menu");
    const items = state.categories.map((c) => {
      const have = targets.filter((m) => (m.categories || []).includes(c.name)).length;
      const all = targets.length > 0 && have === targets.length;
      const b = el("button", `cat-item cat-${c.color}`);
      b.type = "button";
      b.setAttribute("role", "menuitemcheckbox");
      b.setAttribute("aria-checked", all ? "true" : have ? "mixed" : "false");
      b.dataset.cat = c.name;
      b.dataset.all = all ? "1" : "";
      b.append(el("span", "cat-dot"), el("span", "truncate", c.name), el("span", "check", all ? "✓" : have ? "–" : ""));
      return b;
    });
    const newBtn = el("button", "", "New category…");
    newBtn.type = "button";
    newBtn.dataset.action = "new";
    const manage = el("button", "", "Manage categories…");
    manage.type = "button";
    manage.dataset.action = "manage";
    menu.replaceChildren(...items, el("hr"), newBtn, manage);
    menu.classList.remove("hidden");
    const r = anchor.getBoundingClientRect();
    menu.style.top = `${Math.max(8, Math.min(r.bottom + 4, window.innerHeight - menu.offsetHeight - 8))}px`;
    menu.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - menu.offsetWidth - 8))}px`;
    menu.querySelector("button").focus();
  }

  function closeCatMenu() {
    $("cat-menu").classList.add("hidden");
    if (catMenu.anchor) catMenu.anchor.setAttribute("aria-expanded", "false");
    catMenu.anchor = null;
  }

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#cat-menu") && !e.target.closest("#act-categorize, #bulk-categorize")) closeCatMenu();
  });
  $("cat-menu").addEventListener("keydown", (e) => {
    const items = [...$("cat-menu").querySelectorAll("button")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    } else if (e.key === "Escape" || e.key === "Tab") {
      e.stopPropagation();
      const a = catMenu.anchor;
      closeCatMenu();
      if (a) a.focus();
    }
  });
  $("cat-menu").addEventListener("click", async (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const ids = catMenu.ids;
    closeCatMenu();
    if (b.dataset.action === "manage") return openCatManager();
    if (b.dataset.action === "new") {
      openDialog({
        title: "New category",
        input: { placeholder: "Category name" },
        okLabel: "Create and apply",
        onOk: async (name) => {
          const used = new Set(state.categories.map((c) => c.color));
          const color = state.colors.find((c) => !used.has(c)) || "gray";
          const cat = await api("/api/categories", { method: "POST", body: JSON.stringify({ name, color }) });
          await loadCategories();
          await runBulk(ids, "categorize", cat.name);
          toast(`Category "${cat.name}" added`);
        },
      });
      return;
    }
    const name = b.dataset.cat;
    const action = b.dataset.all ? "uncategorize" : "categorize";
    try {
      const r = await runBulk(ids, action, name);
      toast(action === "categorize" ? `${name} added${r.changed > 1 ? ` to ${r.changed} emails` : ""}` : `${name} removed${r.changed > 1 ? ` from ${r.changed} emails` : ""}`);
    } catch (err) {
      if (!handleError(err)) toast(err.message, "error");
    }
  });
  $("act-categorize").addEventListener("click", (e) => {
    if ($("cat-menu").classList.contains("hidden") && reading.detail) openCatMenu([reading.detail.id], e.currentTarget);
    else closeCatMenu();
  });
  $("bulk-categorize").addEventListener("click", (e) => {
    if ($("cat-menu").classList.contains("hidden")) openCatMenu([...state.checked], e.currentTarget);
    else closeCatMenu();
  });

  // ---- Manage categories ----
  function catManagerError(message) {
    $("cat-manager-error").textContent = message || "";
    $("cat-manager-error").classList.toggle("hidden", !message);
  }

  async function saveCategory(c, name, color) {
    catManagerError(null);
    try {
      await api("/api/categories/update", { method: "POST", body: JSON.stringify({ keyword: c.keyword, name, color }) });
      const oldName = c.name;
      await loadCategories();
      if (oldName !== name) {
        // Show the new name on emails already listed.
        for (const m of state.messages.concat(reading.detail ? [reading.detail] : [])) {
          m.categories = (m.categories || []).map((x) => (x === oldName ? name : x));
        }
        if (state.category === oldName) state.category = name;
        renderCategoryFilter();
      }
      renderList();
      if (reading.detail) renderReadingCategories(reading.detail);
      renderCatManager();
    } catch (err) {
      catManagerError(err.message);
      renderCatManager();
    }
  }

  function renderCatManager() {
    const list = $("cat-manager-list");
    list.replaceChildren(...state.categories.map((c) => {
      const li = el("li", "space-y-2 rounded-lg border border-slate-200 p-2 dark:border-slate-800");
      const top = el("div", "flex items-center gap-2");
      const name = el("input", "input h-8 min-w-0 flex-1");
      name.value = c.name;
      name.maxLength = 40;
      name.setAttribute("aria-label", `Name of category ${c.name}`);
      const commit = () => {
        const v = name.value.trim();
        if (v && v !== c.name) saveCategory(c, v, c.color);
        else name.value = c.name;
      };
      name.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        }
      });
      name.addEventListener("blur", commit);
      const del = el("button", "tool-btn !px-2 hover:!text-red-600", "Delete");
      del.type = "button";
      del.addEventListener("click", () => {
        top.replaceChildren(
          el("span", "flex-1 text-sm", `Delete "${c.name}"? Emails just stop showing it.`),
          (() => { const b = el("button", "btn-outline h-8", "Keep"); b.type = "button"; b.addEventListener("click", renderCatManager); return b; })(),
          (() => {
            const b = el("button", "inline-flex h-8 items-center rounded-md bg-red-600 px-3 text-sm font-medium text-white hover:bg-red-700", "Delete");
            b.type = "button";
            b.addEventListener("click", async () => {
              try {
                await api("/api/categories/delete", { method: "POST", body: JSON.stringify({ keyword: c.keyword }) });
                for (const m of state.messages.concat(reading.detail ? [reading.detail] : [])) {
                  m.categories = (m.categories || []).filter((x) => x !== c.name);
                }
                await loadCategories();
                renderList();
                if (reading.detail) renderReadingCategories(reading.detail);
                renderCatManager();
              } catch (err) {
                catManagerError(err.message);
              }
            });
            return b;
          })(),
        );
      });
      top.append(el("span", `cat-dot cat-${c.color}`), name, del);
      const swatches = el("div", "flex flex-wrap gap-1.5 pl-5");
      state.colors.forEach((color) => {
        const s = el("button", `swatch cat-${color}`);
        s.type = "button";
        s.setAttribute("aria-label", `Colour ${color}`);
        s.setAttribute("aria-pressed", String(color === c.color));
        s.title = color;
        s.addEventListener("click", () => color !== c.color && saveCategory(c, c.name, color));
        swatches.append(s);
      });
      li.append(top, swatches);
      return li;
    }));
    if (!state.categories.length) list.replaceChildren(el("li", "py-6 text-center text-sm text-slate-500", "No categories yet. Add one below."));
  }

  function openCatManager() {
    catManagerError(null);
    renderCatManager();
    $("cat-manager").classList.add("open");
    $("cat-new-name").focus();
  }
  function closeCatManager() {
    $("cat-manager").classList.remove("open");
  }
  $("cat-manager-close").addEventListener("click", closeCatManager);
  $("cat-manager").addEventListener("click", (e) => {
    if (e.target === $("cat-manager")) closeCatManager();
  });
  $("cat-manager").addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      closeCatManager();
    }
  });
  $("cat-new-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("cat-new-name").value.trim();
    if (!name) return $("cat-new-name").focus();
    catManagerError(null);
    const used = new Set(state.categories.map((c) => c.color));
    try {
      await api("/api/categories", { method: "POST", body: JSON.stringify({ name, color: state.colors.find((c) => !used.has(c)) || "gray" }) });
      $("cat-new-name").value = "";
      await loadCategories();
      renderCatManager();
    } catch (err) {
      catManagerError(err.message);
    }
  });

  function refreshAll(mode = "refresh") {
    loadMessages(mode);
    loadFolders();
  }

  // ------------------------------------------------------------------------
  // Events
  // ------------------------------------------------------------------------

  // Search
  $("search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    state.query = $("search-input").value.trim();
    $("search-clear").classList.toggle("hidden", !$("search-input").value);
    loadMessages("reset");
  });
  $("search-input").addEventListener("input", () => {
    $("search-clear").classList.toggle("hidden", !$("search-input").value);
  });
  $("search-clear").addEventListener("click", () => {
    $("search-input").value = "";
    $("search-clear").classList.add("hidden");
    if (state.query) {
      state.query = "";
      loadMessages("reset");
    }
  });

  // Filter chips
  document.querySelectorAll(".chip[data-filter]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const key = chip.dataset.filter;
      state.filters[key] = !state.filters[key];
      chip.setAttribute("aria-pressed", String(state.filters[key]));
      updateFilterUi();
      loadMessages("reset");
    });
  });

  // Date range popover
  function toggleDatePanel(open) {
    const panel = $("date-panel");
    const show = open ?? panel.classList.contains("hidden");
    panel.classList.toggle("hidden", !show);
    $("date-btn").setAttribute("aria-expanded", String(show));
    if (show) {
      $("date-from").value = state.filters.from;
      $("date-to").value = state.filters.to;
    }
  }
  $("date-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleDatePanel();
  });
  $("date-panel").addEventListener("click", (e) => e.stopPropagation());
  document.addEventListener("click", () => toggleDatePanel(false));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      toggleDatePanel(false);
      closeSidebar();
    }
  });
  $("date-apply").addEventListener("click", () => {
    let from = $("date-from").value;
    let to = $("date-to").value;
    if (from && to && from > to) [from, to] = [to, from];
    state.filters.from = from;
    state.filters.to = to;
    toggleDatePanel(false);
    updateFilterUi();
    loadMessages("reset");
  });
  $("date-clear").addEventListener("click", () => {
    state.filters.from = "";
    state.filters.to = "";
    toggleDatePanel(false);
    updateFilterUi();
    loadMessages("reset");
  });

  $("filters-clear").addEventListener("click", () => {
    state.filters = { unread: false, flagged: false, attachments: false, from: "", to: "" };
    state.category = "";
    $("cat-filter").value = "";
    $("cat-filter").classList.remove("active");
    document.querySelectorAll(".chip[data-filter]").forEach((c) => c.setAttribute("aria-pressed", "false"));
    updateFilterUi();
    loadMessages("reset");
  });

  function updateFilterUi() {
    const f = state.filters;
    const hasDate = !!(f.from || f.to);
    $("date-btn").classList.toggle("active", hasDate);
    $("date-btn").textContent = hasDate ? `${f.from ? shortDay(f.from) : "…"} – ${f.to ? shortDay(f.to) : "…"}` : "Date";
    $("filters-clear").classList.toggle("hidden", !filtersActive());
  }

  // ------------------------------------------------------------------------
  // Toast
  // ------------------------------------------------------------------------

  let toastTimer = null;
  function toast(message, kind = "info") {
    const box = $("toast-box");
    box.textContent = message;
    box.className =
      "pointer-events-auto flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm shadow-lg " +
      (kind === "error"
        ? "bg-red-600 text-white"
        : "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => box.classList.add("hidden"), kind === "error" ? 6000 : 3000);
  }

  // ------------------------------------------------------------------------
  // Reading pane
  // ------------------------------------------------------------------------

  const reading = { detail: null, showRemote: false, seq: 0 };

  function showReading(which) {
    for (const id of ["reading-empty", "reading-loading", "reading-error", "reading-content"]) {
      const node = $(id);
      const on = id === which;
      node.classList.toggle("hidden", !on);
      node.classList.toggle("flex", on && id !== "reading-loading" && id !== "reading-error");
    }
    if (which === "reading-loading" || which === "reading-error") $(which).classList.remove("hidden");
  }

  function markSelectedRow(id) {
    document.querySelectorAll(".msg.selected").forEach((n) => {
      n.classList.remove("selected");
      n.removeAttribute("aria-current");
    });
    if (!id) return;
    const row = document.querySelector(`.msg[data-id="${CSS.escape(id)}"]`);
    if (row) {
      row.classList.add("selected");
      row.setAttribute("aria-current", "true");
    }
  }

  function updateMessage(id, patch) {
    const m = state.messages.find((x) => x.id === id);
    if (m) Object.assign(m, patch);
    const row = document.querySelector(`.msg[data-id="${CSS.escape(id)}"]`);
    if (row && m) row.parentElement.replaceWith(messageRow(m));
  }

  function closeReading() {
    reading.seq++;
    reading.detail = null;
    state.selectedId = null;
    document.body.classList.remove("reading");
    markSelectedRow(null);
    $("r-frame").removeAttribute("srcdoc");
    showReading("reading-empty");
  }

  function initials(name) {
    const parts = (name || "").replace(/[<>()"]/g, "").trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return "?";
    return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
  }

  function personList(people) {
    return people.map((p) => (p.address && p.address !== p.name ? `${p.name} <${p.address}>` : p.name)).join("; ");
  }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  }

  function attachmentUrl(id, index, inline) {
    return `/api/messages/${encodeURIComponent(id)}/attachments/${index}${inline ? "?inline=1" : ""}`;
  }

  const REMOTE_CONTENT = /(<img[^>]+src\s*=\s*["']?\s*https?:)|(url\(\s*["']?\s*https?:)|(<link[^>]+href\s*=\s*["']?\s*https?:)/i;

  /** Wraps the email HTML in a document with a strict Content-Security-Policy. */
  function buildSrcdoc(detail, allowRemote) {
    // Point cid: references (inline images) at our attachment endpoint.
    const byCid = new Map(detail.attachments.filter((a) => a.contentId).map((a) => [a.contentId.toLowerCase(), a]));
    const html = detail.body.replace(/cid:([^"'\s)>]+)/gi, (match, cid) => {
      const att = byCid.get(cid.toLowerCase());
      return att ? attachmentUrl(detail.id, att.index, true) : match;
    });
    return wrapEmailHtml(html, allowRemote);
  }

  function wrapEmailHtml(html, allowRemote) {
    const origin = location.origin;
    const csp = [
      "default-src 'none'",
      `img-src ${origin} data:${allowRemote ? " https: http:" : ""}`,
      `style-src 'unsafe-inline'${allowRemote ? " https: http:" : ""}`,
      `font-src data:${allowRemote ? " https: http:" : ""}`,
    ].join("; ");
    return (
      '<!doctype html><html><head><meta charset="utf-8">' +
      `<meta http-equiv="Content-Security-Policy" content="${csp}">` +
      '<base target="_blank">' +
      "<style>html,body{margin:0}body{padding:16px 20px;font:14px/1.5 'Segoe UI',system-ui,sans-serif;color:#1e293b;background:#fff;overflow-wrap:anywhere}" +
      "img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap}</style>" +
      "</head><body>" + html + "</body></html>"
    );
  }

  function renderBody(detail) {
    const frame = $("r-frame");
    const text = $("r-text");
    if (detail.bodyType === "html") {
      text.classList.add("hidden");
      frame.classList.remove("hidden");
      frame.srcdoc = buildSrcdoc(detail, reading.showRemote);
      const hasRemote = REMOTE_CONTENT.test(detail.body);
      $("r-remote").classList.toggle("hidden", !hasRemote || reading.showRemote);
      $("r-remote").classList.toggle("flex", hasRemote && !reading.showRemote);
    } else {
      frame.classList.add("hidden");
      frame.removeAttribute("srcdoc");
      text.classList.remove("hidden");
      text.textContent = detail.body || "(This email has no text.)";
      $("r-remote").classList.add("hidden");
    }
  }

  function renderActions(detail) {
    $("act-read-label").textContent = detail.isRead ? "Mark unread" : "Mark read";
    $("act-read").title = detail.isRead ? "Mark as unread" : "Mark as read";
    $("act-flag-label").textContent = detail.flagged ? "Unflag" : "Flag";
    $("act-flag").classList.toggle("active", detail.flagged);
    $("r-flagged").classList.toggle("hidden", !detail.flagged);
    $("r-flagged").classList.toggle("flex", detail.flagged);
    $("act-edit-draft").classList.toggle("hidden", !detail.isDraft);
  }

  function editDraft() {
    const d = reading.detail;
    if (!d || !d.isDraft) return;
    openCompose({
      mode: "new",
      draftId: d.id,
      to: d.recipients.to,
      cc: d.recipients.cc,
      subject: d.subject === "(no subject)" ? "" : d.subject,
      attachments: d.attachments.filter((a) => !a.inline).map((a) => ({ id: a.id, name: a.name, size: a.size })),
    });
    $("c-bcc").value = joinPeople(d.recipients.bcc || []);
    if ($("c-bcc").value) showCcBcc(true);
    $("c-body").value = d.draftText || "";
  }

  function renderDetail(detail) {
    hideReadingTask();
    $("r-subject").textContent = detail.subject;
    const fromName = detail.from ? detail.from.name : "(unknown sender)";
    $("r-avatar").textContent = initials(fromName);
    $("r-from-name").textContent = fromName;
    $("r-from-address").textContent = detail.from && detail.from.address && detail.from.address !== fromName ? `<${detail.from.address}>` : "";
    const to = detail.recipients.to;
    $("r-to").textContent = to.length ? "To: " + personList(to) : "";
    $("r-to").title = $("r-to").textContent;
    const cc = detail.recipients.cc;
    $("r-cc").textContent = cc.length ? "Cc: " + personList(cc) : "";
    $("r-cc").title = $("r-cc").textContent;
    $("r-cc").classList.toggle("hidden", !cc.length);
    const when = detail.receivedDateTime || detail.sentDateTime;
    $("r-date").textContent = when ? new Date(when).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "";
    $("r-date").dateTime = when || "";

    const files = detail.attachments.filter((a) => !a.inline);
    const box = $("r-attachments");
    box.replaceChildren(
      ...files.map((a) => {
        const link = el("a", "attachment");
        link.href = attachmentUrl(detail.id, a.index, false);
        link.setAttribute("download", a.name);
        link.title = `Download ${a.name}`;
        link.append(icon("paperclip", "h-3.5 w-3.5 shrink-0 text-slate-400", "Attachment"));
        link.append(el("span", "truncate", a.name), el("span", "shrink-0 text-slate-500", formatSize(a.size)));
        return link;
      }),
    );
    box.classList.toggle("hidden", !files.length);
    box.classList.toggle("flex", files.length > 0);

    renderActions(detail);
    renderReadingCategories(detail);
    renderBody(detail);
  }

  async function openMessage(id) {
    const seq = ++reading.seq;
    state.selectedId = id;
    reading.showRemote = false;
    markSelectedRow(id);
    document.body.classList.add("reading");
    showReading("reading-loading");

    try {
      const detail = await api(`/api/messages/${encodeURIComponent(id)}`);
      if (seq !== reading.seq) return;
      reading.detail = detail;
      renderDetail(detail);
      showReading("reading-content");

      // Like Outlook: opening an email marks it as read.
      if (!detail.isRead) setRead(true, { quiet: true });
    } catch (err) {
      if (seq !== reading.seq) return;
      if (err.code === "not_found") {
        state.messages = state.messages.filter((m) => m.id !== id);
        renderList();
      }
      if (!handleError(err)) {
        $("reading-error-text").textContent = err.message;
        showReading("reading-error");
      } else {
        closeReading();
      }
    }
  }

  async function setRead(read, { quiet = false } = {}) {
    const d = reading.detail;
    if (!d) return;
    const before = d.isRead;
    d.isRead = read;
    renderActions(d);
    updateMessage(d.id, { isRead: read });
    try {
      await api(`/api/messages/${encodeURIComponent(d.id)}/read`, { method: "POST", body: JSON.stringify({ read }) });
      loadFolders();
      if (!quiet) toast(read ? "Marked as read" : "Marked as unread");
    } catch (err) {
      d.isRead = before;
      renderActions(d);
      updateMessage(d.id, { isRead: before });
      if (!handleError(err)) toast(err.message, "error");
    }
  }

  async function setFlag(flagged) {
    const d = reading.detail;
    if (!d) return;
    const before = d.flagged;
    d.flagged = flagged;
    renderActions(d);
    updateMessage(d.id, { flagged });
    try {
      const r = await api(`/api/messages/${encodeURIComponent(d.id)}/flag`, { method: "POST", body: JSON.stringify({ flagged }) });
      if (r.flagged !== flagged) throw new ApiError(400, "bad_request", "Outlook didn't apply the flag to this item.");
      toast(flagged ? "Flagged" : "Flag cleared");
    } catch (err) {
      d.flagged = before;
      renderActions(d);
      updateMessage(d.id, { flagged: before });
      if (!handleError(err)) toast(err.message, "error");
    }
  }

  async function doDelete(d, permanent) {
    await api(`/api/messages/${encodeURIComponent(d.id)}`, { method: "DELETE" });
    const index = state.messages.findIndex((m) => m.id === d.id);
    state.messages = state.messages.filter((m) => m.id !== d.id);
    state.total = Math.max(0, state.total - 1);
    renderList();
    loadFolders();
    toast(permanent ? "Deleted permanently" : "Moved to Deleted Items");
    // Open the next email (like Outlook), or clear the pane on mobile / at the end of the list.
    const next = state.messages[index] || state.messages[index - 1];
    if (next && window.matchMedia("(min-width: 768px)").matches) openMessage(next.id);
    else closeReading();
  }

  async function deleteCurrent() {
    const d = reading.detail;
    if (!d) return;
    const f = currentFolder();
    if (f && f.key === "deleteditems") {
      // Already in Deleted Items: this removes it for good, so ask first.
      openDialog({
        title: "Delete permanently?",
        text: "This email is already in Deleted Items. Deleting it again removes it for good, also from Outlook.",
        okLabel: "Delete permanently",
        danger: true,
        onOk: () => doDelete(d, true),
      });
      return;
    }
    $("act-delete").disabled = true;
    try {
      await doDelete(d, false);
    } catch (err) {
      if (!handleError(err)) toast(err.message, "error");
    } finally {
      $("act-delete").disabled = false;
    }
  }

  $("message-list").addEventListener("click", (e) => {
    const btn = e.target.closest(".msg");
    if (btn) openMessage(btn.dataset.id);
  });
  $("act-read").addEventListener("click", () => reading.detail && setRead(!reading.detail.isRead));
  $("act-flag").addEventListener("click", () => reading.detail && setFlag(!reading.detail.flagged));
  $("act-delete").addEventListener("click", deleteCurrent);
  $("act-edit-draft").addEventListener("click", editDraft);
  $("r-remote-show").addEventListener("click", () => {
    reading.showRemote = true;
    if (reading.detail) renderBody(reading.detail);
  });
  document.querySelectorAll(".back-btn").forEach((b) => b.addEventListener("click", closeReading));

  // ------------------------------------------------------------------------
  // Compose: new / reply / reply all / forward / drafts
  // ------------------------------------------------------------------------

  const MAX_TOTAL_BYTES = 25 * 1024 * 1024; // keep in line with typical Exchange limits
  const TITLES = { new: "New message", reply: "Reply", replyall: "Reply all", forward: "Forward" };

  const compose = {
    mode: "new",
    sourceId: null,
    draftId: null,
    existing: [], // attachments already on the item (forward / saved draft): {id?, name, size}
    removed: [], // keys (id, or name for classic Outlook) of existing attachments the user removed
    autoDraft: false, // set if the backend created a reply/forward draft up front; deleted if never saved
    quotedHtml: "",
    files: [], // File objects chosen on this computer, not yet uploaded
    dirty: false,
    busy: false,
    confirmYes: null,
  };

  const splitRecipients = (value) => value.split(/[;\n]/).map((s) => s.trim()).filter(Boolean);
  const joinPeople = (people) => people.map((p) => p.address || p.name).filter(Boolean).join("; ");

  function composeOpen() {
    return $("compose").classList.contains("open");
  }

  function setComposeError(message) {
    $("c-error").textContent = message || "";
    $("c-error").classList.toggle("hidden", !message);
  }

  function hideConfirm() {
    compose.confirmYes = null;
    $("c-confirm").classList.add("hidden");
    $("c-confirm").classList.remove("flex");
  }

  function showConfirm(text, yesLabel, onYes) {
    compose.confirmYes = onYes;
    $("c-confirm-text").textContent = text;
    $("c-confirm-yes").textContent = yesLabel;
    $("c-confirm").classList.remove("hidden");
    $("c-confirm").classList.add("flex");
    $("c-confirm-no").focus();
  }

  function setComposeBusy(busy, label) {
    compose.busy = busy;
    for (const id of ["c-send", "c-draft", "c-discard", "c-files"]) $(id).disabled = busy;
    if (label !== undefined) $("compose-status").textContent = label;
  }

  const attKey = (a) => a.id || a.name;

  function totalAttachmentBytes() {
    const existing = compose.existing.filter((a) => !compose.removed.includes(attKey(a))).reduce((n, a) => n + a.size, 0);
    return existing + compose.files.reduce((n, f) => n + f.size, 0);
  }

  function renderComposeAttachments() {
    const box = $("c-attachments");
    const chips = [];
    const chip = (name, size, pending, onRemove) => {
      const c = el("span", "attachment" + (pending ? " pending" : ""));
      c.title = pending ? `${name} (will be attached when you send or save)` : name;
      c.append(icon("paperclip", "h-3.5 w-3.5 shrink-0 text-slate-400", "Attachment"));
      c.append(el("span", "truncate", name), el("span", "shrink-0 text-slate-500", formatSize(size)));
      const x = el("button", "ml-1 shrink-0 rounded px-1 text-slate-400 hover:text-red-600", "×");
      x.type = "button";
      x.setAttribute("aria-label", `Remove ${name}`);
      x.addEventListener("click", onRemove);
      c.append(x);
      return c;
    };
    compose.existing
      .filter((a) => !compose.removed.includes(attKey(a)))
      .forEach((a) => chips.push(chip(a.name, a.size, false, () => {
        compose.removed.push(attKey(a));
        compose.dirty = true;
        renderComposeAttachments();
      })));
    compose.files.forEach((f, i) => chips.push(chip(f.name, f.size, true, () => {
      compose.files.splice(i, 1);
      compose.dirty = true;
      renderComposeAttachments();
    })));
    box.replaceChildren(...chips);
    box.classList.toggle("hidden", !chips.length);
    box.classList.toggle("flex", chips.length > 0);
  }

  function showCcBcc(show) {
    $("c-cc-row").classList.toggle("hidden", !show);
    $("c-bcc-row").classList.toggle("hidden", !show);
    $("c-show-ccbcc").classList.toggle("hidden", show);
  }

  function setQuotedOpen(open) {
    $("c-quoted").classList.toggle("hidden", !open);
    $("c-quoted-chevron").style.transform = open ? "rotate(90deg)" : "";
    $("c-quoted-label").textContent = open ? "Hide original message" : "Show original message";
  }

  /** prefill: {mode, sourceId, to, cc, subject, quotedHtml, attachments} */
  function openCompose(prefill = {}) {
    Object.assign(compose, {
      mode: prefill.mode || "new",
      sourceId: prefill.sourceId || null,
      draftId: prefill.draftId || null,
      autoDraft: !!prefill.autoDraft,
      quotedHtml: prefill.quotedHtml || "",
      existing: prefill.attachments || [],
      removed: [],
      files: [],
      dirty: !!prefill.body,
      busy: false,
      subjectWarned: false,
      taskPeople: (prefill.task && prefill.task.people) || [], // names from Write for me, for Tasks > Given
    });
    $("compose-title").textContent = prefill.title || TITLES[compose.mode];
    $("compose-status").textContent = "";
    $("c-to").value = joinPeople(prefill.to || []);
    $("c-cc").value = joinPeople(prefill.cc || []);
    $("c-bcc").value = "";
    $("c-subject").value = prefill.subject || "";
    compose.autoSubject = prefill.body ? prefill.subject || "" : null; // written-for-you subjects may be refreshed
    $("c-body").value = prefill.body || "";
    polish.undo = null;
    setPolishLabel();
    $("c-files").value = "";
    showCcBcc(!!$("c-cc").value);
    setComposeError(null);
    hideConfirm();
    setComposeBusy(false, prefill.status || "");
    renderComposeAttachments();
    setComposeTask(!!prefill.task, prefill.task || {});

    const quoted = prefill.quotedHtml || "";
    $("c-quoted-wrap").classList.toggle("hidden", !quoted);
    setQuotedOpen(false);
    if (quoted) $("c-quoted").srcdoc = wrapEmailHtml(quoted, false);
    else $("c-quoted").removeAttribute("srcdoc");

    $("compose").classList.add("open");
    document.body.style.overflow = "hidden";
    if (prefill.body && $("c-to").value) {
      $("c-body").focus();
      $("c-body").setSelectionRange(0, 0);
      $("c-body").scrollTop = 0;
    } else {
      (compose.mode === "new" || compose.mode === "forward" ? $("c-to") : $("c-body")).focus();
    }
  }

  function closeCompose() {
    // A reply/forward draft the backend created up front but the user never saved: remove it for good.
    if (compose.autoDraft && compose.draftId) {
      api(`/api/messages/${encodeURIComponent(compose.draftId)}?permanent=1`, { method: "DELETE" }).catch(() => {});
    }
    compose.autoDraft = false;
    $("compose").classList.remove("open");
    $("c-quoted").removeAttribute("srcdoc");
    document.body.style.overflow = "";
    hideConfirm();
  }

  function requestClose() {
    if (compose.busy) return;
    if (compose.dirty) {
      showConfirm(
        compose.draftId && !compose.autoDraft
          ? "Close without saving your latest changes? The saved draft stays in Drafts."
          : "Close without saving? This message will be lost.",
        "Close",
        closeCompose,
      );
    } else {
      closeCompose();
    }
  }

  function buildComposeForm(action) {
    const fd = new FormData();
    fd.append("action", action);
    fd.append("mode", compose.mode);
    if (compose.sourceId) fd.append("sourceId", compose.sourceId);
    if (compose.draftId) fd.append("draftId", compose.draftId);
    fd.append("to", splitRecipients($("c-to").value).join(";"));
    fd.append("cc", splitRecipients($("c-cc").value).join(";"));
    fd.append("bcc", splitRecipients($("c-bcc").value).join(";"));
    fd.append("subject", $("c-subject").value);
    fd.append("body", $("c-body").value);
    fd.append("removeAttachments", JSON.stringify(compose.removed));
    if (compose.mode !== "new" && compose.quotedHtml) fd.append("quotedHtml", compose.quotedHtml);
    compose.files.forEach((f) => fd.append("files", f, f.name));
    const task = composeTaskPayload();
    if (task) fd.append("task", JSON.stringify({ ...task, subject: $("c-subject").value }));
    return fd;
  }

  // "Send as task": any email (new, reply, forward) can go out as a task and is saved in Tasks > Given.
  function setComposeTask(on, t = {}) {
    compose.taskOn = !!on && !!$("c-task-row"); // the page may be older than this script
    if (!$("c-task-row")) return;
    $("c-task-toggle").setAttribute("aria-pressed", String(compose.taskOn));
    $("c-task-row").classList.toggle("hidden", !compose.taskOn);
    if (!compose.taskOn) return;
    const subjectTitle = $("c-subject").value.replace(/^\s*(?:(?:re|fw|fwd)\s*:\s*)*(?:task\s*:\s*)?/i, "").replace(/\s+[–-]\s+due\b.*$/i, "").trim();
    $("c-task-title").value = t.title || $("c-task-title").value || subjectTitle;
    $("c-task-due").value = t.due || $("c-task-due").value || "";
    $("c-task-high").checked = t.importance === "high" || (!t.title && $("c-task-high").checked);
  }

  const SMALL = new Set(["a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with", "from", "as"]);

  /** "stock report for october" -> "Stock Report for October" (only when typed all in lower case). */
  function tidySubject(subject) {
    const s = (subject || "").replace(/\s+/g, " ").trim();
    if (!s || s !== s.toLowerCase() || !/[a-z]/.test(s)) return s;
    return s.split(" ").map((w, i) => (i && SMALL.has(w) ? w : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
  }

  /** "check the generator diesel" -> "Check the Generator Diesel" (words already in capitals are kept). */
  function titleCase(text) {
    return (text || "").replace(/\s+/g, " ").trim().split(" ")
      .map((w, i) => (i && SMALL.has(w.toLowerCase()) ? w.toLowerCase() : w.charAt(0).toUpperCase() + w.slice(1)))
      .join(" ");
  }

  /** "2026-11-20" -> "Due Fri 20 Nov" / "Due Today" / "Due Tomorrow". */
  function dueLabel(iso) {
    const d = new Date(iso + "T00:00");
    const days = Math.round((d - localToday()) / 86_400_000);
    if (days === 0) return "Due Today";
    if (days === 1) return "Due Tomorrow";
    const opts = { weekday: "short", day: "numeric", month: "short" };
    if (d.getFullYear() !== new Date().getFullYear()) opts.year = "numeric";
    return "Due " + d.toLocaleDateString("en-GB", opts).replace(",", "");
  }

  async function suggestSubject(text) {
    if (!text || !text.trim()) return "";
    try {
      const r = await api("/api/subject", { method: "POST", body: JSON.stringify({ text }) });
      return (r && r.subject) || "";
    } catch {
      return "";
    }
  }

  function composeTaskPayload() {
    if (!compose.taskOn) return null;
    return {
      title: $("c-task-title").value.trim(),
      due: $("c-task-due").value || null,
      importance: $("c-task-high").checked ? "high" : "normal",
      people: compose.taskPeople,
    };
  }

  /** Before sending a task: "Task:" subject, and Task / Due date / Priority lines in the body if not there yet. */
  function applyTaskToEmail(task) {
    let subject = tidySubject($("c-subject").value.trim());
    const reply = (subject.match(/^(?:(?:re|fw|fwd)\s*:\s*)+/i) || [""])[0];
    let rest = subject.slice(reply.length).trim();
    if (!/\btask\b/i.test(rest)) rest = "Task: " + (rest ? tidySubject(rest) : titleCase(task.title));
    if (task.due && !/\bdue\b/i.test(rest)) rest += " – " + dueLabel(task.due);
    $("c-subject").value = reply + rest;
    const body = $("c-body").value;
    if (/^\s*task\s*:/im.test(body)) return; // Write for me already wrote the task details
    const lines = [`Task: ${task.title}`];
    if (task.due) {
      lines.push("Due date: " + new Date(task.due + "T00:00").toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }));
    }
    if (task.importance === "high") lines.push("Priority: High");
    const block = lines.join("\n");
    // Put it before the sign-off ("Best regards," ...) if there is one, otherwise at the end.
    const m = body.match(/\n[ \t]*(?:best regards|kind regards|warm regards|regards|sincerely|thanks (?:and|&) regards|thank you(?: and regards)?|thanks)\b[^\n]*\n?[\s\S]*$/i);
    $("c-body").value = m
      ? body.slice(0, m.index).replace(/\s+$/, "") + "\n\n" + block + "\n" + body.slice(m.index)
      : body.replace(/\s+$/, "") + (body.trim() ? "\n\n" : "") + block;
  }

  async function submitCompose(action) {
    if (compose.busy) return;
    hideConfirm();
    setComposeError(null);

    const recipients = [$("c-to").value, $("c-cc").value, $("c-bcc").value].flatMap(splitRecipients);
    if (action === "send" && !recipients.length) {
      setComposeError("Add at least one recipient.");
      $("c-to").focus();
      return;
    }
    if (totalAttachmentBytes() > MAX_TOTAL_BYTES) {
      setComposeError(`Attachments are too large (${formatSize(totalAttachmentBytes())}). The total must be under 25 MB.`);
      return;
    }
    if (action === "send" && !$("c-subject").value.trim() && !compose.taskOn) {
      // Outlook-style nudge rather than a hard block, with a subject written from the message.
      if (!compose.subjectWarned) {
        compose.subjectWarned = true;
        const suggested = await suggestSubject($("c-body").value);
        if (suggested) {
          $("c-subject").value = suggested;
          compose.dirty = true;
          setComposeError(`Subject added: “${suggested}”. Change it if you like, then click Send again.`);
          $("c-subject").focus();
        } else {
          setComposeError("This message has no subject. Click Send again to send it anyway.");
        }
        return;
      }
    }
    if (action === "send") $("c-subject").value = tidySubject($("c-subject").value);

    const task = composeTaskPayload();
    if (task && !task.title) {
      setComposeError("Write what the task is (the Task box under the subject), or turn off Send as task.");
      $("c-task-title").focus();
      return;
    }
    if (task && action === "send") applyTaskToEmail(task);

    setComposeBusy(true, action === "send" ? "Sending…" : "Saving…");
    try {
      const result = await api("/api/compose", { method: "POST", body: buildComposeForm(action) });
      // Drafts and Sent Items change on the server: refresh the list/counts, and close a draft
      // shown in the reading pane (saving replaces it with a new copy).
      if (reading.detail && reading.detail.isDraft && reading.detail.id === compose.draftId) closeReading();
      const f = currentFolder();
      if (f && (f.key === "drafts" || f.key === "sentitems")) loadMessages("refresh");
      loadFolders();
      if (result.status === "sent") {
        if (result.task) {
          tasksState.tasks.unshift(result.task);
          renderTasks();
          toast("Task sent and added to Tasks › Given");
        } else toast(compose.taskOn ? "Message sent (the task could not be saved)" : "Message sent");
        compose.subjectWarned = false;
        compose.autoDraft = false; // the draft became the sent message
        closeCompose();
        return;
      }
      // Saved as draft: keep editing the same draft from now on.
      compose.draftId = result.draftId;
      compose.autoDraft = false;
      compose.existing = result.attachments || [];
      compose.removed = [];
      compose.files = [];
      compose.dirty = false;
      $("c-files").value = "";
      renderComposeAttachments();
      toast("Draft saved");
      setComposeBusy(false, "Draft saved " + new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" }));
    } catch (err) {
      setComposeBusy(false, "");
      if (err.status === 413) setComposeError(err.message);
      else if (CONNECTION_CODES.has(err.code)) {
        handleError(err);
        setComposeError(err.message + " Your message is still here; nothing was sent.");
      } else setComposeError(err.message);
      toast(action === "send" ? "Message not sent" : "Draft not saved", "error");
    }
  }

  async function discardCompose() {
    if (compose.busy) return;
    const savedDraft = compose.draftId && !compose.autoDraft;
    if (!savedDraft && !compose.dirty) {
      closeCompose();
      return;
    }
    showConfirm(
      savedDraft ? "Delete this draft? It will be moved to Deleted Items." : "Discard this message?",
      "Discard",
      async () => {
        if (savedDraft) {
          setComposeBusy(true, "Deleting draft…");
          try {
            await api(`/api/messages/${encodeURIComponent(compose.draftId)}`, { method: "DELETE" });
          } catch (err) {
            setComposeBusy(false, "");
            setComposeError(err.message);
            return;
          }
        }
        closeCompose();
        toast(savedDraft ? "Draft deleted" : "Message discarded");
      },
    );
  }

  async function startResponse(mode, button) {
    const d = reading.detail;
    if (!d) return;
    button.disabled = true;
    try {
      const prefill = await api(`/api/messages/${encodeURIComponent(d.id)}/compose?mode=${mode}`);
      openCompose(prefill);
    } catch (err) {
      if (!handleError(err)) toast(err.message, "error");
    } finally {
      button.disabled = false;
    }
  }

  $("new-mail-btn").addEventListener("click", () => openCompose({ mode: "new" }));
  $("act-reply").addEventListener("click", (e) => startResponse("reply", e.currentTarget));
  $("act-replyall").addEventListener("click", (e) => startResponse("replyall", e.currentTarget));
  $("act-forward").addEventListener("click", (e) => startResponse("forward", e.currentTarget));

  $("compose-form").addEventListener("submit", (e) => {
    e.preventDefault();
    submitCompose("send");
  });
  $("compose-form").addEventListener("input", (e) => {
    if (e.target.id !== "c-files") compose.dirty = true;
    if (e.target.id === "c-subject") compose.subjectWarned = false;
  });
  $("c-draft").addEventListener("click", () => submitCompose("draft"));
  if ($("c-task-toggle")) {
    $("c-task-toggle").addEventListener("click", () => {
      setComposeTask(!compose.taskOn);
      compose.dirty = true;
      if (compose.taskOn && !$("c-task-title").value) $("c-task-title").focus();
    });
  }
  $("c-discard").addEventListener("click", discardCompose);
  $("compose-close").addEventListener("click", requestClose);
  $("c-show-ccbcc").addEventListener("click", () => {
    showCcBcc(true);
    $("c-cc").focus();
  });
  $("c-quoted-toggle").addEventListener("click", () => setQuotedOpen($("c-quoted").classList.contains("hidden")));
  $("c-files").addEventListener("change", () => {
    compose.files.push(...$("c-files").files);
    $("c-files").value = "";
    compose.dirty = true;
    renderComposeAttachments();
    if (totalAttachmentBytes() > MAX_TOTAL_BYTES) setComposeError(`Attachments total ${formatSize(totalAttachmentBytes())}; the limit is 25 MB.`);
  });
  $("c-confirm-no").addEventListener("click", hideConfirm);
  $("c-confirm-yes").addEventListener("click", () => {
    const fn = compose.confirmYes;
    hideConfirm();
    if (fn) fn();
  });
  $("compose").addEventListener("click", (e) => {
    if (e.target === $("compose")) requestClose(); // click on the dimmed backdrop
  });
  $("compose").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      submitCompose("send");
    } else if (e.key === "Escape") {
      e.stopPropagation();
      requestClose();
    }
  });
  // "N" opens a new message when you're not typing somewhere.
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "n" || e.ctrlKey || e.metaKey || e.altKey || composeOpen()) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    e.preventDefault();
    openCompose({ mode: "new" });
  });
  window.addEventListener("beforeunload", (e) => {
    if (composeOpen() && compose.dirty) e.preventDefault();
  });

  // Refresh / load more / retry
  $("refresh-btn").addEventListener("click", () => refreshAll("refresh"));
  $("load-more").addEventListener("click", () => loadMessages("more"));
  $("conn-retry").addEventListener("click", async () => {
    $("conn-retry").disabled = true;
    const ok = await checkStatus();
    $("conn-retry").disabled = false;
    if (ok) refreshAll("reset");
  });

  // Auto-refresh every 60 s (skipped while the tab is hidden), plus when returning to the tab.
  setInterval(() => {
    if (started && !document.hidden && !state.loading) refreshAll("refresh");
    if (started && !document.hidden && currentView === "overview") loadOverview();
    if (started && !document.hidden && currentView === "tasks") {
      loadSuggestions({ quiet: true });
      if (!$("tasks-list").contains(document.activeElement)) loadTasks(); // also picks up task emails you sent (Given)
    }
  }, AUTO_REFRESH_MS);
  document.addEventListener("visibilitychange", () => {
    if (started && !document.hidden && !state.loading) refreshAll("refresh");
  });

  // Mobile sidebar
  function openSidebar() {
    $("sidebar").classList.add("open");
    $("sidebar-backdrop").classList.remove("hidden");
  }
  function closeSidebar() {
    $("sidebar").classList.remove("open");
    $("sidebar-backdrop").classList.add("hidden");
  }
  $("menu-btn").addEventListener("click", openSidebar);
  $("sidebar-backdrop").addEventListener("click", closeSidebar);

  // Theme toggle
  $("theme-btn").addEventListener("click", () => {
    const dark = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* storage unavailable */ }
  });

  // ------------------------------------------------------------------------
  // Views: Mail / Tasks
  // ------------------------------------------------------------------------

  const tasksState = { tasks: [], suggestions: [], suggLoaded: false, suggLoading: false, tab: "mine" };

  function setView(next) {
    $("mail-view").classList.toggle("hidden", next !== "mail");
    $("mail-view").classList.toggle("flex", next === "mail");
    $("tasks-view").classList.toggle("hidden", next !== "tasks");
    $("overview-view").classList.toggle("hidden", next !== "overview");
    $("summary-view").classList.toggle("hidden", next !== "summary");
    document.querySelectorAll(".folder-link[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === next));
    currentView = next;
    renderFolders();
    closeSidebar();
    if (next === "tasks") {
      loadTasks();
      loadSuggestions({ quiet: true });
    }
    if (next === "overview") loadOverview();
    if (next === "summary") loadSummary();
  }

  // ------------------------------------------------------------------------
  // Summary: all mail + task mail
  // ------------------------------------------------------------------------

  const summary = { data: null, loading: false, tab: "all", digest: "all", tstatus: "open" };

  function setSummaryTab(tab) {
    summary.tab = tab;
    $("tab-all").setAttribute("aria-selected", String(tab === "all"));
    $("tab-task").setAttribute("aria-selected", String(tab === "task"));
    $("sum-all").classList.toggle("hidden", tab !== "all");
    $("sum-task").classList.toggle("hidden", tab !== "task");
  }
  $("tab-all").addEventListener("click", () => setSummaryTab("all"));
  $("tab-task").addEventListener("click", () => setSummaryTab("task"));
  $("tab-all").parentElement.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const next = summary.tab === "all" ? "task" : "all";
    setSummaryTab(next);
    $(next === "all" ? "tab-all" : "tab-task").focus();
  });

  function barList(listId, rows, emptyText) {
    const max = Math.max(1, ...rows.map((r) => r.count));
    $(listId).replaceChildren(...(rows.length ? rows.map((r) => {
      const li = el("li", "bar-row");
      li.title = r.title || `${r.label}: ${r.count}`;
      const label = el("span", "truncate", r.label);
      const track = el("span", "bar-track");
      const fill = el("span", "bar-fill block");
      fill.style.width = `${Math.max(4, (r.count / max) * 100)}%`;
      track.append(fill);
      li.append(label, track, el("span", "text-right tabular-nums text-slate-500", String(r.count)));
      return li;
    }) : [el("li", "py-4 text-center text-sm text-slate-500", emptyText)]));
  }

  function digestItem(e) {
    const li = el("li");
    const b = el("button", "digest-item");
    b.type = "button";
    const top = el("div", "flex items-baseline gap-2");
    const who = e.from ? e.from.name || e.from.address : "(unknown sender)";
    top.append(el("span", "min-w-0 max-w-[40%] truncate text-sm " + (e.isRead ? "font-medium" : "font-semibold"), who));
    top.append(el("span", "min-w-0 flex-1 truncate text-sm " + (e.isRead ? "text-slate-600 dark:text-slate-300" : "font-semibold text-brand-600 dark:text-brand-400"), e.subject));
    top.append(el("span", "shrink-0 text-xs text-slate-500", formatListDate(e.receivedDateTime)));
    const sum = el("p", "mt-0.5 line-clamp-2 text-sm text-slate-600 dark:text-slate-300",
      e.summary || (e.hasAttachments ? "(No text: see the attachments.)" : "(No text.)"));
    const meta = el("div", "mt-1 flex flex-wrap items-center gap-1.5");
    meta.append(el("span", `kind-badge kind-${e.kind}`, e.kindLabel));
    if (!e.isRead) meta.append(el("span", "text-[11px] font-semibold text-brand-600 dark:text-brand-400", "Unread"));
    if (e.needsReply) meta.append(el("span", "text-[11px] font-semibold text-amber-700 dark:text-amber-400", "Needs a reply"));
    if (e.answered) meta.append(el("span", "text-[11px] text-slate-500", "Replied"));
    if (e.hasAttachments) meta.append(icon("paperclip", "h-3.5 w-3.5 text-slate-400", "Has attachments"));
    if (e.flagged) meta.append(icon("flag", "h-3.5 w-3.5 text-red-500", "Flagged"));
    (e.categories || []).forEach((c) => meta.append(categoryPill(c)));
    b.append(top, sum, meta);
    b.addEventListener("click", () => openEmail(e.id));
    li.append(b);
    return li;
  }

  function renderDigest() {
    const d = summary.data;
    const f = summary.digest;
    const list = d.emails.filter((e) => f === "all" || (f === "unread" && !e.isRead) || (f === "needs" && e.needsReply) || (f === "request" && e.kind === "request"));
    const box = $("sa-digest");
    if (!list.length) {
      box.replaceChildren(el("p", "py-8 text-center text-sm text-slate-500", d.emails.length ? "No emails match this filter." : "No emails in this period."));
      return;
    }
    const days = new Map();
    list.forEach((e) => {
      const key = (e.receivedDateTime || "").slice(0, 10);
      if (!days.has(key)) days.set(key, []);
      days.get(key).push(e);
    });
    const parts = [];
    for (const [day, items] of days) {
      parts.push(el("div", "digest-day bg-white dark:bg-slate-950", `${day ? dayLabel(day, true) : "Unknown date"} · ${items.length}`));
      const ul = el("ul", "divide-y divide-slate-100 dark:divide-slate-900");
      ul.append(...items.map(digestItem));
      parts.push(ul);
    }
    box.replaceChildren(...parts);
  }

  const STATUS = {
    new: { label: "Waiting for you", cls: "status-new" },
    added: { label: "Task added", cls: "status-added" },
    done: { label: "Task done", cls: "status-done" },
    dismissed: { label: "Dismissed", cls: "status-dismissed" },
  };

  function taskMailCard(e) {
    const li = el("li", "panel space-y-2");
    const head = el("div", "flex flex-wrap items-start gap-2");
    const title = el("button", "min-w-0 flex-1 text-left");
    title.type = "button";
    title.append(el("p", "truncate font-semibold hover:underline", e.subject));
    const who = e.from ? e.from.name || e.from.address : "(unknown sender)";
    title.append(el("p", "truncate text-xs text-slate-500", `${who} · ${formatListDate(e.receivedDateTime)}${e.answered ? " · Replied" : ""}`));
    title.addEventListener("click", () => openEmail(e.id));
    const st = STATUS[e.taskStatus];
    head.append(title, el("span", `status-badge ${st.cls}`, st.label), viewEmailButton(e.id, "shrink-0"));
    li.append(head);
    if (e.summary) li.append(el("p", "text-sm text-slate-600 dark:text-slate-300", e.summary));

    // Tasks already created from this email
    e.linkedTasks.forEach((t) => {
      const row = el("div", "flex items-center gap-2 rounded-md bg-slate-50 px-2 py-1.5 text-sm dark:bg-slate-900");
      row.append(el("span", t.completed ? "text-emerald-600" : "text-brand-600 dark:text-brand-400", t.completed ? "✓" : "•"));
      row.append(el("span", "min-w-0 flex-1 truncate" + (t.completed ? " text-slate-500 line-through" : ""), t.title));
      const due = dueInfo(t.due && t.due.slice(0, 10));
      if (due && !t.completed) row.append(el("span", "shrink-0 text-xs " + due.cls, due.label));
      li.append(row);
    });

    // Requests found in the email that haven't been decided yet
    e.tasks.filter((t) => !t.handled && !e.linkedTasks.length).forEach((t) => {
      const box = el("div", "space-y-2 rounded-md border border-dashed border-amber-400/60 p-2");
      const row = el("div", "flex flex-wrap items-center gap-2");
      const input = el("input", "input h-8 min-w-0 flex-1 text-sm");
      input.value = t.title;
      input.maxLength = 255;
      input.setAttribute("aria-label", "Task title");
      const date = el("input", "input h-8 text-xs");
      date.type = "date";
      date.value = t.due || "";
      date.setAttribute("aria-label", "Due date");
      const add = el("button", "btn-primary h-8", "Add task");
      const dismiss = el("button", "btn-outline h-8", "Dismiss");
      add.type = dismiss.type = "button";
      add.addEventListener("click", async () => {
        if (!input.value.trim()) return input.focus();
        add.disabled = dismiss.disabled = true;
        try {
          await createTask({ title: input.value.trim(), due: date.value || null, messageId: e.id, suggestionKey: t.key, direction: "received", person: personName(e.from), personAddress: ((e.from) || {}).address || "" });
          toast("Task added to Tasks › My tasks");
          loadSummary();
        } catch (err) {
          add.disabled = dismiss.disabled = false;
          if (!handleError(err)) toast(err.message, "error");
        }
      });
      dismiss.addEventListener("click", async () => {
        add.disabled = dismiss.disabled = true;
        try {
          await api("/api/tasks/suggestions/dismiss", { method: "POST", body: JSON.stringify({ key: t.key }) });
          loadSummary();
        } catch (err) {
          add.disabled = dismiss.disabled = false;
          toast(err.message, "error");
        }
      });
      row.append(input, date, add, dismiss);
      box.append(row);
      const info = dueInfo(t.due);
      if (t.quote || info) {
        const q = el("p", "text-xs text-slate-500");
        if (info) q.append(el("span", info.cls + " mr-2", info.label));
        if (t.quote) q.append(el("span", "italic", `“${t.quote}”`));
        box.append(q);
      }
      li.append(box);
    });
    return li;
  }

  function renderTaskMail() {
    const d = summary.data;
    const f = summary.tstatus;
    const order = { new: 0, added: 1, done: 2, dismissed: 3 };
    const soonest = (e) => [...e.tasks.filter((t) => !t.handled).map((t) => t.due), ...e.linkedTasks.filter((t) => !t.completed).map((t) => t.due && t.due.slice(0, 10))].filter(Boolean).sort()[0] || "9999";
    const list = d.emails
      .filter((e) => e.taskStatus)
      .filter((e) => f === "all" || (f === "open" && (e.taskStatus === "new" || e.taskStatus === "added")) || (f === "new" && e.taskStatus === "new") || (f === "added" && (e.taskStatus === "added" || e.taskStatus === "done")))
      .sort((a, b) => order[a.taskStatus] - order[b.taskStatus] || soonest(a).localeCompare(soonest(b)));
    $("st-list").replaceChildren(...(list.length ? list.map(taskMailCard)
      : [el("li", "rounded-lg border border-dashed border-slate-300 px-3 py-10 text-center text-sm text-slate-500 dark:border-slate-700",
        d.taskStats.emails ? "Nothing here. Try another filter." : "No emails with requests or deadlines in this period.")]));
  }

  function renderSummary() {
    const d = summary.data;
    const s = d.stats;
    const n = (v) => Number(v || 0).toLocaleString();
    $("tab-all-count").textContent = n(s.received);
    $("tab-task-count").textContent = d.taskStats.new ? `${n(d.taskStats.new)} waiting` : n(d.taskStats.emails);
    $("sa-received").textContent = n(s.received);
    $("sa-received-sub").textContent = d.days === 1 ? "today" : `in ${d.days} days`;
    $("sa-unread").textContent = n(s.unread);
    $("sa-answered").textContent = n(s.answered);
    $("sa-needs").textContent = n(s.needsReply);
    $("sa-attach").textContent = n(s.attachments);
    $("sa-senders").textContent = n(s.senders);
    barList("sa-top-senders", d.topSenders.map((x) => ({ label: x.name, count: x.count, title: `${x.name} <${x.address}>: ${x.count} email${x.count === 1 ? "" : "s"}${x.unread ? `, ${x.unread} unread` : ""}` })), "No emails in this period.");
    barList("sa-kinds", d.kinds.map((k) => ({ label: k.label, count: k.count })), "No emails in this period.");
    const t = d.taskStats;
    $("st-emails").textContent = n(t.emails);
    $("st-emails-sub").textContent = s.received ? `of ${n(s.received)} emails` : "";
    $("st-new").textContent = n(t.new);
    $("st-added").textContent = n(t.added);
    $("st-added-sub").textContent = t.done ? `${n(t.done)} done` : t.dismissed ? `${n(t.dismissed)} dismissed` : " ";
    $("st-week").textContent = n(t.dueThisWeek);
    $("st-overdue").textContent = n(t.overdue);
    $("st-overdue-sub").classList.toggle("warn", t.overdue > 0);
    $("summary-badge").textContent = t.new ? String(t.new) : "";
    const note = $("sum-note");
    note.textContent = "Inbox only." + (d.truncated ? " Very busy period: only the newest 300 emails are summarised." : "") + " Summaries are picked from each email's own text by simple rules on this PC.";
    note.classList.remove("hidden");
    renderDigest();
    renderTaskMail();
  }

  async function loadSummary({ quiet = false } = {}) {
    if (summary.loading) return;
    summary.loading = true;
    $("sum-refresh-icon").classList.add("spin");
    if (!summary.data && !quiet) $("sa-digest").replaceChildren(...[0, 1, 2].map(() => el("div", "skeleton my-3 h-10 w-full")));
    try {
      summary.data = await api(`/api/summary?days=${encodeURIComponent($("sum-days").value)}`);
      showBox("sum-error", null);
      renderSummary();
    } catch (err) {
      if (!handleError(err) && !quiet) showBox("sum-error", err.message);
    } finally {
      summary.loading = false;
      $("sum-refresh-icon").classList.remove("spin");
    }
  }

  $("sum-days").addEventListener("change", () => {
    summary.data = null;
    loadSummary();
  });
  $("sum-refresh").addEventListener("click", () => loadSummary());
  document.querySelectorAll("[data-digest]").forEach((b) => b.addEventListener("click", () => {
    summary.digest = b.dataset.digest;
    document.querySelectorAll("[data-digest]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (summary.data) renderDigest();
  }));
  document.querySelectorAll("[data-tstatus]").forEach((b) => b.addEventListener("click", () => {
    summary.tstatus = b.dataset.tstatus;
    document.querySelectorAll("[data-tstatus]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (summary.data) renderTaskMail();
  }));

  // ------------------------------------------------------------------------
  // Overview
  // ------------------------------------------------------------------------

  const overview = { data: null, chart: null, loading: false };

  /** Chart.js loads with `defer` from the CDN; wait for it (or give up if offline). */
  function chartLib() {
    if (window.Chart) return Promise.resolve(window.Chart);
    return new Promise((resolve) => {
      const done = () => resolve(window.Chart || null);
      if (document.readyState === "complete") return setTimeout(done, 0);
      window.addEventListener("load", done, { once: true });
    });
  }

  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }

  function dayLabel(iso, long) {
    const [y, m, d] = iso.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    const diff = Math.round((localToday() - dt) / 86_400_000);
    if (diff === 0) return "Today";
    if (diff === 1 && long) return "Yesterday";
    return dt.toLocaleDateString(undefined, long ? { weekday: "long", day: "numeric", month: "short" } : { weekday: "short", day: "numeric" });
  }

  async function renderChart() {
    const data = overview.data;
    if (!data) return;
    const Chart = await chartLib();
    $("ov-chart-fallback").classList.toggle("hidden", !!Chart);
    $("ov-chart-fallback").classList.toggle("flex", !Chart);
    if (!Chart) return;
    const dark = document.documentElement.classList.contains("dark");
    const ink = dark ? "#94a3b8" : "#64748b";
    const grid = dark ? "rgba(148,163,184,0.12)" : "rgba(100,116,139,0.14)";
    const surface = dark ? "#020617" : "#ffffff";
    const labels = data.daily.map((d) => dayLabel(d.date, false));
    const series = (label, key, color) => ({
      label,
      data: data.daily.map((d) => d[key]),
      backgroundColor: color,
      hoverBackgroundColor: color,
      borderColor: surface, // 2px surface gap between neighbouring bars
      borderWidth: { left: 1, right: 1, top: 0, bottom: 0 },
      borderSkipped: "bottom",
      borderRadius: { topLeft: 4, topRight: 4 },
      maxBarThickness: 28,
      categoryPercentage: 0.7,
      barPercentage: 1,
    });
    if (overview.chart) overview.chart.destroy();
    overview.chart = new Chart($("ov-chart"), {
      type: "bar",
      data: {
        labels,
        datasets: [
          series("Received", "received", cssVar("--series-received")),
          series("Sent", "sent", cssVar("--series-sent")),
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? false : { duration: 300 },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false }, // HTML legend above the chart
          tooltip: {
            backgroundColor: dark ? "#e2e8f0" : "#0f172a",
            titleColor: dark ? "#0f172a" : "#ffffff",
            bodyColor: dark ? "#0f172a" : "#ffffff",
            padding: 10,
            boxPadding: 4,
            usePointStyle: true,
            callbacks: {
              title: (items) => dayLabel(data.daily[items[0].dataIndex].date, true),
              label: (item) => ` ${item.dataset.label}: ${item.parsed.y}`,
            },
          },
        },
        scales: {
          x: { grid: { display: false }, border: { color: grid }, ticks: { color: ink, font: { size: 11 } } },
          y: {
            beginAtZero: true,
            border: { display: false },
            grid: { color: grid },
            ticks: { color: ink, font: { size: 11 }, precision: 0, maxTicksLimit: 5 },
          },
        },
      },
    });
  }

  function renderOverview() {
    const d = overview.data;
    const n = (v) => Number(v || 0).toLocaleString();
    $("ov-unread").textContent = n(d.inboxUnread);
    $("ov-unread-sub").textContent = `of ${n(d.inboxTotal)} in Inbox`;
    $("ov-today").textContent = n(d.receivedToday);
    const week = d.daily.reduce((s, x) => s + x.received, 0);
    $("ov-today-sub").textContent = `${n(week)} this week`;
    const sentWeek = d.daily.reduce((s, x) => s + x.sent, 0);
    $("ov-sent").textContent = n(sentWeek);
    $("ov-flagged").textContent = n(d.flagged);
    $("ov-drafts").textContent = n(d.drafts);
    const t = d.tasks;
    $("ov-tasks").textContent = n(t.open);
    const sub = $("ov-tasks-sub");
    sub.textContent = t.overdue ? `${t.overdue} overdue` : t.dueToday ? `${t.dueToday} due today` : t.open ? "none overdue" : "all done";
    sub.classList.toggle("warn", t.overdue > 0);

    // Chart summary line + table (the table is the accessible version of the chart)
    const busiest = d.daily.reduce((a, b) => (b.received > a.received ? b : a), d.daily[0]);
    $("ov-chart-summary").textContent = week || sentWeek
      ? `${n(week)} received and ${n(sentWeek)} sent.` + (busiest.received ? ` Busiest day: ${dayLabel(busiest.date, true)} (${busiest.received} received).` : "")
      : "No emails received or sent in the last 7 days.";
    $("ov-table").replaceChildren(...d.daily.map((x) => {
      const tr = el("tr");
      tr.append(el("td", "py-1", dayLabel(x.date, true)), el("td", "py-1 text-right tabular-nums", String(x.received)), el("td", "py-1 text-right tabular-nums", String(x.sent)));
      return tr;
    }));

    // Upcoming tasks
    const tl = $("ov-task-list");
    if (!t.upcoming.length) {
      tl.replaceChildren(el("li", "py-6 text-center text-sm text-slate-500", "No open tasks."));
    } else {
      tl.replaceChildren(...t.upcoming.map((task) => {
        const li = el("li", "flex items-start gap-2 py-2");
        const main = el("div", "min-w-0 flex-1");
        main.append(el("p", "truncate text-sm", task.title));
        const due = dueInfo(task.due);
        if (due) main.append(el("p", "text-xs " + due.cls, due.label));
        li.append(main);
        if (task.messageId) {
          const open = el("button", "shrink-0 text-xs text-brand-600 hover:underline dark:text-brand-400", "Open email");
          open.type = "button";
          open.addEventListener("click", () => openEmail(task.messageId));
          li.append(open);
        }
        return li;
      }));
    }

    // Recent unread
    const ul = $("ov-unread-list");
    if (!d.recentUnread.length) {
      ul.replaceChildren(el("li", "py-6 text-center text-sm text-slate-500", "You're all caught up. No unread email in your Inbox."));
    } else {
      ul.replaceChildren(...d.recentUnread.map((m) => {
        const li = el("li");
        const b = el("button", "flex w-full items-baseline gap-3 rounded-md px-2 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-900");
        b.type = "button";
        const who = m.from ? m.from.name || m.from.address : "(unknown sender)";
        b.append(
          el("span", "w-40 shrink-0 truncate text-sm font-semibold", who),
          el("span", "min-w-0 flex-1 truncate text-sm", m.subject),
          el("span", "shrink-0 text-xs text-slate-500", formatListDate(m.receivedDateTime)),
        );
        b.addEventListener("click", () => {
          goTo("inbox");
          openMessage(m.id);
        });
        li.append(b);
        return li;
      }));
    }
    $("ov-updated").textContent = "Updated " + new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    renderChart();
  }

  async function loadOverview() {
    if (overview.loading) return;
    overview.loading = true;
    $("ov-refresh-icon").classList.add("spin");
    try {
      overview.data = await api("/api/overview");
      showBox("ov-error", null);
      renderOverview();
    } catch (err) {
      if (!handleError(err)) showBox("ov-error", err.message);
    } finally {
      overview.loading = false;
      $("ov-refresh-icon").classList.remove("spin");
    }
  }

  /** Card / link targets on the overview. */
  function goTo(target) {
    if (target === "tasks") return setView("tasks");
    const folderByKey = (key) => (state.folders.find((f) => f.key === key) || {}).id;
    const folder = { sent: folderByKey("sentitems"), drafts: folderByKey("drafts") }[target] || folderByKey("inbox") || "INBOX";
    // Reset filters, then apply the one the card stands for.
    state.filters = { unread: target === "unread", flagged: target === "flagged", attachments: false, from: "", to: "" };
    state.category = "";
    $("cat-filter").value = "";
    $("cat-filter").classList.remove("active");
    document.querySelectorAll(".chip[data-filter]").forEach((c) => c.setAttribute("aria-pressed", String(!!state.filters[c.dataset.filter])));
    updateFilterUi();
    setView("mail");
    state.folder = folder;
    state.checked.clear();
    closeReading();
    renderFolders();
    loadMessages("reset");
  }

  document.querySelectorAll("#overview-view [data-go]").forEach((b) => b.addEventListener("click", () => goTo(b.dataset.go)));
  $("ov-refresh").addEventListener("click", loadOverview);
  // Re-draw the chart with the other theme's colours.
  new MutationObserver(() => currentView === "overview" && renderChart()).observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  document.querySelectorAll(".folder-link[data-view]").forEach((a) =>
    a.addEventListener("click", (e) => {
      e.preventDefault();
      setView(a.dataset.view);
    }),
  );

  function openEmail(messageId) {
    setView("mail");
    openMessage(messageId);
  }

  // ------------------------------------------------------------------------
  // Tasks
  // ------------------------------------------------------------------------

  function localToday() {
    const n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }

  function dueInfo(due) {
    if (!due) return null;
    const [y, m, d] = due.split("-").map(Number);
    const dt = new Date(y, m - 1, d);
    const days = Math.round((dt - localToday()) / 86_400_000);
    const pretty = dt.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    if (days < 0) return { label: `Overdue · ${pretty}`, cls: "due-overdue" };
    if (days === 0) return { label: "Due today", cls: "due-soon" };
    if (days === 1) return { label: "Due tomorrow", cls: "due-soon" };
    if (days <= 3) return { label: `Due ${pretty}`, cls: "due-soon" };
    return { label: `Due ${pretty}`, cls: "text-slate-500" };
  }

  function showBox(id, message) {
    $(id).textContent = message || "";
    $(id).classList.toggle("hidden", !message);
  }

  const TASK_TABS = {
    mine: {
      help: "Everything you need to do: tasks you added yourself, and tasks from emails (marked “From: …”).",
      empty: "No open tasks. Nice work!",
    },
    given: {
      help: "Tasks you gave to others: every task email you send (from this dashboard, Outlook or your phone) is added here automatically. Tick one off when they report it done.",
      empty: "No open tasks given to others. Use “Give a task to someone” to assign one by email.",
    },
    received: {
      help: "Tasks other people asked you to do, added from their emails (Add task, or Found in your emails).",
      empty: "No open received tasks. Add one from an email with “Add task”.",
    },
  };
  const taskDir = (t) => t.direction || (t.messageId ? "received" : "mine");
  /** My tasks = everything on your plate (your own + received); the other tabs show one kind. */
  const inTaskTab = (t, tab) => (tab === "mine" ? taskDir(t) !== "given" : taskDir(t) === tab);

  function updateTasksBadge() {
    const openTasks = tasksState.tasks.filter((t) => !t.completed);
    const open = openTasks.filter((t) => taskDir(t) !== "given").length; // the sidebar counts what is on your plate
    $("tasks-badge").textContent = open ? String(open) : "";
    for (const dir of Object.keys(TASK_TABS)) {
      const n = openTasks.filter((t) => inTaskTab(t, dir)).length;
      if ($(`ttab-${dir}-count`)) $(`ttab-${dir}-count`).textContent = n ? String(n) : "";
    }
    const inTab = openTasks.filter((t) => inTaskTab(t, tasksState.tab)).length;
    $("tasks-count").textContent = inTab ? `(${inTab} open)` : "";
  }

  function setTaskTab(dir) {
    tasksState.tab = TASK_TABS[dir] ? dir : "mine";
    for (const d of Object.keys(TASK_TABS)) $(`ttab-${d}`).setAttribute("aria-selected", String(d === tasksState.tab));
    $("tasks-tab-help").textContent = TASK_TABS[tasksState.tab].help;
    $("task-new").classList.toggle("hidden", tasksState.tab !== "mine");
    $("task-give").classList.toggle("hidden", tasksState.tab !== "given");
    renderTasks();
  }

  /** Give a task: open Write for me in task mode (optionally to someone, e.g. a reminder). */
  function giveTask(note = "") {
    openWriter({ mode: "task", note });
  }

  function remindAbout(t) {
    const who = (t.person || "").split(",")[0].trim() || "them";
    const when = t.due ? ` by ${new Date(t.due + "T00:00").toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}` : "";
    openWriter({ mode: "email", note: `remind ${who} to ${t.title.charAt(0).toLowerCase() + t.title.slice(1)}${when}` });
  }

  function taskRow(t) {
    const li = el("li", "task-row flex items-start gap-3 px-3 py-2.5" + (t.completed ? " done" : ""));
    const box = el("input", "mt-1 h-4 w-4 shrink-0 cursor-pointer accent-[#0f6cbd]");
    box.type = "checkbox";
    box.checked = t.completed;
    box.setAttribute("aria-label", (t.completed ? "Mark not completed: " : "Mark completed: ") + t.title);
    box.addEventListener("change", () => completeTask(t, box.checked));

    const main = el("div", "min-w-0 flex-1");
    main.append(el("p", "task-title break-words text-sm", t.title));
    const meta = el("div", "mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs");
    const due = dueInfo(t.due);
    if (due && !t.completed) meta.append(el("span", due.cls, due.label));
    if (t.importance === "high") meta.append(el("span", "font-semibold text-red-600", "High importance"));
    const dir = taskDir(t);
    if (dir === "given" && t.person) meta.append(el("span", "task-person text-slate-600 dark:text-slate-300", "To: " + t.person));
    if (dir === "received" && t.person) meta.append(el("span", "task-person text-slate-600 dark:text-slate-300", "From: " + t.person));
    if (dir === "given" && !t.completed) {
      const remind = el("button", "text-brand-600 hover:underline dark:text-brand-400", "Remind");
      remind.type = "button";
      remind.title = "Write a reminder email about this task";
      remind.addEventListener("click", () => remindAbout(t));
      meta.append(remind);
    }
    if (t.messageId) {
      const link = el("button", "text-brand-600 hover:underline dark:text-brand-400", "Open email");
      link.type = "button";
      link.addEventListener("click", () => openEmail(t.messageId));
      meta.append(link);
    }
    if (meta.childNodes.length) main.append(meta);
    li.append(box, main);
    return li;
  }

  function renderTasks() {
    const list = $("tasks-list");
    const inTab = tasksState.tasks.filter((t) => inTaskTab(t, tasksState.tab));
    const shown = $("tasks-show-done").checked ? inTab : inTab.filter((t) => !t.completed);
    if (!shown.length) {
      list.replaceChildren(el("li", "px-3 py-8 text-center text-sm text-slate-500", TASK_TABS[tasksState.tab].empty));
    } else {
      list.replaceChildren(...shown.map(taskRow));
    }
    updateTasksBadge();
  }

  async function loadTasks() {
    try {
      const data = await api("/api/tasks" + ($("tasks-show-done").checked ? "?completed=1" : ""));
      tasksState.tasks = data.tasks;
      showBox("tasks-error", null);
      renderTasks();
    } catch (err) {
      if (!handleError(err)) showBox("tasks-error", err.message);
    }
  }

  async function completeTask(t, completed) {
    t.completed = completed;
    renderTasks();
    try {
      await api(`/api/tasks/${encodeURIComponent(t.id)}/complete`, { method: "POST", body: JSON.stringify({ completed }) });
      toast(completed ? "Task completed" : "Task reopened");
    } catch (err) {
      t.completed = !completed;
      renderTasks();
      if (!handleError(err)) toast(err.message, "error");
    }
  }

  /** {name, address} -> "Qasim Ali" (or the address when there's no name). */
  function personName(p) {
    if (!p) return "";
    if (typeof p === "string") return p;
    return (p.name || p.address || "").trim();
  }

  async function createTask(payload) {
    const task = await api("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
    tasksState.tasks.unshift(task);
    renderTasks();
    return task;
  }

  $("tasks-show-done").addEventListener("change", loadTasks);
  // Guarded: if the page is older than this script (dashboard not restarted after an update), the rest of
  // the app must keep working instead of stopping here.
  if ($("ttab-mine")) {
    for (const d of Object.keys(TASK_TABS)) $(`ttab-${d}`).addEventListener("click", () => setTaskTab(d));
    $("task-give").addEventListener("click", () => giveTask());
    setTaskTab("mine");
  }
  $("task-new").addEventListener("submit", async (e) => {
    e.preventDefault();
    const title = $("task-new-title").value.trim();
    if (!title) return $("task-new-title").focus();
    try {
      await createTask({ title, due: $("task-new-due").value || null, direction: "mine" });
      $("task-new-title").value = "";
      $("task-new-due").value = "";
      toast("Task added");
    } catch (err) {
      if (!handleError(err)) toast(err.message, "error");
    }
  });

  // Suggestions from emails

  function suggestionCard(s) {
    const li = el("li", "space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800");
    const title = el("input", "input h-9 w-full font-medium");
    title.value = s.title;
    title.maxLength = 255;
    title.setAttribute("aria-label", "Task title");

    const row = el("div", "flex flex-wrap items-center gap-2");
    const due = el("input", "input h-8 text-xs");
    due.type = "date";
    due.value = s.due || "";
    due.setAttribute("aria-label", "Due date");
    row.append(due);
    row.append(el("span", "rounded-full px-2 py-0.5 text-[11px] font-semibold " +
      (s.confidence === "high" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300"
        : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300"),
      s.confidence === "high" ? "Likely task" : "Possible task"));
    const info = dueInfo(s.due);
    if (info) row.append(el("span", "text-xs " + info.cls, info.label));

    const meta = el("p", "text-xs text-slate-500");
    const from = s.from ? s.from.name || s.from.address : "Unknown sender";
    const open = el("button", "text-brand-600 hover:underline dark:text-brand-400", s.subject || "(no subject)");
    open.type = "button";
    open.addEventListener("click", () => openEmail(s.messageId));
    meta.append(document.createTextNode(`${from} · `), open, document.createTextNode(s.reason ? ` · ${s.reason}` : ""));

    li.append(title, row, meta);
    if (s.quote) li.append(el("p", "line-clamp-2 border-l-2 border-slate-200 pl-2 text-xs italic text-slate-500 dark:border-slate-700", s.quote));

    const actions = el("div", "flex gap-2 pt-1");
    const add = el("button", "btn-primary h-8", "Add task");
    const dismiss = el("button", "btn-outline h-8", "Dismiss");
    add.type = dismiss.type = "button";
    add.addEventListener("click", async () => {
      if (!title.value.trim()) return title.focus();
      add.disabled = dismiss.disabled = true;
      try {
        await createTask({ title: title.value.trim(), due: due.value || null, messageId: s.messageId, suggestionKey: s.key, direction: "received", person: personName(s.from), personAddress: ((s.from) || {}).address || "" });
        removeSuggestion(s.key);
        toast("Task added to Tasks › My tasks");
      } catch (err) {
        add.disabled = dismiss.disabled = false;
        if (!handleError(err)) toast(err.message, "error");
      }
    });
    dismiss.addEventListener("click", async () => {
      add.disabled = dismiss.disabled = true;
      try {
        await api("/api/tasks/suggestions/dismiss", { method: "POST", body: JSON.stringify({ key: s.key }) });
        removeSuggestion(s.key);
      } catch (err) {
        add.disabled = dismiss.disabled = false;
        toast(err.message, "error");
      }
    });
    actions.append(add, dismiss, viewEmailButton(s.messageId, "ml-auto"));
    li.append(actions);
    return li;
  }

  /** "View email" button: opens the email this task/request came from. */
  function viewEmailButton(messageId, extra = "") {
    const b = el("button", `btn-outline h-8 ${extra}`);
    b.type = "button";
    b.title = "Open the email this came from";
    b.innerHTML = '<svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>';
    b.append(document.createTextNode("View email"));
    b.addEventListener("click", () => openEmail(messageId));
    return b;
  }

  function removeSuggestion(key) {
    tasksState.suggestions = tasksState.suggestions.filter((x) => x.key !== key);
    renderSuggestions();
  }

  function renderSuggestions() {
    const list = $("sugg-list");
    const n = tasksState.suggestions.length;
    $("sugg-count").textContent = tasksState.suggLoaded ? `(${n})` : "";
    if (!n) {
      list.replaceChildren(el("li", "rounded-lg border border-dashed border-slate-300 px-3 py-8 text-center text-sm text-slate-500 dark:border-slate-700",
        `No requests or deadlines found in the last ${$("sugg-days").value} days.`));
      return;
    }
    list.replaceChildren(...tasksState.suggestions.map(suggestionCard));
  }

  /**
   * Scans recent mail for requests. quiet: a background check (opening Tasks again, or every minute while
   * Tasks is open) that only adds requests from newly arrived mail and never wipes what you are editing.
   */
  async function loadSuggestions(opts = {}) {
    const quiet = opts.quiet === true && tasksState.suggLoaded;
    if (tasksState.suggLoading) return;
    tasksState.suggLoading = true;
    $("sugg-refresh").disabled = true;
    $("sugg-refresh").textContent = "Scanning…";
    if (!quiet) {
      $("sugg-list").replaceChildren(...[0, 1].map(() => {
        const li = el("li", "space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-800");
        li.append(el("div", "skeleton h-8 w-full"), el("div", "skeleton h-3 w-2/3"), el("div", "skeleton h-3 w-1/2"));
        return li;
      }));
    }
    try {
      const data = await api(`/api/tasks/suggestions?days=${encodeURIComponent($("sugg-days").value)}`);
      if (quiet) {
        const known = new Set(tasksState.suggestions.map((x) => x.key));
        const fresh = data.suggestions.filter((x) => !known.has(x.key));
        const editing = $("sugg-list").contains(document.activeElement);
        if (fresh.length && !editing) {
          tasksState.suggestions = [...fresh, ...tasksState.suggestions];
          renderSuggestions();
          toast(fresh.length === 1 ? "1 new possible task found in your email" : `${fresh.length} new possible tasks found in your email`);
        }
      } else {
        tasksState.suggestions = data.suggestions;
        renderSuggestions();
      }
      tasksState.suggLoaded = true;
      showBox("sugg-error", null);
    } catch (err) {
      if (!quiet) $("sugg-list").replaceChildren();
      if (!handleError(err)) showBox("sugg-error", err.message);
    } finally {
      tasksState.suggLoading = false;
      $("sugg-refresh").disabled = false;
      $("sugg-refresh").textContent = "Scan";
    }
  }

  $("sugg-refresh").addEventListener("click", () => loadSuggestions());
  $("sugg-days").addEventListener("change", () => loadSuggestions());

  // "Add task" from the open email

  const readingTask = { key: null, title: "" };

  function hideReadingTask() {
    $("r-task").classList.add("hidden");
    readingTask.key = null;
  }

  function pickReadingSuggestion(s) {
    $("r-task-title").value = s.title;
    $("r-task-due").value = s.due || "";
    readingTask.key = s.key || null;
    readingTask.title = s.title;
  }

  $("act-task").addEventListener("click", async () => {
    const d = reading.detail;
    if (!d) return;
    const form = $("r-task");
    if (!form.classList.contains("hidden")) return hideReadingTask();
    form.classList.remove("hidden");
    pickReadingSuggestion({ title: d.subject.replace(/^\s*((re|fw|fwd)\s*:\s*)+/i, ""), due: null });
    $("r-task-suggestions").replaceChildren(el("span", "text-xs text-slate-500", "Looking for requests in this email…"));
    $("r-task-title").focus();
    try {
      const data = await api(`/api/messages/${encodeURIComponent(d.id)}/task-suggestions`);
      if (reading.detail !== d) return;
      const chips = data.suggestions.map((s) => {
        const due = dueInfo(s.due);
        const chip = el("button", "chip max-w-full truncate", s.title + (due ? ` · ${due.label}` : ""));
        chip.type = "button";
        chip.title = s.quote || s.title;
        chip.addEventListener("click", () => pickReadingSuggestion(s));
        return chip;
      });
      $("r-task-suggestions").replaceChildren(...(chips.length ? chips : [el("span", "text-xs text-slate-500", "No specific request found. Using the subject as the title.")]));
      if (data.suggestions.length) pickReadingSuggestion(data.suggestions[0]);
    } catch (err) {
      $("r-task-suggestions").replaceChildren();
      if (!handleError(err)) toast(err.message, "error");
    }
  });
  $("r-task-cancel").addEventListener("click", hideReadingTask);
  $("r-task").addEventListener("submit", async (e) => {
    e.preventDefault();
    const d = reading.detail;
    const title = $("r-task-title").value.trim();
    if (!d || !title) return;
    try {
      await createTask({
        title,
        due: $("r-task-due").value || null,
        messageId: d.id,
        suggestionKey: readingTask.key && title === readingTask.title ? readingTask.key : undefined,
        direction: "received", person: personName(d.from), personAddress: ((d.from) || {}).address || "",
      });
      hideReadingTask();
      toast("Task added to Tasks › My tasks");
    } catch (err) {
      if (!handleError(err)) toast(err.message, "error");
    }
  });

  // ------------------------------------------------------------------------
  // Start
  // ------------------------------------------------------------------------

  // ------------------------------------------------------------------------
  // Write for me: a short note -> a professional email, checked before sending
  // ------------------------------------------------------------------------

  const writer = { busy: false, note: null, rows: [], step: 1, suggestSeq: 0, suggestTimer: null, suggestions: [] };
  const writerOpen = () => $("writer").classList.contains("open");

  function setWriterError(message) {
    $("writer-error").textContent = message || "";
    $("writer-error").classList.toggle("hidden", !message);
  }

  function setWriterMode(mode) {
    writer.mode = mode === "task" ? "task" : "email";
    document.querySelectorAll(".writer-mode-btn").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.mode === writer.mode)));
    if ($("writer-task")) $("writer-task").classList.toggle("hidden", writer.mode !== "task");
    $("writer-title").textContent = writer.mode === "task" ? "Give a task" : "Write for me";
    if (writer.step === 1) $("writer-ok").textContent = writer.mode === "task" ? "Write task email" : "Write email";
    writer.note = null; // switching mode means writing again
  }

  function openWriter(opts = {}) {
    if (composeOpen() || writerOpen()) return;
    Object.assign(writer, { busy: false, note: null, rows: [], step: 1 });
    $("writer-people").classList.add("hidden");
    if (opts.note !== undefined) $("writer-note").value = opts.note;
    if ($("writer-due")) {
      $("writer-due").value = opts.due || "";
      $("writer-high").checked = false;
    }
    setWriterMode(opts.mode || "email");
    $("writer-ok").disabled = false;
    $("writer-status").textContent = "";
    setWriterError(null);
    hideWriterSuggest();
    $("writer").classList.add("open");
    document.body.style.overflow = "hidden";
    showSignatureFields(false);
    loadSignature();
    $("writer-note").focus();
  }

  function closeWriter() {
    $("writer").classList.remove("open");
    hideWriterSuggest();
    if (!composeOpen()) document.body.style.overflow = "";
  }

  const personLabel = (c) => (c.name ? `${c.name} <${c.address}>` : c.address);

  function writerRow(row, index) {
    const wrap = el("div", "writer-row");
    const field = el("select", "input h-8 !flex-none text-xs");
    field.setAttribute("aria-label", "To or Cc");
    for (const [v, label] of [["to", "To"], ["cc", "Cc"]]) {
      const o = el("option", "", label);
      o.value = v;
      field.append(o);
    }
    field.value = row.field;
    field.addEventListener("change", () => { row.field = field.value; });
    wrap.append(field);
    if (row.phrase && row.phrase.toLowerCase() !== (row.address || "").toLowerCase()) {
      wrap.append(el("span", "who", `"${row.phrase}"`));
    }

    const other = el("input", "input h-8 text-sm");
    other.type = "email";
    other.placeholder = row.phrase ? `Email address for ${row.phrase}` : "Email address";
    other.value = row.typed || "";
    other.setAttribute("aria-label", other.placeholder);
    other.addEventListener("input", () => { row.typed = other.value.trim(); });

    if (row.candidates.length) {
      const pick = el("select", "input h-8 text-sm");
      pick.setAttribute("aria-label", `Who is ${row.phrase || "this"}?`);
      if (!row.address) {
        const o = el("option", "", "Choose who this is…");
        o.value = "";
        pick.append(o);
      }
      for (const c of row.candidates) {
        const o = el("option", "", personLabel(c));
        o.value = c.address;
        pick.append(o);
      }
      const o = el("option", "", "Someone else (type the address)…");
      o.value = "__other";
      pick.append(o);
      pick.value = row.choice || row.address || "";
      other.classList.toggle("hidden", pick.value !== "__other");
      pick.addEventListener("change", () => {
        row.choice = pick.value;
        other.classList.toggle("hidden", pick.value !== "__other");
        if (pick.value === "__other") other.focus();
      });
      wrap.append(pick, other);
    } else if (row.address) {
      wrap.append(el("span", "writer-chip truncate", personLabel(row)));
    } else {
      wrap.append(other);
    }
    const remove = el("button", "icon-btn !h-8 !w-8");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove ${row.phrase || row.address}`);
    remove.title = "Remove";
    remove.innerHTML = '<svg viewBox="0 0 24 24" class="h-4 w-4" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>';
    remove.addEventListener("click", () => {
      writer.rows.splice(index, 1);
      renderWriterRows();
    });
    wrap.append(remove);
    return wrap;
  }

  function renderWriterRows() {
    const rows = writer.rows;
    const unsure = rows.filter((r) => !r.address).length;
    $("writer-people-help").textContent = !rows.length
      ? "Who should receive this email? Add someone below, or continue and fill in To yourself."
      : unsure
        ? `Please confirm who ${unsure === 1 ? "this is" : "these are"}:`
        : "This email will go to:";
    $("writer-rows").replaceChildren(...rows.map(writerRow));
    $("writer-people").classList.remove("hidden");
  }

  function hideWriterSuggest() {
    $("writer-suggest").classList.add("hidden");
    writer.suggestions = [];
  }

  function addWriterPerson(c) {
    if (!c || !c.address) return;
    if (!writer.rows.some((r) => (r.choice || r.address || "").toLowerCase() === c.address.toLowerCase())) {
      writer.rows.push({ field: "to", phrase: "", address: c.address, name: c.name || "", candidates: [] });
    }
    $("writer-add").value = "";
    hideWriterSuggest();
    renderWriterRows();
    $("writer-add").focus();
  }

  const EMAIL_RX = /^[^@\s<>;,]+@[^@\s<>;,]+\.[^@\s<>;,]+$/;

  async function suggestWriterPeople() {
    const q = $("writer-add").value.trim();
    const seq = ++writer.suggestSeq;
    if (!q) return hideWriterSuggest();
    let list = [];
    try {
      list = (await api(`/api/contacts?q=${encodeURIComponent(q)}`)).contacts || [];
    } catch { /* suggestions are optional */ }
    if (seq !== writer.suggestSeq) return;
    if (EMAIL_RX.test(q) && !list.some((c) => c.address.toLowerCase() === q.toLowerCase())) list.unshift({ name: "", address: q });
    writer.suggestions = list;
    const box = $("writer-suggest");
    if (!list.length) {
      box.replaceChildren(el("p", "px-2 py-1.5 text-xs text-slate-500", "No one found. Type their full email address."));
    } else {
      box.replaceChildren(...list.map((c) => {
        const b = el("button", "truncate", personLabel(c));
        b.type = "button";
        b.setAttribute("role", "option");
        b.addEventListener("mousedown", (e) => e.preventDefault()); // keep focus in the input
        b.addEventListener("click", () => addWriterPerson(c));
        return b;
      }));
    }
    box.classList.remove("hidden");
  }

  function writerChoices() {
    const out = { to: [], cc: [] };
    for (const r of writer.rows) {
      let address = r.candidates.length ? (r.choice ?? r.address ?? "") : r.address || "";
      if (address === "__other" || (!r.candidates.length && !r.address)) address = r.typed || "";
      if (!address) return { error: `Choose who "${r.phrase}" is, type their email address, or remove them.` };
      if (!EMAIL_RX.test(address)) return { error: `"${address}" is not a full email address.` };
      out[r.field].push({ phrase: r.phrase || address, address });
    }
    return { choices: out };
  }

  function finishWriter(r) {
    closeWriter();
    openCompose({
      mode: "new",
      title: r.task ? "New task (written for you)" : "New message (written for you)",
      to: r.to.map((p) => ({ address: p.address })),
      cc: r.cc.map((p) => ({ address: p.address })),
      subject: r.subject,
      body: r.body,
      task: r.task || null,
      status: r.task
        ? "Task email: when you click Send it is added to Tasks › Given"
        : r.translated ? `Translated from ${r.languages.join(", ")}: check it, then Send` : "Check it, then Send",
    });
  }

  async function runWriter() {
    if (writer.busy) return;
    const note = $("writer-note").value.trim();
    setWriterError(null);
    if (!note) return setWriterError("Write what the email should say.");
    if (/\[name\]/i.test(note)) return setWriterError("Replace [name] with the person's name.");
    let payload = { note };
    if (writer.step === 2 && writer.note === note) {
      const c = writerChoices();
      if (c.error) return setWriterError(c.error);
      payload = { note, choices: c.choices };
    }
    if (writer.mode === "task") {
      payload.task = { due: $("writer-due").value || null, importance: $("writer-high").checked ? "high" : "normal" };
    }
    writer.busy = true;
    $("writer-ok").disabled = true;
    $("writer-status").textContent = "Writing…";
    try {
      const r = await api("/api/write", { method: "POST", body: JSON.stringify(payload) });
      writer.note = note;
      if (payload.choices || (r.ready && r.to.length)) return finishWriter(r);
      writer.step = 2;
      writer.rows = [...r.to.map((p) => ({ ...p, field: "to" })), ...r.cc.map((p) => ({ ...p, field: "cc" }))];
      renderWriterRows();
      $("writer-ok").textContent = "Continue";
      const first = $("writer-rows").querySelector("select:not([aria-label='To or Cc']), input:not(.hidden)");
      (first || $("writer-add")).focus();
    } catch (err) {
      if (!handleError(err)) setWriterError(err.message);
    } finally {
      writer.busy = false;
      $("writer-ok").disabled = false;
      $("writer-status").textContent = "";
    }
  }

  // Signature used by Write for me / Make professional
  writer.sig = null;
  function renderSignature() {
    const s = writer.sig || {};
    const parts = [s.name, s.title, s.company].filter(Boolean);
    $("sig-summary").textContent = parts.length ? parts.join(" · ") : "not set";
    for (const k of ["name", "title", "company", "phone"]) $(`sig-${k}`).value = s[k] || "";
  }
  function showSignatureFields(show) {
    $("sig-fields").classList.toggle("hidden", !show);
    $("sig-fields").classList.toggle("grid", show);
    $("sig-toggle").setAttribute("aria-expanded", String(show));
  }
  async function loadSignature() {
    if (writer.sig) return renderSignature();
    try {
      writer.sig = await api("/api/signature");
      renderSignature();
      // First time: open the fields so the job title and company get filled in.
      if (!writer.sig.saved && writerOpen()) showSignatureFields(true);
    } catch { /* optional */ }
  }
  $("sig-toggle").addEventListener("click", () => {
    showSignatureFields($("sig-fields").classList.contains("hidden"));
  });
  $("sig-save").addEventListener("click", async () => {
    const body = {};
    for (const k of ["name", "title", "company", "phone"]) body[k] = $(`sig-${k}`).value.trim();
    $("sig-save").disabled = true;
    try {
      writer.sig = await api("/api/signature", { method: "POST", body: JSON.stringify(body) });
      renderSignature();
      showSignatureFields(false);
      toast("Signature saved");
    } catch (err) {
      if (!handleError(err)) setWriterError(err.message);
    } finally {
      $("sig-save").disabled = false;
    }
  });

  // "Make professional" in the mail window: rewrite what was typed as a formal email.
  const polish = { undo: null, busy: false };
  function setPolishLabel() {
    $("c-polish-label").textContent = polish.undo ? "Undo rewrite" : "Make professional";
  }
  async function polishCompose() {
    if (polish.busy) return;
    if (polish.undo) {
      $("c-body").value = polish.undo.body;
      if (polish.undo.subject !== null) $("c-subject").value = polish.undo.subject;
      polish.undo = null;
      setPolishLabel();
      return;
    }
    const text = $("c-body").value.trim();
    if (!text) {
      setComposeError("Type what you want to say (a few words is enough), then click Make professional.");
      $("c-body").focus();
      return;
    }
    setComposeError(null);
    const list = (v) => v.split(/[;,\n]/).map((s) => s.trim()).filter((a) => EMAIL_RX.test(a));
    const choices = {
      to: list($("c-to").value).map((a) => ({ phrase: a, address: a })),
      cc: list($("c-cc").value).map((a) => ({ phrase: a, address: a })),
    };
    polish.busy = true;
    $("c-polish").disabled = true;
    const before = $("compose-status").textContent;
    $("compose-status").textContent = "Rewriting…";
    try {
      const r = await api("/api/write", { method: "POST", body: JSON.stringify({ note: text, polish: true, choices, remember: false }) });
      const current = $("c-subject").value.trim();
      // Replace the subject when it's empty or one we wrote earlier; keep a subject you typed yourself.
      const subjectEmpty = !current || current === compose.autoSubject;
      polish.undo = { body: $("c-body").value, subject: subjectEmpty ? $("c-subject").value : null };
      $("c-body").value = r.body;
      if (subjectEmpty) {
        $("c-subject").value = r.subject;
        compose.autoSubject = r.subject;
      }
      compose.dirty = true;
      setPolishLabel();
      $("compose-status").textContent = r.translated
        ? `Translated from ${r.languages.join(", ")} and rewritten: check it, then Send`
        : "Rewritten: check it, then Send";
      $("c-body").scrollTop = 0;
    } catch (err) {
      $("compose-status").textContent = before;
      if (!handleError(err)) setComposeError(err.message);
    } finally {
      polish.busy = false;
      $("c-polish").disabled = false;
    }
  }
  $("c-polish").addEventListener("click", polishCompose);
  $("c-body").addEventListener("input", () => {
    if (polish.undo) {
      polish.undo = null;
      setPolishLabel();
    }
  });

  $("write-btn").addEventListener("click", () => openWriter());
  document.querySelectorAll(".writer-mode-btn").forEach((b) => b.addEventListener("click", () => setWriterMode(b.dataset.mode)));
  $("writer-close").addEventListener("click", closeWriter);
  $("writer-cancel").addEventListener("click", closeWriter);
  $("writer-form").addEventListener("submit", (e) => {
    e.preventDefault();
    runWriter();
  });
  $("writer-note").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      runWriter();
    }
  });
  $("writer-note").addEventListener("input", () => {
    // Editing the note after the people step starts over (the people may have changed).
    if (writer.step === 2 && $("writer-note").value.trim() !== writer.note) {
      writer.step = 1;
      $("writer-ok").textContent = "Write email";
    }
  });
  document.querySelectorAll(".writer-example").forEach((b) => b.addEventListener("click", () => {
    const t = $("writer-note");
    t.value = b.dataset.note;
    writer.step = 1;
    $("writer-ok").textContent = "Write email";
    $("writer-people").classList.add("hidden");
    t.focus();
    const at = t.value.indexOf("[name]");
    if (at >= 0) t.setSelectionRange(at, at + 6);
  }));
  $("writer-add").addEventListener("input", () => {
    clearTimeout(writer.suggestTimer);
    writer.suggestTimer = setTimeout(suggestWriterPeople, 180);
  });
  $("writer-add").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      const q = $("writer-add").value.trim();
      if (writer.suggestions.length) addWriterPerson(writer.suggestions[0]);
      else if (EMAIL_RX.test(q)) addWriterPerson({ name: "", address: q });
    } else if (e.key === "Escape" && !$("writer-suggest").classList.contains("hidden")) {
      e.stopPropagation();
      hideWriterSuggest();
    }
  });
  $("writer-add").addEventListener("blur", () => setTimeout(hideWriterSuggest, 150));
  $("writer").addEventListener("click", (e) => {
    if (e.target === $("writer")) closeWriter();
  });
  $("writer").addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      closeWriter();
    }
  });
  // "W" opens Write for me when you're not typing somewhere.
  document.addEventListener("keydown", (e) => {
    if (e.key.toLowerCase() !== "w" || e.ctrlKey || e.metaKey || e.altKey || composeOpen() || writerOpen()) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
    if (document.querySelector("#dialog.open, #cat-manager.open, #signin.open")) return;
    e.preventDefault();
    openWriter();
  });

  async function startApp() {
    if (started) return;
    started = true;
    renderSkeleton();
    await checkStatus();
    await loadCategories();
    refreshAll("reset");
    setView("overview"); // start on the Overview page
    loadSummary({ quiet: true }); // fills the "waiting" badge next to Summary
    loadTasks();
    if (BACKEND === "imap") setTimeout(() => api("/api/contacts").catch(() => {}), 5000); // warm "Write for me" lookups
  }

  (async function boot() {
    renderSkeleton();
    if (BACKEND === "imap") {
      try {
        const s = await api("/api/auth/status");
        if (!s.signedIn) {
          showSignin(null, s.defaults);
          return;
        }
      } catch (err) {
        setConnection(false, "Not connected", err.message);
        return;
      }
    }
    startApp();
  })();
})();
