"""
Admin management page templates for Schema and Metric administration.
"""

from typing import Optional


def _admin_page_wrapper(title: str, body_html: str, api_base_url: str = "") -> str:
    """Wrap content in the standard Vanna admin page shell with Tailwind + brand styles.

    IMPORTANT: The API helper script (defining apiGet, showToast, etc.) MUST appear
    BEFORE the body_html's <script> tags, because page scripts call these helpers at
    load time (e.g. loadTables() in the schema page, init() in the metric page).
    The toast container must also exist in the DOM before any script calls showToast().
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} — Vanna Admin</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto+Slab:wght@400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    colors: {{
                        'easyq2sql-navy': '#023d60',
                        'easyq2sql-cream': '#e7e1cf',
                        'easyq2sql-teal': '#15a8a8',
                        'easyq2sql-orange': '#fe5d26',
                        'easyq2sql-magenta': '#bf1363',
                    }},
                    fontFamily: {{
                        'sans': ['Space Grotesk', 'ui-sans-serif', 'system-ui'],
                        'serif': ['Roboto Slab', 'ui-serif', 'Georgia'],
                        'mono': ['Space Mono', 'ui-monospace', 'monospace'],
                    }}
                }}
            }}
        }}
    </script>
    <style>
        body {{
            background: linear-gradient(to bottom, #e7e1cf, #ffffff, #e7e1cf);
            min-height: 100vh;
            position: relative;
            overflow-x: hidden;
        }}
        body::before {{
            content: '';
            position: fixed; inset: 0; pointer-events: none; z-index: 0;
            background:
                radial-gradient(circle at top left, rgba(21,168,168,0.10), transparent 60%),
                radial-gradient(circle at bottom right, rgba(254,93,38,0.06), transparent 65%);
        }}
        body > * {{ position: relative; z-index: 1; }}
        .toast {{ animation: slideIn 0.3s ease; }}
        @keyframes slideIn {{ from {{ transform: translateX(100%); opacity: 0; }} to {{ transform: translateX(0); opacity: 1; }} }}
    </style>
</head>
<body>
    <div class="max-w-7xl mx-auto p-5">
        <!-- Header -->
        <div class="flex items-center justify-between mb-6">
            <div>
                <h1 class="text-3xl font-bold text-easyq2sql-navy font-serif">{title}</h1>
                <p class="text-sm text-slate-500 font-mono mt-1">Vanna Admin Console</p>
            </div>
            <div class="flex gap-3">
                <a href="{api_base_url}/" class="px-4 py-2 bg-easyq2sql-navy text-white text-sm rounded-lg hover:bg-easyq2sql-teal transition font-medium">Chat</a>
                <a href="{api_base_url}/admin/schema" class="px-4 py-2 bg-easyq2sql-teal text-white text-sm rounded-lg hover:bg-easyq2sql-navy transition font-medium">Schema</a>
                <a href="{api_base_url}/admin/metrics" class="px-4 py-2 bg-easyq2sql-teal text-white text-sm rounded-lg hover:bg-easyq2sql-navy transition font-medium">Metrics</a>
            </div>
        </div>
        <!-- Toast container & API helpers MUST come before body_html scripts -->
        <div id="toastContainer" class="fixed top-5 right-5 z-50 space-y-2"></div>
        <script>
            const API = '{api_base_url}';
            function showToast(msg, type) {{
                const c = document.getElementById('toastContainer');
                const el = document.createElement('div');
                const bg = type === 'error' ? 'bg-red-500' : type === 'warn' ? 'bg-yellow-500' : 'bg-green-600';
                el.className = `toast ${{bg}} text-white px-5 py-3 rounded-lg shadow-lg text-sm font-medium`;
                el.textContent = msg;
                c.appendChild(el);
                setTimeout(() => el.remove(), 3500);
            }}
            async function apiGet(path) {{
                const r = await fetch(API + path);
                if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
                return r.json();
            }}
            async function apiPut(path, body) {{
                const r = await fetch(API + path, {{
                    method: 'PUT', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)
                }});
                if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
                return r.json();
            }}
            async function apiPost(path, body) {{
                const r = await fetch(API + path, {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)
                }});
                if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
                return r.json();
            }}
            async function apiDelete(path) {{
                const r = await fetch(API + path, {{ method: 'DELETE' }});
                if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
                return r.json();
            }}
        </script>
        {body_html}
    </div>
</body>
</html>"""


# =========================================================================
# Schema Management Page
# =========================================================================

