(() => {
  const $ = (selector) => document.querySelector(selector);
  const money = (value) => new Intl.NumberFormat("es-MX", { style: "currency", currency: "MXN" }).format(Number(value) || 0);
  const round2 = (value) => Math.round((Number(value) + Number.EPSILON) * 100) / 100;
  const todayISO = () => new Date().toISOString().slice(0, 10);
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const initials = (name) => String(name || "").split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("").toUpperCase();
  const newUuid = () => { const bytes = crypto.getRandomValues(new Uint8Array(16)); bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128; const hex = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(""); return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`; };

  const seed = {
    clients: [
      { id: "c1", name: "Grupo Industrial del Centro", rfc: "GIC120315AB1", email: "compras@gic.example", phone: "222 555 0140", regime: "", zip: "" },
      { id: "c2", name: "Residencial Las Palmas", rfc: "RLP180921CD2", email: "admin@laspalmas.example", phone: "222 555 0195", regime: "", zip: "" },
      { id: "c3", name: "Logística Nova Puebla", rfc: "LNP210407EF3", email: "operaciones@nova.example", phone: "222 555 0270", regime: "", zip: "" },
    ],
    quotes: [
      { id: "RM-2026-001", clientId: "c1", title: "Red empresarial · Edificio A", date: todayISO(), expiry: "", status: "Enviada", tax: 16, notes: "", lines: [{ kind: "Equipo", name: "Switch administrable 24 puertos", qty: 2, price: 12400 }, { kind: "Instalación", name: "Configuración y puesta en marcha", qty: 1, price: 8900 }] },
      { id: "RM-2026-002", clientId: "c2", title: "CCTV · Acceso principal", date: todayISO(), expiry: "", status: "Aprobada", tax: 16, notes: "", lines: [{ kind: "Equipo", name: "Cámara IP exterior", qty: 4, price: 3200 }, { kind: "Material", name: "Cableado y canalización", qty: 1, price: 6800 }, { kind: "Instalación", name: "Instalación y configuración", qty: 1, price: 9200 }] },
      { id: "RM-2026-003", clientId: "c3", title: "Mantenimiento de red", date: todayISO(), expiry: "", status: "Lista para FEL", tax: 16, notes: "", lines: [{ kind: "Servicio", name: "Mantenimiento preventivo trimestral", qty: 1, price: 14500 }] },
    ],
    projects: [{ id: "p1", title: "CCTV · Acceso principal", clientId: "c2", quoteId: "RM-2026-002", status: "Programado", progress: 38, date: todayISO() }],
    activities: [
      { text: "Cotización RM-2026-003 preparada para FEL", time: "Hoy · 10:42", icon: "▧" },
      { text: "CCTV · Acceso principal aprobado", time: "Hoy · 09:15", icon: "✓" },
      { text: "Cotización RM-2026-001 enviada", time: "Ayer · 16:30", icon: "↗" },
    ],
  };

  let db;
  try { db = JSON.parse(localStorage.getItem("redmagna-erp-v1")) || structuredClone(seed); } catch { db = structuredClone(seed); }
  db.opportunities ||= [];
  const save = () => localStorage.setItem("redmagna-erp-v1", JSON.stringify(db));
  const backend = {
    base: localStorage.getItem("redmagna-api-base") || "/api",
    token: sessionStorage.getItem("redmagna-api-token") || "",
    connected: false,
    permissions: new Set(),
    username: "",
  };
  const live = { opportunities: [], opportunityAssignees: [], opportunityActivities: [], opportunityReport: null, quoteTemplates: [], invoices: [], creditNotes: [], payments: [], fiscalDocuments: [], issuedCfdiRegister: null, workHoursReport: null, workOrders: [], supportTickets: [], repairCases: [], supportAssignees: [], entries: [], assignees: [], accounts: [], chartAccounts: [], journals: [], postingConfigurations: [], bankStatements: [], accountingPeriods: [], selectedBankStatement: null, receivablesAging: null, customerStatement: null, trialBalance: null, generalLedger: null, financialStatements: null, subledgerReconciliation: null, openItemsPreview: null, openingBalanceBatches: [], openingBalanceBatchDetails: {}, expenses: { categories: [], items: [], reports: [], configurations: [] }, inventory: { products: [], locations: [], balances: [], movements: [], reservations: [], reorderRules: [], counts: [] }, purchasing: { suppliers: [], supplierProducts: [], orders: [], receipts: [], bills: [], supplierPayments: [], sourcing: [], frameworkAgreements: [], payablesAging: null, supplierStatement: null, supplierCfdiRegister: null } };
  let customerImportFile = null;
  let productImportFile = null;
  let supplierImportFile = null;

  const clientOf = (id) => db.clients.find((client) => client.id === id) || { name: "Cliente eliminado", rfc: "" };
  const calc = (quote) => {
    const entries = (quote.lines || []).map((line) => {
      const quantity = line.isOptional && line.approvedQuantity != null ? Number(line.approvedQuantity) : Number(line.qty) || 0;
      const gross = round2(quantity * (Number(line.price) || 0));
      const discountPercent = Math.min(100, Math.max(0, Number(line.discountPercent) || 0));
      const discount = round2(gross * discountPercent / 100);
      const subtotal = round2(gross - discount);
      return { line, gross, discountPercent, discount, subtotal, tax: round2(subtotal * (Number(line.taxRate ?? quote.tax) || 0) / 100) };
    });
    const included = entries.filter(({ line }) => !line.isOptional || (line.approvedQuantity != null && Number(line.approvedQuantity) > 0));
    const optional = entries.filter(({ line }) => line.isOptional && line.approvedQuantity == null);
    const subtotal = included.reduce((sum, item) => sum + item.subtotal, 0);
    const tax = included.reduce((sum, item) => sum + item.tax, 0);
    const optionalTotal = optional.reduce((sum, item) => sum + item.subtotal + item.tax, 0);
    return { sub: subtotal, tax, total: subtotal + tax, optionalTotal };
  };
  const badge = (status) => {
    const cls = status === "Aprobada" || status === "Pagada" || status === "Terminada" || status === "Ganada" || status === "Completada" ? "approved" : status === "Borrador" || status === "Cancelada" ? "draft" : status === "Lista para FEL" || status === "Abierta" || status === "Pago parcial" || status === "Pendiente" ? "fel" : "sent";
    return `<span class="badge ${cls}">${escapeHtml(status)}</span>`;
  };
  const byDate = (a, b) => String(b.date || "").localeCompare(String(a.date || ""));
  const toast = (message) => { const node = $("#toast"); node.textContent = message; node.classList.add("show"); setTimeout(() => node.classList.remove("show"), 3000); };
  const can = (permission) => !backend.connected || backend.permissions.has(permission);

  async function apiRequest(path, options = {}) {
    const url = /^https?:\/\//i.test(path) ? path : `${backend.base.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
    const isFormData = options.body instanceof FormData;
    const headers = { ...(options.body && !isFormData ? { "Content-Type": "application/json" } : {}), ...(backend.token && !options.noAuth ? { Authorization: `Token ${backend.token}` } : {}), ...options.headers };
    const response = await fetch(url, { ...options, headers, body: options.body ? (isFormData ? options.body : JSON.stringify(options.body)) : undefined });
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 && backend.token && !options.noAuth) {
        backend.token = ""; backend.connected = false; backend.permissions = new Set();
        sessionStorage.removeItem("redmagna-api-token"); updateConnectionState();
        toast("La sesión del ERP expiró. Vuelve a conectar tu usuario.");
      }
      const detail = payload?.detail || payload?.non_field_errors?.join(" ") || Object.values(payload || {}).flat().join(" ") || `Error ${response.status}`;
      throw new Error(detail);
    }
    return payload;
  }

  async function apiList(path) {
    let url = `${backend.base.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
    const results = [];
    while (url) {
      const payload = await apiRequest(url);
      if (Array.isArray(payload)) { results.push(...payload); break; }
      results.push(...(payload.results || []));
      url = payload.next || "";
    }
    return results;
  }

  function apiStateLabel(state) {
    return ({ draft: "Borrador", submitted: "En revisión", approved: "Aprobado", rejected: "Rechazado", journal_draft: "Póliza borrador", sent: "Enviada", cancelled: "Cancelada", expired: "Vencida", superseded: "Reemplazada", new: "Nueva", qualified: "Calificada", proposal: "Cotización enviada", won: "Ganada", lost: "Perdida", open: "Abierta", partial: "Pago parcial", paid: "Pagada", credited: "Liquidada por nota de crédito", planned: "Programada", in_progress: "En atención", blocked: "Bloqueada", done: "Terminada", cancelled_work: "Cancelada", ordered: "Solicitada", received: "Recibida", received_partial: "Recibida parcialmente", waiting_customer: "En espera del cliente", resolved: "Resuelto", closed: "Cerrado", recorded: "Registrado", reversed: "Revertido" })[state] || state;
  }

  async function syncFromApi() {
    const [clients, opportunities, opportunityReport, opportunityAssignees, opportunityActivities, quotes, quoteTemplates, workOrders, invoices, payments, fiscalDocuments, entries, assignees, products, locations, balances, movements, reservations, serialUnits, reorderRules, inventoryCounts, suppliers, supplierProducts, purchaseOrders, purchaseReceipts, supplierBills, supplierPayments, sourcingRequests, frameworkAgreements, receivablesAging, payablesAging, accounts, bankStatements, accountingPeriods, journals, postingConfigurations, supportTickets, repairCases, supportAssignees, expenseCategories, expenses, expenseReports, expenseConfigurations] = await Promise.all([
      can("sales.view_customer") ? apiList("customers/") : Promise.resolve([]),
      can("sales.view_opportunity") ? apiList("opportunities/") : Promise.resolve([]),
      can("sales.view_opportunity") ? apiRequest("opportunities/report/").catch(() => null) : Promise.resolve(null),
      can("sales.view_opportunity") ? apiList("opportunities/assignees/") : Promise.resolve([]),
      can("sales.view_opportunityactivity") ? apiList("opportunity-activities/") : Promise.resolve([]),
      can("sales.view_quote") ? apiList("quotes/") : Promise.resolve([]),
      can("sales.view_quote") ? apiList("quote-templates/") : Promise.resolve([]),
      can("sales.view_workorder") ? apiList("work-orders/") : Promise.resolve([]),
      can("billing.view_customerinvoice") ? apiList("billing/invoices/") : Promise.resolve([]),
      can("billing.view_payment") ? apiList("billing/payments/") : Promise.resolve([]),
      can("billing.view_fiscaldocument") ? apiList("billing/fiscal-documents/") : Promise.resolve([]),
      can("accounting.view_journalentry") ? apiList("accounting/entries/") : Promise.resolve([]),
      can("sales.schedule_workorder") ? apiList("work-orders/assignees/") : Promise.resolve([]),
      can("inventory.view_product") ? apiList("inventory/products/") : Promise.resolve([]),
      can("inventory.view_stocklocation") ? apiList("inventory/locations/") : Promise.resolve([]),
      can("inventory.view_stockbalance") ? apiList("inventory/balances/") : Promise.resolve([]),
      can("inventory.view_stockmovement") ? apiList("inventory/movements/") : Promise.resolve([]),
      can("inventory.view_stockmovement") ? apiList("inventory/reservations/") : Promise.resolve([]),
      can("inventory.view_stockbalance") ? apiList("inventory/units/") : Promise.resolve([]),
      can("inventory.view_reorderrule") ? apiList("inventory/reorder-rules/") : Promise.resolve([]),
      can("inventory.view_inventorycount") ? apiList("inventory/counts/") : Promise.resolve([]),
      can("purchasing.view_supplier") ? apiList("purchasing/suppliers/") : Promise.resolve([]),
      can("purchasing.view_supplierproduct") ? apiList("purchasing/supplier-products/") : Promise.resolve([]),
      can("purchasing.view_purchaseorder") ? apiList("purchasing/orders/") : Promise.resolve([]),
      can("purchasing.view_purchasereceipt") ? apiList("purchasing/receipts/") : Promise.resolve([]),
      can("purchasing.view_supplierbill") ? apiList("purchasing/supplier-bills/") : Promise.resolve([]),
      can("purchasing.view_supplierpayment") ? apiList("purchasing/supplier-payments/") : Promise.resolve([]),
      can("purchasing.view_purchasesourcingrequest") ? apiList("purchasing/sourcing/") : Promise.resolve([]),
      can("purchasing.view_purchaseframeworkagreement") ? apiList("purchasing/framework-agreements/") : Promise.resolve([]),
      backend.connected && can("billing.view_customerinvoice") ? apiRequest(`billing/invoices/receivables-aging/?as_of=${encodeURIComponent($("#receivables-aging-date").value || todayISO())}`) : Promise.resolve(null),
      backend.connected && can("purchasing.view_supplierbill") ? apiRequest(`purchasing/supplier-bills/payables-aging/?as_of=${encodeURIComponent($("#payables-aging-date").value || todayISO())}`) : Promise.resolve(null),
      can("accounting.view_account") ? apiList("accounting/accounts/") : Promise.resolve([]),
      can("accounting.view_bankstatement") ? apiList("accounting/bank-statements/") : Promise.resolve([]),
      can("accounting.view_accountingperiod") ? apiList("accounting/periods/") : Promise.resolve([]),
      can("accounting.view_journal") ? apiList("accounting/journals/") : Promise.resolve([]),
      can("accounting.view_postingconfiguration") ? apiList("accounting/posting-configurations/") : Promise.resolve([]),
      can("support.view_supportticket") ? apiList("support/tickets/") : Promise.resolve([]),
      can("repairs.view_repaircase") ? apiList("repairs/cases/") : Promise.resolve([]),
      can("support.assign_supportticket") ? apiList("support/tickets/assignees/") : Promise.resolve([]),
      can("expenses.view_expensecategory") ? apiList("expenses/categories/") : Promise.resolve([]),
      can("expenses.view_expense") ? apiList("expenses/items/") : Promise.resolve([]),
      can("expenses.view_expensereport") ? apiList("expenses/reports/") : Promise.resolve([]),
      can("accounting.view_postingconfiguration") ? apiList("expenses/posting-configurations/") : Promise.resolve([]),
    ]);
    const creditNotes = can("billing.view_customercreditnote") ? await apiList("billing/credit-notes/") : [];
    db.clients = clients.map((client) => ({ id: client.id, name: client.name, legalName: client.legal_name, rfc: client.rfc, email: client.email, phone: client.phone, regime: client.fiscal_regime, zip: client.fiscal_postal_code, paymentTermDays: client.payment_term_days }));
    db.opportunities = opportunities.map((opportunity) => ({ ...opportunity, company_name: opportunity.company_name || opportunity.customer_name || "" }));
    live.opportunityReport = opportunityReport;
    live.opportunityAssignees = opportunityAssignees;
    live.opportunityActivities = opportunityActivities;
    live.quoteTemplates = quoteTemplates;
    db.quotes = quotes.map((quote) => ({
      id: quote.number, backendId: quote.id, clientId: quote.customer, customerContactId: quote.customer_contact || "", customerContactName: quote.customer_contact_name || "", recipientName: quote.recipient_name_snapshot || "", recipientEmail: quote.recipient_email_snapshot || "", opportunityId: quote.opportunity || "", customerSiteId: quote.customer_site || "", serviceSiteName: quote.service_site_name || "", serviceAddress: quote.service_address || "", serviceContactName: quote.service_contact_name || "", serviceContactPhone: quote.service_contact_phone || "", serviceContactEmail: quote.service_contact_email || "", title: quote.title, date: quote.issue_date, expiry: quote.valid_until || "", paymentTermDays: quote.payment_term_days, status: apiStateLabel(quote.status), apiStatus: quote.status, discountApprovalRequired: Boolean(quote.discount_approval_required), discountApproved: Boolean(quote.discount_approved), discountMaximumPercent: quote.discount_maximum_percent || "0.00", discountLimitPercent: quote.discount_limit_percent || "0.00", revisionNumber: quote.revision_number || 0, revisionOf: quote.revision_of || "", revisionOfNumber: quote.revision_of_number || "", notes: quote.notes,
      lines: quote.lines.map((line) => ({ kind: ({ equipment: "Equipo", material: "Material", installation: "Instalación", service: "Servicio" })[line.kind] || line.kind, name: line.description, qty: Number(line.quantity), price: Number(line.unit_price), discountPercent: Number(line.discount_percent || 0), taxRate: Number(line.tax_rate), isOptional: Boolean(line.is_optional), approvedQuantity: line.approved_quantity == null ? null : Number(line.approved_quantity), catalogProduct: line.catalog_product || "", catalogProductSku: line.catalog_product_sku || "" })),
    }));
    live.workOrders = workOrders;
    live.supportTickets = supportTickets;
    live.repairCases = repairCases;
    live.supportAssignees = supportAssignees;
    live.expenses = { categories: expenseCategories, items: expenses, reports: expenseReports, configurations: expenseConfigurations };
    db.projects = workOrders.map((work) => ({
      id: work.sales_order_number || work.id.slice(0, 8), workOrderId: work.id, salesOrderId: work.sales_order, title: work.title,
      clientName: work.customer_name, clientId: db.clients.find((client) => client.name === work.customer_name)?.id || "", status: apiStateLabel(work.status),
      progress: work.status === "done" ? 100 : work.status === "in_progress" ? 50 : work.status === "blocked" ? 25 : 0, date: work.scheduled_start?.slice(0, 10) || todayISO(), rawStatus: work.status,
      scheduledStart: work.scheduled_start, scheduledEnd: work.scheduled_end, assignedToName: work.assigned_to_name, completionNotes: work.completion_notes,
    }));
    live.invoices = invoices; live.creditNotes = creditNotes; live.payments = payments; live.fiscalDocuments = fiscalDocuments; live.entries = entries; live.assignees = assignees;
    live.receivablesAging = receivablesAging;
    live.inventory = { products, locations, balances, movements, reservations, serialUnits, reorderRules, counts: inventoryCounts };
    live.purchasing = { suppliers, supplierProducts, orders: purchaseOrders, receipts: purchaseReceipts, bills: supplierBills, supplierPayments, sourcing: sourcingRequests, frameworkAgreements, payablesAging, supplierStatement: null };
    live.chartAccounts = accounts;
    live.accounts = accounts.filter((account) => account.allow_reconciliation && account.is_active && account.category === "asset");
    live.journals = journals;
    live.postingConfigurations = postingConfigurations;
    live.bankStatements = bankStatements;
    live.accountingPeriods = accountingPeriods;
    if (!live.selectedBankStatement || !bankStatements.some((item) => item.id === live.selectedBankStatement)) live.selectedBankStatement = bankStatements[0]?.id || null;
    db.activities = [];
    backend.connected = true;
    render();
    renderBankReconciliation();
    renderPostingConfigurations();
    renderAccountingCatalog();
    updateConnectionState();
  }

  async function connectSession() {
    const user = await apiRequest("auth/me/");
    backend.username = user.username;
    backend.permissions = new Set(user.permissions || []);
    backend.connected = true;
    await syncFromApi();
  }

  const sessionDate = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("es-MX");
  };

  function renderApiSessions(sessions) {
    const list = $("#session-list");
    if (!sessions.length) { list.innerHTML = `<div class="empty">No hay sesiones registradas.</div>`; return; }
    list.innerHTML = sessions.map((session) => {
      const status = session.is_current ? "Esta pestaña" : session.is_active ? "Activa" : session.revoked_at ? "Revocada" : "Vencida";
      const details = [session.remote_ip && `IP ${session.remote_ip}`, `Creada ${sessionDate(session.created_at)}`, session.last_used_at && `Último uso ${sessionDate(session.last_used_at)}`, `Vence ${sessionDate(session.expires_at)}`].filter(Boolean).join(" · ");
      const userAgent = session.user_agent ? `<details class="muted" style="font-size:10px;margin-top:5px"><summary>Detalles del navegador</summary>${escapeHtml(session.user_agent)}</details>` : "";
      const revoke = session.is_active && !session.is_current ? `<button type="button" class="btn btn-light btn-small" data-session-revoke="${escapeHtml(session.id)}">Revocar</button>` : "";
      return `<article class="work-log session-row"><strong>${escapeHtml(session.session_name || "Navegador web")}${session.username ? ` · ${escapeHtml(session.username)}` : ""}</strong><span class="badge ${session.is_active ? "approved" : "draft"}">${escapeHtml(status)}</span><small class="muted">${escapeHtml(details)}</small>${revoke}${userAgent}</article>`;
    }).join("");
  }

  async function openApiSessions() {
    if (!backend.connected) { toast("Conecta tu usuario para consultar las sesiones."); return; }
    $("#session-list").innerHTML = `<div class="empty">Cargando sesiones…</div>`;
    $("#session-modal").classList.add("open");
    try { renderApiSessions(await apiRequest("auth/sessions/")); }
    catch (error) { $("#session-list").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`; }
  }

  function updateConnectionState() {
    $("#connection-state").textContent = backend.connected ? `Conectado · ${backend.username}` : "Datos de demostración";
    $("#connect-api").textContent = backend.connected ? "Conectado" : "Conectar al ERP";
    $("#connect-api").classList.toggle("btn-primary", backend.connected);
    $("#manage-sessions").hidden = !backend.connected;
  }

  function quoteRow(quote, full = false) {
    const customer = clientOf(quote.clientId), totals = calc(quote), actionId = quote.backendId || quote.id;
    const action = backend.connected ? (quote.apiStatus === "draft" && can("sales.send_quote") ? "Marcar enviada" : quote.apiStatus === "sent" && can("sales.approve_quote") ? "Aprobar" : "") : (quote.status === "Enviada" || quote.status === "Borrador" ? "Aprobar" : quote.status === "Aprobada" ? "Preparar FEL" : quote.status === "Lista para FEL" ? "Registrar cobro" : "Ver");
    const version = quote.revisionNumber ? ` · Rev. ${quote.revisionNumber}${quote.revisionOfNumber ? ` de ${quote.revisionOfNumber}` : ""}` : "";
    const edit = backend.connected && quote.apiStatus === "draft" && can("sales.change_quote") ? `<button class="btn-quiet" data-quote-edit="${escapeHtml(actionId)}">Editar borrador</button>` : "";
    const costSheet = backend.connected && can("sales.view_quotecostsheet") ? `<button class="btn-quiet" data-quote-cost-sheet="${escapeHtml(actionId)}">Costos internos</button>` : "";
    const revise = backend.connected && quote.apiStatus === "sent" && can("sales.revise_quote") && can("sales.change_quote") ? `<button class="btn-quiet" data-quote-revise="${escapeHtml(actionId)}">Crear revisión</button>` : "";
    const discountApproval = backend.connected && quote.apiStatus === "sent" && quote.discountApprovalRequired && !quote.discountApproved && can("sales.approve_quote") ? `<button class="btn-quiet" data-quote-discount-approve="${escapeHtml(actionId)}">Autorizar descuento</button>` : "";
    const recipientEmail = quote.recipientEmail || customer.email;
    const email = backend.connected && quote.apiStatus === "sent" && can("sales.send_quote") && recipientEmail ? `<button class="btn-quiet" data-quote-email="${escapeHtml(actionId)}" data-quote-email-to="${escapeHtml(recipientEmail)}">Enviar propuesta</button>` : "";
    const discountState = quote.discountApprovalRequired && !quote.discountApproved ? `<small class="muted">Pendiente de Gerencia · descuento ${escapeHtml(quote.discountMaximumPercent)}% (límite ${escapeHtml(quote.discountLimitPercent)}%)</small>` : "";
    return `<tr><td class="quote-no">${escapeHtml(quote.id)}${version ? `<small class="muted">${escapeHtml(version)}</small>` : ""}</td><td><div class="client-cell"><span class="client-avatar">${escapeHtml(initials(customer.name))}</span><span class="client-name">${escapeHtml(customer.name)}</span></div></td>${full ? `<td>${escapeHtml(quote.title)}</td>` : ""}<td>${new Date(`${quote.date}T12:00:00`).toLocaleDateString("es-MX", { day: "2-digit", month: "short", year: "numeric" })}</td><td class="money">${money(totals.total)}</td><td>${badge(quote.status)}${discountState}</td>${full ? `<td><div class="quote-actions"><button class="btn-quiet" data-quote-print="${escapeHtml(actionId)}" aria-label="Imprimir cotización ${escapeHtml(quote.id)}">PDF</button>${costSheet}${edit}${action ? `<button class="btn-quiet" data-quote-action="${escapeHtml(actionId)}">${action}</button>` : ""}${discountApproval}${email}${revise}</div></td>` : ""}</tr>`;
  }

  function appendCostSheetItem(item = {}) {
    const row = document.createElement("div");
    row.className = "cost-sheet-line";
    row.style.cssText = "display:grid;grid-template-columns:140px minmax(160px,2fr) minmax(80px,.7fr) minmax(105px,.9fr) 90px 34px;align-items:center;gap:8px;margin:8px 0";
    row.innerHTML = `<select data-cost-category aria-label="Categoría del costo"><option value="equipment">Equipo</option><option value="material">Material</option><option value="labor">Mano de obra</option><option value="travel">Traslado</option><option value="subcontract">Subcontratación</option><option value="other">Otro costo</option></select><input data-cost-description maxlength="240" placeholder="Descripción interna"><input data-cost-quantity type="number" min="0.001" step="0.001" value="${escapeHtml(item.quantity ?? "1")}" aria-label="Cantidad"><input data-cost-unit-cost type="number" min="0" step="0.01" placeholder="Costo unitario" aria-label="Costo unitario"><label style="font-size:11px;display:flex;align-items:center;gap:4px"><input data-cost-optional type="checkbox"> Opcional</label><button type="button" class="btn-quiet" data-cost-remove aria-label="Quitar costo">×</button>`;
    row.querySelector("[data-cost-category]").value = item.category || "equipment";
    row.querySelector("[data-cost-description]").value = item.description || "";
    row.querySelector("[data-cost-unit-cost]").value = item.unit_cost ?? "";
    row.querySelector("[data-cost-optional]").checked = Boolean(item.is_optional);
    $("#cost-sheet-lines").append(row);
    return row;
  }

  function renderCostSheet(sheet) {
    const form = $("#cost-sheet-form");
    form.dataset.quoteId = sheet.quote_id;
    form.dataset.quoteSubtotal = String(sheet.quote_subtotal || 0);
    form.dataset.quoteOptionalSubtotal = String(sheet.quote_optional_subtotal || 0);
    $("#cost-sheet-title").textContent = `Costos internos · ${sheet.quote_number}`;
    $("#cost-sheet-quote-status").textContent = sheet.quote_status === "draft" ? "Borrador editable" : "Solo lectura · la cotización ya fue enviada";
    $("#cost-sheet-margin").value = sheet.target_margin_percent ?? "";
    $("#cost-sheet-lines").replaceChildren();
    (sheet.items || []).forEach((item) => appendCostSheetItem(item));
    if (!sheet.items?.length) appendCostSheetItem();
    const rows = $("#cost-sheet-lines").querySelectorAll(".cost-sheet-line");
    rows.forEach((row) => row.querySelectorAll("input,select,[data-cost-remove]").forEach((field) => { field.disabled = sheet.quote_status !== "draft"; }));
    $("#cost-sheet-margin").disabled = sheet.quote_status !== "draft";
    $("#cost-sheet-add").hidden = sheet.quote_status !== "draft";
    $("#cost-sheet-save").hidden = sheet.quote_status !== "draft";
    updateCostSheetPreview();
  }

  // Cost sheet calculations use scaled integers so the browser matches the backend's Decimal rounding.
  function costSheetScaled(value, decimals) {
    const match = String(value ?? "0").trim().match(/^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/);
    if (!match) return 0n;
    const sign = match[1] === "-" ? -1n : 1n;
    const whole = match[2] || "0", fraction = match[3] || "", exponent = Number(match[4] || 0);
    const digits = `${whole}${fraction}`.replace(/^0+(?=\d)/, "") || "0";
    const shift = decimals + exponent - fraction.length;
    if (shift >= 0) return sign * BigInt(digits) * (10n ** BigInt(shift));
    const divisor = 10n ** BigInt(-shift), absolute = BigInt(digits);
    return sign * ((absolute + divisor / 2n) / divisor);
  }

  function costSheetRoundRatio(numerator, denominator) {
    if (denominator === 0n) return 0n;
    const sign = (numerator < 0n) !== (denominator < 0n) ? -1n : 1n;
    const absoluteNumerator = numerator < 0n ? -numerator : numerator;
    const absoluteDenominator = denominator < 0n ? -denominator : denominator;
    return sign * ((absoluteNumerator + absoluteDenominator / 2n) / absoluteDenominator);
  }

  function costSheetFormat(value, decimals = 2) {
    const scaled = typeof value === "bigint" ? value : costSheetScaled(value, decimals);
    const sign = scaled < 0n ? "-" : "", absolute = scaled < 0n ? -scaled : scaled;
    const divisor = 10n ** BigInt(decimals);
    return `${sign}${absolute / divisor}.${String(absolute % divisor).padStart(decimals, "0")}`;
  }

  function costSheetMoney(cents) {
    return money(Number(cents) / 100);
  }

  function updateCostSheetPreview() {
    const form = $("#cost-sheet-form");
    const rows = [...$("#cost-sheet-lines").querySelectorAll(".cost-sheet-line")];
    const costs = rows.reduce((sum, row) => {
      const quantityMilli = costSheetScaled(row.querySelector("[data-cost-quantity]").value, 3);
      const unitCents = costSheetScaled(row.querySelector("[data-cost-unit-cost]").value, 2);
      const amount = costSheetRoundRatio(quantityMilli * unitCents, 1000n);
      sum[row.querySelector("[data-cost-optional]").checked ? "optional" : "base"] += amount;
      return sum;
    }, { base: 0n, optional: 0n });
    const quoteSubtotal = costSheetScaled(form.dataset.quoteSubtotal, 2);
    const quoteOptionalSubtotal = costSheetScaled(form.dataset.quoteOptionalSubtotal, 2);
    const marginInput = $("#cost-sheet-margin").value;
    const margin = marginInput === "" ? null : costSheetScaled(marginInput, 2);
    const estimatedProfit = quoteSubtotal - costs.base;
    const estimatedMargin = quoteSubtotal > 0n ? costSheetRoundRatio(estimatedProfit * 10000n, quoteSubtotal) : null;
    const optionalProfit = quoteOptionalSubtotal - costs.optional;
    const optionalMargin = quoteOptionalSubtotal > 0n ? costSheetRoundRatio(optionalProfit * 10000n, quoteOptionalSubtotal) : null;
    const targetPrice = (amount) => margin != null && margin >= 0n && margin < 10000n ? costSheetRoundRatio(amount * 10000n, 10000n - margin) : null;
    const targetBase = targetPrice(costs.base), targetOptional = targetPrice(costs.optional);
    $("#cost-sheet-summary").innerHTML = `<div class="totals"><div class="total-row"><span>Venta base antes de IVA</span><strong>${costSheetMoney(quoteSubtotal)}</strong></div><div class="total-row"><span>Venta opcional antes de IVA</span><strong>${costSheetMoney(quoteOptionalSubtotal)}</strong></div><div class="total-row"><span>Costo base</span><strong>${costSheetMoney(costs.base)}</strong></div><div class="total-row grand"><span>Utilidad bruta estimada · base</span><strong>${costSheetMoney(estimatedProfit)}</strong></div><div class="total-row"><span>Margen bruto actual · base</span><strong>${estimatedMargin == null ? "—" : `${costSheetFormat(estimatedMargin)}%`}</strong></div><div class="total-row"><span>Venta base sugerida</span><strong>${targetBase == null ? "Define un margen objetivo" : costSheetMoney(targetBase)}</strong></div><div class="total-row"><span>Costo de opciones</span><strong>${costSheetMoney(costs.optional)}</strong></div><div class="total-row"><span>Utilidad bruta estimada · opciones</span><strong>${costSheetMoney(optionalProfit)}</strong></div><div class="total-row"><span>Margen bruto actual · opciones</span><strong>${optionalMargin == null ? "—" : `${costSheetFormat(optionalMargin)}%`}</strong></div><div class="total-row"><span>Venta sugerida de opciones</span><strong>${targetOptional == null ? "—" : costSheetMoney(targetOptional)}</strong></div><div class="total-row"><span>Costo total base y opciones</span><strong>${costSheetMoney(costs.base + costs.optional)}</strong></div></div><p class="muted" style="font-size:11px">Cálculo interno en MXN antes de IVA. El precio sugerido no cambia la cotización ni se comparte con el cliente.</p>`;
  }

  function downloadCostSheetCSV() {
    const form = $("#cost-sheet-form");
    const categoryLabels = { equipment: "Equipo", material: "Material", labor: "Mano de obra", travel: "Traslado", subcontract: "Subcontratación", other: "Otro costo" };
    const textCell = (value) => {
      let text = String(value ?? "").replace(/[\r\n]+/g, " ");
      if (/^\s*[=+\-@]/.test(text)) text = `'${text}`;
      return `"${text.replaceAll('"', '""')}"`;
    };
    const numberCell = (value, decimals = 2) => ({ numeric: costSheetFormat(typeof value === "bigint" ? value : costSheetScaled(value, decimals), decimals) });
    const rows = [["Tipo", "Categoría", "Descripción", "Cantidad", "Costo unitario MXN", "Costo total MXN"]];
    const totals = { base: 0n, optional: 0n };
    for (const row of $("#cost-sheet-lines").querySelectorAll(".cost-sheet-line")) {
      const description = row.querySelector("[data-cost-description]").value.trim();
      if (!description) continue;
      const quantity = costSheetScaled(row.querySelector("[data-cost-quantity]").value, 3);
      const unitCost = costSheetScaled(row.querySelector("[data-cost-unit-cost]").value, 2);
      const lineTotal = costSheetRoundRatio(quantity * unitCost, 1000n);
      const optional = row.querySelector("[data-cost-optional]").checked;
      totals[optional ? "optional" : "base"] += lineTotal;
      rows.push([optional ? "Opcional" : "Base", categoryLabels[row.querySelector("[data-cost-category]").value] || "Otro costo", description, numberCell(quantity, 3), numberCell(unitCost), numberCell(lineTotal)]);
    }
    const quoteBase = costSheetScaled(form.dataset.quoteSubtotal, 2);
    const quoteOptional = costSheetScaled(form.dataset.quoteOptionalSubtotal, 2);
    const targetMargin = $("#cost-sheet-margin").value === "" ? null : costSheetScaled($("#cost-sheet-margin").value, 2);
    const targetPrice = (cost) => targetMargin != null && targetMargin >= 0n && targetMargin < 10000n ? numberCell(costSheetRoundRatio(cost * 10000n, 10000n - targetMargin)) : "";
    const percent = (profit, sales) => sales > 0n ? numberCell(costSheetRoundRatio(profit * 10000n, sales)) : "";
    rows.push([], ["Resumen", "Base imponible estimada MXN", numberCell(quoteBase)], ["Resumen", "Opciones estimadas MXN", numberCell(quoteOptional)], ["Resumen", "Costo base MXN", numberCell(totals.base)], ["Resumen", "Utilidad bruta base MXN", numberCell(quoteBase - totals.base)], ["Resumen", "Margen base (%)", percent(quoteBase - totals.base, quoteBase)], ["Resumen", "Costo opcional MXN", numberCell(totals.optional)], ["Resumen", "Utilidad bruta opciones MXN", numberCell(quoteOptional - totals.optional)], ["Resumen", "Margen opciones (%)", percent(quoteOptional - totals.optional, quoteOptional)], ["Resumen", "Margen objetivo (%)", targetMargin == null ? "" : numberCell(targetMargin)], ["Resumen", "Precio sugerido base antes de IVA MXN", targetPrice(totals.base)], ["Resumen", "Precio sugerido opcional antes de IVA MXN", targetPrice(totals.optional)], ["Resumen", "Costo total MXN", numberCell(totals.base + totals.optional)]);
    const csv = rows.map((row) => row.map((cell) => cell && typeof cell === "object" && "numeric" in cell ? cell.numeric : textCell(cell)).join(";")).join("\r\n");
    const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob), link = document.createElement("a");
    const quoteNumber = $("#cost-sheet-title").textContent.replace("Costos internos · ", "").replace(/[^A-Za-z0-9_-]/g, "-");
    link.href = url; link.download = `costeo-${quoteNumber || "cotizacion"}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function openQuoteCostSheet(quoteId) {
    try {
      const sheet = await apiRequest(`quotes/${quoteId}/cost-sheet/`);
      sheet.quote_id = quoteId;
      renderCostSheet(sheet);
      $("#cost-sheet-modal").classList.add("open");
    } catch (error) { toast(error.message); }
  }

  function printQuote(quote) {
    const customer = clientOf(quote.clientId), totals = calc(quote);
    const popup = window.open("", "_blank");
    if (!popup) { toast("Permite la ventana emergente para imprimir la cotización."); return; }
    const rows = (quote.lines || []).map((line) => {
      const quantity = line.isOptional && line.approvedQuantity != null ? Number(line.approvedQuantity) : Number(line.qty) || 0;
      const gross = round2(quantity * (Number(line.price) || 0));
      const discountPercent = Math.min(100, Math.max(0, Number(line.discountPercent) || 0));
      const subtotal = round2(gross - round2(gross * discountPercent / 100));
      return `<tr><td>${escapeHtml(line.kind || "Servicio")}</td><td>${escapeHtml(line.name)}${line.isOptional ? " · Opcional" : ""}</td><td class="num">${escapeHtml(quantity)}</td><td class="num">${money(line.price)}</td><td class="num">${discountPercent.toFixed(2)}%</td><td class="num">${Number(line.taxRate ?? quote.tax ?? 0).toFixed(2)}%</td><td class="num">${money(subtotal)}</td></tr>`;
    }).join("");
    const dateLabel = (value) => value ? new Date(`${value}T12:00:00`).toLocaleDateString("es-MX", { day: "2-digit", month: "long", year: "numeric" }) : "—";
    popup.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Cotización ${escapeHtml(quote.id)}</title><style>
      *{box-sizing:border-box}body{font:14px/1.5 Arial,sans-serif;color:#243247;margin:0;background:#eef1f5}.sheet{max-width:850px;min-height:1050px;margin:24px auto;background:#fff;padding:54px 62px;box-shadow:0 8px 30px #1522381a}.brand{font-size:24px;font-weight:800;letter-spacing:.08em;color:#bc2228}.top{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid #bc2228;padding-bottom:22px}.label{font-size:12px;color:#6b788b;text-transform:uppercase;letter-spacing:.08em}.folio{text-align:right}.folio strong{font-size:18px}.title{margin:30px 0 4px;font-size:25px}.sub{margin:0;color:#66758a}.details{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin:28px 0}.details p{margin:3px 0}.details strong{display:block;margin-bottom:7px}.pill{display:inline-block;margin-top:8px;padding:4px 9px;border-radius:99px;background:#f2f4f7;color:#4d5d72;font-size:11px}table{width:100%;border-collapse:collapse;margin-top:18px}th{text-align:left;background:#f4f6f8;color:#55657b;font-size:11px;text-transform:uppercase}th,td{padding:11px 9px;border-bottom:1px solid #e5e9ef}td.num,th.num{text-align:right;white-space:nowrap}.totals{width:310px;margin:20px 0 0 auto}.total{display:flex;justify-content:space-between;padding:6px 0}.grand{border-top:2px solid #25344a;margin-top:6px;padding-top:12px;font-size:18px;font-weight:700}.notes{margin-top:42px;white-space:pre-wrap}.signatures{display:grid;grid-template-columns:1fr 1fr;gap:55px;margin-top:86px}.sign{border-top:1px solid #8090a3;padding-top:8px;font-size:12px;color:#65748a}.foot{margin-top:55px;border-top:1px solid #e5e9ef;padding-top:14px;font-size:11px;color:#758195}.print{position:fixed;right:24px;top:20px;border:0;border-radius:8px;background:#bc2228;color:#fff;padding:11px 16px;font-weight:700;cursor:pointer}@media print{body{background:#fff}.sheet{margin:0;max-width:none;min-height:0;padding:18mm 17mm;box-shadow:none}.print{display:none}}@media(max-width:650px){.sheet{padding:24px;margin:0;min-height:100vh}.details{grid-template-columns:1fr}.folio{font-size:12px}.signatures{gap:22px}}
      </style></head><body><button class="print" onclick="window.print()">Imprimir / Guardar PDF</button><main class="sheet"><header class="top"><div><div class="brand">REDMAGNA</div><div class="label">Propuesta comercial</div></div><div class="folio"><div class="label">Cotización</div><strong>${escapeHtml(quote.id)}</strong><div>Fecha: ${dateLabel(quote.date)}</div><div>Vigencia: ${dateLabel(quote.expiry)}</div><span class="pill">${escapeHtml(quote.status)}</span></div></header><h1 class="title">${escapeHtml(quote.title)}</h1><p class="sub">Propuesta de equipos y servicios</p><section class="details"><div><strong>Preparada para</strong><p>${escapeHtml(customer.name)}</p>${customer.legalName ? `<p>${escapeHtml(customer.legalName)}</p>` : ""}${customer.rfc ? `<p>RFC: ${escapeHtml(customer.rfc)}</p>` : ""}${(quote.recipientEmail || customer.email) ? `<p>${escapeHtml(quote.recipientName || quote.customerContactName || customer.name)} · ${escapeHtml(quote.recipientEmail || customer.email)}</p>` : ""}${customer.phone ? `<p>${escapeHtml(customer.phone)}</p>` : ""}</div><div><strong>Sitio de servicio</strong><p>${escapeHtml(quote.serviceSiteName || "No especificado")}</p>${quote.serviceAddress ? `<p>${escapeHtml(quote.serviceAddress)}</p>` : ""}${quote.serviceContactName ? `<p>Contacto: ${escapeHtml(quote.serviceContactName)}</p>` : ""}${quote.serviceContactPhone ? `<p>${escapeHtml(quote.serviceContactPhone)}</p>` : ""}${quote.serviceContactEmail ? `<p>${escapeHtml(quote.serviceContactEmail)}</p>` : ""}</div><div><strong>Referencia</strong><p>Folio: ${escapeHtml(quote.id)}</p><p>Moneda: MXN</p><p>Precios expresados en pesos mexicanos.</p>${quote.paymentTermDays != null ? `<p>Plazo de pago: ${escapeHtml(quote.paymentTermDays)} días naturales desde la emisión de factura.</p>` : ""}</div></section><table><thead><tr><th>Tipo</th><th>Descripción</th><th class="num">Cantidad</th><th class="num">Precio unitario</th><th class="num">Descuento</th><th class="num">IVA</th><th class="num">Importe</th></tr></thead><tbody>${rows}</tbody></table><section class="totals"><div class="total"><span>Subtotal</span><strong>${money(totals.sub)}</strong></div><div class="total"><span>Impuestos estimados</span><strong>${money(totals.tax)}</strong></div><div class="total grand"><span>Total</span><strong>${money(totals.total)}</strong></div></section>${quote.notes ? `<section class="notes"><strong>Notas y condiciones</strong><div>${escapeHtml(quote.notes)}</div></section>` : ""}<section class="signatures"><div class="sign">Aceptación del cliente · Nombre y firma</div><div class="sign">Redmagna · Nombre y firma</div></section><footer class="foot">Documento de propuesta comercial. No es un CFDI ni sustituye una factura fiscal. Los impuestos se muestran como estimación comercial; los datos y condiciones deben confirmarse antes de aceptar.</footer></main><script>window.addEventListener("load",()=>setTimeout(()=>window.print(),250));</script></body></html>`);
    popup.document.close();
  }

  function render() {
    $("#today").textContent = new Date().toLocaleDateString("es-MX", { weekday: "short", day: "numeric", month: "short" });
    const quoted = db.quotes.reduce((sum, quote) => sum + calc(quote).total, 0);
    const receivable = backend.connected ? live.invoices.reduce((sum, invoice) => sum + Number(invoice.balance_due || 0), 0) : db.quotes.filter((quote) => quote.status === "Lista para FEL").reduce((sum, quote) => sum + calc(quote).total, 0);
    $("#stat-quoted").textContent = money(quoted);
    $("#stat-quotes-count").textContent = `${db.quotes.length} cotizaciones`;
    $("#stat-receivable").textContent = money(receivable);
    $("#stat-projects").textContent = db.projects.filter((project) => !["Terminada", "Cancelada"].includes(project.status)).length;
    $("#stat-clients").textContent = db.clients.length;
    const inventoryNav = document.querySelector('[data-view="inventario"]');
    if (inventoryNav) inventoryNav.hidden = !backend.connected || !can("inventory.view_stockbalance");
    const purchasingNav = document.querySelector('[data-view="compras"]');
    if (purchasingNav) purchasingNav.hidden = !backend.connected || !can("purchasing.view_purchaseorder");
    const opportunityNav = document.querySelector('[data-view="oportunidades"]');
    if (opportunityNav) opportunityNav.hidden = !backend.connected || !can("sales.view_opportunity");
    const supportNav = document.querySelector('[data-view="soporte"]');
    if (supportNav) supportNav.hidden = !backend.connected || !can("support.view_supportticket");
    $("#new-opportunity").hidden = !backend.connected || !can("sales.add_opportunity");
    $("#opportunity-notice").hidden = backend.connected && can("sales.view_opportunity");
    document.querySelectorAll("[data-new-quote]").forEach((button) => { button.hidden = !can("sales.add_quote"); });
    $("#save-quote-template").hidden = !backend.connected || !can("sales.add_quote");
    $("#new-client").hidden = !can("sales.add_customer");
    $("#import-clients").hidden = !backend.connected || !can("sales.add_customer") || !can("sales.view_customer");
    $("#quote-count").textContent = db.quotes.length;
    $("#recent-quotes").innerHTML = db.quotes.slice().sort(byDate).slice(0, 5).map((quote) => quoteRow(quote)).join("") || `<tr><td colspan="5" class="empty">Aún no hay cotizaciones.</td></tr>`;
    $("#all-quotes").innerHTML = filteredQuotes().map((quote) => quoteRow(quote, true)).join("") || `<tr><td colspan="7" class="empty"><strong>No hay cotizaciones que mostrar</strong>Prueba otro filtro o crea una cotización nueva.</td></tr>`;
    $("#quote-table-summary").textContent = `${db.quotes.length} cotizaciones registradas`;
    $("#activity-list").innerHTML = db.activities.slice(0, 5).map((item) => `<div class="activity-item"><div class="activity-icon">${escapeHtml(item.icon)}</div><div><strong>${escapeHtml(item.text)}</strong><time>${escapeHtml(item.time)}</time></div></div>`).join("") || `<div class="empty">${backend.connected ? "La actividad se mostrará conforme se registren movimientos." : "Sin actividad reciente."}</div>`;
    renderOpportunityReminders();
    renderClients(); renderProjects(); renderSupportTickets(); renderOpportunities(); renderOpportunityReport(); renderInventory(); renderPurchasing(); renderExpenses(); renderFEL(); renderLedger(); renderTrialBalance(); renderGeneralLedger();
    $("#q-client").innerHTML = db.clients.map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)}</option>`).join("");
    $("#q-template").innerHTML = `<option value="">Cotización en blanco</option>${live.quoteTemplates.filter((template) => template.is_active).map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.name)}</option>`).join("")}`;
    updateQuoteOpportunityOptions();
    $("#opportunity-customer").innerHTML = `<option value="">Prospecto nuevo</option>${db.clients.map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)}</option>`).join("")}`;
    $("#opportunity-owner").innerHTML = `<option value="">Sin asignar</option>${live.opportunityAssignees.map((person) => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}</option>`).join("")}`;
    $("#activity-assignee").innerHTML = `<option value="">Sin asignar</option>${live.opportunityAssignees.map((person) => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}</option>`).join("")}`;
    $("#opportunity-activity-form").hidden = !can("sales.add_opportunityactivity");
    updateConnectionState();
  }

  function filteredQuotes() {
    const term = ($("#all-quote-search")?.value || "").toLowerCase(), state = $("#quote-filter")?.value || "";
    return db.quotes.filter((quote) => `${quote.id} ${quote.title} ${clientOf(quote.clientId).name}`.toLowerCase().includes(term) && (!state || quote.status === state)).slice().sort(byDate);
  }

  function renderClients() {
    $("#client-list").innerHTML = db.clients.map((client) => `<article class="card client-card"><div class="client-card-top"><span class="client-avatar" style="width:39px;height:39px;font-size:12px">${escapeHtml(initials(client.name))}</span><div>${backend.connected && can("sales.view_customer") ? `<button class="btn-quiet" data-client-contacts="${escapeHtml(client.id)}">Contactos</button>` : ""}${can("sales.change_customer") ? `<button class="btn-quiet" data-client-edit="${escapeHtml(client.id)}">Editar</button>` : ""}</div></div><h3>${escapeHtml(client.name)}</h3><p>${escapeHtml(client.rfc || "RFC pendiente")}</p><div class="client-info"><span>✉ &nbsp;${escapeHtml(client.email || "Correo pendiente")}</span><span>☎ &nbsp;${escapeHtml(client.phone || "Teléfono pendiente")}</span><span>▧ &nbsp;${escapeHtml(client.regime || "Datos fiscales pendientes")}</span></div></article>`).join("") || `<div class="card empty"><strong>Empieza por registrar clientes</strong>Sus datos se usarán en cotizaciones y facturación.</div>`;
  }

  function filteredOpportunities() {
    const term = $("#opportunity-search")?.value?.trim().toLowerCase() || "";
    const stage = $("#opportunity-filter")?.value || "";
    return db.opportunities.filter((item) => `${item.name} ${item.company_name} ${item.contact_name} ${item.customer_name}`.toLowerCase().includes(term) && (!stage || item.stage === stage));
  }

  function renderOpportunityReport() {
    const panel = $("#opportunity-report"), report = live.opportunityReport;
    if (!panel) return;
    panel.hidden = !backend.connected || !can("sales.view_opportunity") || !report;
    if (panel.hidden) return;
    $("#opportunity-report-total").textContent = report.total;
    $("#opportunity-report-open").textContent = `${report.open_count} · ${money(report.open_revenue)}`;
    $("#opportunity-report-weighted").textContent = money(report.weighted_revenue);
    $("#opportunity-report-win-rate").textContent = report.win_rate == null ? "—" : `${Number(report.win_rate).toFixed(1)}%`;
    const sources = [...(report.by_source || [])].sort((a, b) => Number(b.weighted_revenue || 0) - Number(a.weighted_revenue || 0));
    $("#opportunity-report-sources").innerHTML = sources.map((item) => `<tr><td>${escapeHtml(item.source || "Sin origen")}</td><td>${item.count}</td><td>${item.won}</td><td>${item.lost}</td><td>${item.win_rate == null ? "—" : `${Number(item.win_rate).toFixed(1)}%`}</td><td class="money">${money(item.weighted_revenue || 0)}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">Aún no hay oportunidades en este periodo.</td></tr>`;
    const campaigns = [...(report.by_campaign || [])].sort((a, b) => Number(b.weighted_revenue || 0) - Number(a.weighted_revenue || 0));
    $("#opportunity-report-campaigns").innerHTML = campaigns.map((item) => `<tr><td>${escapeHtml(item.utm_campaign || "Sin nombre")}</td><td>${escapeHtml([item.utm_source, item.utm_medium].filter(Boolean).join(" / ") || "Sin atribución")}</td><td>${item.count}</td><td>${item.won}</td><td>${item.lost}</td><td>${item.win_rate == null ? "—" : `${Number(item.win_rate).toFixed(1)}%`}</td><td class="money">${money(item.weighted_revenue || 0)}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">Aún no hay oportunidades atribuidas a campañas.</td></tr>`;
  }

  async function loadOpportunityReport() {
    const query = new URLSearchParams();
    if ($("#opportunity-report-from").value) query.set("date_from", $("#opportunity-report-from").value);
    if ($("#opportunity-report-to").value) query.set("date_to", $("#opportunity-report-to").value);
    const suffix = query.toString();
    try { live.opportunityReport = await apiRequest(`opportunities/report/${suffix ? `?${suffix}` : ""}`); renderOpportunityReport(); }
    catch (error) { toast(error.message); }
  }

  function renderOpportunities() {
    const rows = filteredOpportunities().map((item) => {
      const relatedQuotes = db.quotes.filter((quote) => quote.opportunityId === item.id || quote.opportunity === item.id);
      const pendingActivities = live.opportunityActivities.filter((activity) => activity.opportunity === item.id && activity.status === "planned").length;
      const organization = item.customer_name || item.company_name || "Sin empresa";
      const isOpen = !["won", "lost"].includes(item.stage);
      const actions = [];
      if (backend.connected && can("sales.change_opportunity")) actions.push(`<button class="btn-quiet" data-opportunity-edit="${escapeHtml(item.id)}">Editar</button>`);
      if (backend.connected && item.stage === "new" && can("sales.transition_opportunity")) actions.push(`<button class="btn-quiet" data-opportunity-qualify="${escapeHtml(item.id)}">Calificar</button>`);
      if (backend.connected && isOpen && item.customer && can("sales.add_quote")) actions.push(`<button class="btn-quiet" data-opportunity-quote="${escapeHtml(item.id)}">Cotizar</button>`);
      if (backend.connected && isOpen && !item.customer && can("sales.transition_opportunity")) actions.push(`<button class="btn-quiet" data-opportunity-convert="${escapeHtml(item.id)}">Convertir a cliente</button>`);
      if (backend.connected && isOpen && can("sales.transition_opportunity")) actions.push(`<button class="btn-quiet" data-opportunity-lost="${escapeHtml(item.id)}">Perdida</button>`);
      if (backend.connected && item.stage === "lost" && can("sales.transition_opportunity")) actions.push(`<button class="btn-quiet" data-opportunity-reopen="${escapeHtml(item.id)}">Reabrir</button>`);
      if (backend.connected && can("sales.view_opportunityactivity")) actions.push(`<button class="btn-quiet" data-opportunity-activities="${escapeHtml(item.id)}">Seguimiento${pendingActivities ? ` · ${pendingActivities}` : ""}</button>`);
      return `<tr><td><strong>${escapeHtml(item.name)}</strong>${item.source ? `<small class="muted">${escapeHtml(item.source)}</small>` : ""}</td><td>${escapeHtml(organization)}${item.contact_name ? `<small class="muted">${escapeHtml(item.contact_name)}</small>` : ""}</td><td>${badge(apiStateLabel(item.stage))}</td><td class="money">${money(item.expected_revenue)}</td><td>${Number(item.probability) || 0}%</td><td>${item.expected_close_date ? new Date(`${item.expected_close_date}T12:00:00`).toLocaleDateString("es-MX") : "—"}</td><td>${relatedQuotes.length}</td><td>${pendingActivities}</td><td><div class="quote-actions">${actions.join("")}</div></td></tr>`;
    }).join("");
    $("#opportunity-list").innerHTML = rows || `<tr><td colspan="9" class="empty"><strong>${backend.connected ? "No hay oportunidades que mostrar" : "Conecta el ERP para ver el pipeline"}</strong>${backend.connected ? "Registra el primer contacto comercial para iniciar el seguimiento." : "Las oportunidades se guardan en la base central del ERP."}</td></tr>`;
    $("#opportunity-summary").textContent = `${db.opportunities.length} oportunidades · ${db.opportunities.filter((item) => !["won", "lost"].includes(item.stage)).length} abiertas`;
  }

  function updateQuoteOpportunityOptions() {
    const select = $("#q-opportunity");
    if (!select) return;
    const customerId = $("#q-client")?.value;
    const available = db.opportunities.filter((item) => item.customer === customerId && !["won", "lost"].includes(item.stage));
    const selected = select.value;
    select.innerHTML = `<option value="">Sin oportunidad relacionada</option>${available.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("")}`;
    if (available.some((item) => item.id === selected)) select.value = selected;
  }

  async function updateQuoteContactOptions(selectedId = "") {
    const select = $("#q-customer-contact");
    if (!select) return;
    select.innerHTML = '<option value="">Usar correo del cliente</option>';
    const customerId = $("#q-client")?.value;
    if (!backend.connected || !customerId) return;
    try {
      const contacts = await apiList(`customer-contacts/?customer=${encodeURIComponent(customerId)}`);
      const eligible = contacts.filter((contact) => contact.is_active && contact.email);
      select.innerHTML = `<option value="">Usar correo del cliente</option>${eligible.map((contact) => `<option value="${escapeHtml(contact.id)}">${escapeHtml(contact.name)}${contact.is_primary ? " · Principal" : ""} · ${escapeHtml(contact.email)}</option>`).join("")}`;
      if (eligible.some((contact) => contact.id === selectedId)) select.value = selectedId;
      else if (!selectedId) select.value = eligible.find((contact) => contact.is_primary)?.id || "";
    } catch (error) { toast(`No se pudieron cargar los contactos del cliente: ${error.message}`); }
  }

  async function updateQuoteSiteOptions() {
    const select = $("#q-service-site");
    if (!select) return;
    select.innerHTML = '<option value="">Sin sitio de servicio</option>';
    const customerId = $("#q-client")?.value;
    if (!backend.connected || !customerId) return;
    try {
      const sites = await apiList(`customer-sites/?customer=${encodeURIComponent(customerId)}`);
      select.innerHTML = `<option value="">Sin sitio de servicio</option>${sites.map((site) => `<option value="${escapeHtml(site.id)}">${escapeHtml(site.name)} · ${escapeHtml(site.address)}</option>`).join("")}`;
    } catch (error) { toast(`No se pudieron cargar los sitios del cliente: ${error.message}`); }
  }

  function renderOpportunityActivities(opportunityId) {
    const activities = live.opportunityActivities.filter((activity) => activity.opportunity === opportunityId).slice().sort((a, b) => String(a.due_at).localeCompare(String(b.due_at)));
    $("#opportunity-activity-list").innerHTML = activities.map((activity) => {
      const due = new Date(activity.due_at).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" });
      const status = ({ planned: "Pendiente", done: "Completada", cancelled: "Cancelada" })[activity.status] || activity.status;
      const type = ({ call: "Llamada", email: "Correo", meeting: "Reunión", task: "Tarea" })[activity.activity_type] || activity.activity_type;
      const actions = activity.status === "planned" ? `${can("sales.complete_opportunityactivity") ? `<button class="btn-quiet" data-activity-complete="${escapeHtml(activity.id)}">Completar</button>` : ""}${can("sales.change_opportunityactivity") ? `<button class="btn-quiet" data-activity-cancel="${escapeHtml(activity.id)}">Cancelar</button>` : ""}` : "";
      return `<tr><td><strong>${escapeHtml(activity.title)}</strong><small class="muted">${escapeHtml(type)} · ${escapeHtml(activity.assigned_to_name || "Sin responsable")}</small>${activity.note ? `<small class="muted">${escapeHtml(activity.note)}</small>` : ""}</td><td>${escapeHtml(due)}</td><td>${badge(status)}</td><td>${actions}</td></tr>`;
    }).join("") || `<tr><td colspan="4" class="empty">No hay seguimientos registrados para esta oportunidad.</td></tr>`;
  }

  function renderOpportunityReminders() {
    const panel = $("#opportunity-reminders");
    if (!panel) return;
    const visible = backend.connected && can("sales.view_opportunityactivity");
    panel.hidden = !visible;
    if (!visible) return;
    const now = Date.now(), horizon = now + 7 * 24 * 60 * 60 * 1000;
    const due = live.opportunityActivities
      .filter((activity) => activity.status === "planned" && new Date(activity.due_at).getTime() <= horizon)
      .filter((activity) => db.opportunities.some((item) => item.id === activity.opportunity))
      .sort((a, b) => new Date(a.due_at) - new Date(b.due_at));
    const overdue = due.filter((activity) => new Date(activity.due_at).getTime() < now).length;
    const upcoming = due.length - overdue;
    $("#opportunity-reminders-summary").textContent = `${overdue} vencido${overdue === 1 ? "" : "s"} · ${upcoming} próximo${upcoming === 1 ? "" : "s"} en siete días`;
    $("#opportunity-reminder-list").innerHTML = due.slice(0, 8).map((activity) => {
      const opportunity = db.opportunities.find((item) => item.id === activity.opportunity);
      const dueAt = new Date(activity.due_at), isOverdue = dueAt.getTime() < now;
      const type = ({ call: "Llamada", email: "Correo", meeting: "Reunión", task: "Tarea" })[activity.activity_type] || "Seguimiento";
      const label = isOverdue ? "Vencido" : dueAt.toDateString() === new Date(now).toDateString() ? "Hoy" : "Próximo";
      return `<tr><td><strong>${escapeHtml(activity.title)}</strong><small class="muted">${escapeHtml(type)} · ${escapeHtml(label)}</small></td><td>${escapeHtml(opportunity.name)}</td><td>${escapeHtml(activity.assigned_to_name || "Sin responsable")}</td><td>${escapeHtml(dueAt.toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" }))}</td><td><button class="btn-quiet" data-reminder-opportunity="${escapeHtml(opportunity.id)}">Abrir</button></td></tr>`;
    }).join("") || `<tr><td colspan="5" class="empty">No hay seguimientos vencidos ni próximos durante los siguientes siete días.</td></tr>`;
  }

  function openOpportunityConversion(opportunityId) {
    const opportunity = db.opportunities.find((item) => item.id === opportunityId);
    if (!opportunity) return;
    const form = $("#opportunity-convert-form");
    form.reset(); form.dataset.opportunity = opportunity.id;
    $("#convert-opportunity-label").textContent = `${opportunity.name} · ${opportunity.company_name || opportunity.contact_name || "Prospecto"}`;
    $("#convert-existing-customer").innerHTML = `<option value="">Selecciona un cliente</option>${db.clients.map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)}${client.rfc ? ` · ${escapeHtml(client.rfc)}` : ""}</option>`).join("")}`;
    $("#convert-customer-mode").value = "existing";
    $("#convert-existing-fields").hidden = false; $("#convert-new-fields").hidden = true;
    $("#convert-existing-customer").required = true; $("#convert-name").required = false;
    $("#convert-name").value = opportunity.company_name || opportunity.contact_name || "";
    $("#convert-email").value = opportunity.email || ""; $("#convert-phone").value = opportunity.phone || "";
    $("#opportunity-convert-modal").classList.add("open");
  }

  function openOpportunityActivities(opportunityId) {
    const opportunity = db.opportunities.find((item) => item.id === opportunityId);
    if (!opportunity) return;
    $("#activity-opportunity-id").value = opportunity.id;
    $("#activity-opportunity-label").textContent = `${opportunity.name} · ${opportunity.customer_name || opportunity.company_name || "Prospecto"}`;
    $("#opportunity-activity-form").reset();
    const due = new Date(Date.now() + 60 * 60 * 1000);
    due.setMinutes(Math.ceil(due.getMinutes() / 15) * 15, 0, 0);
    $("#activity-due-at").value = new Date(due.getTime() - due.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    $("#activity-assignee").innerHTML = `<option value="">Sin asignar</option>${live.opportunityAssignees.map((person) => `<option value="${escapeHtml(person.id)}">${escapeHtml(person.name)}</option>`).join("")}`;
    $("#opportunity-activity-form").hidden = !can("sales.add_opportunityactivity");
    renderOpportunityActivities(opportunityId);
    $("#opportunity-activities-modal").classList.add("open");
  }

  function localDateISO(date) { return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`; }
  function mondayOfISO(dateISO) { const date = new Date(`${dateISO}T12:00:00`); date.setDate(date.getDate() - ((date.getDay() + 6) % 7)); return date; }
  function renderWeeklyAgenda() {
    const picker = $("#agenda-week");
    if (!picker) return;
    const start = mondayOfISO(picker.value || localDateISO(new Date()));
    const end = new Date(start); end.setDate(end.getDate() + 6);
    const days = Array.from({ length: 7 }, (_, index) => { const day = new Date(start); day.setDate(start.getDate() + index); const iso = localDateISO(day); const entries = live.workOrders.filter((work) => work.scheduled_start && localDateISO(new Date(work.scheduled_start)) === iso && work.status !== "cancelled").sort((a, b) => a.scheduled_start.localeCompare(b.scheduled_start));
      const events = entries.map((work) => { const begin = new Date(work.scheduled_start); const finish = work.scheduled_end ? new Date(work.scheduled_end) : null; const time = `${begin.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}${finish ? `–${finish.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}` : ""}`; return `<article class="agenda-event"><strong>${escapeHtml(time)} · ${escapeHtml(work.title)}</strong><small>${escapeHtml(work.sales_order_number || "Orden de servicio")} · ${escapeHtml(work.customer_name || "Sin cliente")}</small><small>${escapeHtml(work.assigned_to_name || "Sin responsable")}</small></article>`; }).join("");
      return `<div class="agenda-day"><div class="agenda-day-title">${escapeHtml(day.toLocaleDateString("es-MX", { weekday: "short", day: "numeric", month: "short" }))}</div>${events || `<span class="agenda-empty">Sin servicios programados</span>`}</div>`;
    });
    $("#agenda-week-label").textContent = `${start.toLocaleDateString("es-MX", { day: "numeric", month: "long" })} – ${end.toLocaleDateString("es-MX", { day: "numeric", month: "long", year: "numeric" })}`;
    $("#agenda-grid").innerHTML = days.join("");
  }

  function renderWorkHoursReport() {
    const panel = $("#work-hours-report-panel");
    if (!panel) return;
    const permitted = backend.connected && can("sales.view_workorder");
    panel.hidden = !permitted;
    if (!permitted) return;
    const report = live.workHoursReport;
    const status = { planned: "Programada", in_progress: "En curso", blocked: "Bloqueada", done: "Terminada", cancelled: "Cancelada" };
    $("#work-hours-summary").textContent = report
      ? `${report.date_from} a ${report.date_to} · ${Number(report.totals.hours || 0).toFixed(2)} h · ${report.totals.entries} registros · ${report.totals.work_orders} servicios · ${report.totals.people} personas`
      : "Consulta las horas registradas en un periodo de hasta un año.";
    $("#work-hours-orders").innerHTML = report?.by_work_order?.map((row) => `<tr><td class="quote-no">${escapeHtml(row.number)}</td><td>${escapeHtml(row.customer_name)}</td><td>${escapeHtml(row.title)}</td><td>${escapeHtml(status[row.status] || row.status)}</td><td>${Number(row.hours).toFixed(2)}</td><td>${row.entries}</td><td>${row.people}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">No hay horas en el periodo consultado.</td></tr>`;
    $("#work-hours-people").innerHTML = report?.by_person?.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${Number(row.hours).toFixed(2)}</td><td>${row.entries}</td><td>${row.work_orders}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">No hay horas en el periodo consultado.</td></tr>`;
  }

  async function loadWorkHoursReport() {
    if (!backend.connected || !can("sales.view_workorder")) return;
    const query = new URLSearchParams();
    if ($("#work-hours-from").value) query.set("date_from", $("#work-hours-from").value);
    if ($("#work-hours-to").value) query.set("date_to", $("#work-hours-to").value);
    try {
      live.workHoursReport = await apiRequest(`work-orders/hours-report/?${query.toString()}`);
      renderWorkHoursReport();
    } catch (error) { toast(error.message); }
  }

  function renderProjects() {
    renderWorkHoursReport();
    renderWeeklyAgenda();
    $("#project-list").innerHTML = db.projects.map((project) => {
      const work = live.workOrders.find((item) => item.id === project.workOrderId);
      const linkedInvoices = backend.connected && project.salesOrderId ? live.invoices.filter((invoice) => invoice.sales_order === project.salesOrderId) : [];
      const billableStates = new Set(["open", "partial", "paid", "credited"]);
      const draftInvoiceTotal = linkedInvoices.filter((invoice) => invoice.state === "draft").reduce((sum, invoice) => sum + Number(invoice.total || 0), 0);
      const internalInvoiceTotal = linkedInvoices.filter((invoice) => billableStates.has(invoice.state)).reduce((sum, invoice) => sum + Number(invoice.total || 0), 0);
      const receivableBalance = linkedInvoices.filter((invoice) => billableStates.has(invoice.state)).reduce((sum, invoice) => sum + Number(invoice.balance_due || 0), 0);
      const pendingInvoiceValue = (work?.invoiceable_lines || []).reduce((sum, line) => {
        const gross = round2(Number(line.remaining_quantity || 0) * Number(line.unit_price || 0));
        const discount = round2(gross * Number(line.discount_percent || 0) / 100);
        const subtotal = round2(gross - discount);
        return sum + subtotal + round2(subtotal * Number(line.tax_rate || 0) / 100);
      }, 0);
      const commercialSummary = backend.connected && work ? `<section class="work-logs"><div class="work-logs-head"><strong>Resumen comercial</strong><span>Importes MXN · sin costos</span></div><div class="project-meta"><span>Venta aceptada (con IVA) <strong>${money(work.approved_total)}</strong></span><span>Pendiente de facturar <strong>${work.status === "cancelled" ? "No facturable · orden cancelada" : money(pendingInvoiceValue)}</strong></span></div><div class="project-meta"><span>Facturas internas no canceladas <strong>${money(internalInvoiceTotal)}</strong></span><span>En borrador <strong>${money(draftInvoiceTotal)}</strong></span><span>Saldo CxC <strong>${money(receivableBalance)}</strong></span></div><small class="muted">Las facturas internas no confirman por sí solas el timbrado CFDI. El saldo considera pagos y notas de crédito aplicados.</small></section>` : "";
      const actions = [];
      if (backend.connected && work) {
        if (work.status === "planned" && can("sales.transition_workorder")) actions.push(`<button class="btn btn-light btn-small" data-work-status="${escapeHtml(work.id)}" data-target="in_progress">Iniciar trabajo</button>`);
        else if (work.status === "in_progress" && can("sales.transition_workorder")) actions.push(`<button class="btn btn-light btn-small" data-work-status="${escapeHtml(work.id)}" data-target="done">Marcar terminado</button>`);
        if (["planned", "in_progress", "done"].includes(work.status) && work.invoiceable_lines?.length && can("billing.add_customerinvoice")) actions.push(`<button class="btn btn-primary btn-small" data-create-invoice="${escapeHtml(work.id)}">${linkedInvoices.length ? "Facturar avance" : "Crear factura"}</button>`);
        linkedInvoices.forEach((invoice) => actions.push(`<button class="btn btn-light btn-small" data-view-link="facturacion">${escapeHtml(invoice.number)}</button>`));
        if (can("sales.schedule_workorder")) actions.push(`<button class="btn btn-light btn-small" data-work-edit="${escapeHtml(work.id)}">Programar / asignar</button>`);
        else if (work.status === "in_progress" && can("sales.change_workorder")) actions.push(`<button class="btn btn-light btn-small" data-work-edit="${escapeHtml(work.id)}">Registrar cierre</button>`);
        if (can("sales.view_workorderevidence")) actions.push(`<button class="btn btn-light btn-small" data-work-evidence="${escapeHtml(work.id)}">Evidencia</button>`);
        if (work.status === "in_progress" && can("sales.log_workorder_hours")) actions.push(`<button class="btn btn-light btn-small" data-work-log="${escapeHtml(work.id)}">Registrar horas</button>`);
        if (["planned", "in_progress"].includes(work.status) && can("inventory.issue_stock")) actions.push(`<button class="btn btn-light btn-small" data-stock-work="${escapeHtml(work.id)}">Materiales</button>`);
      }
      const customer = project.clientName || clientOf(project.clientId).name;
      const schedule = work?.scheduled_start ? new Date(work.scheduled_start).toLocaleString("es-MX", { dateStyle: "medium", timeStyle: "short" }) : "Sin fecha programada";
      const assignee = work?.assigned_to_name || "Sin responsable asignado";
      const logs = work?.time_logs || [];
      const recentLogs = logs.slice(0, 3).map((log) => `<div class="work-log"><span>${escapeHtml(log.work_date)} · ${escapeHtml(log.created_by_name)}</span><strong>${escapeHtml(log.hours)} h</strong><small>${escapeHtml(log.description)}</small></div>`).join("");
      const workMaterialMovements = work ? live.inventory.movements.filter((movement) => movement.work_order === work.id && ["issue", "return"].includes(movement.kind)) : [];
      const materials = workMaterialMovements.slice(0, 3);
      const recentMaterials = materials.map((movement) => {
        const timestamp = movement.created_at ? new Date(movement.created_at).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "short" }) : "Fecha sin dato";
        const details = [
          movement.location_code ? `Ubicación ${movement.location_code}` : "",
          movement.created_by_name ? `Registró ${movement.created_by_name}` : "",
          movement.serial_numbers?.length ? `Series: ${movement.serial_numbers.join(", ")}` : "",
          movement.note || "",
        ].filter(Boolean).map(escapeHtml).join(" · ");
        return `<div class="work-log"><span>${escapeHtml(movement.product_sku)} · ${movement.kind === "issue" ? "entregado" : "devuelto"} · ${escapeHtml(timestamp)}</span><strong>${escapeHtml(movement.quantity)} ${escapeHtml(movement.product_unit || "")}</strong><small>${escapeHtml(movement.product_name)}${details ? ` · ${details}` : ""}</small></div>`;
      }).join("");
      const reservations = work ? live.inventory.reservations.filter((reservation) => reservation.work_order === work.id) : [];
      const reservationRows = reservations.map((reservation) => `<div class="work-log"><span>${escapeHtml(reservation.product_sku)} · ${reservation.state === "active" ? "reservado" : reservation.state === "fulfilled" ? "surtido" : "liberado"}</span><strong>${escapeHtml(reservation.remaining_quantity)} ${escapeHtml(reservation.product_unit || "")}</strong><small>${escapeHtml(reservation.location_code)} · ${escapeHtml(reservation.product_name)}${reservation.state === "active" && can("inventory.issue_stock") ? ` <button class="btn btn-light btn-small" data-reservation-release="${escapeHtml(reservation.id)}">Liberar</button>` : ""}</small></div>`).join("");
      const materialRequirements = work?.material_requirements || [];
      const materialProgress = new Map();
      for (const requirement of materialRequirements) {
        const current = materialProgress.get(requirement.product) || { required: 0, issued: 0, returned: 0, reserved: 0 };
        current.required += Number(requirement.required_quantity) || 0;
        materialProgress.set(requirement.product, current);
      }
      for (const movement of live.inventory.movements) {
        if (movement.work_order !== work?.id || !materialProgress.has(movement.product)) continue;
        const current = materialProgress.get(movement.product);
        if (movement.kind === "issue") current.issued += Number(movement.quantity) || 0;
        if (movement.kind === "return") current.returned += Number(movement.quantity) || 0;
      }
      for (const reservation of live.inventory.reservations) {
        if (reservation.work_order === work?.id && reservation.state === "active" && materialProgress.has(reservation.product)) {
          materialProgress.get(reservation.product).reserved += Number(reservation.remaining_quantity) || 0;
        }
      }
      const requirementRows = materialRequirements.map((item) => {
        const progress = materialProgress.get(item.product) || { required: 0, issued: 0, returned: 0, reserved: 0 };
        const netIssued = Math.max(0, progress.issued - progress.returned);
        const remaining = Math.max(0, progress.required - netIssued - progress.reserved);
        const product = live.inventory.products.find((candidate) => candidate.id === item.product);
        const firstProductRow = materialRequirements.find((requirement) => requirement.product === item.product) === item;
        const canReserve = firstProductRow && remaining > 0 && product?.tracking_policy === "quantity" && ["planned", "in_progress"].includes(work.status) && can("inventory.issue_stock");
        const canAssignSupplyLocation = can("inventory.change_reorderrule") && ["planned", "in_progress", "blocked"].includes(work.status);
        const progressText = firstProductRow && can("inventory.view_stockmovement")
          ? `Producto: ${progress.required.toFixed(3)} requeridos · ${progress.issued.toFixed(3)} entregados · ${progress.returned.toFixed(3)} devueltos · ${progress.reserved.toFixed(3)} reservados · ${remaining.toFixed(3)} pendientes.`
          : "";
        return `<div class="work-log"><span>${escapeHtml(item.product_sku)} · ${escapeHtml(item.source_description)}</span><strong>${escapeHtml(item.required_quantity)} ${escapeHtml(item.product_unit)}</strong><small>Destino de surtido: ${escapeHtml(item.supply_location_name)}${canAssignSupplyLocation ? ` <button class="btn btn-light btn-small" data-material-location="${escapeHtml(work.id)}" data-requirement="${escapeHtml(item.id)}" data-location-code="${escapeHtml(item.supply_location_code)}">Cambiar</button>` : ""}${progressText ? ` · ${escapeHtml(progressText)}` : ""}${canReserve ? ` <button class="btn btn-light btn-small" data-stock-reserve-requirement="${escapeHtml(work.id)}" data-reserve-product="${escapeHtml(item.product)}" data-reserve-quantity="${remaining.toFixed(3)}">Reservar pendiente</button>` : ""}</small></div>`;
      }).join("");
      const checklist = work?.checklist_items || [];
      const checklistDone = checklist.filter((item) => item.is_completed).length;
      return `<article class="card project-card"><div class="project-card-top">${badge(project.status)}<span class="muted" style="font-size:11px">${escapeHtml(project.id)}</span></div><h3>${escapeHtml(project.title)}</h3><p>${escapeHtml(customer)}</p><div class="project-progress"><span style="width:${Math.max(0, Math.min(100, Number(project.progress) || 0))}%"></span></div><div class="project-meta"><span>${Number(project.progress) || 0}% completado</span><span>${escapeHtml(schedule)}</span></div>${commercialSummary}${work ? `<div class="project-meta" style="margin-top:7px"><span>Responsable</span><strong>${escapeHtml(assignee)}</strong></div>${work.service_address ? `<div class="work-log"><strong>Domicilio del servicio${work.customer_site_name ? ` · ${escapeHtml(work.customer_site_name)}` : ""}</strong><small>${escapeHtml(work.service_address)}</small>${work.service_contact_name || work.service_contact_phone || work.service_contact_email ? `<small>Contacto: ${escapeHtml(work.service_contact_name || "")} ${escapeHtml(work.service_contact_phone || "")} ${escapeHtml(work.service_contact_email || "")}</small>` : ""}</div>` : ""}${checklist.length ? `<div class="project-meta" style="margin-top:7px"><span>Lista de verificación</span><strong>${checklistDone}/${checklist.length} completados</strong></div>` : ""}<section class="work-logs"><div class="work-logs-head"><strong>${escapeHtml(work.total_logged_hours || "0.00")} h registradas</strong><span>${logs.length} entradas recientes</span></div>${recentLogs || `<small class="muted">Aún no hay horas capturadas.</small>`}</section><section class="work-logs"><div class="work-logs-head"><strong>Materiales del trabajo</strong><span>${workMaterialMovements.length} movimientos${can("inventory.view_stockmovement") && workMaterialMovements.length ? ` · <button type="button" class="btn btn-light btn-small" data-export-work-materials="${escapeHtml(work.id)}">Exportar CSV</button>` : ""}</span></div>${recentMaterials || `<small class="muted">Sin materiales registrados.</small>`}</section>${materialRequirements.length ? `<section class="work-logs"><div class="work-logs-head"><strong>Materiales de la cotización aprobada</strong><span>${materialRequirements.length} renglones requeridos</span></div>${requirementRows}</section>` : ""}${reservations.length ? `<section class="work-logs"><div class="work-logs-head"><strong>Reservas de almacén</strong><span>${reservations.filter((item) => item.state === "active").length} activas</span></div>${reservationRows}</section>` : ""}` : ""}${actions.length ? `<div class="project-actions">${actions.join("")}</div>` : ""}</article>`;
    }).join("") || `<div class="card empty"><strong>Aún no hay proyectos</strong>Al aprobar una cotización se crea el seguimiento del trabajo.</div>`;
  }

  const supportStatusLabels = { new: "Nuevo", in_progress: "En atención", waiting_customer: "En espera del cliente", resolved: "Resuelto", closed: "Cerrado", cancelled: "Cancelado" };
  const supportPriorityLabels = { low: "Baja", normal: "Normal", high: "Alta", urgent: "Urgente" };
  const supportSlaLabels = { unconfigured: "Sin objetivo configurado", on_track: "En plazo", overdue: "Vencido", met: "Cumplido", breached: "Incumplido", not_applicable: "No aplica" };
  const supportNextStatuses = {
    new: [["in_progress", "Atender"], ["cancelled", "Cancelar"]],
    in_progress: [["waiting_customer", "Esperar cliente"], ["resolved", "Resolver"], ["cancelled", "Cancelar"]],
    waiting_customer: [["in_progress", "Reanudar"], ["resolved", "Resolver"]],
    resolved: [["closed", "Cerrar"], ["in_progress", "Reabrir"]],
    closed: [["in_progress", "Reabrir"]],
    cancelled: [],
  };

  function renderSupportTickets() {
    const canView = backend.connected && can("support.view_supportticket");
    const nav = document.querySelector('[data-view="soporte"]');
    if (nav) nav.hidden = !canView;
    $("#new-support-ticket").hidden = !backend.connected || !can("support.add_supportticket");
    $("#support-notice").hidden = canView;
    const term = $("#support-search").value.trim().toLowerCase();
    const status = $("#support-status-filter").value;
    const rows = live.supportTickets.filter((ticket) => {
      const text = `${ticket.number} ${ticket.title} ${ticket.customer_name} ${ticket.serial_number || ""} ${ticket.description}`.toLowerCase();
      return (!term || text.includes(term)) && (!status || ticket.status === status);
    });
    $("#support-summary").textContent = `${live.supportTickets.length} tickets registrados`;
    $("#support-ticket-list").innerHTML = rows.map((ticket) => {
      const actions = (supportNextStatuses[ticket.status] || []).filter(([target]) => can("support.transition_supportticket")).map(([target, label]) => `<button class="btn btn-light btn-small" data-ticket-transition="${escapeHtml(ticket.id)}" data-target-status="${target}">${label}</button>`).join(" ");
      return `<tr><td><button class="btn-quiet" data-ticket-detail="${escapeHtml(ticket.id)}">${escapeHtml(ticket.number)}</button></td><td>${escapeHtml(ticket.customer_name)}${ticket.work_order_number ? `<small class="muted" style="display:block">${escapeHtml(ticket.work_order_number)}</small>` : ""}${ticket.serial_number ? `<small class="muted" style="display:block">${escapeHtml(ticket.serial_product_name || "Equipo")} · ${escapeHtml(ticket.serial_number)}</small>` : ""}</td><td>${escapeHtml(ticket.title)}</td><td>${escapeHtml(supportPriorityLabels[ticket.priority] || ticket.priority)}</td><td>${badge(supportStatusLabels[ticket.status] || ticket.status)}</td><td>${escapeHtml(ticket.assigned_to_name || "Sin asignar")}</td><td>${new Date(ticket.updated_at).toLocaleString("es-MX", { dateStyle: "short", timeStyle: "short" })}</td><td>${actions}</td></tr>`;
    }).join("") || `<tr><td colspan="8" class="empty">${canView ? "No hay tickets que coincidan con la búsqueda." : "Conecta el ERP y usa un rol autorizado para abrir soporte."}</td></tr>`;
  }

  function openSupportTicketDetail(ticketId) {
    const ticket = live.supportTickets.find((item) => item.id === ticketId);
    if (!ticket) return;
    const warrantyLabel = ({ recorded_date_valid: "fecha registrada vigente al abrir el ticket", recorded_date_expired: "fecha registrada vencida al abrir el ticket", unknown: "sin fecha de vencimiento registrada" })[ticket.warranty_window_status] || "sin equipo relacionado";
    const repairCase = live.repairCases.find((item) => item.ticket_number === ticket.number);
    $("#support-ticket-detail").dataset.ticketId = ticket.id;
    $("#support-ticket-detail-title").textContent = `${ticket.number} · ${ticket.title}`;
    $("#support-ticket-detail-body").innerHTML = `<p><strong>${escapeHtml(ticket.customer_name)}</strong>${ticket.work_order_number ? ` · ${escapeHtml(ticket.work_order_number)}` : ""}</p>${ticket.serial_number ? `<p><strong>Equipo:</strong> ${escapeHtml(ticket.serial_product_name || "Equipo")} · serie ${escapeHtml(ticket.serial_number)}${ticket.serial_warranty_until ? ` · garantía registrada hasta ${escapeHtml(ticket.serial_warranty_until)}` : ""}<br><small class="muted">${escapeHtml(warrantyLabel)}. Es una referencia de fechas, no una confirmación de cobertura.</small></p>` : ""}<p>${escapeHtml(ticket.description).replace(/\n/g, "<br>")}</p><p class="muted">${escapeHtml(supportPriorityLabels[ticket.priority] || ticket.priority)} · ${escapeHtml(supportStatusLabels[ticket.status] || ticket.status)} · ${escapeHtml(ticket.assigned_to_name || "Sin asignar")}</p>`;
    const slaInfo = document.createElement("p");
    const responseDue = ticket.sla_response_due_at ? " · límite " + new Date(ticket.sla_response_due_at).toLocaleString("es-MX") : "";
    const resolutionDue = ticket.sla_resolution_due_at ? " · límite " + new Date(ticket.sla_resolution_due_at).toLocaleString("es-MX") : "";
    slaInfo.textContent = "SLA — primera respuesta: " + (supportSlaLabels[ticket.sla_response_status] || "Sin dato") + responseDue + "; resolución: " + (supportSlaLabels[ticket.sla_resolution_status] || "Sin dato") + resolutionDue + ". El plazo de resolución se pausa mientras se espera al cliente; se cuentan minutos corridos.";
    $("#support-ticket-detail-body").appendChild(slaInfo);
    const repairStatusLabels = { received: "Recibido", diagnosis: "En diagnóstico", waiting_authorization: "Espera autorización", authorized: "Autorizado", in_repair: "En reparación", ready: "Listo", closed: "Cerrado", unrepairable: "No reparable", cancelled: "Cancelado" };
    const custodyStatusLabels = { not_received: "No recibido físicamente", in_custody: "En custodia de Redmagna", returned: "Devuelto al cliente" };
    const repairEventLabels = { created: "Expediente creado", details_updated: "Datos actualizados", status_changed: "Cambio de estado", custody_received: "Recepción física", custody_returned: "Devolución física" };
    $("#support-create-repair-case").hidden = Boolean(repairCase) || !ticket.serial_unit || !can("repairs.add_repaircase");
    $("#support-repair-panel").hidden = !repairCase;
    if (repairCase) {
      $("#support-repair-summary").textContent = `${repairCase.number} · ${repairStatusLabels[repairCase.status] || repairCase.status} · garantía: ${{ pending: "pendiente", covered: "revisada como cubierta", not_covered: "revisada sin cobertura", unknown: "no determinada" }[repairCase.warranty_review] || repairCase.warranty_review}. Esta revisión no decide por sí sola cobertura contractual ni genera cobros.`;
      const custodyLabels = { not_received: "El equipo no está registrado como recibido físicamente.", in_custody: `En custodia de Redmagna desde ${new Date(repairCase.custody_received_at).toLocaleString("es-MX")} por ${repairCase.custody_received_by_name || "usuario registrado"}. Condición al recibir: ${repairCase.intake_condition || "Sin detalle"}`, returned: `Devuelto el ${new Date(repairCase.custody_returned_at).toLocaleString("es-MX")} por ${repairCase.custody_returned_by_name || "usuario registrado"}. Condición al devolver: ${repairCase.return_condition || "Sin detalle"}` };
      $("#repair-custody-summary").textContent = custodyLabels[repairCase.custody_status] || "Estado de custodia sin clasificar.";
      $("#repair-diagnosis").value = repairCase.diagnosis || "";
      $("#repair-proposed-work").value = repairCase.proposed_work || "";
      $("#repair-warranty-review").value = repairCase.warranty_review || "pending";
      const editable = can("repairs.change_repaircase") && !["closed", "cancelled"].includes(repairCase.status);
      $("#repair-case-update-form").hidden = !editable;
      $("#repair-case-update-form").querySelectorAll("input,textarea,select,button").forEach((field) => { field.disabled = !editable; });
      const next = { received: [["diagnosis", "Iniciar diagnóstico"], ["cancelled", "Cancelar expediente"]], diagnosis: [["waiting_authorization", "Solicitar autorización"], ["unrepairable", "Marcar no reparable"], ["cancelled", "Cancelar expediente"]], waiting_authorization: [["authorized", "Registrar autorización"], ["cancelled", "Cerrar sin autorización"]], authorized: [["in_repair", "Iniciar reparación"], ["cancelled", "Cancelar expediente"]], in_repair: [["ready", "Marcar listo"], ["unrepairable", "Marcar no reparable"]], ready: [["closed", "Cerrar expediente"]], unrepairable: [["closed", "Cerrar expediente"]] }[repairCase.status] || [];
      $("#repair-case-transitions").innerHTML = next.filter(() => can("repairs.transition_repaircase")).map(([target, label]) => `<button type="button" class="btn btn-light btn-small" data-repair-transition="${escapeHtml(repairCase.id)}" data-target-status="${target}">${label}</button>`).join(" ");
      const custodyActions = [];
      if (repairCase.custody_status === "not_received" && !["closed", "cancelled"].includes(repairCase.status)) custodyActions.push(["receive", "Registrar recepción física"]);
      if (repairCase.custody_status === "in_custody" && ["ready", "unrepairable", "cancelled"].includes(repairCase.status)) custodyActions.push(["return", "Registrar devolución al cliente"]);
      $("#repair-case-custody").innerHTML = can("repairs.transition_repaircase") ? custodyActions.map(([action, label]) => `<button type="button" class="btn btn-light btn-small" data-repair-custody="${escapeHtml(repairCase.id)}" data-custody-action="${action}">${label}</button>`).join(" ") : "";
      $("#repair-case-events").innerHTML = (repairCase.events || []).map((item) => {
        const isCustodyEvent = ["custody_received", "custody_returned"].includes(item.action);
        const statusLabels = isCustodyEvent ? custodyStatusLabels : repairStatusLabels;
        const transition = item.from_status ? ` · ${escapeHtml(statusLabels[item.from_status] || item.from_status)} → ${escapeHtml(statusLabels[item.to_status] || item.to_status)}` : "";
        return `<div class="work-log"><span>${escapeHtml(item.actor_name)} · ${new Date(item.occurred_at).toLocaleString("es-MX")}</span><small>${escapeHtml(repairEventLabels[item.action] || item.action)}${transition}${item.detail ? ` · ${escapeHtml(item.detail)}` : ""}</small></div>`;
      }).join("");
    } else {
      $("#repair-case-update-form").hidden = true;
      $("#repair-case-transitions").innerHTML = "";
      $("#repair-case-custody").innerHTML = "";
      $("#repair-custody-summary").textContent = "";
    }
    const notificationLabels = { pending: "Aviso al equipo pendiente", sent: "Aviso al equipo enviado", failed: "No se pudo enviar el aviso", skipped: "Sin correo de responsable disponible" };
    $("#support-ticket-messages").innerHTML = (ticket.messages || []).map((message) => `<div class="work-log"><span>${escapeHtml(message.author_name || "Equipo Redmagna")} · ${new Date(message.created_at).toLocaleString("es-MX")}</span><small>${message.is_public ? "Mensaje compartido con el cliente" : "Nota interna"}${message.staff_notification_status && message.staff_notification_status !== "not_applicable" ? ` · ${escapeHtml(notificationLabels[message.staff_notification_status] || message.staff_notification_status)}` : ""}</small><small>${escapeHtml(message.body).replace(/\n/g, "<br>")}</small></div>`).join("") || `<small class="muted">Sin mensajes todavía.</small>`;
    $("#support-ticket-note-form").hidden = !can("support.add_supportticketmessage") || ["closed", "cancelled"].includes(ticket.status);
    $("#support-send-portal-link").hidden = !can("support.send_supportticket_portal_link");
    $("#support-ticket-public-field").hidden = !can("support.publish_supportticketmessage");
    $("#support-ticket-note").value = "";
    $("#support-ticket-public").checked = false;
    $("#support-ticket-detail").classList.add("open");
  }

  function updateSupportWorkOrderOptions() {
    const customerId = $("#support-customer").value;
    const workOrders = live.workOrders.filter((work) => db.quotes.some((quote) => quote.id === work.sales_order_number && quote.clientId === customerId));
    $("#support-work-order").innerHTML = `<option value="">Sin orden relacionada</option>${workOrders.map((work) => `<option value="${escapeHtml(work.id)}">${escapeHtml(work.sales_order_number)} · ${escapeHtml(work.title)}</option>`).join("")}`;
  }

  async function updateSupportAssets() {
    const customerId = $("#support-customer").value;
    const select = $("#support-serial-unit");
    select.innerHTML = `<option value="">Sin equipo asociado</option>`;
    if (!customerId || !backend.connected || !can("support.view_supportticket")) return;
    try {
      const assets = await apiList(`support/tickets/assets/?customer=${encodeURIComponent(customerId)}`);
      if (customerId !== $("#support-customer").value) return;
      select.innerHTML = `<option value="">Sin equipo asociado</option>${assets.map((asset) => { const warranty = asset.warranty_until ? ` · garantía registrada ${asset.warranty_until < todayISO() ? "vencida" : "vigente"} hasta ${escapeHtml(asset.warranty_until)}` : " · sin vencimiento registrado"; return `<option value="${escapeHtml(asset.id)}">${escapeHtml(asset.product_sku)} · ${escapeHtml(asset.serial_number)}${warranty}</option>`; }).join("")}`;
    } catch {
      select.innerHTML = `<option value="">No se pudieron cargar equipos</option>`;
    }
  }

  function openSupportTicketForm() {
    const form = $("#support-ticket-form"); form.reset();
    $("#support-customer").innerHTML = `<option value="">Selecciona un cliente</option>${db.clients.map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)}</option>`).join("")}`;
    updateSupportWorkOrderOptions();
    updateSupportAssets();
    const assign = can("support.assign_supportticket");
    $("#support-assignee-field").hidden = !assign;
    $("#support-assignee").innerHTML = `<option value="">Sin asignar</option>${live.supportAssignees.map((user) => `<option value="${escapeHtml(user.id)}">${escapeHtml(user.name)}</option>`).join("")}`;
    $("#support-ticket-modal").classList.add("open");
  }

  const toDateTimeInput = (value) => {
    if (!value) return "";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "" : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };

  let workOrderSites = [];
  let workOrderChecklistTemplates = [];

  async function openWorkOrderEditor(workOrderId) {
    const work = live.workOrders.find((item) => item.id === workOrderId);
    if (!work) return;
    const canSchedule = can("sales.schedule_workorder");
    const canEditClosure = canSchedule || (can("sales.change_workorder") && work.status === "in_progress");
    $("#work-order-modal-title").textContent = canSchedule ? `${work.sales_order_number} · ${work.customer_name}` : `${work.sales_order_number} · Registrar cierre`;
    $("#work-order-form").querySelector('button[type="submit"]').textContent = canSchedule ? "Guardar cambios" : "Guardar nota";
    $("#work-order-id").value = work.id;
    $("#wo-assignee").innerHTML = `<option value="">Sin responsable</option>${live.assignees.map((user) => `<option value="${escapeHtml(user.id)}">${escapeHtml(user.name)}</option>`).join("")}`;
    $("#wo-assignee").value = work.assigned_to || "";
    $("#wo-start").value = toDateTimeInput(work.scheduled_start);
    $("#wo-end").value = toDateTimeInput(work.scheduled_end);
    $("#wo-service-address").value = work.service_address || "";
    $("#wo-service-contact").value = work.service_contact_name || "";
    $("#wo-service-phone").value = work.service_contact_phone || "";
    $("#wo-service-email").value = work.service_contact_email || "";
    const frozen = Boolean(work.customer_acceptance);
    ["#wo-assignee", "#wo-start", "#wo-end", "#wo-service-address", "#wo-service-contact", "#wo-service-phone", "#wo-service-email", "#wo-customer-site", "#wo-site-name", "#wo-save-site"].forEach((selector) => { $(selector).disabled = frozen || !canSchedule; });
    $("#wo-assignee").closest(".field").hidden = !canSchedule;
    $("#wo-start").closest(".form-row").hidden = !canSchedule;
    $("#wo-customer-site").closest(".form-row").hidden = !canSchedule;
    $("#wo-service-address").closest(".field").hidden = !canSchedule;
    $("#wo-service-contact").closest(".form-row").hidden = !canSchedule;
    $("#wo-notes").readOnly = frozen || !canEditClosure;
    $("#wo-save-site").hidden = !canSchedule;
    $("#wo-site-name").value = work.customer_site_name || "";
    $("#wo-customer-site").innerHTML = '<option value="">Domicilio manual</option>';
    workOrderSites = [];
    try {
      workOrderSites = canSchedule ? await apiList(`customer-sites/?customer=${encodeURIComponent(work.customer_id)}`) : [];
      const currentSiteAvailable = workOrderSites.some((site) => site.id === work.customer_site);
      const archivedSiteOption = work.customer_site && !currentSiteAvailable ? `<option value="${escapeHtml(work.customer_site)}">${escapeHtml(work.customer_site_name || "Sitio archivado")}</option>` : "";
      $("#wo-customer-site").innerHTML = `<option value="">Domicilio manual</option>${archivedSiteOption}${workOrderSites.map((site) => `<option value="${escapeHtml(site.id)}">${escapeHtml(site.name)} · ${escapeHtml(site.address)}</option>`).join("")}`;
      $("#wo-customer-site").value = work.customer_site || "";
    } catch (error) { toast(`No se pudieron cargar los sitios guardados: ${error.message}`); }
    try {
      workOrderChecklistTemplates = await apiList("checklist-templates/");
      $("#wo-checklist-template").innerHTML = `<option value="">Selecciona una plantilla</option>${workOrderChecklistTemplates.map((template) => `<option value="${escapeHtml(template.id)}">${escapeHtml(template.name)} · ${template.items.length} puntos</option>`).join("")}`;
    } catch (error) { workOrderChecklistTemplates = []; toast(`No se pudieron cargar las plantillas: ${error.message}`); }
    $("#wo-notes").value = work.completion_notes || "";
    renderWorkOrderChecklist(work);
    $("#work-order-modal").classList.add("open");
  }

  $("#wo-customer-site").addEventListener("change", () => {
    const site = workOrderSites.find((item) => item.id === $("#wo-customer-site").value);
    if (!site) { $("#wo-site-name").value = ""; return; }
    $("#wo-site-name").value = site.name;
    $("#wo-service-address").value = site.address;
    $("#wo-service-contact").value = site.contact_name || "";
    $("#wo-service-phone").value = site.phone || "";
    $("#wo-service-email").value = site.email || "";
  });

  function openWorkOrderInvoice(workOrderId) {
    const work = live.workOrders.find((item) => item.id === workOrderId);
    if (!work?.invoiceable_lines?.length) { toast("Esta orden ya no tiene cantidades pendientes por facturar."); return; }
    $("#invoice-milestone-modal-title").textContent = `${work.sales_order_number} · ${work.customer_name}`;
    $("#invoice-milestone-order-id").value = work.id;
    $("#invoice-milestone-lines").innerHTML = work.invoiceable_lines.map((line) => `<article class="work-log"><strong>${escapeHtml(line.description)}</strong><small class="muted" style="display:block">Cotizado ${escapeHtml(line.quoted_quantity)} · facturado ${escapeHtml(line.invoiced_quantity)} · pendiente ${escapeHtml(line.remaining_quantity)}</small><div class="form-row" style="align-items:end;margin-top:8px"><div class="field" style="margin:0"><label>Cantidad para esta factura</label><input type="number" min="0" max="${escapeHtml(line.remaining_quantity)}" step="0.001" value="${escapeHtml(line.remaining_quantity)}" data-invoice-quote-line="${escapeHtml(line.quote_line)}" data-unit-price="${escapeHtml(line.unit_price)}" data-discount-percent="${escapeHtml(line.discount_percent || 0)}" data-tax-rate="${escapeHtml(line.tax_rate)}"></div><span class="muted">${money(line.unit_price)} c/u · descuento ${Number(line.discount_percent || 0).toFixed(2)}% · IVA ${escapeHtml(line.tax_rate)}%</span></div></article>`).join("");
    updateWorkOrderInvoicePreview();
    $("#invoice-milestone-modal").classList.add("open");
  }

  function updateWorkOrderInvoicePreview() {
    const inputs = Array.from(document.querySelectorAll("[data-invoice-quote-line]"));
    const subtotal = inputs.reduce((sum, input) => { const gross = round2((Number(input.value) || 0) * Number(input.dataset.unitPrice)); const discount = round2(gross * Number(input.dataset.discountPercent || 0) / 100); return sum + round2(gross - discount); }, 0);
    const tax = inputs.reduce((sum, input) => { const gross = round2((Number(input.value) || 0) * Number(input.dataset.unitPrice)); const net = round2(gross - round2(gross * Number(input.dataset.discountPercent || 0) / 100)); return sum + round2(net * Number(input.dataset.taxRate) / 100); }, 0);
    $("#invoice-milestone-subtotal").textContent = money(subtotal);
    $("#invoice-milestone-tax").textContent = money(tax);
    $("#invoice-milestone-total").textContent = money(subtotal + tax);
  }

  async function openWorkOrderEvidence(workOrderId) {
    const work = live.workOrders.find((item) => item.id === workOrderId);
    if (!work || !can("sales.view_workorderevidence")) return;
    $("#work-evidence-title").textContent = `${work.sales_order_number} · Evidencia del servicio`;
    $("#work-evidence-form").dataset.workOrderId = work.id;
    $("#work-evidence-form").reset();
    $("#work-evidence-form").hidden = !can("sales.add_workorderevidence");
    $("#work-order-evidence-modal").classList.add("open");
    try { await refreshWorkOrderEvidence(work.id); }
    catch (error) { toast(error.message); }
  }

  async function refreshWorkOrderEvidence(workOrderId) {
    const items = await apiRequest(`work-orders/${workOrderId}/evidence/`);
    $("#work-evidence-list").innerHTML = items.map((item) => `<article class="work-log"><div style="display:flex;justify-content:space-between;gap:10px;align-items:center"><div><strong>${escapeHtml(item.original_name)}</strong><small class="muted" style="display:block">${escapeHtml(item.uploaded_by_name)} · ${new Date(item.created_at).toLocaleString("es-MX")} · ${(Number(item.file_size) / 1048576).toFixed(2)} MB</small>${item.description ? `<small>${escapeHtml(item.description)}</small>` : ""}</div><button type="button" class="btn btn-light btn-small" data-evidence-download="${escapeHtml(item.download_path)}" data-evidence-filename="${escapeHtml(item.original_name)}">Descargar</button></div></article>`).join("") || `<small class="muted">Aún no hay evidencia cargada para esta orden.</small>`;
  }

  function renderWorkOrderChecklist(work) {
    const items = work.checklist_items || [];
    const editable = (can("sales.schedule_workorder") || can("sales.transition_workorder")) && !["done", "cancelled"].includes(work.status) && !work.customer_acceptance;
    $("#wo-checklist-section").hidden = !backend.connected;
    $("#wo-checklist-summary").textContent = `${items.filter((item) => item.is_completed).length}/${items.length} completados`;
    $("#wo-checklist-items").innerHTML = items.map((item) => `<label class="work-log" style="display:flex;align-items:center;gap:10px"><input type="checkbox" data-work-checklist="${escapeHtml(item.id)}" ${item.is_completed ? "checked" : ""} ${editable ? "" : "disabled"}><span style="flex:1">${escapeHtml(item.label)}</span><small class="muted">${escapeHtml(item.completed_by_name || "Pendiente")}</small></label>`).join("") || `<small class="muted">Agrega los pasos que deben completarse para este trabajo.</small>`;
    $("#wo-checklist-add-row").hidden = !editable;
    $("#wo-checklist-template-row").hidden = !editable || items.length > 0 || !workOrderChecklistTemplates.length;
    $("#wo-checklist-template-save-row").hidden = !editable || items.length === 0;
    const acceptance = work.customer_acceptance;
    const acceptanceEligible = work.status === "in_progress" && Boolean(work.completion_notes?.trim()) && items.length > 0 && items.every((item) => item.is_completed);
    $("#wo-customer-acceptance-section").hidden = !backend.connected;
    $("#wo-customer-acceptance-display").innerHTML = acceptance ? `<div class="work-log"><strong>Conformidad capturada de ${escapeHtml(acceptance.customer_contact_name)}</strong><small class="muted" style="display:block">${new Date(acceptance.accepted_at).toLocaleString("es-MX")} · Registró ${escapeHtml(acceptance.captured_by_name)}</small>${acceptance.customer_contact_email ? `<small>${escapeHtml(acceptance.customer_contact_email)}</small>` : ""}${acceptance.notes ? `<p>${escapeHtml(acceptance.notes)}</p>` : ""}</div>` : !acceptanceEligible ? `<small class="muted">Registra la nota de cierre y completa la lista de verificación para capturar la conformidad antes de terminar.</small>` : "";
    $("#wo-customer-acceptance-fields").hidden = Boolean(acceptance) || !acceptanceEligible || !can("sales.record_workorder_acceptance");
    $("#wo-notes").readOnly = Boolean(acceptance);
    $("#wo-customer-contact-name").value = "";
    $("#wo-customer-contact-email").value = "";
    $("#wo-customer-acceptance-notes").value = "";
    $("#wo-customer-confirmed").checked = false;
  }

  function openWorkLogEditor(workOrderId) {
    const work = live.workOrders.find((item) => item.id === workOrderId);
    if (!work) return;
    $("#work-log-title").textContent = `${work.sales_order_number} · ${work.customer_name}`;
    $("#work-log-order-id").value = work.id;
    $("#work-log-date").value = todayISO();
    $("#work-log-hours").value = "";
    $("#work-log-description").value = "";
    $("#work-log-modal").classList.add("open");
  }

  let stockSerialPage = 0;
  const STOCK_SERIAL_PAGE_SIZE = 100;

  function renderInventory() {
    const permitted = backend.connected && can("inventory.view_stockbalance");
    const canViewProducts = backend.connected && can("inventory.view_product");
    $("#inventory-product-catalog").hidden = !canViewProducts;
    $("#import-products").hidden = !canViewProducts || !can("inventory.add_product");
    const products = live.inventory.products || [];
    const canChangeProduct = can("inventory.change_product");
    $("#inventory-product-list").innerHTML = canViewProducts ? products.map((product) => `<tr><td class="quote-no">${escapeHtml(product.sku)}</td><td>${escapeHtml(product.barcode || "—")}</td><td>${escapeHtml(product.name)}</td><td>${product.kind === "service" ? "Servicio" : "Producto"}</td><td>${escapeHtml(product.unit)}</td><td>${escapeHtml(product.sat_product_service_key || "—")}</td><td>${escapeHtml(product.sat_unit_key || "—")}</td><td>${escapeHtml(product.sat_tax_object || "02")} · ${escapeHtml(product.sat_tax_factor || "Tasa")}</td><td>${product.sat_border_8_eligible ? "Revisado" : "Sin revisar"}</td><td>${product.is_active ? "Activo" : "Inactivo"}</td><td>${canChangeProduct ? `<button class="btn btn-light btn-small" data-product-edit="${escapeHtml(product.id)}">Editar</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="11" class="empty">Aún no hay productos ni servicios en el catálogo.</td></tr>` : `<tr><td colspan="11" class="empty">Conecta un usuario con permisos para consultar productos.</td></tr>`;
    $("#inventory-locations-card").hidden = !backend.connected || !can("inventory.view_stocklocation");
    $("#inventory-product-new").hidden = !backend.connected || !can("inventory.add_product");
    $("#inventory-receive").hidden = !permitted || !can("inventory.receive_stock");
    $("#inventory-adjust").hidden = !permitted || !can("inventory.adjust_stock");
    $("#inventory-location-new").hidden = !backend.connected || !can("inventory.add_stocklocation");
    $("#inventory-transfer").hidden = !permitted || !can("inventory.transfer_stock");
    if (!permitted) {
      $("#stock-list").innerHTML = `<tr><td colspan="8" class="empty">Conecta un usuario con permisos de inventario para consultar existencias.</td></tr>`;
      $("#inventory-location-list").innerHTML = `<tr><td colspan="5" class="empty">Conecta el ERP para consultar ubicaciones.</td></tr>`;
      $("#stock-movement-list").innerHTML = `<tr><td colspan="6" class="empty">Los movimientos aparecerán aquí.</td></tr>`;
      $("#stock-serial-list").innerHTML = `<tr><td colspan="7" class="empty">Conecta un usuario con permisos de inventario para consultar equipos.</td></tr>`;
      $("#stock-serial-search").disabled = true;
      $("#stock-serial-prev").disabled = true;
      $("#stock-serial-next").disabled = true;
      $("#stock-serial-page-info").textContent = "Conecta para consultar";
      $("#inventory-summary").textContent = "Conecta el sistema para ver existencias y movimientos.";
      return;
    }
    const { locations, balances, movements } = live.inventory;
    const countCard = $("#inventory-count-card");
    const canCount = backend.connected && can("inventory.adjust_stock");
    const canReviewCounts = backend.connected && can("inventory.review_inventorycount");
    countCard.hidden = !backend.connected || !can("inventory.view_inventorycount");
    $("#inventory-count-create").hidden = !canCount;
    const activeLocationsForCount = locations.filter((location) => location.is_active);
    const countLocation = $("#inventory-count-location");
    const selectedLocation = countLocation.value;
    countLocation.innerHTML = activeLocationsForCount.map((location) => `<option value="${escapeHtml(location.id)}">${escapeHtml(location.code)} · ${escapeHtml(location.name)}</option>`).join("");
    if (activeLocationsForCount.some((location) => location.id === selectedLocation)) countLocation.value = selectedLocation;
    $("#inventory-count-products").innerHTML = products.filter((product) => product.is_active && product.kind === "stockable").map((product) => `<option value="${escapeHtml(product.id)}">${escapeHtml(product.sku)} · ${escapeHtml(product.name)}${product.tracking_policy === "serial" ? " · por serie" : " · por cantidad"}</option>`).join("");
    const countStates = { draft: "En captura", submitted: "Pendiente de revisión", applied: "Aplicado" };
    $("#inventory-count-list").innerHTML = (live.inventory.counts || []).slice(0, 15).map((count) => {
      const lineRows = count.lines.map((line) => {
        const serial = line.tracking_policy === "serial";
        const serialHint = serial ? `<small class="muted" style="display:block">Series esperadas: ${escapeHtml((line.expected_serial_numbers || []).join(", ") || "ninguna")}</small>` : "";
        const editor = serial
          ? `<textarea rows="3" data-count-serials="${escapeHtml(line.id)}" placeholder="Escanea o escribe una serie por línea" aria-label="Series contadas de ${escapeHtml(line.product_sku)}">${escapeHtml((line.counted_serials || []).join("\n"))}</textarea>`
          : `<input type="number" min="0" step="0.001" data-count-quantity="${escapeHtml(line.id)}" value="${escapeHtml(line.counted_quantity ?? "")}" aria-label="Cantidad contada de ${escapeHtml(line.product_sku)}">`;
        const countedDisplay = serial ? `${escapeHtml(line.counted_quantity ?? "Pendiente")} series${line.counted_serials?.length ? `<small class="muted" style="display:block">${escapeHtml(line.counted_serials.join(", "))}</small>` : ""}` : `${escapeHtml(line.counted_quantity ?? "Pendiente")} ${escapeHtml(line.unit)}`;
        return `<tr><td><strong>${escapeHtml(line.product_sku)}</strong><small class="muted" style="display:block">${escapeHtml(line.product_name)}</small>${serialHint}</td><td>${escapeHtml(line.expected_quantity)} ${serial ? "series" : escapeHtml(line.unit)}</td><td>${count.state === "draft" && canCount ? `${editor} <button type="button" class="btn btn-light btn-small" data-count-record="${escapeHtml(count.id)}" data-count-line="${escapeHtml(line.id)}" data-count-serial="${serial}">Guardar</button>` : countedDisplay}</td><td>${line.difference == null ? "—" : `${Number(line.difference) > 0 ? "+" : ""}${escapeHtml(line.difference)}`}</td></tr>`;
      }).join("");
      const actions = [count.state === "draft" && canCount ? `<button type="button" class="btn btn-light btn-small" data-count-submit="${escapeHtml(count.id)}">Enviar a revisión</button>` : "", count.state === "submitted" && canReviewCounts ? `<button type="button" class="btn btn-primary btn-small" data-count-apply="${escapeHtml(count.id)}">Revisar y aplicar</button>` : ""].filter(Boolean).join(" ");
      return `<section class="work-log"><div class="work-logs-head"><strong>${escapeHtml(count.location_code)} · ${escapeHtml(countStates[count.state] || count.state)}</strong><span>${escapeHtml(new Date(count.created_at).toLocaleString("es-MX"))}</span></div><small>${escapeHtml(count.reason)} · Capturó ${escapeHtml(count.created_by_name || "")}${count.reviewed_by_name ? ` · Revisó ${escapeHtml(count.reviewed_by_name)}` : ""}</small><div class="table-wrap"><table><thead><tr><th>Producto</th><th>Esperado</th><th>Contado</th><th>Diferencia</th></tr></thead><tbody>${lineRows}</tbody></table></div>${actions ? `<div style="padding-top:8px">${actions}</div>` : ""}</section>`;
    }).join("") || `<p class="muted">Aún no hay conteos físicos.</p>`;
    $("#inventory-count-start").disabled = !activeLocationsForCount.length || !products.some((product) => product.is_active && product.kind === "stockable");
    const canChangeLocation = can("inventory.change_stocklocation");
    const reorderRules = live.inventory.reorderRules || [];
    const canManageReorder = can("inventory.change_reorderrule");
    $("#inventory-reorder-new").hidden = !backend.connected || !can("inventory.add_reorderrule");
    $("#inventory-reorder-list").innerHTML = reorderRules.map((rule) => `<tr><td class="quote-no">${escapeHtml(rule.product_sku)}</td><td>${escapeHtml(rule.product_name)}</td><td>${escapeHtml(rule.location_name)}</td><td class="money">${escapeHtml(rule.on_hand_quantity)} ${escapeHtml(rule.product_unit)}</td><td class="money">${escapeHtml(rule.reserved_quantity)} ${escapeHtml(rule.product_unit)}</td><td class="money">${escapeHtml(rule.unreserved_demand)} ${escapeHtml(rule.product_unit)}</td><td class="money">${escapeHtml(rule.incoming_quantity)} ${escapeHtml(rule.product_unit)}</td><td class="money">${escapeHtml(rule.projected_quantity)} ${escapeHtml(rule.product_unit)}</td><td class="money">${escapeHtml(rule.minimum_quantity)}</td><td class="money">${escapeHtml(rule.target_quantity)}</td><td class="money">${rule.suggested_quantity > 0 ? `<strong>${escapeHtml(rule.suggested_quantity)} ${escapeHtml(rule.product_unit)}</strong>` : "—"}</td><td>${rule.is_active ? "Activa" : "Inactiva"}</td><td>${can("inventory.view_reorderrule") ? `<button class="btn btn-light btn-small" data-reorder-forecast="${escapeHtml(rule.id)}">Previsión</button>` : ""} ${rule.suggested_quantity > 0 && can("purchasing.add_purchaseorder") ? `<button class="btn btn-light btn-small" data-reorder-purchase="${escapeHtml(rule.id)}">Crear borrador</button>` : ""} ${canManageReorder ? `<button class="btn btn-light btn-small" data-reorder-edit="${escapeHtml(rule.id)}">Editar</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="13" class="empty">No hay reglas configuradas. Define mínimos y objetivos para los productos que deban reabastecerse.</td></tr>`;
    $("#inventory-location-list").innerHTML = locations.map((location) => `<tr><td>${escapeHtml(location.code)}</td><td>${escapeHtml(location.barcode || "—")}</td><td>${escapeHtml(location.name)}</td><td>${location.is_active ? "Activa" : "Inactiva"}</td><td>${canChangeLocation ? `<button class="btn btn-light btn-small" data-location-toggle="${escapeHtml(location.id)}" data-active="${location.is_active}">${location.is_active ? "Desactivar" : "Activar"}</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">No hay ubicaciones activas.</td></tr>`;
    const stockable = products.filter((product) => product.kind === "stockable" && product.is_active);
    const rows = stockable.flatMap((product) => {
      const productBalances = balances.filter((balance) => balance.product === product.id);
      if (!productBalances.length) {
        const main = locations.find((location) => location.code === "MAIN");
        return [`<tr><td class="quote-no">${escapeHtml(product.sku)}</td><td>${escapeHtml(product.name)}</td><td>${escapeHtml(product.tracking_policy === "serial" ? "Por serie" : "Por cantidad")}</td><td>${escapeHtml(main?.name || "Almacén principal")}</td><td class="money">0.000</td><td class="money">0.000</td><td class="money">0.000</td><td>${escapeHtml(product.unit)}</td></tr>`];
      }
      return productBalances.map((balance) => `<tr><td class="quote-no">${escapeHtml(product.sku)}</td><td>${escapeHtml(product.name)}</td><td>${escapeHtml(product.tracking_policy === "serial" ? "Por serie" : "Por cantidad")}</td><td>${escapeHtml(balance.location_name)}</td><td class="money">${escapeHtml(balance.quantity)}</td><td class="money">${escapeHtml(balance.reserved_quantity || "0.000")}</td><td class="money">${escapeHtml(balance.available_quantity ?? balance.quantity)}</td><td>${escapeHtml(product.unit)}</td></tr>`);
    });
    $("#stock-list").innerHTML = rows.join("") || `<tr><td colspan="6" class="empty">No hay productos con existencias en el catálogo.</td></tr>`;
    const kinds = { receipt: "Entrada", issue: "Entrega a trabajo", return: "Devolución", adjustment_in: "Ajuste +", adjustment_out: "Ajuste −", transfer_out: "Traspaso enviado", transfer_in: "Traspaso recibido" };
    $("#stock-movement-list").innerHTML = movements.slice(0, 25).map((movement) => `<tr><td>${new Date(movement.created_at).toLocaleDateString("es-MX")}</td><td>${escapeHtml(kinds[movement.kind] || movement.kind)}</td><td class="quote-no">${escapeHtml(movement.product_sku)}</td><td>${escapeHtml(movement.product_name)}</td><td class="money">${escapeHtml(movement.quantity)} ${escapeHtml(movement.product_unit || "")}</td><td>${movement.counterpart_location_code ? `${escapeHtml(movement.location_code)} → ${escapeHtml(movement.counterpart_location_code)}` : escapeHtml(movement.work_order_number || movement.reference || movement.note || "—")}${movement.serial_numbers?.length ? `<small class="muted" style="display:block">Series: ${escapeHtml(movement.serial_numbers.join(", "))}</small>` : ""}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">Sin movimientos de inventario.</td></tr>`;
    const states = { in_stock: "En almacén", reserved: "Reservado para orden", assigned: "Entregado a una orden", installed: "Instalado con el cliente", retired: "Retirado" };
    const serialUnits = live.inventory.serialUnits || [];
    const normalizeSerialSearch = (value) => String(value || "").toLocaleLowerCase("es-MX").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const search = normalizeSerialSearch($("#stock-serial-search").value.trim());
    const filteredSerialUnits = search ? serialUnits.filter((unit) => {
      const origin = unit.purchase_origin || {};
      const haystack = [unit.serial_number, unit.product_sku, unit.product_name, states[unit.state], unit.customer_name, unit.location_code, unit.work_order_number, origin.purchase_order_number, origin.supplier_name, origin.purchase_line_number, origin.receipt_date, unit.warranty_until].join(" ");
      return normalizeSerialSearch(haystack).includes(search);
    }) : serialUnits;
    const serialPageCount = Math.ceil(filteredSerialUnits.length / STOCK_SERIAL_PAGE_SIZE);
    stockSerialPage = Math.min(stockSerialPage, Math.max(0, serialPageCount - 1));
    const visibleSerialUnits = filteredSerialUnits.slice(stockSerialPage * STOCK_SERIAL_PAGE_SIZE, (stockSerialPage + 1) * STOCK_SERIAL_PAGE_SIZE);
    $("#stock-serial-search").disabled = false;
    $("#stock-serial-prev").disabled = stockSerialPage <= 0;
    $("#stock-serial-next").disabled = serialPageCount === 0 || stockSerialPage >= serialPageCount - 1;
    $("#stock-serial-page-info").textContent = `${filteredSerialUnits.length} equipos · página ${serialPageCount ? stockSerialPage + 1 : 0} de ${serialPageCount}`;
    $("#stock-serial-list").innerHTML = visibleSerialUnits.map((unit) => {
      const workOrder = live.workOrders.find((item) => item.id === unit.work_order);
      const purchaseOrigin = unit.purchase_origin;
      const canInstall = unit.state === "assigned" && workOrder?.status === "done" && can("inventory.issue_stock");
      const canReserve = unit.state === "in_stock" && can("inventory.issue_stock") && live.workOrders.some((item) => ["planned", "in_progress"].includes(item.status));
      const canRelease = unit.state === "reserved" && can("inventory.issue_stock");
      return `<tr><td class="quote-no">${escapeHtml(unit.serial_number)}</td><td>${escapeHtml(unit.product_sku)}</td><td>${escapeHtml(unit.product_name)}${purchaseOrigin ? `<small class="muted" style="display:block">OC ${escapeHtml(purchaseOrigin.purchase_order_number)} · renglón ${escapeHtml(purchaseOrigin.purchase_line_number)} · ${escapeHtml(purchaseOrigin.supplier_name)} · recibida ${new Date(purchaseOrigin.receipt_date).toLocaleDateString("es-MX")}</small>` : ""}</td><td>${escapeHtml(states[unit.state] || unit.state)}</td><td>${escapeHtml(unit.customer_name || unit.location_code || unit.work_order_number || "—")}${unit.work_order_number ? `<small class="muted" style="display:block">Orden ${escapeHtml(unit.work_order_number)}</small>` : ""}</td><td>${escapeHtml(unit.warranty_until || "Sin dato")}</td><td>${canReserve ? `<button class="btn btn-light btn-small" data-stock-unit-reserve="${escapeHtml(unit.id)}">Reservar</button>` : ""} ${canRelease ? `<button class="btn btn-light btn-small" data-stock-unit-release="${escapeHtml(unit.id)}">Liberar reserva</button>` : ""} ${canInstall ? `<button class="btn btn-light btn-small" data-stock-unit-install="${escapeHtml(unit.id)}">Registrar instalación</button>` : ""}</td></tr>`;
    }).join("") || `<tr><td colspan="7" class="empty">${search ? "No hay equipos que coincidan con la búsqueda." : "No hay equipos serializados registrados."}</td></tr>`;
    $("#inventory-summary").textContent = `${stockable.length} productos con control de existencias · ${balances.length} saldos por ubicación · ${movements.length} movimientos`;
  }

  let sourcingDraftLines = [];
  const sourcingProductOptions = () => live.inventory.products.filter((product) => product.is_active && product.kind === "stockable").map((product) => `<option value="${escapeHtml(product.id)}">${escapeHtml(product.sku)} · ${escapeHtml(product.name)}</option>`).join("");
  function renderSourcing() {
    const canView = backend.connected && can("purchasing.view_purchasesourcingrequest");
    const canCreate = canView && can("purchasing.add_purchasesourcingrequest");
    const requests = live.purchasing.sourcing || [];
    $("#sourcing-create-card").hidden = !canCreate;
    $("#sourcing-list-card").hidden = !canView;
    if (canCreate) {
      $("#sourcing-notes").maxLength = 500;
      const locations = live.inventory.locations.filter((item) => item.is_active);
      $("#sourcing-location").innerHTML = locations.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.code)} · ${escapeHtml(item.name)}</option>`).join("");
      $("#sourcing-product").innerHTML = sourcingProductOptions();
      $("#sourcing-lines").innerHTML = sourcingDraftLines.map((line, index) => `<div class="work-log"><strong>${escapeHtml(live.inventory.products.find((product) => String(product.id) === String(line.product))?.name || "Producto")}</strong><span>${escapeHtml(line.quantity)} unidades</span><button type="button" class="btn btn-quiet btn-small" data-sourcing-remove-line="${index}">Quitar</button></div>`).join("") || `<p class="muted">Agrega uno o más productos para comparar sus precios.</p>`;
    }
    $("#sourcing-list").innerHTML = requests.map((request) => {
      const offers = request.offers || [];
      const offerRows = offers.map((offer) => {
        const breakdown = offer.lines.map((line) => `${escapeHtml(line.product_sku)}: ${money(line.unit_cost)} × ${escapeHtml(line.quantity)} = ${money(line.line_total)}`).join("<br>");
        const offerState = offer.state === "selected" ? "Seleccionada" : offer.state === "partial" ? "Seleccionada parcialmente" : offer.state === "rejected" ? "No seleccionada" : "Recibida";
        return `<tr><td>${escapeHtml(offer.supplier_name)}</td><td>${escapeHtml(offer.supplier_reference || "—")}</td><td>${breakdown}</td><td>${money(offer.total)}</td><td>${escapeHtml(offer.notes || "—")}</td><td>${escapeHtml(offer.expected_date || "—")}</td><td>${escapeHtml(offer.valid_until || "—")}</td><td>${badge(offerState)}</td></tr>`;
      }).join("");
      const lines = request.lines.map((line) => `${escapeHtml(line.product_sku)} · solicitado ${escapeHtml(line.quantity)}, adjudicado ${escapeHtml(line.awarded_quantity)}, pendiente ${escapeHtml(line.remaining_quantity)} ${escapeHtml(line.product_unit)}`).join("; ");
      const actionable = ["open", "partial"].includes(request.state);
      const canAward = actionable && can("purchasing.award_purchaseoffer") && offers.some((offer) => ["received", "partial"].includes(offer.state) && offer.lines.some((line) => Number(line.available_quantity) > 0));
      const actions = `${request.state === "open" && can("purchasing.send_purchasingsourcingrequest") || request.state === "partial" && can("purchasing.send_purchasingsourcingrequest") ? `<button type="button" class="btn btn-primary btn-small" data-sourcing-rfq="${escapeHtml(request.id)}">Enviar RFQ</button>` : ""}${actionable && can("purchasing.add_purchaseoffer") ? ` <button type="button" class="btn btn-light btn-small" data-sourcing-offer-add="${escapeHtml(request.id)}">＋ Registrar oferta</button>` : ""}${canAward ? ` <button type="button" class="btn btn-primary btn-small" data-sourcing-award-open="${escapeHtml(request.id)}">Adjudicar cantidades</button>` : ""}`;
      const eventLabels = { request_created: "Solicitud creada", rfq_email_attempt: "Intento de envío iniciado", rfq_email_sent: "RFQ enviada", rfq_email_failed: "Falló el envío de RFQ", rfq_email_uncertain: "Resultado del correo incierto", offer_received: "Oferta recibida", offer_awarded: "Renglones adjudicados" };
      const events = (request.events || []).map((item) => `<li><strong>${escapeHtml(eventLabels[item.action] || item.action)}</strong>${item.supplier_name ? ` · ${escapeHtml(item.supplier_name)}` : ""}${item.recipient_email ? ` · ${escapeHtml(item.recipient_email)}` : ""} · ${escapeHtml(item.actor_name)} · ${escapeHtml(new Date(item.occurred_at).toLocaleString("es-MX"))}${item.detail ? `<br>${escapeHtml(item.detail)}` : ""}</li>`).join("");
      const requestState = request.state === "open" ? "Abierta" : request.state === "partial" ? "Parcialmente adjudicada" : request.state === "awarded" ? "Adjudicada" : "Cancelada";
      const orders = (request.purchase_orders || []).map((order) => `${escapeHtml(order.number)} · ${escapeHtml(order.supplier_name)} · ${escapeHtml(purchaseStateLabel(order.status))}`).join("<br>");
      return `<article class="card" style="margin:12px 0;padding:14px"><div class="panel-head"><div><strong class="quote-no">${escapeHtml(request.number)}</strong> ${badge(requestState)}<p>${lines}<br>Recepción: ${escapeHtml(request.desired_date || "Sin fecha")} · ${escapeHtml(request.target_location_code || "")}</p>${orders ? `<p>Órdenes de compra:<br>${orders}</p>` : ""}</div>${actions}</div><div class="notice">El total comparado suma cantidades y precios cotizados; revisa impuestos y flete anotados en las condiciones antes de adjudicar.</div><div class="table-wrap"><table><thead><tr><th>Proveedor</th><th>Folio</th><th>Precios por producto (MXN)</th><th>Total cotizado</th><th>Condiciones (impuestos/flete)</th><th>Entrega</th><th>Vigencia</th><th>Estado</th></tr></thead><tbody>${offerRows || `<tr><td colspan="8" class="empty">Aún no hay ofertas registradas.</td></tr>`}</tbody></table></div><details style="margin-top:10px"><summary>Historial de solicitudes y ofertas (${(request.events || []).length})</summary><ol>${events || "<li>Sin eventos</li>"}</ol></details></article>`;
    }).join("") || `<p class="empty">No hay solicitudes de cotización para mostrar.</p>`;
  }

  let frameworkDraftLines = [];
  const activeStockProducts = () => live.inventory.products.filter((product) => product.is_active && product.kind === "stockable");
  function renderFrameworkDraftLines() {
    const products = activeStockProducts();
    $("#framework-lines").innerHTML = frameworkDraftLines.map((line, index) => {
      const used = new Set(frameworkDraftLines.filter((_, otherIndex) => otherIndex !== index).map((item) => String(item.product)));
      const available = products.filter((product) => !used.has(String(product.id)) || String(line.product) === String(product.id));
      return `<div class="line-item"><div class="form-row"><div class="field"><label>Producto</label><select data-framework-product required>${available.map((product) => `<option value="${escapeHtml(product.id)}" ${String(line.product) === String(product.id) ? "selected" : ""}>${escapeHtml(product.sku)} · ${escapeHtml(product.name)}</option>`).join("")}</select></div><div class="field"><label>Precio unitario MXN</label><input data-framework-cost type="number" min="0" step="0.01" value="${escapeHtml(line.unit_cost || "")}" required></div><div class="field"><label>Límite total (opcional)</label><input data-framework-limit type="number" min="0.001" step="0.001" value="${escapeHtml(line.quantity_limit || "")}" placeholder="Sin límite"></div><div class="field"><label>Descripción</label><input data-framework-description maxlength="300" value="${escapeHtml(line.description || "")}" placeholder="Especificación (opcional)"></div></div><button type="button" class="btn btn-quiet btn-small" data-framework-remove-line="${index}">Quitar producto</button></div>`;
    }).join("") || `<p class="muted">Agrega al menos un producto antes de guardar el acuerdo.</p>`;
  }

  function captureFrameworkDraftLines() {
    const rows = [...$("#framework-lines").querySelectorAll(".line-item")];
    if (!rows.length) return;
    frameworkDraftLines = rows.map((row) => ({
      product: row.querySelector("[data-framework-product]").value,
      unit_cost: row.querySelector("[data-framework-cost]").value,
      quantity_limit: row.querySelector("[data-framework-limit]").value,
      description: row.querySelector("[data-framework-description]").value,
    }));
  }

  function openFrameworkAgreement(agreementId = "") {
    const agreement = agreementId ? live.purchasing.frameworkAgreements.find((item) => String(item.id) === String(agreementId)) : null;
    const form = $("#framework-agreement-form");
    form.reset();
    $("#framework-supplier").innerHTML = live.purchasing.suppliers.filter((supplier) => supplier.is_active).map((supplier) => `<option value="${escapeHtml(supplier.id)}">${escapeHtml(supplier.name)}</option>`).join("");
    if (agreement) {
      form.dataset.edit = agreement.id;
      $("#framework-reference").value = agreement.reference;
      $("#framework-supplier").value = agreement.supplier;
      $("#framework-valid-from").value = agreement.valid_from;
      $("#framework-valid-until").value = agreement.valid_until;
      $("#framework-notes").value = agreement.notes || "";
      frameworkDraftLines = agreement.lines.map((line) => ({ product: line.product, unit_cost: line.unit_cost, quantity_limit: line.quantity_limit || "", description: line.description || "" }));
      $("#save-framework-agreement").textContent = "Guardar cambios";
    } else {
      delete form.dataset.edit;
      $("#framework-valid-from").value = todayISO();
      $("#framework-valid-until").value = "";
      frameworkDraftLines = activeStockProducts().length ? [{ product: activeStockProducts()[0].id, unit_cost: "", quantity_limit: "", description: "" }] : [];
      $("#save-framework-agreement").textContent = "Guardar borrador";
    }
    renderFrameworkDraftLines();
    form.hidden = false;
    form.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  function renderFrameworkAgreements() {
    const canView = backend.connected && can("purchasing.view_purchaseframeworkagreement");
    const agreements = live.purchasing.frameworkAgreements || [];
    const canCreate = canView && can("purchasing.add_purchaseframeworkagreement");
    $("#framework-agreements-section").hidden = !canView;
    $("#new-framework-agreement").hidden = !canCreate;
    const locationOptions = live.inventory.locations.filter((location) => location.is_active);
    $("#framework-agreement-list").innerHTML = agreements.map((agreement) => {
      const lines = agreement.lines.map((line) => {
        const committed = Number(line.committed_quantity || 0);
        const cap = line.quantity_limit == null ? "sin límite" : `${Math.max(0, Number(line.quantity_limit) - committed).toFixed(3)} / ${Number(line.quantity_limit).toFixed(3)} restantes`;
        return `${escapeHtml(line.product_sku)} · ${escapeHtml(line.product_name)} · ${money(line.unit_cost)} · ${cap}`;
      }).join("<br>");
      const status = agreement.status === "draft" ? "Borrador" : agreement.status === "active" ? "Vigente" : "Cerrado";
      const today = todayISO();
      const inDate = agreement.valid_from <= today && agreement.valid_until >= today;
      const actions = [];
      if (agreement.status === "draft" && can("purchasing.change_purchaseframeworkagreement")) actions.push(`<button type="button" class="btn btn-light btn-small" data-framework-edit="${escapeHtml(agreement.id)}">Editar</button>`);
      if (agreement.status === "draft" && can("purchasing.activate_purchaseframeworkagreement")) actions.push(`<button type="button" class="btn btn-primary btn-small" data-framework-activate="${escapeHtml(agreement.id)}">Activar</button>`);
      const hasAvailableLines = agreement.lines.some((line) => line.quantity_limit == null || Number(line.committed_quantity || 0) < Number(line.quantity_limit));
      if (agreement.status === "active" && inDate && hasAvailableLines && can("purchasing.order_purchaseframeworkagreement") && locationOptions.length) actions.push(`<button type="button" class="btn btn-primary btn-small" data-framework-order="${escapeHtml(agreement.id)}">＋ Crear orden</button>`);
      if (agreement.status === "active" && can("purchasing.close_purchaseframeworkagreement")) actions.push(`<button type="button" class="btn btn-quiet btn-small" data-framework-close="${escapeHtml(agreement.id)}">Cerrar acuerdo</button>`);
      return `<tr><td class="quote-no">${escapeHtml(agreement.reference)}</td><td>${escapeHtml(agreement.supplier_name)}</td><td>${escapeHtml(agreement.valid_from)} – ${escapeHtml(agreement.valid_until)}</td><td>${lines || "—"}</td><td>${badge(status)}${agreement.status === "active" && !inDate ? `<small class="muted" style="display:block">Fuera de vigencia</small>` : ""}</td><td>${actions.join(" ") || "—"}</td></tr>`;
    }).join("") || `<tr><td colspan="6" class="empty">No hay acuerdos marco registrados.</td></tr>`;
  }

  function openFrameworkOrder(agreementId) {
    const agreement = live.purchasing.frameworkAgreements.find((item) => String(item.id) === String(agreementId));
    const locations = live.inventory.locations.filter((location) => location.is_active);
    if (!agreement || !locations.length) return toast("Registra una ubicación activa antes de crear la orden.");
    const mainLocation = locations.find((location) => location.code === "MAIN") || locations[0];
    $("#framework-order-form").dataset.agreement = agreement.id;
    $("#framework-order-summary").textContent = `${agreement.reference} · ${agreement.supplier_name} · ${agreement.valid_from} a ${agreement.valid_until}`;
    $("#framework-order-location").innerHTML = locations.map((location) => `<option value="${escapeHtml(location.id)}" ${location.id === mainLocation.id ? "selected" : ""}>${escapeHtml(location.code)} · ${escapeHtml(location.name)}</option>`).join("");
    $("#framework-order-expected").value = "";
    $("#framework-order-notes").value = "";
    $("#framework-order-lines").innerHTML = agreement.lines.map((line) => {
      const remaining = line.quantity_limit == null ? null : Math.max(0, Number(line.quantity_limit) - Number(line.committed_quantity || 0));
      const max = remaining == null ? "" : `max="${remaining.toFixed(3)}"`;
      const disabled = remaining != null && remaining <= 0;
      const suggested = disabled ? "" : remaining != null && remaining < 1 ? remaining.toFixed(3) : "1.000";
      return `<div class="line-item" data-framework-order-line="${escapeHtml(line.id)}"><strong>${escapeHtml(line.product_sku)} · ${escapeHtml(line.product_name)}</strong><p>${escapeHtml(line.description || "")}${line.description ? " · " : ""}${money(line.unit_cost)} / unidad · ${remaining == null ? "sin límite de cantidad" : `${remaining.toFixed(3)} disponibles de ${escapeHtml(line.quantity_limit)}`}</p><div class="field"><label>Cantidad a pedir</label><input data-framework-order-quantity type="number" min="0.001" step="0.001" ${max} ${disabled ? "disabled" : ""} placeholder="Cantidad" value="${suggested}"></div></div>`;
    }).join("");
    $("#framework-order-modal").classList.add("open");
  }

  function purchaseStateLabel(state) {
    return ({ draft: "Borrador", ordered: "Solicitada", partial: "Recibida parcialmente", received: "Recibida", cancelled: "Cancelada" })[state] || state;
  }

  function renderPurchasing() {
    renderSourcing();
    renderFrameworkAgreements();
    renderPayablesAging();
    const permitted = backend.connected && can("purchasing.view_purchaseorder");
    const canViewSuppliers = backend.connected && can("purchasing.view_supplier");
    $("#new-supplier").hidden = !backend.connected || !can("purchasing.add_supplier");
    $("#import-suppliers").hidden = !canViewSuppliers || !can("purchasing.add_supplier");
    $("#new-purchase-order").hidden = !backend.connected || !can("purchasing.add_purchaseorder");
    $("#supplier-list-section").hidden = !canViewSuppliers;
    $("#supplier-products-section").hidden = !backend.connected || !can("purchasing.view_supplierproduct");
    $("#new-supplier-product").hidden = !backend.connected || !can("purchasing.add_supplierproduct");
    $("#supplier-list").innerHTML = live.purchasing.suppliers.map((supplier) => `<tr><td>${escapeHtml(supplier.name)}${supplier.legal_name ? `<small class="muted" style="display:block">${escapeHtml(supplier.legal_name)}</small>` : ""}</td><td>${escapeHtml(supplier.rfc || "—")}</td><td>${escapeHtml(supplier.email || "—")}</td><td>${supplier.lead_time_days == null ? `<span class="muted">Sin estimación</span>` : `${escapeHtml(supplier.lead_time_days)} días`}</td><td>${can("purchasing.change_supplier") ? `<button class="btn btn-light btn-small" data-supplier-edit="${escapeHtml(supplier.id)}">Editar</button>` : "—"}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">No hay proveedores registrados.</td></tr>`;
    $("#supplier-product-list").innerHTML = live.purchasing.supplierProducts.map((item) => {
      const revisions = (item.history || []).map((revision) => `<li><strong>Rev. ${escapeHtml(revision.revision)} · ${money(revision.unit_cost)}</strong> · ${escapeHtml(revision.changed_by_name || "Proceso del sistema")} · ${escapeHtml(new Date(revision.changed_at).toLocaleString("es-MX"))}<br>${escapeHtml(revision.change_reason)}</li>`).join("");
      const archiveAction = can("purchasing.change_supplierproduct") ? `<button class="btn btn-light btn-small" data-supplier-product-toggle="${escapeHtml(item.id)}" data-next-active="${!item.is_active}">${item.is_active ? "Archivar" : "Reactivar"}</button>` : "";
      return `<tr><td>${escapeHtml(item.supplier_name)}${item.is_active ? "" : `<small class="muted" style="display:block">Archivada</small>`}</td><td>${escapeHtml(item.product_sku)} · ${escapeHtml(item.product_name)}</td><td>${escapeHtml(item.supplier_reference || "—")}</td><td>${money(item.unit_cost)}</td><td>${item.minimum_order_quantity == null ? "—" : escapeHtml(item.minimum_order_quantity)}</td><td>${item.lead_time_days == null ? "Plazo general" : `${escapeHtml(item.lead_time_days)} días`}</td><td>${escapeHtml(item.last_verified_on || "—")}</td><td>${can("purchasing.change_supplierproduct") ? `<button class="btn btn-light btn-small" data-supplier-product-edit="${escapeHtml(item.id)}">Editar</button>` : ""}${archiveAction}<details><summary>${(item.history || []).length} revisiones</summary><ol>${revisions || "<li>Sin historial</li>"}</ol></details></td></tr>`;
    }).join("") || `<tr><td colspan="8" class="empty">Aún no hay condiciones por producto.</td></tr>`;
    if (!permitted) {
      $("#purchase-order-list").innerHTML = `<tr><td colspan="8" class="empty">Conecta un usuario con permisos de compras para consultar órdenes.</td></tr>`;
      $("#purchase-receipt-list").innerHTML = `<tr><td colspan="5" class="empty">Las recepciones aparecerán aquí.</td></tr>`;
      $("#purchase-summary").textContent = "Conecta el ERP para ver las compras.";
      return;
    }
    const term = $("#purchase-search").value.trim().toLowerCase();
    const orders = live.purchasing.orders.filter((order) => !term || `${order.number} ${order.supplier_name}`.toLowerCase().includes(term));
    $("#purchase-order-list").innerHTML = orders.map((order) => {
      const status = purchaseStateLabel(order.status);
      const actions = [];
      if (order.status === "draft" && can("purchasing.change_purchaseorder")) actions.push(`<button class="btn btn-light btn-small" data-purchase-edit="${escapeHtml(order.id)}">Editar</button>`);
      if (order.status === "draft" && can("purchasing.confirm_purchaseorder")) actions.push(`<button class="btn btn-light btn-small" data-purchase-confirm="${escapeHtml(order.id)}">Solicitar</button>`);
      if (["ordered", "partial"].includes(order.status) && can("purchasing.receive_purchaseorder")) actions.push(`<button class="btn btn-light btn-small" data-purchase-receive="${escapeHtml(order.id)}">Recibir</button>`);
      if (["partial", "received"].includes(order.status) && can("purchasing.register_supplierbill") && order.lines.some((line) => Number(line.received_quantity) > live.purchasing.bills.flatMap((bill) => bill.lines).filter((billLine) => billLine.purchase_order_line === line.id).reduce((sum, billLine) => sum + Number(billLine.quantity), 0))) actions.push(`<button class="btn btn-light btn-small" data-purchase-bill="${escapeHtml(order.id)}">Factura</button>`);
      if (["draft", "ordered"].includes(order.status) && can("purchasing.cancel_purchaseorder")) actions.push(`<button class="btn btn-quiet btn-small" data-purchase-cancel="${escapeHtml(order.id)}">Cancelar</button>`);
      const origin = order.framework_agreement ? live.purchasing.frameworkAgreements.find((agreement) => String(agreement.id) === String(order.framework_agreement))?.reference : "";
      return `<tr><td class="quote-no">${escapeHtml(order.number)}</td><td>${escapeHtml(order.supplier_name)}${origin ? `<small class="muted" style="display:block">Acuerdo ${escapeHtml(origin)}</small>` : ""}</td><td>${escapeHtml(order.order_date)}</td><td>${escapeHtml(order.expected_date || "—")}</td><td>${order.lines.length}</td><td class="money">${money(order.subtotal)}</td><td>${badge(status)}</td><td>${actions.join(" ") || "—"}</td></tr>`;
    }).join("") || `<tr><td colspan="8" class="empty">No hay órdenes de compra para mostrar.</td></tr>`;
    $("#purchase-summary").textContent = `${live.purchasing.orders.length} órdenes · ${live.purchasing.suppliers.length} proveedores`;
    $("#purchase-receipt-list").innerHTML = live.purchasing.receipts.slice(0, 20).map((receipt) => `<tr><td>${new Date(receipt.receipt_date).toLocaleString("es-MX")}</td><td class="quote-no">${escapeHtml(receipt.order_number)}</td><td>${escapeHtml(receipt.supplier_name)}</td><td>${receipt.lines.length}</td><td>${receipt.lines.map((line) => `${escapeHtml(line.product_sku)}: ${escapeHtml(line.quantity)}`).join(" · ")}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">Sin recepciones de compra.</td></tr>`;
    $("#supplier-bill-list").innerHTML = live.purchasing.bills.slice(0, 50).map((bill) => {
      const action = Number(bill.balance_due) > 0 && can("purchasing.add_supplierpayment") && can("purchasing.post_supplierpayment") ? `<button class="btn btn-light btn-small" data-supplier-pay="${escapeHtml(bill.id)}">Pagar</button>` : "—";
      const cfdiAction = bill.cfdi_xml_attached ? `<button class="btn btn-quiet btn-small" data-supplier-bill-cfdi-download="${escapeHtml(bill.id)}">Descargar XML</button><div class="muted" title="Sello del emisor verificado con el certificado incluido; no valida la cadena de confianza SAT ni consulta la vigencia del UUID">UUID ${escapeHtml(String(bill.cfdi_uuid).slice(0, 8))} · ${bill.cfdi_issuer_seal_verified ? "XSD y sello local verificados" : "XSD revisado; sello no verificado"}</div>` : can("purchasing.attach_cfdi_supplierbill") ? `<button class="btn btn-light btn-small" data-supplier-bill-cfdi-upload="${escapeHtml(bill.id)}">Adjuntar XML</button><input type="file" accept=".xml,application/xml,text/xml" data-supplier-bill-cfdi-file="${escapeHtml(bill.id)}" hidden>` : `<span class="muted">Sin XML</span>`;
      const dueDate = bill.due_date ? new Date(`${bill.due_date}T12:00:00`).toLocaleDateString("es-MX") : `<span class="muted">Sin fecha</span>`;
      return `<tr><td>${escapeHtml(bill.invoice_date)}</td><td>${dueDate}</td><td class="quote-no">${escapeHtml(bill.invoice_number)}</td><td>${escapeHtml(bill.supplier_name)}</td><td>${escapeHtml(bill.purchase_order_number)}</td><td>${money(bill.subtotal)}</td><td>${money(bill.tax_total)}</td><td>${money(bill.total)}</td><td>${money(bill.paid_amount)}</td><td><strong>${money(bill.balance_due)}</strong></td><td>${cfdiAction}</td><td>${action}</td></tr>`;
    }).join("") || `<tr><td colspan="12" class="empty">Sin facturas de proveedor capturadas.</td></tr>`;
    $("#supplier-payment-list").innerHTML = live.purchasing.supplierPayments.slice(0, 50).map((payment) => {
      const appliedBills = payment.applications.map((application) => live.purchasing.bills.find((bill) => bill.id === application.bill)?.invoice_number).filter(Boolean).join(", ");
      const action = payment.state === "draft" && can("purchasing.post_supplierpayment") ? `<button class="btn btn-light btn-small" data-post-supplier-payment="${escapeHtml(payment.id)}">Aplicar</button>${payment.applications.length === 1 && can("purchasing.change_supplierpayment") ? ` <button class="btn btn-quiet btn-small" data-edit-supplier-payment="${escapeHtml(payment.id)}">Editar</button>` : ""}` : payment.state === "posted" && can("purchasing.reverse_supplierpayment") ? `<button class="btn btn-light btn-small" data-reverse-supplier-payment="${escapeHtml(payment.id)}">Revertir</button>` : "—";
      const stateLabel = payment.state === "posted" ? "Aplicado" : payment.state === "reversed" ? "Revertido" : "Borrador";
      const reversalNote = payment.state === "reversed" ? `<small class="muted" style="display:block">${escapeHtml(payment.reversal_reason)}${payment.reversal_entry_number ? ` · póliza ${escapeHtml(payment.reversal_entry_number)}` : ""}</small>` : "";
      return `<tr><td>${new Date(payment.paid_at).toLocaleDateString("es-MX")}</td><td class="quote-no">${escapeHtml(payment.number)}</td><td>${escapeHtml(payment.supplier_name)}</td><td>${escapeHtml(payment.reference || appliedBills || "—")}${reversalNote}</td><td>${money(payment.amount)}</td><td>${badge(stateLabel)}</td><td>${action}</td></tr>`;
    }).join("") || `<tr><td colspan="7" class="empty">Sin pagos capturados.</td></tr>`;
  }

  function renderExpenses() {
    const nav = document.querySelector('[data-view="gastos"]');
    if (nav) nav.hidden = !backend.connected || !can("expenses.view_expense");
    const canCapture = backend.connected && can("expenses.add_expense");
    const canCategories = backend.connected && can("expenses.add_expensecategory");
    const canConfigure = backend.connected && can("accounting.change_postingconfiguration");
    $("#expense-capture-section").hidden = !canCapture;
    $("#expense-category-section").hidden = !canCategories;
    $("#expense-posting-config-section").hidden = !canConfigure;
    const categories = live.expenses.categories.filter((category) => category.is_active);
    $("#expense-category").innerHTML = `<option value="">Selecciona una categoría</option>${categories.map((category) => `<option value="${escapeHtml(category.id)}">${escapeHtml(category.code)} · ${escapeHtml(category.name)}${category.receipt_required ? " · comprobante" : ""}</option>`).join("")}`;
    const expenseAccounts = live.chartAccounts.filter((account) => account.is_active && account.category === "expense");
    $("#expense-category-account").innerHTML = `<option value="">Selecciona cuenta de gasto</option>${expenseAccounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.code)} · ${escapeHtml(account.name)}</option>`).join("")}`;
    const liabilities = live.chartAccounts.filter((account) => account.is_active && account.category === "liability");
    const assets = live.chartAccounts.filter((account) => account.is_active && account.category === "asset");
    const reimbursementConfig = live.expenses.configurations.find((configuration) => configuration.is_active && configuration.reimbursement_journal);
    const reimbursementJournal = live.journals.find((journal) => String(journal.id) === String(reimbursementConfig?.reimbursement_journal));
    $("#expense-journal").innerHTML = `<option value="">Selecciona diario</option>${live.journals.filter((journal) => journal.is_active && ["purchases", "general"].includes(journal.kind)).map((journal) => `<option value="${escapeHtml(journal.id)}">${escapeHtml(journal.code)} · ${escapeHtml(journal.name)}</option>`).join("")}`;
    $("#expense-reimbursement-journal").innerHTML = `<option value="">Selecciona diario de pago</option>${live.journals.filter((journal) => journal.is_active && ["bank", "cash"].includes(journal.kind)).map((journal) => `<option value="${escapeHtml(journal.id)}">${escapeHtml(journal.code)} · ${escapeHtml(journal.name)} (${journal.kind === "bank" ? "Banco" : "Caja"})</option>`).join("")}`;
    $("#expense-payable-account").innerHTML = `<option value="">Selecciona cuenta por pagar</option>${liabilities.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.code)} · ${escapeHtml(account.name)}</option>`).join("")}`;
    $("#expense-funds-account").innerHTML = `<option value="">Selecciona fondos</option>${assets.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.code)} · ${escapeHtml(account.name)}</option>`).join("")}`;
    $("#expense-list").innerHTML = live.expenses.items.filter((expense) => !expense.report).map((expense) => {
      const category = live.expenses.categories.find((item) => item.id === expense.category);
      const receipts = (expense.receipts || []).map((file) => `<button class="btn btn-quiet btn-small" data-expense-download="${escapeHtml(expense.id)}" data-receipt-id="${escapeHtml(file.id)}">${escapeHtml(file.original_name)}</button>`).join(" ");
      const upload = can("expenses.add_expensereceipt") ? `<label class="btn btn-light btn-small">Adjuntar<input type="file" accept=".jpg,.jpeg,.png,.webp,.pdf" data-expense-upload="${escapeHtml(expense.id)}" hidden></label>` : "";
      return `<tr><td><input type="checkbox" data-expense-select="${escapeHtml(expense.id)}" aria-label="Seleccionar gasto"></td><td>${escapeHtml(expense.expense_date)}</td><td>${escapeHtml(expense.description)}${expense.merchant ? `<small class="muted" style="display:block">${escapeHtml(expense.merchant)}</small>` : ""}</td><td>${escapeHtml(category?.name || "—")}</td><td class="money">${money(expense.amount)}</td><td>${expense.paid_by === "employee" ? "Yo" : "Empresa"}</td><td>${receipts || `<span class="muted">Sin archivo</span>`} ${upload}</td></tr>`;
    }).join("") || `<tr><td colspan="7" class="empty">No hay gastos sueltos. Captura uno o revisa tus reportes.</td></tr>`;
    $("#create-expense-report").hidden = !can("expenses.add_expensereport");
    $("#expense-report-list").innerHTML = live.expenses.reports.map((report) => {
      const actions = [];
      if (["draft", "rejected"].includes(report.state) && can("expenses.submit_expensereport")) actions.push(`<button class="btn btn-light btn-small" data-expense-report-action="submit" data-report-id="${escapeHtml(report.id)}">Enviar</button>`);
      if (report.state === "submitted" && can("expenses.approve_expensereport")) actions.push(`<button class="btn btn-light btn-small" data-expense-report-action="approve" data-report-id="${escapeHtml(report.id)}">Aprobar</button><button class="btn btn-quiet btn-small" data-expense-report-action="reject" data-report-id="${escapeHtml(report.id)}">Rechazar</button>`);
      if (report.state === "approved" && can("expenses.post_expensereport")) actions.push(`<button class="btn btn-light btn-small" data-expense-report-action="prepare-journal" data-report-id="${escapeHtml(report.id)}">Preparar póliza</button>`);
      if (report.state === "journal_draft" && report.journal_state === "posted" && Number(report.reimbursement_balance) > 0 && reimbursementJournal && can("expenses.register_expensereimbursement")) actions.push(`<button class="btn btn-light btn-small" data-expense-reimburse="${escapeHtml(report.id)}">Registrar reembolso (${money(report.reimbursement_balance)})</button>`);
      const expenseLines = (report.expenses || []).map((item) => {
        const receipts = (item.receipts || []).map((file) => ` <button type="button" class="btn btn-quiet btn-small" data-expense-download="${escapeHtml(item.id)}" data-receipt-id="${escapeHtml(file.id)}">${escapeHtml(file.original_name)}</button>`).join("") + (report.state === "rejected" && can("expenses.add_expensereceipt") ? ` <label class="btn btn-light btn-small">Adjuntar<input type="file" accept=".jpg,.jpeg,.png,.webp,.pdf" data-expense-upload="${escapeHtml(item.id)}" hidden></label>` : "");
        const edit = report.state === "rejected" && can("expenses.change_expense") ? `<details><summary>Corregir</summary><form data-expense-edit="${escapeHtml(item.id)}" class="work-logs"><input name="description" value="${escapeHtml(item.description)}" maxlength="240" required aria-label="Descripción corregida"><input name="expense_date" type="date" value="${escapeHtml(item.expense_date)}" required aria-label="Fecha corregida"><input name="amount" type="number" min="0.01" step="0.01" value="${escapeHtml(item.amount)}" required aria-label="Importe corregido"><select name="category" required>${categories.map((category) => `<option value="${escapeHtml(category.id)}" ${item.category === category.id ? "selected" : ""}>${escapeHtml(category.name)}</option>`).join("")}</select><select name="paid_by"><option value="employee" ${item.paid_by === "employee" ? "selected" : ""}>Pagó la persona</option><option value="company" ${item.paid_by === "company" ? "selected" : ""}>Pagó la empresa</option></select><button class="btn btn-light btn-small" type="submit">Guardar corrección</button></form></details>` : "";
        return `<div>${escapeHtml(item.description)} · ${money(item.amount)}${receipts}${edit}</div>`;
      }).join("");
      const journal = report.journal_number ? `<small class="muted" style="display:block">${escapeHtml(report.journal_number)}</small>` : "";
      const reimbursementHistory = (report.reimbursements || []).map((item) => `<div>${escapeHtml(item.number)} · ${money(item.amount)} · ${escapeHtml(item.payment_date)} · ${badge(apiStateLabel(item.state))}${item.reference ? ` · ${escapeHtml(item.reference)}` : ""}<small class="muted" style="display:block">Póliza ${escapeHtml(item.journal_number || "—")} (${escapeHtml(apiStateLabel(item.journal_state || "—"))})${item.reversal_reason ? ` · Reversa: ${escapeHtml(item.reversal_reason)}` : ""}</small>${item.state === "recorded" && item.journal_state === "posted" && can("expenses.reverse_expensereimbursement") ? `<button class="btn btn-quiet btn-small" data-expense-reimbursement-reverse="${escapeHtml(report.id)}" data-reimbursement-id="${escapeHtml(item.id)}">Revertir reembolso</button>` : ""}</div>`).join("");
      const settlement = Number(report.reimbursable_total) > 0 ? `<details><summary>Reembolsos · pendiente ${money(report.reimbursement_balance)}</summary><div class="muted" style="white-space:normal;min-width:240px">${reimbursementHistory || "Sin pagos registrados"}</div></details>` : "";
      const reportStateLabel = report.state === "journal_draft" ? (report.journal_state === "posted" ? "Contabilizado" : "Póliza borrador") : apiStateLabel(report.state);
      return `<tr><td class="quote-no">${escapeHtml(report.number)}</td><td>${escapeHtml(report.owner_name || "")}</td><td>${escapeHtml((report.submitted_at || report.created_at || "").slice(0, 10))}</td><td>${report.expenses?.length || 0}<details><summary>Ver gastos</summary><div class="muted" style="white-space:normal;min-width:180px">${expenseLines || "Sin renglones"}</div></details>${settlement}</td><td class="money">${money(report.total)}</td><td>${badge(reportStateLabel)}${report.rejection_reason ? `<small class="muted" style="display:block">${escapeHtml(report.rejection_reason)}</small>` : ""}${journal}</td><td>${actions.join(" ") || "—"}</td></tr>`;
    }).join("") || `<tr><td colspan="7" class="empty">Aún no hay reportes de gastos.</td></tr>`;
  }

  function renderPayablesAging() {
    const report = live.purchasing.payablesAging;
    $("#payables-aging-caption").textContent = report ? `Fecha de corte ${new Date(`${report.as_of}T12:00:00`).toLocaleDateString("es-MX")} · ${report.bill_count} facturas pendientes.` : "Conecta un usuario con permiso de consulta de facturas de proveedor.";
    $("#payables-aging-summary").innerHTML = (report?.buckets || []).map((bucket) => `<tr><td>${escapeHtml(bucket.label)}</td><td>${Number(bucket.bill_count || 0)}</td><td class="money">${money(bucket.balance)}</td></tr>`).join("") || `<tr><td colspan="3" class="empty">Sin datos de cuentas por pagar.</td></tr>`;
    $("#payables-aging-count").textContent = report?.bill_count ?? 0;
    $("#payables-aging-total").textContent = money(report?.total_balance || 0);
    $("#export-payables-aging").disabled = !report;
    $("#payables-aging-bills").innerHTML = (report?.bills || []).map((bill) => `<tr><td>${bill.due_date ? new Date(`${bill.due_date}T12:00:00`).toLocaleDateString("es-MX") : "Sin fecha"}</td><td>${bill.overdue_days === null || bill.overdue_days === 0 ? "—" : bill.overdue_days}</td><td class="quote-no">${escapeHtml(bill.invoice_number)}</td><td>${escapeHtml(bill.supplier_name)}</td><td>${escapeHtml(bill.purchase_order_number)}</td><td>${escapeHtml(bill.bucket_label)}</td><td class="money">${money(bill.balance_due)}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">No hay facturas pendientes al corte seleccionado.</td></tr>`;
    renderSupplierStatement();
  }

  function renderSupplierStatement() {
    const select = $("#supplier-statement-supplier");
    const selected = select.value;
    const suppliers = new Map(live.purchasing.suppliers.map((supplier) => [String(supplier.id), supplier]));
    for (const bill of live.purchasing.bills) {
      const id = String(bill.supplier);
      if (!suppliers.has(id)) suppliers.set(id, { id, name: bill.supplier_name, rfc: "" });
    }
    select.innerHTML = `<option value="">Selecciona un proveedor</option>` + [...suppliers.values()].sort((a, b) => a.name.localeCompare(b.name, "es-MX")).map((supplier) => `<option value="${escapeHtml(supplier.id)}">${escapeHtml(supplier.name)}${supplier.rfc ? ` · ${escapeHtml(supplier.rfc)}` : ""}</option>`).join("");
    if (suppliers.has(selected)) select.value = selected;
    const report = live.purchasing.supplierStatement;
    $("#supplier-statement-caption").textContent = report ? `${report.supplier_name}${report.supplier_rfc ? ` · RFC ${report.supplier_rfc}` : ""} · corte ${new Date(`${report.as_of}T12:00:00`).toLocaleDateString("es-MX")} · ${report.bill_count} facturas y ${report.payment_count} pagos.` : "Consulta facturas registradas y pagos aplicados de un proveedor.";
    $("#supplier-statement-billed").textContent = money(report?.total_billed || 0);
    $("#supplier-statement-paid").textContent = money(report?.total_paid || 0);
    $("#supplier-statement-balance").textContent = money(report?.balance_due || 0);
    $("#export-supplier-statement").disabled = !report;
    $("#supplier-statement-entries").innerHTML = (report?.entries || []).map((entry) => `<tr><td>${new Date(`${entry.date}T12:00:00`).toLocaleDateString("es-MX")}</td><td>${supplierStatementEntryLabel(entry.type)}</td><td class="quote-no">${escapeHtml(entry.document_number)}</td><td>${escapeHtml(entry.description)}</td><td class="money">${Number(entry.debit) ? money(entry.debit) : "—"}</td><td class="money">${Number(entry.credit) ? money(entry.credit) : "—"}</td><td class="money">${money(entry.running_balance)}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">Selecciona un proveedor y consulta su estado de cuenta.</td></tr>`;
  }

  function supplierStatementEntryLabel(type) {
    return ({ bill: "Factura de proveedor", payment: "Pago", payment_reversal: "Reversa de pago", opening_payment_summary: "Pago previo (apertura)" })[type] || "Movimiento";
  }

  async function loadSupplierStatement() {
    if (!backend.connected || !can("purchasing.view_supplierbill")) { toast("Conecta un usuario con permiso para consultar estados de cuenta de proveedor."); return; }
    const supplierId = $("#supplier-statement-supplier").value;
    if (!supplierId) { toast("Selecciona un proveedor."); return; }
    const asOf = $("#supplier-statement-date").value || todayISO();
    try {
      live.purchasing.supplierStatement = await apiRequest(`purchasing/supplier-bills/supplier-statement/?supplier_id=${encodeURIComponent(supplierId)}&as_of=${encodeURIComponent(asOf)}`);
      renderSupplierStatement();
    } catch (error) { toast(error.message); }
  }

  async function loadPayablesAging() {
    if (!backend.connected || !can("purchasing.view_supplierbill")) { toast("Conecta un usuario con permiso para consultar cuentas por pagar."); return; }
    const asOf = $("#payables-aging-date").value || todayISO();
    try {
      live.purchasing.payablesAging = await apiRequest(`purchasing/supplier-bills/payables-aging/?as_of=${encodeURIComponent(asOf)}`);
      renderPayablesAging();
    } catch (error) { toast(error.message); }
  }

  function exportPayablesAging() {
    const report = live.purchasing.payablesAging;
    if (!report) { toast("Consulta primero la antigüedad de cuentas por pagar."); return; }
    const rows = [
      ["Fecha de corte", report.as_of, "Moneda", report.currency || "MXN"],
      ["Folio proveedor", "Proveedor", "RFC", "Orden de compra", "Emisión", "Vencimiento", "Días de atraso", "Grupo", "Total original", "Pagado", "Saldo pendiente"],
      ...(report.bills || []).map((bill) => [bill.invoice_number, bill.supplier_name, live.purchasing.suppliers.find((supplier) => String(supplier.id) === String(bill.supplier_id))?.rfc || "", bill.purchase_order_number, bill.invoice_date, bill.due_date || "", bill.overdue_days ?? "", bill.bucket_label, bill.bill_total, bill.paid_amount, bill.balance_due]),
      [], ["Total pendiente", report.total_balance, "Facturas", report.bill_count],
    ];
    downloadSafeCsv(`redmagna-cxp-antiguedad-${report.as_of}.csv`, rows);
  }

  function exportSupplierStatement() {
    const report = live.purchasing.supplierStatement;
    if (!report) { toast("Consulta primero el estado de cuenta del proveedor."); return; }
    const rows = [
      ["Proveedor", report.supplier_name, "RFC", report.supplier_rfc || "", "Fecha de corte", report.as_of, "Moneda", report.currency || "MXN"],
      ["Fecha", "Tipo", "Folio", "Descripción / referencia", "Débito", "Crédito", "Saldo acumulado"],
      ...(report.entries || []).map((entry) => [entry.date, supplierStatementEntryLabel(entry.type), entry.document_number, entry.description, entry.debit, entry.credit, entry.running_balance]),
      [], ["Total facturado", report.total_billed, "Pagos netos", report.total_paid, "Saldo al corte", report.balance_due],
    ];
    downloadSafeCsv(`redmagna-cxp-estado-cuenta-${report.as_of}.csv`, rows);
  }

  function addPurchaseLine(initial = null) {
    const products = live.inventory.products.filter((product) => product.kind === "stockable" && product.is_active);
    const locations = live.inventory.locations.filter((location) => location.is_active);
    if (!products.length || !locations.length) { toast("Primero registra productos con control de existencias y una ubicación activa."); return; }
    const row = document.createElement("div");
    row.className = "line-item";
    row.innerHTML = `<select class="po-product" aria-label="Producto">${products.map((product) => `<option value="${escapeHtml(product.id)}">${escapeHtml(product.sku)} · ${escapeHtml(product.name)}</option>`).join("")}</select><select class="po-location" aria-label="Ubicación prevista">${locations.map((location) => `<option value="${escapeHtml(location.id)}">${escapeHtml(location.code)} · ${escapeHtml(location.name)}</option>`).join("")}</select><input class="po-quantity" type="number" min="0.001" step="0.001" placeholder="Cantidad" required><input class="po-cost" type="number" min="0" step="0.01" placeholder="Costo unitario" required><button type="button" class="remove-line po-remove" aria-label="Quitar">×</button><small class="muted po-term-note" style="grid-column:1/-1"></small>`;
    if (initial) { row.querySelector(".po-product").value = initial.product; row.querySelector(".po-location").value = initial.expected_location || locations.find((location) => location.code === "MAIN")?.id || locations[0].id; row.querySelector(".po-quantity").value = initial.quantity; row.querySelector(".po-cost").value = initial.unit_cost; row.dataset.costManual = "true"; }
    row.querySelector(".po-product").addEventListener("change", () => { if (row.dataset.costManual !== "true") applySupplierProductTerm(row); updateExpectedDateFromSupplier(); });
    row.querySelector(".po-cost").addEventListener("input", () => { row.dataset.costManual = "true"; });
    row.querySelector(".po-remove").addEventListener("click", () => { row.remove(); updateExpectedDateFromSupplier(); });
    $("#purchase-lines").appendChild(row);
    if (!initial) applySupplierProductTerm(row);
    updateExpectedDateFromSupplier();
  }

  function supplierProductTerm(supplierId, productId) {
    return live.purchasing.supplierProducts.find((item) => item.is_active && String(item.supplier) === String(supplierId) && String(item.product) === String(productId));
  }

  function applySupplierProductTerm(row) {
    const term = supplierProductTerm($("#po-supplier").value, row.querySelector(".po-product").value);
    const cost = row.querySelector(".po-cost");
    const note = row.querySelector(".po-term-note");
    if (term) {
      cost.value = Number(term.unit_cost).toFixed(2);
      row.dataset.costManual = "false";
      const details = [term.supplier_reference && `Código proveedor: ${term.supplier_reference}`, term.minimum_order_quantity && `Mínimo: ${term.minimum_order_quantity}`, term.lead_time_days != null && `Entrega: ${term.lead_time_days} días`, term.last_verified_on && `Precio revisado: ${term.last_verified_on}`].filter(Boolean);
      note.textContent = details.join(" · ") || "Condición vigente del proveedor aplicada.";
    } else {
      if (row.dataset.costManual !== "true") cost.value = "";
      note.textContent = "Sin ficha de precio para este proveedor y producto; captura el costo de la cotización recibida.";
    }
  }

  function openPurchaseOrder(orderId = "", suggestedLine = null) {
    const suppliers = live.purchasing.suppliers.filter((supplier) => supplier.is_active);
    if (!suppliers.length) { toast("Registra primero un proveedor."); $("#supplier-modal").classList.add("open"); return; }
    if (!live.inventory.products.some((product) => product.kind === "stockable" && product.is_active) || !live.inventory.locations.some((location) => location.is_active)) { toast("Registra primero productos con control de existencias y una ubicación activa."); go("inventario"); return; }
    const existing = orderId ? live.purchasing.orders.find((order) => order.id === orderId) : null;
    const form = $("#purchase-order-form");
    form.reset();
    if (existing) form.dataset.edit = existing.id; else delete form.dataset.edit;
    form.dataset.expectedManual = existing ? "true" : "false";
    $("#po-supplier").innerHTML = suppliers.map((supplier) => `<option value="${escapeHtml(supplier.id)}">${escapeHtml(supplier.name)}${supplier.lead_time_days != null ? ` · ${escapeHtml(supplier.lead_time_days)} días` : ""}</option>`).join("");
    $("#po-order-date").value = existing?.order_date || todayISO();
    if (existing) { $("#po-supplier").value = existing.supplier; $("#po-expected-date").value = existing.expected_date || ""; $("#po-notes").value = existing.notes || ""; }
    updateExpectedDateFromSupplier();
    $("#purchase-lines").innerHTML = "";
    if (existing?.lines.length) existing.lines.forEach((line) => addPurchaseLine({ product: line.product, expected_location: line.expected_location, quantity: line.quantity, unit_cost: line.unit_cost }));
    else if (suggestedLine) addPurchaseLine({ ...suggestedLine, unit_cost: "0.00" });
    else addPurchaseLine();
    if (!existing) [...$("#purchase-lines").querySelectorAll(".line-item")].forEach(applySupplierProductTerm);
    updateExpectedDateFromSupplier();
    $("#purchase-order-title").textContent = existing ? `Editar ${existing.number}` : "Nueva orden de compra";
    $("#save-purchase-order").textContent = existing ? "Guardar cambios" : "Guardar borrador";
    $("#purchase-order-modal").classList.add("open");
  }

  function openSupplier(supplierId = "") {
    const form = $("#supplier-form");
    const supplier = supplierId ? live.purchasing.suppliers.find((item) => item.id === supplierId) : null;
    form.reset();
    if (supplier) {
      form.dataset.edit = supplier.id;
      $("#supplier-title").textContent = `Editar ${supplier.name}`;
      $("#supplier-save").textContent = "Guardar cambios";
      $("#supplier-name").value = supplier.name || "";
      $("#supplier-legal-name").value = supplier.legal_name || "";
      $("#supplier-rfc").value = supplier.rfc || "";
      $("#supplier-email").value = supplier.email || "";
      $("#supplier-phone").value = supplier.phone || "";
      $("#supplier-lead-days").value = supplier.lead_time_days ?? "";
    } else {
      delete form.dataset.edit;
      $("#supplier-title").textContent = "Nuevo proveedor";
      $("#supplier-save").textContent = "Guardar proveedor";
    }
    $("#supplier-modal").classList.add("open");
  }

  function openSupplierProduct(itemId = "") {
    const item = itemId ? live.purchasing.supplierProducts.find((entry) => entry.id === itemId) : null;
    const form = $("#supplier-product-form");
    form.reset();
    $("#supplier-product-supplier").innerHTML = live.purchasing.suppliers.filter((entry) => entry.is_active).map((entry) => `<option value="${escapeHtml(entry.id)}">${escapeHtml(entry.name)}</option>`).join("");
    $("#supplier-product-product").innerHTML = live.inventory.products.filter((entry) => entry.kind === "stockable" && entry.is_active).map((entry) => `<option value="${escapeHtml(entry.id)}">${escapeHtml(entry.sku)} · ${escapeHtml(entry.name)}</option>`).join("");
    if (item) {
      form.dataset.edit = item.id;
      $("#supplier-product-supplier").value = item.supplier;
      $("#supplier-product-product").value = item.product;
      $("#supplier-product-cost").value = item.unit_cost;
      $("#supplier-product-reference").value = item.supplier_reference || "";
      $("#supplier-product-minimum").value = item.minimum_order_quantity ?? "";
      $("#supplier-product-lead").value = item.lead_time_days ?? "";
      $("#supplier-product-verified").value = item.last_verified_on || "";
      $("#supplier-product-title").textContent = "Editar condición proveedor–producto";
    } else {
      delete form.dataset.edit;
      $("#supplier-product-title").textContent = "Condición proveedor–producto";
      $("#supplier-product-verified").value = todayISO();
    }
    $("#supplier-product-modal").classList.add("open");
  }

  function updateExpectedDateFromSupplier() {
    const form = $("#purchase-order-form");
    if (form.dataset.expectedManual === "true") return;
    const supplier = live.purchasing.suppliers.find((item) => item.id === $("#po-supplier").value);
    const orderDate = $("#po-order-date").value;
    if (!orderDate) { $("#po-expected-date").value = ""; return; }
    const rowTerms = [...$("#purchase-lines").querySelectorAll(".line-item")].map((row) => supplierProductTerm(supplier?.id, row.querySelector(".po-product").value));
    const rowLeadDays = rowTerms.map((term) => term?.lead_time_days ?? supplier?.lead_time_days).filter((value) => value != null).map(Number);
    const leadDays = rowLeadDays.length ? Math.max(...rowLeadDays) : null;
    if (leadDays == null) { $("#po-expected-date").value = ""; return; }
    const [year, month, day] = orderDate.split("-").map(Number);
    $("#po-expected-date").value = new Date(Date.UTC(year, month - 1, day + Number(leadDays))).toISOString().slice(0, 10);
  }

  function openPurchaseReceipt(orderId) {
    const order = live.purchasing.orders.find((item) => item.id === orderId);
    const locations = live.inventory.locations.filter((location) => location.is_active);
    if (!order || !locations.length) { toast("No hay una ubicación activa para recibir productos."); return; }
    const mainLocation = locations.find((location) => location.code === "MAIN") || locations[0];
    const pending = order.lines.filter((line) => Number(line.quantity) > Number(line.received_quantity));
    $("#receipt-order-id").value = order.id;
    $("#receipt-idempotency-key").value = newUuid();
    $("#receipt-order-label").textContent = `${order.number} · ${order.supplier_name}`;
    $("#receipt-note").value = "";
    $("#receipt-product-scan").value = "";
    $("#purchase-receive-lines").innerHTML = pending.map((line) => {
      const remaining = Number(line.quantity) - Number(line.received_quantity);
      const product = live.inventory.products.find((item) => item.id === line.product);
      const lineLocation = locations.find((location) => location.id === line.expected_location) || mainLocation;
      const lineLocations = line.expected_location ? locations.filter((location) => location.id === line.expected_location) : locations;
      return `<tr data-receipt-line="${escapeHtml(line.id)}" data-product-id="${escapeHtml(line.product)}" data-remaining="${remaining.toFixed(3)}" data-barcode-scans="0"><td>${escapeHtml(line.product_sku)} · ${escapeHtml(line.product_name)}</td><td>${escapeHtml(line.quantity)}</td><td>${escapeHtml(line.received_quantity)}</td><td>${remaining.toFixed(3)}</td><td><input class="receipt-quantity" type="number" min="0" max="${remaining.toFixed(3)}" step="0.001" value="${remaining.toFixed(3)}" aria-label="Cantidad a recibir"></td><td>${product?.tracking_policy === "serial" ? `<textarea class="receipt-serials" rows="2" placeholder="Una serie por renglón" aria-label="Números de serie"></textarea>` : "—"}</td><td><select class="receipt-location" aria-label="Ubicación">${lineLocations.map((location) => `<option value="${escapeHtml(location.id)}" ${location.id === lineLocation.id ? "selected" : ""}>${escapeHtml(location.name)}</option>`).join("")}</select></td></tr>`;
    }).join("");
    $("#purchase-receive-modal").classList.add("open");
    $("#receipt-product-scan").focus();
  }

  function scanPurchaseReceiptProduct() {
    const input = $("#receipt-product-scan");
    const barcode = input.value.trim();
    if (!barcode) return;
    const products = live.inventory.products.filter((product) => product.kind === "stockable" && product.is_active && product.barcode === barcode);
    if (products.length !== 1) {
      toast(products.length ? "El código coincide con varios productos." : "No se encontró un producto activo con ese código.");
      input.select();
      return;
    }
    const rows = [...$("#purchase-receive-lines").querySelectorAll("[data-receipt-line]")].filter((row) => row.dataset.productId === products[0].id);
    if (rows.length !== 1) {
      toast(rows.length ? "El producto aparece en varias líneas de esta orden; captura la cantidad en la línea correspondiente." : "Este producto no tiene cantidades pendientes en esta orden.");
      input.select();
      return;
    }
    const row = rows[0];
    const quantity = row.querySelector(".receipt-quantity");
    if (Number(row.dataset.barcodeScans) === 0 && row.dataset.quantityEdited !== "true") quantity.value = "0.000";
    const next = Number(quantity.value || 0) + 1;
    if (next > Number(row.dataset.remaining)) {
      toast("La lectura supera la cantidad pendiente por recibir.");
      input.select();
      return;
    }
    quantity.value = next.toFixed(3);
    row.dataset.barcodeScans = String(Number(row.dataset.barcodeScans) + 1);
    input.value = "";
    input.focus();
    toast(products[0].tracking_policy === "serial" ? "Una unidad recibida. Captura su serie antes de registrar." : `Una unidad de ${products[0].sku} agregada a la recepción.`);
  }

  function openSupplierBill(orderId) {
    const order = live.purchasing.orders.find((item) => item.id === orderId);
    if (!order) return;
    const rows = order.lines.map((line) => {
      const alreadyBilled = live.purchasing.bills.flatMap((bill) => bill.lines).filter((billLine) => billLine.purchase_order_line === line.id).reduce((sum, billLine) => sum + Number(billLine.quantity), 0);
      const remaining = Math.max(0, Number(line.received_quantity) - alreadyBilled);
      return remaining > 0 ? `<tr data-bill-line="${escapeHtml(line.id)}"><td><strong>${escapeHtml(line.product_sku)}</strong> · ${escapeHtml(line.product_name)}</td><td>${escapeHtml(line.received_quantity)}</td><td>${remaining.toFixed(3)}</td><td><input class="bill-quantity search" type="number" min="0" max="${remaining}" step="0.001" aria-label="Cantidad facturada"></td><td><input class="bill-unit-cost search" type="number" min="0" step="0.01" value="${escapeHtml(line.unit_cost)}" aria-label="Precio unitario"></td><td><input class="bill-tax search" type="number" min="0" step="0.01" value="0.00" aria-label="Impuesto declarado"></td></tr>` : "";
    }).join("");
    if (!rows) { toast("No hay cantidades recibidas pendientes de facturar."); return; }
    $("#supplier-bill-form").reset();
    $("#supplier-bill-order-id").value = order.id;
    $("#supplier-bill-date").value = todayISO();
    $("#supplier-bill-due-date").value = "";
    $("#supplier-bill-lines").innerHTML = rows;
    $("#supplier-bill-modal").classList.add("open");
  }

  function openSupplierPayment(billId, existingPayment = null) {
    const bill = live.purchasing.bills.find((item) => item.id === billId);
    if (!bill || (!existingPayment && Number(bill.balance_due) <= 0)) return;
    $("#supplier-payment-form").reset();
    $("#supplier-payment-bill-id").value = bill.id;
    $("#supplier-payment-id").value = existingPayment?.id || "";
    $("#supplier-payment-bill-label").textContent = `${bill.supplier_name} · Factura ${bill.invoice_number} · Saldo ${money(bill.balance_due)} MXN`;
    $("#supplier-payment-date").value = existingPayment?.paid_at?.slice(0, 10) || todayISO();
    $("#supplier-payment-amount").value = Number(existingPayment?.applications?.[0]?.amount ?? bill.balance_due).toFixed(2);
    $("#supplier-payment-amount").max = Number(bill.balance_due).toFixed(2);
    if (existingPayment) { $("#supplier-payment-method").value = existingPayment.method; $("#supplier-payment-reference").value = existingPayment.reference; $("#supplier-payment-memo").value = existingPayment.memo; }
    $("#supplier-payment-modal").classList.add("open");
  }

  function openStockMovement(initialKind, workOrderId = "", initialProductId = "", initialQuantity = "") {
    const { products, locations } = live.inventory;
    const activeLocations = locations.filter((location) => location.is_active);
    const stockable = products.filter((product) => product.kind === "stockable" && product.is_active);
    if (!stockable.length) { toast("Primero registra productos con control de existencias en el catálogo."); go("inventario"); return; }
    const options = [];
    if (workOrderId) {
      if (can("inventory.issue_stock")) options.push(["reserve", "Reservar material para la orden"], ["issue", "Entregar material a la orden"], ["return", "Devolver material de la orden"]);
    } else {
      if (can("inventory.receive_stock")) options.push(["receipt", "Entrada al almacén"]);
      if (can("inventory.adjust_stock")) options.push(["adjustment_in", "Ajuste positivo"], ["adjustment_out", "Ajuste negativo"]);
    }
    if (!options.length) { toast("Tu usuario no tiene permisos para mover existencias."); return; }
    $("#stock-movement-title").textContent = workOrderId ? "Materiales de la orden" : "Movimiento de inventario";
    $("#stock-work-order-id").value = workOrderId;
    $("#stock-movement-form").dataset.idempotencyKey = newUuid();
    $("#stock-kind").innerHTML = options.map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
    $("#stock-kind").value = options.some(([value]) => value === initialKind) ? initialKind : options[0][0];
    $("#stock-product-scan").value = "";
    $("#stock-location-scan").value = "";
    const updateProductOptions = () => {
      const eligible = $("#stock-kind").value === "reserve" ? stockable.filter((product) => product.tracking_policy === "quantity") : stockable;
      $("#stock-product").innerHTML = eligible.map((product) => `<option value="${escapeHtml(product.id)}">${escapeHtml(product.sku)} · ${escapeHtml(product.name)}</option>`).join("");
      if (initialProductId && eligible.some((product) => product.id === initialProductId)) $("#stock-product").value = initialProductId;
    };
    updateProductOptions();
    const updateSerialField = () => {
      const product = stockable.find((item) => item.id === $("#stock-product").value);
      $("#stock-serial-field").hidden = $("#stock-kind").value === "reserve" || product?.tracking_policy !== "serial";
      $("#stock-serials").value = "";
    };
    const updateReasonField = () => {
      const required = ["return", "adjustment_in", "adjustment_out"].includes($("#stock-kind").value);
      $("#stock-note").required = required;
      $("#stock-note").placeholder = required ? "Describe por qué se devuelve o ajusta" : "Detalle opcional";
      $("#stock-note").closest(".field").querySelector("label").textContent = required ? "Motivo" : "Nota";
    };
    const updateReferenceField = () => {
      const required = $("#stock-kind").value === "receipt";
      $("#stock-reference").required = required;
      $("#stock-reference").placeholder = required ? "Orden, remisión o referencia de origen" : "Referencia opcional";
      $("#stock-reference").closest(".field").querySelector("label").textContent = required ? "Referencia de origen" : "Referencia";
    };
    $("#stock-product").onchange = updateSerialField;
    $("#stock-kind").onchange = () => { updateProductOptions(); updateSerialField(); updateReasonField(); updateReferenceField(); };
    updateSerialField();
    updateReasonField();
    updateReferenceField();
    $("#stock-location").innerHTML = activeLocations.map((location) => `<option value="${escapeHtml(location.id)}">${escapeHtml(location.code)} · ${escapeHtml(location.name)}</option>`).join("");
    const main = activeLocations.find((location) => location.code === "MAIN");
    $("#stock-location").value = main?.id || activeLocations[0]?.id || "";
    $("#stock-quantity").value = initialQuantity || ""; $("#stock-reference").value = ""; $("#stock-note").value = "";
    $("#stock-movement-modal").classList.add("open");
    $("#stock-product-scan").focus();
  }

  function scanStockMovementProduct() {
    const input = $("#stock-product-scan");
    const barcode = input.value.trim();
    if (!barcode) return;
    const matches = live.inventory.products.filter((product) => product.kind === "stockable" && product.is_active && product.barcode === barcode);
    if (matches.length !== 1) {
      toast(matches.length ? "El código coincide con varios productos; revisa el catálogo." : "No se encontró un producto activo con ese código.");
      input.select();
      return;
    }
    const product = matches[0];
    const selector = $("#stock-product");
    if (![...selector.options].some((option) => option.value === product.id)) {
      toast("Este producto no está disponible para el tipo de movimiento seleccionado.");
      input.select();
      return;
    }
    const quantity = $("#stock-quantity");
    const changedProduct = selector.value !== product.id;
    if (changedProduct) quantity.value = "";
    selector.value = product.id;
    if (changedProduct) selector.dispatchEvent(new Event("change"));
    quantity.value = (Number(quantity.value || 0) + 1).toFixed(3);
    input.value = "";
    input.focus();
    toast(product.tracking_policy === "serial" ? "Una unidad agregada. Captura su número de serie antes de registrar." : `Una unidad de ${product.sku} agregada.`);
  }

  function scanStockMovementLocation() {
    const input = $("#stock-location-scan");
    const value = input.value.trim();
    if (!value) return;
    const matches = live.inventory.locations.filter((location) => location.is_active && (location.barcode === value || location.code === value.toUpperCase()));
    if (matches.length !== 1) {
      toast(matches.length ? "La lectura coincide con varias ubicaciones." : "No se encontró una ubicación activa con ese código.");
      input.select();
      return;
    }
    $("#stock-location").value = matches[0].id;
    input.value = "";
    input.focus();
    toast(`Ubicación: ${matches[0].code} · ${matches[0].name}.`);
  }

  function openStockUnitInstall(unitId) {
    const unit = (live.inventory.serialUnits || []).find((item) => item.id === unitId);
    if (!unit || !can("inventory.issue_stock")) return;
    $("#stock-unit-install-id").value = unit.id;
    $("#stock-unit-install-label").textContent = `${unit.product_sku} · ${unit.product_name} · serie ${unit.serial_number} · ${unit.work_order_number || "orden"}`;
    $("#stock-unit-installed-at").value = todayISO();
    $("#stock-unit-warranty-until").value = "";
    $("#stock-unit-install-modal").classList.add("open");
  }

  function openStockUnitReserve(unitId) {
    const unit = (live.inventory.serialUnits || []).find((item) => item.id === unitId);
    const workOrders = live.workOrders.filter((item) => ["planned", "in_progress"].includes(item.status));
    if (!unit || !workOrders.length) { toast("No hay órdenes programadas o en curso para reservar este equipo."); return; }
    $("#stock-unit-reserve-id").value = unit.id;
    $("#stock-unit-reserve-label").textContent = `${unit.product_sku} · ${unit.product_name} · serie ${unit.serial_number} · ${unit.location_code || "almacén"}`;
    $("#stock-unit-reserve-order").innerHTML = workOrders.map((order) => `<option value="${escapeHtml(order.id)}">${escapeHtml(order.sales_order_number)} · ${escapeHtml(order.customer_name)} · ${escapeHtml(order.title)}</option>`).join("");
    $("#stock-unit-reserve-modal").classList.add("open");
  }

  function transferIdempotencyKey() {
    return globalThis.crypto?.randomUUID?.() || "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
      const random = Math.floor(Math.random() * 16);
      return (char === "x" ? random : (random & 3) | 8).toString(16);
    });
  }

  function addStockTransferLine() {
    const products = live.inventory.products.filter((product) => product.kind === "stockable" && product.is_active);
    if (!products.length) { toast("Registra primero productos con control de existencias."); return; }
    const row = document.createElement("div");
    row.dataset.transferLine = "";
    row.className = "form-row";
    row.innerHTML = `<div class="field"><label>Producto</label><select data-transfer-product required>${products.map((product) => `<option value="${escapeHtml(product.id)}">${escapeHtml(product.sku)} · ${escapeHtml(product.name)}</option>`).join("")}</select></div><div class="field" style="max-width:180px"><label>Cantidad</label><input data-transfer-quantity type="number" min="0.001" step="0.001" required></div><div class="field" data-transfer-serial-field hidden><label>Números de serie</label><textarea data-transfer-serials rows="2" placeholder="Una serie por renglón"></textarea></div><button type="button" class="btn btn-light btn-small" data-transfer-remove aria-label="Quitar producto">Quitar</button>`;
    const toggleSerials = () => { const product = products.find((item) => item.id === row.querySelector("[data-transfer-product]").value); row.querySelector("[data-transfer-serial-field]").hidden = product?.tracking_policy !== "serial"; };
    row.querySelector("[data-transfer-product]").addEventListener("change", toggleSerials);
    toggleSerials();
    row.querySelector("[data-transfer-remove]").addEventListener("click", () => row.remove());
    $("#transfer-lines").append(row);
  }

  function openStockTransfer() {
    const locations = live.inventory.locations.filter((location) => location.is_active);
    if (locations.length < 2) { toast("Registra al menos dos ubicaciones activas para hacer un traspaso."); return; }
    const options = locations.map((location) => `<option value="${escapeHtml(location.id)}">${escapeHtml(location.code)} · ${escapeHtml(location.name)}</option>`).join("");
    $("#transfer-source").innerHTML = options;
    $("#transfer-destination").innerHTML = options;
    $("#transfer-source-scan").value = "";
    $("#transfer-destination-scan").value = "";
    $("#transfer-barcode-scan").value = "";
    const main = locations.find((location) => location.code === "MAIN");
    $("#transfer-source").value = main?.id || locations[0].id;
    $("#transfer-destination").value = locations.find((location) => location.id !== $("#transfer-source").value)?.id || "";
    $("#transfer-reference").value = ""; $("#transfer-note").value = "";
    $("#transfer-lines").replaceChildren();
    $("#inventory-transfer-form").dataset.idempotencyKey = transferIdempotencyKey();
    addStockTransferLine();
    $("#inventory-transfer-modal").classList.add("open");
    $("#transfer-barcode-scan").focus();
  }

  function addScannedProductToTransfer() {
    const input = $("#transfer-barcode-scan");
    const barcode = input.value.trim();
    if (!barcode) return;
    const matches = live.inventory.products.filter((product) => product.kind === "stockable" && product.is_active && product.barcode === barcode);
    if (matches.length !== 1) {
      toast(matches.length ? "El código coincide con más de un producto; revisa el catálogo." : "No se encontró un producto activo con ese código de barras.");
      input.select();
      return;
    }
    const product = matches[0];
    const rows = [...$("#transfer-lines").querySelectorAll("[data-transfer-line]")];
    let row = rows.find((item) => item.querySelector("[data-transfer-product]").value === product.id);
    if (!row) {
      row = rows.find((item) => !item.querySelector("[data-transfer-quantity]").value.trim());
      if (!row) {
        addStockTransferLine();
        row = $("#transfer-lines").lastElementChild;
      }
      row.querySelector("[data-transfer-product]").value = product.id;
      row.querySelector("[data-transfer-product]").dispatchEvent(new Event("change"));
    }
    const quantity = row.querySelector("[data-transfer-quantity]");
    quantity.value = (Number(quantity.value || 0) + 1).toFixed(3);
    input.value = "";
    input.focus();
    toast(product.tracking_policy === "serial" ? "Una unidad agregada. Captura su número de serie antes de confirmar." : `Una unidad de ${product.sku} agregada al traspaso.`);
  }

  function scanTransferLocation(role) {
    const input = $(`#transfer-${role}-scan`);
    const value = input.value.trim();
    if (!value) return;
    const matches = live.inventory.locations.filter((location) => location.is_active && (location.barcode === value || location.code === value.toUpperCase()));
    if (matches.length !== 1) {
      toast(matches.length ? "La lectura coincide con varias ubicaciones; revisa el catálogo." : "No se encontró una ubicación activa con ese código.");
      input.select();
      return;
    }
    const selector = $(`#transfer-${role}`);
    selector.value = matches[0].id;
    input.value = "";
    input.focus();
    toast(`${role === "source" ? "Origen" : "Destino"}: ${matches[0].code} · ${matches[0].name}.`);
  }

  function fiscalCancellationResponse(fiscal) {
    const pdf = fiscal?.pdf_available && can("billing.view_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-pdf="${escapeHtml(fiscal.id)}">Descargar PDF timbrado</button>` : "";
    const emailEvent = [...(fiscal?.events || [])].reverse().find((item) => item.response_payload?.type === "customer_copy_email");
    const emailPayload = emailEvent?.response_payload || {};
    const emailStatus = emailEvent ? `<details class="muted" style="font-size:10px"><summary>Copia fiscal · ${emailEvent.response_code === "customer_copy_email_sent" ? "enviada" : "resultado incierto"}</summary>${escapeHtml(emailPayload.recipient || "Correo registrado")}${emailPayload.attachments?.length ? ` · ${escapeHtml(emailPayload.attachments.join(" y ").toUpperCase())}` : ""}</details>` : "";
    if (!["cancel_pending", "cancelled", "cancel_rejected"].includes(fiscal?.state)) return `${pdf}${emailStatus}`;
    const event = [...(fiscal.events || [])].reverse().find((item) => item.state_before === "cancel_pending");
    if (!event) return `${pdf}${emailStatus}`;
    const payload = event.response_payload || {};
    const status = payload.status ? ` · estado SAT/FEL: ${escapeHtml(payload.status)}` : "";
    const uuidCheck = payload.uuid_matches_document === true
      ? " · UUID confirmado"
      : payload.uuid_matches_document === false
        ? " · UUID devuelto distinto del comprobante"
        : "";
    const summary = event.action === "query" ? "Consulta SAT/FEL" : event.action === "error" ? "Error de comunicación FEL" : "Respuesta FEL";
    const message = payload.message || "Revisa la respuesta de SAT/FEL antes de actuar de nuevo.";
    return `${pdf}${emailStatus}<details class="muted" style="font-size:10px"><summary>${summary} · ${escapeHtml(event.response_code || "sin código")}${status}${uuidCheck}</summary>${escapeHtml(message)}</details>`;
  }

  function printInternalInvoice(invoiceId) {
    const invoice = live.invoices.find((item) => item.id === invoiceId);
    if (!invoice) { toast("No se encontró la factura para imprimir."); return; }
    const printWindow = window.open("", "_blank");
    if (!printWindow) { toast("Permite ventanas emergentes para imprimir esta factura."); return; }
    const lineRows = (invoice.lines || []).map((line) => `<tr><td>${escapeHtml(line.description)}</td><td class="num">${escapeHtml(line.quantity)}</td><td class="num">${money(line.unit_price)}</td><td class="num">${Number(line.discount_percent || 0).toFixed(2)}%</td><td class="num">${escapeHtml(line.tax_rate)}%</td><td class="num">${money(line.line_subtotal)}</td><td class="num">${money(line.tax_amount)}</td><td class="num">${money(Number(line.line_subtotal || 0) + Number(line.tax_amount || 0))}</td></tr>`).join("");
    const status = ({ draft: "Borrador", open: "Abierta", partial: "Pago parcial", paid: "Pagada", credited: "Liquidada por nota de crédito", cancelled: "Cancelada" })[invoice.state] || invoice.state;
    const issued = invoice.issue_date ? new Date(`${invoice.issue_date}T12:00:00`).toLocaleDateString("es-MX") : "—";
    const due = invoice.due_date ? new Date(`${invoice.due_date}T12:00:00`).toLocaleDateString("es-MX") : "Sin fecha de vencimiento";
    printWindow.document.open();
    const fiscalName = invoice.customer_legal_name || invoice.customer_name;
    const fiscalDetails = [invoice.customer_rfc && `RFC: ${invoice.customer_rfc}`, invoice.customer_fiscal_regime && `Régimen: ${invoice.customer_fiscal_regime}`, invoice.customer_fiscal_postal_code && `C.P. fiscal: ${invoice.customer_fiscal_postal_code}`].filter(Boolean).map(escapeHtml).join("<br>");
    printWindow.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(invoice.number)} · Redmagna</title><style>
      *{box-sizing:border-box}body{font:14px/1.45 Arial,sans-serif;color:#172338;margin:32px}header{display:flex;justify-content:space-between;gap:24px;border-bottom:2px solid #18365b;padding-bottom:18px;margin-bottom:22px}.brand{font-size:26px;font-weight:700;color:#18365b}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#68778a}.title{font-size:22px;margin:4px 0}.meta{color:#536174;text-align:right}.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:20px 0}.panel{padding:14px;background:#f4f7fa;border-radius:8px}.panel strong{display:block;margin-bottom:6px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:9px 7px;border-bottom:1px solid #dce3eb;text-align:left;vertical-align:top}th{background:#f4f7fa;font-size:10px;text-transform:uppercase;color:#526174}.num{text-align:right;white-space:nowrap}.totals{margin:18px 0 0 auto;width:min(340px,100%)}.totals div{display:flex;justify-content:space-between;padding:5px 0}.grand{border-top:2px solid #18365b;margin-top:5px;padding-top:10px!important;font-size:17px;font-weight:700}.balance{font-size:16px;font-weight:700;color:#18365b}.notice{margin-top:26px;border:1px solid #cf6a3a;border-radius:8px;padding:12px;color:#763816;background:#fff8f3;font-weight:700}.foot{margin-top:20px;color:#68778a;font-size:11px}@media print{body{margin:12mm}button{display:none}}
      </style></head><body><header><div><div class="brand">Redmagna</div><div class="eyebrow">Control administrativo de cobranza</div><h1 class="title">Factura interna ${escapeHtml(invoice.number)}</h1></div><div class="meta"><div>Emisión: ${escapeHtml(issued)}</div><div>Vencimiento: ${escapeHtml(due)}</div><div>Estado: ${escapeHtml(status)}</div></div></header><div class="grid"><section class="panel"><strong>Cliente</strong>${escapeHtml(invoice.customer_name)}<br>${escapeHtml(fiscalName)}${fiscalDetails ? `<br>${fiscalDetails}` : ""}${invoice.memo ? `<br>${escapeHtml(invoice.memo)}` : ""}</section><section class="panel"><strong>Referencia comercial</strong>${escapeHtml(invoice.sales_order_number || "Sin orden de venta vinculada")}<br>Moneda: ${escapeHtml(invoice.currency || "MXN")}</section></div><table><thead><tr><th>Concepto</th><th class="num">Cantidad</th><th class="num">Precio unitario</th><th class="num">Descuento</th><th class="num">IVA</th><th class="num">Subtotal</th><th class="num">Impuesto</th><th class="num">Importe</th></tr></thead><tbody>${lineRows || `<tr><td colspan="8">Sin conceptos</td></tr>`}</tbody></table><section class="totals"><div><span>Subtotal</span><strong>${money(invoice.subtotal)}</strong></div><div><span>Impuestos</span><strong>${money(invoice.tax_total)}</strong></div><div class="grand"><span>Total</span><strong>${money(invoice.total)}</strong></div><div><span>Pagado</span><strong>${money(invoice.paid_amount)}</strong></div><div><span>Notas de crédito aplicadas</span><strong>${money(invoice.credited_amount)}</strong></div><div class="balance"><span>Saldo pendiente</span><strong>${money(invoice.balance_due)}</strong></div></section><div class="notice">DOCUMENTO INTERNO DE COBRANZA. NO ES UN CFDI Y NO SUSTITUYE LA FACTURA FISCAL TIMBRADA POR FEL.</div><p class="foot">Para obtener el comprobante fiscal, solicita el CFDI timbrado correspondiente. Este documento refleja la captura interna y el saldo registrado al momento de imprimir.</p><script>window.addEventListener("load",()=>setTimeout(()=>window.print(),150));</script></body></html>`);
    printWindow.document.close();
  }

  function renderFEL() {
    if (backend.connected) {
      $("#fel-list").innerHTML = live.invoices.map((invoice) => {
        const state = apiStateLabel(invoice.state), invoiceFiscalDocuments = live.fiscalDocuments.filter((document) => document.invoice === invoice.id), fiscal = invoiceFiscalDocuments.find((document) => !["rejected", "cancelled"].includes(document.state)), lastRejected = invoiceFiscalDocuments.find((document) => document.state === "rejected");
        const actions = [];
        if (invoice.state === "draft" && can("billing.open_customerinvoice")) actions.push(`<button class="btn btn-light btn-small" data-invoice-open="${escapeHtml(invoice.id)}">Abrir cuenta</button>`);
        if (["open", "partial"].includes(invoice.state) && can("billing.add_payment") && can("billing.post_payment")) actions.push(`<button class="btn btn-light btn-small" data-invoice-pay="${escapeHtml(invoice.id)}">Registrar cobro</button>`);
        if (["open", "partial"].includes(invoice.state) && invoice.lines?.length && can("billing.add_customercreditnote") && can("billing.post_customercreditnote")) actions.push(`<button class="btn btn-light btn-small" data-invoice-credit="${escapeHtml(invoice.id)}">Crear nota</button>`);
        if (["open", "partial", "paid"].includes(invoice.state) && can("billing.prepare_fiscaldocument")) {
          if (fiscal) actions.push(`<span class="muted" style="font-size:10px">CFDI: ${escapeHtml(({ prepared: "Preparado", submitted: "Enviado · revisar FEL", stamped: "Timbrado", rejected: "Rechazado", cancel_pending: "Cancelación pendiente", cancelled: "Cancelado", cancel_rejected: "Cancelación rechazada · revisar respuesta" })[fiscal.state] || fiscal.state)}</span>${fiscalCancellationResponse(fiscal)}${fiscal.state === "prepared" && can("billing.generate_fiscaldocument_xml") ? ` <button class="btn btn-light btn-small" data-fiscal-generate="${escapeHtml(fiscal.id)}">${fiscal.request_xml ? "Descargar XML" : "Generar XML firmado"}</button>` : ""}${fiscal.state === "prepared" && fiscal.request_xml && can("billing.send_fiscaldocument") ? ` <button class="btn btn-primary btn-small" data-fiscal-send="${escapeHtml(fiscal.id)}">Enviar a FEL</button>` : ""}${fiscal.state === "submitted" && can("billing.query_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-query="${escapeHtml(fiscal.id)}">Consultar FEL</button>` : ""}${fiscal.state === "cancel_pending" && can("billing.query_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-query="${escapeHtml(fiscal.id)}">Actualizar estado SAT</button>` : ""}${["stamped", "cancel_rejected"].includes(fiscal.state) && can("billing.cancel_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-cancel="${escapeHtml(fiscal.id)}">Solicitar cancelación SAT</button>` : ""}`);
          else actions.push(`<button class="btn btn-light btn-small" data-cfdi-prepare="${escapeHtml(invoice.id)}">Preparar CFDI</button>`);
        }
        if (!fiscal && lastRejected) {
          const errorEvent = [...(lastRejected.events || [])].reverse().find((item) => item.action === "error");
          if (errorEvent) actions.push(`<details class="muted" style="font-size:10px"><summary>Último rechazo · ${escapeHtml(errorEvent.response_code || "sin código")}</summary>${escapeHtml(errorEvent.response_payload?.message || "Revisa la respuesta FEL registrada.")}</details>`);
        }
        if (fiscal?.state === "submitted" && can("billing.query_fiscaldocument")) actions.push(`<button class="btn btn-light btn-small" data-fiscal-query="${escapeHtml(fiscal.id)}">Consultar FEL</button>`);
        if (fiscal?.state === "stamped" && can("billing.send_customer_copy_fiscaldocument")) actions.push(`<button class="btn btn-light btn-small" data-fiscal-customer-copy="${escapeHtml(fiscal.id)}">Enviar CFDI al cliente</button>`);
        const dueDate = invoice.state === "draft" && can("billing.change_customerinvoice")
          ? `<div style="display:flex;align-items:center;gap:6px"><input class="search" style="width:145px" type="date" data-invoice-due-input value="${escapeHtml(invoice.due_date || "")}" aria-label="Vencimiento de ${escapeHtml(invoice.number)}"><button class="btn btn-light btn-small" data-invoice-due-save="${escapeHtml(invoice.id)}">Guardar</button></div>`
          : invoice.due_date ? new Date(`${invoice.due_date}T12:00:00`).toLocaleDateString("es-MX") : `<span class="muted">Sin fecha</span>`;
        if (can("billing.view_customerinvoice")) actions.unshift(`<button class="btn btn-light btn-small" data-print-invoice="${escapeHtml(invoice.id)}">Imprimir</button>`);
        const rowAction = actions.join(" ");
        return `<tr><td class="quote-no">${escapeHtml(invoice.number)}</td><td>${escapeHtml(invoice.customer_name)}</td><td>${escapeHtml(invoice.memo || "Factura interna")}</td><td class="money">${money(invoice.total)}</td><td>${dueDate}</td><td>${badge(state)}</td><td>${rowAction}</td></tr>`;
      }).join("") || `<tr><td colspan="7" class="empty">Aún no hay facturas internas. Termina una orden de trabajo para preparar una.</td></tr>`;
      $("#credit-note-list").innerHTML = live.creditNotes.map((note) => {
        const fiscal = live.fiscalDocuments.find((document) => document.credit_note === note.id && !["rejected", "cancelled"].includes(document.state));
        const activeIncome = live.fiscalDocuments.some((document) => document.invoice === note.invoice && document.document_type === "I" && ["stamped", "cancel_rejected"].includes(document.state) && document.cfdi_uuid);
        const actions = [];
        if (note.state === "draft" && can("billing.post_customercreditnote")) actions.push(`<button class="btn btn-light btn-small" data-credit-note-post="${escapeHtml(note.id)}">Aplicar</button>`);
        if (note.state === "posted" && !fiscal && activeIncome && can("billing.prepare_fiscaldocument")) actions.push(`<button class="btn btn-light btn-small" data-credit-note-cfdi="${escapeHtml(note.id)}">Preparar CFDI E</button>`);
        if (note.state === "posted" && !activeIncome) actions.push(`<span class="muted" style="font-size:10px">Requiere CFDI I timbrado vigente</span>`);
        if (fiscal) {
          actions.push(`<span class="muted" style="font-size:10px">CFDI E: ${escapeHtml(({ prepared: "Preparado", submitted: "Enviado · revisar FEL", stamped: "Timbrado", cancel_pending: "Cancelación pendiente", cancel_rejected: "Cancelación rechazada" })[fiscal.state] || fiscal.state)}</span>`);
          actions.push(fiscalCancellationResponse(fiscal));
          if (fiscal.state === "prepared" && can("billing.generate_fiscaldocument_xml")) actions.push(`<button class="btn btn-light btn-small" data-fiscal-generate="${escapeHtml(fiscal.id)}">${fiscal.request_xml ? "Descargar XML" : "Generar XML firmado"}</button>`);
          if (fiscal.state === "prepared" && fiscal.request_xml && can("billing.send_fiscaldocument")) actions.push(`<button class="btn btn-primary btn-small" data-fiscal-send="${escapeHtml(fiscal.id)}">Enviar a FEL</button>`);
          if (["submitted", "cancel_pending"].includes(fiscal.state) && can("billing.query_fiscaldocument")) actions.push(`<button class="btn btn-light btn-small" data-fiscal-query="${escapeHtml(fiscal.id)}">Consultar FEL</button>`);
          if (fiscal.state === "stamped" && can("billing.send_customer_copy_fiscaldocument")) actions.push(`<button class="btn btn-light btn-small" data-fiscal-customer-copy="${escapeHtml(fiscal.id)}">Enviar CFDI al cliente</button>`);
          if (["stamped", "cancel_rejected"].includes(fiscal.state) && can("billing.cancel_fiscaldocument")) actions.push(`<button class="btn btn-light btn-small" data-fiscal-cancel="${escapeHtml(fiscal.id)}">Solicitar cancelación SAT</button>`);
        }
        if (note.state === "posted" && !fiscal && can("billing.reverse_customercreditnote")) actions.push(`<button class="btn btn-light btn-small" data-credit-note-reverse="${escapeHtml(note.id)}">Revertir</button>`);
        return `<tr><td class="quote-no">${escapeHtml(note.number)}</td><td>${escapeHtml(note.invoice_number)}</td><td>${escapeHtml(note.customer_name)}</td><td>${escapeHtml(note.reason)}</td><td class="money">${money(note.total)}</td><td>${badge(apiStateLabel(note.state))}</td><td>${actions.join(" ") || "—"}</td></tr>`;
      }).join("") || `<tr><td colspan="7" class="empty">Aún no hay notas de crédito internas.</td></tr>`;
      $("#payment-fel-list").innerHTML = live.payments.map((payment) => {
        const fiscal = live.fiscalDocuments.find((document) => document.payment === payment.id && !["rejected", "cancelled"].includes(document.state));
        const sourcesReady = payment.allocations?.length && payment.allocations.every((allocation) => live.fiscalDocuments.some((document) => document.invoice === allocation.invoice && document.state === "stamped" && document.payment_method === "PPD"));
        let action = "—";
        if (fiscal) {
          const review = fiscal.document_type === "P" ? `<details class="muted" style="font-size:10px"><summary>Revisar snapshot fiscal</summary><div style="padding:6px 0">${(fiscal.request_payload?.related_documents || []).map((item) => `<div>${escapeHtml(item.source_invoice_number)} · UUID ${escapeHtml(item.cfdi_uuid)} · aplicado ${money(item.amount_paid)} · saldo ${money(item.remaining_balance)}</div>`).join("") || "Sin CFDI relacionados"}${(fiscal.request_payload?.taxes_summary || []).map((item) => `<div>IVA ${escapeHtml(item.factor === "Exento" ? "exento" : `${Number(item.rate) * 100}%`)} · base ${money(item.base)} · impuesto ${money(item.amount)}</div>`).join("") || "<div>Sin impuestos trasladados</div>"}</div></details>` : "";
          action = `<span class="muted" style="font-size:10px">Complemento: ${escapeHtml(({ prepared: "Preparado", submitted: "Enviado", stamped: "Timbrado", rejected: "Rechazado", cancel_pending: "Cancelación pendiente", cancelled: "Cancelado", cancel_rejected: "Cancelación rechazada · revisar respuesta" })[fiscal.state] || fiscal.state)}</span>${review}${fiscalCancellationResponse(fiscal)}${fiscal.state === "prepared" && can("billing.generate_fiscaldocument_xml") ? ` <button class="btn btn-light btn-small" data-fiscal-generate="${escapeHtml(fiscal.id)}">${fiscal.request_xml ? "Descargar XML" : "Generar XML firmado"}</button>` : ""}${fiscal.state === "prepared" && fiscal.request_xml && can("billing.send_fiscaldocument") ? ` <button class="btn btn-primary btn-small" data-fiscal-send="${escapeHtml(fiscal.id)}">Enviar a FEL</button>` : ""}${fiscal.state === "submitted" && can("billing.query_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-query="${escapeHtml(fiscal.id)}">Consultar FEL</button>` : ""}${fiscal.state === "cancel_pending" && can("billing.query_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-query="${escapeHtml(fiscal.id)}">Actualizar estado SAT</button>` : ""}${fiscal.state === "stamped" && can("billing.send_customer_copy_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-customer-copy="${escapeHtml(fiscal.id)}">Enviar CFDI al cliente</button>` : ""}${["stamped", "cancel_rejected"].includes(fiscal.state) && can("billing.cancel_fiscaldocument") ? ` <button class="btn btn-light btn-small" data-fiscal-cancel="${escapeHtml(fiscal.id)}">Solicitar cancelación SAT</button>` : ""}`;
        }
        else if (payment.state === "posted" && can("billing.prepare_fiscaldocument")) action = sourcesReady ? `<button class="btn btn-light btn-small" data-payment-cfdi="${escapeHtml(payment.id)}">Preparar complemento</button>` : `<span class="muted" style="font-size:10px">Requiere CFDI PPD timbrado</span>`;
        return `<tr><td>${new Date(payment.received_at).toLocaleDateString("es-MX")}</td><td class="quote-no">${escapeHtml(payment.number)}</td><td>${escapeHtml(payment.customer_name)}</td><td class="money">${money(payment.amount)}</td><td>${badge(payment.state === "posted" ? "Aplicado" : "Borrador")}</td><td>${action}</td></tr>`;
      }).join("") || `<tr><td colspan="6" class="empty">Los cobros aplicados aparecerán aquí.</td></tr>`;
      renderReceivablesAging();
      return;
    }
    renderReceivablesAging();
    const ready = db.quotes.filter((quote) => ["Aprobada", "Lista para FEL"].includes(quote.status));
    $("#fel-list").innerHTML = ready.map((quote) => `<tr><td class="quote-no">${escapeHtml(quote.id)}</td><td>${escapeHtml(clientOf(quote.clientId).name)}</td><td>${escapeHtml(quote.title)}</td><td class="money">${money(calc(quote).total)}</td><td><span class="muted">Sin fecha</span></td><td>${badge(quote.status)}</td><td><button class="btn btn-light btn-small" data-quote-action="${escapeHtml(quote.id)}">${quote.status === "Aprobada" ? "Preparar factura" : "Registrar cobro"}</button></td></tr>`).join("") || `<tr><td colspan="7" class="empty">Las cotizaciones aprobadas aparecerán aquí.</td></tr>`;
  }

  function renderReceivablesAging() {
    const report = live.receivablesAging;
    $("#receivables-aging-caption").textContent = report ? `Fecha de corte ${new Date(`${report.as_of}T12:00:00`).toLocaleDateString("es-MX")} · ${report.invoice_count} facturas abiertas.` : "Conecta la base central para consultar las facturas pendientes.";
    $("#receivables-aging-summary").innerHTML = (report?.buckets || []).map((bucket) => `<tr><td>${escapeHtml(bucket.label)}</td><td>${Number(bucket.invoice_count || 0)}</td><td class="money">${money(bucket.balance)}</td></tr>`).join("") || `<tr><td colspan="3" class="empty">Sin datos de cuentas por cobrar.</td></tr>`;
    $("#receivables-aging-count").textContent = report?.invoice_count ?? 0;
    $("#receivables-aging-total").textContent = money(report?.total_balance || 0);
    $("#export-receivables-aging").disabled = !report;
    $("#receivables-aging-invoices").innerHTML = (report?.invoices || []).map((invoice) => `<tr><td>${invoice.due_date ? new Date(`${invoice.due_date}T12:00:00`).toLocaleDateString("es-MX") : "Sin fecha"}</td><td>${invoice.overdue_days === null ? "—" : invoice.overdue_days === 0 ? "—" : invoice.overdue_days}</td><td class="quote-no">${escapeHtml(invoice.number)}</td><td>${escapeHtml(invoice.customer_name)}</td><td>${escapeHtml(invoice.bucket_label)}</td><td class="money">${money(invoice.balance_due)}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">No hay facturas abiertas al corte seleccionado.</td></tr>`;
    renderCustomerStatement();
  }

  function customerStatementEntryLabel(type) {
    return ({ invoice: "Factura", payment: "Cobro", payment_reversal: "Reversa de cobro", credit_note: "Nota de crédito", credit_note_reversal: "Reversa de nota de crédito", opening_payment_summary: "Pago previo (apertura)" })[type] || "Movimiento";
  }

  function renderCustomerStatement() {
    const select = $("#customer-statement-customer");
    const selected = select.value;
    select.innerHTML = `<option value="">Selecciona un cliente</option>` + db.clients.map((client) => `<option value="${escapeHtml(client.id)}">${escapeHtml(client.name)}${client.rfc ? ` · ${escapeHtml(client.rfc)}` : ""}</option>`).join("");
    if (db.clients.some((client) => String(client.id) === selected)) select.value = selected;
    const report = live.customerStatement;
    $("#customer-statement-caption").textContent = report ? `${report.customer_name}${report.customer_rfc ? ` · RFC ${report.customer_rfc}` : ""} · corte ${new Date(`${report.as_of}T12:00:00`).toLocaleDateString("es-MX")} · ${report.invoice_count} facturas y ${report.payment_count} cobros.` : "Consulta los cargos y cobros aplicados de un cliente.";
    $("#customer-statement-charged").textContent = money(report?.total_charged || 0);
    $("#customer-statement-paid").textContent = money(report?.total_paid || 0);
    $("#customer-statement-balance").textContent = money(report?.balance_due || 0);
    $("#print-customer-statement").disabled = !report;
    $("#export-customer-statement").disabled = !report;
    $("#customer-statement-entries").innerHTML = (report?.entries || []).map((entry) => `<tr><td>${new Date(`${entry.date}T12:00:00`).toLocaleDateString("es-MX")}</td><td>${customerStatementEntryLabel(entry.type)}</td><td class="quote-no">${escapeHtml(entry.document_number)}</td><td>${escapeHtml(entry.description)}</td><td class="money">${Number(entry.debit) ? money(entry.debit) : "—"}</td><td class="money">${Number(entry.credit) ? money(entry.credit) : "—"}</td><td class="money">${money(entry.running_balance)}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">Selecciona un cliente y consulta su estado de cuenta.</td></tr>`;
  }

  function printCustomerStatement() {
    const report = live.customerStatement;
    if (!report) { toast("Consulta primero el estado de cuenta."); return; }
    const printWindow = window.open("", "_blank");
    if (!printWindow) { toast("Permite ventanas emergentes para imprimir este estado de cuenta."); return; }
    const entries = (report.entries || []).map((entry) => `<tr><td>${escapeHtml(new Date(`${entry.date}T12:00:00`).toLocaleDateString("es-MX"))}</td><td>${customerStatementEntryLabel(entry.type)}</td><td>${escapeHtml(entry.document_number)}</td><td>${escapeHtml(entry.description)}</td><td class="num">${Number(entry.debit) ? money(entry.debit) : "—"}</td><td class="num">${Number(entry.credit) ? money(entry.credit) : "—"}</td><td class="num">${money(entry.running_balance)}</td></tr>`).join("");
    const cutoff = new Date(`${report.as_of}T12:00:00`).toLocaleDateString("es-MX");
    printWindow.document.open();
    printWindow.document.write(`<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Estado de cuenta · ${escapeHtml(report.customer_name)}</title><style>*{box-sizing:border-box}body{font:14px/1.45 Arial,sans-serif;color:#172338;margin:32px}header{display:flex;justify-content:space-between;gap:20px;border-bottom:2px solid #18365b;padding-bottom:16px}.brand{font-size:25px;font-weight:700;color:#18365b}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:#68778a}.meta{text-align:right;color:#536174}h1{font-size:22px;margin:5px 0 0}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:22px 0}.metric{background:#f4f7fa;padding:13px;border-radius:7px}.metric span{display:block;color:#68778a;font-size:11px}.metric strong{display:block;margin-top:4px;font-size:18px}table{width:100%;border-collapse:collapse;font-size:12px}th,td{padding:9px 7px;border-bottom:1px solid #dce3eb;text-align:left;vertical-align:top}th{background:#f4f7fa;font-size:10px;text-transform:uppercase;color:#526174}.num{text-align:right;white-space:nowrap}.notice{margin-top:22px;padding:11px;background:#f4f7fa;color:#536174;font-size:11px}@media print{body{margin:12mm}}</style></head><body><header><div><div class="brand">Redmagna</div><div class="eyebrow">Cuentas por cobrar</div><h1>Estado de cuenta</h1></div><div class="meta"><div>Cliente: <strong>${escapeHtml(report.customer_name)}</strong></div>${report.customer_rfc ? `<div>RFC: ${escapeHtml(report.customer_rfc)}</div>` : ""}<div>Fecha de corte: ${escapeHtml(cutoff)}</div><div>Moneda: ${escapeHtml(report.currency || "MXN")}</div></div></header><div class="metrics"><div class="metric"><span>Total facturado</span><strong>${money(report.total_charged)}</strong></div><div class="metric"><span>Cobros aplicados</span><strong>${money(report.total_paid)}</strong></div><div class="metric"><span>Saldo al corte</span><strong>${money(report.balance_due)}</strong></div></div><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Folio</th><th>Descripción / referencia</th><th class="num">Cargo</th><th class="num">Abono</th><th class="num">Saldo acumulado</th></tr></thead><tbody>${entries || `<tr><td colspan="7">Sin movimientos en el periodo.</td></tr>`}</tbody></table><p class="notice">Estado interno de cuenta por cobrar calculado a la fecha de corte. No es un CFDI ni un estado bancario.</p><script>window.addEventListener("load",()=>setTimeout(()=>window.print(),150));</script></body></html>`);
    printWindow.document.close();
  }

  function exportReceivablesAging() {
    const report = live.receivablesAging;
    if (!report) { toast("Consulta primero la antigüedad de saldos."); return; }
    const rows = [
      ["Fecha de corte", report.as_of, "Moneda", report.currency || "MXN"],
      ["Folio", "Cliente", "RFC", "Emisión", "Vencimiento", "Días de atraso", "Grupo", "Total original", "Pagado", "Nota de crédito", "Saldo abierto"],
      ...(report.invoices || []).map((item) => [item.number, item.customer_name, db.clients.find((client) => String(client.id) === String(item.customer_id))?.rfc || "", item.issue_date, item.due_date || "", item.overdue_days ?? "", item.bucket_label, item.invoice_total, item.paid_amount, item.credited_amount, item.balance_due]),
      [], ["Total abierto", report.total_balance, "Facturas", report.invoice_count],
    ];
    downloadSafeCsv(`redmagna-cxc-antiguedad-${report.as_of}.csv`, rows);
  }

  function exportCustomerStatement() {
    const report = live.customerStatement;
    if (!report) { toast("Consulta primero el estado de cuenta."); return; }
    const rows = [
      ["Cliente", report.customer_name, "RFC", report.customer_rfc || "", "Fecha de corte", report.as_of, "Moneda", report.currency || "MXN"],
      ["Fecha", "Tipo", "Folio", "Descripción / referencia", "Cargo", "Abono", "Saldo acumulado"],
      ...(report.entries || []).map((entry) => [entry.date, customerStatementEntryLabel(entry.type), entry.document_number, entry.description, entry.debit, entry.credit, entry.running_balance]),
      [], ["Total facturado", report.total_charged, "Cobros netos", report.total_paid, "Saldo al corte", report.balance_due],
    ];
    downloadSafeCsv(`redmagna-cxc-estado-cuenta-${report.as_of}.csv`, rows);
  }

  async function loadCustomerStatement() {
    if (!backend.connected || !can("billing.view_customerinvoice")) { toast("Conecta un usuario con permiso para consultar estados de cuenta."); return; }
    const customerId = $("#customer-statement-customer").value;
    if (!customerId) { toast("Selecciona un cliente."); return; }
    const asOf = $("#customer-statement-date").value || todayISO();
    try {
      live.customerStatement = await apiRequest(`billing/invoices/customer-statement/?customer_id=${encodeURIComponent(customerId)}&as_of=${encodeURIComponent(asOf)}`);
      renderCustomerStatement();
    } catch (error) { toast(error.message); }
  }

  async function loadReceivablesAging() {
    if (!backend.connected || !can("billing.view_customerinvoice")) { toast("Conecta un usuario con permiso para consultar cuentas por cobrar."); return; }
    const asOf = $("#receivables-aging-date").value || todayISO();
    try {
      live.receivablesAging = await apiRequest(`billing/invoices/receivables-aging/?as_of=${encodeURIComponent(asOf)}`);
      renderReceivablesAging();
    } catch (error) { toast(error.message); }
  }

  function openCFDIPreparation(invoiceId) {
    const invoice = live.invoices.find((item) => item.id === invoiceId);
    if (!invoice || !invoice.lines?.length) { toast("La factura debe tener conceptos para preparar los datos fiscales."); return; }
    $("#cfdi-invoice-id").value = invoice.id;
    $("#cfdi-use").value = "";
    $("#cfdi-exportation").value = "";
    $("#cfdi-payment-method").value = "PPD";
    $("#cfdi-payment-form").value = "99";
    $("#cfdi-concepts").innerHTML = invoice.lines.map((line) => `<tr data-cfdi-line="${escapeHtml(line.id)}"><td><strong>${escapeHtml(line.description)}</strong><br><small class="muted">${line.catalog_product_sku ? `SKU ${escapeHtml(line.catalog_product_sku)} · ` : ""}${escapeHtml(line.quantity)} × ${money(line.unit_price)} · IVA estimado ${escapeHtml(line.tax_rate)}%${Number(line.tax_rate) === 8 ? ` · elegibilidad 8% ${line.catalog_product_sat_border_8_eligible ? "revisada" : "pendiente"}` : ""}</small></td><td><input data-cfdi-product-service maxlength="8" pattern="[0-9]{8}" value="${escapeHtml(line.catalog_product_sat_product_service_key || "")}" required aria-label="Clave SAT de producto o servicio"></td><td><input data-cfdi-unit maxlength="3" pattern="[A-Za-z0-9]{2,3}" value="${escapeHtml(line.catalog_product_sat_unit_key || "")}" required aria-label="Clave SAT de unidad"></td><td><select data-cfdi-tax-object aria-label="Objeto de impuesto"><option value="02" ${(line.catalog_product_sat_tax_object || "02") === "02" ? "selected" : ""}>02 · Sí objeto</option><option value="01" ${line.catalog_product_sat_tax_object === "01" ? "selected" : ""}>01 · No objeto</option></select></td><td><select data-cfdi-tax-factor aria-label="Factor de IVA"><option value="Tasa" ${(line.catalog_product_sat_tax_factor || "Tasa") === "Tasa" ? "selected" : ""}>Tasa ${escapeHtml(line.tax_rate)}%</option><option value="Exento" ${line.catalog_product_sat_tax_factor === "Exento" ? "selected" : ""}>Exento</option></select></td></tr>`).join("");
    $("#cfdi-preparation-modal").classList.add("open");
  }

  function invoiceReminderSummary(reminders = []) {
    const kindLabels = { upcoming: "Próximo al vencimiento", overdue: "Vencido" };
    const statusLabels = { pending: "Pendiente", sent: "Enviado", failed: "Reintentos agotados", skipped: "Omitido" };
    return reminders.map((reminder) => {
      const kind = kindLabels[reminder.kind] || "Recordatorio";
      let status = statusLabels[reminder.status] || reminder.status;
      if (reminder.status === "skipped" && reminder.last_error === "customer_email_missing") status = "Sin correo del cliente";
      if (reminder.status === "pending" && reminder.attempt_count > 0) status += ` · intento ${reminder.attempt_count}`;
      const when = reminder.sent_at ? ` · ${new Date(reminder.sent_at).toLocaleDateString("es-MX")}` : "";
      return `<small class="muted" style="display:block">${escapeHtml(kind)}: ${escapeHtml(status)}${when}</small>`;
    }).join("");
  }

  function renderLedger() {
    if (backend.connected) {
      const total = live.invoices.reduce((sum, invoice) => sum + Number(invoice.total || 0), 0);
      const tax = live.invoices.reduce((sum, invoice) => sum + Number(invoice.tax_total || 0), 0);
      const balance = live.invoices.reduce((sum, invoice) => sum + Number(invoice.balance_due || 0), 0);
      $("#ledger-sales").textContent = money(total); $("#ledger-tax").textContent = money(tax); $("#ledger-balance").textContent = money(balance);
      const rows = live.invoices.map((invoice) => `<tr><td>${new Date(`${invoice.issue_date}T12:00:00`).toLocaleDateString("es-MX")}</td><td class="quote-no">${escapeHtml(invoice.number)}</td><td>${escapeHtml(invoice.customer_name)}</td><td>${invoice.is_opening_balance ? `Saldo importado · ${escapeHtml(invoice.opening_source_system || "Sistema anterior")} · folio ${escapeHtml(invoice.opening_external_number || "—")}` : "Factura interna"}</td><td class="money">${money(invoice.total)}</td><td>${badge(apiStateLabel(invoice.state))}${invoiceReminderSummary(invoice.reminders)}</td></tr>`);
      live.payments.forEach((payment) => rows.push(`<tr><td>${new Date(payment.received_at).toLocaleDateString("es-MX")}</td><td class="quote-no">${escapeHtml(payment.number)}</td><td>${escapeHtml(payment.customer_name)}</td><td>${payment.state === "reversed" ? "Cobro revertido" : "Cobro aplicado"}${payment.reversal_reason ? `<small class="muted" style="display:block">${escapeHtml(payment.reversal_reason)}</small>` : ""}</td><td class="money">${money(payment.amount)}</td><td>${badge(apiStateLabel(payment.state))}${payment.state === "posted" && can("billing.reverse_payment") ? ` <button class="btn btn-light btn-small" data-customer-payment-reverse="${escapeHtml(payment.id)}">Revertir</button>` : ""}</td></tr>`));
      live.entries.forEach((entry) => rows.push(`<tr><td>${new Date(`${entry.entry_date}T12:00:00`).toLocaleDateString("es-MX")}</td><td class="quote-no">${escapeHtml(entry.number)}</td><td>—</td><td>${escapeHtml(entry.memo)}</td><td class="money">${money(entry.debit_total)}</td><td>${badge(entry.state === "posted" ? "Contabilizada" : "Borrador")}</td></tr>`));
      $("#ledger-list").innerHTML = rows.join("") || `<tr><td colspan="6" class="empty">Sin facturas ni cobros todavía.</td></tr>`;
      return;
    }
    const subtotal = db.quotes.reduce((sum, quote) => sum + calc(quote).sub, 0), tax = db.quotes.reduce((sum, quote) => sum + calc(quote).tax, 0), balance = db.quotes.filter((quote) => quote.status === "Lista para FEL").reduce((sum, quote) => sum + calc(quote).total, 0);
    $("#ledger-sales").textContent = money(subtotal); $("#ledger-tax").textContent = money(tax); $("#ledger-balance").textContent = money(balance);
    $("#ledger-list").innerHTML = db.quotes.slice().sort(byDate).map((quote) => `<tr><td>${new Date(`${quote.date}T12:00:00`).toLocaleDateString("es-MX")}</td><td class="quote-no">${escapeHtml(quote.id)}</td><td>${escapeHtml(clientOf(quote.clientId).name)}</td><td>${quote.status === "Lista para FEL" ? "Venta lista para facturar" : "Cotización comercial"}</td><td class="money">${money(calc(quote).total)}</td><td>${badge(quote.status)}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">Sin movimientos todavía.</td></tr>`;
  }

  function renderBankReconciliation() {
    const permitted = backend.connected && can("accounting.view_bankstatement");
    const section = $("#bank-reconciliation-section");
    section.hidden = !permitted;
    if (!permitted) return;
    const accountSelect = $("#bank-account");
    const oldAccount = accountSelect.value;
    accountSelect.innerHTML = live.accounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.code)} · ${escapeHtml(account.name)}</option>`).join("") || `<option value="">No hay cuentas habilitadas para conciliación</option>`;
    if (live.accounts.some((account) => account.id === oldAccount)) accountSelect.value = oldAccount;
    $("#bank-statement-form").hidden = !can("accounting.add_bankstatement");
    const statements = live.bankStatements || [];
    $("#bank-statements-list").innerHTML = statements.map((statement) => `<tr><td>${escapeHtml(statement.account_code)} · ${escapeHtml(statement.account_name)}</td><td>${escapeHtml(statement.period_start)} – ${escapeHtml(statement.period_end)}</td><td>${money(statement.opening_balance)}</td><td>${money(statement.movement_total)}</td><td>${money(statement.closing_balance)}</td><td>${money(statement.balance_difference)}</td><td>${escapeHtml(statement.unmatched_line_count)}</td><td>${statement.state === "reconciled" ? "Conciliado · " : "Pendiente · "}<button class="btn btn-light btn-small" data-bank-statement="${escapeHtml(statement.id)}">Ver movimientos</button>${statement.state === "open" && Number(statement.unmatched_line_count) === 0 && Number(statement.balance_difference) === 0 && can("accounting.reconcile_bankstatement") ? ` <button class="btn btn-primary btn-small" data-bank-reconcile="${escapeHtml(statement.id)}">Cerrar</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="8" class="empty">Aún no hay estados de cuenta.</td></tr>`;
    const active = statements.find((statement) => statement.id === live.selectedBankStatement);
    const autoMatch = $("#bank-auto-match");
    autoMatch.hidden = !active || active.state !== "open" || !can("accounting.change_bankstatement") || !can("accounting.view_journalentry");
    $("#bank-statement-lines").innerHTML = active ? active.lines.map((line) => {
      const pendingEntry = line.adjustment_entry_number ? `<small>Póliza ${escapeHtml(line.adjustment_entry_number)} · ${line.adjustment_entry_state === "posted" ? "contabilizada" : "borrador"}</small><br>` : "";
      const actions = active.state === "open" && can("accounting.change_bankstatement") ? line.journal_line
        ? `<button class="btn btn-light btn-small" data-bank-unmatch="${escapeHtml(active.id)}" data-line-id="${escapeHtml(line.id)}">Deshacer</button>`
        : `${pendingEntry}<button class="btn btn-light btn-small" data-bank-match="${escapeHtml(active.id)}" data-line-id="${escapeHtml(line.id)}">Buscar póliza</button>${!line.adjustment_entry_number && can("accounting.add_journalentry") && can("accounting.view_account") && can("accounting.view_journal") ? ` <button class="btn btn-light btn-small" data-bank-adjustment="${escapeHtml(active.id)}" data-line-id="${escapeHtml(line.id)}">Preparar póliza</button>` : ""}` : "";
      return `<tr><td>${escapeHtml(line.transaction_date)}</td><td>${escapeHtml(line.reference || "—")}</td><td>${escapeHtml(line.description || "—")}</td><td class="money">${money(line.amount)}</td><td>${line.journal_entry_number ? `${escapeHtml(line.journal_entry_number)} · ${escapeHtml(line.journal_entry_memo || "")}` : "Pendiente"}</td><td>${actions}</td></tr>`;
    }).join("") : `<tr><td colspan="6" class="empty">Selecciona un estado de cuenta para ver sus movimientos.</td></tr>`;
  }

  function renderAccountingPeriods() {
    const permitted = backend.connected && can("accounting.view_accountingperiod");
    const section = $("#accounting-periods-section");
    section.hidden = !permitted;
    if (!permitted) return;
    $("#accounting-period-form").hidden = !can("accounting.add_accountingperiod");
    const periods = live.accountingPeriods || [];
    $("#accounting-period-list").innerHTML = periods.map((period) => {
      const history = (period.events || []).map((item) => `${item.action === "closed" ? "Cierre" : "Reapertura"} · ${escapeHtml(item.actor_name)} · ${escapeHtml(item.reason || "sin nota")}`).join("<br>") || "—";
      const action = period.state === "open" && can("accounting.close_accountingperiod")
        ? `<button class="btn btn-primary btn-small" data-period-close="${escapeHtml(period.id)}">Cerrar</button>`
        : period.state === "closed" && can("accounting.reopen_accountingperiod")
          ? `<button class="btn btn-light btn-small" data-period-reopen="${escapeHtml(period.id)}">Reabrir</button>` : "";
      return `<tr><td><strong>${escapeHtml(period.label)}</strong></td><td>${escapeHtml(period.period_start)} – ${escapeHtml(period.period_end)}</td><td>${period.state === "closed" ? "Cerrado" : "Abierto"}</td><td>${escapeHtml(period.closed_by_name || "—")}</td><td>${escapeHtml(period.closed_at ? new Date(period.closed_at).toLocaleString("es-MX") : "—")}</td><td>${history}</td><td>${action}</td></tr>`;
    }).join("") || `<tr><td colspan="7" class="empty">Agrega un mes para habilitar el control de cierre.</td></tr>`;
  }

  function renderPostingConfigurations() {
    const section = $("#posting-configurations-section");
    const permitted = backend.connected && can("accounting.view_postingconfiguration");
    section.hidden = !permitted;
    if (!permitted) return;
    const rules = [
      { type: "customer_invoice", label: "Factura de cliente", journals: ["sales"], fields: [["receivable_account", "Cuenta por cobrar", ["asset"]], ["revenue_account", "Cuenta de ingresos", ["income"]], ["tax_account", "IVA trasladado", ["liability"]]] },
      { type: "customer_credit_note", label: "Nota de crédito de cliente", journals: ["sales"], fields: [["receivable_account", "Cuenta por cobrar", ["asset"]], ["revenue_account", "Cuenta de ingresos", ["income"]], ["tax_account", "IVA trasladado", ["liability"]]] },
      { type: "customer_payment", label: "Cobro de cliente", journals: ["bank", "cash"], fields: [["receivable_account", "Cuenta por cobrar", ["asset"]], ["funds_account", "Banco o caja", ["asset"]]] },
      { type: "supplier_bill", label: "Factura de proveedor", journals: ["purchases"], fields: [["payable_account", "Cuenta por pagar", ["liability"]], ["purchase_account", "Compra o inventario", ["asset", "expense"]], ["supplier_tax_account", "Impuesto declarado de proveedor", ["asset", "expense"]]] },
      { type: "supplier_payment", label: "Pago a proveedor", journals: ["bank", "cash"], fields: [["payable_account", "Cuenta por pagar", ["liability"]], ["funds_account", "Banco o caja", ["asset"]]] },
    ];
    const accounts = live.chartAccounts || [];
    const configurations = live.postingConfigurations || [];
    const journals = live.journals || [];
    const snapshotSummary = (snapshot) => {
      if (!snapshot) return "Configuración creada";
      const labels = { journal: "Diario", receivable_account: "CxC", revenue_account: "Ingresos", tax_account: "Impuestos", funds_account: "Fondos", payable_account: "CxP", purchase_account: "Compras", supplier_tax_account: "Impuesto proveedor", is_active: "Automatización" };
      return Object.entries(labels).map(([key, label]) => {
        const value = snapshot[key];
        const text = key === "is_active" ? (value ? "activa" : "desactivada") : value ? `${value.code} · ${value.name}` : "sin asignar";
        return `${label}: ${text}`;
      }).join(" · ");
    };
    $("#posting-config-list").innerHTML = rules.map((rule) => {
      const config = configurations.find((item) => item.event_type === rule.type);
      const editable = config ? can("accounting.change_postingconfiguration") : can("accounting.add_postingconfiguration");
      const journalOptions = journals.filter((journal) => journal.is_active && rule.journals.includes(journal.kind)).map((journal) => `<option value="${escapeHtml(journal.id)}" ${config?.journal === journal.id ? "selected" : ""}>${escapeHtml(journal.code)} · ${escapeHtml(journal.name)}</option>`).join("");
      const fields = rule.fields.map(([name, label, categories]) => {
        const options = accounts.filter((account) => account.is_active && categories.includes(account.category)).map((account) => `<option value="${escapeHtml(account.id)}" ${config?.[name] === account.id ? "selected" : ""}>${escapeHtml(account.code)} · ${escapeHtml(account.name)}</option>`).join("");
        return `<div class="field"><label>${escapeHtml(label)}</label><select data-posting-field="${name}" required ${editable ? "" : "disabled"}><option value="">Selecciona una cuenta</option>${options}</select></div>`;
      }).join("");
      const history = (config?.change_history || []).map((event) => `<li style="margin:8px 0"><strong>${escapeHtml(event.actor_name)}</strong> · ${escapeHtml(new Date(event.occurred_at).toLocaleString("es-MX"))}<small class="muted" style="display:block">${escapeHtml(snapshotSummary(event.before))} → ${escapeHtml(snapshotSummary(event.after))}</small></li>`).join("");
      return `<article class="card" style="padding:16px"><div class="panel-head"><div><h3 style="margin:0;font-size:15px">${escapeHtml(rule.label)}</h3><p class="muted" style="margin:4px 0">${config?.is_active ? "Activa · crea borradores" : config ? "Desactivada" : "Sin configurar"}</p></div></div><form data-posting-form data-event-type="${rule.type}" data-config-id="${escapeHtml(config?.id || "")}"><div class="field"><label>Diario</label><select data-posting-field="journal" required ${editable ? "" : "disabled"}><option value="">Selecciona un diario</option>${journalOptions}</select></div><div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px">${fields}</div><label class="muted" style="display:flex;align-items:center;gap:8px;margin:12px 0"><input data-posting-field="is_active" type="checkbox" ${config?.is_active ? "checked" : ""} ${editable ? "" : "disabled"}> Crear borradores al registrar este movimiento</label>${editable ? `<button class="btn btn-light btn-small" type="button" data-posting-save>Guardar regla</button>` : ""}</form>${history ? `<details style="margin-top:12px"><summary>Historial de cambios</summary><ol style="padding-left:20px">${history}</ol></details>` : ""}</article>`;
    }).join("");
  }

  function renderAccountingCatalog() {
    const section = $("#accounting-catalog-section");
    const canViewAccounts = backend.connected && can("accounting.view_account");
    const canViewJournals = backend.connected && can("accounting.view_journal");
    section.hidden = !canViewAccounts && !canViewJournals;
    if (section.hidden) return;
    const canAddAccount = can("accounting.add_account"), canChangeAccount = can("accounting.change_account");
    const canAddJournal = can("accounting.add_journal"), canChangeJournal = can("accounting.change_journal");
    $("#account-catalog-form").hidden = !canAddAccount;
    $("#journal-catalog-form").hidden = !canAddJournal;
    const accounts = live.chartAccounts || [];
    $("#account-parent").innerHTML = `<option value="">Sin cuenta padre</option>${accounts.filter((account) => account.is_active).map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.code)} · ${escapeHtml(account.name)}</option>`).join("")}`;
    $("#account-catalog-list").innerHTML = canViewAccounts ? accounts.map((account) => `<tr><td>${escapeHtml(account.code)}</td><td>${escapeHtml(account.name)}${account.parent ? ` · ${escapeHtml(accounts.find((item) => item.id === account.parent)?.code || "")}` : ""}</td><td>${escapeHtml(({asset:"Activo",liability:"Pasivo",equity:"Capital",income:"Ingreso",expense:"Gasto"})[account.category] || account.category)}</td><td>${escapeHtml(account.normal_balance === "debit" ? "Deudor" : "Acreedor")}</td><td>${account.is_active ? "Activa" : "Inactiva"}</td><td>${canChangeAccount ? `<button class="btn btn-light btn-small" data-account-toggle="${escapeHtml(account.id)}" data-active="${account.is_active}">${account.is_active ? "Desactivar" : "Activar"}</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">Aún no hay cuentas.</td></tr>` : "";
    const journals = live.journals || [];
    $("#journal-catalog-list").innerHTML = canViewJournals ? journals.map((journal) => `<tr><td>${escapeHtml(journal.code)}</td><td>${escapeHtml(journal.name)}</td><td>${escapeHtml(({sales:"Ventas",purchases:"Compras",bank:"Banco",cash:"Caja",general:"General"})[journal.kind] || journal.kind)}</td><td>${journal.is_active ? "Activo" : "Inactivo"}</td><td>${canChangeJournal ? `<button class="btn btn-light btn-small" data-journal-toggle="${escapeHtml(journal.id)}" data-active="${journal.is_active}">${journal.is_active ? "Desactivar" : "Activar"}</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">Aún no hay diarios.</td></tr>` : "";
  }

  async function savePostingConfiguration(button) {
    const form = button.closest("[data-posting-form]");
    if (!form) return;
    const configId = form.dataset.configId;
    if (!configId && !can("accounting.add_postingconfiguration")) return;
    if (configId && !can("accounting.change_postingconfiguration")) return;
    const body = { event_type: form.dataset.eventType };
    form.querySelectorAll("[data-posting-field]").forEach((field) => {
      if (field.dataset.postingField === "is_active") body.is_active = field.checked;
      else body[field.dataset.postingField] = field.value || null;
    });
    try {
      if (!body.journal || Object.entries(body).some(([key, value]) => key !== "is_active" && value === null)) {
        toast("Completa el diario y las cuentas de la regla antes de guardarla.");
        return;
      }
      await apiRequest(configId ? `accounting/posting-configurations/${configId}/` : "accounting/posting-configurations/", { method: configId ? "PATCH" : "POST", body });
      await syncFromApi();
      toast("Regla guardada. Los movimientos nuevos crearán pólizas borrador para revisión.");
    } catch (error) { toast(error.message); }
  }

  async function refreshAccountingPeriods() {
    if (!backend.connected || !can("accounting.view_accountingperiod")) return;
    live.accountingPeriods = await apiList("accounting/periods/");
    renderAccountingPeriods();
  }

  function parseBankCsv(text) {
    const source = text.replace(/^\uFEFF/, "");
    const firstLine = source.split(/\r?\n/, 1)[0] || "";
    const delimiter = (firstLine.match(/;/g) || []).length > (firstLine.match(/,/g) || []).length ? ";" : ",";
    const rows = [];
    let row = [], field = "", quoted = false;
    for (let index = 0; index < source.length; index += 1) {
      const char = source[index];
      if (char === '"' && quoted && source[index + 1] === '"') { field += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === delimiter && !quoted) { row.push(field); field = ""; }
      else if ((char === "\n" || char === "\r") && !quoted) { if (char === "\r" && source[index + 1] === "\n") index += 1; row.push(field); if (row.some((cell) => cell.trim())) rows.push(row); row = []; field = ""; }
      else field += char;
    }
    if (field || row.length) { row.push(field); if (row.some((cell) => cell.trim())) rows.push(row); }
    if (rows.length < 2) throw new Error("El CSV debe incluir encabezados y al menos un movimiento.");
    const headers = rows[0].map((header) => header.trim().toLocaleLowerCase("es-MX").normalize("NFD").replace(/[\u0300-\u036f]/g, ""));
    const indexes = { transaction_date: headers.indexOf("fecha"), reference: headers.indexOf("referencia"), description: headers.indexOf("descripcion"), amount: headers.indexOf("importe") };
    if (indexes.transaction_date < 0 || indexes.amount < 0) throw new Error("El CSV debe tener columnas fecha e importe. Usa referencia y descripcion como opcionales.");
    return rows.slice(1).map((values, index) => {
      let rawAmount = (values[indexes.amount] || "").trim().replace(/\s|\$/g, "").replace(/MXN/gi, "");
      if (delimiter === ";" && /,\d{1,2}$/.test(rawAmount)) rawAmount = rawAmount.replace(/\./g, "").replace(",", ".");
      else rawAmount = rawAmount.replace(/,/g, "");
      const amount = Number(rawAmount);
      const transaction_date = (values[indexes.transaction_date] || "").trim();
      if (!/^\d{4}-\d{2}-\d{2}$/.test(transaction_date) || !Number.isFinite(amount) || amount === 0) throw new Error(`Revisa la fecha o el importe de la fila ${index + 2}. Usa AAAA-MM-DD e importe con punto decimal.`);
      return { transaction_date, reference: indexes.reference >= 0 ? values[indexes.reference].trim() : "", description: indexes.description >= 0 ? values[indexes.description].trim() : "", amount: amount.toFixed(2) };
    });
  }

  function parseOpeningBalancesCsv(text) {
    const source = text.replace(/^\uFEFF/, ""), firstLine = source.split(/\r?\n/, 1)[0] || "";
    const delimiter = (firstLine.match(/;/g) || []).length > (firstLine.match(/,/g) || []).length ? ";" : ",";
    const rows = []; let row = [], field = "", quoted = false;
    for (let index = 0; index < source.length; index += 1) {
      const char = source[index];
      if (char === '"' && quoted && source[index + 1] === '"') { field += '"'; index += 1; }
      else if (char === '"') quoted = !quoted;
      else if (char === delimiter && !quoted) { row.push(field); field = ""; }
      else if ((char === "\n" || char === "\r") && !quoted) { if (char === "\r" && source[index + 1] === "\n") index += 1; row.push(field); if (row.some((cell) => cell.trim())) rows.push(row); row = []; field = ""; }
      else field += char;
    }
    if (field || row.length) { row.push(field); if (row.some((cell) => cell.trim())) rows.push(row); }
    if (rows.length < 3) throw new Error("El CSV debe incluir encabezados y al menos dos cuentas.");
    const normalize = (value) => value.trim().toLocaleLowerCase("es-MX").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
    const headers = rows[0].map(normalize), codeIndex = headers.indexOf("codigo"), debitIndex = ["cargo", "debe"].map((value) => headers.indexOf(value)).find((index) => index >= 0), creditIndex = ["abono", "haber"].map((value) => headers.indexOf(value)).find((index) => index >= 0), descriptionIndex = headers.indexOf("descripcion");
    if (codeIndex < 0 || debitIndex === undefined || creditIndex === undefined) throw new Error("El CSV debe tener Código, Cargo y Abono; Descripción es opcional.");
    const lines = rows.slice(1).map((values, offset) => {
      const amount = (index) => { let raw = (values[index] || "").trim().replace(/\s|\$/g, "").replace(/MXN/gi, ""); if (delimiter === ";" && /,\d{1,2}$/.test(raw)) raw = raw.replace(/\./g, "").replace(",", "."); else raw = raw.replace(/,/g, ""); const value = Number(raw || "0"); if (!Number.isFinite(value) || value < 0) throw new Error(`Importe inválido en la fila ${offset + 2}.`); return value; };
      const account_code = (values[codeIndex] || "").trim(), debit = amount(debitIndex), credit = amount(creditIndex);
      if (!account_code || (debit > 0) === (credit > 0)) throw new Error(`Revisa código y saldo de la fila ${offset + 2}; usa cargo o abono, no ambos.`);
      return { account_code, debit: debit.toFixed(2), credit: credit.toFixed(2), description: descriptionIndex >= 0 ? (values[descriptionIndex] || "").trim() : "Saldo inicial" };
    });
    if (new Set(lines.map((line) => line.account_code)).size !== lines.length) throw new Error("Cada cuenta debe aparecer una sola vez en el CSV.");
    return lines;
  }

  async function refreshBankStatements() {
    live.bankStatements = await apiList("accounting/bank-statements/");
    renderBankReconciliation();
  }

  function renderTrialBalance() {
    const permitted = backend.connected && can("accounting.view_journalentry");
    $("#trial-balance-section").hidden = !permitted;
    const canImportOpening = backend.connected && can("accounting.add_journalentry");
    $("#opening-balances-import").hidden = !canImportOpening;
    const generalJournals = (live.journals || []).filter((journal) => journal.is_active && journal.kind === "general");
    $("#opening-balance-journal").innerHTML = `<option value="">Selecciona un diario</option>${generalJournals.map((journal) => `<option value="${escapeHtml(journal.id)}">${escapeHtml(journal.code)} · ${escapeHtml(journal.name)}</option>`).join("")}`;
    if (!permitted) return;
    const report = live.trialBalance;
    $("#trial-balance-list").innerHTML = report?.accounts?.map((account) => `<tr><td><strong>${escapeHtml(account.code)}</strong> · ${escapeHtml(account.name)}</td><td>${money(account.opening_debit)}</td><td>${money(account.opening_credit)}</td><td>${money(account.period_debit)}</td><td>${money(account.period_credit)}</td><td>${money(account.closing_debit)}</td><td>${money(account.closing_credit)}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">Consulta un periodo para ver saldos contabilizados.</td></tr>`;
    const totals = report?.totals || {};
    $("#tb-total-opening-debit").textContent = money(totals.opening_debit);
    $("#tb-total-opening-credit").textContent = money(totals.opening_credit);
    $("#tb-total-period-debit").textContent = money(totals.period_debit);
    $("#tb-total-period-credit").textContent = money(totals.period_credit);
    $("#tb-total-closing-debit").textContent = money(totals.closing_debit);
    $("#tb-total-closing-credit").textContent = money(totals.closing_credit);
    $("#trial-balance-summary").textContent = report ? `Pólizas contabilizadas · ${report.date_from || "desde el inicio"} a ${report.date_to}` : "Consulta cargos y abonos de pólizas contabilizadas.";
  }

  function renderGeneralLedger() {
    const permitted = backend.connected && can("accounting.view_journalentry");
    $("#general-ledger-section").hidden = !permitted;
    if (!permitted) return;
    const report = live.generalLedger;
    $("#general-ledger-list").innerHTML = report?.transactions?.map((item) => `<tr><td>${escapeHtml(item.entry_date)}</td><td class="quote-no">${escapeHtml(item.entry_number)}</td><td>${escapeHtml(item.journal_code)} · ${escapeHtml(item.journal_name)}</td><td>${escapeHtml(item.description || item.memo)}</td><td>${escapeHtml(item.reversal_of ? `Reversa de ${item.reversal_of}` : item.origin_type || "—")}</td><td class="money">${money(item.debit)}</td><td class="money">${money(item.credit)}</td><td class="money">${money(item.balance_debit)}</td><td class="money">${money(item.balance_credit)}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">Captura un código de cuenta y consulta las pólizas contabilizadas del periodo.</td></tr>`;
    $("#general-ledger-summary").textContent = report ? `${report.account.code} · ${report.account.name} · apertura debe ${money(report.opening_debit)} / haber ${money(report.opening_credit)} · cierre debe ${money(report.closing_debit)} / haber ${money(report.closing_credit)}` : "Consulta el detalle de una cuenta y su saldo acumulado.";
    $("#gl-period-debit").textContent = money(report?.period_debit);
    $("#gl-period-credit").textContent = money(report?.period_credit);
    $("#gl-closing-debit").textContent = money(report?.closing_debit);
    $("#gl-closing-credit").textContent = money(report?.closing_credit);
  }

  function renderFinancialStatements() {
    const permitted = backend.connected && can("accounting.view_journalentry");
    $("#financial-statements-section").hidden = !permitted;
    if (!permitted) return;
    const report = live.financialStatements;
    const results = report?.income_statement;
    const balance = report?.balance_sheet;
    const line = (row, prefix) => `<tr><td>${prefix}<strong>${escapeHtml(row.code)}</strong> · ${escapeHtml(row.name)}</td><td>${money(row.amount)}</td></tr>`;
    const resultRows = results ? [...results.income_accounts.map((row) => line(row, "Ingreso · ")), ...results.expense_accounts.map((row) => line(row, "Gasto · "))] : [];
    $("#income-statement-list").innerHTML = resultRows.join("") || `<tr><td colspan="2" class="empty">Consulta un periodo para ver ingresos y gastos contabilizados.</td></tr>`;
    $("#income-total").textContent = money(results?.total_income);
    $("#expense-total").textContent = money(results?.total_expenses);
    $("#net-income-total").textContent = money(results?.net_income);
    const balanceRows = balance ? [
      ...balance.assets.map((row) => line(row, "Activo · ")),
      ...balance.liabilities.map((row) => line(row, "Pasivo · ")),
      ...balance.equity.map((row) => line(row, "Capital · ")),
    ] : [];
    $("#balance-sheet-list").innerHTML = balanceRows.join("") || `<tr><td colspan="2" class="empty">Sin saldos contabilizados hasta la fecha consultada.</td></tr>`;
    $("#assets-total").textContent = money(balance?.total_assets);
    $("#liabilities-total").textContent = money(balance?.total_liabilities);
    $("#equity-total").textContent = money(balance?.total_equity);
    $("#unclosed-result-total").textContent = money(balance?.unclosed_result);
    $("#liabilities-equity-total").textContent = money(balance?.liabilities_and_equity);
    $("#balance-difference").textContent = money(balance?.difference);
  }

  function renderSubledgerReconciliation() {
    const permitted = backend.connected && can("accounting.view_journalentry");
    $("#subledger-reconciliation-section").hidden = !permitted;
    $("#open-items-preview-section").hidden = !permitted;
    $("#opening-batches-section").hidden = !permitted;
    if (!permitted) return;
    const report = live.subledgerReconciliation;
    $("#subledger-reconciliation-list").innerHTML = report?.reconciliations?.map((item) => `<tr><td>${item.key === "receivables" ? "Cuentas por cobrar" : "Cuentas por pagar"}</td><td><strong>${escapeHtml(item.account_code)}</strong> · ${escapeHtml(item.account_name)}</td><td class="money">${money(item.control_balance)}</td><td class="money">${money(item.subledger_balance)}</td><td class="money">${money(item.difference)}</td><td>${item.reconciled ? "Cuadrado" : "Revisar diferencia"}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">Captura las cuentas de control de CxC y CxP para consultar la conciliación.</td></tr>`;
    $("#subledger-reconciliation-summary").textContent = report ? `Saldos MXN al ${report.as_of}; una diferencia distinta de cero requiere revisión contable.` : "Compara los auxiliares abiertos con las cuentas de control contabilizadas a una fecha.";
    renderOpenItemsPreview();
  }

  function renderOpenItemsPreview() {
    const report = live.openItemsPreview;
    const canPrepare = backend.connected && can("accounting.prepare_openingbalancebatch");
    $("#prepare-opening-batch").hidden = !canPrepare || !report?.ready_for_review;
    $("#open-items-preview-summary").textContent = report ? `${report.as_of} · ${report.valid_rows} renglones válidos · ${report.error_rows} renglones con errores · ${report.ready_for_review ? "Saldos cuadrados para revisión" : "No está listo para revisión"}. No se publicaron saldos.` : "Valida el CSV y compara sus saldos con el mayor sin crear facturas ni pólizas. La vista previa no habilita Pagos 2.0 para CFDI históricos.";
    $("#open-items-preview-totals").innerHTML = report?.totals?.map((item) => `<tr><td>${item.direction === "cxc" ? "Cuentas por cobrar" : "Cuentas por pagar"}</td><td><strong>${escapeHtml(item.account_code)}</strong> · ${escapeHtml(item.account_name)}</td><td class="money">${money(item.open_items_total)}</td><td class="money">${money(item.control_balance)}</td><td class="money">${money(item.difference)}</td><td>${item.row_count}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">Selecciona un CSV y pulsa Validar CSV.</td></tr>`;
    $("#open-items-preview-issues").innerHTML = report?.issues?.map((issue) => `<article class="work-log"><strong>Renglón ${issue.row}</strong><small>${issue.errors.map(escapeHtml).join(" · ")}</small></article>`).join("") || "";
  }

  function renderOpeningBalanceBatches() {
    const permitted = backend.connected && can("accounting.view_journalentry");
    $("#opening-batches-section").hidden = !permitted;
    if (!permitted) return;
    const labels = { draft: "Pendiente de revisión", posted: "Publicada", rejected: "Rechazada" };
    $("#opening-batches-list").innerHTML = live.openingBalanceBatches?.map((batch) => {
      const reviewer = batch.reviewed_by_name ? `${escapeHtml(batch.reviewed_by_name)} · ${escapeHtml(batch.reviewed_at || "")}` : "Pendiente";
      const actions = batch.state === "draft" && can("accounting.review_openingbalancebatch")
        ? `<button class="btn btn-primary btn-small" data-opening-batch-review="publish" data-batch-id="${escapeHtml(batch.id)}">Publicar</button> <button class="btn btn-light btn-small" data-opening-batch-review="reject" data-batch-id="${escapeHtml(batch.id)}">Rechazar</button>`
        : escapeHtml(batch.review_note || "—");
      const detail = `<details data-opening-batch-detail="${escapeHtml(batch.id)}"><summary>Ver partidas (${batch.item_count})</summary><div class="muted">Abre el detalle para comparar RFC, folios, origen, fechas e importes antes de revisar.</div><div class="opening-batch-detail-body"></div></details>`;
      return `<tr><td>${escapeHtml(batch.cutoff_date)}</td><td>${escapeHtml(labels[batch.state] || batch.state)}</td><td>${batch.item_count}</td><td class="money">${money(batch.receivables_total)}</td><td class="money">${money(batch.payables_total)}</td><td>${escapeHtml(batch.created_by_name)}<br><small>${reviewer}</small></td><td>${detail}<div style="margin-top:8px">${actions}</div></td></tr>`;
    }).join("") || `<tr><td colspan="7" class="empty">Aún no hay lotes preparados.</td></tr>`;
  }

  async function loadOpeningBalanceBatches() {
    if (!backend.connected || !can("accounting.view_journalentry")) return;
    try {
      const response = await apiRequest("accounting/opening-balance-batches/");
      live.openingBalanceBatches = Array.isArray(response) ? response : (response.results || []);
      renderOpeningBalanceBatches();
    } catch (error) { live.openingBalanceBatches = []; renderOpeningBalanceBatches(); toast(error.message); }
  }

  async function loadOpeningBalanceBatchDetail(details) {
    const batchId = details.dataset.openingBatchDetail;
    if (!batchId || details.dataset.loading === "true" || live.openingBalanceBatchDetails[batchId]) return;
    details.dataset.loading = "true";
    const body = details.querySelector(".opening-batch-detail-body");
    body.innerHTML = `<p class="muted">Cargando partidas…</p>`;
    try {
      const batch = await apiRequest(`accounting/opening-balance-batches/${encodeURIComponent(batchId)}/`);
      live.openingBalanceBatchDetails[batchId] = batch;
      const directionLabel = (item) => item.direction === "cxc" ? "CxC" : "CxP";
      const visibleItems = batch.items.slice(0, 100);
      body.innerHTML = `<p>${batch.item_count} partidas · se muestran ${visibleItems.length}. La descarga contiene el lote completo.</p><button class="btn btn-light btn-small" data-opening-batch-export="${escapeHtml(batchId)}">Descargar partidas CSV</button><div class="table-wrap" style="max-height:360px;overflow:auto;margin-top:8px"><table><thead><tr><th>Tipo</th><th>RFC</th><th>Folio externo</th><th>Sistema origen</th><th>Emisión</th><th>Vencimiento</th><th>Total original</th><th>Pagado previo</th><th>Saldo abierto</th></tr></thead><tbody>${visibleItems.map((item) => `<tr><td>${directionLabel(item)}</td><td>${escapeHtml(item.counterparty_rfc)}</td><td>${escapeHtml(item.external_number)}</td><td>${escapeHtml(item.source_system)}</td><td>${escapeHtml(item.issue_date)}</td><td>${escapeHtml(item.due_date)}</td><td class="money">${money(item.original_total)}</td><td class="money">${money(item.paid_before_cutoff)}</td><td class="money">${money(item.open_balance)}</td></tr>`).join("")}</tbody></table></div>`;
    } catch (error) {
      body.innerHTML = `<p class="muted">No se pudo cargar el detalle. <button class="btn btn-quiet btn-small" data-opening-batch-detail-retry="${escapeHtml(batchId)}">Reintentar</button></p>`;
      toast(error.message);
    } finally { details.dataset.loading = "false"; }
  }

  function exportOpeningBalanceBatch(batchId) {
    const batch = live.openingBalanceBatchDetails[batchId];
    if (!batch) { toast("Abre primero el detalle de este lote."); return; }
    downloadSafeCsv(`apertura-auxiliar-${batch.cutoff_date}-${batchId.slice(0, 8)}.csv`, [
      ["Tipo", "RFC", "Folio externo", "Sistema origen", "Fecha emisión", "Fecha vencimiento", "Moneda", "Total original", "Pagado previo", "Saldo abierto"],
      ...batch.items.map((item) => [item.direction === "cxc" ? "CxC" : "CxP", item.counterparty_rfc, item.external_number, item.source_system, item.issue_date, item.due_date, item.currency, item.original_total, item.paid_before_cutoff, item.open_balance]),
    ]);
  }

  async function prepareOpeningBalanceBatch() {
    if (!backend.connected || !can("accounting.prepare_openingbalancebatch")) return;
    const report = live.openItemsPreview;
    const file = $("#open-items-file").files?.[0];
    const accountsByCode = new Map((live.chartAccounts || []).map((account) => [account.code, account]));
    const receivables = accountsByCode.get($("#recon-ar-account").value.trim());
    const payables = accountsByCode.get($("#recon-ap-account").value.trim());
    if (!report?.ready_for_review || !file || !receivables || !payables || !$("#recon-as-of").value) {
      toast("Valida primero el CSV y confirma las cuentas de control y la fecha de corte."); return;
    }
    const form = new FormData(); form.set("file", file); form.set("cutoff_date", $("#recon-as-of").value);
    form.set("receivables_account", receivables.id); form.set("payables_account", payables.id);
    try {
      const batch = await apiRequest("accounting/opening-balance-batches/prepare/", { method: "POST", body: form });
      live.openItemsPreview = null; renderOpenItemsPreview(); await loadOpeningBalanceBatches();
      toast(`Lote guardado para revisión (${batch.item_count} partidas).`);
    } catch (error) { toast(`No se pudo preparar el lote: ${error.message}`); }
  }

  async function reviewOpeningBalanceBatch(batchId, decision) {
    if (!can("accounting.review_openingbalancebatch")) return;
    let note = "";
    if (decision === "publish") {
      if (!confirm("¿Publicar este lote de saldos operativos? La decisión quedará registrada y no creará pólizas.")) return;
      note = prompt("Nota de revisión (opcional):", "") || "";
    } else {
      note = prompt("Explica el motivo del rechazo (mínimo 10 caracteres):", "") || "";
      if (note.trim().length < 10) { toast("El motivo de rechazo debe tener al menos 10 caracteres."); return; }
    }
    try {
      await apiRequest(`accounting/opening-balance-batches/${encodeURIComponent(batchId)}/review/`, { method: "POST", body: { decision, note } });
      await loadOpeningBalanceBatches(); toast(decision === "publish" ? "Lote publicado como saldo operativo." : "Lote rechazado y referencias liberadas.");
    } catch (error) { toast(`No se pudo revisar el lote: ${error.message}`); }
  }

  function downloadSafeCsv(filename, rows) {
    const csv = `\ufeff${rows.map((row) => row.map((value) => {
      const raw = String(value ?? "");
      const numeric = /^-?\d+(\.\d+)?$/.test(raw);
      const safe = !numeric && /^\s*[=+\-@]/.test(raw) ? `'${raw}` : raw;
      return `"${safe.replaceAll('"', '""')}"`;
    }).join(",")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  async function loadTrialBalance() {
    if (!backend.connected || !can("accounting.view_journalentry")) return;
    const query = new URLSearchParams();
    if ($("#trial-balance-from").value) query.set("date_from", $("#trial-balance-from").value);
    if ($("#trial-balance-to").value) query.set("date_to", $("#trial-balance-to").value);
    try {
      const suffix = query.toString();
      const accountCode = $("#general-ledger-account").value.trim();
      const generalQuery = new URLSearchParams(query);
      if (accountCode) generalQuery.set("account_code", accountCode);
      const [trialBalance, financialStatements] = await Promise.all([
        apiRequest(`accounting/reports/trial-balance/?${suffix}`),
        apiRequest(`accounting/reports/financial-statements/?${suffix}`),
      ]);
      live.trialBalance = trialBalance;
      live.financialStatements = financialStatements;
      live.generalLedger = null;
      if (accountCode) {
        try { live.generalLedger = await apiRequest(`accounting/reports/general-ledger/?${generalQuery.toString()}`); }
        catch (error) { toast(error.message); }
      }
      renderTrialBalance();
      renderGeneralLedger();
      renderFinancialStatements();
      renderSubledgerReconciliation();
      await loadOpeningBalanceBatches();
    } catch (error) { toast(error.message); }
  }

  async function loadSubledgerReconciliation() {
    if (!backend.connected || !can("accounting.view_journalentry")) return;
    const query = new URLSearchParams({
      receivables_account_code: $("#recon-ar-account").value.trim(),
      payables_account_code: $("#recon-ap-account").value.trim(),
    });
    if ($("#recon-as-of").value) query.set("as_of", $("#recon-as-of").value);
    try {
      live.subledgerReconciliation = await apiRequest(`accounting/reports/subledger-reconciliation/?${query}`);
      renderSubledgerReconciliation();
    } catch (error) { live.subledgerReconciliation = null; renderSubledgerReconciliation(); toast(error.message); }
  }

  async function previewOpenItems() {
    if (!backend.connected || !can("accounting.view_journalentry")) return;
    const file = $("#open-items-file").files?.[0];
    if (!file) { toast("Selecciona el archivo CSV de partidas abiertas."); return; }
    const form = new FormData();
    form.set("file", file);
    form.set("as_of", $("#recon-as-of").value);
    form.set("receivables_account_code", $("#recon-ar-account").value.trim());
    form.set("payables_account_code", $("#recon-ap-account").value.trim());
    try {
      live.openItemsPreview = await apiRequest("accounting/reports/open-items-preview/", { method: "POST", body: form });
      renderOpenItemsPreview();
    } catch (error) { live.openItemsPreview = null; renderOpenItemsPreview(); toast(error.message); }
  }

  function renderIssuedCfdiRegister() {
    const report = live.issuedCfdiRegister;
    if (!report) return;
    const taxSummary = (items) => items.map((tax) => `${tax.tax_code} ${tax.rate === "Exento" ? tax.rate : `${Number(tax.rate || 0) * 100}%`}: ${money(tax.amount)}`).join(" · ") || "Sin traslados";
    $("#fiscal-sales-register-summary").textContent = `${report.active_count} CFDI sin cancelación confirmada · Ingreso: ${money(report.income_active_total)} (impuestos: ${taxSummary(report.income_taxes)}) · Egreso: ${money(report.egress_active_total)} (impuestos: ${taxSummary(report.egress_taxes)}) · Cancelados: ${report.cancelled_count} (${money(report.cancelled_total)})`;
    $("#fiscal-sales-register-list").innerHTML = report.rows.map((row) => {
      const taxes = row.taxes.map((tax) => `${escapeHtml(tax.tax_code)} ${escapeHtml(tax.rate === "Exento" ? tax.rate : `${Number(tax.rate || 0) * 100}%`)}: ${money(tax.amount)}`).join("<br>") || "—";
      const related = row.related_uuids.length ? `<br><small>Relacionado: ${escapeHtml(row.related_uuids.join(", "))}</small>` : "";
      return `<tr><td>${escapeHtml(row.issue_date)}</td><td>${escapeHtml(row.document_type_label)} · ${escapeHtml(row.source_number)}<br><small>${escapeHtml(row.uuid)}</small>${related}</td><td>${escapeHtml(row.recipient_name)}</td><td>${escapeHtml(row.recipient_rfc)}</td><td class="money">${money(row.subtotal)}</td><td>${taxes}</td><td class="money">${money(row.total)}</td><td>${escapeHtml(row.state_label)}</td></tr>`;
    }).join("") || `<tr><td colspan="8" class="empty">No hay CFDI de ingreso o egreso timbrados en el periodo.</td></tr>`;
  }

  async function loadIssuedCfdiRegister() {
    if (!backend.connected || !can("billing.view_fiscaldocument")) return;
    const query = new URLSearchParams();
    if ($("#fiscal-register-from").value) query.set("date_from", $("#fiscal-register-from").value);
    if ($("#fiscal-register-to").value) query.set("date_to", $("#fiscal-register-to").value);
    try {
      live.issuedCfdiRegister = await apiRequest(`billing/fiscal-documents/issued-register/?${query.toString()}`);
      renderIssuedCfdiRegister();
    } catch (error) { toast(error.message); }
  }

  function renderSupplierCfdiRegister() {
    const report = live.purchasing.supplierCfdiRegister;
    if (!report) return;
    const taxSummary = report.taxes.map((tax) => `${tax.tax_code} ${tax.rate === "Exento" ? tax.rate : `${Number(tax.rate || 0) * 100}%`}: ${money(tax.amount)}`).join(" · ") || "Sin traslados";
    $("#supplier-cfdi-register-summary").textContent = `${report.document_count} XML · Subtotal ${money(report.subtotal)} · Impuesto declarado ${money(report.declared_tax_total)} · Total ${money(report.total)} · Desglose: ${taxSummary}`;
    $("#supplier-cfdi-register-list").innerHTML = report.rows.map((row) => {
      const taxes = row.taxes.map((tax) => `${escapeHtml(tax.tax_code)} ${escapeHtml(tax.rate === "Exento" ? tax.rate : `${Number(tax.rate || 0) * 100}%`)}: ${money(tax.amount)} (base ${money(tax.base)})`).join("<br>") || "—";
      return `<tr><td>${escapeHtml(row.invoice_date)}</td><td>${escapeHtml(row.invoice_number)}<br><small>${escapeHtml(row.uuid)}</small></td><td>${escapeHtml(row.supplier_name)}</td><td>${escapeHtml(row.issuer_rfc)}</td><td class="money">${money(row.subtotal)}</td><td class="money">${money(row.tax_total)}</td><td>${taxes}</td><td class="money">${money(row.total)}</td><td>${escapeHtml(apiStateLabel(row.payable_status))}</td></tr>`;
    }).join("") || `<tr><td colspan="9" class="empty">No hay XML CFDI de proveedores adjuntos en el periodo.</td></tr>`;
  }

  async function loadSupplierCfdiRegister() {
    if (!backend.connected || !can("purchasing.view_supplierbill")) return;
    const query = new URLSearchParams();
    if ($("#supplier-cfdi-register-from").value) query.set("date_from", $("#supplier-cfdi-register-from").value);
    if ($("#supplier-cfdi-register-to").value) query.set("date_to", $("#supplier-cfdi-register-to").value);
    try {
      live.purchasing.supplierCfdiRegister = await apiRequest(`purchasing/supplier-bills/cfdi-register/?${query.toString()}`);
      renderSupplierCfdiRegister();
    } catch (error) { toast(error.message); }
  }

  function go(view) {
    document.querySelectorAll(".nav button").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
    document.querySelectorAll(".dash-view").forEach((element) => element.classList.toggle("hidden", view !== "inicio"));
    document.querySelectorAll(".section-view").forEach((element) => element.classList.toggle("active", element.id === `view-${view}`));
    const names = { inicio: "Resumen", oportunidades: "Oportunidades", cotizaciones: "Cotizaciones", proyectos: "Proyectos y servicios", soporte: "Soporte técnico", clientes: "Clientes", inventario: "Inventario", compras: "Compras", gastos: "Gastos", facturacion: "Facturación y cobros", contabilidad: "Contabilidad" };
    $("#crumb-title").textContent = names[view] || "Resumen"; $("#sidebar").classList.remove("open"); window.scrollTo({ top: 0, behavior: "smooth" });
    if (view === "contabilidad" && backend.connected) { loadTrialBalance(); renderAccountingPeriods(); renderPostingConfigurations(); renderAccountingCatalog(); $("#fiscal-sales-register-section").hidden = !can("billing.view_fiscaldocument"); if (!$("#fiscal-sales-register-section").hidden) loadIssuedCfdiRegister(); $("#supplier-cfdi-register-section").hidden = !can("purchasing.view_supplierbill"); if (!$("#supplier-cfdi-register-section").hidden) loadSupplierCfdiRegister(); }
  }

  function newLine(line = null) {
    const row = document.createElement("div"); row.className = "line-item";
    row.innerHTML = `<input class="line-name" placeholder="Descripción del concepto" required><select class="line-product" aria-label="Vincular producto del catálogo"></select><select class="line-kind"><option>Equipo</option><option>Material</option><option>Instalación</option><option>Servicio</option></select><input class="line-qty" type="number" min="0.01" step="0.01" value="1" aria-label="Cantidad"><input class="line-price" type="number" min="0" step="0.01" placeholder="Precio unitario" aria-label="Precio unitario"><input class="line-tax" type="number" min="0" max="100" step=".01" placeholder="IVA %" aria-label="IVA del concepto (%)"><input class="line-discount" type="number" min="0" max="100" step=".01" value="0" placeholder="Desc. %" aria-label="Descuento porcentual"><label class="line-optional-label"><input class="line-optional" type="checkbox"> Opcional</label><button type="button" class="remove-line" aria-label="Quitar concepto">×</button>`;
    row.querySelector(".line-tax").value = line?.taxRate ?? (Number($("#q-tax").value) || 0);
    if (line) { row.querySelector(".line-name").value = line.name; row.querySelector(".line-kind").value = line.kind; row.querySelector(".line-qty").value = line.qty; row.querySelector(".line-price").value = line.price; row.querySelector(".line-discount").value = line.discountPercent || 0; row.querySelector(".line-optional").checked = Boolean(line.isOptional); }
    const productSelect = row.querySelector(".line-product"), kindSelect = row.querySelector(".line-kind");
    const updateProducts = (selected = "") => {
      const stockable = ["Equipo", "Material"].includes(kindSelect.value);
      const products = live.inventory.products.filter((product) => product.is_active && product.kind === (stockable ? "stockable" : "service"));
      productSelect.innerHTML = `<option value="">Sin vínculo al catálogo</option>${products.map((product) => `<option value="${escapeHtml(product.id)}">${escapeHtml(product.sku)} · ${escapeHtml(product.name)}</option>`).join("")}`;
      productSelect.value = products.some((product) => product.id === selected) ? selected : "";
    };
    updateProducts(line?.catalogProduct || "");
    kindSelect.addEventListener("change", () => updateProducts());
    productSelect.addEventListener("change", () => { const product = live.inventory.products.find((item) => item.id === productSelect.value); if (product) row.querySelector(".line-name").value = product.name; });
    row.querySelectorAll("input,select").forEach((input) => input.addEventListener("input", updateTotals));
    row.querySelector(".remove-line").addEventListener("click", () => { row.remove(); updateTotals(); });
    $("#line-items").appendChild(row); updateTotals();
  }

  function updateTotals() {
    const rows = [...document.querySelectorAll("#line-items .line-item")];
    const amount = (row) => { const gross = round2((Number(row.querySelector(".line-qty").value) || 0) * (Number(row.querySelector(".line-price").value) || 0)); const percent = Math.min(100, Math.max(0, Number(row.querySelector(".line-discount").value) || 0)); return round2(gross - round2(gross * percent / 100)); };
    const taxAmount = (row) => round2(amount(row) * (Number(row.querySelector(".line-tax").value) || 0) / 100);
    const required = rows.filter((row) => !row.querySelector(".line-optional").checked), optional = rows.filter((row) => row.querySelector(".line-optional").checked);
    const subtotal = required.reduce((sum, row) => sum + amount(row), 0), tax = required.reduce((sum, row) => sum + taxAmount(row), 0);
    const optionalTotal = optional.reduce((sum, row) => sum + amount(row) + taxAmount(row), 0);
    $("#subtotal").textContent = money(subtotal); $("#tax-total").textContent = money(tax); $("#grand-total").textContent = `${money(subtotal + tax)}${optionalTotal ? ` + ${money(optionalTotal)} opciones` : ""}`;
  }

  async function openCustomerContacts(customerId) {
    const customer = db.clients.find((item) => item.id === customerId);
    if (!customer || !backend.connected) return;
    const modal = $("#customer-contacts-modal");
    modal.dataset.customerId = customerId;
    $("#customer-contacts-title").textContent = `Contactos · ${customer.name}`;
    $("#customer-contact-form").reset(); delete $("#customer-contact-form").dataset.edit;
    $("#customer-contact-form").hidden = true;
    $("#customer-contact-add").hidden = !can("sales.add_customer");
    $("#customer-contacts-list").innerHTML = `<tr><td colspan="6" class="empty">Cargando contactos…</td></tr>`;
    modal.classList.add("open");
    try {
      const contacts = await apiList(`customer-contacts/?customer=${encodeURIComponent(customerId)}&active=all`);
      modal.contacts = contacts;
      $("#customer-contacts-list").innerHTML = contacts.map((contact) => `<tr><td>${escapeHtml(contact.name)}${contact.is_primary && contact.is_active ? ` <span class="badge approved">Principal</span>` : ""}</td><td>${escapeHtml(contact.role || "—")}</td><td>${escapeHtml(contact.email || "—")}</td><td>${escapeHtml(contact.phone || "—")}</td><td>${contact.is_active ? "Activo" : "Archivado"}</td><td>${can("sales.change_customer") ? `<button class="btn-quiet" data-contact-edit="${escapeHtml(contact.id)}">Editar</button>${contact.is_active ? `<button class="btn-quiet" data-contact-active="${escapeHtml(contact.id)}" data-active="false">Archivar</button>` : `<button class="btn-quiet" data-contact-active="${escapeHtml(contact.id)}" data-active="true">Reactivar</button>`}` : ""}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">No hay contactos registrados.</td></tr>`;
    } catch (error) { $("#customer-contacts-list").innerHTML = `<tr><td colspan="6" class="empty">${escapeHtml(error.message)}</td></tr>`; }
  }

  async function openQuote(opportunityId = "") {
    if (!db.clients.length) { toast("Registra un cliente antes de crear una cotización."); go("clientes"); return; }
    const opportunity = db.opportunities.find((item) => item.id === opportunityId);
    const form = $("#quote-form"); form.reset(); delete form.dataset.edit;
    $("#modal-title").textContent = "Nueva cotización"; $("#quote-save-button").textContent = "Guardar cotización";
    $("#q-template").disabled = false; $("#save-quote-template").hidden = !backend.connected || !can("sales.add_quote");
    $("#q-date").value = todayISO(); $("#q-client").value = opportunity?.customer || db.clients[0].id; $("#q-payment-term-days").value = clientOf($("#q-client").value).paymentTermDays ?? ""; updateQuoteOpportunityOptions(); $("#q-opportunity").value = opportunity?.id || ""; await updateQuoteContactOptions(); await updateQuoteSiteOptions(); $("#line-items").innerHTML = ""; newLine(); $("#quote-modal").classList.add("open"); setTimeout(() => $("#q-title").focus(), 80);
  }

  async function openQuoteForEdit(quote) {
    if (!backend.connected || !quote?.backendId || quote.apiStatus !== "draft" || !can("sales.change_quote")) return;
    const form = $("#quote-form"); form.reset(); form.dataset.edit = quote.backendId;
    $("#modal-title").textContent = `Editar ${quote.id}`; $("#quote-save-button").textContent = "Guardar cambios";
    $("#q-template").value = ""; $("#q-template").disabled = true; $("#save-quote-template").hidden = true;
    $("#q-client").value = quote.clientId; updateQuoteOpportunityOptions(); await updateQuoteContactOptions(quote.customerContactId);
    if (quote.opportunityId && ![...$("#q-opportunity").options].some((option) => option.value === quote.opportunityId)) {
      const opportunity = db.opportunities.find((item) => item.id === quote.opportunityId);
      if (opportunity) $("#q-opportunity").add(new Option(`${opportunity.name} · etapa actual`, opportunity.id));
    }
    $("#q-opportunity").value = quote.opportunityId || "";
    await updateQuoteSiteOptions();
    if (quote.customerSiteId && ![...$("#q-service-site").options].some((option) => option.value === quote.customerSiteId)) {
      $("#q-service-site").add(new Option(`${quote.serviceSiteName || "Sitio guardado"} · ${quote.serviceAddress || "domicilio histórico"}`, quote.customerSiteId));
    }
    $("#q-service-site").value = quote.customerSiteId || "";
    $("#q-title").value = quote.title || ""; $("#q-date").value = quote.date || todayISO();
    $("#q-expiry").value = quote.expiry || ""; $("#q-payment-term-days").value = quote.paymentTermDays ?? ""; $("#q-notes").value = quote.notes || "";
    $("#q-tax").value = quote.lines[0]?.taxRate ?? 16;
    $("#line-items").innerHTML = "";
    quote.lines.forEach((line) => newLine(line));
    $("#quote-modal").classList.add("open"); setTimeout(() => $("#q-title").focus(), 80);
  }

  function applyQuoteTemplate(template) {
    if (!template) return;
    const inactiveProduct = template.lines.find((line) => line.catalog_product && !live.inventory.products.some((product) => product.id === line.catalog_product && product.is_active));
    if (inactiveProduct) { toast("La plantilla usa un producto inactivo o no disponible para tu perfil. Actualízala antes de usarla."); $("#q-template").value = ""; return; }
    const kindNames = { equipment: "Equipo", material: "Material", installation: "Instalación", service: "Servicio" };
    $("#q-title").value = template.title;
    $("#q-tax").value = template.tax_rate;
    $("#q-notes").value = template.notes || "";
    const days = Number(template.validity_days) || 0;
    if (days) { const date = new Date(`${$("#q-date").value}T12:00:00`); date.setDate(date.getDate() + days); $("#q-expiry").value = date.toISOString().slice(0, 10); }
    else $("#q-expiry").value = "";
    $("#line-items").innerHTML = "";
    template.lines.forEach((line) => newLine({ name: line.description, kind: kindNames[line.kind] || line.kind, qty: Number(line.quantity), price: Number(line.unit_price), discountPercent: Number(line.discount_percent || 0), taxRate: Number(line.tax_rate ?? template.tax_rate), isOptional: Boolean(line.is_optional), catalogProduct: line.catalog_product || "" }));
    updateTotals();
  }

  async function saveQuoteTemplate() {
    if (!backend.connected || !can("sales.add_quote")) { toast("Conecta el ERP y usa un perfil autorizado para guardar plantillas."); return; }
    const name = prompt("Nombre para esta plantilla de cotización:");
    if (!name?.trim()) return;
    const issue = new Date(`${$("#q-date").value || todayISO()}T12:00:00`);
    const expiry = $("#q-expiry").value ? new Date(`${$("#q-expiry").value}T12:00:00`) : null;
    const validityDays = expiry ? Math.max(0, Math.round((expiry - issue) / 86400000)) : 30;
    const kindMap = { Equipo: "equipment", Material: "material", Instalación: "installation", Servicio: "service" };
    const lines = [...document.querySelectorAll("#line-items .line-item")].map((row) => ({
      kind: kindMap[row.querySelector(".line-kind").value], catalog_product: row.querySelector(".line-product").value || null,
      description: row.querySelector(".line-name").value.trim(), quantity: Number(row.querySelector(".line-qty").value) || 1,
      unit_price: Number(row.querySelector(".line-price").value) || 0, discount_percent: Number(row.querySelector(".line-discount").value) || 0, tax_rate: Number(row.querySelector(".line-tax").value) || 0, is_optional: row.querySelector(".line-optional").checked,
    })).filter((line) => line.description);
    if (!lines.length) { toast("Agrega conceptos antes de guardar la plantilla."); return; }
    try {
      await apiRequest("quote-templates/", { method: "POST", body: { name: name.trim(), title: $("#q-title").value.trim() || name.trim(), validity_days: validityDays, notes: $("#q-notes").value.trim(), tax_rate: Number($("#q-tax").value) || 0, lines } });
      await syncFromApi(); toast("Plantilla guardada para futuras cotizaciones.");
    } catch (error) { toast(error.message); }
  }

  function localQuoteAction(quote) {
    if (quote.status === "Borrador") { quote.status = "Enviada"; toast("Cotización enviada."); }
    else if (quote.status === "Enviada") {
      quote.status = "Aprobada";
      if (!db.projects.some((project) => project.quoteId === quote.id)) db.projects.unshift({ id: `P-${String(db.projects.length + 1).padStart(3, "0")}`, title: quote.title, clientId: quote.clientId, quoteId: quote.id, status: "Por programar", progress: 0, date: todayISO() });
      toast("Cotización aprobada; proyecto agregado.");
    } else if (quote.status === "Aprobada") { quote.status = "Lista para FEL"; toast("Venta lista para completar en FEL."); }
    else if (quote.status === "Lista para FEL") {
      const amount = prompt(`¿Cuánto se cobró de ${money(calc(quote).total)}?`);
      if (amount !== null && Number(amount) > 0) { quote.paid = (Number(quote.paid) || 0) + Number(amount); if (quote.paid >= calc(quote).total) quote.status = "Pagada"; toast("Cobro guardado en los datos de demostración."); }
    }
    db.activities.unshift({ text: `${quote.id} · ${quote.status}`, time: `Hoy · ${new Date().toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}`, icon: "✓" }); save(); render();
  }

  document.querySelectorAll(".nav button").forEach((button) => button.addEventListener("click", () => go(button.dataset.view)));
  $("#refresh-expenses").addEventListener("click", async () => { try { await syncFromApi(); toast("Gastos actualizados."); } catch (error) { toast(error.message); } });
  $("#expense-date").value = todayISO();
  $("#expense-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { category: $("#expense-category").value, description: $("#expense-description").value.trim(), merchant: $("#expense-merchant").value.trim(), expense_date: $("#expense-date").value, amount: $("#expense-amount").value, currency: "MXN", paid_by: $("#expense-paid-by").value, reference: $("#expense-reference").value.trim() };
    try {
      const expense = await apiRequest("expenses/items/", { method: "POST", body });
      const file = $("#expense-receipt-file").files[0];
      if (file) { const formData = new FormData(); formData.append("file", file); await apiRequest(`expenses/items/${expense.id}/receipt/`, { method: "POST", body: formData }); }
      event.currentTarget.reset(); $("#expense-date").value = todayISO(); await syncFromApi(); toast("Gasto guardado.");
    } catch (error) { toast(error.message); }
  });
  $("#expense-category-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { code: $("#expense-category-code").value.trim().toUpperCase(), name: $("#expense-category-name").value.trim(), expense_account: $("#expense-category-account").value, receipt_required: $("#expense-category-receipt").checked };
    try { await apiRequest("expenses/categories/", { method: "POST", body }); event.currentTarget.reset(); $("#expense-category-receipt").checked = true; await syncFromApi(); toast("Categoría de gasto guardada."); } catch (error) { toast(error.message); }
  });
  $("#expense-posting-config-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { journal: $("#expense-journal").value, reimbursement_journal: $("#expense-reimbursement-journal").value, employee_payable_account: $("#expense-payable-account").value, company_funds_account: $("#expense-funds-account").value, is_active: true };
    try { await apiRequest("expenses/posting-configurations/", { method: "POST", body }); await syncFromApi(); toast("Configuración contable activa."); } catch (error) { toast(error.message); }
  });
  $("#create-expense-report").addEventListener("click", async () => {
    const expense_ids = [...document.querySelectorAll("[data-expense-select]:checked")].map((input) => input.dataset.expenseSelect);
    if (!expense_ids.length) { toast("Selecciona al menos un gasto."); return; }
    try { await apiRequest("expenses/reports/", { method: "POST", body: { expense_ids } }); await syncFromApi(); toast("Reporte creado. Revísalo y envíalo a aprobación."); } catch (error) { toast(error.message); }
  });
  document.addEventListener("change", async (event) => {
    const input = event.target.closest("[data-expense-upload]");
    if (!input?.files?.[0]) return;
    const formData = new FormData(); formData.append("file", input.files[0]);
    try { await apiRequest(`expenses/items/${input.dataset.expenseUpload}/receipt/`, { method: "POST", body: formData }); await syncFromApi(); toast("Comprobante adjuntado."); } catch (error) { toast(error.message); }
  });
  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-expense-edit]");
    if (!form) return;
    event.preventDefault();
    const fields = new FormData(form), body = Object.fromEntries(fields.entries());
    try { await apiRequest(`expenses/items/${form.dataset.expenseEdit}/`, { method: "PATCH", body }); await syncFromApi(); toast("Gasto corregido. Vuelve a enviar el reporte cuando esté listo."); } catch (error) { toast(error.message); }
  });
  document.addEventListener("click", async (event) => {
    const reimburseButton = event.target.closest("[data-expense-reimburse]");
    if (reimburseButton) {
      const report = live.expenses.reports.find((item) => String(item.id) === reimburseButton.dataset.expenseReimburse);
      if (!report) return;
      $("#expense-reimbursement-report").value = report.id;
      $("#expense-reimbursement-idempotency").value = newUuid();
      $("#expense-reimbursement-amount").value = Number(report.reimbursement_balance).toFixed(2);
      $("#expense-reimbursement-amount").max = Number(report.reimbursement_balance).toFixed(2);
      $("#expense-reimbursement-date").value = todayISO();
      const reimbursementConfig = live.expenses.configurations.find((configuration) => configuration.is_active && configuration.reimbursement_journal);
      const journal = live.journals.find((item) => String(item.id) === String(reimbursementConfig?.reimbursement_journal));
      $("#expense-reimbursement-method").innerHTML = journal?.kind === "cash" ? `<option value="cash">Caja</option>` : `<option value="bank_transfer">Transferencia bancaria</option><option value="check">Cheque</option>`;
      $("#expense-reimbursement-method").value = journal?.kind === "cash" ? "cash" : "bank_transfer";
      $("#expense-reimbursement-reference").value = "";
      $("#expense-reimbursement-confirm").checked = false;
      $("#expense-reimbursement-modal").classList.add("open");
      return;
    }
    const reverseReimbursementButton = event.target.closest("[data-expense-reimbursement-reverse]");
    if (reverseReimbursementButton) {
      const reason = prompt("Motivo de la reversa (mínimo 10 caracteres):") || "";
      if (reason.trim().length < 10 || !confirm("Confirma que el pago fue devuelto, cancelado o registrado por error.")) return;
      try {
        await apiRequest(`expenses/reports/${reverseReimbursementButton.dataset.expenseReimbursementReverse}/reimbursements/${reverseReimbursementButton.dataset.reimbursementId}/reverse/`, { method: "POST", body: { reason, confirm_payment_returned: true } });
        await syncFromApi(); toast("Reembolso revertido; se creó una póliza inversa.");
      } catch (error) { toast(`No se pudo revertir: ${error.message}`); }
      return;
    }
    const actionButton = event.target.closest("[data-expense-report-action]");
    if (actionButton) {
      const id = actionButton.dataset.reportId, action = actionButton.dataset.expenseReportAction;
      let reason = "";
      if (action === "reject") { reason = prompt("Motivo del rechazo:") || ""; if (!reason.trim()) return; }
      try { await apiRequest(`expenses/reports/${id}/${action}/`, { method: "POST", body: action === "reject" ? { reason } : {} }); await syncFromApi(); toast(action === "prepare-journal" ? "Póliza borrador creada para revisión." : "Reporte actualizado."); } catch (error) { toast(error.message); }
      return;
    }
    const download = event.target.closest("[data-expense-download]");
    if (download) {
      try {
        const url = `${backend.base.replace(/\/$/, "")}/expenses/items/${download.dataset.expenseDownload}/receipt/${download.dataset.receiptId}/`;
        const response = await fetch(url, { headers: backend.token ? { Authorization: `Token ${backend.token}` } : {} });
        if (!response.ok) throw new Error("No se pudo descargar el comprobante.");
        const objectUrl = URL.createObjectURL(await response.blob()), link = document.createElement("a"); link.href = objectUrl; link.download = "comprobante-gasto"; link.click(); URL.revokeObjectURL(objectUrl);
      } catch (error) { toast(error.message); }
    }
  });
  const closeExpenseReimbursement = () => $("#expense-reimbursement-modal").classList.remove("open");
  $("#close-expense-reimbursement").addEventListener("click", closeExpenseReimbursement);
  $("#cancel-expense-reimbursement").addEventListener("click", closeExpenseReimbursement);
  $("#expense-reimbursement-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const reportId = $("#expense-reimbursement-report").value;
    const body = { idempotency_key: $("#expense-reimbursement-idempotency").value, amount: $("#expense-reimbursement-amount").value, payment_date: $("#expense-reimbursement-date").value, method: $("#expense-reimbursement-method").value, reference: $("#expense-reimbursement-reference").value.trim(), confirm_payment_made: $("#expense-reimbursement-confirm").checked };
    try {
      await apiRequest(`expenses/reports/${reportId}/reimburse/`, { method: "POST", body });
      closeExpenseReimbursement(); await syncFromApi(); toast("Pago registrado y póliza borrador creada para Contabilidad.");
    } catch (error) { toast(`No se pudo registrar el reembolso: ${error.message}`); }
  });
  document.querySelectorAll("[data-new-quote]").forEach((button) => button.addEventListener("click", () => openQuote()));
  $("#new-opportunity").addEventListener("click", () => { const form = $("#opportunity-form"); form.reset(); delete form.dataset.edit; $("#opportunity-modal-title").textContent = "Nueva oportunidad"; $("#opportunity-probability").value = "10"; $("#opportunity-revenue").value = "0"; $("#opportunity-modal").classList.add("open"); setTimeout(() => $("#opportunity-name").focus(), 80); });
  $("#close-opportunity-modal").addEventListener("click", () => $("#opportunity-modal").classList.remove("open"));
  $("#cancel-opportunity").addEventListener("click", () => $("#opportunity-modal").classList.remove("open"));
  $("#opportunity-customer").addEventListener("change", () => { const client = db.clients.find((item) => item.id === $("#opportunity-customer").value); if (client) $("#opportunity-company").value = client.name; });
  $("#opportunity-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, id = form.dataset.edit;
    const body = { name: $("#opportunity-name").value.trim(), customer: $("#opportunity-customer").value || null, company_name: $("#opportunity-company").value.trim(), contact_name: $("#opportunity-contact").value.trim(), email: $("#opportunity-email").value.trim(), phone: $("#opportunity-phone").value.trim(), expected_revenue: $("#opportunity-revenue").value || "0", probability: Number($("#opportunity-probability").value), expected_close_date: $("#opportunity-close-date").value || null, source: $("#opportunity-source").value.trim(), assigned_to: $("#opportunity-owner").value || null, description: $("#opportunity-description").value.trim() };
    try { await apiRequest(id ? `opportunities/${id}/` : "opportunities/", { method: id ? "PATCH" : "POST", body }); await syncFromApi(); $("#opportunity-modal").classList.remove("open"); go("oportunidades"); toast(id ? "Oportunidad actualizada." : "Oportunidad guardada en el ERP."); } catch (error) { toast(error.message); }
  });
  $("#close-opportunity-convert").addEventListener("click", () => $("#opportunity-convert-modal").classList.remove("open"));
  $("#cancel-opportunity-convert").addEventListener("click", () => $("#opportunity-convert-modal").classList.remove("open"));
  $("#convert-customer-mode").addEventListener("change", () => {
    const isNew = $("#convert-customer-mode").value === "new";
    $("#convert-existing-fields").hidden = isNew; $("#convert-new-fields").hidden = !isNew;
    $("#convert-existing-customer").required = !isNew; $("#convert-name").required = isNew;
  });
  $("#opportunity-convert-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, mode = $("#convert-customer-mode").value;
    const body = mode === "existing" ? { customer_id: $("#convert-existing-customer").value } : { new_customer: { name: $("#convert-name").value.trim(), legal_name: $("#convert-legal-name").value.trim(), rfc: $("#convert-rfc").value.trim().toUpperCase(), email: $("#convert-email").value.trim(), phone: $("#convert-phone").value.trim(), fiscal_regime: $("#convert-regime").value.trim(), fiscal_postal_code: $("#convert-zip").value.trim() } };
    try {
      const result = await apiRequest(`opportunities/${form.dataset.opportunity}/convert/`, { method: "POST", body });
      await syncFromApi(); $("#opportunity-convert-modal").classList.remove("open");
      toast(result.created ? "Cliente creado y vinculado a la oportunidad." : "Cliente vinculado a la oportunidad.");
    } catch (error) { toast(error.message); }
  });
  const closeOpportunityActivities = () => $("#opportunity-activities-modal").classList.remove("open");
  $("#close-opportunity-activities").addEventListener("click", closeOpportunityActivities);
  $("#done-opportunity-activities").addEventListener("click", closeOpportunityActivities);
  $("#opportunity-activity-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const dueAt = $("#activity-due-at").value;
    if (!dueAt) { toast("Indica la fecha y hora del seguimiento."); return; }
    const body = { opportunity: $("#activity-opportunity-id").value, activity_type: $("#activity-type").value, title: $("#activity-title").value.trim(), due_at: new Date(dueAt).toISOString(), assigned_to: $("#activity-assignee").value || null, note: $("#activity-note").value.trim() };
    try { await apiRequest("opportunity-activities/", { method: "POST", body }); await syncFromApi(); renderOpportunityActivities(body.opportunity); $("#opportunity-activity-form").reset(); toast("Seguimiento programado."); } catch (error) { toast(error.message); }
  });
  $("#opportunity-search").addEventListener("input", renderOpportunities); $("#opportunity-filter").addEventListener("change", renderOpportunities);
  $("#load-opportunity-report").addEventListener("click", loadOpportunityReport);
  $("#new-support-ticket").addEventListener("click", openSupportTicketForm);
  $("#support-customer").addEventListener("change", () => { updateSupportWorkOrderOptions(); updateSupportAssets(); });
  $("#support-search").addEventListener("input", renderSupportTickets);
  $("#support-status-filter").addEventListener("change", renderSupportTickets);
  $("#close-support-ticket").addEventListener("click", () => $("#support-ticket-modal").classList.remove("open"));
  $("#cancel-support-ticket").addEventListener("click", () => $("#support-ticket-modal").classList.remove("open"));
  $("#close-support-detail").addEventListener("click", () => $("#support-ticket-detail").classList.remove("open"));
  $("#done-support-detail").addEventListener("click", () => $("#support-ticket-detail").classList.remove("open"));
  $("#support-ticket-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { customer: $("#support-customer").value, work_order: $("#support-work-order").value || null, serial_unit: $("#support-serial-unit").value || null, title: $("#support-title").value.trim(), description: $("#support-description").value.trim(), priority: $("#support-priority").value, channel: $("#support-channel").value };
    if (can("support.assign_supportticket")) body.assigned_to = $("#support-assignee").value || null;
    try { const ticket = await apiRequest("support/tickets/", { method: "POST", body }); await syncFromApi(); $("#support-ticket-modal").classList.remove("open"); toast(`${ticket.number} registrado en soporte.`); }
    catch (error) { toast(error.message); }
  });
  $("#support-create-repair-case").addEventListener("click", async () => {
    const ticket = live.supportTickets.find((item) => item.id === $("#support-ticket-detail").dataset.ticketId);
    if (!ticket || !ticket.serial_unit || !can("repairs.add_repaircase")) return;
    if (!window.confirm("Se abrirá un expediente de reparación ligado a este ticket y equipo instalado. No se modificarán existencias ni se generarán cargos. ¿Continuar?")) return;
    try { await apiRequest("repairs/cases/", { method: "POST", body: { ticket: ticket.id } }); await syncFromApi(); openSupportTicketDetail(ticket.id); toast("Expediente de reparación abierto."); }
    catch (error) { toast(error.message); }
  });
  $("#repair-case-update-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const ticketId = $("#support-ticket-detail").dataset.ticketId;
    const ticket = live.supportTickets.find((item) => item.id === ticketId);
    const repairCase = ticket && live.repairCases.find((item) => item.ticket_number === ticket.number);
    if (!repairCase || !can("repairs.change_repaircase")) return;
    const body = { diagnosis: $("#repair-diagnosis").value.trim(), proposed_work: $("#repair-proposed-work").value.trim(), warranty_review: $("#repair-warranty-review").value };
    try { await apiRequest(`repairs/cases/${repairCase.id}/`, { method: "PATCH", body }); await syncFromApi(); openSupportTicketDetail(ticketId); toast("Diagnóstico y revisión guardados."); }
    catch (error) { toast(error.message); }
  });
  $("#repair-case-transitions").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-repair-transition]");
    if (!button || !can("repairs.transition_repaircase")) return;
    const target = button.dataset.targetStatus;
    let authorization_record = "";
    let note = "";
    if (target === "authorized") {
      authorization_record = window.prompt("Registra la evidencia de autorización del cliente (correo, folio o nota; mínimo 10 caracteres):", "") || "";
      if (!authorization_record.trim()) return;
    } else if (["closed", "unrepairable", "cancelled"].includes(target)) {
      note = window.prompt("Deja una nota para la bitácora (mínimo 10 caracteres):", "") || "";
      if (!note.trim()) return;
    }
    const ticketId = $("#support-ticket-detail").dataset.ticketId;
    try { await apiRequest(`repairs/cases/${button.dataset.repairTransition}/transition/`, { method: "POST", body: { status: target, authorization_record, note } }); await syncFromApi(); openSupportTicketDetail(ticketId); toast("Etapa de reparación actualizada."); }
    catch (error) { toast(error.message); }
  });
  $("#repair-case-custody").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-repair-custody]");
    if (!button || !can("repairs.transition_repaircase")) return;
    const action = button.dataset.custodyAction;
    const promptText = action === "receive"
      ? "Describe la condición física del equipo y los accesorios recibidos (mínimo 10 caracteres):"
      : "Describe la condición física y los accesorios que se devuelven al cliente (mínimo 10 caracteres):";
    const condition = window.prompt(promptText, "") || "";
    if (condition.trim().length < 10) return;
    if (!window.confirm(action === "receive" ? "Se registrará que Redmagna recibe físicamente el equipo. Esto no cambia el inventario. ¿Continuar?" : "Se registrará la devolución física del equipo al cliente. ¿Continuar?")) return;
    const ticketId = $("#support-ticket-detail").dataset.ticketId;
    try { await apiRequest(`repairs/cases/${button.dataset.repairCustody}/custody/`, { method: "POST", body: { action, condition } }); await syncFromApi(); openSupportTicketDetail(ticketId); toast(action === "receive" ? "Recepción física registrada." : "Devolución física registrada."); }
    catch (error) { toast(error.message); }
  });
  $("#support-ticket-note-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const ticketId = $("#support-ticket-detail").dataset.ticketId, body = $("#support-ticket-note").value.trim();
    if (!body) { toast("Escribe una nota antes de guardarla."); return; }
    const isPublic = can("support.publish_supportticketmessage") && $("#support-ticket-public").checked;
    if (isPublic && !window.confirm("Esta respuesta quedará visible para el cliente en su enlace de seguimiento. ¿Compartirla?")) return;
    try { await apiRequest(`support/tickets/${ticketId}/add-note/`, { method: "POST", body: { body, is_public: isPublic } }); await syncFromApi(); openSupportTicketDetail(ticketId); toast(isPublic ? "Respuesta compartida con el cliente." : "Nota interna guardada."); }
    catch (error) { toast(error.message); }
  });
  $("#support-send-portal-link").addEventListener("click", async () => {
    const ticketId = $("#support-ticket-detail").dataset.ticketId;
    if (!ticketId || !window.confirm("Se enviará un enlace privado de seguimiento al correo registrado del cliente. El enlace vence en 30 días. ¿Continuar?")) return;
    try { const result = await apiRequest(`support/tickets/${ticketId}/send-portal-link/`, { method: "POST", body: {} }); await syncFromApi(); openSupportTicketDetail(ticketId); toast(`Enlace enviado a ${result.recipient_email}.`); }
    catch (error) { toast(error.message); }
  });
  $("#q-client").addEventListener("change", async () => { updateQuoteOpportunityOptions(); await updateQuoteContactOptions(); updateQuoteSiteOptions(); $("#q-payment-term-days").value = clientOf($("#q-client").value).paymentTermDays ?? ""; });
  $("#q-template").addEventListener("change", () => { const template = live.quoteTemplates.find((item) => item.id === $("#q-template").value); if (template) applyQuoteTemplate(template); });
  $("#save-quote-template").addEventListener("click", saveQuoteTemplate);
  $("#menu-toggle").addEventListener("click", () => $("#sidebar").classList.toggle("open"));
  $("#close-modal").addEventListener("click", () => $("#quote-modal").classList.remove("open"));
  $("#cancel-modal").addEventListener("click", () => $("#quote-modal").classList.remove("open"));
  $("#add-line").addEventListener("click", () => newLine());
  $("#all-quote-search").addEventListener("input", render); $("#quote-filter").addEventListener("change", render); $("#quote-search").addEventListener("input", () => { $("#all-quote-search").value = $("#quote-search").value; render(); go("cotizaciones"); });

  $("#quote-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, editId = form.dataset.edit;
    const lines = [...document.querySelectorAll("#line-items .line-item")].map((row) => ({ name: row.querySelector(".line-name").value.trim(), kind: row.querySelector(".line-kind").value, qty: Number(row.querySelector(".line-qty").value) || 1, price: Number(row.querySelector(".line-price").value) || 0, discountPercent: Number(row.querySelector(".line-discount").value) || 0, taxRate: Number(row.querySelector(".line-tax").value) || 0, isOptional: row.querySelector(".line-optional").checked, catalogProduct: row.querySelector(".line-product").value || null })).filter((line) => line.name);
    if (!lines.length) { toast("Agrega al menos un concepto."); return; }
    try {
      if (backend.connected) {
        const kindMap = { Equipo: "equipment", Material: "material", Instalación: "installation", Servicio: "service" };
        const termDays = $("#q-payment-term-days").value;
        const body = { customer: $("#q-client").value, customer_contact: $("#q-customer-contact").value || null, opportunity: $("#q-opportunity").value || null, customer_site: $("#q-service-site").value || null, title: $("#q-title").value.trim(), issue_date: $("#q-date").value, valid_until: $("#q-expiry").value || null, payment_term_days: termDays === "" ? null : Number(termDays), notes: $("#q-notes").value.trim(), lines: lines.map((line) => ({ kind: kindMap[line.kind], catalog_product: line.catalogProduct, description: line.name, quantity: line.qty, unit_price: line.price, tax_rate: line.taxRate, discount_percent: line.discountPercent, is_optional: line.isOptional })) };
        if (!editId && $("#q-template").value) body.template = $("#q-template").value;
        await apiRequest(editId ? `quotes/${editId}/` : "quotes/", { method: editId ? "PATCH" : "POST", body });
        await syncFromApi(); toast(editId ? "Cotización actualizada." : "Cotización guardada en el ERP.");
      } else {
        const count = db.quotes.length + 1, quote = { id: `RM-${new Date().getFullYear()}-${String(count).padStart(3, "0")}`, clientId: $("#q-client").value, paymentTermDays: $("#q-payment-term-days").value === "" ? null : Number($("#q-payment-term-days").value), title: $("#q-title").value.trim(), date: $("#q-date").value, expiry: $("#q-expiry").value, status: "Borrador", tax: Number($("#q-tax").value) || 0, notes: $("#q-notes").value.trim(), lines };
        db.quotes.unshift(quote); db.activities.unshift({ text: `Cotización ${quote.id} creada para ${clientOf(quote.clientId).name}`, time: `Hoy · ${new Date().toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" })}`, icon: "＋" }); save(); render(); toast(`Cotización ${quote.id} guardada en esta demostración.`);
      }
      delete form.dataset.edit;
      $("#quote-modal").classList.remove("open"); go("cotizaciones");
    } catch (error) { toast(error.message); }
  });

  $("#cost-sheet-add").addEventListener("click", () => { appendCostSheetItem(); updateCostSheetPreview(); });
  $("#cost-sheet-download").addEventListener("click", downloadCostSheetCSV);
  $("#cost-sheet-form").addEventListener("input", updateCostSheetPreview);
  $("#cost-sheet-form").addEventListener("change", updateCostSheetPreview);
  $("#close-cost-sheet").addEventListener("click", () => $("#cost-sheet-modal").classList.remove("open"));
  $("#cancel-cost-sheet").addEventListener("click", () => $("#cost-sheet-modal").classList.remove("open"));
  $("#cost-sheet-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, quoteId = form.dataset.quoteId;
    const items = [...$("#cost-sheet-lines").querySelectorAll(".cost-sheet-line")].map((row, index) => ({
      category: row.querySelector("[data-cost-category]").value,
      description: row.querySelector("[data-cost-description]").value.trim(),
      quantity: row.querySelector("[data-cost-quantity]").value,
      unit_cost: row.querySelector("[data-cost-unit-cost]").value,
      is_optional: row.querySelector("[data-cost-optional]").checked,
      sort_order: index,
    })).filter((item) => item.description);
    if ([...$("#cost-sheet-lines").querySelectorAll("[data-cost-description]")].some((input) => !input.value.trim() && input.closest(".cost-sheet-line").querySelector("[data-cost-unit-cost]").value)) {
      toast("Completa la descripción de cada costo con importe o quita la fila vacía."); return;
    }
    if (items.some((item) => !item.quantity || item.unit_cost === "")) { toast("Completa la cantidad y el costo unitario de cada renglón."); return; }
    const margin = $("#cost-sheet-margin").value;
    const body = { target_margin_percent: margin === "" ? null : margin, items };
    try {
      const sheet = await apiRequest(`quotes/${quoteId}/cost-sheet/`, { method: "PUT", body });
      sheet.quote_id = quoteId; renderCostSheet(sheet); toast("Hoja de costos guardada. La cotización al cliente no cambió.");
    } catch (error) { toast(error.message); }
  });

  $("#new-client").addEventListener("click", () => { $("#client-form").reset(); delete $("#client-form").dataset.edit; $("#client-modal-title").textContent = "Nuevo cliente"; $("#client-modal").classList.add("open"); });
  $("#import-clients").addEventListener("click", () => $("#client-import-file").click());
  const closeClientImport = () => {
    $("#client-import-modal").classList.remove("open");
    $("#client-import-file").value = "";
    $("#client-import-rows").innerHTML = `<tr><td colspan="4" class="empty">Sin vista previa.</td></tr>`;
    $("#client-import-summary").textContent = "Selecciona un archivo CSV para revisar las filas.";
    $("#commit-client-import").disabled = true;
    customerImportFile = null;
  };
  $("#close-client-import").addEventListener("click", closeClientImport);
  $("#cancel-client-import").addEventListener("click", closeClientImport);
  $("#client-import-file").addEventListener("change", async (event) => {
    customerImportFile = event.currentTarget.files?.[0] || null;
    if (!customerImportFile) return;
    const body = new FormData(); body.append("file", customerImportFile);
    $("#client-import-modal").classList.add("open");
    $("#client-import-summary").textContent = "Revisando archivo…";
    $("#commit-client-import").disabled = true;
    try {
      const preview = await apiRequest("customers/import-csv/", { method: "POST", body });
      const ready = preview.rows.filter((row) => row.status === "create").length;
      $("#client-import-rows").innerHTML = preview.rows.map((row) => `<tr><td>${escapeHtml(row.row)}</td><td>${escapeHtml(row.name || "—")}</td><td>${row.status === "create" ? "Listo" : row.status === "duplicate" ? "Omitido · posible duplicado" : "Error"}</td><td>${escapeHtml(row.detail)}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">El archivo no contiene filas para importar.</td></tr>`;
      $("#client-import-summary").textContent = `${ready} listas para crear · ${preview.skipped} posibles duplicados omitidos · ${preview.errors} con errores. La vista previa no guarda datos.`;
      $("#commit-client-import").disabled = ready === 0;
    } catch (error) { $("#client-import-summary").textContent = error.message; }
  });
  $("#commit-client-import").addEventListener("click", async () => {
    if (!customerImportFile || !window.confirm("Se crearán únicamente las filas marcadas como listas. Los clientes existentes no se modificarán. ¿Continuar?")) return;
    const body = new FormData(); body.append("file", customerImportFile); body.append("commit", "true");
    $("#commit-client-import").disabled = true;
    try {
      const result = await apiRequest("customers/import-csv/", { method: "POST", body });
      await syncFromApi();
      $("#client-import-summary").textContent = `Importación terminada: ${result.created} creados · ${result.skipped} duplicados omitidos · ${result.errors} filas con errores.`;
      toast(`${result.created} clientes importados.`);
    } catch (error) { $("#client-import-summary").textContent = error.message; $("#commit-client-import").disabled = false; }
  });
  $("#close-client-modal").addEventListener("click", () => $("#client-modal").classList.remove("open"));
  $("#customer-contacts-close").addEventListener("click", () => $("#customer-contacts-modal").classList.remove("open"));
  $("#customer-contacts-close-bottom").addEventListener("click", () => $("#customer-contacts-modal").classList.remove("open"));
  $("#customer-contact-add").addEventListener("click", () => {
    const form = $("#customer-contact-form"); form.reset(); delete form.dataset.edit; form.hidden = false; $("#customer-contact-name").focus();
  });
  $("#customer-contact-cancel").addEventListener("click", () => { const form = $("#customer-contact-form"); form.hidden = true; delete form.dataset.edit; form.reset(); });
  $("#customer-contact-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, contactId = form.dataset.edit;
    const body = { name: $("#customer-contact-name").value.trim(), role: $("#customer-contact-role").value.trim(), email: $("#customer-contact-email").value.trim(), phone: $("#customer-contact-phone").value.trim(), is_primary: $("#customer-contact-primary").checked, is_active: true };
    if (!contactId) body.customer = $("#customer-contacts-modal").dataset.customerId;
    try {
      await apiRequest(contactId ? `customer-contacts/${contactId}/?active=all` : "customer-contacts/", { method: contactId ? "PATCH" : "POST", body });
      form.hidden = true; delete form.dataset.edit; form.reset(); await openCustomerContacts($("#customer-contacts-modal").dataset.customerId); toast(contactId ? "Contacto actualizado." : "Contacto agregado.");
    } catch (error) { toast(error.message); }
  });
  $("#client-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.currentTarget, id = form.dataset.edit;
    const termDays = $("#c-payment-term-days").value;
    const client = { name: $("#c-name").value.trim(), legal_name: $("#c-legal-name").value.trim(), rfc: $("#c-rfc").value.trim(), email: $("#c-email").value.trim(), phone: $("#c-phone").value.trim(), fiscal_regime: $("#c-regime").value.trim(), fiscal_postal_code: $("#c-zip").value.trim(), payment_term_days: termDays === "" ? null : Number(termDays), is_active: true };
    try {
      if (backend.connected) { await apiRequest(id ? `customers/${id}/` : "customers/", { method: id ? "PATCH" : "POST", body: client }); await syncFromApi(); }
      else { const item = { id: id || `c${Date.now()}`, name: client.name, legalName: client.legal_name, rfc: client.rfc, email: client.email, phone: client.phone, regime: client.fiscal_regime, zip: client.fiscal_postal_code, paymentTermDays: client.payment_term_days }; const index = db.clients.findIndex((entry) => entry.id === id); if (index >= 0) db.clients[index] = item; else db.clients.unshift(item); save(); render(); }
      $("#client-modal").classList.remove("open"); toast(id ? "Cliente actualizado." : "Cliente guardado.");
    } catch (error) { toast(error.message); }
  });

  document.addEventListener("click", async (event) => {
    const revokeSession = event.target.closest("[data-session-revoke]");
    if (revokeSession) {
      if (!window.confirm("¿Revocar esta sesión? El navegador seleccionado tendrá que volver a conectarse.")) return;
      revokeSession.disabled = true;
      try { await apiRequest(`auth/sessions/${revokeSession.dataset.sessionRevoke}/revoke/`, { method: "POST", body: {} }); await openApiSessions(); toast("Sesión revocada."); }
      catch (error) { revokeSession.disabled = false; toast(error.message); }
      return;
    }
    const ticketDetail = event.target.closest("[data-ticket-detail]");
    if (ticketDetail) { openSupportTicketDetail(ticketDetail.dataset.ticketDetail); return; }
    const ticketTransition = event.target.closest("[data-ticket-transition]");
    if (ticketTransition) {
      try { await apiRequest(`support/tickets/${ticketTransition.dataset.ticketTransition}/transition/`, { method: "POST", body: { status: ticketTransition.dataset.targetStatus } }); await syncFromApi(); toast("Estado del ticket actualizado."); }
      catch (error) { toast(error.message); }
      return;
    }
    const accountToggle = event.target.closest("[data-account-toggle]");
    if (accountToggle) {
      if (!can("accounting.change_account")) return;
      try { await apiRequest(`accounting/accounts/${accountToggle.dataset.accountToggle}/`, { method: "PATCH", body: { is_active: accountToggle.dataset.active !== "true" } }); await syncFromApi(); toast("Estado de la cuenta actualizado."); }
      catch (error) { toast(error.message); }
      return;
    }
    const journalToggle = event.target.closest("[data-journal-toggle]");
    if (journalToggle) {
      if (!can("accounting.change_journal")) return;
      try { await apiRequest(`accounting/journals/${journalToggle.dataset.journalToggle}/`, { method: "PATCH", body: { is_active: journalToggle.dataset.active !== "true" } }); await syncFromApi(); toast("Estado del diario actualizado."); }
      catch (error) { toast(error.message); }
      return;
    }
    const savePosting = event.target.closest("[data-posting-save]");
    if (savePosting) { await savePostingConfiguration(savePosting); return; }
    const viewLink = event.target.closest("[data-view-link]");
    if (viewLink) { go(viewLink.dataset.viewLink); return; }
    const editQuoteButton = event.target.closest("[data-quote-edit]");
    if (editQuoteButton) {
      const quote = db.quotes.find((item) => (item.backendId || item.id) === editQuoteButton.dataset.quoteEdit);
      if (quote) await openQuoteForEdit(quote);
      return;
    }
    const costSheetButton = event.target.closest("[data-quote-cost-sheet]");
    if (costSheetButton) { await openQuoteCostSheet(costSheetButton.dataset.quoteCostSheet); return; }
    const removeCostItem = event.target.closest("[data-cost-remove]");
    if (removeCostItem) { removeCostItem.closest(".cost-sheet-line")?.remove(); updateCostSheetPreview(); return; }
    const reviseQuote = event.target.closest("[data-quote-revise]");
    if (reviseQuote) {
      try {
        const revision = await apiRequest(`quotes/${reviseQuote.dataset.quoteRevise}/revise/`, { method: "POST", body: {} });
        await syncFromApi();
        go("cotizaciones");
        const editableRevision = db.quotes.find((item) => item.backendId === revision.id);
        if (editableRevision && revision.status === "draft") {
          await openQuoteForEdit(editableRevision);
          toast(`Se creó ${revision.number}${revision.revision_number ? ` · revisión ${revision.revision_number}` : ""} como borrador listo para editar.`);
        } else {
          toast(`La revisión vigente es ${revision.number}${revision.revision_number ? ` · revisión ${revision.revision_number}` : ""} y ya no está en borrador.`);
        }
      } catch (error) { toast(error.message); }
      return;
    }
    const emailQuote = event.target.closest("[data-quote-email]");
    if (emailQuote) {
      const recipient = emailQuote.dataset.quoteEmailTo;
      if (!window.confirm(`Enviar la cotización con enlace de aceptación a ${recipient}?`)) return;
      emailQuote.disabled = true;
      try { await apiRequest(`quotes/${emailQuote.dataset.quoteEmail}/send-email/`, { method: "POST", body: {} }); toast(`Propuesta enviada a ${recipient}.`); }
      catch (error) { toast(error.message); emailQuote.disabled = false; }
      return;
    }
    const qualifyOpportunity = event.target.closest("[data-opportunity-qualify]");
    if (qualifyOpportunity) {
      try { await apiRequest(`opportunities/${qualifyOpportunity.dataset.opportunityQualify}/qualify/`, { method: "POST", body: {} }); await syncFromApi(); toast("Oportunidad calificada."); } catch (error) { toast(error.message); }
      return;
    }
    const convertOpportunity = event.target.closest("[data-opportunity-convert]");
    if (convertOpportunity) { openOpportunityConversion(convertOpportunity.dataset.opportunityConvert); return; }
    const editOpportunity = event.target.closest("[data-opportunity-edit]");
    if (editOpportunity) {
      const item = db.opportunities.find((opportunity) => opportunity.id === editOpportunity.dataset.opportunityEdit);
      if (!item) return;
      const form = $("#opportunity-form"); form.reset(); form.dataset.edit = item.id;
      $("#opportunity-modal-title").textContent = "Editar oportunidad";
      $("#opportunity-name").value = item.name || ""; $("#opportunity-customer").value = item.customer || ""; $("#opportunity-company").value = item.company_name || ""; $("#opportunity-contact").value = item.contact_name || ""; $("#opportunity-email").value = item.email || ""; $("#opportunity-phone").value = item.phone || ""; $("#opportunity-revenue").value = item.expected_revenue || "0"; $("#opportunity-probability").value = item.probability ?? "10"; $("#opportunity-close-date").value = item.expected_close_date || ""; $("#opportunity-source").value = item.source || ""; $("#opportunity-owner").value = item.assigned_to || ""; $("#opportunity-description").value = item.description || "";
      $("#opportunity-modal").classList.add("open"); return;
    }
    const loseOpportunity = event.target.closest("[data-opportunity-lost]");
    if (loseOpportunity) {
      const reason = window.prompt("¿Por qué se perdió esta oportunidad?");
      if (reason === null) return;
      const note = window.prompt("Nota de cierre (opcional):") || "";
      try { await apiRequest(`opportunities/${loseOpportunity.dataset.opportunityLost}/mark-lost/`, { method: "POST", body: { reason: reason.trim(), note: note.trim() } }); await syncFromApi(); toast("Oportunidad cerrada como perdida."); } catch (error) { toast(error.message); }
      return;
    }
    const reopenOpportunity = event.target.closest("[data-opportunity-reopen]");
    if (reopenOpportunity) {
      try { await apiRequest(`opportunities/${reopenOpportunity.dataset.opportunityReopen}/reopen/`, { method: "POST", body: {} }); await syncFromApi(); toast("Oportunidad reabierta."); } catch (error) { toast(error.message); }
      return;
    }
    const quoteOpportunity = event.target.closest("[data-opportunity-quote]");
    if (quoteOpportunity) { openQuote(quoteOpportunity.dataset.opportunityQuote); return; }
    const opportunityActivities = event.target.closest("[data-opportunity-activities]");
    if (opportunityActivities) { openOpportunityActivities(opportunityActivities.dataset.opportunityActivities); return; }
    const reminderOpportunity = event.target.closest("[data-reminder-opportunity]");
    if (reminderOpportunity) { openOpportunityActivities(reminderOpportunity.dataset.reminderOpportunity); return; }
    const completeActivity = event.target.closest("[data-activity-complete]");
    if (completeActivity) {
      try { await apiRequest(`opportunity-activities/${completeActivity.dataset.activityComplete}/complete/`, { method: "POST", body: {} }); await syncFromApi(); renderOpportunityActivities($("#activity-opportunity-id").value); toast("Seguimiento marcado como completado."); } catch (error) { toast(error.message); }
      return;
    }
    const cancelActivity = event.target.closest("[data-activity-cancel]");
    if (cancelActivity) {
      try { await apiRequest(`opportunity-activities/${cancelActivity.dataset.activityCancel}/cancel/`, { method: "POST", body: {} }); await syncFromApi(); renderOpportunityActivities($("#activity-opportunity-id").value); toast("Seguimiento cancelado."); } catch (error) { toast(error.message); }
      return;
    }
    const printButton = event.target.closest("[data-quote-print]");
    if (printButton) {
      const quote = db.quotes.find((item) => (item.backendId || item.id) === printButton.dataset.quotePrint);
      if (quote) printQuote(quote);
      return;
    }
    const action = event.target.closest("[data-quote-action]");
    if (action) {
      const quote = db.quotes.find((item) => (item.backendId || item.id) === action.dataset.quoteAction);
      if (!quote) return;
      if (backend.connected) {
        const operation = quote.apiStatus === "draft" && can("sales.send_quote") ? "send" : quote.apiStatus === "sent" && can("sales.approve_quote") ? "approve" : "";
        if (!operation) { toast("La cotización no tiene una acción disponible aquí."); return; }
        try { await apiRequest(`quotes/${quote.backendId}/${operation}/`, { method: "POST" }); await syncFromApi(); toast(operation === "send" ? "Cotización marcada como enviada." : "Cotización aprobada; se creó una orden de trabajo."); }
        catch (error) { toast(error.message); }
      } else localQuoteAction(quote);
      return;
    }
    const discountApproval = event.target.closest("[data-quote-discount-approve]");
    if (discountApproval) {
      try {
        const result = await apiRequest(`quotes/${discountApproval.dataset.quoteDiscountApprove}/approve-discount/`, { method: "POST" });
        await syncFromApi();
        toast(result.discount_approval_created ? "Descuento autorizado por Gerencia; la aceptación del cliente sigue pendiente." : "La autorización vigente ya estaba registrada.");
      } catch (error) { toast(error.message); }
      return;
    }
    const contactManager = event.target.closest("[data-client-contacts]");
    if (contactManager) { await openCustomerContacts(contactManager.dataset.clientContacts); return; }
    const contactEdit = event.target.closest("[data-contact-edit]");
    if (contactEdit) {
      const modal = $("#customer-contacts-modal"), contact = (modal.contacts || []).find((item) => item.id === contactEdit.dataset.contactEdit);
      if (!contact) return;
      const form = $("#customer-contact-form"); form.reset(); form.dataset.edit = contact.id; form.hidden = false;
      $("#customer-contact-name").value = contact.name; $("#customer-contact-role").value = contact.role || ""; $("#customer-contact-email").value = contact.email || ""; $("#customer-contact-phone").value = contact.phone || ""; $("#customer-contact-primary").checked = Boolean(contact.is_primary); $("#customer-contact-name").focus(); return;
    }
    const contactActive = event.target.closest("[data-contact-active]");
    if (contactActive) {
      const active = contactActive.dataset.active === "true";
      if (!active && !window.confirm("¿Archivar este contacto? Se conservará en el historial del cliente.")) return;
      try { await apiRequest(`customer-contacts/${contactActive.dataset.contactActive}/?active=all`, { method: "PATCH", body: { is_active: active } }); await openCustomerContacts($("#customer-contacts-modal").dataset.customerId); toast(active ? "Contacto reactivado." : "Contacto archivado."); }
      catch (error) { toast(error.message); }
      return;
    }
    const edit = event.target.closest("[data-client-edit]");
    if (edit) {
      const client = db.clients.find((item) => item.id === edit.dataset.clientEdit);
      if (!client) return;
      $("#c-name").value = client.name; $("#c-legal-name").value = client.legalName || ""; $("#c-rfc").value = client.rfc || ""; $("#c-email").value = client.email || ""; $("#c-phone").value = client.phone || ""; $("#c-regime").value = client.regime || ""; $("#c-zip").value = client.zip || ""; $("#c-payment-term-days").value = client.paymentTermDays ?? ""; $("#client-form").dataset.edit = client.id; $("#client-modal-title").textContent = "Editar cliente"; $("#client-modal").classList.add("open"); return;
    }
    const workStatus = event.target.closest("[data-work-status]");
    if (workStatus) {
      const work = live.workOrders.find((item) => item.id === workStatus.dataset.workStatus);
      if (workStatus.dataset.target === "done" && !work?.completion_notes?.trim()) {
        openWorkOrderEditor(workStatus.dataset.workStatus);
        toast("Agrega una nota de cierre antes de terminar el trabajo.");
        return;
      }
      if (workStatus.dataset.target === "done" && (!work?.checklist_items?.length || work.checklist_items.some((item) => !item.is_completed))) {
        openWorkOrderEditor(workStatus.dataset.workStatus);
        toast("Completa la lista de verificación antes de terminar el trabajo.");
        return;
      }
      try { await apiRequest(`work-orders/${workStatus.dataset.workStatus}/transition/`, { method: "POST", body: { status: workStatus.dataset.target } }); await syncFromApi(); toast("Orden de trabajo actualizada."); } catch (error) { toast(error.message); }
      return;
    }
    const workEdit = event.target.closest("[data-work-edit]");
    if (workEdit) { openWorkOrderEditor(workEdit.dataset.workEdit); return; }
    const workEvidence = event.target.closest("[data-work-evidence]");
    if (workEvidence) { await openWorkOrderEvidence(workEvidence.dataset.workEvidence); return; }
    const evidenceDownload = event.target.closest("[data-evidence-download]");
    if (evidenceDownload) {
      try {
        const url = `${backend.base.replace(/\/$/, "")}/${evidenceDownload.dataset.evidenceDownload.replace(/^\/+/, "")}`;
        const response = await fetch(url, { headers: backend.token ? { Authorization: `Token ${backend.token}` } : {} });
        if (!response.ok) throw new Error(`No se pudo descargar la evidencia (${response.status}).`);
        const blobUrl = URL.createObjectURL(await response.blob());
        const anchor = document.createElement("a"); anchor.href = blobUrl; anchor.download = evidenceDownload.dataset.evidenceFilename; anchor.click();
        setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
      } catch (error) { toast(error.message); }
      return;
    }
    const workLog = event.target.closest("[data-work-log]");
    if (workLog) { openWorkLogEditor(workLog.dataset.workLog); return; }
    const reserveRequirement = event.target.closest("[data-stock-reserve-requirement]");
    if (reserveRequirement) { openStockMovement("reserve", reserveRequirement.dataset.stockReserveRequirement, reserveRequirement.dataset.reserveProduct, reserveRequirement.dataset.reserveQuantity); return; }
    const materialLocation = event.target.closest("[data-material-location]");
    if (materialLocation && can("inventory.change_reorderrule")) {
      const locations = live.inventory.locations.filter((item) => item.is_active);
      const choices = locations.map((item) => `${item.code} — ${item.name}`).join("\n");
      const code = window.prompt(`Código del almacén de surtido:\n${choices}`, materialLocation.dataset.locationCode);
      if (code === null) return;
      const location = locations.find((item) => item.code.toLowerCase() === code.trim().toLowerCase());
      if (!location) { toast("Escribe el código de una ubicación activa de la lista."); return; }
      try {
        await apiRequest(`work-orders/${materialLocation.dataset.materialLocation}/material-requirements/${materialLocation.dataset.requirement}/location/`, { method: "PATCH", body: { supply_location: location.id } });
        await syncFromApi(); toast(`Destino de surtido actualizado a ${location.name}.`);
      } catch (error) { toast(error.message); }
      return;
    }
    const stockWork = event.target.closest("[data-stock-work]");
    if (stockWork) { openStockMovement("issue", stockWork.dataset.stockWork); return; }
    const releaseReservation = event.target.closest("[data-reservation-release]");
    if (releaseReservation) {
      try { await apiRequest(`inventory/reservations/${releaseReservation.dataset.reservationRelease}/release/`, { method: "POST" }); await syncFromApi(); toast("Reserva liberada; la existencia vuelve a estar disponible para otras órdenes."); }
      catch (error) { toast(error.message); }
      return;
    }
    const startCount = event.target.closest("#inventory-count-start");
    if (startCount) {
      const products = [...$("#inventory-count-products").selectedOptions].map((option) => option.value);
      const reason = $("#inventory-count-reason").value.trim();
      if (!products.length || !reason) { toast("Selecciona productos y escribe el motivo del conteo."); return; }
      try { await apiRequest("inventory/counts/", { method: "POST", body: { location: $("#inventory-count-location").value, products, reason } }); $("#inventory-count-reason").value = ""; await syncFromApi(); toast("Conteo iniciado con las existencias actuales como referencia."); }
      catch (error) { toast(error.message); }
      return;
    }
    const recordCountLine = event.target.closest("[data-count-record]");
    if (recordCountLine) {
      const lineId = recordCountLine.dataset.countLine;
      const url = `inventory/counts/${recordCountLine.dataset.countRecord}/lines/${lineId}/record/`;
      if (recordCountLine.dataset.countSerial === "true") {
        const input = document.querySelector(`[data-count-serials="${CSS.escape(lineId)}"]`);
        const countedSerials = (input?.value || "").split(/[\n,;]+/).map((serial) => serial.trim()).filter(Boolean);
        if (new Set(countedSerials).size !== countedSerials.length) { toast("No repitas una serie en el conteo."); return; }
        try { await apiRequest(url, { method: "POST", body: { counted_serial_numbers: countedSerials } }); await syncFromApi(); toast("Series del conteo guardadas."); }
        catch (error) { toast(error.message); }
      } else {
        const input = document.querySelector(`[data-count-quantity="${CSS.escape(lineId)}"]`);
        const counted = input?.value.trim();
        if (counted === "" || !Number.isFinite(Number(counted)) || Number(counted) < 0) { toast("Captura una cantidad válida, incluido cero."); return; }
        try { await apiRequest(url, { method: "POST", body: { counted_quantity: counted } }); await syncFromApi(); toast("Cantidad del conteo guardada."); }
        catch (error) { toast(error.message); }
      }
      return;
    }
    const submitCount = event.target.closest("[data-count-submit]");
    if (submitCount) {
      try { await apiRequest(`inventory/counts/${submitCount.dataset.countSubmit}/submit/`, { method: "POST" }); await syncFromApi(); toast("Conteo enviado para revisión."); }
      catch (error) { toast(error.message); }
      return;
    }
    const applyCount = event.target.closest("[data-count-apply]");
    if (applyCount) {
      if (!window.confirm("¿Revisar y aplicar estos ajustes al inventario? El sistema verificará que las existencias no hayan cambiado desde el conteo.")) return;
      try { await apiRequest(`inventory/counts/${applyCount.dataset.countApply}/apply/`, { method: "POST" }); await syncFromApi(); toast("Conteo revisado; diferencias registradas como movimientos."); }
      catch (error) { toast(error.message); }
      return;
    }
    const stockReceive = event.target.closest("[data-stock-receive]");
    if (stockReceive) { openStockMovement("receipt"); return; }
    const stockAdjust = event.target.closest("[data-stock-adjust]");
    if (stockAdjust) { openStockMovement("adjustment_in"); return; }
    const locationToggle = event.target.closest("[data-location-toggle]");
    if (locationToggle) {
      if (!can("inventory.change_stocklocation")) return;
      try { await apiRequest(`inventory/locations/${locationToggle.dataset.locationToggle}/`, { method: "PATCH", body: { is_active: locationToggle.dataset.active !== "true" } }); await syncFromApi(); toast("Estado de la ubicación actualizado."); }
      catch (error) { toast(error.message); }
      return;
    }
    const purchaseConfirm = event.target.closest("[data-purchase-confirm]");
    if (purchaseConfirm) {
      try { await apiRequest(`purchasing/orders/${purchaseConfirm.dataset.purchaseConfirm}/confirm/`, { method: "POST" }); await syncFromApi(); toast("Orden de compra solicitada."); } catch (error) { toast(error.message); }
      return;
    }
    const purchaseCancel = event.target.closest("[data-purchase-cancel]");
    if (purchaseCancel) {
      if (!window.confirm("¿Cancelar esta orden de compra?")) return;
      try { await apiRequest(`purchasing/orders/${purchaseCancel.dataset.purchaseCancel}/cancel/`, { method: "POST" }); await syncFromApi(); toast("Orden de compra cancelada."); } catch (error) { toast(error.message); }
      return;
    }
    const purchaseReceive = event.target.closest("[data-purchase-receive]");
    if (purchaseReceive) { openPurchaseReceipt(purchaseReceive.dataset.purchaseReceive); return; }
    const purchaseBill = event.target.closest("[data-purchase-bill]");
    if (purchaseBill) { openSupplierBill(purchaseBill.dataset.purchaseBill); return; }
    const supplierPay = event.target.closest("[data-supplier-pay]");
    if (supplierPay) { openSupplierPayment(supplierPay.dataset.supplierPay); return; }
    const supplierCfdiUpload = event.target.closest("[data-supplier-bill-cfdi-upload]");
    if (supplierCfdiUpload) { supplierCfdiUpload.closest("td")?.querySelector("[data-supplier-bill-cfdi-file]")?.click(); return; }
    const supplierCfdiDownload = event.target.closest("[data-supplier-bill-cfdi-download]");
    if (supplierCfdiDownload) {
      try {
        const response = await fetch(`${backend.base.replace(/\/$/, "")}/purchasing/supplier-bills/${supplierCfdiDownload.dataset.supplierBillCfdiDownload}/cfdi-xml/`, { headers: backend.token ? { Authorization: `Token ${backend.token}` } : {} });
        if (!response.ok) throw new Error("No se pudo descargar el CFDI adjunto.");
        const anchor = document.createElement("a"), objectUrl = URL.createObjectURL(await response.blob());
        anchor.href = objectUrl; anchor.download = `factura-proveedor-${supplierCfdiDownload.dataset.supplierBillCfdiDownload}.xml`; anchor.click(); URL.revokeObjectURL(objectUrl);
      } catch (error) { toast(error.message); }
      return;
    }
    const postSupplierPayment = event.target.closest("[data-post-supplier-payment]");
    if (postSupplierPayment) {
      try { await apiRequest(`purchasing/supplier-payments/${postSupplierPayment.dataset.postSupplierPayment}/post/`, { method: "POST" }); await syncFromApi(); toast("Pago aplicado a la cuenta por pagar."); } catch (error) { toast(error.message); }
      return;
    }
    const reverseSupplierPayment = event.target.closest("[data-reverse-supplier-payment]");
    if (reverseSupplierPayment && can("purchasing.reverse_supplierpayment")) {
      if (!window.confirm("La reversa reabrirá el saldo de las facturas aplicadas y registrará una póliza inversa si existe una póliza contabilizada. ¿Continuar?")) return;
      const reason = window.prompt("Motivo de la reversa (mínimo 10 caracteres):");
      if (!reason || reason.trim().length < 10) { toast("Escribe un motivo de al menos 10 caracteres."); return; }
      try {
        await apiRequest(`purchasing/supplier-payments/${reverseSupplierPayment.dataset.reverseSupplierPayment}/reverse/`, { method: "POST", body: { reason: reason.trim(), confirm_irreversible: true } });
        await syncFromApi(); toast("Pago revertido; el saldo del proveedor fue reabierto.");
      } catch (error) { toast(error.message); }
      return;
    }
    const editSupplierPayment = event.target.closest("[data-edit-supplier-payment]");
    if (editSupplierPayment) {
      const payment = live.purchasing.supplierPayments.find((item) => item.id === editSupplierPayment.dataset.editSupplierPayment);
      const billId = payment?.applications?.[0]?.bill;
      if (billId) openSupplierPayment(billId, payment);
      return;
    }
    const purchaseEdit = event.target.closest("[data-purchase-edit]");
    if (purchaseEdit) { openPurchaseOrder(purchaseEdit.dataset.purchaseEdit); return; }
    const supplierEdit = event.target.closest("[data-supplier-edit]");
    if (supplierEdit) { openSupplier(supplierEdit.dataset.supplierEdit); return; }
    const supplierProductEdit = event.target.closest("[data-supplier-product-edit]");
    if (supplierProductEdit) { openSupplierProduct(supplierProductEdit.dataset.supplierProductEdit); return; }
    const supplierProductToggle = event.target.closest("[data-supplier-product-toggle]");
    if (supplierProductToggle && can("purchasing.change_supplierproduct")) {
      const active = supplierProductToggle.dataset.nextActive === "true";
      if (!window.confirm(active ? "¿Reactivar esta condición de compra?" : "¿Archivar esta condición de compra?")) return;
      const reason = window.prompt("Motivo del cambio (mínimo 10 caracteres):");
      if (reason === null) return;
      if (reason.trim().length < 10) { toast("El motivo debe tener al menos 10 caracteres."); return; }
      try {
        await apiRequest(`purchasing/supplier-products/${supplierProductToggle.dataset.supplierProductToggle}/`, { method: "PATCH", body: { is_active: active, history_reason: reason.trim() } });
        await syncFromApi();
        toast(active ? "Condición reactivada y registrada en el historial." : "Condición archivada y registrada en el historial.");
      } catch (error) { toast(error.message); }
      return;
    }
    const createInvoice = event.target.closest("[data-create-invoice]");
    if (createInvoice) { openWorkOrderInvoice(createInvoice.dataset.createInvoice); return; }
    const printInvoice = event.target.closest("[data-print-invoice]");
    if (printInvoice) { printInternalInvoice(printInvoice.dataset.printInvoice); return; }
    const openInvoice = event.target.closest("[data-invoice-open]");
    if (openInvoice) {
      try { await apiRequest(`billing/invoices/${openInvoice.dataset.invoiceOpen}/open/`, { method: "POST" }); await syncFromApi(); toast("Cuenta por cobrar abierta; se creó una póliza borrador si está configurada."); } catch (error) { toast(error.message); }
      return;
    }
    const saveInvoiceDueDate = event.target.closest("[data-invoice-due-save]");
    if (saveInvoiceDueDate) {
      const input = saveInvoiceDueDate.closest("tr")?.querySelector("[data-invoice-due-input]");
      if (!input?.value) { toast("Selecciona la fecha de vencimiento antes de guardar."); return; }
      try {
        await apiRequest(`billing/invoices/${saveInvoiceDueDate.dataset.invoiceDueSave}/`, { method: "PATCH", body: { due_date: input.value } });
        await syncFromApi(); toast("Fecha de vencimiento guardada.");
      } catch (error) { toast(error.message); }
      return;
    }
    const payInvoice = event.target.closest("[data-invoice-pay]");
    if (payInvoice) {
      const invoice = live.invoices.find((item) => item.id === payInvoice.dataset.invoicePay), amount = prompt(`Importe a aplicar (saldo: ${money(invoice?.balance_due)} MXN)`);
      if (amount === null || !(Number(amount) > 0) || !invoice) return;
      try {
        const payment = await apiRequest("billing/payments/", { method: "POST", body: { customer: invoice.customer, amount: Number(amount).toFixed(2), currency: "MXN", method: "transfer", reference: "", memo: `Aplicación a ${invoice.number}`, allocations: [{ invoice: invoice.id, amount: Number(amount).toFixed(2) }] } });
        await apiRequest(`billing/payments/${payment.id}/post/`, { method: "POST" }); await syncFromApi(); toast("Cobro aplicado; se creó una póliza borrador si está configurada.");
      } catch (error) { toast(error.message); }
      return;
    }
    const creditInvoice = event.target.closest("[data-invoice-credit]");
    if (creditInvoice) {
      const invoice = live.invoices.find((item) => item.id === creditInvoice.dataset.invoiceCredit);
      if (!invoice?.lines?.length) { toast("La factura no tiene conceptos disponibles para acreditar."); return; }
      const choices = invoice.lines.map((line, index) => `${index + 1}. ${line.description} · ${line.quantity} × ${money(line.unit_price)} · IVA ${line.tax_rate}%`).join("\n");
      const selectedNumber = Number(window.prompt(`Elige el renglón de la factura ${invoice.number}:\n${choices}`, "1"));
      const line = invoice.lines[selectedNumber - 1];
      if (!line) { toast("Selecciona un renglón válido."); return; }
      const quantity = Number(window.prompt(`Cantidad que se acreditará (máximo ${line.quantity}):`, String(line.quantity)));
      if (!(quantity > 0) || quantity > Number(line.quantity)) { toast("La cantidad debe ser mayor que cero y no exceder la facturada."); return; }
      const reason = window.prompt("Motivo de la nota de crédito:");
      if (!reason?.trim()) { toast("Escribe el motivo de la nota."); return; }
      try {
        const note = await apiRequest("billing/credit-notes/", { method: "POST", body: { invoice: invoice.id, issue_date: todayISO(), reason: reason.trim(), lines: [{ invoice_line: line.id, line_number: 1, quantity: quantity.toFixed(3) }] } });
        if (window.confirm(`Se preparó ${note.number} por ${money(note.total)} MXN. Aplicarla ahora al saldo de ${invoice.number}?\nEsta operación es interna y no timbra CFDI E.`)) {
          await apiRequest(`billing/credit-notes/${note.id}/post/`, { method: "POST" });
          await syncFromApi(); toast("Nota de crédito aplicada; se actualizó el saldo de la factura.");
        } else {
          await syncFromApi(); toast("La nota quedó guardada como borrador.");
        }
      } catch (error) { await syncFromApi(); toast(error.message); }
      return;
    }
    const postCreditNote = event.target.closest("[data-credit-note-post]");
    if (postCreditNote) {
      const note = live.creditNotes.find((item) => item.id === postCreditNote.dataset.creditNotePost);
      if (!note || !window.confirm(`Aplicar ${note.number} por ${money(note.total)} MXN? Esto reducirá el saldo de la factura ${note.invoice_number}; la nota no preparará automáticamente el CFDI E.`)) return;
      try {
        await apiRequest(`billing/credit-notes/${note.id}/post/`, { method: "POST" });
        await syncFromApi(); toast("Nota de crédito aplicada y saldo actualizado.");
      } catch (error) { toast(error.message); }
      return;
    }
    const reverseCreditNote = event.target.closest("[data-credit-note-reverse]");
    if (reverseCreditNote) {
      const note = live.creditNotes.find((item) => item.id === reverseCreditNote.dataset.creditNoteReverse);
      if (!note || !window.confirm(`Revertir ${note.number} y reabrir el saldo de ${note.invoice_number}?`)) return;
      const reason = window.prompt("Motivo de la reversa (mínimo 10 caracteres):");
      if (!reason || reason.trim().length < 10) { toast("Escribe un motivo de al menos 10 caracteres."); return; }
      try {
        await apiRequest(`billing/credit-notes/${note.id}/reverse/`, { method: "POST", body: { reason: reason.trim(), confirm_irreversible: true } });
        await syncFromApi(); toast("Nota revertida; se reabrió el saldo y se creó la póliza inversa cuando correspondía.");
      } catch (error) { toast(error.message); }
      return;
    }
    const reverseCustomerPayment = event.target.closest("[data-customer-payment-reverse]");
    if (reverseCustomerPayment && can("billing.reverse_payment")) {
      const payment = live.payments.find((item) => item.id === reverseCustomerPayment.dataset.customerPaymentReverse);
      if (!payment || !window.confirm(`Confirma que el cobro ${payment.number} fue devuelto o cancelado. Se reabrirá el saldo de sus facturas y se revertirá su póliza contabilizada si existe.`)) return;
      const reason = window.prompt("Motivo de la reversa (mínimo 10 caracteres):");
      if (!reason || reason.trim().length < 10) { toast("Escribe un motivo de al menos 10 caracteres."); return; }
      try {
        await apiRequest(`billing/payments/${payment.id}/reverse/`, { method: "POST", body: { reason: reason.trim(), confirm_irreversible: true } });
        await syncFromApi(); toast("Cobro revertido; se reabrió el saldo y se registró la póliza inversa cuando correspondía.");
      } catch (error) { toast(error.message); }
      return;
    }
    const prepareCFDI = event.target.closest("[data-cfdi-prepare]");
    if (prepareCFDI) { openCFDIPreparation(prepareCFDI.dataset.cfdiPrepare); return; }
    const prepareCreditNoteCFDI = event.target.closest("[data-credit-note-cfdi]");
    if (prepareCreditNoteCFDI) {
      const note = live.creditNotes.find((item) => item.id === prepareCreditNoteCFDI.dataset.creditNoteCfdi);
      if (!note) return;
      const cfdiUse = window.prompt("Uso CFDI del egreso, elegido por Contabilidad (por ejemplo, G02 para devoluciones, descuentos o bonificaciones):", "G02");
      if (cfdiUse === null) return;
      const paymentForm = window.prompt("Forma de pago SAT aplicable a esta bonificación (clave de dos dígitos; Contabilidad debe confirmarla):", "");
      if (paymentForm === null) return;
      if (!/^[A-Z0-9]{3}$/.test(cfdiUse.trim()) || !/^\d{2}$/.test(paymentForm.trim()) || paymentForm.trim() === "99") { toast("Revisa Uso CFDI y forma de pago SAT; PUE no admite la clave 99."); return; }
      try {
        const fiscal = await apiRequest(`billing/credit-notes/${note.id}/prepare-cfdi/`, { method: "POST", body: { cfdi_use: cfdiUse.trim(), payment_form: paymentForm.trim(), idempotency_key: newUuid() } });
        await syncFromApi(); toast(`Snapshot de CFDI E preparado y ligado al UUID ${fiscal.request_payload?.related_cfdi_uuid}. Revisa antes de firmar o enviar a FEL.`);
      } catch (error) { toast(error.message); }
      return;
    }
    const preparePaymentCFDI = event.target.closest("[data-payment-cfdi]");
    if (preparePaymentCFDI) {
      const payment = live.payments.find((item) => item.id === preparePaymentCFDI.dataset.paymentCfdi);
      if (!payment) return;
      const suggestedForm = ({ transfer: "03", cash: "01", check: "02" })[payment.method] || "";
      const paymentForm = prompt("Captura la clave SAT de forma de pago realmente recibida (por ejemplo, 03 transferencia).", suggestedForm);
      if (paymentForm === null) return;
      if (!/^\d{2}$/.test(paymentForm.trim()) || paymentForm.trim() === "99") { toast("Captura una clave SAT de dos dígitos distinta de 99."); return; }
      try {
        await apiRequest(`billing/payments/${payment.id}/prepare-payment-cfdi/`, { method: "POST", body: { payment_form: paymentForm.trim(), idempotency_key: newUuid() } });
        await syncFromApi(); toast("Snapshot del complemento guardado para revisión; aún no es un CFDI emitido.");
      } catch (error) { toast(error.message); }
      return;
    }
    const queryFiscal = event.target.closest("[data-fiscal-query]");
    if (queryFiscal) {
      try {
        const document = await apiRequest(`billing/fiscal-documents/${queryFiscal.dataset.fiscalQuery}/query/`, { method: "POST" });
        await syncFromApi();
        toast(document.state === "stamped" ? `FEL confirmó el timbrado ${document.cfdi_uuid}.` : document.state === "cancelled" ? `FEL confirmó la cancelación ${document.cfdi_uuid}.` : document.state === "cancel_pending" ? "El UUID sigue vigente o la cancelación espera aceptación; vuelve a consultar más adelante." : "FEL no confirmó un timbre; el documento sigue enviado para revisión. No se reenvió.");
      } catch (error) { toast(error.message); }
      return;
    }
    const downloadFiscalPdf = event.target.closest("[data-fiscal-pdf]");
    if (downloadFiscalPdf) {
      try {
        const response = await fetch(`${backend.base.replace(/\/$/, "")}/billing/fiscal-documents/${downloadFiscalPdf.dataset.fiscalPdf}/pdf/`, { headers: backend.token ? { Authorization: `Token ${backend.token}` } : {} });
        if (!response.ok) {
          const payload = await response.json().catch(() => null);
          throw new Error(payload?.detail || `No se pudo descargar el PDF timbrado (${response.status}).`);
        }
        const objectUrl = URL.createObjectURL(await response.blob());
        const link = document.createElement("a"); link.href = objectUrl; link.download = `CFDI-${downloadFiscalPdf.dataset.fiscalPdf}.pdf`; link.click();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      } catch (error) { toast(error.message); }
      return;
    }
    const cancelFiscal = event.target.closest("[data-fiscal-cancel]");
    if (cancelFiscal) {
      const documentId = cancelFiscal.dataset.fiscalCancel;
      const reason = prompt("Motivo SAT: 01 error con relación, 02 error sin relación, 03 operación no realizada, 04 nominativa en factura global.");
      if (reason === null) return;
      const normalizedReason = reason.trim().padStart(2, "0");
      if (!["01", "02", "03", "04"].includes(normalizedReason)) { toast("Captura una clave SAT válida: 01, 02, 03 o 04."); return; }
      let replacementUuid = null;
      if (normalizedReason === "01") {
        replacementUuid = prompt("UUID de un CFDI ya timbrado y vigente en Redmagna. Debe coincidir tipo, RFC emisor/receptor y moneda; su XML debe relacionar con clave 04 solo el UUID que cancelarás:");
        if (replacementUuid === null || !replacementUuid.trim()) return;
      }
      if (!window.confirm("Esta solicitud se envía al SAT por FEL Premium. FEL no ofrece un ambiente de pruebas para cancelaciones; el proceso puede consumir un timbre y no se puede revertir. FEL recomienda esperar 24 horas después de emitir. ¿Confirmas que revisaste motivo y UUID sustituto?")) return;
      try {
        const fiscal = await apiRequest(`billing/fiscal-documents/${documentId}/cancel/`, { method: "POST", body: { reason: normalizedReason, replacement_uuid: replacementUuid?.trim() || null, confirm_irreversible: true } });
        live.fiscalDocuments = live.fiscalDocuments.map((item) => item.id === fiscal.id ? fiscal : item);
        renderFEL();
        toast(fiscal.state === "cancelled" ? `FEL confirmó la cancelación ${fiscal.cfdi_uuid}.` : fiscal.state === "cancel_pending" ? "La solicitud quedó pendiente de aceptación o confirmación. Consulta SAT/FEL antes de actuar de nuevo." : "FEL rechazó la cancelación. Revisa el código y la respuesta registrados.");
      } catch (error) { await syncFromApi().catch(() => {}); toast(`${error.message} Si la respuesta de FEL fue incierta, verifica SAT/FEL antes de reintentar.`); }
      return;
    }
    const sendFiscalCopy = event.target.closest("[data-fiscal-customer-copy]");
    if (sendFiscalCopy) {
      const documentId = sendFiscalCopy.dataset.fiscalCustomerCopy;
      const current = live.fiscalDocuments.find((item) => item.id === documentId);
      if (!current || current.state !== "stamped") { toast("Solo se puede enviar un CFDI timbrado y vigente."); return; }
      if (!window.confirm(`Enviar el XML y el PDF disponible del CFDI ${current.cfdi_uuid} al correo registrado del cliente? Si el resultado del correo es incierto, revisa la bitácora antes de volver a enviarlo.`)) return;
      try {
        const fiscal = await apiRequest(`billing/fiscal-documents/${documentId}/send-customer-copy/`, { method: "POST" });
        live.fiscalDocuments = live.fiscalDocuments.map((item) => item.id === fiscal.id ? fiscal : item);
        renderFEL();
        const delivery = [...(fiscal.events || [])].reverse().find((item) => item.response_payload?.type === "customer_copy_email");
        toast(`Copia fiscal enviada a ${delivery?.response_payload?.recipient || "el correo registrado del cliente"}.`);
      } catch (error) {
        await syncFromApi().catch(() => {});
        toast(error.message);
      }
      return;
    }
    const generateFiscalXml = event.target.closest("[data-fiscal-generate]");
    if (generateFiscalXml) {
      const documentId = generateFiscalXml.dataset.fiscalGenerate;
      const current = live.fiscalDocuments.find((item) => item.id === documentId);
      if (current?.document_type === "P" && !current.request_xml && !window.confirm("Confirma que revisaste las facturas relacionadas, saldos e IVA del snapshot antes de firmar este complemento de pago.")) return;
      if (current?.document_type === "E" && !current.request_xml && !window.confirm(`Confirma que revisaste Uso CFDI ${current.cfdi_use}, forma de pago ${current.payment_form}, receptor ${current.recipient_rfc}, CFDI de ingreso relacionado ${current.request_payload?.related_cfdi_uuid}, conceptos e IVA antes de firmar.`)) return;
      try {
        const body = current?.document_type === "P" ? { confirm_payment_snapshot: true } : current?.document_type === "E" ? { confirm_credit_note_snapshot: true } : {};
        const fiscal = current?.request_xml ? current : await apiRequest(`billing/fiscal-documents/${documentId}/generate-xml/`, { method: "POST", body });
        live.fiscalDocuments = live.fiscalDocuments.map((item) => item.id === fiscal.id ? fiscal : item);
        const invoice = live.invoices.find((item) => item.id === fiscal.invoice);
        const creditNote = live.creditNotes.find((item) => item.id === fiscal.credit_note);
        const payment = live.payments.find((item) => item.id === fiscal.payment);
        const filename = `${invoice?.number || creditNote?.number || payment?.number || "CFDI"}.xml`;
        const link = document.createElement("a");
        link.href = URL.createObjectURL(new Blob([fiscal.request_xml], { type: "application/xml;charset=utf-8" }));
        link.download = filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        renderFEL();
        toast("XML firmado y validado con los XSD locales del SAT. Aún no se envió a FEL.");
      } catch (error) { toast(error.message); }
      return;
    }
    const sendFiscal = event.target.closest("[data-fiscal-send]");
    if (sendFiscal) {
      const current = live.fiscalDocuments.find((item) => item.id === sendFiscal.dataset.fiscalSend);
      if (current?.document_type === "E" && !window.confirm(`Enviar a FEL el CFDI E por ${money(current.request_payload?.total)} MXN, relacionado al UUID ${current.request_payload?.related_cfdi_uuid}? Si FEL lo timbra, consumirá un timbre.`)) return;
      try {
        const fiscal = await apiRequest(`billing/fiscal-documents/${sendFiscal.dataset.fiscalSend}/send/`, { method: "POST" });
        live.fiscalDocuments = live.fiscalDocuments.map((item) => item.id === fiscal.id ? fiscal : item);
        renderFEL();
        if (fiscal.state === "stamped") toast(`FEL confirmó el timbrado ${fiscal.cfdi_uuid}.`);
        else if (fiscal.state === "rejected") toast("FEL rechazó el CFDI. Revisa el código y la respuesta antes de corregirlo.");
        else toast("FEL no confirmó el resultado. El envío quedó pendiente; consulta por referencia antes de cualquier reintento.");
      } catch (error) {
        await syncFromApi().catch(() => {});
        toast(`${error.message} Revisa el estado y consulta la referencia antes de reintentar.`);
      }
      return;
    }
    const cfdiCloseButton = event.target.closest("#close-cfdi-preparation, #cancel-cfdi-preparation");
    if (cfdiCloseButton) { $("#cfdi-preparation-modal").classList.remove("open"); return; }
  });

  $("#cfdi-preparation-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const invoiceId = $("#cfdi-invoice-id").value;
    const concepts = Array.from(document.querySelectorAll("[data-cfdi-line]")).map((row) => ({
      invoice_line_id: row.dataset.cfdiLine,
      product_service_key: row.querySelector("[data-cfdi-product-service]").value.trim(),
      unit_key: row.querySelector("[data-cfdi-unit]").value.trim().toUpperCase(),
      tax_object: row.querySelector("[data-cfdi-tax-object]").value,
      tax_factor: row.querySelector("[data-cfdi-tax-factor]").value,
    }));
    const body = { cfdi_use: $("#cfdi-use").value.trim().toUpperCase(), exportation: $("#cfdi-exportation").value, payment_method: $("#cfdi-payment-method").value, payment_form: $("#cfdi-payment-form").value.trim(), idempotency_key: newUuid(), concepts };
    try {
      await apiRequest(`billing/invoices/${invoiceId}/prepare-cfdi/`, { method: "POST", body });
      await syncFromApi(); $("#cfdi-preparation-modal").classList.remove("open"); toast("Snapshot fiscal guardado para revisión; aún no es un CFDI emitido.");
    } catch (error) { toast(error.message); }
  });

  $("#connect-api").addEventListener("click", () => { $("#api-base").value = backend.base; $("#api-modal").classList.add("open"); });
  $("#manage-sessions").addEventListener("click", openApiSessions);
  $("#close-session-modal").addEventListener("click", () => $("#session-modal").classList.remove("open"));
  $("#done-session-modal").addEventListener("click", () => $("#session-modal").classList.remove("open"));
  $("#close-api-modal").addEventListener("click", () => $("#api-modal").classList.remove("open"));
  async function disconnectApi() {
    const hadToken = backend.connected && Boolean(backend.token);
    let revoked = !hadToken;
    if (hadToken) {
      try { await apiRequest("auth/logout/", { method: "POST" }); revoked = true; }
      catch { revoked = false; }
    }
    backend.connected = false; backend.token = ""; backend.permissions = new Set(); sessionStorage.removeItem("redmagna-api-token");
    live.invoices = []; live.creditNotes = []; live.payments = []; live.workOrders = []; live.supportTickets = []; live.supportAssignees = []; live.entries = []; live.assignees = [];
    live.receivablesAging = null; live.customerStatement = null; live.trialBalance = null; live.generalLedger = null; live.financialStatements = null; live.subledgerReconciliation = null;
    live.inventory = { products: [], locations: [], balances: [], movements: [], reservations: [], serialUnits: [], reorderRules: [] };
    live.purchasing = { suppliers: [], supplierProducts: [], orders: [], receipts: [], bills: [], supplierPayments: [], sourcing: [], payablesAging: null, supplierStatement: null };
    try { db = JSON.parse(localStorage.getItem("redmagna-erp-v1")) || structuredClone(seed); } catch { db = structuredClone(seed); }
    render(); $("#api-modal").classList.remove("open"); $("#session-modal").classList.remove("open"); updateConnectionState();
    toast(revoked ? "Sesión cerrada; el token se revocó en el servidor." : "Se borró el token local, pero no se confirmó la revocación. El token vencerá según el plazo configurado.");
  }
  $("#disconnect-api").addEventListener("click", disconnectApi);
  $("#api-form").addEventListener("submit", async (event) => {
    event.preventDefault(); backend.base = $("#api-base").value.trim().replace(/\/$/, "");
    try {
      const response = await apiRequest("auth/token/", { method: "POST", noAuth: true, body: { username: $("#api-user").value.trim(), password: $("#api-password").value } });
      backend.token = response.token; localStorage.setItem("redmagna-api-base", backend.base); sessionStorage.setItem("redmagna-api-token", backend.token); $("#api-password").value = "";
      await connectSession(); $("#api-modal").classList.remove("open"); toast("Conexión con la base central lista.");
    } catch (error) { backend.token = ""; backend.connected = false; backend.permissions = new Set(); sessionStorage.removeItem("redmagna-api-token"); updateConnectionState(); toast(`No se pudo conectar: ${error.message}`); }
  });

  const closeWorkOrderModal = () => $("#work-order-modal").classList.remove("open");
  $("#close-work-order-modal").addEventListener("click", closeWorkOrderModal);
  $("#cancel-work-order-modal").addEventListener("click", closeWorkOrderModal);
  $("#work-order-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const workOrderId = $("#work-order-id").value;
    const canSchedule = can("sales.schedule_workorder");
    const start = $("#wo-start").value, end = $("#wo-end").value;
    if (canSchedule && start && end && new Date(end) <= new Date(start)) { toast("La hora de fin debe ser posterior a la hora de inicio."); return; }
    const body = canSchedule ? {
      assigned_to: $("#wo-assignee").value || null,
      scheduled_start: start ? new Date(start).toISOString() : null,
      scheduled_end: end ? new Date(end).toISOString() : null,
      customer_site: $("#wo-customer-site").value || null,
      service_site_name: $("#wo-site-name").value.trim(),
      service_address: $("#wo-service-address").value.trim(),
      service_contact_name: $("#wo-service-contact").value.trim(),
      service_contact_phone: $("#wo-service-phone").value.trim(),
      service_contact_email: $("#wo-service-email").value.trim(),
      completion_notes: $("#wo-notes").value.trim(),
    } : { completion_notes: $("#wo-notes").value.trim() };
    try {
      await apiRequest(`work-orders/${workOrderId}/schedule/`, { method: "PATCH", body });
      await syncFromApi(); closeWorkOrderModal(); toast(canSchedule ? "Programación, responsable y notas guardados." : "Nota de cierre guardada.");
    } catch (error) { toast(error.message); }
  });
  $("#wo-save-site").addEventListener("click", async () => {
    const work = live.workOrders.find((item) => item.id === $("#work-order-id").value);
    const name = $("#wo-site-name").value.trim();
    const address = $("#wo-service-address").value.trim();
    if (!work || !name || !address) { toast("Indica el nombre del sitio y su domicilio antes de guardarlo."); return; }
    try {
      const site = await apiRequest("customer-sites/", { method: "POST", body: { customer: work.customer_id, name, address, contact_name: $("#wo-service-contact").value.trim(), phone: $("#wo-service-phone").value.trim(), email: $("#wo-service-email").value.trim() } });
      workOrderSites.push(site);
      $("#wo-customer-site").insertAdjacentHTML("beforeend", `<option value="${escapeHtml(site.id)}">${escapeHtml(site.name)} · ${escapeHtml(site.address)}</option>`);
      $("#wo-customer-site").value = site.id;
      toast("Sitio guardado para este cliente.");
    } catch (error) { toast(error.message); }
  });
  const closeWorkOrderEvidence = () => $("#work-order-evidence-modal").classList.remove("open");
  $("#close-work-order-evidence").addEventListener("click", closeWorkOrderEvidence);
  $("#cancel-work-order-evidence").addEventListener("click", closeWorkOrderEvidence);
  $("#work-evidence-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!can("sales.add_workorderevidence")) return;
    const file = $("#work-evidence-file").files[0];
    if (!file) { toast("Selecciona una foto o PDF."); return; }
    const formData = new FormData();
    formData.append("file", file);
    formData.append("description", $("#work-evidence-description").value.trim());
    const url = `${backend.base.replace(/\/$/, "")}/work-orders/${event.currentTarget.dataset.workOrderId}/evidence/`;
    try {
      const response = await fetch(url, { method: "POST", headers: backend.token ? { Authorization: `Token ${backend.token}` } : {}, body: formData });
      const payload = await response.json().catch(() => null);
      if (!response.ok) throw new Error(payload?.detail || Object.values(payload || {}).flat().join(" ") || `Error ${response.status}`);
      event.currentTarget.reset();
      await refreshWorkOrderEvidence(event.currentTarget.dataset.workOrderId);
      toast("Evidencia guardada en la orden de trabajo.");
    } catch (error) { toast(error.message); }
  });
  $("#wo-checklist-add").addEventListener("click", async () => {
    const workOrderId = $("#work-order-id").value;
    const label = $("#wo-checklist-label").value.trim();
    if (!label) { toast("Escribe el punto que quieres agregar."); return; }
    try {
      await apiRequest(`work-orders/${workOrderId}/checklist/add/`, { method: "POST", body: { label } });
      $("#wo-checklist-label").value = "";
      await syncFromApi();
      const work = live.workOrders.find((item) => item.id === workOrderId);
      if (work) renderWorkOrderChecklist(work);
      toast("Punto agregado a la lista.");
    } catch (error) { toast(error.message); }
  });
  $("#wo-checklist-template-apply").addEventListener("click", async () => {
    const workOrderId = $("#work-order-id").value;
    const template = $("#wo-checklist-template").value;
    if (!template) { toast("Selecciona una plantilla para aplicarla."); return; }
    try {
      await apiRequest(`work-orders/${workOrderId}/checklist/apply-template/`, { method: "POST", body: { template } });
      await syncFromApi();
      const work = live.workOrders.find((item) => item.id === workOrderId);
      if (work) renderWorkOrderChecklist(work);
      toast("Plantilla aplicada; los puntos se copiaron a esta orden.");
    } catch (error) { toast(error.message); }
  });
  $("#wo-checklist-template-save").addEventListener("click", async () => {
    const workOrderId = $("#work-order-id").value;
    const work = live.workOrders.find((item) => item.id === workOrderId);
    const name = $("#wo-checklist-template-name").value.trim();
    const items = (work?.checklist_items || []).map((item) => item.label);
    if (!name || !items.length) { toast("Escribe un nombre y agrega puntos antes de guardar la plantilla."); return; }
    try {
      const template = await apiRequest("checklist-templates/", { method: "POST", body: { name, items } });
      workOrderChecklistTemplates.push(template);
      $("#wo-checklist-template").innerHTML = `<option value="">Selecciona una plantilla</option>${workOrderChecklistTemplates.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)} · ${item.items.length} puntos</option>`).join("")}`;
      $("#wo-checklist-template").value = template.id;
      $("#wo-checklist-template-name").value = "";
      if (work) renderWorkOrderChecklist(work);
      toast("Plantilla guardada para futuras órdenes.");
    } catch (error) { toast(error.message); }
  });
  $("#wo-checklist-items").addEventListener("change", async (event) => {
    const checkbox = event.target.closest("[data-work-checklist]");
    if (!checkbox) return;
    const workOrderId = $("#work-order-id").value;
    try {
      await apiRequest(`work-orders/${workOrderId}/checklist/${checkbox.dataset.workChecklist}/`, { method: "PATCH", body: { is_completed: checkbox.checked } });
      await syncFromApi();
      const work = live.workOrders.find((item) => item.id === workOrderId);
      if (work) renderWorkOrderChecklist(work);
    } catch (error) { checkbox.checked = !checkbox.checked; toast(error.message); }
  });
  $("#wo-customer-acceptance-save").addEventListener("click", async () => {
    const workOrderId = $("#work-order-id").value;
    const body = { customer_contact_name: $("#wo-customer-contact-name").value.trim(), customer_contact_email: $("#wo-customer-contact-email").value.trim(), notes: $("#wo-customer-acceptance-notes").value.trim(), customer_confirmed: $("#wo-customer-confirmed").checked };
    if (!body.customer_confirmed) { toast("Confirma que el cliente manifestó su conformidad."); return; }
    try {
      await apiRequest(`work-orders/${workOrderId}/customer-acceptance/`, { method: "POST", body });
      await syncFromApi();
      const work = live.workOrders.find((item) => item.id === workOrderId);
      if (work) renderWorkOrderChecklist(work);
      toast("Conformidad del cliente registrada en la orden.");
    } catch (error) { toast(error.message); }
  });

  const closeWorkLogModal = () => $("#work-log-modal").classList.remove("open");
  $("#close-work-log-modal").addEventListener("click", closeWorkLogModal);
  $("#cancel-work-log-modal").addEventListener("click", closeWorkLogModal);
  $("#work-log-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const workOrderId = $("#work-log-order-id").value;
    const body = { work_date: $("#work-log-date").value, hours: Number($("#work-log-hours").value).toFixed(2), description: $("#work-log-description").value.trim() };
    try {
      await apiRequest(`work-orders/${workOrderId}/log-hours/`, { method: "POST", body });
      await syncFromApi(); closeWorkLogModal(); toast("Horas de trabajo registradas.");
    } catch (error) { toast(error.message); }
  });

  const closeStockMovementModal = () => $("#stock-movement-modal").classList.remove("open");
  $("#close-stock-movement-modal").addEventListener("click", closeStockMovementModal);
  $("#cancel-stock-movement-modal").addEventListener("click", closeStockMovementModal);
  $("#stock-product-scan").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); scanStockMovementProduct(); }
  });
  $("#stock-location-scan").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); scanStockMovementLocation(); }
  });
  $("#stock-movement-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const kind = $("#stock-kind").value, workOrderId = $("#stock-work-order-id").value;

    const body = { product: $("#stock-product").value, location: $("#stock-location").value || null, quantity: Number($("#stock-quantity").value).toFixed(3), reference: $("#stock-reference").value.trim(), note: $("#stock-note").value.trim(), serial_numbers: $("#stock-serials").value.split(/[\n,;]+/).map((value) => value.trim()).filter(Boolean), idempotency_key: event.currentTarget.dataset.idempotencyKey };
    if (workOrderId) body.work_order = workOrderId;
    if (kind === "adjustment_in" || kind === "adjustment_out") body.direction = kind === "adjustment_in" ? "in" : "out";
    try {
      if (kind === "reserve") await apiRequest("inventory/reservations/", { method: "POST", body: { work_order: workOrderId, product: body.product, location: body.location, quantity: body.quantity, idempotency_key: newUuid() } });
      else {
        const path = { receipt: "receive", issue: "issue", return: "return", adjustment_in: "adjust", adjustment_out: "adjust" }[kind];
        await apiRequest(`inventory/movements/${path}/`, { method: "POST", body });
      }
      await syncFromApi(); closeStockMovementModal(); toast(kind === "reserve" ? "Material reservado para esta orden." : "Movimiento de inventario registrado.");
    } catch (error) { toast(error.message); }
  });

  const closeInventoryProductModal = () => $("#inventory-product-modal").classList.remove("open");
  const closeStockUnitReserve = () => $("#stock-unit-reserve-modal").classList.remove("open");
  $("#close-stock-unit-reserve").addEventListener("click", closeStockUnitReserve);
  $("#cancel-stock-unit-reserve").addEventListener("click", closeStockUnitReserve);
  $("#stock-serial-list").addEventListener("click", async (event) => {
    const reserveButton = event.target.closest("[data-stock-unit-reserve]");
    if (reserveButton) { openStockUnitReserve(reserveButton.dataset.stockUnitReserve); return; }
    const releaseButton = event.target.closest("[data-stock-unit-release]");
    if (releaseButton) {
      try { await apiRequest(`inventory/units/${releaseButton.dataset.stockUnitRelease}/release/`, { method: "POST", body: {} }); await syncFromApi(); toast("Reserva liberada; el equipo vuelve a estar disponible."); }
      catch (error) { toast(error.message); }
    }
  });
  $("#stock-serial-search").addEventListener("input", () => { stockSerialPage = 0; renderInventory(); });
  $("#stock-serial-prev").addEventListener("click", () => { stockSerialPage = Math.max(0, stockSerialPage - 1); renderInventory(); });
  $("#stock-serial-next").addEventListener("click", () => { stockSerialPage += 1; renderInventory(); });
  $("#stock-unit-reserve-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const unitId = $("#stock-unit-reserve-id").value;
    try {
      await apiRequest(`inventory/units/${unitId}/reserve/`, { method: "POST", body: { work_order: $("#stock-unit-reserve-order").value } });
      await syncFromApi(); closeStockUnitReserve(); toast("Equipo reservado para la orden de trabajo.");
    } catch (error) { toast(error.message); }
  });
  const closeStockUnitInstall = () => $("#stock-unit-install-modal").classList.remove("open");
  $("#close-stock-unit-install").addEventListener("click", closeStockUnitInstall);
  $("#cancel-stock-unit-install").addEventListener("click", closeStockUnitInstall);
  $("#stock-serial-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-stock-unit-install]");
    if (button) openStockUnitInstall(button.dataset.stockUnitInstall);
  });
  $("#stock-unit-install-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const unitId = $("#stock-unit-install-id").value;
    const body = { installed_at: $("#stock-unit-installed-at").value, warranty_until: $("#stock-unit-warranty-until").value || null };
    try {
      await apiRequest(`inventory/units/${unitId}/install/`, { method: "POST", body });
      await syncFromApi(); closeStockUnitInstall(); toast("Instalación registrada; el equipo aparece en los activos del cliente para soporte.");
    } catch (error) { toast(error.message); }
  });
  const closeInventoryLocationModal = () => $("#inventory-location-modal").classList.remove("open");
  const closeInventoryReorderModal = () => $("#inventory-reorder-modal").classList.remove("open");
  function openInventoryReorder(ruleId = "") {
    const rule = (live.inventory.reorderRules || []).find((item) => item.id === ruleId);
    const productOptions = live.inventory.products.filter((item) => item.kind === "stockable" && (item.is_active || item.id === rule?.product));
    const locationOptions = live.inventory.locations.filter((item) => item.is_active || item.id === rule?.location);
    if (!rule && (!productOptions.length || !locationOptions.length)) { toast("Primero registra un producto con existencias y una ubicación activa."); return; }
    $("#inventory-reorder-form").reset();
    $("#inventory-reorder-id").value = rule?.id || "";
    $("#inventory-reorder-title").textContent = rule ? "Editar regla de reabastecimiento" : "Regla de reabastecimiento";
    $("#inventory-reorder-product").innerHTML = productOptions.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.sku)} · ${escapeHtml(item.name)}</option>`).join("");
    $("#inventory-reorder-location").innerHTML = locationOptions.map((item) => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.code)} · ${escapeHtml(item.name)}</option>`).join("");
    $("#inventory-reorder-product").disabled = Boolean(rule);
    $("#inventory-reorder-location").disabled = Boolean(rule);
    if (rule) {
      $("#inventory-reorder-product").value = rule.product;
      $("#inventory-reorder-location").value = rule.location;
      $("#inventory-reorder-minimum").value = rule.minimum_quantity;
      $("#inventory-reorder-target").value = rule.target_quantity;
      $("#inventory-reorder-active").checked = rule.is_active;
    } else {
      $("#inventory-reorder-minimum").value = "0.000";
      $("#inventory-reorder-target").value = "1.000";
      $("#inventory-reorder-active").checked = true;
    }
    $("#inventory-reorder-modal").classList.add("open");
  }
  async function loadInventoryForecast() {
    const ruleId = $("#inventory-forecast-rule").value;
    const horizon = $("#inventory-forecast-horizon").value;
    $("#inventory-forecast-summary").textContent = "Cargando previsión…";
    $("#inventory-forecast-warning").textContent = "";
    $("#inventory-forecast-rows").innerHTML = "";
    try {
      const forecast = await apiRequest(`inventory/reorder-rules/${ruleId}/forecast/?horizon_days=${encodeURIComponent(horizon)}`);
      const fmt = (value) => Number(value).toLocaleString("es-MX", { maximumFractionDigits: 3 });
      $("#inventory-forecast-product").textContent = `${forecast.product_sku} · ${forecast.product_name} · ${forecast.location_code}`;
      const breach = forecast.first_breach_date ? `Baja del mínimo: ${forecast.first_breach_date}` : "No baja del mínimo en el horizonte con fechas conocidas";
      $("#inventory-forecast-summary").textContent = `Disponible al corte ${fmt(forecast.opening_available)} · mínimo ${fmt(forecast.minimum_quantity)} · mínimo previsto ${fmt(forecast.minimum_projected_quantity)} · sugerencia ${fmt(forecast.suggested_quantity)} · ${breach}`;
      const warnings = [];
      if (Number(forecast.unknown_demand) > 0) warnings.push(`Demanda sin fecha: ${fmt(forecast.unknown_demand)} (${forecast.undated_work_orders.join(", ")}).`);
      if (Number(forecast.unknown_incoming) > 0) warnings.push(`Compras sin fecha esperada: ${fmt(forecast.unknown_incoming)} (${forecast.undated_purchase_orders.join(", ")}).`);
      if (Number(forecast.undestined_incoming) > 0) warnings.push(`Compras pendientes sin ubicación destino: ${fmt(forecast.undestined_incoming)} (${forecast.undestined_purchase_orders.join(", ")}).`);
      if (warnings.length) warnings.unshift("La proyección diaria no incluye estos movimientos porque no tienen fecha; la disponibilidad futura puede cambiar.");
      $("#inventory-forecast-warning").textContent = warnings.join(" ");
      const kindLabels = { incoming: "Entrada", demand: "Demanda" };
      $("#inventory-forecast-rows").innerHTML = forecast.rows.map((row) => {
        const events = row.events.map((item) => `${kindLabels[item.kind]} ${item.reference}${item.overdue ? " · vencida" : ""}`).join("; ");
        return `<tr><td>${escapeHtml(row.date)}</td><td class="money">${fmt(row.incoming)}</td><td class="money">${fmt(row.demand)}</td><td class="money"><strong>${fmt(row.projected_quantity)}</strong>${row.below_minimum ? `<small style="display:block;color:var(--red)">Bajo mínimo</small>` : ""}</td><td>${escapeHtml(events || "—")}</td></tr>`;
      }).join("") || `<tr><td colspan="5" class="empty">Sin fechas en el horizonte.</td></tr>`;
    } catch (error) {
      $("#inventory-forecast-summary").textContent = "No se pudo cargar la previsión.";
      toast(error.message);
    }
  }
  function openInventoryForecast(ruleId) {
    const rule = (live.inventory.reorderRules || []).find((item) => item.id === ruleId);
    if (!rule) return;
    $("#inventory-forecast-rule").value = ruleId;
    $("#inventory-forecast-product").textContent = `${rule.product_sku} · ${rule.product_name} · ${rule.location_code}`;
    $("#inventory-forecast-modal").classList.add("open");
    loadInventoryForecast();
  }
  const closeInventoryForecast = () => $("#inventory-forecast-modal").classList.remove("open");
  $("#close-inventory-forecast").addEventListener("click", closeInventoryForecast);
  $("#cancel-inventory-forecast").addEventListener("click", closeInventoryForecast);
  $("#inventory-forecast-horizon").addEventListener("change", loadInventoryForecast);
  $("#inventory-reorder-new").addEventListener("click", () => openInventoryReorder());
  $("#inventory-reorder-list").addEventListener("click", (event) => {
    const forecastButton = event.target.closest("[data-reorder-forecast]");
    if (forecastButton && can("inventory.view_reorderrule")) { openInventoryForecast(forecastButton.dataset.reorderForecast); return; }
    const purchaseButton = event.target.closest("[data-reorder-purchase]");
    if (purchaseButton && can("purchasing.add_purchaseorder")) {
      const rule = (live.inventory.reorderRules || []).find((item) => item.id === purchaseButton.dataset.reorderPurchase);
      if (rule?.suggested_quantity > 0) openPurchaseOrder("", { product: rule.product, expected_location: rule.location, quantity: rule.suggested_quantity });
      return;
    }
    const button = event.target.closest("[data-reorder-edit]");
    if (button && can("inventory.change_reorderrule")) openInventoryReorder(button.dataset.reorderEdit);
  });
  $("#close-inventory-reorder").addEventListener("click", closeInventoryReorderModal);
  $("#cancel-inventory-reorder").addEventListener("click", closeInventoryReorderModal);
  $("#inventory-reorder-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = $("#inventory-reorder-id").value;
    const body = {
      minimum_quantity: Number($("#inventory-reorder-minimum").value).toFixed(3),
      target_quantity: Number($("#inventory-reorder-target").value).toFixed(3),
      is_active: $("#inventory-reorder-active").checked,
    };
    if (!id) {
      body.product = $("#inventory-reorder-product").value;
      body.location = $("#inventory-reorder-location").value;
    }
    try {
      await apiRequest(id ? `inventory/reorder-rules/${id}/` : "inventory/reorder-rules/", { method: id ? "PATCH" : "POST", body });
      await syncFromApi(); closeInventoryReorderModal(); toast(id ? "Regla actualizada." : "Regla de reabastecimiento creada.");
    } catch (error) { toast(error.message); }
  });
  $("#inventory-location-new").addEventListener("click", () => { $("#inventory-location-form").reset(); $("#inventory-location-modal").classList.add("open"); });
  $("#close-inventory-location").addEventListener("click", closeInventoryLocationModal);
  $("#cancel-inventory-location").addEventListener("click", closeInventoryLocationModal);
  $("#inventory-location-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const body = { code: $("#inventory-location-code").value.trim().toUpperCase(), barcode: $("#inventory-location-barcode").value.trim(), name: $("#inventory-location-name").value.trim(), is_active: true };
    try { await apiRequest("inventory/locations/", { method: "POST", body }); event.currentTarget.reset(); await syncFromApi(); closeInventoryLocationModal(); toast("Ubicación agregada."); }
    catch (error) { toast(error.message); }
  });
  const closeInventoryTransfer = () => $("#inventory-transfer-modal").classList.remove("open");
  $("#inventory-transfer").addEventListener("click", openStockTransfer);
  $("#close-inventory-transfer").addEventListener("click", closeInventoryTransfer);
  $("#cancel-inventory-transfer").addEventListener("click", closeInventoryTransfer);
  $("#transfer-line-add").addEventListener("click", addStockTransferLine);
  $("#transfer-barcode-scan").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); addScannedProductToTransfer(); }
  });
  $("#transfer-source-scan").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); scanTransferLocation("source"); }
  });
  $("#transfer-destination-scan").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); scanTransferLocation("destination"); }
  });
  $("#inventory-transfer-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!can("inventory.transfer_stock")) return;
    const lines = [...$("#transfer-lines").querySelectorAll("[data-transfer-line]")].map((row) => ({ product: row.querySelector("[data-transfer-product]").value, quantity: Number(row.querySelector("[data-transfer-quantity]").value).toFixed(3), serial_numbers: (row.querySelector("[data-transfer-serials]")?.value || "").split(/[\n,;]+/).map((value) => value.trim()).filter(Boolean) }));
    const body = { source_location: $("#transfer-source").value, destination_location: $("#transfer-destination").value, idempotency_key: event.currentTarget.dataset.idempotencyKey, reference: $("#transfer-reference").value.trim(), note: $("#transfer-note").value.trim(), lines };
    try { await apiRequest("inventory/transfers/", { method: "POST", body }); await syncFromApi(); closeInventoryTransfer(); toast("Traspaso registrado; existencias actualizadas en ambas ubicaciones."); }
    catch (error) { toast(error.message); }
  });
  $("#import-products").addEventListener("click", () => $("#product-import-file").click());
  const closeProductImport = () => {
    $("#product-import-modal").classList.remove("open");
    $("#product-import-file").value = "";
    $("#product-import-rows").innerHTML = `<tr><td colspan="5" class="empty">Sin vista previa.</td></tr>`;
    $("#product-import-summary").textContent = "Selecciona un archivo CSV para revisar las filas.";
    $("#commit-product-import").disabled = true;
    productImportFile = null;
  };
  $("#close-product-import").addEventListener("click", closeProductImport);
  $("#cancel-product-import").addEventListener("click", closeProductImport);
  $("#product-import-file").addEventListener("change", async (event) => {
    productImportFile = event.currentTarget.files?.[0] || null;
    if (!productImportFile) return;
    const body = new FormData(); body.append("file", productImportFile);
    $("#product-import-modal").classList.add("open");
    $("#product-import-summary").textContent = "Revisando archivo…";
    $("#commit-product-import").disabled = true;
    try {
      const preview = await apiRequest("inventory/products/import-csv/", { method: "POST", body });
      const ready = preview.rows.filter((row) => row.status === "create").length;
      $("#product-import-rows").innerHTML = preview.rows.map((row) => `<tr><td>${escapeHtml(row.row)}</td><td>${escapeHtml(row.sku || "—")}</td><td>${escapeHtml(row.name || "—")}</td><td>${row.status === "create" ? "Listo" : row.status === "duplicate" ? "Omitido · SKU existente" : "Error"}</td><td>${escapeHtml(row.detail)}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">El archivo no contiene filas para importar.</td></tr>`;
      $("#product-import-summary").textContent = `${ready} listas para crear · ${preview.skipped} SKU existentes omitidos · ${preview.errors} con errores. La vista previa no guarda datos.`;
      $("#commit-product-import").disabled = ready === 0;
    } catch (error) { $("#product-import-summary").textContent = error.message; }
  });
  $("#commit-product-import").addEventListener("click", async () => {
    if (!productImportFile || !window.confirm("Se crearán únicamente las filas marcadas como listas. Los productos existentes y sus existencias no cambiarán. ¿Continuar?")) return;
    const body = new FormData(); body.append("file", productImportFile); body.append("commit", "true");
    $("#commit-product-import").disabled = true;
    try {
      const result = await apiRequest("inventory/products/import-csv/", { method: "POST", body });
      await syncFromApi();
      $("#product-import-summary").textContent = `Importación terminada: ${result.created} creados · ${result.skipped} SKU existentes omitidos · ${result.errors} filas con errores.`;
      toast(`${result.created} productos o servicios importados.`);
    } catch (error) { $("#product-import-summary").textContent = error.message; $("#commit-product-import").disabled = false; }
  });
  function openInventoryProduct(productId = "") {
    const form = $("#inventory-product-form"), product = productId ? live.inventory.products.find((item) => String(item.id) === String(productId)) : null;
    if (productId && !product) return;
    form.reset();
    form.dataset.edit = product?.id || "";
    $("#inventory-product-title").textContent = product ? "Editar producto o servicio" : "Nuevo producto";
    $("#inventory-product-sku").value = product?.sku || "";
    $("#inventory-product-name").value = product?.name || "";
    $("#inventory-product-barcode").value = product?.barcode || "";
    $("#inventory-product-kind").value = product?.kind || "stockable";
    $("#inventory-product-kind").disabled = Boolean(product);
    $("#inventory-product-unit").value = product?.unit || "pza";
    $("#inventory-product-description").value = product?.description || "";
    $("#inventory-product-sat-product-service").value = product?.sat_product_service_key || "";
    $("#inventory-product-sat-unit").value = product?.sat_unit_key || "";
    $("#inventory-product-sat-tax-object").value = product?.sat_tax_object || "02";
    $("#inventory-product-sat-tax-factor").value = product?.sat_tax_factor || "Tasa";
    $("#inventory-product-tracking").value = product?.tracking_policy || "quantity";
    $("#inventory-product-tracking").disabled = Boolean(product) || product?.kind === "service";
    $("#inventory-product-modal").classList.add("open");
  }
  $("#inventory-product-new").addEventListener("click", () => {
    openInventoryProduct();
  });
  $("#inventory-product-kind").addEventListener("change", () => {
    if ($("#inventory-product-kind").value === "service") { $("#inventory-product-tracking").value = "quantity"; $("#inventory-product-tracking").disabled = true; }
    else $("#inventory-product-tracking").disabled = false;
  });
  $("#close-inventory-product").addEventListener("click", closeInventoryProductModal);
  $("#cancel-inventory-product").addEventListener("click", closeInventoryProductModal);
  $("#inventory-product-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, editId = form.dataset.edit || "", existing = editId ? live.inventory.products.find((item) => String(item.id) === String(editId)) : null;
    const body = {
      sku: $("#inventory-product-sku").value.trim().toUpperCase(),
      barcode: $("#inventory-product-barcode").value.trim(),
      name: $("#inventory-product-name").value.trim(),
      kind: $("#inventory-product-kind").value,
      tracking_policy: $("#inventory-product-tracking").value,
      unit: $("#inventory-product-unit").value.trim(),
      sat_product_service_key: $("#inventory-product-sat-product-service").value.trim(),
      sat_unit_key: $("#inventory-product-sat-unit").value.trim().toUpperCase(),
      sat_tax_object: $("#inventory-product-sat-tax-object").value,
      sat_tax_factor: $("#inventory-product-sat-tax-factor").value,
      description: $("#inventory-product-description").value.trim(),
      is_active: existing ? existing.is_active : true,
    };
    try {
      await apiRequest(editId ? `inventory/products/${editId}/` : "inventory/products/", { method: editId ? "PATCH" : "POST", body });
      await syncFromApi(); closeInventoryProductModal(); toast(editId ? "Producto actualizado." : "Producto registrado.");
    } catch (error) { toast(error.message); }
  });

  const closeSupplierModal = () => $("#supplier-modal").classList.remove("open");
  $("#import-suppliers").addEventListener("click", () => $("#supplier-import-file").click());
  const closeSupplierImport = () => {
    $("#supplier-import-modal").classList.remove("open");
    $("#supplier-import-file").value = "";
    $("#supplier-import-rows").innerHTML = `<tr><td colspan="4" class="empty">Sin vista previa.</td></tr>`;
    $("#supplier-import-summary").textContent = "Selecciona un archivo CSV para revisar las filas.";
    $("#commit-supplier-import").disabled = true;
    supplierImportFile = null;
  };
  $("#close-supplier-import").addEventListener("click", closeSupplierImport);
  $("#cancel-supplier-import").addEventListener("click", closeSupplierImport);
  $("#supplier-import-file").addEventListener("change", async (event) => {
    supplierImportFile = event.currentTarget.files?.[0] || null;
    if (!supplierImportFile) return;
    const body = new FormData(); body.append("file", supplierImportFile);
    $("#supplier-import-modal").classList.add("open");
    $("#supplier-import-summary").textContent = "Revisando archivo…";
    $("#commit-supplier-import").disabled = true;
    try {
      const preview = await apiRequest("purchasing/suppliers/import-csv/", { method: "POST", body });
      const ready = preview.rows.filter((row) => row.status === "create").length;
      $("#supplier-import-rows").innerHTML = preview.rows.map((row) => `<tr><td>${escapeHtml(row.row)}</td><td>${escapeHtml(row.name || "—")}</td><td>${row.status === "create" ? "Listo" : row.status === "duplicate" ? "Omitido · posible duplicado" : "Error"}</td><td>${escapeHtml(row.detail)}</td></tr>`).join("") || `<tr><td colspan="4" class="empty">El archivo no contiene filas para importar.</td></tr>`;
      $("#supplier-import-summary").textContent = `${ready} listas para crear · ${preview.skipped} posibles duplicados omitidos · ${preview.errors} con errores. La vista previa no guarda datos.`;
      $("#commit-supplier-import").disabled = ready === 0;
    } catch (error) { $("#supplier-import-summary").textContent = error.message; }
  });
  $("#commit-supplier-import").addEventListener("click", async () => {
    if (!supplierImportFile || !window.confirm("Se crearán únicamente las filas marcadas como listas. Los proveedores existentes no se modificarán. ¿Continuar?")) return;
    const body = new FormData(); body.append("file", supplierImportFile); body.append("commit", "true");
    $("#commit-supplier-import").disabled = true;
    try {
      const result = await apiRequest("purchasing/suppliers/import-csv/", { method: "POST", body });
      await syncFromApi();
      $("#supplier-import-summary").textContent = `Importación terminada: ${result.created} creados · ${result.skipped} duplicados omitidos · ${result.errors} filas con errores.`;
      toast(`${result.created} proveedores importados.`);
    } catch (error) { $("#supplier-import-summary").textContent = error.message; $("#commit-supplier-import").disabled = false; }
  });
  $("#new-supplier").addEventListener("click", () => openSupplier());
  $("#new-framework-agreement").addEventListener("click", () => openFrameworkAgreement());
  $("#cancel-framework-agreement").addEventListener("click", () => { $("#framework-agreement-form").hidden = true; delete $("#framework-agreement-form").dataset.edit; });
  $("#add-framework-line").addEventListener("click", () => {
    captureFrameworkDraftLines();
    const firstProduct = activeStockProducts().find((product) => !frameworkDraftLines.some((line) => String(line.product) === String(product.id)));
    if (!firstProduct) return toast("Agrega primero un producto disponible con control de existencias al catálogo.");
    frameworkDraftLines.push({ product: firstProduct.id, unit_cost: "", quantity_limit: "", description: "" });
    renderFrameworkDraftLines();
  });
  $("#framework-lines").addEventListener("click", (event) => {
    const remove = event.target.closest("[data-framework-remove-line]"); if (!remove) return;
    captureFrameworkDraftLines();
    frameworkDraftLines.splice(Number(remove.dataset.frameworkRemoveLine), 1); renderFrameworkDraftLines();
  });
  $("#framework-agreement-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const lineInputs = [...$("#framework-lines").querySelectorAll(".line-item")].map((row) => ({ product: row.querySelector("[data-framework-product]").value, unit_cost: Number(row.querySelector("[data-framework-cost]").value).toFixed(2), quantity_limit: row.querySelector("[data-framework-limit]").value ? Number(row.querySelector("[data-framework-limit]").value).toFixed(3) : null, description: row.querySelector("[data-framework-description]").value.trim() }));
    if (!lineInputs.length || lineInputs.some((line) => !line.product || !(Number(line.unit_cost) >= 0) || (line.quantity_limit != null && !(Number(line.quantity_limit) > 0)))) return toast("Completa al menos un producto con un precio y límite válidos.");
    const form = event.currentTarget, editId = form.dataset.edit;
    const body = { reference: $("#framework-reference").value.trim(), supplier: $("#framework-supplier").value, valid_from: $("#framework-valid-from").value, valid_until: $("#framework-valid-until").value, notes: $("#framework-notes").value.trim(), line_inputs: lineInputs };
    try { await apiRequest(editId ? `purchasing/framework-agreements/${editId}/` : "purchasing/framework-agreements/", { method: editId ? "PATCH" : "POST", body }); await syncFromApi(); form.hidden = true; delete form.dataset.edit; toast(editId ? "Acuerdo actualizado." : "Acuerdo guardado como borrador."); }
    catch (error) { toast(error.message); }
  });
  const closeFrameworkOrder = () => $("#framework-order-modal").classList.remove("open");
  $("#close-framework-order").addEventListener("click", closeFrameworkOrder);
  $("#cancel-framework-order").addEventListener("click", closeFrameworkOrder);
  $("#framework-order-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const lines = [...$("#framework-order-lines").querySelectorAll("[data-framework-order-line]")].map((row) => ({ framework_line: row.dataset.frameworkOrderLine, expected_location: $("#framework-order-location").value, quantity: Number(row.querySelector("[data-framework-order-quantity]").value || 0).toFixed(3) })).filter((line) => Number(line.quantity) > 0);
    if (!lines.length) return toast("Indica la cantidad de al menos un producto disponible.");
    try { await apiRequest(`purchasing/framework-agreements/${event.currentTarget.dataset.agreement}/create-order/`, { method: "POST", body: { lines, expected_date: $("#framework-order-expected").value || null, notes: $("#framework-order-notes").value.trim() } }); await syncFromApi(); closeFrameworkOrder(); toast("Orden borrador creada con precios y saldo del acuerdo."); }
    catch (error) { toast(error.message); }
  });
  $("#framework-agreement-list").addEventListener("click", async (event) => {
    const edit = event.target.closest("[data-framework-edit]"); if (edit) return openFrameworkAgreement(edit.dataset.frameworkEdit);
    const createOrder = event.target.closest("[data-framework-order]"); if (createOrder) return openFrameworkOrder(createOrder.dataset.frameworkOrder);
    const activate = event.target.closest("[data-framework-activate]");
    if (activate) {
      if (!window.confirm("Al activar, los productos y precios quedarán protegidos. ¿Activar este acuerdo?")) return;
      try { await apiRequest(`purchasing/framework-agreements/${activate.dataset.frameworkActivate}/activate/`, { method: "POST", body: {} }); await syncFromApi(); toast("Acuerdo marco activado."); } catch (error) { toast(error.message); }
      return;
    }
    const close = event.target.closest("[data-framework-close]");
    if (close) {
      if (!window.confirm("El acuerdo dejará de aceptar nuevas órdenes. Las órdenes ya creadas se conservan. ¿Cerrar el acuerdo?")) return;
      try { await apiRequest(`purchasing/framework-agreements/${close.dataset.frameworkClose}/close/`, { method: "POST", body: {} }); await syncFromApi(); toast("Acuerdo cerrado."); } catch (error) { toast(error.message); }
    }
  });
  $("#close-supplier").addEventListener("click", closeSupplierModal);
  $("#cancel-supplier").addEventListener("click", closeSupplierModal);
  $("#supplier-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const leadDays = $("#supplier-lead-days").value;
    const body = { name: $("#supplier-name").value.trim(), legal_name: $("#supplier-legal-name").value.trim(), rfc: $("#supplier-rfc").value.trim(), email: $("#supplier-email").value.trim(), phone: $("#supplier-phone").value.trim(), lead_time_days: leadDays === "" ? null : Number(leadDays), is_active: true };
    const editId = event.currentTarget.dataset.edit;
    try { await apiRequest(editId ? `purchasing/suppliers/${editId}/` : "purchasing/suppliers/", { method: editId ? "PATCH" : "POST", body }); await syncFromApi(); closeSupplierModal(); toast(editId ? "Proveedor actualizado." : "Proveedor guardado."); } catch (error) { toast(error.message); }
  });

  const closeSupplierProductModal = () => $("#supplier-product-modal").classList.remove("open");
  $("#new-supplier-product").addEventListener("click", () => openSupplierProduct());
  $("#close-supplier-product").addEventListener("click", closeSupplierProductModal);
  $("#cancel-supplier-product").addEventListener("click", closeSupplierProductModal);
  $("#supplier-product-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget, editId = form.dataset.edit;
    const minimum = $("#supplier-product-minimum").value, lead = $("#supplier-product-lead").value;
    const historyReason = editId ? window.prompt("Motivo del cambio (mínimo 10 caracteres):") : "";
    if (editId && historyReason === null) return;
    const body = { supplier: $("#supplier-product-supplier").value, product: $("#supplier-product-product").value, supplier_reference: $("#supplier-product-reference").value.trim(), unit_cost: Number($("#supplier-product-cost").value).toFixed(2), minimum_order_quantity: minimum ? Number(minimum).toFixed(3) : null, lead_time_days: lead === "" ? null : Number(lead), last_verified_on: $("#supplier-product-verified").value || null, is_active: true, ...(editId ? { history_reason: historyReason.trim() } : {}) };
    try { await apiRequest(editId ? `purchasing/supplier-products/${editId}/` : "purchasing/supplier-products/", { method: editId ? "PATCH" : "POST", body }); await syncFromApi(); closeSupplierProductModal(); toast(editId ? "Condición actualizada." : "Condición guardada."); }
    catch (error) { toast(error.message); }
  });

  const closePurchaseOrderModal = () => $("#purchase-order-modal").classList.remove("open");
  $("#po-supplier").addEventListener("change", () => { [...$("#purchase-lines").querySelectorAll(".line-item")].forEach((row) => { row.dataset.costManual = "false"; applySupplierProductTerm(row); }); updateExpectedDateFromSupplier(); });
  $("#po-order-date").addEventListener("change", updateExpectedDateFromSupplier);
  $("#po-expected-date").addEventListener("input", () => { $("#purchase-order-form").dataset.expectedManual = "true"; });
  $("#new-purchase-order").addEventListener("click", openPurchaseOrder);
  $("#close-purchase-order").addEventListener("click", closePurchaseOrderModal);
  $("#cancel-purchase-order").addEventListener("click", closePurchaseOrderModal);
  $("#add-purchase-line").addEventListener("click", addPurchaseLine);
  $("#purchase-order-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const lineInputs = [...$("#purchase-lines").querySelectorAll(".line-item")].map((row) => ({ product: row.querySelector(".po-product").value, expected_location: row.querySelector(".po-location").value, quantity: Number(row.querySelector(".po-quantity").value).toFixed(3), unit_cost: Number(row.querySelector(".po-cost").value).toFixed(2), description: "" }));
    if (!lineInputs.length || lineInputs.some((line) => !(Number(line.quantity) > 0) || !(Number(line.unit_cost) >= 0))) { toast("Completa producto, cantidad y costo de cada renglón."); return; }
    const body = { supplier: $("#po-supplier").value, order_date: $("#po-order-date").value, expected_date: $("#po-expected-date").value || null, notes: $("#po-notes").value.trim(), line_inputs: lineInputs };
    const form = $("#purchase-order-form"), editId = form.dataset.edit;
    try { await apiRequest(editId ? `purchasing/orders/${editId}/` : "purchasing/orders/", { method: editId ? "PATCH" : "POST", body }); await syncFromApi(); closePurchaseOrderModal(); toast(editId ? "Borrador actualizado." : "Borrador de compra guardado."); } catch (error) { toast(error.message); }
  });

  const closePurchaseReceiptModal = () => $("#purchase-receive-modal").classList.remove("open");
  $("#close-purchase-receive").addEventListener("click", closePurchaseReceiptModal);
  $("#cancel-purchase-receive").addEventListener("click", closePurchaseReceiptModal);
  $("#receipt-product-scan").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); scanPurchaseReceiptProduct(); }
  });
  $("#purchase-receive-lines").addEventListener("input", (event) => {
    if (event.target.matches(".receipt-quantity")) event.target.closest("[data-receipt-line]").dataset.quantityEdited = "true";
  });
  $("#purchase-receive-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const lines = [...$("#purchase-receive-lines").querySelectorAll("[data-receipt-line]")].map((row) => ({ purchase_order_line: row.dataset.receiptLine, location: row.querySelector(".receipt-location").value, quantity: Number(row.querySelector(".receipt-quantity").value).toFixed(3), serial_numbers: (row.querySelector(".receipt-serials")?.value || "").split(/[\n,;]+/).map((value) => value.trim()).filter(Boolean) })).filter((line) => Number(line.quantity) > 0);
    if (!lines.length) { toast("Indica al menos una cantidad recibida."); return; }
    const orderId = $("#receipt-order-id").value;
    try { await apiRequest(`purchasing/orders/${orderId}/receive/`, { method: "POST", body: { idempotency_key: $("#receipt-idempotency-key").value, note: $("#receipt-note").value.trim(), lines } }); await syncFromApi(); closePurchaseReceiptModal(); toast("Recepción guardada y existencias actualizadas."); } catch (error) { toast(error.message); }
  });
  const closeSupplierBillModal = () => $("#supplier-bill-modal").classList.remove("open");
  $("#close-supplier-bill").addEventListener("click", closeSupplierBillModal);
  $("#cancel-supplier-bill").addEventListener("click", closeSupplierBillModal);
  $("#supplier-bill-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const lines = [...$("#supplier-bill-lines").querySelectorAll("[data-bill-line]")].map((row) => ({
      purchase_order_line: row.dataset.billLine,
      quantity: Number(row.querySelector(".bill-quantity").value || 0).toFixed(3),
      unit_cost: Number(row.querySelector(".bill-unit-cost").value || 0).toFixed(2),
      tax_amount: Number(row.querySelector(".bill-tax").value || 0).toFixed(2),
    })).filter((line) => Number(line.quantity) > 0);
    if (!lines.length) { toast("Captura al menos una cantidad facturada."); return; }
    const orderId = $("#supplier-bill-order-id").value;
    const body = { invoice_number: $("#supplier-bill-number").value.trim(), invoice_date: $("#supplier-bill-date").value, due_date: $("#supplier-bill-due-date").value || null, lines };
    try { await apiRequest(`purchasing/orders/${orderId}/register-bill/`, { method: "POST", body }); await syncFromApi(); closeSupplierBillModal(); toast("Factura del proveedor capturada para revisión."); } catch (error) { toast(error.message); }
  });
  const closeSupplierPaymentModal = () => $("#supplier-payment-modal").classList.remove("open");
  $("#close-supplier-payment").addEventListener("click", closeSupplierPaymentModal);
  $("#cancel-supplier-payment").addEventListener("click", closeSupplierPaymentModal);
  $("#supplier-payment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const billId = $("#supplier-payment-bill-id").value;
    const bill = live.purchasing.bills.find((item) => item.id === billId);
    const amount = Number($("#supplier-payment-amount").value);
    if (!bill || !(amount > 0) || amount > Number(bill.balance_due)) { toast("El importe debe ser mayor que cero y no superar el saldo pendiente."); return; }
    const existingPaymentId = $("#supplier-payment-id").value;
    try {
      let paymentId = existingPaymentId;
      const date = $("#supplier-payment-date").value;
      const paymentBody = {
          supplier: bill.supplier, amount: amount.toFixed(2), currency: "MXN", method: $("#supplier-payment-method").value,
          paid_at: new Date(`${date}T12:00:00`).toISOString(), reference: $("#supplier-payment-reference").value.trim(), memo: $("#supplier-payment-memo").value.trim(),
          applications: [{ bill: bill.id, amount: amount.toFixed(2) }],
      };
      if (!paymentId) { const payment = await apiRequest("purchasing/supplier-payments/", { method: "POST", body: paymentBody }); paymentId = payment.id; $("#supplier-payment-id").value = paymentId; }
      else await apiRequest(`purchasing/supplier-payments/${paymentId}/`, { method: "PATCH", body: paymentBody });
      await apiRequest(`purchasing/supplier-payments/${paymentId}/post/`, { method: "POST" });
      await syncFromApi(); closeSupplierPaymentModal(); toast("Pago aplicado a la factura del proveedor.");
    } catch (error) { await syncFromApi().catch(() => {}); toast(error.message); }
  });
  $("#purchase-search").addEventListener("input", renderPurchasing);
  $("#sourcing-add-line").addEventListener("click", () => {
    const product = $("#sourcing-product").value, quantity = Number($("#sourcing-quantity").value);
    if (!product || !Number.isFinite(quantity) || quantity <= 0) return toast("Selecciona un producto y una cantidad válida.");
    const existing = sourcingDraftLines.find((line) => String(line.product) === String(product));
    if (existing) existing.quantity = round2(Number(existing.quantity) + quantity); else sourcingDraftLines.push({ product, quantity });
    renderSourcing();
  });
  $("#sourcing-lines").addEventListener("click", (event) => {
    const button = event.target.closest("[data-sourcing-remove-line]"); if (!button) return;
    sourcingDraftLines.splice(Number(button.dataset.sourcingRemoveLine), 1); renderSourcing();
  });
  $("#sourcing-request-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!sourcingDraftLines.length) return toast("Agrega al menos un producto.");
    try {
      await apiRequest("purchasing/sourcing/", { method: "POST", body: { target_location: $("#sourcing-location").value, desired_date: $("#sourcing-date").value || null, notes: $("#sourcing-notes").value.trim(), lines: sourcingDraftLines } });
      sourcingDraftLines = []; $("#sourcing-date").value = ""; $("#sourcing-notes").value = ""; await connectSession(); toast("Solicitud creada; registra las propuestas que recibas.");
    } catch (error) { toast(`No se pudo crear la solicitud: ${error.message}`); }
  });
  const closeSourcingOffer = () => $("#sourcing-offer-modal").classList.remove("open");
  const closeSourcingRFQ = () => $("#sourcing-rfq-modal").classList.remove("open");
  const closeSourcingAward = () => $("#sourcing-award-modal").classList.remove("open");
  $("#close-sourcing-award").addEventListener("click", closeSourcingAward);
  $("#cancel-sourcing-award").addEventListener("click", closeSourcingAward);
  $("#close-sourcing-rfq").addEventListener("click", closeSourcingRFQ);
  $("#cancel-sourcing-rfq").addEventListener("click", closeSourcingRFQ);
  $("#sourcing-rfq-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const requestId = $("#sourcing-rfq-request").value;
    const supplierId = $("#sourcing-rfq-supplier").value;
    const supplier = live.purchasing.suppliers.find((item) => String(item.id) === String(supplierId));
    if (!supplier) return toast("Selecciona un proveedor activo.");
    if (!window.confirm(`Enviar la solicitud por correo a ${supplier.name} (${supplier.email})?`)) return;
    try {
      await apiRequest(`purchasing/sourcing/${requestId}/send-rfq/`, { method: "POST", body: { supplier: supplierId, confirm_send: true } });
      closeSourcingRFQ(); await connectSession(); toast("Solicitud enviada; el correo quedó registrado en el historial.");
    } catch (error) { toast(`No se pudo enviar la solicitud: ${error.message}`); }
  });
  $("#close-sourcing-offer").addEventListener("click", closeSourcingOffer);
  $("#cancel-sourcing-offer").addEventListener("click", closeSourcingOffer);
  $("#sourcing-list").addEventListener("click", (event) => {
    const sendRFQ = event.target.closest("[data-sourcing-rfq]");
    if (sendRFQ) {
      const request = live.purchasing.sourcing.find((item) => String(item.id) === String(sendRFQ.dataset.sourcingRfq)); if (!request) return;
      const offeredSupplierIds = new Set(request.offers.map((offer) => String(offer.supplier)));
      const suppliers = live.purchasing.suppliers.filter((supplier) => supplier.is_active && supplier.email && !offeredSupplierIds.has(String(supplier.id)));
      if (!suppliers.length) { toast("Agrega un proveedor activo con correo y sin oferta registrada para esta solicitud."); return; }
      $("#sourcing-rfq-request").value = request.id;
      $("#sourcing-rfq-supplier").innerHTML = suppliers.map((supplier) => `<option value="${escapeHtml(supplier.id)}">${escapeHtml(supplier.name)} · ${escapeHtml(supplier.email)}</option>`).join("");
      $("#sourcing-rfq-modal").classList.add("open"); return;
    }
    const add = event.target.closest("[data-sourcing-offer-add]");
    if (add) {
      const request = live.purchasing.sourcing.find((item) => String(item.id) === String(add.dataset.sourcingOfferAdd)); if (!request) return;
      $("#sourcing-offer-request").value = request.id;
      $("#sourcing-offer-supplier").innerHTML = live.purchasing.suppliers.filter((supplier) => supplier.is_active && !request.offers.some((offer) => String(offer.supplier) === String(supplier.id))).map((supplier) => `<option value="${escapeHtml(supplier.id)}">${escapeHtml(supplier.name)}</option>`).join("");
      $("#sourcing-offer-lines").innerHTML = request.lines.filter((line) => Number(line.remaining_quantity) > 0).map((line) => `<div class="form-row" style="align-items:end"><div class="field"><label>${escapeHtml(line.product_sku)} · ${escapeHtml(line.product_name)} · pendiente ${escapeHtml(line.remaining_quantity)} ${escapeHtml(line.product_unit)}</label><input type="number" min="0.001" max="${escapeHtml(line.remaining_quantity)}" step="0.001" data-offer-quantity="${escapeHtml(line.id)}" placeholder="Cantidad cotizada (opcional)"></div><div class="field"><label>Costo unitario antes de IVA (MXN)</label><input type="number" min="0" step="0.01" data-offer-unit-cost="${escapeHtml(line.id)}" placeholder="Costo unitario MXN (opcional)"></div></div>`).join("") || `<p class="empty">Esta solicitud ya no tiene cantidades pendientes.</p>`;
      $("#sourcing-offer-reference").value = ""; $("#sourcing-offer-valid").value = ""; $("#sourcing-offer-expected").value = ""; $("#sourcing-offer-notes").value = "";
      $("#sourcing-offer-modal").classList.add("open"); return;
    }
    const awardOpen = event.target.closest("[data-sourcing-award-open]");
    if (awardOpen) {
      const request = live.purchasing.sourcing.find((item) => String(item.id) === String(awardOpen.dataset.sourcingAwardOpen)); if (!request) return;
      const requestLines = new Map(request.lines.map((line) => [String(line.id), line]));
      const rows = (request.offers || []).filter((offer) => ["received", "partial"].includes(offer.state) && (!offer.valid_until || offer.valid_until >= todayISO())).flatMap((offer) => offer.lines.filter((line) => Number(line.available_quantity) > 0 && Number(requestLines.get(String(line.sourcing_line))?.remaining_quantity) > 0).map((line) => {
        const requested = requestLines.get(String(line.sourcing_line));
        const maxQty = Math.min(Number(line.available_quantity), Number(requested.remaining_quantity));
        const otherPrices = (request.offers || []).filter((candidate) => ["received", "partial"].includes(candidate.state) && (!candidate.valid_until || candidate.valid_until >= todayISO())).flatMap((candidate) => candidate.lines.filter((item) => String(item.sourcing_line) === String(line.sourcing_line) && Number(item.available_quantity) > 0).map((item) => Number(item.unit_cost)));
        const needsReason = otherPrices.length > 0 && Number(line.unit_cost) > Math.min(...otherPrices);
        return `<tr><td>${escapeHtml(line.product_sku)} · ${escapeHtml(line.product_name)}</td><td>${escapeHtml(offer.supplier_name)}<br><span class="muted">${escapeHtml(offer.supplier_reference || "Sin folio")}</span></td><td>${money(line.unit_cost)}</td><td>${escapeHtml(line.available_quantity)} ${escapeHtml(requested.product_unit)}</td><td>${escapeHtml(requested.remaining_quantity)} ${escapeHtml(requested.product_unit)}</td><td><input type="number" min="0.001" max="${escapeHtml(String(maxQty))}" step="0.001" placeholder="0" data-award-offer="${escapeHtml(offer.id)}" data-award-line="${escapeHtml(line.sourcing_line)}" data-award-needs-reason="${needsReason}"></td><td><input type="text" maxlength="300" data-award-reason placeholder="${needsReason ? "Requerida: mínimo 10 caracteres" : "Opcional"}"></td></tr>`;
      }));
      $("#sourcing-award-request").value = request.id;
      $("#sourcing-award-confirm").checked = false;
      $("#sourcing-award-lines").innerHTML = rows.length ? `<table><thead><tr><th>Producto</th><th>Proveedor</th><th>Precio unitario</th><th>Disponible en oferta</th><th>Pendiente</th><th>Cantidad a adjudicar</th><th>Motivo si el precio es mayor</th></tr></thead><tbody>${rows.join("")}</tbody></table>` : `<p class="empty">No hay cantidades pendientes cubiertas por ofertas vigentes.</p>`;
      $("#sourcing-award-modal").classList.add("open"); return;
    }
    const award = event.target.closest("[data-sourcing-award]"); if (!award) return;
    if (!confirm("La oferta elegida creará una orden de compra en borrador. Compras todavía deberá revisarla y confirmarla.")) return;
    apiRequest(`purchasing/sourcing/${award.dataset.sourcingAward}/award/`, { method: "POST", body: { offer: award.dataset.sourcingOffer } }).then(() => connectSession()).then(() => toast("Oferta elegida; se creó una orden en borrador.")).catch((error) => toast(`No se pudo elegir la oferta: ${error.message}`));
  });
  $("#sourcing-offer-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const quantities = Array.from($("#sourcing-offer-lines").querySelectorAll("[data-offer-quantity]"));
    const prices = Array.from($("#sourcing-offer-lines").querySelectorAll("[data-offer-unit-cost]"));
    const incomplete = prices.some((input) => Boolean(input.value) !== Boolean(quantities.find((item) => item.dataset.offerQuantity === input.dataset.offerUnitCost)?.value));
    if (incomplete) return toast("Captura cantidad y precio para cada producto que incluya esta oferta.");
    const lines = prices.filter((input) => Boolean(input.value)).map((input) => ({ sourcing_line: input.dataset.offerUnitCost, quantity: quantities.find((item) => item.dataset.offerQuantity === input.dataset.offerUnitCost).value, unit_cost: input.value }));
    if (!lines.length) return toast("Agrega al menos un producto cotizado.");
    try {
      await apiRequest(`purchasing/sourcing/${$("#sourcing-offer-request").value}/offers/`, { method: "POST", body: { supplier: $("#sourcing-offer-supplier").value, supplier_reference: $("#sourcing-offer-reference").value.trim(), quote_date: todayISO(), valid_until: $("#sourcing-offer-valid").value || null, expected_date: $("#sourcing-offer-expected").value || null, notes: $("#sourcing-offer-notes").value.trim(), lines } });
      closeSourcingOffer(); await connectSession(); toast("Cotización guardada para comparar.");
    } catch (error) { toast(`No se pudo guardar la cotización: ${error.message}`); }
  });
  $("#sourcing-award-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const selectedRows = Array.from($("#sourcing-award-lines").querySelectorAll("[data-award-offer]"))
      .filter((input) => input.value && Number(input.value) > 0);
    const allocations = selectedRows.map((input) => {
      const reason = input.closest("tr").querySelector("[data-award-reason]").value.trim();
      if (input.dataset.awardNeedsReason === "true" && reason.length < 10) return null;
      return { offer: input.dataset.awardOffer, sourcing_line: input.dataset.awardLine, quantity: input.value, reason };
    });
    if (allocations.some((allocation) => allocation === null)) return toast("Justifica con al menos 10 caracteres cada adjudicación a un precio mayor que otra oferta disponible.");
    if (!allocations.length) return toast("Indica al menos una cantidad que quieras adjudicar.");
    try {
      await apiRequest(`purchasing/sourcing/${$("#sourcing-award-request").value}/award-lines/`, { method: "POST", body: { allocations } });
      closeSourcingAward(); await connectSession(); toast("Adjudicación guardada; revisa las órdenes borrador por proveedor.");
    } catch (error) { toast(`No se pudieron adjudicar las cantidades: ${error.message}`); }
  });

  $("#export-ledger").addEventListener("click", () => {
    const rows = [["Fecha", "Folio", "Cliente", "Concepto", "Importe", "Estado"]];
    if (backend.connected) {
      live.invoices.forEach((invoice) => rows.push([invoice.issue_date, invoice.number, invoice.customer_name, "Factura interna", Number(invoice.total).toFixed(2), apiStateLabel(invoice.state)]));
      live.payments.forEach((payment) => rows.push([payment.received_at, payment.number, payment.customer_name, "Cobro", Number(payment.amount).toFixed(2), payment.state]));
      live.entries.forEach((entry) => rows.push([entry.entry_date, entry.number, entry.origin_type || entry.memo, entry.memo, Number(entry.debit_total).toFixed(2), entry.state]));
    }
    else db.quotes.forEach((quote) => rows.push([quote.date, quote.id, clientOf(quote.clientId).name, quote.title, calc(quote).total.toFixed(2), quote.status]));
    const csv = `\ufeff${rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\r\n")}`, anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" })); anchor.download = `redmagna-movimientos-${todayISO()}.csv`; anchor.click(); URL.revokeObjectURL(anchor.href);
  });
  $("#load-work-hours-report").addEventListener("click", loadWorkHoursReport);
  $("#export-work-hours-report").addEventListener("click", () => {
    const report = live.workHoursReport;
    if (!report) { toast("Consulta primero las horas del periodo."); return; }
    const rows = [["REDMAGNA · Horas registradas"], ["Desde", report.date_from, "Hasta", report.date_to], ["Total horas", report.totals.hours, "Registros", report.totals.entries], [], ["Resumen por servicio"], ["Folio", "Cliente", "Servicio", "Estado", "Horas", "Registros", "Personas"]];
    report.by_work_order.forEach((item) => rows.push([item.number, item.customer_name, item.title, item.status, item.hours, item.entries, item.people]));
    rows.push([], ["Resumen por persona"], ["Persona", "Horas", "Registros", "Servicios"]);
    report.by_person.forEach((item) => rows.push([item.name, item.hours, item.entries, item.work_orders]));
    downloadSafeCsv(`redmagna-horas-servicio-${report.date_from}-${report.date_to}.csv`, rows);
  });
  $("#load-trial-balance").addEventListener("click", loadTrialBalance);
  $("#load-subledger-reconciliation").addEventListener("click", loadSubledgerReconciliation);
  $("#preview-open-items").addEventListener("click", previewOpenItems);
  $("#prepare-opening-batch").addEventListener("click", prepareOpeningBalanceBatch);
  $("#refresh-opening-batches").addEventListener("click", loadOpeningBalanceBatches);
  $("#download-open-items-template").addEventListener("click", () => downloadSafeCsv("plantilla-partidas-abiertas.csv", [["tipo", "rfc", "folio_externo", "sistema_origen", "fecha_emision", "fecha_vencimiento", "moneda", "total_original", "pagado_previo", "saldo_abierto"]]));
  ["#recon-as-of", "#recon-ar-account", "#recon-ap-account", "#open-items-file"].forEach((selector) => $(selector).addEventListener("change", () => { live.openItemsPreview = null; renderOpenItemsPreview(); }));
  $("#export-subledger-reconciliation").addEventListener("click", () => {
    const report = live.subledgerReconciliation;
    if (!report) return;
    downloadSafeCsv(`conciliacion-auxiliares-${report.as_of}.csv`, [
      ["Auxiliar", "Cuenta", "Nombre de cuenta", "Saldo de mayor", "Saldo auxiliar", "Diferencia", "Estado"],
      ...report.reconciliations.map((item) => [item.key === "receivables" ? "CxC" : "CxP", item.account_code, item.account_name, item.control_balance, item.subledger_balance, item.difference, item.reconciled ? "Cuadrado" : "Revisar"]),
    ]);
  });
  $("#export-trial-balance").addEventListener("click", () => {
    const report = live.trialBalance;
    if (!report) { toast("Consulta primero la balanza del periodo."); return; }
    const rows = [["Código", "Cuenta", "Categoría", "Saldo inicial debe", "Saldo inicial haber", "Debe del periodo", "Haber del periodo", "Saldo final debe", "Saldo final haber"]];
    report.accounts.forEach((account) => rows.push([account.code, account.name, account.category, account.opening_debit, account.opening_credit, account.period_debit, account.period_credit, account.closing_debit, account.closing_credit]));
    rows.push(["", "Totales", "", report.totals.opening_debit, report.totals.opening_credit, report.totals.period_debit, report.totals.period_credit, report.totals.closing_debit, report.totals.closing_credit]);
    downloadSafeCsv(`redmagna-balanza-${report.date_from || "inicio"}-${report.date_to || todayISO()}.csv`, rows);
  });
  $("#export-general-ledger").addEventListener("click", () => {
    const report = live.generalLedger;
    if (!report) { toast("Consulta primero una cuenta del libro mayor."); return; }
    const rows = [["Cuenta", report.account.code, report.account.name], ["Desde", report.date_from || "Inicio"], ["Hasta", report.date_to || ""], [], ["Fecha", "Póliza", "Diario", "Concepto", "Referencia", "Debe", "Haber", "Saldo debe", "Saldo haber"]];
    report.transactions.forEach((item) => rows.push([item.entry_date, item.entry_number, `${item.journal_code} · ${item.journal_name}`, item.description || item.memo, item.reversal_of ? `Reversa de ${item.reversal_of}` : item.origin_type, item.debit, item.credit, item.balance_debit, item.balance_credit]));
    rows.push(["", "", "", "Totales del periodo / cierre", "", report.period_debit, report.period_credit, report.closing_debit, report.closing_credit]);
    downloadSafeCsv(`redmagna-mayor-${report.account.code}-${report.date_from || "inicio"}-${report.date_to || todayISO()}.csv`, rows);
  });
  $("#export-financial-statements").addEventListener("click", () => {
    const report = live.financialStatements;
    if (!report) { toast("Consulta primero los estados financieros del periodo."); return; }
    const result = report.income_statement, balance = report.balance_sheet;
    const rows = [["Estado", "Código", "Cuenta", "Importe"], ["Resultados · Ingresos"]];
    result.income_accounts.forEach((account) => rows.push(["Resultados · Ingreso", account.code, account.name, account.amount]));
    rows.push(["Resultados", "", "Total ingresos", result.total_income], ["Resultados · Gastos"]);
    result.expense_accounts.forEach((account) => rows.push(["Resultados · Gasto", account.code, account.name, account.amount]));
    rows.push(["Resultados", "", "Total gastos", result.total_expenses], ["Resultados", "", "Resultado neto", result.net_income], ["Balance general · Activos"]);
    balance.assets.forEach((account) => rows.push(["Balance · Activo", account.code, account.name, account.amount]));
    rows.push(["Balance", "", "Total activos", balance.total_assets], ["Balance general · Pasivos"]);
    balance.liabilities.forEach((account) => rows.push(["Balance · Pasivo", account.code, account.name, account.amount]));
    rows.push(["Balance", "", "Total pasivos", balance.total_liabilities], ["Balance general · Capital"]);
    balance.equity.forEach((account) => rows.push(["Balance · Capital", account.code, account.name, account.amount]));
    rows.push(["Balance", "", "Total capital", balance.total_equity], ["Balance", "", "Resultado acumulado sin cierre", balance.unclosed_result], ["Balance", "", "Pasivo + capital + resultado", balance.liabilities_and_equity], ["Balance", "", "Diferencia", balance.difference]);
    downloadSafeCsv(`redmagna-estados-financieros-${report.date_from}-${report.date_to}.csv`, rows);
  });
  $("#load-fiscal-sales-register").addEventListener("click", loadIssuedCfdiRegister);
  $("#export-fiscal-sales-register").addEventListener("click", () => {
    const report = live.issuedCfdiRegister;
    if (!report?.rows?.length) { toast("Consulta un periodo con CFDI antes de exportar el registro."); return; }
    const rows = [["Fecha", "Tipo CFDI", "Folio ERP", "UUID", "UUID relacionado", "Estado", "RFC emisor", "RFC receptor", "Receptor", "Moneda", "Subtotal", "Impuestos por tasa", "Total"]];
    report.rows.forEach((row) => rows.push([row.issue_date, row.document_type, row.source_number, row.uuid, row.related_uuids.join(" | "), row.state_label, row.issuer_rfc, row.recipient_rfc, row.recipient_name, row.currency, row.subtotal, row.taxes.map((tax) => `${tax.tax_code} ${tax.rate}: base ${tax.base}, impuesto ${tax.amount}`).join(" | "), row.total]));
    const csv = `\ufeff${rows.map((row) => row.map((value) => { const raw = String(value); const safe = /^\s*[=+\-@]/.test(raw) ? `'${raw}` : raw; return `"${safe.replaceAll('"', '""')}"`; }).join(",")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `redmagna-registro-cfdi-emitidos-${todayISO()}.csv`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("#load-supplier-cfdi-register").addEventListener("click", loadSupplierCfdiRegister);
  $("#export-supplier-cfdi-register").addEventListener("click", () => {
    const report = live.purchasing.supplierCfdiRegister;
    if (!report?.rows?.length) { toast("Consulta un periodo con XML de proveedores antes de exportar el registro."); return; }
    const rows = [["Fecha", "Folio ERP", "Folio CFDI", "UUID", "Proveedor", "RFC emisor", "RFC receptor", "Moneda", "Subtotal", "Impuesto declarado", "Desglose por tasa", "Total", "Estado de cuenta por pagar", "Revisión"]];
    report.rows.forEach((row) => rows.push([row.invoice_date, row.invoice_number, row.cfdi_number, row.uuid, row.supplier_name, row.issuer_rfc, row.receiver_rfc, row.currency, row.subtotal, row.tax_total, row.taxes.map((tax) => `${tax.tax_code} ${tax.rate}: base ${tax.base}, impuesto ${tax.amount}`).join(" | "), row.total, row.payable_status, row.review_status]));
    const csv = `\ufeff${rows.map((row) => row.map((value) => { const raw = String(value); const safe = /^\s*[=+\-@]/.test(raw) ? `'${raw}` : raw; return `"${safe.replaceAll('"', '""')}"`; }).join(",")).join("\r\n")}`;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `redmagna-registro-cfdi-proveedores-${todayISO()}.csv`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  $("#load-general-ledger").addEventListener("click", loadTrialBalance);
  $("#opening-balance-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const file = $("#opening-balance-file").files[0];
      if (!file) throw new Error("Selecciona el archivo CSV de saldos.");
      if (file.size > 2 * 1024 * 1024) throw new Error("El CSV debe pesar menos de 2 MB.");
      const lines = parseOpeningBalancesCsv(await file.text());
      const entryDate = $("#opening-balance-date").value;
      if (!entryDate) throw new Error("Selecciona la fecha de apertura.");
      const entry = await apiRequest("accounting/entries/import-opening-balances/", { method: "POST", body: { journal: $("#opening-balance-journal").value, entry_date: entryDate, memo: `Saldos iniciales · ${entryDate}`, lines } });
      await syncFromApi();
      go("contabilidad");
      toast(`Póliza ${entry.number} preparada en borrador. Revísala y contabilízala cuando cuadre con el contador.`);
    } catch (error) { toast(error.message); }
  });
  $("#accounting-period-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await apiRequest("accounting/periods/", { method: "POST", body: { month: $("#accounting-period-month").value } });
      event.currentTarget.reset();
      await refreshAccountingPeriods();
      toast("Periodo mensual agregado.");
    } catch (error) { toast(error.message); }
  });
  $("#account-catalog-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!can("accounting.add_account")) return;
    const body = { code: $("#account-code").value.trim(), name: $("#account-name").value.trim(), category: $("#account-category").value, normal_balance: $("#account-balance").value, parent: $("#account-parent").value || null, allow_reconciliation: $("#account-reconcile").checked, is_active: true };
    try { await apiRequest("accounting/accounts/", { method: "POST", body }); event.currentTarget.reset(); await syncFromApi(); toast("Cuenta agregada al catálogo."); }
    catch (error) { toast(error.message); }
  });
  $("#journal-catalog-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!can("accounting.add_journal")) return;
    const body = { code: $("#journal-code").value.trim(), name: $("#journal-name").value.trim(), kind: $("#journal-kind").value, is_active: true };
    try { await apiRequest("accounting/journals/", { method: "POST", body }); event.currentTarget.reset(); await syncFromApi(); toast("Diario agregado al catálogo."); }
    catch (error) { toast(error.message); }
  });
  $("#bank-statement-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const file = $("#bank-file").files[0];
      if (!file) throw new Error("Selecciona un archivo CSV.");
      const lines = parseBankCsv(await file.text());
      const statement = await apiRequest("accounting/bank-statements/", { method: "POST", body: { account: $("#bank-account").value, period_start: $("#bank-period-start").value, period_end: $("#bank-period-end").value, opening_balance: Number($("#bank-opening").value).toFixed(2), closing_balance: Number($("#bank-closing").value).toFixed(2), lines } });
      live.selectedBankStatement = statement.id;
      event.currentTarget.reset();
      await refreshBankStatements();
      toast("Estado de cuenta importado. Revisa cada sugerencia antes de cerrar la conciliación.");
    } catch (error) { toast(error.message); }
  });
  $("#close-bank-match").addEventListener("click", () => $("#bank-match-modal").classList.remove("open"));
  $("#close-bank-adjustment").addEventListener("click", () => $("#bank-adjustment-modal").classList.remove("open"));
  $("#cancel-bank-adjustment").addEventListener("click", () => $("#bank-adjustment-modal").classList.remove("open"));
  $("#bank-adjustment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const statementId = event.currentTarget.dataset.statement;
    try {
      await apiRequest(`accounting/bank-statements/${statementId}/prepare-adjustment/`, { method: "POST", body: { line_id: $("#bank-adjustment-line-id").value, journal: $("#bank-adjustment-journal").value, counterpart_account: $("#bank-adjustment-account").value, memo: $("#bank-adjustment-memo").value.trim() } });
      $("#bank-adjustment-modal").classList.remove("open");
      await refreshBankStatements();
      toast("Se preparó la póliza borrador. Revísala y contabilízala; después vincúlala al movimiento.");
    } catch (error) { toast(error.message); }
  });
  $("#close-invoice-milestone").addEventListener("click", () => $("#invoice-milestone-modal").classList.remove("open"));
  $("#cancel-invoice-milestone").addEventListener("click", () => $("#invoice-milestone-modal").classList.remove("open"));
  $("#invoice-milestone-lines").addEventListener("input", updateWorkOrderInvoicePreview);
  $("#invoice-milestone-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const workOrderId = $("#invoice-milestone-order-id").value;
    try {
      const lines = Array.from(event.currentTarget.querySelectorAll("[data-invoice-quote-line]")).flatMap((input) => {
        const quantity = Number(input.value), maximum = Number(input.max);
        if (!Number.isFinite(quantity) || quantity < 0 || quantity > maximum) throw new Error("Revisa las cantidades: ninguna puede superar lo pendiente por facturar.");
        return quantity > 0 ? [{ quote_line: input.dataset.invoiceQuoteLine, quantity: quantity.toFixed(3) }] : [];
      });
      if (!lines.length) throw new Error("Indica una cantidad mayor que cero en al menos un concepto.");
      const invoice = await apiRequest(`work-orders/${workOrderId}/create-invoice/`, { method: "POST", body: { lines } });
      $("#invoice-milestone-modal").classList.remove("open");
      await syncFromApi(); go("facturacion");
      toast(`Borrador ${invoice.number} creado. Quedan por facturar las cantidades restantes.`);
    } catch (error) { toast(error.message); }
  });
  $("#bank-match-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const form = event.currentTarget;
      await apiRequest(`accounting/bank-statements/${form.dataset.statement}/match-line/`, { method: "POST", body: { line_id: form.dataset.lineId, journal_line: $("#bank-match-candidate").value } });
      $("#bank-match-modal").classList.remove("open");
      await refreshBankStatements();
      toast("Movimiento vinculado a la póliza.");
    } catch (error) { toast(error.message); }
  });
  document.addEventListener("click", async (event) => {
    const workMaterialsExport = event.target.closest("[data-export-work-materials]");
    if (workMaterialsExport) {
      if (!can("inventory.view_stockmovement")) { toast("No tienes permiso para consultar movimientos de inventario."); return; }
      const work = live.workOrders.find((item) => item.id === workMaterialsExport.dataset.exportWorkMaterials);
      if (!work) { toast("No se encontró la orden de trabajo."); return; }
      const movements = live.inventory.movements.filter((item) => item.work_order === work.id && ["issue", "return"].includes(item.kind)).sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
      const rows = [["REDMAGNA · Movimientos de materiales"], ["Folio", work.sales_order_number, "Servicio", work.title, "Cliente", work.customer_name], [], ["Fecha y hora", "Tipo", "SKU", "Producto", "Cantidad", "Unidad", "Ubicación", "Series", "Registró", "Referencia", "Nota"]];
      movements.forEach((item) => rows.push([item.created_at, item.kind === "issue" ? "Entrega a trabajo" : "Devolución de trabajo", item.product_sku, item.product_name, item.quantity, item.product_unit, item.location_code, (item.serial_numbers || []).join("; "), item.created_by_name, item.reference, item.note]));
      const folio = (work.sales_order_number || work.id).replace(/[^A-Za-z0-9_-]/g, "-");
      downloadSafeCsv(`redmagna-materiales-${folio}.csv`, rows);
      return;
    }
    const openingBatchExport = event.target.closest("[data-opening-batch-export]");
    if (openingBatchExport) { exportOpeningBalanceBatch(openingBatchExport.dataset.openingBatchExport); return; }
    const openingBatchRetry = event.target.closest("[data-opening-batch-detail-retry]");
    if (openingBatchRetry) {
      const details = openingBatchRetry.closest("[data-opening-batch-detail]");
      if (details) await loadOpeningBalanceBatchDetail(details);
      return;
    }
    const openingBatchSummary = event.target.closest("summary");
    const openingBatchDetails = openingBatchSummary?.closest("[data-opening-batch-detail]");
    if (openingBatchDetails) { await loadOpeningBalanceBatchDetail(openingBatchDetails); return; }
    const openingBatchReview = event.target.closest("[data-opening-batch-review]");
    if (openingBatchReview) { await reviewOpeningBalanceBatch(openingBatchReview.dataset.batchId, openingBatchReview.dataset.openingBatchReview); return; }
    const productEdit = event.target.closest("[data-product-edit]");
    if (productEdit) { openInventoryProduct(productEdit.dataset.productEdit); return; }
    const savePosting = event.target.closest("[data-posting-save]");
    if (savePosting) { await savePostingConfiguration(savePosting); return; }
    const closePeriod = event.target.closest("[data-period-close]");
    if (closePeriod) {
      const reason = prompt("Nota opcional para el cierre del periodo:") || "";
      try { await apiRequest(`accounting/periods/${closePeriod.dataset.periodClose}/close/`, { method: "POST", body: { reason } }); await refreshAccountingPeriods(); toast("Periodo cerrado; ya no se podrán contabilizar pólizas en esas fechas."); }
      catch (error) { toast(error.message); }
      return;
    }
    const reopenPeriod = event.target.closest("[data-period-reopen]");
    if (reopenPeriod) {
      const reason = prompt("Escribe el motivo de reapertura (mínimo 10 caracteres):");
      if (reason === null) return;
      try { await apiRequest(`accounting/periods/${reopenPeriod.dataset.periodReopen}/reopen/`, { method: "POST", body: { reason } }); await refreshAccountingPeriods(); toast("Periodo reabierto; el motivo quedó en la bitácora."); }
      catch (error) { toast(error.message); }
      return;
    }
    const statementButton = event.target.closest("[data-bank-statement]");
    if (statementButton) { live.selectedBankStatement = statementButton.dataset.bankStatement; renderBankReconciliation(); return; }
    const autoMatchButton = event.target.closest("#bank-auto-match");
    if (autoMatchButton) {
      const statementId = live.selectedBankStatement;
      if (!statementId || !window.confirm("El ERP vinculará solo movimientos con referencia bancaria igual al número de póliza, importe y cuenta exactos, fecha dentro de 3 días y coincidencia única. ¿Continuar?")) return;
      try {
        const result = await apiRequest(`accounting/bank-statements/${statementId}/auto-match-references/`, { method: "POST", body: {} });
        const index = live.bankStatements.findIndex((item) => item.id === statementId);
        if (index >= 0) live.bankStatements[index] = result.statement;
        renderBankReconciliation();
        toast(`${result.matched} referencia(s) vinculada(s); ${result.unmatched} movimiento(s) siguen pendientes.`);
      } catch (error) { toast(error.message); }
      return;
    }
    const adjustmentButton = event.target.closest("[data-bank-adjustment]");
    if (adjustmentButton) {
      const statementId = adjustmentButton.dataset.bankAdjustment, lineId = adjustmentButton.dataset.lineId;
      const statement = live.bankStatements.find((item) => item.id === statementId);
      const line = statement?.lines.find((item) => item.id === lineId);
      const parentIds = new Set((live.chartAccounts || []).filter((account) => account.parent).map((account) => account.parent));
      const accounts = (live.chartAccounts || []).filter((account) => account.is_active && !parentIds.has(account.id) && account.id !== statement?.account);
      const journals = (live.journals || []).filter((journal) => journal.is_active && ["general", "bank"].includes(journal.kind));
      if (!accounts.length) { toast("No hay cuentas activas de movimiento para clasificar este cargo o abono."); return; }
      if (!journals.length) { toast("Agrega un diario general o bancario activo antes de preparar el ajuste."); return; }
      $("#bank-adjustment-line-id").value = lineId;
      $("#bank-adjustment-form").dataset.statement = statementId;
      $("#bank-adjustment-summary").textContent = `${line?.transaction_date || ""} · ${line?.description || line?.reference || "Movimiento"} · ${money(line?.amount)}`;
      $("#bank-adjustment-journal").innerHTML = journals.map((journal) => `<option value="${escapeHtml(journal.id)}">${escapeHtml(journal.code)} · ${escapeHtml(journal.name)}</option>`).join("");
      const generalJournal = journals.find((journal) => journal.kind === "general");
      if (generalJournal) $("#bank-adjustment-journal").value = generalJournal.id;
      $("#bank-adjustment-account").innerHTML = `<option value="" selected disabled>Selecciona una cuenta de contrapartida</option>${accounts.map((account) => `<option value="${escapeHtml(account.id)}">${escapeHtml(account.code)} · ${escapeHtml(account.name)}</option>`).join("")}`;
      $("#bank-adjustment-memo").value = line?.description || line?.reference || "Ajuste bancario";
      $("#bank-adjustment-modal").classList.add("open");
      return;
    }
    const matchButton = event.target.closest("[data-bank-match]");
    if (matchButton) {
      try {
        const statementId = matchButton.dataset.bankMatch, lineId = matchButton.dataset.lineId;
        const response = await apiRequest(`accounting/bank-statements/${statementId}/candidate-lines/?line_id=${encodeURIComponent(lineId)}`);
        if (!response.candidates.length) { toast("No hay pólizas contabilizadas con esta cuenta e importe exactos."); return; }
        $("#bank-match-form").dataset.statement = statementId;
        $("#bank-match-form").dataset.lineId = lineId;
        const statement = live.bankStatements.find((item) => item.id === statementId), line = statement?.lines.find((item) => item.id === lineId);
        $("#bank-match-summary").textContent = `${line?.transaction_date || ""} · ${line?.description || line?.reference || "Movimiento"} · ${money(line?.amount)}`;
        $("#bank-match-candidate").innerHTML = response.candidates.map((candidate) => {
          const reasons = (candidate.match_reasons || []).join(" · ") || "Coincide cuenta e importe";
          return `<option value="${escapeHtml(candidate.id)}">${escapeHtml(candidate.entry_date)} · ${escapeHtml(candidate.entry_number)} · ${escapeHtml(candidate.journal_code)} · ${escapeHtml(candidate.entry_memo)} · ${money(candidate.signed_amount)} · ${escapeHtml(reasons)}</option>`;
        }).join("");
        $("#bank-match-modal").classList.add("open");
      } catch (error) { toast(error.message); }
      return;
    }
    const unmatchButton = event.target.closest("[data-bank-unmatch]");
    if (unmatchButton) {
      try { await apiRequest(`accounting/bank-statements/${unmatchButton.dataset.bankUnmatch}/unmatch-line/`, { method: "POST", body: { line_id: unmatchButton.dataset.lineId } }); await refreshBankStatements(); toast("Se quitó el vínculo; la póliza sigue contabilizada."); }
      catch (error) { toast(error.message); }
      return;
    }
    const reconcileButton = event.target.closest("[data-bank-reconcile]");
    if (reconcileButton) {
      try { await apiRequest(`accounting/bank-statements/${reconcileButton.dataset.bankReconcile}/reconcile/`, { method: "POST", body: {} }); await refreshBankStatements(); toast("Conciliación cerrada."); }
      catch (error) { toast(error.message); }
    }
  });
  document.addEventListener("change", async (event) => {
    const input = event.target.closest("[data-supplier-bill-cfdi-file]");
    if (!input?.files?.length) return;
    const file = input.files[0];
    try {
      if (file.size < 1 || file.size > 5 * 1024 * 1024) throw new Error("El XML debe pesar entre 1 byte y 5 MB.");
      const form = new FormData(); form.append("xml_file", file);
      await apiRequest(`purchasing/supplier-bills/${input.dataset.supplierBillCfdiFile}/attach-cfdi/`, { method: "POST", body: form });
      await syncFromApi(); toast("XML adjunto. La revisión local no consulta el estado del CFDI en el SAT.");
    } catch (error) { toast(error.message); }
    finally { input.value = ""; }
  });
  $("#load-receivables-aging").addEventListener("click", loadReceivablesAging);
  $("#export-receivables-aging").addEventListener("click", exportReceivablesAging);
  $("#receivables-aging-date").addEventListener("change", () => { live.receivablesAging = null; renderReceivablesAging(); });
  $("#load-customer-statement").addEventListener("click", loadCustomerStatement);
  $("#print-customer-statement").addEventListener("click", printCustomerStatement);
  $("#export-customer-statement").addEventListener("click", exportCustomerStatement);
  $("#customer-statement-date").addEventListener("change", () => { live.customerStatement = null; renderCustomerStatement(); });
  $("#customer-statement-customer").addEventListener("change", () => { live.customerStatement = null; renderCustomerStatement(); });
  $("#load-payables-aging").addEventListener("click", loadPayablesAging);
  $("#export-payables-aging").addEventListener("click", exportPayablesAging);
  $("#payables-aging-date").addEventListener("change", () => { live.purchasing.payablesAging = null; renderPayablesAging(); });
  $("#load-supplier-statement").addEventListener("click", loadSupplierStatement);
  $("#export-supplier-statement").addEventListener("click", exportSupplierStatement);
  $("#supplier-statement-date").addEventListener("change", () => { live.purchasing.supplierStatement = null; renderSupplierStatement(); });
  $("#supplier-statement-supplier").addEventListener("change", () => { live.purchasing.supplierStatement = null; renderSupplierStatement(); });

  document.addEventListener("keydown", (event) => { if (event.key === "Escape") ["quote-modal", "client-modal", "api-modal", "work-order-modal", "work-order-evidence-modal", "work-log-modal", "stock-movement-modal", "inventory-product-modal", "inventory-location-modal", "inventory-transfer-modal", "inventory-reorder-modal", "inventory-forecast-modal", "cfdi-preparation-modal", "supplier-modal", "supplier-product-modal", "purchase-order-modal", "framework-order-modal", "purchase-receive-modal", "supplier-bill-modal", "supplier-payment-modal", "bank-match-modal", "bank-adjustment-modal", "invoice-milestone-modal", "opportunity-convert-modal", "opportunity-activities-modal", "support-ticket-modal", "support-ticket-detail", "sourcing-offer-modal", "sourcing-rfq-modal", "expense-reimbursement-modal"].forEach((id) => $(`#${id}`).classList.remove("open")); });
  const initialDate = todayISO(); $("#trial-balance-from").value = `${initialDate.slice(0, 7)}-01`; $("#trial-balance-to").value = initialDate; $("#recon-as-of").value = initialDate; $("#work-hours-from").value = `${initialDate.slice(0, 7)}-01`; $("#work-hours-to").value = initialDate; $("#receivables-aging-date").value = initialDate; $("#customer-statement-date").value = initialDate; $("#payables-aging-date").value = initialDate; $("#supplier-statement-date").value = initialDate; $("#opening-balance-date").value = initialDate; $("#fiscal-register-from").value = `${initialDate.slice(0, 7)}-01`; $("#fiscal-register-to").value = initialDate; $("#supplier-cfdi-register-from").value = `${initialDate.slice(0, 7)}-01`; $("#supplier-cfdi-register-to").value = initialDate;
  $("#agenda-week").value = localDateISO(new Date());
  $("#agenda-week").addEventListener("change", renderWeeklyAgenda);
  $("#agenda-prev").addEventListener("click", () => { const week = mondayOfISO($("#agenda-week").value); week.setDate(week.getDate() - 7); $("#agenda-week").value = localDateISO(week); renderWeeklyAgenda(); });
  $("#agenda-next").addEventListener("click", () => { const week = mondayOfISO($("#agenda-week").value); week.setDate(week.getDate() + 7); $("#agenda-week").value = localDateISO(week); renderWeeklyAgenda(); });
  $("#agenda-today").addEventListener("click", () => { $("#agenda-week").value = localDateISO(new Date()); renderWeeklyAgenda(); });
  render();
  setInterval(renderOpportunityReminders, 60 * 1000);
  if (backend.token) { connectSession().catch(() => { backend.token = ""; backend.connected = false; backend.permissions = new Set(); sessionStorage.removeItem("redmagna-api-token"); updateConnectionState(); }); }
})();
