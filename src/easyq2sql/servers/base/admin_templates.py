"""
Admin management page templates for Schema and Metric administration.
"""

#: Ordered nav items: (key, path, label). The active page's link is rendered dark.
_NAV_ITEMS = [
    ("chat", "/", "Chat"),
    ("schema", "/admin/schema", "Schema"),
    ("atomic-metrics", "/admin/atomic-metrics", "AtomicMetric"),
    ("derived-metrics", "/admin/derived-metrics", "DerivedMetric"),
    ("composite-metrics", "/admin/composite-metrics", "CompositeMetric"),
    ("metric-graph", "/admin/metric-graph", "Metric Graph"),
]


def _nav_html(active: str, api_base_url: str) -> str:
    """Render the top nav links, highlighting ``active`` with the dark navy color."""
    links = []
    for key, path, label in _NAV_ITEMS:
        bg = "bg-easyq2sql-navy" if key == active else "bg-easyq2sql-teal"
        hover = "hover:bg-easyq2sql-teal" if key == active else "hover:bg-easyq2sql-navy"
        links.append(
            f'<a href="{api_base_url}{path}" class="px-4 py-2 {bg} text-white text-sm rounded-lg {hover} transition font-medium">{label}</a>'
        )
    return "\n                ".join(links)


def _admin_page_wrapper(title: str, body_html: str, api_base_url: str = "", active: str = "chat") -> str:
    """Wrap content in the standard admin page shell with Tailwind + brand styles.

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
    <title>{title} — EasyQ2Sql Admin</title>
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
                <p class="text-sm text-slate-500 font-mono mt-1">EasyQ2Sql Admin Console</p>
            </div>
            <div class="flex gap-3">
                {_nav_html(active, api_base_url)}
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
                if (!r.ok) {{ const d = await r.json().catch(()=>null); throw new Error((d && d.detail) || r.statusText || ('HTTP ' + r.status)); }}
                return r.json();
            }}
            async function apiPut(path, body) {{
                const r = await fetch(API + path, {{
                    method: 'PUT', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)
                }});
                if (!r.ok) {{ const d = await r.json().catch(()=>null); throw new Error((d && d.detail) || r.statusText || ('HTTP ' + r.status)); }}
                return r.json();
            }}
            async function apiPost(path, body) {{
                const r = await fetch(API + path, {{
                    method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)
                }});
                if (!r.ok) {{ const d = await r.json().catch(()=>null); throw new Error((d && d.detail) || r.statusText || ('HTTP ' + r.status)); }}
                return r.json();
            }}
            async function apiDelete(path) {{
                const r = await fetch(API + path, {{ method: 'DELETE' }});
                if (!r.ok) {{ const d = await r.json().catch(()=>null); throw new Error((d && d.detail) || r.statusText || ('HTTP ' + r.status)); }}
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
    return _admin_page_wrapper("Schema Management", body, api_base_url, active="schema")


# =========================================================================
# Metric Management Page
# =========================================================================

def get_metric_admin_html(api_base_url: str = "") -> str:
    """Generate the standalone Atomic Metric Management admin page."""
    body = """
    <style>
        .stat-card { transition: box-shadow .2s; }
        .stat-card:hover { box-shadow: 0 6px 16px rgba(0,0,0,.08); }
        .tag { display:inline-flex; align-items:center; padding:1px 8px; border-radius:3px; font-size:12px; line-height:20px; }
        .tag-blue { background:#e6f4ff; color:#1677ff; border:1px solid #bae0ff; }
        .tag-gray { background:#f5f5f5; color:#8c8c8c; border:1px solid #d9d9d9; }
        .tag-orange { background:#fff7e6; color:#fa8c16; border:1px solid #ffd591; }
        .modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:1000; display:flex; align-items:flex-start; justify-content:center; padding-top:40px; }
        .toast-msg { position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:2000; padding:10px 24px; border-radius:8px; font-size:14px; box-shadow:0 4px 12px rgba(0,0,0,.15); }
    </style>
    <!-- Stats Row -->
    <div class="grid grid-cols-4 gap-4 mb-5">
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center text-2xl">📊</div><div><div class="text-2xl font-bold text-gray-900" id="statTotal">0</div><div class="text-xs text-gray-500">Configured Metrics</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-green-50 text-green-500 flex items-center justify-center text-2xl">🗄️</div><div><div class="text-2xl font-bold text-gray-900" id="statTables">0</div><div class="text-xs text-gray-500">Source Tables</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center text-2xl">🔢</div><div><div class="text-2xl font-bold text-gray-900" id="statCalcs">0</div><div class="text-xs text-gray-500">Calculation Types</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-red-50 text-red-500 flex items-center justify-center text-2xl">⚠️</div><div><div class="text-2xl font-bold text-gray-900" id="statNoBiz">0</div><div class="text-xs text-gray-500">Incomplete Metrics</div></div></div>
    </div>
    <!-- Toolbar -->
    <div class="bg-white rounded-lg p-4 border border-gray-200 flex items-center gap-3 flex-wrap mb-5">
        <input id="searchInput" placeholder="🔍 Search metric name / definition..." oninput="renderTable()" class="w-72 h-9 px-3 text-sm border border-gray-300 rounded-md focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal outline-none">
        <button onclick="resetFilters()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:text-easyq2sql-teal hover:border-easyq2sql-teal transition bg-white">↻ Reset</button>
        <button onclick="batchDeleteMetrics()" class="h-9 px-4 text-sm border border-easyq2sql-orange text-easyq2sql-orange rounded-md hover:bg-easyq2sql-orange hover:text-white transition bg-white font-medium">🗑 Batch Delete</button>
        <div class="flex-1"></div>
        <button onclick="openCreateModal()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">+ New Metric</button>
        <button onclick="syncGraph(this)" class="h-9 px-4 text-sm border border-easyq2sql-navy text-easyq2sql-navy rounded-md hover:bg-easyq2sql-navy hover:text-white transition bg-white font-medium">🔗 Sync to Neo4j</button>
    </div>
    <!-- Table -->
    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 text-sm font-semibold text-gray-900 flex justify-between"><span>Metric List</span><span class="text-xs font-normal text-gray-500">Total <b id="totalCount">0</b></span></div>
        <div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="bg-gray-50 text-left text-xs text-gray-500 uppercase"><th class="py-3 px-4 w-10"><input type="checkbox" id="selAll" onchange="selAllMetrics(this.checked)" title="Select all"></th><th class="py-3 px-4">Metric Name</th><th class="py-3 px-4 w-36">Calculation</th><th class="py-3 px-4">Analysis Field</th><th class="py-3 px-4">Business Definition</th><th class="py-3 px-4 w-36">Updated</th><th class="py-3 px-4 w-28">Actions</th></tr></thead><tbody id="tableBody"></tbody></table></div>
        <div class="px-5 py-3 border-t border-gray-200 text-xs text-gray-500 flex justify-between"><span id="pageInfo"></span></div>
    </div>
    <!-- Modal -->
    <div class="modal-overlay" id="metricModal" style="display:none" onclick="if(event.target===this)closeModal()">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-lg max-h-[85vh] flex flex-col">
            <div class="px-6 py-4 border-b border-gray-200 text-base font-semibold flex items-center justify-between"><span id="modalTitle">New Metric</span><button onclick="closeModal()" class="text-gray-400 hover:text-gray-800 text-xl leading-none">&times;</button></div>
            <div class="p-6 overflow-y-auto flex-1 space-y-4">
                <input type="hidden" id="editId">
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Metric Name <span class="text-red-500">*</span></label><input id="m-name" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="e.g. order count"></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Business Definition</label><textarea id="m-bizdef" rows="2" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="Business meaning, e.g. total number of valid orders"></textarea></div>
                <div class="grid grid-cols-2 gap-4">
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">Calculation</label><select id="m-calc" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">None (direct value)</option><option>COUNT</option><option>COUNT(DISTINCT)</option><option>SUM</option><option>AVG</option><option>MAX</option><option>MIN</option></select></div>
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">Source Table <span class="text-red-500">*</span></label><select id="m-table" onchange="onTableChange()" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">Select a table</option></select></div>
                </div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Analysis Field <span class="text-red-500">*</span></label><select id="m-field" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">Select a table first</option></select><p class="text-xs text-gray-400 mt-1">Format: table.column, e.g. ods_order.order_id</p></div>
            </div>
            <div class="px-6 py-3 border-t border-gray-200 flex justify-end gap-2"><button onclick="closeModal()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:bg-gray-100 bg-white">Cancel</button><button onclick="saveMetric()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">✓ Save</button></div>
        </div>
    </div>
    <!-- Toast -->
    <div class="toast-msg hidden" id="toast"></div>
    <script>
        let allAtomicMetrics=[],allTables=[],editingId=null,columnCache={},selMetrics=new Set(),visibleMetricIds=[];
        function esc(s){return(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
        function t(txt,ms,color){const e=document.getElementById('toast');e.textContent=txt;e.className='toast-msg '+color;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',ms||2000);}
        async function syncGraph(btn){if(btn){btn.disabled=true;btn.textContent='⏳ Syncing...';}try{const r=await apiPost('/api/easyq2sql/v1/metric-graph/sync',{});t('Graph synced: '+r.nodes+' nodes, '+r.edges+' edges ✓','','bg-green-600 text-white');}catch(e){t('Sync failed: '+e.message,'','bg-red-500 text-white');}if(btn){btn.disabled=false;btn.textContent='🔗 Sync to Neo4j';}}
        async function getCols(tn){if(!tn)return[];if(columnCache[tn])return columnCache[tn];try{const t=await apiGet('/api/easyq2sql/v1/schema/tables/'+encodeURIComponent(tn));columnCache[tn]=(t&&t.columns)?t.columns:[];return columnCache[tn];}catch(e){return[];}}
        async function popCol(sel,tn,preselected){sel.innerHTML='<option value="">-- Select field --</option>';if(!tn)return;const cols=await getCols(tn);sel.innerHTML+=cols.map(c=>`<option value="${tn}.${c.name}" ${preselected===tn+'.'+c.name?'selected':''}>${c.name}${c.description?' -- '+esc(c.description):''}</option>`).join('');}
        function popTableOpts(sel,preselected){const o=allTables.map(t=>`<option value="${t.table_name}" ${preselected===t.table_name?'selected':''}>${t.table_name}${t.description?' - '+esc(t.description):''}</option>`).join('');sel.innerHTML='<option value="">Select a table</option>'+o;}
        async function init(){try{allTables=await apiGet('/api/easyq2sql/v1/schema/tables');}catch(e){allTables=[];}await loadMetrics();}
        async function loadMetrics(){try{allAtomicMetrics=await apiGet('/api/easyq2sql/v1/atomic-metrics');}catch(e){allAtomicMetrics=[];}renderTable();}
        function calcTag(c){if(!c)return '<span class="text-gray-400">—</span>';return '<span class="tag tag-blue">'+esc(c)+'</span>';}
        function getFiltered(){const s=document.getElementById('searchInput').value.toLowerCase();return allAtomicMetrics.filter(m=>!s||m.name.toLowerCase().includes(s)||(m.business_definition||'').toLowerCase().includes(s)||m.id.toLowerCase().includes(s));}
        function renderTable(){const data=getFiltered();visibleMetricIds=data.map(m=>m.id);const tb=document.getElementById('tableBody');document.getElementById('totalCount').textContent=data.length;document.getElementById('pageInfo').textContent='Showing '+data.length;document.getElementById('statTotal').textContent=allAtomicMetrics.length;document.getElementById('statTables').textContent=new Set(allAtomicMetrics.map(m=>m.data_source).filter(Boolean)).size;document.getElementById('statCalcs').textContent=new Set(allAtomicMetrics.map(m=>m.calculation_logic).filter(Boolean)).size;document.getElementById('statNoBiz').textContent=allAtomicMetrics.filter(m=>!m.business_definition).length;const sa=document.getElementById('selAll');const selN=visibleMetricIds.filter(id=>selMetrics.has(id)).length;sa.checked=visibleMetricIds.length>0&&selN===visibleMetricIds.length;sa.indeterminate=selN>0&&selN<visibleMetricIds.length;if(!data.length){tb.innerHTML='<tr><td colspan="7" class="text-center py-10 text-gray-400">📊 No metrics yet</td></tr>';return;}tb.innerHTML=data.map(m=>{const tv=m.updated_at||m.created_at||'';const ck=selMetrics.has(m.id)?' checked':'';return '<tr class="border-b border-gray-100 hover:bg-blue-50/30 transition"><td class="py-3 px-4 w-10"><input type="checkbox"'+ck+' onchange="onMetricSel(\\''+m.id+'\\',this.checked)"></td><td class="py-3 px-4 font-medium text-gray-900">'+esc(m.name)+' <span class="text-xs text-gray-400">'+esc(m.id)+'</span></td><td class="py-3 px-4">'+calcTag(m.calculation_logic)+'</td><td class="py-3 px-4 font-mono text-xs text-gray-600">'+esc(m.analysis_field||'-')+'</td><td class="py-3 px-4 max-w-[200px] truncate text-xs" title="'+esc(m.business_definition||'')+'">'+esc(m.business_definition||'-')+'</td><td class="py-3 px-4 text-xs text-gray-500">'+esc(typeof tv==='string'?tv.substring(0,16):'')+'</td><td class="py-3 px-4 whitespace-nowrap"><button onclick="editMetric(\\''+m.id+'\\')" class="text-easyq2sql-teal hover:text-easyq2sql-navy text-xs mr-2">Edit</button><button onclick="deleteMetric(\\''+m.id+'\\')" class="text-red-500 hover:text-red-700 text-xs">Delete</button></td></tr>';}).join('');}
        function resetFilters(){document.getElementById('searchInput').value='';renderTable();}
        async function onTableChange(pf){const tn=document.getElementById('m-table').value;await popCol(document.getElementById('m-field'),tn,pf||'');}
        function openCreateModal(){editingId=null;document.getElementById('modalTitle').textContent='New Metric';document.getElementById('editId').value='';document.getElementById('m-name').value='';document.getElementById('m-bizdef').value='';document.getElementById('m-calc').value='';document.getElementById('m-table').value='';document.getElementById('m-field').innerHTML='<option value="">Select a table first</option>';popTableOpts(document.getElementById('m-table'));document.getElementById('metricModal').style.display='flex';}
        function editMetric(id){const m=allAtomicMetrics.find(x=>x.id===id);if(!m)return;editingId=id;document.getElementById('modalTitle').textContent='Edit Metric';document.getElementById('editId').value=m.id;document.getElementById('m-name').value=m.name;document.getElementById('m-bizdef').value=m.business_definition||'';document.getElementById('m-calc').value=m.calculation_logic||'';document.getElementById('m-table').value=m.data_source||'';popTableOpts(document.getElementById('m-table'),m.data_source);onTableChange(m.analysis_field);document.getElementById('metricModal').style.display='flex';}
        function closeModal(){document.getElementById('metricModal').style.display='none';}
        document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
        async function saveMetric(){const name=document.getElementById('m-name').value.trim();const bizDef=document.getElementById('m-bizdef').value.trim();const calc=document.getElementById('m-calc').value;const ds=document.getElementById('m-table').value;const field=document.getElementById('m-field').value;if(!name||!ds||!field){t('Please fill all required fields','','bg-red-500 text-white');return;}const body={name,business_definition:bizDef||null,calculation_logic:calc||null,data_source:ds,analysis_field:field,description:null};try{if(editingId){await apiPut('/api/easyq2sql/v1/atomic-metrics/'+encodeURIComponent(editingId),body);t('Metric updated ✓','','bg-green-600 text-white');}else{await apiPost('/api/easyq2sql/v1/atomic-metrics',body);t('Metric created ✓','','bg-green-600 text-white');}closeModal();await loadMetrics();}catch(e){t('Save failed: '+e.message,'','bg-red-500 text-white');}}
        async function deleteMetric(id){const m=allAtomicMetrics.find(x=>x.id===id);if(!confirm('Delete metric "'+(m?m.name:id)+'"?'))return;try{await apiDelete('/api/easyq2sql/v1/atomic-metrics/'+encodeURIComponent(id));t('Deleted','','bg-green-600 text-white');await loadMetrics();}catch(e){t('Delete failed: '+e.message,'','bg-red-500 text-white');}}
        function onMetricSel(id,ck){if(ck)selMetrics.add(id);else selMetrics.delete(id);renderTable();}
        function selAllMetrics(ck){visibleMetricIds.forEach(id=>{if(ck)selMetrics.add(id);else selMetrics.delete(id);});renderTable();}
        async function batchDeleteMetrics(){if(!selMetrics.size){t('Select metrics to delete first','','bg-orange-500 text-white');return;}const ids=[...selMetrics];if(!confirm('Delete the '+ids.length+' selected metrics?'))return;let ok=0,fail=0;for(const id of ids){try{await apiDelete('/api/easyq2sql/v1/atomic-metrics/'+encodeURIComponent(id));selMetrics.delete(id);ok++;}catch(e){fail++;}}t('Deleted '+ok+(fail?('; '+fail+' failed'):''),'','bg-green-600 text-white');await loadMetrics();}
        init();
    </script>"""
    return _admin_page_wrapper("AtomicMetric Management", body, api_base_url, active="atomic-metrics")

# =========================================================================
# Dimension Management Page
# =========================================================================

def get_dimension_admin_html(api_base_url: str = "") -> str:
    """Generate the Dimension Management admin page."""
    body = """
    <style>
        .stat-card { transition: box-shadow .2s; }
        .stat-card:hover { box-shadow: 0 6px 16px rgba(0,0,0,.08); }
        .dim-tag { display:inline-flex; align-items:center; gap:4px; padding:2px 10px; border-radius:4px; font-size:12px; line-height:22px; background:#fafafa; border:1px solid #f0f0f0; color:#595959; cursor:pointer; transition:all .15s; white-space:nowrap; }
        .dim-tag:hover { background:#e6f4ff; border-color:#bae0ff; color:#1677ff; }
        .dim-tag input[type=checkbox] { margin:0; width:13px; height:13px; cursor:pointer; vertical-align:middle; }
        .dim-tag.has-join { border-style:dashed; }
        .dim-tag-overflow { display:inline-flex; align-items:center; padding:2px 10px; border-radius:4px; font-size:12px; line-height:22px; background:#e6f4ff; border:1px solid #bae0ff; color:#1677ff; cursor:pointer; font-weight:500; }
        .tag-blue { background:#e6f4ff; color:#1677ff; border:1px solid #bae0ff; }
        .tag-green { background:#f6ffed; color:#52c41a; border:1px solid #b7eb8f; }
        .tag-gray { background:#f5f5f5; color:#8c8c8c; border:1px solid #d9d9d9; }
        .tag { display:inline-flex; align-items:center; padding:1px 8px; border-radius:3px; font-size:12px; line-height:20px; }
        .modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:1000; display:flex; align-items:flex-start; justify-content:center; padding-top:40px; }
        .toast-msg { position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:2000; padding:10px 24px; border-radius:8px; font-size:14px; box-shadow:0 4px 12px rgba(0,0,0,.15); }
        .join-row { display:grid; grid-template-columns:1fr 1fr 1fr 1fr 80px 32px; gap:6px; align-items:end; padding:8px 10px; background:#fafafa; border-radius:4px; border:1px solid #f0f0f0; margin-bottom:4px; }
    </style>
    <!-- Stats Row -->
    <div class="grid grid-cols-4 gap-4 mb-5">
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center text-2xl">📐</div><div><div class="text-2xl font-bold text-gray-900" id="statDimTotal">0</div><div class="text-xs text-gray-500">Total Dimensions</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-green-50 text-green-500 flex items-center justify-center text-2xl">🔗</div><div><div class="text-2xl font-bold text-gray-900" id="statMetricLinked">0</div><div class="text-xs text-gray-500">Linked Metrics</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center text-2xl">🌳</div><div><div class="text-2xl font-bold text-gray-900" id="statHier">0</div><div class="text-xs text-gray-500">With Definition</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-red-50 text-red-500 flex items-center justify-center text-2xl">⚠️</div><div><div class="text-2xl font-bold text-gray-900" id="statNoJoin">0</div><div class="text-xs text-gray-500">JOIN Missing</div></div></div>
    </div>
    <!-- Toolbar -->
    <div class="bg-white rounded-lg p-4 border border-gray-200 flex items-center gap-3 flex-wrap mb-5">
        <input id="searchInput" placeholder="🔍 Search metric / dimension name..." oninput="renderTable()" class="w-72 h-9 px-3 text-sm border border-gray-300 rounded-md focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal outline-none">
        <button onclick="resetFilters()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:text-easyq2sql-teal hover:border-easyq2sql-teal transition bg-white">↻ Reset</button>
        <div class="flex-1"></div>
        <button id="batchDeleteBtn" onclick="batchDelete()" class="hidden h-9 px-4 text-sm bg-red-500 text-white rounded-md hover:bg-red-600 transition font-medium">🗑 Batch Delete (<span id="batchDeleteCount">0</span>)</button>
        <button onclick="openCreateModal()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">+ New Dimension</button>
        <button onclick="syncGraph(this)" class="h-9 px-4 text-sm border border-easyq2sql-navy text-easyq2sql-navy rounded-md hover:bg-easyq2sql-navy hover:text-white transition bg-white font-medium">🔗 Sync to Neo4j</button>
    </div>
    <!-- Table -->
    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 text-sm font-semibold text-gray-900 flex justify-between"><span>Dimension List</span><span class="text-xs font-normal text-gray-500"><b id="totalMetricCount">0</b> metrics, <b id="totalDimCount">0</b> dimensions</span></div>
        <div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="bg-gray-50 text-left text-xs text-gray-500 uppercase"><th class="py-3 px-4 w-40">Linked Metric</th><th class="py-3 px-4">Linked Dimensions</th><th class="py-3 px-4 w-44">Updated</th><th class="py-3 px-4 w-32">Actions</th></tr></thead><tbody id="tableBody"></tbody></table></div>
        <div class="px-5 py-3 border-t border-gray-200 text-xs text-gray-500 flex justify-between"><span id="pageInfo"></span></div>
    </div>
    <!-- Modal -->
    <div class="modal-overlay" id="dimModal" style="display:none" onclick="if(event.target===this)closeModal()">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-2xl max-h-[90vh] flex flex-col">
            <div class="px-6 py-4 border-b border-gray-200 text-base font-semibold flex items-center justify-between"><span id="modalTitle">New Dimension</span><button onclick="closeModal()" class="text-gray-400 hover:text-gray-800 text-xl leading-none">&times;</button></div>
            <div class="p-6 overflow-y-auto flex-1 space-y-4">
                <input type="hidden" id="editId">
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Linked Metric <span class="text-red-500">*</span></label><select id="d-metric" onchange="onMetricChange()" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">Select a configured metric</option></select></div>
                <div class="grid grid-cols-2 gap-4">
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">Dimension Name <span class="text-red-500">*</span></label><input id="d-name" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="e.g. time"></div>

                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">Data Source Table <span class="text-red-500">*</span></label><select id="d-table" onchange="onDimTableChange()" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">Select dimension table</option></select></div>
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">Database Field <span class="text-red-500">*</span></label><select id="d-field" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">Select dimension table first</option></select></div>
                </div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Value Range <button onclick="autoFillRange()" class="ml-2 text-xs text-easyq2sql-teal hover:text-easyq2sql-navy border border-easyq2sql-teal rounded px-2 py-0.5 hover:bg-easyq2sql-teal hover:text-white transition" title="Auto-fetch distinct values for this field from the database (≤20)">⚡ Auto-generate</button></label><input id="d-range" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="e.g. 2020-01-01 ~ today"></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Business Definition</label><textarea id="d-bizdef" rows="2" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="Explain the business meaning of this dimension"></textarea></div>
                <!-- JOIN section -->
                <div><div class="flex items-center justify-between mb-2"><span class="text-xs font-medium text-gray-500">Table Join Relations (JOIN)</span><button onclick="addJoinRow()" class="text-xs text-easyq2sql-teal hover:text-easyq2sql-navy">+ Add JOIN Clause</button></div><div id="joinContainer"><div class="text-xs text-gray-400 py-1">No JOIN configured yet (not needed if the dimension table joins the fact table directly)</div></div></div>
            </div>
            <div class="px-6 py-3 border-t border-gray-200 flex justify-end gap-2"><button onclick="closeModal()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:bg-gray-100 bg-white">Cancel</button><button onclick="saveDim()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">✓ Save</button></div>
        </div>
    </div>
    <!-- Toast -->
    <div class="toast-msg hidden" id="toast"></div>
    <script>
        let allDerivedMetrics=[],allAtomicMetrics=[],allTables=[],editingId=null,columnCache={},tempJoins=[];
        const MAX_TAGS=4;
        function esc(s){return(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
        function t(txt,ms,color){const e=document.getElementById('toast');e.textContent=txt;e.className='toast-msg '+color;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',ms||2000);}
        async function syncGraph(btn){if(btn){btn.disabled=true;btn.textContent='⏳ Syncing...';}try{const r=await apiPost('/api/easyq2sql/v1/metric-graph/sync',{});t('Graph synced: '+r.nodes+' nodes, '+r.edges+' edges ✓','','bg-green-600 text-white');}catch(e){t('Sync failed: '+e.message,'','bg-red-500 text-white');}if(btn){btn.disabled=false;btn.textContent='🔗 Sync to Neo4j';}}
        function metricName(mid){const m=allAtomicMetrics.find(x=>x.id===mid);return m?m.name:mid;}
        async function getCols(tn){if(!tn)return[];if(columnCache[tn])return columnCache[tn];try{const t=await apiGet('/api/easyq2sql/v1/schema/tables/'+encodeURIComponent(tn));columnCache[tn]=(t&&t.columns)?t.columns:[];return columnCache[tn];}catch(e){return[];}}
        async function popCol(sel,tn,preselected){sel.innerHTML='<option value="">-- Select field --</option>';if(!tn)return;const cols=await getCols(tn);sel.innerHTML+=cols.map(c=>`<option value="${tn}.${c.name}" ${preselected===tn+'.'+c.name?'selected':''}>${c.name}${c.description?' -- '+esc(c.description):''}</option>`).join('');}
        async function init(){try{allTables=await apiGet('/api/easyq2sql/v1/schema/tables');}catch(e){allTables=[];}popDimTableOpts();await loadAll();}
        function popDimTableOpts(){const o=allTables.map(t=>`<option value="${t.table_name}">${t.table_name}${t.description?' -- '+esc(t.description):''}</option>`).join('');document.querySelectorAll('#d-table').forEach(s=>{const v=s.value;s.innerHTML='<option value="">Select dimension table</option>'+o;s.value=v;});}
        async function loadAll(){try{allAtomicMetrics=await apiGet('/api/easyq2sql/v1/atomic-metrics');}catch(e){allAtomicMetrics=[];}try{allDerivedMetrics=await apiGet('/api/easyq2sql/v1/derived-metrics');}catch(e){allDerivedMetrics=[];}renderTable();}
        function groupByMetric(filtered){const map=new Map();for(const d of filtered){if(!map.has(d.atomic_metric_id))map.set(d.atomic_metric_id,[]);map.get(d.atomic_metric_id).push(d);}for(const dims of map.values()){dims.sort((a,b)=>(a.name||'').localeCompare(b.name||''));}return map;}
        function getFiltered(){const s=document.getElementById('searchInput').value.toLowerCase();return allDerivedMetrics.filter(dim=>{const mn=metricName(dim.atomic_metric_id).toLowerCase();return(!s||dim.name.toLowerCase().includes(s)||mn.includes(s)||dim.id.toLowerCase().includes(s));});}
        function renderTable(){const filtered=getFiltered();const grouped=groupByMetric(filtered);const tb=document.getElementById('tableBody');const mc=grouped.size;const dc=filtered.length;document.getElementById('totalMetricCount').textContent=mc;document.getElementById('totalDimCount').textContent=dc;document.getElementById('pageInfo').textContent=`Showing ${mc} metrics, ${dc} dimensions`;document.getElementById('statDimTotal').textContent=allDerivedMetrics.length;document.getElementById('statMetricLinked').textContent=new Set(allDerivedMetrics.map(d=>d.atomic_metric_id)).size;document.getElementById('statHier').textContent=allDerivedMetrics.filter(d=>d.business_definition).length;document.getElementById('statNoJoin').textContent=allDerivedMetrics.filter(d=>!d.joins||!d.joins.length).length;if(!filtered.length){tb.innerHTML='<tr><td colspan="4" class="text-center py-10 text-gray-400">📐 No dimensions yet</td></tr>';return;}const sorted=[...grouped.entries()].sort((a,b)=>b[1].length-a[1].length||metricName(a[0]).localeCompare(metricName(b[0])));tb.innerHTML=sorted.map(([mid,dims])=>{const mn=metricName(mid);const latest=dims.reduce((t,d)=>(d.updated_at||d.created_at||'')>t?(d.updated_at||d.created_at||''):t,'');const vis=dims.slice(0,MAX_TAGS);const hid=dims.slice(MAX_TAGS);const tags=vis.map(d=>{const hj=d.joins&&d.joins.length>0;return`<span class="dim-tag${hj?' has-join':''}" onclick="editDim('${d.id}')" title="Click to edit · ${esc(d.data_source)}.${esc(d.field_ref)}${hj?' · with JOIN':''}"><input type="checkbox" class="dim-check" value="${d.id}" onclick="event.stopPropagation()" onchange="updateBatchBar()"> ${esc(d.name)}</span>`;}).join('');const overflow=hid.length>0?`<span class="dim-tag-overflow" onclick="this.style.display='none';this.parentElement.querySelectorAll('.hidden-tag').forEach(e=>e.style.display='inline-flex')">+${hid.length}</span>`:'';const hidden=hid.map(d=>{const hj=d.joins&&d.joins.length>0;return`<span class="dim-tag hidden-tag${hj?' has-join':''}" style="display:none" onclick="editDim('${d.id}')" title="Click to edit"><input type="checkbox" class="dim-check" value="${d.id}" onclick="event.stopPropagation()" onchange="updateBatchBar()"> ${esc(d.name)}</span>`;}).join('');return`<tr class="border-b border-gray-100 hover:bg-blue-50/30 transition"><td class="py-3 px-4"><div class="font-medium text-gray-900">${esc(mn)}</div></td><td class="py-3 px-4"><div class="flex flex-wrap gap-1.5 items-center">${tags}${overflow}${hidden}</div></td><td class="py-3 px-4 text-xs text-gray-500">${esc(typeof latest==='string'?latest.substring(0,16):'')}</td><td class="py-3 px-4 whitespace-nowrap"><button onclick="openCreateModalForMetric('${mid}')" class="text-easyq2sql-teal hover:text-easyq2sql-navy text-xs mr-1">Add</button><button onclick="editDim('${dims[0].id}')" class="text-easyq2sql-teal hover:text-easyq2sql-navy text-xs mr-1">Edit</button><button onclick="deleteMetricDims('${mid}')" class="text-red-500 hover:text-red-700 text-xs">Delete</button></td></tr>`;}).join('');updateBatchBar();}
        function resetFilters(){document.getElementById('searchInput').value='';renderTable();}

        function addJoinRow(j){const jn=j||{source_table:'',source_column:'',target_table:'',target_column:'',join_type:'INNER JOIN'};tempJoins.push(jn);renderJoins();}
        function removeJoinRow(i){tempJoins.splice(i,1);renderJoins();}
        function renderJoins(){const c=document.getElementById('joinContainer');if(!tempJoins.length){c.innerHTML='<div class="text-xs text-gray-400 py-1">No JOIN configured yet (not needed if the dimension table joins the fact table directly)</div>';return;}c.innerHTML=tempJoins.map((j,i)=>`<div class="join-row"><div><label class="text-xs text-gray-500">Source Table</label><select onchange="tempJoins[${i}].source_table=this.value;renderJoins()" class="w-full px-2 py-1 text-xs border rounded font-mono"><option value="">Select</option>${allTables.map(t=>`<option value="${t.table_name}" ${j.source_table===t.table_name?'selected':''}>${t.table_name}${t.description?' -- '+esc(t.description):''}</option>`).join('')}</select></div><div><label class="text-xs text-gray-500">Source Column</label><select onchange="tempJoins[${i}].source_column=this.value" data-idx="${i}" class="w-full px-2 py-1 text-xs border rounded font-mono join-source-field"><option value="">-- Select field --</option></select></div><div><label class="text-xs text-gray-500">Target Table</label><select onchange="tempJoins[${i}].target_table=this.value;renderJoins()" class="w-full px-2 py-1 text-xs border rounded font-mono"><option value="">Select</option>${allTables.map(t=>`<option value="${t.table_name}" ${j.target_table===t.table_name?'selected':''}>${t.table_name}${t.description?' -- '+esc(t.description):''}</option>`).join('')}</select></div><div><label class="text-xs text-gray-500">Target Column</label><select onchange="tempJoins[${i}].target_column=this.value" data-idx="${i}" class="w-full px-2 py-1 text-xs border rounded font-mono join-target-field"><option value="">-- Select field --</option></select></div><div><label class="text-xs text-gray-500">Type</label><select onchange="tempJoins[${i}].join_type=this.value" class="w-full px-2 py-1 text-xs border rounded font-mono"><option value="LEFT JOIN" ${j.join_type==='LEFT JOIN'?'selected':''}>LEFT</option><option value="INNER JOIN" ${j.join_type==='INNER JOIN'?'selected':''}>INNER</option></select></div><button onclick="removeJoinRow(${i})" class="text-red-400 hover:text-red-600 text-lg leading-none">&times;</button></div>`).join('');setTimeout(()=>popJoinFields(),0);}
        async function popJoinFields(){const srcSelects=document.querySelectorAll('.join-source-field');const tgtSelects=document.querySelectorAll('.join-target-field');for(const sel of srcSelects){const idx=parseInt(sel.dataset.idx);const tableName=tempJoins[idx]?tempJoins[idx].source_table:'';const currentVal=sel.value||tempJoins[idx]?.source_column||'';if(tableName){const cols=await getCols(tableName);sel.innerHTML='<option value="">-- Select field --</option>'+cols.map(c=>`<option value="${tableName}.${c.name}" ${currentVal===tableName+'.'+c.name?'selected':''}>${c.name}${c.description?' -- '+esc(c.description):''}</option>`).join('');}else{sel.innerHTML='<option value="">-- Select source table first --</option>';}}for(const sel of tgtSelects){const idx=parseInt(sel.dataset.idx);const tableName=tempJoins[idx]?tempJoins[idx].target_table:'';const currentVal=sel.value||tempJoins[idx]?.target_column||'';if(tableName){const cols=await getCols(tableName);sel.innerHTML='<option value="">-- Select field --</option>'+cols.map(c=>`<option value="${tableName}.${c.name}" ${currentVal===tableName+'.'+c.name?'selected':''}>${c.name}${c.description?' -- '+esc(c.description):''}</option>`).join('');}else{sel.innerHTML='<option value="">-- Select target table first --</option>';}}}
        async function onDimTableChange(pf){const tn=document.getElementById('d-table').value;const fs=document.getElementById('d-field');await popCol(fs,tn,pf||'');}
        function openCreateModal(){openCreateModalForMetric('');}
        function openCreateModalForMetric(mid){editingId=null;document.getElementById('modalTitle').textContent='New Dimension';document.getElementById('editId').value='';document.getElementById('d-name').value='';document.getElementById('d-range').value='';document.getElementById('d-bizdef').value='';document.getElementById('d-table').value='';document.getElementById('d-field').innerHTML='<option value="">Select dimension table first</option>';tempJoins=[];renderJoins();popDimTableOpts();const ms=document.getElementById('d-metric');ms.innerHTML='<option value="">Select a configured metric</option>'+allAtomicMetrics.map(m=>`<option value="${m.id}" ${mid===m.id?'selected':''}>${esc(m.name)}</option>`).join('');if(mid){ms.value=mid;}document.getElementById('dimModal').style.display='flex';}
        function editDim(id){const d=allDerivedMetrics.find(x=>x.id===id);if(!d)return;editingId=id;document.getElementById('modalTitle').textContent='Edit Dimension';document.getElementById('editId').value=d.id;document.getElementById('d-name').value=d.name;document.getElementById('d-range').value=d.value_range||'';document.getElementById('d-bizdef').value=d.business_definition||'';document.getElementById('d-table').value=d.data_source||'';tempJoins=d.joins?JSON.parse(JSON.stringify(d.joins)):[];renderJoins();popDimTableOpts();onDimTableChange(d.field_ref);const ms=document.getElementById('d-metric');ms.innerHTML='<option value="">Select a configured metric</option>'+allAtomicMetrics.map(m=>`<option value="${m.id}" ${d.atomic_metric_id===m.id?'selected':''}>${esc(m.name)}</option>`).join('');ms.value=d.atomic_metric_id;document.getElementById('dimModal').style.display='flex';}
        function closeModal(){document.getElementById('dimModal').style.display='none';}
        document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
        async function saveDim(){const mid=document.getElementById('d-metric').value;const name=document.getElementById('d-name').value.trim();const ds=document.getElementById('d-table').value;const field=document.getElementById('d-field').value;if(!mid||!name||!ds||!field){t('Please fill in all required fields','','bg-red-500 text-white');return;}const body={atomic_metric_id:mid,name,business_definition:document.getElementById('d-bizdef').value.trim()||null,value_range:document.getElementById('d-range').value.trim()||null,data_source:ds,field_ref:field,joins:tempJoins.filter(j=>j.source_table&&j.target_table),description:null};try{if(editingId){await apiPut('/api/easyq2sql/v1/derived-metrics/'+encodeURIComponent(editingId),body);t('Dimension updated ✓','','bg-green-600 text-white');}else{await apiPost('/api/easyq2sql/v1/derived-metrics',body);t('Dimension created ✓','','bg-green-600 text-white');}closeModal();await loadAll();}catch(e){t('Save failed: '+e.message,'','bg-red-500 text-white');}}
        async function deleteMetricDims(mid){const dims=allDerivedMetrics.filter(d=>d.atomic_metric_id===mid);if(!dims.length)return;const mn=metricName(mid);if(!confirm(`Delete all ${dims.length} dimensions under metric "${mn}"?`))return;for(const d of dims){try{await apiDelete('/api/easyq2sql/v1/derived-metrics/'+encodeURIComponent(d.id));}catch(e){}}
        t(`Deleted ${dims.length} dimensions`,'','bg-green-600 text-white');await loadAll();}
        async function autoFillRange(){const ds=document.getElementById('d-table').value;const fr=document.getElementById('d-field').value;if(!ds||!fr){t('Select the data table and field first','','bg-orange-500 text-white');return;}const btn=event.target;btn.disabled=true;btn.textContent='⏳ Querying...';try{const r=await apiPost('/api/easyq2sql/v1/derived-metrics/auto-range',{data_source:ds,field_ref:fr});if(r.too_many){t(`This field has ${r.count} distinct values (over 20), so it will not be auto-filled. Enter the value range manually.`,'','bg-orange-500 text-white');}else if(r.values&&r.values.length){document.getElementById('d-range').value=r.values.join(';');t(`Auto-filled ${r.values.length} values ✓`,'','bg-green-600 text-white');}else{t('This field has no data','','bg-gray-500 text-white');}}catch(e){t('Query failed: '+e.message,'','bg-red-500 text-white');}finally{btn.disabled=false;btn.textContent='⚡ Auto-generate';}}
        function getSelectedDims(){return Array.from(document.querySelectorAll('.dim-check:checked'));}
        function updateBatchBar(){const n=getSelectedDims().length;const btn=document.getElementById('batchDeleteBtn');if(btn){document.getElementById('batchDeleteCount').textContent=n;btn.classList.toggle('hidden',n===0);}}
        async function batchDelete(){const sel=getSelectedDims();if(!sel.length){t('Select dimensions to delete first','','bg-orange-500 text-white');return;}const ids=sel.map(c=>c.value);if(!confirm(`Delete the ${ids.length} selected dimensions?`))return;try{const r=await apiPost('/api/easyq2sql/v1/derived-metrics/batch-delete',{ids});t(`Deleted ${r.deleted} dimensions ✓`,'','bg-green-600 text-white');}catch(e){t('Delete failed: '+e.message,'','bg-red-500 text-white');}await loadAll();}
        init();
    </script>"""
    return _admin_page_wrapper("DerivedMetric Management", body, api_base_url, active="derived-metrics")


# =========================================================================
# Composite Metric Management Page
# =========================================================================

def get_composite_admin_html(api_base_url: str = "") -> str:
    """Generate the Composite Metric Management admin page.

    Composite metrics combine two derived metrics (i.e. two ``Dimension``
    slices) via an operator (比值 / 差值 / 环比 / 同比). The two operands are
    selected from the configured dimensions.
    """
    body = """
    <style>
        .stat-card { transition: box-shadow .2s; }
        .stat-card:hover { box-shadow: 0 6px 16px rgba(0,0,0,.08); }
        .tag { display:inline-flex; align-items:center; padding:1px 8px; border-radius:3px; font-size:12px; line-height:20px; }
        .tag-blue { background:#e6f4ff; color:#1677ff; border:1px solid #bae0ff; }
        .tag-green { background:#f6ffed; color:#52c41a; border:1px solid #b7eb8f; }
        .tag-orange { background:#fff7e6; color:#fa8c16; border:1px solid #ffd591; }
        .tag-purple { background:#f9f0ff; color:#722ed1; border:1px solid #d3adf7; }
        .modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:1000; display:flex; align-items:flex-start; justify-content:center; padding-top:40px; }
        .toast-msg { position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:2000; padding:10px 24px; border-radius:8px; font-size:14px; box-shadow:0 4px 12px rgba(0,0,0,.15); }
    </style>
    <!-- Stats Row -->
    <div class="grid grid-cols-4 gap-4 mb-5">
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center text-2xl">🧩</div><div><div class="text-2xl font-bold text-gray-900" id="statTotal">0</div><div class="text-xs text-gray-500">Total Composites</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-green-50 text-green-500 flex items-center justify-center text-2xl">➗</div><div><div class="text-2xl font-bold text-gray-900" id="statRatio">0</div><div class="text-xs text-gray-500">比值</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center text-2xl">➖</div><div><div class="text-2xl font-bold text-gray-900" id="statDiff">0</div><div class="text-xs text-gray-500">差值</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-purple-50 text-purple-500 flex items-center justify-center text-2xl">📈</div><div><div class="text-2xl font-bold text-gray-900" id="statPct">0</div><div class="text-xs text-gray-500">环比 / 同比</div></div></div>
    </div>
    <!-- Toolbar -->
    <div class="bg-white rounded-lg p-4 border border-gray-200 flex items-center gap-3 flex-wrap mb-5">
        <input id="searchInput" placeholder="🔍 Search composite metric name / definition..." oninput="renderTable()" class="w-72 h-9 px-3 text-sm border border-gray-300 rounded-md focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal outline-none">
        <button onclick="resetFilters()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:text-easyq2sql-teal hover:border-easyq2sql-teal transition bg-white">↻ Reset</button>
        <button onclick="batchDeleteComps()" class="h-9 px-4 text-sm border border-easyq2sql-orange text-easyq2sql-orange rounded-md hover:bg-easyq2sql-orange hover:text-white transition bg-white font-medium">🗑 Batch Delete</button>
        <div class="flex-1"></div>
        <button onclick="openCreateModal()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">+ New Composite</button>
        <button onclick="syncGraph(this)" class="h-9 px-4 text-sm border border-easyq2sql-navy text-easyq2sql-navy rounded-md hover:bg-easyq2sql-navy hover:text-white transition bg-white font-medium">🔗 Sync to Neo4j</button>
    </div>
    <!-- Table -->
    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 text-sm font-semibold text-gray-900 flex justify-between"><span>Composite Metric List</span><span class="text-xs font-normal text-gray-500"><b id="totalCount">0</b> total</span></div>
        <div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="bg-gray-50 text-left text-xs text-gray-500 uppercase"><th class="py-3 px-4 w-10"><input type="checkbox" id="selAll" onchange="selAllComps(this.checked)" title="Select all"></th><th class="py-3 px-4">Composite Name</th><th class="py-3 px-4 w-28">Composition</th><th class="py-3 px-4">Operand A</th><th class="py-3 px-4">Operand B</th><th class="py-3 px-4">Business Definition</th><th class="py-3 px-4 w-32">Updated</th><th class="py-3 px-4 w-24">Actions</th></tr></thead><tbody id="tableBody"></tbody></table></div>
        <div class="px-5 py-3 border-t border-gray-200 text-xs text-gray-500 flex justify-between"><span id="pageInfo"></span></div>
    </div>
    <!-- Modal -->
    <div class="modal-overlay" id="compModal" style="display:none" onclick="if(event.target===this)closeModal()">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-lg max-h-[85vh] flex flex-col">
            <div class="px-6 py-4 border-b border-gray-200 text-base font-semibold flex items-center justify-between"><span id="modalTitle">New Composite</span><button onclick="closeModal()" class="text-gray-400 hover:text-gray-800 text-xl leading-none">&times;</button></div>
            <div class="p-6 overflow-y-auto flex-1 space-y-4">
                <input type="hidden" id="editId">
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Composite Metric Name <span class="text-red-500">*</span></label><input id="c-name" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="e.g. average order value, gross margin"></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Composition <span class="text-red-500">*</span></label><select id="c-func" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="比值">比值</option><option value="差值">差值</option><option value="环比">环比</option><option value="同比">同比</option></select><p class="text-xs text-gray-400 mt-1">Composite = Operand A (composition) Operand B</p></div>
                <div class="grid grid-cols-2 gap-4">
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">Operand A (derived metric)<span class="text-red-500">*</span></label><select id="c-opa" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">Select a derived metric</option></select></div>
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">Operand B (derived metric)<span class="text-red-500">*</span></label><select id="c-opb" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">Select a derived metric</option></select></div>
                </div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">Business Definition</label><textarea id="c-bizdef" rows="2" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="Explain the business meaning of this composite metric"></textarea></div>
            </div>
            <div class="px-6 py-3 border-t border-gray-200 flex justify-end gap-2"><button onclick="closeModal()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:bg-gray-100 bg-white">Cancel</button><button onclick="saveComp()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">✓ Save</button></div>
        </div>
    </div>
    <!-- Toast -->
    <div class="toast-msg hidden" id="toast"></div>
    <script>
        let allCompositeMetrics=[],allDerivedMetrics=[],allAtomicMetrics=[],editingId=null,selComps=new Set(),visibleCompIds=[];
        function esc(s){return(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
        function t(txt,ms,color){const e=document.getElementById('toast');e.textContent=txt;e.className='toast-msg '+color;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',ms||2000);}
        async function syncGraph(btn){if(btn){btn.disabled=true;btn.textContent='⏳ Syncing...';}try{const r=await apiPost('/api/easyq2sql/v1/metric-graph/sync',{});t('Graph synced: '+r.nodes+' nodes, '+r.edges+' edges ✓','','bg-green-600 text-white');}catch(e){t('Sync failed: '+e.message,'','bg-red-500 text-white');}if(btn){btn.disabled=false;btn.textContent='🔗 Sync to Neo4j';}}
        function metricName(mid){const m=allAtomicMetrics.find(x=>x.id===mid);return m?m.name:mid;}
        function dimLabel(did){const d=allDerivedMetrics.find(x=>x.id===did);if(!d)return did;return d.name+' ('+metricName(d.atomic_metric_id)+')';}
        function combTag(f){const map={'比值':'tag-blue','差值':'tag-green','环比':'tag-orange','同比':'tag-purple'};return '<span class="tag '+(map[f]||'tag-gray')+'">'+esc(f)+'</span>';}
        async function init(){try{allAtomicMetrics=await apiGet('/api/easyq2sql/v1/atomic-metrics');}catch(e){allAtomicMetrics=[];}try{allDerivedMetrics=await apiGet('/api/easyq2sql/v1/derived-metrics');}catch(e){allDerivedMetrics=[];}await loadComps();}
        async function loadComps(){try{allCompositeMetrics=await apiGet('/api/easyq2sql/v1/composite-metrics');}catch(e){allCompositeMetrics=[];}renderTable();}
        function getFiltered(){const s=document.getElementById('searchInput').value.toLowerCase();return allCompositeMetrics.filter(c=>!s||c.name.toLowerCase().includes(s)||(c.business_definition||'').toLowerCase().includes(s)||c.comb_func.toLowerCase().includes(s)||dimLabel(c.operand_a).toLowerCase().includes(s)||dimLabel(c.operand_b).toLowerCase().includes(s));}
        function renderTable(){const data=getFiltered();visibleCompIds=data.map(c=>c.id);const tb=document.getElementById('tableBody');document.getElementById('totalCount').textContent=data.length;document.getElementById('pageInfo').textContent='Showing '+data.length;document.getElementById('statTotal').textContent=allCompositeMetrics.length;document.getElementById('statRatio').textContent=allCompositeMetrics.filter(c=>c.comb_func==='比值').length;document.getElementById('statDiff').textContent=allCompositeMetrics.filter(c=>c.comb_func==='差值').length;document.getElementById('statPct').textContent=allCompositeMetrics.filter(c=>c.comb_func==='环比'||c.comb_func==='同比').length;const sa=document.getElementById('selAll');const selN=visibleCompIds.filter(id=>selComps.has(id)).length;sa.checked=visibleCompIds.length>0&&selN===visibleCompIds.length;sa.indeterminate=selN>0&&selN<visibleCompIds.length;if(!data.length){tb.innerHTML='<tr><td colspan="8" class="text-center py-10 text-gray-400">🧩 No composites yet</td></tr>';return;}tb.innerHTML=data.map(c=>{const tv=c.updated_at||c.created_at||'';const ck=selComps.has(c.id)?' checked':'';return '<tr class="border-b border-gray-100 hover:bg-blue-50/30 transition"><td class="py-3 px-4 w-10"><input type="checkbox"'+ck+' onchange="onCompSel(\\''+c.id+'\\',this.checked)"></td><td class="py-3 px-4 font-medium text-gray-900">'+esc(c.name)+' <span class="text-xs text-gray-400">'+esc(c.id)+'</span></td><td class="py-3 px-4">'+combTag(c.comb_func)+'</td><td class="py-3 px-4 text-gray-700">'+esc(dimLabel(c.operand_a))+'</td><td class="py-3 px-4 text-gray-700">'+esc(dimLabel(c.operand_b))+'</td><td class="py-3 px-4 max-w-[200px] truncate text-xs" title="'+esc(c.business_definition||'')+'">'+esc(c.business_definition||'-')+'</td><td class="py-3 px-4 text-xs text-gray-500">'+esc(typeof tv==='string'?tv.substring(0,16):'')+'</td><td class="py-3 px-4 whitespace-nowrap"><button onclick="editComp(\\''+c.id+'\\')" class="text-easyq2sql-teal hover:text-easyq2sql-navy text-xs mr-2">Edit</button><button onclick="deleteComp(\\''+c.id+'\\')" class="text-red-500 hover:text-red-700 text-xs">Delete</button></td></tr>';}).join('');}
        function resetFilters(){document.getElementById('searchInput').value='';renderTable();}
        function popOperandOpts(preselA,preselB){const opts=allDerivedMetrics.map(d=>'<option value="'+esc(d.id)+'">'+esc(d.name)+' ('+esc(metricName(d.atomic_metric_id))+')</option>').join('');const opa=document.getElementById('c-opa');opa.innerHTML='<option value="">Select a derived metric</option>'+opts;if(preselA)opa.value=preselA;const opb=document.getElementById('c-opb');opb.innerHTML='<option value="">Select a derived metric</option>'+opts;if(preselB)opb.value=preselB;}
        function openCreateModal(){editingId=null;document.getElementById('modalTitle').textContent='New Composite';document.getElementById('editId').value='';document.getElementById('c-name').value='';document.getElementById('c-func').value='比值';document.getElementById('c-bizdef').value='';popOperandOpts();document.getElementById('compModal').style.display='flex';}
        function editComp(id){const c=allCompositeMetrics.find(x=>x.id===id);if(!c)return;editingId=id;document.getElementById('modalTitle').textContent='Edit Composite';document.getElementById('editId').value=c.id;document.getElementById('c-name').value=c.name;document.getElementById('c-func').value=c.comb_func||'比值';document.getElementById('c-bizdef').value=c.business_definition||'';popOperandOpts(c.operand_a,c.operand_b);document.getElementById('compModal').style.display='flex';}
        function closeModal(){document.getElementById('compModal').style.display='none';}
        document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
        async function saveComp(){if(!allDerivedMetrics.length){t('Create derived metrics (dimensions) under "Dimension Config" first — composite operands must be selected from dimensions','','bg-orange-500 text-white');return;}const name=document.getElementById('c-name').value.trim();const func=document.getElementById('c-func').value;const opa=document.getElementById('c-opa').value;const opb=document.getElementById('c-opb').value;if(!name||!func||!opa||!opb){t('Please fill in all required fields','','bg-red-500 text-white');return;}if(opa===opb){t('Operand A and Operand B must be different','','bg-red-500 text-white');return;}const body={name,comb_func:func,operand_a:opa,operand_b:opb,business_definition:document.getElementById('c-bizdef').value.trim()||null,description:null};try{if(editingId){await apiPut('/api/easyq2sql/v1/composite-metrics/'+encodeURIComponent(editingId),body);t('Composite updated ✓','','bg-green-600 text-white');}else{await apiPost('/api/easyq2sql/v1/composite-metrics',body);t('Composite created ✓','','bg-green-600 text-white');}closeModal();await loadComps();}catch(e){t('Save failed: '+e.message,'','bg-red-500 text-white');}}
        async function deleteComp(id){const c=allCompositeMetrics.find(x=>x.id===id);if(!confirm('Delete composite "'+(c?c.name:id)+'"?'))return;try{await apiDelete('/api/easyq2sql/v1/composite-metrics/'+encodeURIComponent(id));t('Deleted','','bg-green-600 text-white');await loadComps();}catch(e){t('Delete failed: '+e.message,'','bg-red-500 text-white');}}
        function onCompSel(id,ck){if(ck)selComps.add(id);else selComps.delete(id);renderTable();}
        function selAllComps(ck){visibleCompIds.forEach(id=>{if(ck)selComps.add(id);else selComps.delete(id);});renderTable();}
        async function batchDeleteComps(){if(!selComps.size){t('Select composites to delete first','','bg-orange-500 text-white');return;}const ids=[...selComps];if(!confirm('Delete the '+ids.length+' selected composites?'))return;let ok=0,fail=0;for(const id of ids){try{await apiDelete('/api/easyq2sql/v1/composite-metrics/'+encodeURIComponent(id));selComps.delete(id);ok++;}catch(e){fail++;}}t('Deleted '+ok+(fail?(', '+fail+' failed'):''),'','bg-green-600 text-white');await loadComps();}
        init();
    </script>"""
    return _admin_page_wrapper("CompositeMetric Management", body, api_base_url, active="composite-metrics")


# =========================================================================
# Metric Graph Page (LLM extraction -> draft -> import -> sync)
# =========================================================================

def get_metric_graph_admin_html(api_base_url: str = "") -> str:
    """Generate the Metric Graph admin page.

    Implements the manual-trigger -> draft-area -> checkbox-import workflow:

      1. "Trigger LLM Extraction" runs extraction over all schemas and fills the draft;
      2. the draft is rendered as three groups (原子指标 / 派生指标 / 复合指标)
         with checkboxes;
      3. "Import Selected" maps the selected entities into the config stores;
      4. "Sync to Neo4j" rebuilds the graph index for retrieval.
    """
    body = """
    <style>
        .stat-card { transition: box-shadow .2s; }
        .stat-card:hover { box-shadow: 0 6px 16px rgba(0,0,0,.08); }
        .tag { display:inline-flex; align-items:center; padding:1px 8px; border-radius:3px; font-size:12px; line-height:20px; }
        .tag-blue { background:#e6f4ff; color:#1677ff; border:1px solid #bae0ff; }
        .tag-green { background:#f6ffed; color:#52c41a; border:1px solid #b7eb8f; }
        .tag-orange { background:#fff7e6; color:#fa8c16; border:1px solid #ffd591; }
        .tag-gray { background:#f5f5f5; color:#8c8c8c; border:1px solid #d9d9d9; }
        .toast-msg { position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:2000; padding:10px 24px; border-radius:8px; font-size:14px; box-shadow:0 4px 12px rgba(0,0,0,.15); }
        .entity-row { display:flex; gap:10px; align-items:flex-start; padding:10px 12px; border:1px solid #f0f0f0; border-radius:8px; cursor:pointer; transition:background .15s; background:#fff; }
        .entity-row:hover { background:#e6f4ff; }
        .entity-row input[type=checkbox] { margin-top:3px; }
        .entity-body { flex:1; min-width:0; }
        .entity-name { font-weight:600; color:#1f1f1f; font-size:13px; }
        .entity-desc { font-size:12px; color:#8c8c8c; margin-top:2px; overflow:hidden; text-overflow:ellipsis; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
        .entity-props { margin-top:6px; display:flex; flex-wrap:wrap; gap:4px; }
        .prop { font-size:11px; background:#fafafa; border:1px solid #f0f0f0; color:#595959; padding:1px 6px; border-radius:3px; }
        .rel-row { font-size:12px; color:#595959; padding:4px 8px; border-bottom:1px solid #fafafa; }
        .table-group { border:1px solid #f0f0f0; border-radius:6px; margin-bottom:8px; overflow:hidden; }
        .table-group-header { font-size:12px; font-weight:600; color:#1677ff; background:#f0f7ff; padding:4px 10px; border-bottom:1px solid #e6f4ff; display:flex; justify-content:space-between; align-items:center; }
        .table-group-count { color:#8c8c8c; font-weight:400; }
        .table-group-body { padding:6px 10px; display:flex; flex-direction:column; gap:6px; }
    </style>
    <!-- Stats Row -->
    <div class="grid grid-cols-4 gap-4 mb-5">
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center text-2xl">⚛️</div><div><div class="text-2xl font-bold text-gray-900" id="statAtomic">0</div><div class="text-xs text-gray-500">原子指标</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-green-50 text-green-500 flex items-center justify-center text-2xl">📐</div><div><div class="text-2xl font-bold text-gray-900" id="statDerived">0</div><div class="text-xs text-gray-500">派生指标</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center text-2xl">🧩</div><div><div class="text-2xl font-bold text-gray-900" id="statComposite">0</div><div class="text-xs text-gray-500">复合指标</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-purple-50 text-purple-500 flex items-center justify-center text-2xl">🔗</div><div><div class="text-2xl font-bold text-gray-900" id="statRel">0</div><div class="text-xs text-gray-500">Relationships</div></div></div>
    </div>
    <!-- Toolbar -->
    <div class="bg-white rounded-lg p-4 border border-gray-200 flex items-center gap-3 flex-wrap mb-5">
        <label class="text-xs text-gray-500 font-medium">Scope</label>
        <select id="extractTable" onchange="onScopeChange()" class="h-9 px-3 text-sm border border-gray-300 rounded-md outline-none bg-white max-w-[280px]"><option value="">All tables</option></select>
        <button id="btnExtract" onclick="extract()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">🔄 Trigger LLM Extraction</button>
        <button id="btnClear" onclick="clearDraft()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:text-easyq2sql-orange hover:border-easyq2sql-orange transition bg-white">🗑️ Clear Draft</button>
        <div class="flex-1"></div>
        <span id="draftStatus" class="text-xs text-gray-500">No draft yet. Click "Trigger LLM Extraction" to begin.</span>
        <button onclick="syncGraph()" class="h-9 px-4 text-sm border border-easyq2sql-navy text-easyq2sql-navy rounded-md hover:bg-easyq2sql-navy hover:text-white transition bg-white font-medium">🔗 Sync to Neo4j</button>
    </div>
    <!-- Import bar -->
    <div class="bg-white rounded-lg p-3 border border-gray-200 flex items-center gap-3 mb-5">
        <span class="text-sm text-gray-700">Selected <b id="selCount" class="text-easyq2sql-teal">0</b> items</span>
        <div class="flex-1"></div>
        <button onclick="importSelected()" class="h-9 px-5 bg-easyq2sql-orange text-white text-sm font-medium rounded-md hover:bg-easyq2sql-magenta transition">✓ Import Selected</button>
    </div>
    <!-- Import report -->
    <div id="importReport" class="hidden bg-white rounded-lg p-4 border border-gray-200 mb-5"></div>
    <!-- Entity groups -->
    <div id="groups" class="grid grid-cols-3 gap-4 mb-5"></div>
    <!-- Relationships -->
    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 text-sm font-semibold text-gray-900 flex justify-between"><span>Entity Relationships (Extraction Result)</span><span class="text-xs font-normal text-gray-500"><b id="relCount">0</b> total</span></div>
        <div id="relList" class="p-2 max-h-64 overflow-y-auto"><div class="text-xs text-gray-400 text-center py-6">No relationships yet</div></div>
    </div>
    <!-- Toast -->
    <div class="toast-msg hidden" id="toast"></div>
    <script>
        let draft=null;
        const TYPE_META={'原子指标':{icon:'⚛️',color:'tag-blue'},'派生指标':{icon:'📐',color:'tag-green'},'复合指标':{icon:'🧩',color:'tag-orange'}};
        const TYPE_ORDER=['原子指标','派生指标','复合指标'];
        function esc(s){return(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
        function t(txt,ms,color){const e=document.getElementById('toast');e.textContent=txt;e.className='toast-msg '+color;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',ms||2500);}
        function setStatus(txt){document.getElementById('draftStatus').textContent=txt;}
        function currentScope(){return document.getElementById('extractTable').value;}
        function onScopeChange(){const sc=currentScope();const bc=document.getElementById('btnClear');if(bc)bc.textContent=sc?'🗑️ Clear This Table':'🗑️ Clear Draft';renderDraft();}
        function visibleEntities(){const sc=currentScope();if(!draft||!draft.entities)return[];if(!sc)return draft.entities;return draft.entities.filter(function(e){return (e.source_table||'')===sc;});}
        function visibleRelationships(ents){if(!draft||!draft.relationships)return[];const names={};ents.forEach(function(e){names[e.entity_name]=true;});return draft.relationships.filter(function(r){return names[r.src_id]&&names[r.tgt_id];});}
        function groupByType(ents){const g={};ents.forEach(function(e){(g[e.entity_type]=g[e.entity_type]||[]).push(e);});return g;}
        async function extract(){const btn=document.getElementById('btnExtract');btn.disabled=true;btn.textContent='⏳ Extracting via LLM...';try{const tbl=document.getElementById('extractTable').value;const body=tbl?{tables:[tbl]}:{};const kick=await apiPost('/api/easyq2sql/v1/metric-graph/extract',body);setStatus('Extracting: '+(kick.tables_total||'')+' tables...');let state;while(true){await new Promise(res=>setTimeout(res,1500));state=await apiGet('/api/easyq2sql/v1/metric-graph/extract/status');if(state.status==='running'){setStatus('Extracting: '+(state.tables_total||'')+' tables...');}else if(state.status==='done'){break;}else if(state.status==='error'){throw new Error(state.error||'Extraction failed');}else{throw new Error('Unknown status: '+state.status);}}draft=await apiGet('/api/easyq2sql/v1/metric-graph/draft');setStatus('Extraction complete: '+summary(draft));t('Metric graph extraction complete ✓','','bg-green-600 text-white');renderDraft();}catch(e){t('Extraction failed: '+e.message,'','bg-red-500 text-white');setStatus('Extraction failed');}finally{btn.disabled=false;btn.textContent='🔄 Trigger LLM Extraction';}}
        function summary(r){const c=r.counts||{};return TYPE_ORDER.map(k=>(c[k]||0)+' '+k).join(', ');}
        function groupByTable(list){const by={};list.forEach(function(e){const t=e.source_table||'(unlinked table)';(by[t]=by[t]||[]).push(e);});return Object.keys(by).sort().map(function(t){return {table:t,entities:by[t]};});}
        async function loadTables(){try{const ts=await apiGet('/api/easyq2sql/v1/schema/tables');const sel=document.getElementById('extractTable');ts.forEach(function(t){const o=document.createElement('option');o.value=t.table_name;o.textContent=t.table_name+(t.description?' — '+t.description:'');sel.appendChild(o);});}catch(e){}}
        async function loadDraft(){try{draft=await apiGet('/api/easyq2sql/v1/metric-graph/draft');setStatus('Draft loaded: '+summary(draft));renderDraft();}catch(e){draft=null;setStatus('No draft yet. Click "Trigger LLM Extraction" to begin.');renderDraft();}}
        async function clearDraft(){const sc=currentScope();if(sc){if(!confirm('Clear extraction results for table "'+sc+'"?'))return;try{const r=await apiPost('/api/easyq2sql/v1/metric-graph/draft/clear',{tables:[sc]});await loadDraft();t('Cleared table "'+sc+'" extraction results'+(r.cleared?(' ('+r.cleared+' items)'):''),'','bg-green-600 text-white');}catch(e){t('Clear failed: '+e.message,'','bg-red-500 text-white');}}else{if(!draft){t('No draft available','','bg-gray-500 text-white');return;}if(!confirm('Clear the entire draft?'))return;try{await apiDelete('/api/easyq2sql/v1/metric-graph/draft');draft=null;setStatus('No draft yet. Click "Trigger LLM Extraction" to begin.');renderDraft();t('Draft cleared','','bg-green-600 text-white');}catch(e){t('Clear failed: '+e.message,'','bg-red-500 text-white');}}}
        function entityRow(e){const meta=TYPE_META[e.entity_type]||{icon:'📄',color:'tag-gray'};const props=e.properties||{};const propItems=Object.entries(props).map(function(kv){return '<span class="prop">'+esc(kv[0])+': '+esc(String(kv[1]))+'</span>';}).join('');return '<label class="entity-row"><input type="checkbox" class="entity-check" value="'+esc(e.entity_name)+'" onchange="updateSel()"><div class="entity-body"><div class="entity-name">'+esc(e.entity_name)+'</div>'+(e.description?'<div class="entity-desc">'+esc(e.description)+'</div>':'')+(propItems?'<div class="entity-props">'+propItems+'</div>':'')+'</div></label>';}
        function renderDraft(){const g=document.getElementById('groups');const rel=document.getElementById('relList');const ents=visibleEntities();const rels=visibleRelationships(ents);const grouped=groupByType(ents);const counts={};TYPE_ORDER.forEach(function(k){counts[k]=(grouped[k]||[]).length;});document.getElementById('relCount').textContent=rels.length;document.getElementById('statRel').textContent=rels.length;document.getElementById('statAtomic').textContent=counts['原子指标']||0;document.getElementById('statDerived').textContent=counts['派生指标']||0;document.getElementById('statComposite').textContent=counts['复合指标']||0;if(!ents.length){const sc=currentScope();g.innerHTML=sc?'<div class="col-span-3 bg-white rounded-lg border border-dashed border-gray-300 p-16 text-center text-gray-400"><div class="text-4xl mb-3">🕸️</div><p>Table "'+esc(sc)+'" has no extraction results yet</p><p class="text-xs mt-1">Click "Trigger LLM Extraction" above to extract this table, or switch the scope back to "All tables"</p></div>':'<div class="col-span-3 bg-white rounded-lg border border-dashed border-gray-300 p-16 text-center text-gray-400"><div class="text-4xl mb-3">🕸️</div><p>No draft data yet</p><p class="text-xs mt-1">Click "Trigger LLM Extraction" above to auto-extract the metric graph from the database schema</p></div>';}else{g.innerHTML=TYPE_ORDER.map(function(k){const meta=TYPE_META[k]||{icon:'📄',color:'tag-blue'};const list=(grouped[k]||[]);const header='<div class="flex items-center justify-between px-4 py-3 border-b border-gray-200"><span class="text-sm font-semibold text-gray-900">'+meta.icon+' '+esc(k)+' <span class="text-xs text-gray-400">'+list.length+'</span></span><label class="text-xs text-easyq2sql-teal cursor-pointer"><input type="checkbox" class="group-check" data-group="'+esc(k)+'" onchange="toggleGroup(this)"> Select all</label></div>';const rows=list.length?groupByTable(list).map(function(grp){return '<div class="table-group"><div class="table-group-header"><span>📄 '+esc(grp.table)+'</span><span class="table-group-count">'+grp.entities.length+' items</span></div><div class="table-group-body">'+grp.entities.map(entityRow).join('')+'</div></div>';}).join(''):'<div class="text-xs text-gray-400 text-center py-6">None</div>';return '<div class="bg-white rounded-lg border border-gray-200 overflow-hidden">'+header+'<div class="p-3 space-y-2 max-h-96 overflow-y-auto">'+rows+'</div></div>';}).join('');}
        if(rels.length){rel.innerHTML=rels.map(function(r){const kw=r.keywords?' <span class="tag tag-gray">'+esc(r.keywords)+'</span>':'';return '<div class="rel-row">'+esc(r.src_id)+' → '+esc(r.tgt_id)+kw+'</div>';}).join('');}else{rel.innerHTML='<div class="text-xs text-gray-400 text-center py-6">No relationships yet</div>';}updateSel();}
        function toggleGroup(cb){const k=cb.dataset.group;(groupByType(visibleEntities())[k]||[]).forEach(function(e){document.querySelectorAll('.entity-check').forEach(function(c){if(c.value===e.entity_name)c.checked=cb.checked;});});updateSel();}
        function updateSel(){const n=document.querySelectorAll('.entity-check:checked').length;document.getElementById('selCount').textContent=n;}
        async function importSelected(){const checks=document.querySelectorAll('.entity-check:checked');const selected=[];checks.forEach(function(c){selected.push(c.value);});if(!selected.length){t('Select metrics to import first','','bg-orange-500 text-white');return;}try{const r=await apiPost('/api/easyq2sql/v1/metric-graph/draft/import',{selected:selected});renderImportReport(r);await loadDraft();const imported=Object.entries(r.imported||{}).map(function(kv){return kv[0]+': '+kv[1].length;}).join(', ');const skipped=(r.skipped||[]).length;let msg='Import complete: '+imported;if(skipped)msg+='; skipped '+skipped+' items (see report)';t(msg,skipped?4000:2000,skipped?'bg-orange-500 text-white':'bg-green-600 text-white');}catch(e){t('Import failed: '+e.message,'','bg-red-500 text-white');}}
        function renderImportReport(r){const box=document.getElementById('importReport');const imp=Object.entries(r.imported||{}).map(function(kv){return '<div class="text-sm text-gray-700">'+esc(kv[0])+': '+kv[1].map(esc).join(', ')+'</div>';}).join('');const skp=(r.skipped||[]).map(function(s){return '<div class="text-xs text-red-500">✗ '+esc(s.entity_name)+' — '+esc(s.reason)+'</div>';}).join('');box.innerHTML='<div class="text-sm font-semibold text-gray-900 mb-2">Import Report</div>'+imp+(skp?'<div class="mt-2 border-t border-gray-100 pt-2">'+skp+'</div>':'')+'<div class="mt-2 text-xs text-gray-400">After importing, click "Sync to Neo4j" (top-right) to rebuild the graph index.</div>';box.classList.remove('hidden');}
        async function syncGraph(){const btn=event.target;btn.disabled=true;btn.textContent='⏳ Syncing...';try{const r=await apiPost('/api/easyq2sql/v1/metric-graph/sync',{});t('Graph synced: '+r.nodes+' nodes, '+r.edges+' edges ✓','','bg-green-600 text-white');}catch(e){t('Sync failed: '+e.message,'','bg-red-500 text-white');}finally{btn.disabled=false;btn.textContent='🔗 Sync to Neo4j';}}
        loadTables(); loadDraft();
    </script>"""
    return _admin_page_wrapper("Metric Graph", body, api_base_url, active="metric-graph")