def get_schema_admin_html(api_base_url: str = "") -> str:
    """Generate the Schema Management admin page."""
    body = """
    <div class="flex gap-5" style="min-height: calc(100vh - 180px);">
        <!-- Left: Table List -->
        <div class="w-64 flex-shrink-0 bg-white rounded-xl shadow border border-easyq2sql-teal/30 overflow-hidden flex flex-col">
            <div class="p-4 bg-easyq2sql-navy text-white font-semibold text-sm flex items-center justify-between">
                <span>Database Tables</span>
                <button onclick="loadTables()" class="text-xs bg-white/20 hover:bg-white/30 px-2 py-1 rounded transition" title="Refresh">&#x21bb;</button>
            </div>
            <div id="tableList" class="flex-1 overflow-y-auto p-2 space-y-1">
                <div class="text-sm text-slate-400 text-center py-8">Loading...</div>
            </div>
            <div class="p-3 border-t border-easyq2sql-teal/20">
                <button onclick="syncSchemas()" class="w-full py-2 bg-easyq2sql-orange text-white text-xs font-bold rounded hover:bg-easyq2sql-magenta transition">
                    &#x21bb; Re-sync from Database
                </button>
            </div>
        </div>

        <!-- Right: Table Detail -->
        <div class="flex-1 bg-white rounded-xl shadow border border-easyq2sql-teal/30 p-6 overflow-y-auto">
            <div id="tableDetail">
                <div class="text-center text-slate-400 py-20">
                    <div class="text-5xl mb-4">&#x1f4ca;</div>
                    <p class="text-lg font-medium">Select a table from the left panel</p>
                    <p class="text-sm mt-1">View and edit table metadata</p>
                </div>
            </div>
        </div>
    </div>
    <script>
        let currentTable = null;
        let allTables = [];

        async function loadTables() {
            const list = document.getElementById('tableList');
            list.innerHTML = '<div class="text-sm text-slate-400 text-center py-8">Loading...</div>';
            try {
                allTables = await apiGet('/api/easyq2sql/v1/schema/tables');
                if (!allTables.length) {
                    list.innerHTML = '<div class="text-sm text-slate-400 text-center py-8">No tables found. <button onclick="syncSchemas()" class="text-easyq2sql-teal underline hover:text-easyq2sql-navy">Sync now</button></div>';
                    return;
                }
                list.innerHTML = allTables.map(t => `
                    <div onclick="selectTable('${t.table_name}')"
                         class="px-3 py-2 rounded-lg cursor-pointer transition text-sm font-medium
                                hover:bg-easyq2sql-teal/10 text-slate-700 hover:text-easyq2sql-navy
                                flex items-center justify-between group"
                         id="tab-${t.table_name}">
                        <span class="truncate">${t.table_name}</span>
                        <span class="text-xs text-slate-300 group-hover:text-easyq2sql-teal">${t.columns ? t.columns.length : 0} cols</span>
                    </div>
                `).join('');
                if (currentTable) selectTable(currentTable);
            } catch(e) {
                list.innerHTML = '<div class="text-sm text-red-400 text-center py-8">Failed to load. <button onclick="loadTables()" class="text-easyq2sql-teal underline hover:text-easyq2sql-navy">Retry</button></div>';
                showToast('Failed to load tables: ' + e.message, 'error');
            }
        }

        function selectTable(name) {
            currentTable = name;
            document.querySelectorAll('#tableList > div').forEach(el => {
                if (el.id === 'tab-' + name) el.classList.add('bg-easyq2sql-teal/20', 'text-easyq2sql-navy', 'font-bold');
                else el.classList.remove('bg-easyq2sql-teal/20', 'text-easyq2sql-navy', 'font-bold');
            });
            const t = allTables.find(x => x.table_name === name);
            if (!t) return;
            renderTableDetail(t);
        }

        function renderTableDetail(t) {
            const fd = document.getElementById('tableDetail');
            const pkCols = t.columns.filter(c => c.is_primary_key).map(c => c.name);
            const fkCols = t.columns.filter(c => c.is_foreign_key);
            fd.innerHTML = `
                <div class="mb-6">
                    <div class="flex items-center gap-3 mb-2">
                        <h2 class="text-2xl font-bold text-easyq2sql-navy font-serif">${t.table_name}</h2>
                        ${t.schema_name ? `<span class="text-xs bg-easyq2sql-cream px-2 py-1 rounded font-mono text-easyq2sql-navy">${t.schema_name}</span>` : ''}
                        ${t.database_name ? `<span class="text-xs bg-easyq2sql-teal/10 px-2 py-1 rounded font-mono text-easyq2sql-teal">${t.database_name}</span>` : ''}
                    </div>
                    <div class="mb-3">
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Description</label>
                        <div class="flex gap-2">
                            <input id="descInput" type="text" value="${escHtml(t.description || '')}"
                                   placeholder="No description set..."
                                   class="flex-1 px-3 py-2 text-sm border border-easyq2sql-teal/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-easyq2sql-teal font-mono">
                            <button onclick="saveDescription('${t.table_name}')"
                                    class="px-4 py-2 bg-easyq2sql-teal text-white text-sm font-medium rounded-lg hover:bg-easyq2sql-navy transition whitespace-nowrap">
                                Save
                            </button>
                        </div>
                    </div>
                    ${pkCols.length ? `<div class="mb-3"><span class="text-xs font-bold text-slate-500 uppercase">Primary Keys:</span> <span class="text-sm font-mono text-easyq2sql-navy">${pkCols.join(', ')}</span></div>` : ''}
                    ${fkCols.length ? `<div class="mb-3"><span class="text-xs font-bold text-slate-500 uppercase">Foreign Keys:</span>` + fkCols.map(c => `<div class="text-sm font-mono text-easyq2sql-teal ml-2">&bull; ${c.name} &rarr; ${c.fk_reference_table}.${c.fk_reference_column}</div>`).join('') + '</div>' : ''}
                </div>
                <div>
                    <h3 class="text-lg font-semibold text-easyq2sql-navy mb-3 font-serif">Fields</h3>
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm">
                            <thead>
                                <tr class="border-b-2 border-easyq2sql-navy/20 text-left">
                                    <th class="py-2 px-3 font-bold text-easyq2sql-navy text-xs uppercase">Column</th>
                                    <th class="py-2 px-3 font-bold text-easyq2sql-navy text-xs uppercase">Type</th>
                                    <th class="py-2 px-3 font-bold text-easyq2sql-navy text-xs uppercase">Nullable</th>
                                    <th class="py-2 px-3 font-bold text-easyq2sql-navy text-xs uppercase">Keys</th>
                                    <th class="py-2 px-3 font-bold text-easyq2sql-navy text-xs uppercase">Comment</th>
                                    <th class="py-2 px-3 font-bold text-easyq2sql-navy text-xs uppercase w-20">Action</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${t.columns.map(c => `
                                    <tr class="border-b border-slate-100 hover:bg-easyq2sql-cream/30 transition">
                                        <td class="py-2 px-3 font-mono font-medium text-easyq2sql-navy">${c.name}</td>
                                        <td class="py-2 px-3 font-mono text-slate-600 text-xs">${c.data_type}</td>
                                        <td class="py-2 px-3 text-xs">${c.nullable ? '<span class="text-slate-400">YES</span>' : '<span class="text-easyq2sql-orange font-bold">NOT NULL</span>'}</td>
                                        <td class="py-2 px-3 text-xs">
                                            ${c.is_primary_key ? '<span class="bg-easyq2sql-navy text-white px-1.5 py-0.5 rounded text-xs font-bold mr-1">PK</span>' : ''}
                                            ${c.is_foreign_key ? '<span class="bg-easyq2sql-teal text-white px-1.5 py-0.5 rounded text-xs font-bold">FK</span>' : ''}
                                        </td>
                                        <td class="py-2 px-3">
                                            <input id="col-comment-${c.name}" type="text"
                                                   value="${escHtml(c.description || '')}"
                                                   placeholder="—"
                                                   class="w-full px-2 py-1 text-xs border border-slate-200 rounded focus:outline-none focus:ring-1 focus:ring-easyq2sql-teal font-mono">
                                        </td>
                                        <td class="py-2 px-3">
                                            <button onclick="saveColumnComment('${t.table_name}', '${c.name}')"
                                                    class="px-2 py-1 bg-easyq2sql-teal text-white text-xs rounded hover:bg-easyq2sql-navy transition">
                                                Save
                                            </button>
                                        </td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        async function saveDescription(tableName) {
            const val = document.getElementById('descInput').value;
            try {
                await apiPut('/api/easyq2sql/v1/schema/tables/' + encodeURIComponent(tableName) + '/description', {description: val});
                const t = allTables.find(x => x.table_name === tableName);
                if (t) t.description = val;
                showToast('Description updated', 'success');
            } catch(e) { showToast('Failed: ' + e.message, 'error'); }
        }

        async function saveColumnComment(tableName, colName) {
            const val = document.getElementById('col-comment-' + colName).value;
            try {
                await apiPut('/api/easyq2sql/v1/schema/tables/' + encodeURIComponent(tableName) + '/columns/' + encodeURIComponent(colName) + '/description', {description: val});
                const t = allTables.find(x => x.table_name === tableName);
                if (t) { const c = t.columns.find(x => x.name === colName); if (c) c.description = val; }
                showToast('Column comment updated', 'success');
            } catch(e) { showToast('Failed: ' + e.message, 'error'); }
        }

        async function syncSchemas() {
            if (!confirm('Re-extract DDL from database? This will replace all schema entries.')) return;
            try {
                const r = await apiPost('/api/easyq2sql/v1/schema/sync');
                showToast('Schema synced: ' + r.tables_synced + ' tables', 'success');
                await loadTables();
            } catch(e) { showToast('Sync failed: ' + e.message, 'error'); }
        }

        function escHtml(s) { return (s == null ? '' : String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

        loadTables();
    </script>"""
    return _admin_page_wrapper("Schema Management", body, api_base_url)


# =========================================================================
# Metric Management Page
# =========================================================================

def get_metric_admin_html(api_base_url: str = "") -> str:
    """Generate the Metric Management admin page."""
    body = """
    <div class="flex gap-5" style="min-height: calc(100vh - 180px);">
        <!-- Left: Metric List -->
        <div class="w-80 flex-shrink-0 bg-white rounded-xl shadow border border-easyq2sql-teal/30 overflow-hidden flex flex-col">
            <div class="p-4 bg-easyq2sql-navy text-white font-semibold text-sm flex items-center justify-between">
                <span>Defined Metrics</span>
                <button onclick="loadMetrics()" class="text-xs bg-white/20 hover:bg-white/30 px-2 py-1 rounded transition" title="Refresh">&#x21bb;</button>
            </div>
            <div id="metricList" class="flex-1 overflow-y-auto p-2 space-y-1">
                <div class="text-sm text-slate-400 text-center py-8">Loading...</div>
            </div>
            <div class="p-3 border-t border-easyq2sql-teal/20">
                <button onclick="showCreateForm()" class="w-full py-2 bg-easyq2sql-teal text-white text-sm font-bold rounded hover:bg-easyq2sql-navy transition">
                    + New Metric
                </button>
            </div>
        </div>

        <!-- Right: Metric Form / Detail -->
        <div class="flex-1 bg-white rounded-xl shadow border border-easyq2sql-teal/30 p-6 overflow-y-auto">
            <div id="metricDetail">
                <div class="text-center text-slate-400 py-20">
                    <div class="text-5xl mb-4">&#x1f4c8;</div>
                    <p class="text-lg font-medium">Select a metric or create a new one</p>
                </div>
            </div>
        </div>
    </div>

    <script>
        let allMetrics = [];
        let allTables = [];
        let editingId = null;
        let columnCache = {};

        // -- Helpers --
        function escHtml(s) { return (s == null ? '' : String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

        /** Split "table.column" into {table, column}. */
        function parseFieldRef(ref) {
            if (!ref || !ref.includes('.')) return {table: '', column: ''};
            const dot = ref.indexOf('.');
            return {table: ref.substring(0, dot), column: ref.substring(dot + 1)};
        }

        /** Build a <select> of all tables. Returns a placeholder message when no tables are synced. */
        function tableSelectHtml(selectedTable, cssClass, onChangeFn, idx, extraArgs) {
            if (!allTables.length) {
                return `<span class="text-xs text-easyq2sql-orange italic">No tables synced — <a href="${API}/admin/schema" class="underline hover:text-easyq2sql-navy">run Schema sync first</a></span>`;
            }
            const args = extraArgs ? [idx].concat(extraArgs).join(', ') : String(idx);
            return `<select onchange="${onChangeFn}(${args})" class="${cssClass} px-2 py-1.5 text-xs border border-easyq2sql-teal/30 rounded font-mono" data-idx="${idx}">
                <option value="">— table —</option>
                ${allTables.map(t => `<option value="${t.table_name}" ${selectedTable === t.table_name ? 'selected' : ''}>${t.table_name}${t.description ? ' — ' + escHtml(t.description) : ''}</option>`).join('')}
            </select>`;
        }
        async function getColumns(tableName) {
            if (!tableName) return [];
            if (columnCache[tableName]) return columnCache[tableName];
            try {
                const t = await apiGet('/api/easyq2sql/v1/schema/tables/' + encodeURIComponent(tableName));
                columnCache[tableName] = (t && t.columns) ? t.columns : [];
                return columnCache[tableName];
            } catch(e) { return []; }
        }

        /** Populate a <select> element with column options for a given table. */
        async function populateColumnSelect(sel, tableName, preselectedColumn, tableLabel) {
            sel.innerHTML = '<option value="">— column —</option>';
            if (!tableName) return;
            const cols = await getColumns(tableName);
            const tbl = tableLabel || tableName;
            sel.innerHTML += cols.map(c =>
                `<option value="${tbl}.${c.name}" ${preselectedColumn === c.name ? 'selected' : ''}>${c.name} (${c.data_type})${c.description ? ' — ' + escHtml(c.description) : ''}</option>`
            ).join('');
        }

        // -- Init --
        async function init() {
            await loadTablesForForm();
            await loadMetrics();
        }

        async function loadTablesForForm() {
            try { allTables = await apiGet('/api/easyq2sql/v1/schema/tables'); } catch(e) { allTables = []; showToast('Failed to load tables: ' + e.message, 'error'); }
        }

        async function loadMetrics() {
            const list = document.getElementById('metricList');
            list.innerHTML = '<div class="text-sm text-slate-400 text-center py-8">Loading...</div>';
            try {
                allMetrics = await apiGet('/api/easyq2sql/v1/metrics');
                if (!allMetrics.length) {
                    list.innerHTML = '<div class="text-sm text-slate-400 text-center py-8">No metrics defined</div>';
                    return;
                }
                list.innerHTML = allMetrics.map(m => `
                    <div onclick="selectMetric('${m.id}')"
                         class="px-3 py-2 rounded-lg cursor-pointer transition text-sm hover:bg-easyq2sql-teal/10 group"
                         id="metric-${m.id}">
                        <div class="font-semibold text-easyq2sql-navy group-hover:text-easyq2sql-teal">${escHtml(m.name)}</div>
                        <div class="text-xs text-slate-400 font-mono mt-0.5 truncate">${m.analysis_table}.${m.analysis_field.split('.').pop()}</div>
                        <div class="flex items-center gap-1.5 mt-1 flex-wrap">
                            ${m.dimensions && m.dimensions.length ? `<span class="text-xs text-slate-500 bg-slate-100 px-1.5 py-0.5 rounded" title="${m.dimensions.map(d => d.name + ' (' + d.field_ref + ')' + (d.joins && d.joins.length ? ' [Joins: ' + d.joins.map(j => j.source_table + '.' + j.source_column + '=' + j.target_table + '.' + j.target_column).join(', ') + ']' : '')).join('; ')}">📐 ${m.dimensions.length} dim${m.dimensions.length > 1 ? 's' : ''}</span>` : ''}
                        </div>
                    </div>
                `).join('');
                if (editingId) selectMetric(editingId);
            } catch(e) {
                list.innerHTML = '<div class="text-sm text-red-400 text-center py-8">Failed to load. <button onclick="loadMetrics()" class="text-easyq2sql-teal underline hover:text-easyq2sql-navy">Retry</button></div>';
                showToast('Failed to load metrics: ' + e.message, 'error');
            }
        }

        function selectMetric(id) {
            editingId = id;
            document.querySelectorAll('#metricList > div').forEach(el => el.classList.remove('bg-easyq2sql-teal/20'));
            const el = document.getElementById('metric-' + id);
            if (el) el.classList.add('bg-easyq2sql-teal/20');
            const m = allMetrics.find(x => x.id === id);
            if (m) renderMetricForm(m, false);
        }

        function showCreateForm() {
            editingId = null;
            document.querySelectorAll('#metricList > div').forEach(el => el.classList.remove('bg-easyq2sql-teal/20'));
            renderMetricForm({
                name: '', description: '', analysis_table: '', analysis_field: '',
                dimensions: [], function_steps: []
            }, true);
        }

        function renderMetricForm(m, isNew) {
            const fd = document.getElementById('metricDetail');
            const dims = m.dimensions || [];

            fd.innerHTML = `
                <div class="flex items-center justify-between mb-5">
                    <h2 class="text-2xl font-bold text-easyq2sql-navy font-serif">${isNew ? 'Create Metric' : escHtml(m.name)}</h2>
                    ${!isNew ? `<button onclick="deleteMetric('${m.id}')" class="px-3 py-1.5 bg-red-500 text-white text-xs rounded hover:bg-red-700 transition">Delete</button>` : ''}
                </div>

                ${!allTables.length ? `<div class="mb-4 p-3 bg-easyq2sql-orange/10 border border-easyq2sql-orange/30 rounded-lg text-sm text-easyq2sql-orange">
                    <strong>&#x26a0; No tables available.</strong> Tables and columns cannot be selected until schemas are synced.
                    <a href="${API}/admin/schema" class="underline font-bold hover:text-easyq2sql-magenta ml-1">Go to Schema Admin &rarr;</a>
                </div>` : ''}

                <!-- Basic Info -->
                <div class="grid grid-cols-2 gap-4 mb-6">
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Metric Name *</label>
                        <input id="m-name" value="${escHtml(m.name || '')}" placeholder="e.g. Sign Rate"
                               class="w-full px-3 py-2 text-sm border border-easyq2sql-teal/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-easyq2sql-teal font-mono">
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Description</label>
                        <input id="m-desc" value="${escHtml(m.description || '')}" placeholder="What this metric measures"
                               class="w-full px-3 py-2 text-sm border border-easyq2sql-teal/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-easyq2sql-teal font-mono">
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Analysis Table *</label>
                        <select id="m-table" onchange="onTableChange()"
                                class="w-full px-3 py-2 text-sm border border-easyq2sql-teal/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-easyq2sql-teal font-mono">
                            <option value="">— Select —</option>
                            ${allTables.map(t => `<option value="${t.table_name}" ${m.analysis_table === t.table_name ? 'selected' : ''}>${t.table_name}${t.description ? ' — ' + escHtml(t.description) : ''}</option>`).join('')}
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-bold text-slate-500 uppercase mb-1">Analysis Field *</label>
                        <select id="m-field"
                                class="w-full px-3 py-2 text-sm border border-easyq2sql-teal/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-easyq2sql-teal font-mono">
                            <option value="">— Select table first —</option>
                        </select>
                    </div>
                </div>

                <!-- Dimensions -->
                <div class="mb-6">
                    <div class="flex items-center justify-between mb-3">
                        <h3 class="text-lg font-semibold text-easyq2sql-navy font-serif">Dimensions</h3>
                        <button onclick="addDimension()" class="px-3 py-1 bg-easyq2sql-navy text-white text-xs rounded hover:bg-easyq2sql-teal transition">+ Add Dimension</button>
                    </div>
                    <div id="dimensionsContainer" class="space-y-2">
                        ${dims.map((d, i) => renderDimRow(d, i)).join('')}
                    </div>
                    <div id="noDimsMsg" class="text-sm text-slate-400 py-3 ${dims.length ? 'hidden' : ''}">No dimensions defined.</div>
                </div>

                <!-- Actions -->
                <div class="flex gap-3 pt-4 border-t border-slate-200">
                    <button onclick="saveMetric('${isNew ? 'create' : 'update'}')"
                            class="px-6 py-2.5 bg-easyq2sql-teal text-white font-bold rounded-lg hover:bg-easyq2sql-navy transition text-sm">
                        ${isNew ? 'Create Metric' : 'Update Metric'}
                    </button>
                    <button onclick="showCreateForm(); document.getElementById('metricDetail').innerHTML='<div class=\\'text-center text-slate-400 py-20\\'><div class=\\'text-5xl mb-4\\'>&#x1f4c8;</div><p class=\\'text-lg font-medium\\'>Select a metric or create a new one</p></div>'; editingId=null;"
                            class="px-4 py-2.5 text-slate-500 text-sm rounded-lg hover:bg-slate-100 transition">
                        Cancel
                    </button>
                </div>
            `;
            // Populate analysis field dropdown & step/dim pre-selections
            if (m.analysis_table) onTableChange(m.analysis_field);
            // Pre-populate dim field dropdowns
            dims.forEach((d, i) => {
                const ref = parseFieldRef(d.field_ref || '');
                if (ref.table) onDimFieldTableChange(i, ref.table, ref.column);
            });
            // Pre-populate join column dropdowns inside each dimension
            dims.forEach((d, i) => {
                (d.joins || []).forEach((j, ji) => {
                    if (j.source_table) onJoinSourceTableChange(i, ji, j.source_table, j.source_column);
                    if (j.target_table) onJoinTargetTableChange(i, ji, j.target_table, j.target_column);
                });
            });
        }

        // -- Row renderers --

        function renderDimRow(d, i) {
            const ref = parseFieldRef(d.field_ref || '');
            const tableSel = tableSelectHtml(ref.table, 'dim-tbl', 'onDimFieldTableChange', i);
            const joins = d.joins || [];
            const joinHtml = joins.map((j, ji) => renderJoinRow(j, i, ji)).join('');
            return `<div class="bg-easyq2sql-cream/30 p-2 rounded-lg" id="dim-${i}">
                <div class="flex items-center gap-2">
                    <input value="${escHtml(d.name || '')}" placeholder="Dimension name"
                           class="dim-name px-2 py-1.5 text-xs border border-easyq2sql-teal/30 rounded font-mono" data-idx="${i}" style="width:160px">
                    ${tableSel}
                    <span class="text-xs text-slate-400">.</span>
                    <select class="dim-col px-2 py-1.5 text-xs border border-easyq2sql-teal/30 rounded font-mono flex-1" data-idx="${i}">
                        <option value="">— column —</option>
                    </select>
                    <button onclick="document.getElementById('dim-${i}').remove(); updateNoDimMsg();" class="text-red-400 hover:text-red-600 text-lg leading-none">&times;</button>
                </div>
                <div class="dim-joins ml-4 mt-1 space-y-1" id="dim-${i}-joins">${joinHtml}</div>
                <button onclick="addDimJoin(${i})" class="ml-4 mt-1 text-xs text-easyq2sql-teal hover:text-easyq2sql-navy underline">+ Add Join</button>
            </div>`;
        }

        function renderJoinRow(j, dimIdx, joinIdx) {
            const id = `dim-${dimIdx}-join-${joinIdx}`;
            return `<div class="flex items-center gap-2 flex-wrap" id="${id}">
                ${tableSelectHtml(j.source_table || '', 'join-st', 'onJoinSourceTableChange', dimIdx, [joinIdx])}
                <span class="text-xs text-slate-400">.</span>
                <select class="join-sc px-2 py-1.5 text-xs border border-easyq2sql-teal/30 rounded font-mono w-28" data-dim="${dimIdx}" data-join="${joinIdx}">
                    <option value="">— column —</option>
                </select>
                <span class="text-xs text-slate-400 font-bold">=</span>
                ${tableSelectHtml(j.target_table || '', 'join-tt', 'onJoinTargetTableChange', dimIdx, [joinIdx])}
                <span class="text-xs text-slate-400">.</span>
                <select class="join-tc px-2 py-1.5 text-xs border border-easyq2sql-teal/30 rounded font-mono w-28" data-dim="${dimIdx}" data-join="${joinIdx}">
                    <option value="">— column —</option>
                </select>
                <select class="join-jt px-2 py-1.5 text-xs border border-easyq2sql-teal/30 rounded font-mono" data-dim="${dimIdx}" data-join="${joinIdx}">
                    <option value="LEFT JOIN" ${(j.join_type || 'LEFT JOIN') === 'LEFT JOIN' ? 'selected' : ''}>LEFT JOIN</option>
                    <option value="INNER JOIN" ${j.join_type === 'INNER JOIN' ? 'selected' : ''}>INNER JOIN</option>
                    <option value="RIGHT JOIN" ${j.join_type === 'RIGHT JOIN' ? 'selected' : ''}>RIGHT JOIN</option>
                </select>
                <button onclick="document.getElementById('${id}').remove();" class="text-red-400 hover:text-red-600 text-lg leading-none">&times;</button>
            </div>`;
        }
        function addDimJoin(dimIdx) {
            const container = document.getElementById(`dim-${dimIdx}-joins`);
            const count = container.querySelectorAll('div').length;
            container.insertAdjacentHTML('beforeend', renderJoinRow({source_table:'',source_column:'',target_table:'',target_column:'',join_type:'LEFT JOIN'}, dimIdx, count));
        }

        // -- Collectors --

        function collectDimensions() {
            const rows = document.querySelectorAll('#dimensionsContainer > div');
            return Array.from(rows).map(row => {
                const dimIdx = row.id.replace('dim-', '');
                const joinRows = document.querySelectorAll(`#dim-${dimIdx}-joins > div`);
                return {
                    name: row.querySelector('.dim-name').value,
                    field_ref: row.querySelector('.dim-col').value,
                    joins: Array.from(joinRows).map(jr => ({
                        source_table: jr.querySelector('.join-st').value,
                        source_column: jr.querySelector('.join-sc').value.split('.').pop(),
                        target_table: jr.querySelector('.join-tt').value,
                        target_column: jr.querySelector('.join-tc').value.split('.').pop(),
                        join_type: jr.querySelector('.join-jt').value
                    }))
                };
            });
        }
        // -- Adders --

        function addDimension() {
            const i = document.querySelectorAll('#dimensionsContainer > div').length;
            document.getElementById('dimensionsContainer').insertAdjacentHTML('beforeend', renderDimRow({name:'',field_ref:'', joins:[]}, i));
            updateNoDimMsg();
        }
        function updateNoDimMsg() { document.getElementById('noDimsMsg').classList.toggle('hidden', document.querySelectorAll('#dimensionsContainer > div').length > 0); }

        // -- Event handlers --

        async function onDimFieldTableChange(idx, preselectedTable, preselectedCol) {
            const row = document.getElementById('dim-' + idx);
            if (!row) return;
            const tbl = preselectedTable || row.querySelector('.dim-tbl').value;
            const colSel = row.querySelector('.dim-col');
            await populateColumnSelect(colSel, tbl, preselectedCol || '', tbl);
        }

        async function onJoinSourceTableChange(dimIdx, joinIdx, preselectedTable, preselectedCol) {
            const row = document.getElementById('dim-' + dimIdx + '-join-' + joinIdx);
            if (!row) return;
            const tbl = preselectedTable || row.querySelector('.join-st').value;
            const colSel = row.querySelector('.join-sc');
            await populateColumnSelect(colSel, tbl, preselectedCol || '', tbl);
        }

        async function onJoinTargetTableChange(dimIdx, joinIdx, preselectedTable, preselectedCol) {
            const row = document.getElementById('dim-' + dimIdx + '-join-' + joinIdx);
            if (!row) return;
            const tbl = preselectedTable || row.querySelector('.join-tt').value;
            const colSel = row.querySelector('.join-tc');
            await populateColumnSelect(colSel, tbl, preselectedCol || '', tbl);
        }

        async function onTableChange(preselectedField) {
            const tableName = document.getElementById('m-table').value;
            const fieldSel = document.getElementById('m-field');
            fieldSel.innerHTML = '<option value="">— Select —</option>';
            if (!tableName) return;
            const cols = await getColumns(tableName);
            fieldSel.innerHTML += cols.map(c =>
                `<option value="${tableName}.${c.name}" ${preselectedField === tableName + '.' + c.name ? 'selected' : ''}>${c.name} (${c.data_type})${c.description ? ' — ' + escHtml(c.description) : ''}</option>`
            ).join('');
        }

        // -- Save / Delete --

        async function saveMetric(mode) {
            const name = document.getElementById('m-name').value.trim();
            if (!name) { showToast('Metric name is required', 'error'); return; }
            const analysisTable = document.getElementById('m-table').value;
            const analysisField = document.getElementById('m-field').value;
            if (!analysisTable || !analysisField) { showToast('Analysis table and field are required', 'error'); return; }

            const body = {
                name,
                description: document.getElementById('m-desc').value.trim() || null,
                analysis_table: analysisTable,
                analysis_field: analysisField,
                dimensions: collectDimensions(),
            };

            try {
                if (mode === 'create') {
                    const r = await apiPost('/api/easyq2sql/v1/metrics', body);
                    showToast('Metric created: ' + r.name, 'success');
                } else {
                    await apiPut('/api/easyq2sql/v1/metrics/' + encodeURIComponent(editingId), body);
                    showToast('Metric updated', 'success');
                }
                await loadMetrics();
                editingId = mode === 'create' ? null : editingId;
                if (mode === 'create') showCreateForm();
            } catch(e) { showToast('Failed: ' + e.message, 'error'); }
        }

        async function deleteMetric(id) {
            if (!confirm('Delete this metric?')) return;
            try {
                await apiDelete('/api/easyq2sql/v1/metrics/' + encodeURIComponent(id));
                showToast('Metric deleted', 'success');
                editingId = null;
                document.getElementById('metricDetail').innerHTML = '<div class="text-center text-slate-400 py-20"><div class="text-5xl mb-4">&#x1f4c8;</div><p class="text-lg font-medium">Select a metric or create a new one</p></div>';
                await loadMetrics();
            } catch(e) { showToast('Failed: ' + e.message, 'error'); }
        }

        init();
    </script>"""
    return _admin_page_wrapper("Metric Management", body, api_base_url)
