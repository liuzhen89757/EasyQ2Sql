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
# Metric Management Page (prototype-aligned)
# =========================================================================

def get_metric_admin_html(api_base_url: str = "") -> str:
    """Generate the unified Admin Console with sidebar navigation.

    Three-column layout (sidebar + top bar + content area) switching between
    Metrics, Dimensions, and Terminology management sections.
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Console — EasyQ2Sql</title>
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
/* ===== CSS Variables ===== */
:root {{
  --blue-500: #1677ff; --blue-50: #e6f4ff; --blue-100: #bae0ff; --blue-600: #0958d9;
  --red-500: #f5222d; --red-50: #fff1f0;
  --green-500: #52c41a; --green-50: #f6ffed;
  --orange-500: #fa8c16; --orange-50: #fff7e6;
  --cyan-500: #08979c; --cyan-50: #e6fffb;
  --gray-50: #fafafa; --gray-100: #f5f5f5; --gray-200: #f0f0f0; --gray-300: #d9d9d9;
  --gray-400: #bfbfbf; --gray-500: #8c8c8c; --gray-600: #595959;
  --gray-700: #434343; --gray-800: #262626; --gray-900: #1f1f1f;
  --white: #ffffff;
  --shadow-sm: 0 1px 2px 0 rgba(0,0,0,.03),0 1px 6px -1px rgba(0,0,0,.02),0 2px 4px 0 rgba(0,0,0,.02);
  --shadow-md: 0 6px 16px 0 rgba(0,0,0,.08),0 3px 6px -4px rgba(0,0,0,.12),0 9px 28px 8px rgba(0,0,0,.05);
  --radius: 6px; --radius-sm: 4px; --radius-lg: 8px;
  --sider-w: 220px; --header-h: 56px;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{
  font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans","PingFang SC","Microsoft YaHei",sans-serif;
  font-size:14px;color:var(--gray-800);background:var(--gray-50);
  -webkit-font-smoothing:antialiased;
}}
.layout{{display:flex;min-height:100vh}}
/* ===== Left Sider ===== */
.sider{{
  width:var(--sider-w);min-width:var(--sider-w);max-width:var(--sider-w);
  background:var(--white);border-right:1px solid var(--gray-200);
  display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;z-index:100;
}}
.sider-logo{{
  height:var(--header-h);display:flex;align-items:center;padding:0 20px;
  border-bottom:1px solid var(--gray-200);gap:10px;flex-shrink:0;
}}
.sider-logo .logo-icon{{width:32px;height:32px;background:var(--blue-500);border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;color:var(--white);font-size:16px;font-weight:700}}
.sider-logo .logo-text{{font-size:16px;font-weight:600;color:var(--gray-900);white-space:nowrap}}
.sider-nav{{flex:1;overflow-y:auto;padding:8px 0}}
.nav-group{{margin-bottom:4px}}
.nav-group-title{{font-size:12px;color:var(--gray-400);padding:8px 20px 4px;text-transform:uppercase;letter-spacing:.5px}}
.nav-item{{
  display:flex;align-items:center;gap:10px;padding:9px 20px;margin:2px 8px;border-radius:var(--radius-sm);
  color:var(--gray-600);cursor:pointer;font-size:14px;transition:all .15s;white-space:nowrap;border:none;background:none;width:calc(100% - 16px);text-align:left;
}}
.nav-item:hover{{color:var(--gray-900);background:var(--gray-100)}}
.nav-item.active{{color:var(--blue-500);background:var(--blue-50);font-weight:500}}
.nav-item .nav-icon{{width:16px;text-align:center;font-size:14px}}
.nav-item .nav-badge{{margin-left:auto;font-size:12px;background:var(--gray-200);color:var(--gray-600);padding:0 6px;border-radius:10px;min-width:20px;text-align:center}}
/* ===== Main Area ===== */
.main{{margin-left:var(--sider-w);flex:1;display:flex;flex-direction:column;min-height:100vh}}
.header{{
  height:var(--header-h);background:var(--white);border-bottom:1px solid var(--gray-200);
  display:flex;align-items:center;justify-content:space-between;padding:0 24px;
  position:sticky;top:0;z-index:50;gap:16px;
}}
.header-left{{display:flex;align-items:center;gap:12px}}
.header-breadcrumb{{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--gray-500)}}
.header-breadcrumb span{{color:var(--gray-800);font-weight:500}}
.header-right{{display:flex;align-items:center;gap:16px}}
.header-external-links{{display:flex;align-items:center;gap:8px}}
.header-external-links a{{
  padding:5px 14px;border-radius:var(--radius-sm);font-size:12px;font-weight:500;
  text-decoration:none;transition:all .2s;white-space:nowrap;
  background:var(--blue-500);color:var(--white);
}}
.header-external-links a:hover{{background:var(--blue-600)}}
.header-external-links a.schema-btn{{background:var(--white);color:var(--gray-700);border:1px solid var(--gray-300)}}
.header-external-links a.schema-btn:hover{{color:var(--blue-500);border-color:var(--blue-500)}}
/* ===== Content ===== */
.content{{padding:24px;flex:1;display:flex;flex-direction:column;gap:20px;overflow-y:auto}}
.content-section{{display:none;flex-direction:column;gap:20px;flex:1}}
.content-section.active{{display:flex}}
/* ===== Stats Cards ===== */
.stats-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}
.stat-card{{
  background:var(--white);border-radius:var(--radius);padding:20px 24px;
  box-shadow:var(--shadow-sm);display:flex;align-items:center;gap:16px;
  transition:box-shadow .2s;border:1px solid var(--gray-200);cursor:default;
}}
.stat-card:hover{{box-shadow:var(--shadow-md)}}
.stat-icon{{width:48px;height:48px;border-radius:var(--radius);display:flex;align-items:center;justify-content:center;font-size:22px}}
.stat-icon.blue{{background:var(--blue-50);color:var(--blue-500)}}
.stat-icon.green{{background:var(--green-50);color:var(--green-500)}}
.stat-icon.orange{{background:var(--orange-50);color:var(--orange-500)}}
.stat-icon.red{{background:var(--red-50);color:var(--red-500)}}
.stat-icon.cyan{{background:var(--cyan-50);color:var(--cyan-500)}}
.stat-info{{flex:1}}
.stat-value{{font-size:28px;font-weight:600;color:var(--gray-900);line-height:1.2}}
.stat-label{{font-size:13px;color:var(--gray-500);margin-top:2px}}
/* ===== Toolbar ===== */
.toolbar{{
  background:var(--white);border-radius:var(--radius);padding:16px 20px;
  box-shadow:var(--shadow-sm);border:1px solid var(--gray-200);
  display:flex;align-items:center;gap:12px;flex-wrap:wrap;
}}
.toolbar-spacer{{flex:1}}
.btn{{
  height:32px;padding:0 16px;border-radius:var(--radius-sm);font-size:13px;cursor:pointer;
  display:inline-flex;align-items:center;gap:6px;border:1px solid transparent;
  transition:all .2s;font-weight:500;white-space:nowrap;
}}
.btn-primary{{background:var(--blue-500);color:var(--white);border-color:var(--blue-500)}}
.btn-primary:hover{{background:var(--blue-600)}}
.btn-outline{{background:var(--white);color:var(--gray-700);border-color:var(--gray-300)}}
.btn-outline:hover{{color:var(--blue-500);border-color:var(--blue-500)}}
.btn-link{{background:transparent;color:var(--blue-500);border:none;padding:0 4px;height:auto;cursor:pointer;font-size:13px}}
.btn-link:hover{{color:var(--blue-600)}}
.btn-link.danger{{color:var(--red-500)}}
.btn-link.danger:hover{{background:var(--red-50)}}
.btn-orange{{background:var(--white);color:var(--orange-500);border-color:var(--orange-500)}}
.btn-orange:hover{{background:var(--orange-500);color:var(--white)}}
/* ===== Table Card ===== */
.table-card{{
  background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow-sm);
  border:1px solid var(--gray-200);overflow:hidden;
}}
.table-card-header{{
  padding:16px 20px;border-bottom:1px solid var(--gray-200);
  font-size:15px;font-weight:600;color:var(--gray-900);
  display:flex;align-items:center;justify-content:space-between;
}}
.table-card-header .count{{font-size:13px;font-weight:400;color:var(--gray-500)}}
.data-table{{width:100%;border-collapse:collapse}}
.data-table th{{
  text-align:left;padding:12px 16px;font-size:13px;font-weight:500;color:var(--gray-500);
  background:var(--gray-50);border-bottom:1px solid var(--gray-200);white-space:nowrap;
}}
.data-table td{{padding:13px 16px;font-size:13px;color:var(--gray-700);border-bottom:1px solid var(--gray-100);vertical-align:middle}}
.data-table tbody tr{{transition:background .2s}}
.data-table tbody tr:hover{{background:var(--blue-50)}}
.data-table .col-name{{font-weight:500;color:var(--gray-900)}}
.data-table .col-name .metric-id{{font-size:12px;color:var(--gray-400);font-weight:400;margin-left:6px}}
.table-footer{{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;border-top:1px solid var(--gray-200);font-size:13px;color:var(--gray-500)}}
/* ===== Tags ===== */
.tag{{display:inline-flex;align-items:center;padding:1px 8px;border-radius:3px;font-size:12px;line-height:20px;border:1px solid}}
.tag-blue{{background:var(--blue-50);border-color:var(--blue-100);color:var(--blue-500)}}
.tag-green{{background:var(--green-50);border-color:#b7eb8f;color:var(--green-500)}}
.tag-gray{{background:var(--gray-100);border-color:var(--gray-300);color:var(--gray-600)}}
.tag-orange{{background:var(--orange-50);border-color:#ffd591;color:var(--orange-500)}}
.tag-cyan{{background:var(--cyan-50);border-color:#87e8de;color:var(--cyan-500)}}
/* ===== Dimension Tags ===== */
.dim-tags{{display:flex;flex-wrap:wrap;gap:6px;align-items:center}}
.dim-tag{{
  display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:4px;font-size:12px;line-height:22px;
  background:var(--gray-50);border:1px solid var(--gray-200);color:var(--gray-700);
  cursor:pointer;transition:all .15s;white-space:nowrap;
}}
.dim-tag:hover{{background:var(--blue-50);border-color:var(--blue-100);color:var(--blue-500)}}
.dim-tag.has-join{{border-style:dashed}}
.dim-tag-overflow{{
  display:inline-flex;align-items:center;padding:2px 10px;border-radius:4px;font-size:12px;line-height:22px;
  background:var(--blue-50);border:1px solid var(--blue-100);color:var(--blue-500);
  cursor:pointer;font-weight:500;
}}
/* ===== Synonym Tags ===== */
.syn-tag{{display:inline-flex;align-items:center;padding:1px 8px;border-radius:3px;font-size:12px;line-height:20px;background:var(--gray-50);border:1px solid var(--gray-200);color:var(--gray-600)}}
.syn-chip{{
  display:inline-flex;align-items:center;gap:4px;padding:2px 10px;border-radius:12px;
  font-size:12px;line-height:22px;background:var(--blue-50);border:1px solid var(--blue-100);color:var(--blue-500);
}}
.syn-chip button{{width:16px;height:16px;border:none;background:none;color:var(--gray-400);cursor:pointer;font-size:14px;line-height:1;padding:0;display:flex;align-items:center;justify-content:center}}
.syn-chip button:hover{{color:var(--red-500)}}
/* ===== Tabs ===== */
.tabs{{display:flex;gap:0;border-bottom:none}}
.tab-item{{
  padding:10px 20px;font-size:14px;color:var(--gray-500);cursor:pointer;
  border-bottom:2px solid transparent;transition:all .2s;margin-bottom:0;border-top:none;border-left:none;border-right:none;background:none;font-weight:500;
}}
.tab-item:hover{{color:var(--blue-500)}}
.tab-item.active{{color:var(--blue-500);border-bottom-color:var(--blue-500)}}
/* ===== Modal ===== */
.modal-overlay{{
  position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.45);z-index:1000;
  display:flex;align-items:flex-start;justify-content:center;padding-top:40px;display:none;
}}
.modal-overlay.show{{display:flex}}
.modal{{
  background:var(--white);border-radius:var(--radius-lg);box-shadow:var(--shadow-md);
  width:680px;max-width:92vw;max-height:88vh;display:flex;flex-direction:column;
}}
.modal.wide{{width:760px}}
.modal-header{{
  padding:16px 24px;border-bottom:1px solid var(--gray-200);
  font-size:16px;font-weight:600;display:flex;align-items:center;justify-content:space-between;
}}
.modal-close{{width:28px;height:28px;border:none;background:none;cursor:pointer;color:var(--gray-500);font-size:18px;border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center}}
.modal-close:hover{{background:var(--gray-100);color:var(--gray-800)}}
.modal-body{{padding:24px;overflow-y:auto;flex:1}}
.modal-footer{{padding:12px 24px;border-top:1px solid var(--gray-200);display:flex;justify-content:flex-end;gap:8px}}
/* ===== Form ===== */
.form-row{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
.form-group{{margin-bottom:16px}}
.form-label{{display:block;font-size:13px;font-weight:500;color:var(--gray-700);margin-bottom:6px}}
.form-label .required{{color:var(--red-500);margin-left:2px}}
.form-input,.form-textarea,.form-select{{
  width:100%;padding:6px 12px;border:1px solid var(--gray-300);border-radius:var(--radius-sm);
  font-size:13px;outline:none;font-family:inherit;transition:border-color .2s;
}}
.form-input:focus,.form-textarea:focus,.form-select:focus{{border-color:var(--blue-500);box-shadow:0 0 0 2px rgba(22,119,255,.1)}}
.form-textarea{{resize:vertical;min-height:60px}}
.form-select{{background:var(--white);cursor:pointer}}
.form-hint{{font-size:12px;color:var(--gray-400);margin-top:4px}}
/* ===== Join Row ===== */
.join-row{{
  display:grid;grid-template-columns:1fr 1fr 1fr 1fr 80px 32px;gap:6px;align-items:end;
  padding:8px 10px;background:var(--gray-50);border-radius:4px;border:1px solid var(--gray-200);margin-bottom:4px;
}}
.join-row .form-group{{margin-bottom:0}}
.join-row .form-label{{font-size:11px;color:var(--gray-500)}}
.join-remove{{width:28px;height:28px;border:1px solid var(--gray-300);background:var(--white);border-radius:var(--radius-sm);cursor:pointer;color:var(--red-500);font-size:16px;display:flex;align-items:center;justify-content:center}}
.join-remove:hover{{background:var(--red-50);border-color:var(--red-500)}}
/* ===== Toast ===== */
.toast{{
  position:fixed;top:24px;left:50%;transform:translateX(-50%);z-index:2000;
  background:var(--white);border-radius:var(--radius);box-shadow:var(--shadow-md);
  padding:10px 20px;display:flex;align-items:center;gap:8px;font-size:14px;
  border:1px solid var(--gray-200);display:none;
}}
.toast.show{{display:flex;animation:slideDown .3s ease}}
.toast.success{{border-color:#b7eb8f}}
.toast.error{{border-color:#ffa39e}}
@keyframes slideDown{{from{{opacity:0;transform:translateX(-50%) translateY(-12px)}}to{{opacity:1;transform:translateX(-50%) translateY(0)}}}}
</style>
</head>
<body>
<div class="layout">
<!-- ============ LEFT SIDEBAR ============ -->
<aside class="sider">
  <div class="sider-logo">
    <div class="logo-icon">Q</div>
    <span class="logo-text">EasyQ2Sql</span>
  </div>
  <nav class="sider-nav">
    <div class="nav-group">
      <div class="nav-group-title">数据管理</div>
      <button class="nav-item active" data-section="metrics" onclick="switchSection('metrics',this)">
        <span class="nav-icon">📊</span> 指标配置
        <span class="nav-badge" id="badgeMetrics">0</span>
      </button>
      <button class="nav-item" data-section="dimensions" onclick="switchSection('dimensions',this)">
        <span class="nav-icon">📐</span> 维度配置
        <span class="nav-badge" id="badgeDimensions">0</span>
      </button>
      <button class="nav-item" data-section="terminology" onclick="switchSection('terminology',this)">
        <span class="nav-icon">🏷️</span> 术语映射
        <span class="nav-badge" id="badgeTerminology">0</span>
      </button>
    </div>
    <div class="nav-group">
      <div class="nav-group-title">数据资产</div>
      <a href="{api_base_url}/admin/schema" style="text-decoration:none"><button class="nav-item">
        <span class="nav-icon">🗄️</span> Schema 管理
      </button></a>
    </div>
  </nav>
</aside>

<!-- ============ MAIN AREA ============ -->
<div class="main">
  <!-- Top Header -->
  <header class="header">
    <div class="header-left">
      <div class="header-breadcrumb">数据管理 / <span id="breadcrumbLabel">指标配置</span></div>
    </div>
    <div class="header-right">
      <div class="header-external-links">
        <a href="{api_base_url}/" class="schema-btn">💬 Chat</a>
        <a href="{api_base_url}/admin/schema" class="schema-btn">🗄️ Schema</a>
      </div>
    </div>
  </header>

  <!-- ===== SECTION: Metrics ===== -->
  <div class="content-section active" id="sec-metrics">
    <div class="stats-row">
      <div class="stat-card"><div class="stat-icon blue">📊</div><div class="stat-info"><div class="stat-value" id="statMetricTotal">0</div><div class="stat-label">已配置指标</div></div></div>
      <div class="stat-card"><div class="stat-icon green">📐</div><div class="stat-info"><div class="stat-value" id="statMetricTables">0</div><div class="stat-label">数据表来源</div></div></div>
      <div class="stat-card"><div class="stat-icon orange">🔢</div><div class="stat-info"><div class="stat-value" id="statMetricCalcs">0</div><div class="stat-label">计算逻辑类型</div></div></div>
      <div class="stat-card"><div class="stat-icon red">⚠️</div><div class="stat-info"><div class="stat-value" id="statMetricNoBiz">0</div><div class="stat-label">待完善指标</div></div></div>
    </div>
    <div class="toolbar">
      <input id="metricSearch" placeholder="🔍 搜索指标名称 / 业务定义..." oninput="renderMetrics()" class="form-input" style="width:280px">
      <button class="btn btn-outline" onclick="document.getElementById('metricSearch').value='';renderMetrics()">↻ 重置</button>
      <div class="toolbar-spacer"></div>
      <button class="btn btn-primary" onclick="openMetricModal()">+ 新建指标</button>
    </div>
    <div class="table-card">
      <div class="table-card-header">指标列表 <span class="count">共 <b id="totalMetricCount">0</b> 条</span></div>
      <div style="overflow-x:auto"><table class="data-table"><thead><tr><th>指标名称</th><th>业务定义</th><th>更新时间</th><th style="width:110px">操作</th></tr></thead><tbody id="metricTableBody"></tbody></table></div>
      <div class="table-footer"><span id="metricPageInfo"></span></div>
    </div>
  </div>

  <!-- ===== SECTION: Dimensions ===== -->
  <div class="content-section" id="sec-dimensions">
    <div class="stats-row">
      <div class="stat-card"><div class="stat-icon blue">📐</div><div class="stat-info"><div class="stat-value" id="statDimTotal">0</div><div class="stat-label">维度总数</div></div></div>
      <div class="stat-card"><div class="stat-icon green">🔗</div><div class="stat-info"><div class="stat-value" id="statDimLinked">0</div><div class="stat-label">已关联指标</div></div></div>
      <div class="stat-card"><div class="stat-icon orange">🌳</div><div class="stat-info"><div class="stat-value" id="statDimBizDef">0</div><div class="stat-label">含业务定义</div></div></div>
      <div class="stat-card"><div class="stat-icon red">⚠️</div><div class="stat-info"><div class="stat-value" id="statDimNoJoin">0</div><div class="stat-label">JOIN 未配置</div></div></div>
    </div>
    <div class="toolbar">
      <input id="dimSearch" placeholder="🔍 搜索指标名称 / 维度名称..." oninput="renderDimensions()" class="form-input" style="width:280px">
      <button class="btn btn-outline" onclick="document.getElementById('dimSearch').value='';renderDimensions()">↻ 重置</button>
      <div class="toolbar-spacer"></div>
      <button class="btn btn-primary" onclick="openDimModal()">+ 新建维度</button>
    </div>
    <div class="table-card">
      <div class="table-card-header">维度列表 <span class="count">共 <b id="totalDimMetricCount">0</b> 个指标，<b id="totalDimCount">0</b> 个维度</span></div>
      <div style="overflow-x:auto"><table class="data-table"><thead><tr><th style="width:160px">关联指标</th><th>关联维度</th><th style="width:140px">更新时间</th><th style="width:130px">操作</th></tr></thead><tbody id="dimTableBody"></tbody></table></div>
      <div class="table-footer"><span id="dimPageInfo"></span></div>
    </div>
  </div>

  <!-- ===== SECTION: Terminology ===== -->
  <div class="content-section" id="sec-terminology">
    <div class="stats-row">
      <div class="stat-card"><div class="stat-icon blue">🏷️</div><div class="stat-info"><div class="stat-value" id="statTermTotal">0</div><div class="stat-label">术语总数</div></div></div>
      <div class="stat-card"><div class="stat-icon orange">✏️</div><div class="stat-info"><div class="stat-value" id="statTermManual">0</div><div class="stat-label">手动配置</div></div></div>
      <div class="stat-card"><div class="stat-icon green">⚡</div><div class="stat-info"><div class="stat-value" id="statTermAuto">0</div><div class="stat-label">自动生成</div></div></div>
      <div class="stat-card"><div class="stat-icon cyan">🎯</div><div class="stat-info"><div class="stat-value" id="statTermCoverage">0</div><div class="stat-label">覆盖指标/维度</div></div></div>
    </div>
    <div class="toolbar">
      <input id="termSearch" placeholder="🔍 搜索术语文本 / 同义词..." oninput="renderTerminology()" class="form-input" style="width:280px">
      <select id="termTargetFilter" onchange="renderTerminology()" class="form-select" style="width:140px"><option value="">全部类型</option><option value="metric">→ 指标</option><option value="dimension">→ 维度</option></select>
      <button class="btn btn-outline" onclick="document.getElementById('termSearch').value='';document.getElementById('termTargetFilter').value='';termTab='all';const tabs=document.querySelectorAll('#termTabs .tab-item');tabs.forEach(b=>b.classList.remove('active'));if(tabs[0])tabs[0].classList.add('active');renderTermTabs();renderTerminology()">↻ 重置</button>
      <div class="toolbar-spacer"></div>
      <button class="btn btn-orange" onclick="syncAutoTerms()">🔄 同步自动映射</button>
      <button class="btn btn-primary" onclick="openTermModal()">+ 新建映射</button>
    </div>
    <div class="table-card">
      <div class="table-card-header">
        <div class="tabs" id="termTabs">
          <button class="tab-item active" onclick="switchTermTab('all',this)">全部 <span style="color:var(--gray-400)">0</span></button>
          <button class="tab-item" onclick="switchTermTab('manual',this)">手动配置 <span style="color:var(--gray-400)">0</span></button>
          <button class="tab-item" onclick="switchTermTab('auto',this)">自动生成 <span style="color:var(--gray-400)">0</span></button>
        </div>
        <span class="count">共 <b id="totalTermCount">0</b> 条</span>
      </div>
      <div style="overflow-x:auto"><table class="data-table"><thead><tr><th style="width:130px">术语文本</th><th style="width:140px">映射目标</th><th>业务定义</th><th>同义词</th><th style="width:70px">来源</th><th style="width:130px">更新时间</th><th style="width:100px">操作</th></tr></thead><tbody id="termTableBody"></tbody></table></div>
      <div class="table-footer"><span id="termPageInfo"></span></div>
    </div>
  </div>
</div><!-- .main -->
</div><!-- .layout -->

<!-- ============ METRIC MODAL ============ -->
<div class="modal-overlay" id="metricModal">
  <div class="modal">
    <div class="modal-header"><span id="metricModalTitle">新建指标</span><button class="modal-close" onclick="closeMetricModal()">✕</button></div>
    <div class="modal-body">
      <input type="hidden" id="metricEditId">
      <div class="form-group"><label class="form-label">指标名称 <span class="required">*</span></label><input class="form-input" id="mf-name" placeholder="如：订单数量"></div>
      <div class="form-group"><label class="form-label">业务定义</label><textarea class="form-textarea" id="mf-bizdef" placeholder="说明指标的业务含义，如：统计有效订单的总数"></textarea></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">计算逻辑</label><select class="form-select" id="mf-calc"><option value="">无（直接取值）</option><option>COUNT</option><option>COUNT(DISTINCT)</option><option>SUM</option><option>AVG</option><option>MAX</option><option>MIN</option></select></div>
        <div class="form-group"><label class="form-label">数据表来源 <span class="required">*</span></label><select class="form-select" id="mf-table" onchange="onMetricTableChange()"><option value="">请选择数据表</option></select></div>
      </div>
      <div class="form-group"><label class="form-label">分析字段 <span class="required">*</span></label><select class="form-select" id="mf-field"><option value="">请先选择数据表</option></select><p class="form-hint">格式：table.column，如 ods_order.order_id</p></div>
    </div>
    <div class="modal-footer"><button class="btn btn-outline" onclick="closeMetricModal()">取消</button><button class="btn btn-primary" onclick="saveMetric()">✓ 保存</button></div>
  </div>
</div>

<!-- ============ DIMENSION MODAL ============ -->
<div class="modal-overlay" id="dimModal">
  <div class="modal wide">
    <div class="modal-header"><span id="dimModalTitle">新建维度</span><button class="modal-close" onclick="closeDimModal()">✕</button></div>
    <div class="modal-body">
      <input type="hidden" id="dimEditId">
      <div class="form-group"><label class="form-label">关联指标 <span class="required">*</span></label><select class="form-select" id="df-metric" onchange="onDimMetricChange()"><option value="">请选择已配置的指标</option></select></div>
      <div class="form-group"><label class="form-label">维度名称 <span class="required">*</span></label><input class="form-input" id="df-name" placeholder="如：时间"></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">数据表来源 <span class="required">*</span></label><select class="form-select" id="df-table" onchange="onDimTableChange()"><option value="">请选择维表</option></select></div>
        <div class="form-group"><label class="form-label">数据库字段 <span class="required">*</span></label><select class="form-select" id="df-field"><option value="">请先选择维表</option></select></div>
      </div>
      <div class="form-group"><label class="form-label">取值范围 <button onclick="autoFillDimRange()" class="btn-link" style="font-weight:400;margin-left:4px" title="从数据库自动获取该字段的去重值（≤20条）">⚡ 自动生成</button></label><input class="form-input" id="df-range" placeholder="如：2020-01-01 ~ 今日"></div>
      <div class="form-group"><label class="form-label">业务定义</label><textarea class="form-textarea" id="df-bizdef" placeholder="说明维度的业务含义"></textarea></div>
      <div class="form-group">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px"><span class="form-label" style="margin-bottom:0">表连接关系 (JOIN)</span><button class="btn-link" onclick="addJoinRow()">+ 添加 JOIN 子句</button></div>
        <div id="joinContainer"><div style="font-size:12px;color:var(--gray-400);padding:4px 0">暂未配置 JOIN（如维表与事实表可直接关联则无需 JOIN）</div></div>
      </div>
    </div>
    <div class="modal-footer"><button class="btn btn-outline" onclick="closeDimModal()">取消</button><button class="btn btn-primary" onclick="saveDim()">✓ 保存</button></div>
  </div>
</div>

<!-- ============ TERMINOLOGY MODAL ============ -->
<div class="modal-overlay" id="termModal">
  <div class="modal">
    <div class="modal-header"><span id="termModalTitle">新建术语映射</span><button class="modal-close" onclick="closeTermModal()">✕</button></div>
    <div class="modal-body">
      <input type="hidden" id="termEditId">
      <div class="form-group"><label class="form-label">术语文本 <span class="required">*</span></label><input class="form-input" id="tf-term" placeholder="如：OEE、上月、订单量"><p class="form-hint">用户在自然语言中可能使用的业务术语</p></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">映射目标类型 <span class="required">*</span></label><select class="form-select" id="tf-type" onchange="onTermTypeChange()"><option value="">请选择</option><option value="metric">指标</option><option value="dimension">维度</option></select></div>
        <div class="form-group"><label class="form-label">映射目标 <span class="required">*</span></label><select class="form-select" id="tf-target"><option value="">请先选择映射目标类型</option></select></div>
      </div>
      <div class="form-group"><label class="form-label">同义词</label><div id="synList" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px"></div><div style="display:flex;gap:8px"><input class="form-input" id="synInput" placeholder="输入同义词后回车添加" onkeydown="if(event.key==='Enter'){{event.preventDefault();addSyn()}}" style="flex:1"><button class="btn btn-outline" onclick="addSyn()">添加</button></div><p class="form-hint">同义词也将参与检索匹配</p></div>
      <div class="form-group"><label class="form-label">业务定义</label><textarea class="form-textarea" id="tf-bizdef" placeholder="说明该术语的业务含义"></textarea><p class="form-hint">自动生成时从关联的指标/维度继承业务定义</p></div>
      <div class="form-group" id="overrideHint" style="display:none"><div style="padding:10px 14px;background:var(--orange-50);border:1px solid #ffd591;border-radius:var(--radius-sm);font-size:12px;color:var(--orange-500)">⚠️ 此操作为手动配置，将覆盖同术语的自动生成映射。</div></div>
    </div>
    <div class="modal-footer"><button class="btn btn-outline" onclick="closeTermModal()">取消</button><button class="btn btn-primary" onclick="saveTerm()">✓ 保存</button></div>
  </div>
</div>

<!-- ============ TOAST ============ -->
<div class="toast" id="toast"></div>

<script>
const API = '{api_base_url}';
function esc(s){{return(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}}
let toastTimer;
function showToast(msg,type){{
  const t=document.getElementById('toast');t.textContent=msg;
  t.className='toast show '+(type||'success');clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>t.classList.remove('show'),2000);
}}
async function apiGet(path){{
  const r=await fetch(API+path);if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json();
}}
async function apiPost(path,body){{
  const r=await fetch(API+path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json();
}}
async function apiPut(path,body){{
  const r=await fetch(API+path,{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json();
}}
async function apiDelete(path){{
  const r=await fetch(API+path,{{method:'DELETE'}});
  if(!r.ok)throw new Error((await r.json()).detail||r.statusText);return r.json();
}}

// ===== GLOBAL STATE =====
let allMetrics=[],allDims=[],allTerms=[],allTables=[],columnCache={{}};
let currentSection='metrics';

// ===== SECTION SWITCHING =====
function switchSection(section,el){{
  if(currentSection===section)return;
  currentSection=section;
  document.querySelectorAll('.nav-item[data-section]').forEach(b=>b.classList.remove('active'));
  if(el)el.classList.add('active');
  document.querySelectorAll('.content-section').forEach(s=>s.classList.remove('active'));
  document.getElementById('sec-'+section).classList.add('active');
  const labels={{metrics:'指标配置',dimensions:'维度配置',terminology:'术语映射'}};
  document.getElementById('breadcrumbLabel').textContent=labels[section]||'';
}}
function updateBadges(){{
  document.getElementById('badgeMetrics').textContent=allMetrics.length;
  document.getElementById('badgeDimensions').textContent=allDims.length;
  document.getElementById('badgeTerminology').textContent=allTerms.length;
}}

// ===== TABLE COLUMN HELPERS =====
async function getCols(tn){{
  if(!tn)return[];if(columnCache[tn])return columnCache[tn];
  try{{const t=await apiGet('/api/easyq2sql/v1/schema/tables/'+encodeURIComponent(tn));columnCache[tn]=(t&&t.columns)?t.columns:[];return columnCache[tn];}}catch(e){{return[];}}
}}
async function popCol(sel,tn,preselected){{
  sel.innerHTML='<option value="">-- 选择字段 --</option>';if(!tn)return;
  const cols=await getCols(tn);
  sel.innerHTML+=cols.map(c=>`<option value="${{tn}}.${{c.name}}" ${{preselected===tn+'.'+c.name?'selected':''}}>${{c.name}}${{c.description?' -- '+esc(c.description):''}}</option>`).join('');
}}
function popTableOpts(sel,preselected){{
  const o=allTables.map(t=>`<option value="${{t.table_name}}" ${{preselected===t.table_name?'selected':''}}>${{t.table_name}}${{t.description?' - '+esc(t.description):''}}</option>`).join('');
  sel.innerHTML='<option value="">请选择数据表</option>'+o;
}}

// ================================================================
// METRICS
// ================================================================
function renderMetrics(){{
  const s=document.getElementById('metricSearch').value.toLowerCase();
  const data=allMetrics.filter(m=>(!s||m.name.toLowerCase().includes(s)||(m.business_definition||'').toLowerCase().includes(s)||m.id.toLowerCase().includes(s)));
  const tb=document.getElementById('metricTableBody');
  document.getElementById('totalMetricCount').textContent=data.length;
  document.getElementById('metricPageInfo').textContent='显示 '+data.length+' 条';
  document.getElementById('statMetricTotal').textContent=allMetrics.length;
  document.getElementById('statMetricTables').textContent=new Set(allMetrics.map(m=>m.data_source).filter(Boolean)).size;
  document.getElementById('statMetricCalcs').textContent=new Set(allMetrics.map(m=>m.calculation_logic).filter(Boolean)).size;
  document.getElementById('statMetricNoBiz').textContent=allMetrics.filter(m=>!m.business_definition).length;
  if(!data.length){{tb.innerHTML='<tr><td colspan="4" style="text-align:center;padding:40px;color:var(--gray-400)">📋 暂无数据</td></tr>';return;}}
  tb.innerHTML=data.map(m=>{{
    const tv=m.updated_at||m.created_at||'';
    return`<tr><td class="col-name">${{esc(m.name)}}<span class="metric-id">${{esc(m.id)}}</span></td><td style="max-width:240px;overflow:hidden;text-overflow:ellipsis" title="${{esc(m.business_definition||'')}}">${{esc(m.business_definition||'-')}}</td><td style="color:var(--gray-500);font-size:12px">${{esc(typeof tv==='string'?tv.substring(0,16):'')}}</td><td style="white-space:nowrap"><button class="btn-link" onclick="editMetric('${{m.id}}')">编辑</button><button class="btn-link danger" onclick="deleteMetric('${{m.id}}')">删除</button></td></tr>`;
  }}).join('');
}}
 async function loadMetrics(){{
  try{{allMetrics=await apiGet('/api/easyq2sql/v1/metrics');}}catch(e){{allMetrics=[];}}
  renderMetrics();updateBadges();
}}
function openMetricModal(mid){{
  document.getElementById('metricEditId').value=mid||'';
  document.getElementById('metricModalTitle').textContent=mid?'编辑指标':'新建指标';
  document.getElementById('mf-name').value='';document.getElementById('mf-bizdef').value='';
  document.getElementById('mf-calc').value='';document.getElementById('mf-table').value='';
  document.getElementById('mf-field').innerHTML='<option value="">请先选择数据表</option>';
  popTableOpts(document.getElementById('mf-table'));
  if(mid){{
    const m=allMetrics.find(x=>x.id===mid);if(!m)return;
    document.getElementById('mf-name').value=m.name;
    document.getElementById('mf-bizdef').value=m.business_definition||'';
    document.getElementById('mf-calc').value=m.calculation_logic||'';
    document.getElementById('mf-table').value=m.data_source||'';
    popTableOpts(document.getElementById('mf-table'),m.data_source);
    onMetricTableChange(m.analysis_field);
  }}
  document.getElementById('metricModal').classList.add('show');
}}
function closeMetricModal(){{document.getElementById('metricModal').classList.remove('show');}}
async function onMetricTableChange(pf){{
  const tn=document.getElementById('mf-table').value;
  await popCol(document.getElementById('mf-field'),tn,pf||'');
}}
async function saveMetric(){{
  const id=document.getElementById('metricEditId').value;
  const name=document.getElementById('mf-name').value.trim();
  const bizDef=document.getElementById('mf-bizdef').value.trim();
  const calc=document.getElementById('mf-calc').value;
  const ds=document.getElementById('mf-table').value;
  const field=document.getElementById('mf-field').value;
  if(!name||!ds||!field){{showToast('请填写所有必填字段','error');return;}}
  const body={{name,business_definition:bizDef||null,calculation_logic:calc||null,data_source:ds,analysis_field:field,description:null}};
  try{{
    if(id){{await apiPut('/api/easyq2sql/v1/metrics/'+encodeURIComponent(id),body);showToast('指标更新成功 ✓');}}
    else{{await apiPost('/api/easyq2sql/v1/metrics',body);showToast('指标创建成功 ✓');}}
    closeMetricModal();await loadMetrics();
  }}catch(e){{showToast('保存失败: '+e.message,'error');}}
}}
function editMetric(id){{openMetricModal(id);}}
async function deleteMetric(id){{
  if(!confirm('确认删除该指标？'))return;
  try{{await apiDelete('/api/easyq2sql/v1/metrics/'+encodeURIComponent(id));showToast('已删除');await loadMetrics();}}catch(e){{showToast('删除失败: '+e.message,'error');}}
}}

// ================================================================
// DIMENSIONS
// ================================================================
const MAX_VISIBLE_TAGS=4;
let tempJoins=[];
function metricName(mid){{const m=allMetrics.find(x=>x.id===mid);return m?m.name:mid;}}
function groupByMetric(filtered){{
  const map=new Map();
  for(const d of filtered){{if(!map.has(d.metric_id))map.set(d.metric_id,[]);map.get(d.metric_id).push(d);}}
  for(const dims of map.values()){{dims.sort((a,b)=>(a.name||'').localeCompare(b.name||''));}}
  return map;
}}
function renderDimensions(){{
  const s=document.getElementById('dimSearch').value.toLowerCase();
  const filtered=allDims.filter(d=>{{
    const mn=metricName(d.metric_id).toLowerCase();
    return (!s||d.name.toLowerCase().includes(s)||mn.includes(s)||d.id.toLowerCase().includes(s));
  }});
  const grouped=groupByMetric(filtered);
  const tb=document.getElementById('dimTableBody');
  const mc=grouped.size,dc=filtered.length;
  document.getElementById('totalDimMetricCount').textContent=mc;
  document.getElementById('totalDimCount').textContent=dc;
  document.getElementById('dimPageInfo').textContent='显示 '+mc+' 个指标，共 '+dc+' 个维度';
  document.getElementById('statDimTotal').textContent=allDims.length;
  document.getElementById('statDimLinked').textContent=new Set(allDims.map(d=>d.metric_id)).size;
  document.getElementById('statDimBizDef').textContent=allDims.filter(d=>d.business_definition).length;
  document.getElementById('statDimNoJoin').textContent=allDims.filter(d=>!d.joins||!d.joins.length).length;
  if(!filtered.length){{tb.innerHTML='<tr><td colspan="4" style="text-align:center;padding:40px;color:var(--gray-400)">📐 暂无维度数据</td></tr>';return;}}
  const sorted=[...grouped.entries()].sort((a,b)=>b[1].length-a[1].length||metricName(a[0]).localeCompare(metricName(b[0])));
  tb.innerHTML=sorted.map(([mid,dims])=>{{
    const mn=metricName(mid);
    const latest=dims.reduce((t,d)=>(d.updated_at||d.created_at||'')>t?(d.updated_at||d.created_at||''):t,'');
    const vis=dims.slice(0,MAX_VISIBLE_TAGS),hid=dims.slice(MAX_VISIBLE_TAGS);
    const tags=vis.map(d=>{{
      const hj=d.joins&&d.joins.length>0;
      return`<span class="dim-tag${{hj?' has-join':''}}" onclick="editDim('${{d.id}}')" title="点击编辑">${{esc(d.name)}}</span>`;
    }}).join('');
    const overflow=hid.length>0?`<span class="dim-tag-overflow" onclick="this.style.display='none';this.parentElement.querySelectorAll('.hidden-tag').forEach(e=>e.style.display='inline-flex')">+${{hid.length}}</span>`:'';
    const hidden=hid.map(d=>`<span class="dim-tag hidden-tag${{d.joins&&d.joins.length?' has-join':''}}" style="display:none" onclick="editDim('${{d.id}}')">${{esc(d.name)}}</span>`).join('');
    return`<tr><td><div style="font-weight:500;color:var(--gray-900)">${{esc(mn)}}</div></td><td><div class="dim-tags">${{tags}}${{overflow}}${{hidden}}</div></td><td style="color:var(--gray-500);font-size:12px">${{esc(typeof latest==='string'?latest.substring(0,16):'')}}</td><td style="white-space:nowrap"><button class="btn-link" onclick="openDimModalForMetric('${{mid}}')">新增</button><button class="btn-link" onclick="editDim('${{dims[0].id}}')">编辑</button><button class="btn-link danger" onclick="deleteMetricDims('${{mid}}')">删除</button></td></tr>`;
  }}).join('');
}}
async function loadDimensions(){{
  try{{allDims=await apiGet('/api/easyq2sql/v1/dimensions');}}catch(e){{allDims=[];}}
  renderDimensions();updateBadges();
}}
function popDimTableOpts(presel){{
  const o=allTables.map(t=>`<option value="${{t.table_name}}" ${{presel===t.table_name?'selected':''}}>${{t.table_name}}${{t.description?' -- '+esc(t.description):''}}</option>`).join('');
  document.getElementById('df-table').innerHTML='<option value="">请选择维表</option>'+o;
}}
async function onDimTableChange(pf){{
  const tn=document.getElementById('df-table').value;
  await popCol(document.getElementById('df-field'),tn,pf||'');
  // Sync existing JOIN source_tables to the new dim table
  for(const j of tempJoins){{if(!j.source_table)j.source_table=tn;}}
  renderJoins();
}}
function onDimMetricChange(){{
  const metricId=document.getElementById('df-metric').value;
  const metric=allMetrics.find(m=>m.id===metricId);
  const metricTable=metric?metric.data_source||'':'';
  // Sync existing JOIN target_tables to the selected metric's table
  for(const j of tempJoins){{if(!j.target_table)j.target_table=metricTable;}}
  renderJoins();
}}
function addJoinRow(j){{
  // Auto-fill: LEFT=dimension table, RIGHT=metric table, user only picks columns
  const dimTable=document.getElementById('df-table').value||'';
  const metricId=document.getElementById('df-metric').value;
  const metric=allMetrics.find(m=>m.id===metricId);
  const metricTable=metric?metric.data_source||'':'';
  const jn=j||{{
    source_table:dimTable,
    source_column:'',
    target_table:metricTable,
    target_column:'',
    join_type:'INNER JOIN'
  }};
  tempJoins.push(jn);renderJoins();
}}
function removeJoinRow(i){{tempJoins.splice(i,1);renderJoins();}}
function renderJoins(){{
  const c=document.getElementById('joinContainer');
  if(!tempJoins.length){{c.innerHTML='<div style="font-size:12px;color:var(--gray-400);padding:4px 0">暂未配置 JOIN（如维表与事实表可直接关联则无需 JOIN）</div>';return;}}
  c.innerHTML=tempJoins.map((j,i)=>`<div class="join-row">
    <div class="form-group"><label class="form-label">维表（左）</label><select class="form-select" onchange="tempJoins[${{i}}].source_table=this.value;renderJoins()"><option value="">请选择</option>${{allTables.map(t=>`<option value="${{t.table_name}}" ${{j.source_table===t.table_name?'selected':''}}>${{t.table_name}}${{t.description?' -- '+esc(t.description):''}}</option>`).join('')}}</select></div>
    <div class="form-group"><label class="form-label">维表字段</label><select class="form-select join-source-field" data-idx="${{i}}" onchange="tempJoins[${{i}}].source_column=this.value"><option value="">-- 选择字段 --</option></select></div>
    <div class="form-group"><label class="form-label">指标表（右）</label><select class="form-select" onchange="tempJoins[${{i}}].target_table=this.value;renderJoins()"><option value="">请选择</option>${{allTables.map(t=>`<option value="${{t.table_name}}" ${{j.target_table===t.table_name?'selected':''}}>${{t.table_name}}${{t.description?' -- '+esc(t.description):''}}</option>`).join('')}}</select></div>
    <div class="form-group"><label class="form-label">指标表字段</label><select class="form-select join-target-field" data-idx="${{i}}" onchange="tempJoins[${{i}}].target_column=this.value"><option value="">-- 选择字段 --</option></select></div>
    <div class="form-group"><label class="form-label">类型</label><select class="form-select" onchange="tempJoins[${{i}}].join_type=this.value"><option value="LEFT JOIN" ${{j.join_type==='LEFT JOIN'?'selected':''}}>LEFT</option><option value="INNER JOIN" ${{j.join_type==='INNER JOIN'?'selected':''}}>INNER</option></select></div>
    <button class="join-remove" onclick="removeJoinRow(${{i}})">✕</button>
  </div>`).join('');
	setTimeout(()=>popJoinFields(),0);
	}}
	async function popJoinFields(){{
	  const srcSelects=document.querySelectorAll('.join-source-field');
	  const tgtSelects=document.querySelectorAll('.join-target-field');
	  for(const sel of srcSelects){{
	    const idx=parseInt(sel.dataset.idx);
	    const tableName=tempJoins[idx]?tempJoins[idx].source_table:'';
	    const currentVal=sel.value||tempJoins[idx]?.source_column||'';
	    if(tableName){{
	      const cols=await getCols(tableName);
	      sel.innerHTML='<option value="">-- 选择字段 --</option>'+cols.map(c=>`<option value="${{tableName}}.${{c.name}}" ${{currentVal===tableName+'.'+c.name?'selected':''}}>${{c.name}}${{c.description?' -- '+esc(c.description):''}}</option>`).join('');
	    }}else{{
	      sel.innerHTML='<option value="">-- 请先选择源表 --</option>';
	    }}
	  }}
	  for(const sel of tgtSelects){{
	    const idx=parseInt(sel.dataset.idx);
	    const tableName=tempJoins[idx]?tempJoins[idx].target_table:'';
	    const currentVal=sel.value||tempJoins[idx]?.target_column||'';
	    if(tableName){{
	      const cols=await getCols(tableName);
	      sel.innerHTML='<option value="">-- 选择字段 --</option>'+cols.map(c=>`<option value="${{tableName}}.${{c.name}}" ${{currentVal===tableName+'.'+c.name?'selected':''}}>${{c.name}}${{c.description?' -- '+esc(c.description):''}}</option>`).join('');
	    }}else{{
	      sel.innerHTML='<option value="">-- 请先选择目标表 --</option>';
	    }}
	  }}
	}}
function openDimModal(dimid){{
  document.getElementById('dimEditId').value=dimid||'';
  document.getElementById('dimModalTitle').textContent=dimid?'编辑维度':'新建维度';
  document.getElementById('df-name').value='';
  document.getElementById('df-range').value='';document.getElementById('df-bizdef').value='';
  document.getElementById('df-table').value='';document.getElementById('df-field').innerHTML='<option value="">请先选择维表</option>';
  
  tempJoins=[];renderJoins();popDimTableOpts();
  const ms=document.getElementById('df-metric');
  ms.innerHTML='<option value="">请选择已配置的指标</option>'+allMetrics.map(m=>`<option value="${{m.id}}">${{esc(m.name)}}</option>`).join('');
  if(dimid){{
    const d=allDims.find(x=>x.id===dimid);if(!d)return;
    document.getElementById('df-name').value=d.name;
    
    document.getElementById('df-range').value=d.value_range||'';
    document.getElementById('df-bizdef').value=d.business_definition||'';
    
    tempJoins=d.joins?JSON.parse(JSON.stringify(d.joins)):[];
    renderJoins();popDimTableOpts(d.data_source);
    onDimTableChange(d.field_ref);
    ms.value=d.metric_id;
    
  }}else{{ms.value='';}}
  document.getElementById('dimModal').classList.add('show');
}}
function openDimModalForMetric(mid){{openDimModal();document.getElementById('df-metric').value=mid;;}}
function closeDimModal(){{document.getElementById('dimModal').classList.remove('show');}}
function editDim(id){{openDimModal(id);}}
async function saveDim(){{
  const id=document.getElementById('dimEditId').value;
  const mid=document.getElementById('df-metric').value;
  const name=document.getElementById('df-name').value.trim();
  const ds=document.getElementById('df-table').value;
  const field=document.getElementById('df-field').value;
  if(!mid||!name||!ds||!field){{showToast('请填写所有必填字段','error');return;}}
  const body={{
    metric_id:mid,name,business_definition:document.getElementById('df-bizdef').value.trim()||null,
    value_range:document.getElementById('df-range').value.trim()||null,
    data_source:ds,field_ref:field,
    joins:tempJoins.filter(j=>j.source_table&&j.target_table),description:null
  }};
  try{{
    if(id){{await apiPut('/api/easyq2sql/v1/dimensions/'+encodeURIComponent(id),body);showToast('维度更新成功 ✓');}}
    else{{await apiPost('/api/easyq2sql/v1/dimensions',body);showToast('维度创建成功 ✓（系统将自动生成术语映射）');}}
    closeDimModal();await loadDimensions();await loadTerms();
  }}catch(e){{showToast('保存失败: '+e.message,'error');}}
}}
async function autoFillDimRange(){{
  const ds=document.getElementById('df-table').value;
  const fr=document.getElementById('df-field').value;
  if(!ds||!fr){{showToast('请先选择数据表和字段','error');return;}}
  const btn=event.target;btn.disabled=true;btn.textContent='⏳ 查询中...';
  try{{
    const r=await apiPost('/api/easyq2sql/v1/dimensions/auto-range',{{data_source:ds,field_ref:fr}});
    if(r.too_many){{showToast('该字段有 '+r.count+' 个去重值，超过 20 条，不自动填充。请手动输入取值范围','warning');}}
    else if(r.values&&r.values.length){{document.getElementById('df-range').value=r.values.join(';');showToast('已自动填入 '+r.values.length+' 个取值 ✓');}}
    else{{showToast('该字段无数据','warning');}}
  }}catch(e){{showToast('查询失败: '+e.message,'error');}}
  finally{{btn.disabled=false;btn.textContent='⚡ 自动生成';}}
}}
async function deleteMetricDims(mid){{
  const dims=allDims.filter(d=>d.metric_id===mid);
  if(!dims.length)return;
  const mn=metricName(mid);
  if(!confirm('确认删除指标「'+mn+'」下的全部 '+dims.length+' 个维度？'))return;
  for(const d of dims){{try{{await apiDelete('/api/easyq2sql/v1/dimensions/'+encodeURIComponent(d.id));}}catch(e){{}}}}
  showToast('已删除 '+dims.length+' 个维度');await loadDimensions();await loadTerms();
}}

// ================================================================
// TERMINOLOGY
// ================================================================
let termTab='all',tempSyns=[];
function renderTerminology(){{
  let data=[...allTerms];
  if(termTab==='manual')data=data.filter(t=>t.source==='manual');
  if(termTab==='auto')data=data.filter(t=>t.source==='auto');
  const s=document.getElementById('termSearch').value.toLowerCase();
  const tg=document.getElementById('termTargetFilter').value;
  data=data.filter(t=>(!s||t.term_text.toLowerCase().includes(s)||(t.synonyms||[]).some(sy=>sy.toLowerCase().includes(s)))&&(!tg||t.target_type===tg));
  const tb=document.getElementById('termTableBody');
  document.getElementById('totalTermCount').textContent=data.length;
  document.getElementById('termPageInfo').textContent='显示 '+data.length+' 条';
  const manual=allTerms.filter(t=>t.source==='manual').length;
  const auto=allTerms.filter(t=>t.source==='auto').length;
  document.getElementById('statTermTotal').textContent=allTerms.length;
  document.getElementById('statTermManual').textContent=manual;
  document.getElementById('statTermAuto').textContent=auto;
  document.getElementById('statTermCoverage').textContent=new Set(allTerms.map(t=>t.target_id)).size;
  if(!data.length){{tb.innerHTML='<tr><td colspan="7" style="text-align:center;padding:40px;color:var(--gray-400)">🏷️ 暂无术语数据</td></tr>';return;}}
  tb.innerHTML=data.map(t=>{{
    const st=t.source==='manual'?'<span class="tag tag-orange">手动</span>':'<span class="tag tag-green">自动</span>';
    const tt=t.target_type==='metric'?'<span class="tag tag-blue">指标</span>':'<span class="tag tag-cyan">维度</span>';
    const syns=(t.synonyms||[]).length?(t.synonyms||[]).map(s=>`<span class="syn-tag">${{esc(s)}}</span>`).join(' '):'<span style="color:var(--gray-400)">—</span>';
    const tv=t.updated_at||t.created_at||'';
    return`<tr><td style="font-weight:500;color:var(--gray-900)">${{esc(t.term_text)}}</td><td>${{tt}} <span style="font-size:12px;color:var(--gray-600)">${{esc(t.target_id)}}</span></td><td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;font-size:12px" title="${{esc(t.business_definition||'')}}">${{esc(t.business_definition||'-')}}</td><td>${{syns}}</td><td>${{st}}</td><td style="color:var(--gray-500);font-size:12px">${{esc(typeof tv==='string'?tv.substring(0,16):'')}}</td><td style="white-space:nowrap"><button class="btn-link" onclick="editTerm('${{t.id}}')">编辑</button><button class="btn-link danger" onclick="deleteTerm('${{t.id}}')">删除</button></td></tr>`;
  }}).join('');
}}
async function loadTerms(){{
  try{{allTerms=await apiGet('/api/easyq2sql/v1/terminology');}}catch(e){{allTerms=[];}}
  renderTermTabs();renderTerminology();updateBadges();
}}
function renderTermTabs(){{
  const manual=allTerms.filter(t=>t.source==='manual').length;
  const auto=allTerms.filter(t=>t.source==='auto').length;
  const tabs=document.getElementById('termTabs').querySelectorAll('.tab-item');
  tabs[0].innerHTML='全部 <span style="color:var(--gray-400)">'+allTerms.length+'</span>';
  tabs[1].innerHTML='手动配置 <span style="color:var(--gray-400)">'+manual+'</span>';
  tabs[2].innerHTML='自动生成 <span style="color:var(--gray-400)">'+auto+'</span>';
}}
function switchTermTab(tab,el){{
  termTab=tab;document.querySelectorAll('#termTabs .tab-item').forEach(b=>b.classList.remove('active'));el.classList.add('active');
  renderTerminology();
}}
function onTermTypeChange(){{
  const type=document.getElementById('tf-type').value;
  const sel=document.getElementById('tf-target');
  sel.innerHTML='<option value="">请选择</option>';
  if(type==='metric'){{
    sel.innerHTML+=allMetrics.map(m=>`<option value="${{m.id}}">${{esc(m.name)}}</option>`).join('');
    sel.onchange=function(){{const m=allMetrics.find(x=>x.id===sel.value);if(m&&!document.getElementById('tf-bizdef').value)document.getElementById('tf-bizdef').value=m.business_definition||'';}};
  }}else if(type==='dimension'){{
    sel.innerHTML+=allDims.map(d=>{{const mn=metricName(d.metric_id);return`<option value="${{d.id}}">${{esc(d.name)}}</option>`;}}).join('');
    sel.onchange=function(){{const d=allDims.find(x=>x.id===sel.value);if(d&&!document.getElementById('tf-bizdef').value)document.getElementById('tf-bizdef').value=d.business_definition||'';}};
  }}
}}
function renderSyns(){{
  const c=document.getElementById('synList');
  if(!tempSyns.length){{c.innerHTML='<span style="font-size:12px;color:var(--gray-400)">暂未添加同义词</span>';return;}}
  c.innerHTML=tempSyns.map((s,i)=>`<span class="syn-chip">${{esc(s)}}<button onclick="tempSyns.splice(${{i}},1);renderSyns()">✕</button></span>`).join('');
}}
function addSyn(){{const v=document.getElementById('synInput').value.trim();if(v&&!tempSyns.includes(v)){{tempSyns.push(v);document.getElementById('synInput').value='';renderSyns();}}}}
function openTermModal(tid){{
  document.getElementById('termEditId').value=tid||'';
  document.getElementById('termModalTitle').textContent=tid?'编辑术语映射':'新建术语映射';
  document.getElementById('tf-term').value='';document.getElementById('tf-type').value='';
  document.getElementById('tf-target').innerHTML='<option value="">请先选择映射目标类型</option>';
  document.getElementById('tf-bizdef').value='';tempSyns=[];renderSyns();
  document.getElementById('overrideHint').style.display='none';
  if(tid){{
    const t=allTerms.find(x=>x.id===tid);if(!t)return;
    document.getElementById('termModalTitle').textContent=t.source==='auto'?'编辑术语映射（覆盖自动生成）':'编辑术语映射';
    document.getElementById('tf-term').value=t.term_text;
    document.getElementById('tf-type').value=t.target_type;onTermTypeChange();
    document.getElementById('tf-target').value=t.target_id;
    document.getElementById('tf-bizdef').value=t.business_definition||'';
    tempSyns=[...(t.synonyms||[])];renderSyns();
    document.getElementById('overrideHint').style.display=t.source==='auto'?'block':'none';
  }}
  document.getElementById('termModal').classList.add('show');
}}
function closeTermModal(){{document.getElementById('termModal').classList.remove('show');}}
function editTerm(id){{openTermModal(id);}}
async function saveTerm(){{
  const id=document.getElementById('termEditId').value;
  const termText=document.getElementById('tf-term').value.trim();
  const type=document.getElementById('tf-type').value;
  const targetId=document.getElementById('tf-target').value;
  if(!termText||!type||!targetId){{showToast('请填写所有必填字段','error');return;}}
  const body={{term_text:termText,target_type:type,target_id:targetId,business_definition:document.getElementById('tf-bizdef').value.trim()||null,synonyms:tempSyns}};
  try{{
    if(id){{await apiPut('/api/easyq2sql/v1/terminology/'+encodeURIComponent(id),body);showToast('术语映射更新成功 ✓');}}
    else{{await apiPost('/api/easyq2sql/v1/terminology',body);showToast('术语映射创建成功 ✓');}}
    closeTermModal();await loadTerms();
  }}catch(e){{showToast('保存失败: '+e.message,'error');}}
}}
async function deleteTerm(id){{
  const t=allTerms.find(x=>x.id===id);
  const label=t&&t.source==='auto'?'此术语为自动生成，删除后可在下次同步时恢复。':'此操作为手动配置，删除后不可恢复。';
  if(!confirm('确认删除术语「'+(t?t.term_text:id)+'」？\\n'+label))return;
  try{{await apiDelete('/api/easyq2sql/v1/terminology/'+encodeURIComponent(id));showToast('已删除');await loadTerms();}}catch(e){{showToast('删除失败: '+e.message,'error');}}
}}
async function syncAutoTerms(){{
  if(!confirm('同步自动映射将根据当前指标和维度重新生成默认术语（不会覆盖手动配置）。确认继续？'))return;
  try{{const r=await apiPost('/api/easyq2sql/v1/terminology/sync',{{}});showToast('同步完成，已更新 '+r.auto_entries_synced+' 条映射 ✓');await loadTerms();}}catch(e){{showToast('同步失败: '+e.message,'error');}}
}}

// ===== KEYBOARD =====
document.addEventListener('keydown',function(e){{
  if(e.key==='Escape'){{closeMetricModal();closeDimModal();closeTermModal();}}
}});

// ===== INIT =====
async function init(){{
  try{{allTables=await apiGet('/api/easyq2sql/v1/schema/tables');}}catch(e){{allTables=[];}}
  await Promise.all([loadMetrics(),loadDimensions(),loadTerms()]);
}}
init();
</script>
</body>
</html>"""


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
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center text-2xl">📐</div><div><div class="text-2xl font-bold text-gray-900" id="statDimTotal">0</div><div class="text-xs text-gray-500">维度总数</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-green-50 text-green-500 flex items-center justify-center text-2xl">🔗</div><div><div class="text-2xl font-bold text-gray-900" id="statMetricLinked">0</div><div class="text-xs text-gray-500">已关联指标</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center text-2xl">🌳</div><div><div class="text-2xl font-bold text-gray-900" id="statHier">0</div><div class="text-xs text-gray-500">含业务定义</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-red-50 text-red-500 flex items-center justify-center text-2xl">⚠️</div><div><div class="text-2xl font-bold text-gray-900" id="statNoJoin">0</div><div class="text-xs text-gray-500">JOIN 未配置</div></div></div>
    </div>
    <!-- Toolbar -->
    <div class="bg-white rounded-lg p-4 border border-gray-200 flex items-center gap-3 flex-wrap mb-5">
        <input id="searchInput" placeholder="🔍 搜索指标名称 / 维度名称..." oninput="renderTable()" class="w-72 h-9 px-3 text-sm border border-gray-300 rounded-md focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal outline-none">
        <button onclick="resetFilters()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:text-easyq2sql-teal hover:border-easyq2sql-teal transition bg-white">↻ 重置</button>
        <div class="flex-1"></div>
        <button onclick="openCreateModal()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">+ 新建维度</button>
    </div>
    <!-- Table -->
    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div class="px-5 py-3 border-b border-gray-200 text-sm font-semibold text-gray-900 flex justify-between"><span>维度列表</span><span class="text-xs font-normal text-gray-500">共 <b id="totalMetricCount">0</b> 个指标，<b id="totalDimCount">0</b> 个维度</span></div>
        <div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="bg-gray-50 text-left text-xs text-gray-500 uppercase"><th class="py-3 px-4 w-40">关联指标</th><th class="py-3 px-4">关联维度</th><th class="py-3 px-4 w-44">更新时间</th><th class="py-3 px-4 w-32">操作</th></tr></thead><tbody id="tableBody"></tbody></table></div>
        <div class="px-5 py-3 border-t border-gray-200 text-xs text-gray-500 flex justify-between"><span id="pageInfo"></span></div>
    </div>
    <!-- Modal -->
    <div class="modal-overlay" id="dimModal" style="display:none" onclick="if(event.target===this)closeModal()">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-2xl max-h-[90vh] flex flex-col">
            <div class="px-6 py-4 border-b border-gray-200 text-base font-semibold flex items-center justify-between"><span id="modalTitle">新建维度</span><button onclick="closeModal()" class="text-gray-400 hover:text-gray-800 text-xl leading-none">&times;</button></div>
            <div class="p-6 overflow-y-auto flex-1 space-y-4">
                <input type="hidden" id="editId">
                <div><label class="block text-xs font-medium text-gray-600 mb-1">关联指标 <span class="text-red-500">*</span></label><select id="d-metric" onchange="onMetricChange()" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">请选择已配置的指标</option></select></div>
                <div class="grid grid-cols-2 gap-4">
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">维度名称 <span class="text-red-500">*</span></label><input id="d-name" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="如：时间"></div>

                </div>

                <div class="grid grid-cols-2 gap-4">
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">数据表来源 <span class="text-red-500">*</span></label><select id="d-table" onchange="onDimTableChange()" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">请选择维表</option></select></div>
                    <div><label class="block text-xs font-medium text-gray-600 mb-1">数据库字段 <span class="text-red-500">*</span></label><select id="d-field" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">请先选择维表</option></select></div>
                </div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">取值范围 <button onclick="autoFillRange()" class="ml-2 text-xs text-easyq2sql-teal hover:text-easyq2sql-navy border border-easyq2sql-teal rounded px-2 py-0.5 hover:bg-easyq2sql-teal hover:text-white transition" title="从数据库自动获取该字段的去重值（≤20条）">⚡ 自动生成</button></label><input id="d-range" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="如：2020-01-01 ~ 今日"></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">业务定义</label><textarea id="d-bizdef" rows="2" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="说明维度的业务含义"></textarea></div>
                <!-- JOIN section -->
                <div><div class="flex items-center justify-between mb-2"><span class="text-xs font-medium text-gray-500">表连接关系 (JOIN)</span><button onclick="addJoinRow()" class="text-xs text-easyq2sql-teal hover:text-easyq2sql-navy">+ 添加 JOIN 子句</button></div><div id="joinContainer"><div class="text-xs text-gray-400 py-1">暂未配置 JOIN（如维表与事实表可直接关联则无需 JOIN）</div></div></div>
            </div>
            <div class="px-6 py-3 border-t border-gray-200 flex justify-end gap-2"><button onclick="closeModal()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:bg-gray-100 bg-white">取消</button><button onclick="saveDim()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">✓ 保存</button></div>
        </div>
    </div>
    <!-- Toast -->
    <div class="toast-msg hidden" id="toast"></div>
    <script>
        let allDims=[],allMetrics=[],allTables=[],editingId=null,columnCache={},tempJoins=[];
        const MAX_TAGS=4;
        function esc(s){return(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
        function t(txt,ms,color){const e=document.getElementById('toast');e.textContent=txt;e.className='toast-msg '+color;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',ms||2000);}
        function metricName(mid){const m=allMetrics.find(x=>x.id===mid);return m?m.name:mid;}
        async function getCols(tn){if(!tn)return[];if(columnCache[tn])return columnCache[tn];try{const t=await apiGet('/api/easyq2sql/v1/schema/tables/'+encodeURIComponent(tn));columnCache[tn]=(t&&t.columns)?t.columns:[];return columnCache[tn];}catch(e){return[];}}
        async function popCol(sel,tn,preselected){sel.innerHTML='<option value="">-- 选择字段 --</option>';if(!tn)return;const cols=await getCols(tn);sel.innerHTML+=cols.map(c=>`<option value="${tn}.${c.name}" ${preselected===tn+'.'+c.name?'selected':''}>${c.name}${c.description?' -- '+esc(c.description):''}</option>`).join('');}
        async function init(){try{allTables=await apiGet('/api/easyq2sql/v1/schema/tables');}catch(e){allTables=[];}popDimTableOpts();await loadAll();}
        function popDimTableOpts(){const o=allTables.map(t=>`<option value="${t.table_name}">${t.table_name}${t.description?' -- '+esc(t.description):''}</option>`).join('');document.querySelectorAll('#d-table').forEach(s=>{const v=s.value;s.innerHTML='<option value="">请选择维表</option>'+o;s.value=v;});}
        async function loadAll(){try{allMetrics=await apiGet('/api/easyq2sql/v1/metrics');}catch(e){allMetrics=[];}try{allDims=await apiGet('/api/easyq2sql/v1/dimensions');}catch(e){allDims=[];}renderTable();}
        function groupByMetric(filtered){const map=new Map();for(const d of filtered){if(!map.has(d.metric_id))map.set(d.metric_id,[]);map.get(d.metric_id).push(d);}for(const dims of map.values()){dims.sort((a,b)=>(a.name||'').localeCompare(b.name||''));}return map;}
        function getFiltered(){const s=document.getElementById('searchInput').value.toLowerCase();return allDims.filter(dim=>{const mn=metricName(dim.metric_id).toLowerCase();return(!s||dim.name.toLowerCase().includes(s)||mn.includes(s)||dim.id.toLowerCase().includes(s));});}
        function renderTable(){const filtered=getFiltered();const grouped=groupByMetric(filtered);const tb=document.getElementById('tableBody');const mc=grouped.size;const dc=filtered.length;document.getElementById('totalMetricCount').textContent=mc;document.getElementById('totalDimCount').textContent=dc;document.getElementById('pageInfo').textContent=`显示 ${mc} 个指标，共 ${dc} 个维度`;document.getElementById('statDimTotal').textContent=allDims.length;document.getElementById('statMetricLinked').textContent=new Set(allDims.map(d=>d.metric_id)).size;document.getElementById('statHier').textContent=allDims.filter(d=>d.business_definition).length;document.getElementById('statNoJoin').textContent=allDims.filter(d=>!d.joins||!d.joins.length).length;if(!filtered.length){tb.innerHTML='<tr><td colspan="4" class="text-center py-10 text-gray-400">📐 暂无维度数据</td></tr>';return;}const sorted=[...grouped.entries()].sort((a,b)=>b[1].length-a[1].length||metricName(a[0]).localeCompare(metricName(b[0])));tb.innerHTML=sorted.map(([mid,dims])=>{const mn=metricName(mid);const latest=dims.reduce((t,d)=>(d.updated_at||d.created_at||'')>t?(d.updated_at||d.created_at||''):t,'');const vis=dims.slice(0,MAX_TAGS);const hid=dims.slice(MAX_TAGS);const tags=vis.map(d=>{const hj=d.joins&&d.joins.length>0;return`<span class="dim-tag${hj?' has-join':''}" onclick="editDim('${d.id}')" title="点击编辑 · ${esc(d.data_source)}.${esc(d.field_ref)}${hj?' · 含JOIN':''}">${esc(d.name)}</span>`;}).join('');const overflow=hid.length>0?`<span class="dim-tag-overflow" onclick="this.style.display='none';this.parentElement.querySelectorAll('.hidden-tag').forEach(e=>e.style.display='inline-flex')">+${hid.length}</span>`:'';const hidden=hid.map(d=>{const hj=d.joins&&d.joins.length>0;return`<span class="dim-tag hidden-tag${hj?' has-join':''}" style="display:none" onclick="editDim('${d.id}')" title="点击编辑">${esc(d.name)}</span>`;}).join('');return`<tr class="border-b border-gray-100 hover:bg-blue-50/30 transition"><td class="py-3 px-4"><div class="font-medium text-gray-900">${esc(mn)}</div></td><td class="py-3 px-4"><div class="flex flex-wrap gap-1.5 items-center">${tags}${overflow}${hidden}</div></td><td class="py-3 px-4 text-xs text-gray-500">${esc(typeof latest==='string'?latest.substring(0,16):'')}</td><td class="py-3 px-4 whitespace-nowrap"><button onclick="openCreateModalForMetric('${mid}')" class="text-easyq2sql-teal hover:text-easyq2sql-navy text-xs mr-1">新增</button><button onclick="editDim('${dims[0].id}')" class="text-easyq2sql-teal hover:text-easyq2sql-navy text-xs mr-1">编辑</button><button onclick="deleteMetricDims('${mid}')" class="text-red-500 hover:text-red-700 text-xs">删除</button></td></tr>`;}).join('');}
        function resetFilters(){document.getElementById('searchInput').value='';renderTable();}

        function addJoinRow(j){const jn=j||{source_table:'',source_column:'',target_table:'',target_column:'',join_type:'INNER JOIN'};tempJoins.push(jn);renderJoins();}
        function removeJoinRow(i){tempJoins.splice(i,1);renderJoins();}
        function renderJoins(){const c=document.getElementById('joinContainer');if(!tempJoins.length){c.innerHTML='<div class="text-xs text-gray-400 py-1">暂未配置 JOIN（如维表与事实表可直接关联则无需 JOIN）</div>';return;}c.innerHTML=tempJoins.map((j,i)=>`<div class="join-row"><div><label class="text-xs text-gray-500">源表</label><select onchange="tempJoins[${i}].source_table=this.value;renderJoins()" class="w-full px-2 py-1 text-xs border rounded font-mono"><option value="">请选择</option>${allTables.map(t=>`<option value="${t.table_name}" ${j.source_table===t.table_name?'selected':''}>${t.table_name}${t.description?' -- '+esc(t.description):''}</option>`).join('')}</select></div><div><label class="text-xs text-gray-500">源字段</label><select onchange="tempJoins[${i}].source_column=this.value" data-idx="${i}" class="w-full px-2 py-1 text-xs border rounded font-mono join-source-field"><option value="">-- 选择字段 --</option></select></div><div><label class="text-xs text-gray-500">目标表</label><select onchange="tempJoins[${i}].target_table=this.value;renderJoins()" class="w-full px-2 py-1 text-xs border rounded font-mono"><option value="">请选择</option>${allTables.map(t=>`<option value="${t.table_name}" ${j.target_table===t.table_name?'selected':''}>${t.table_name}${t.description?' -- '+esc(t.description):''}</option>`).join('')}</select></div><div><label class="text-xs text-gray-500">目标字段</label><select onchange="tempJoins[${i}].target_column=this.value" data-idx="${i}" class="w-full px-2 py-1 text-xs border rounded font-mono join-target-field"><option value="">-- 选择字段 --</option></select></div><div><label class="text-xs text-gray-500">类型</label><select onchange="tempJoins[${i}].join_type=this.value" class="w-full px-2 py-1 text-xs border rounded font-mono"><option value="LEFT JOIN" ${j.join_type==='LEFT JOIN'?'selected':''}>LEFT</option><option value="INNER JOIN" ${j.join_type==='INNER JOIN'?'selected':''}>INNER</option></select></div><button onclick="removeJoinRow(${i})" class="text-red-400 hover:text-red-600 text-lg leading-none">&times;</button></div>`).join('');setTimeout(()=>popJoinFields(),0);}
        async function popJoinFields(){const srcSelects=document.querySelectorAll('.join-source-field');const tgtSelects=document.querySelectorAll('.join-target-field');for(const sel of srcSelects){const idx=parseInt(sel.dataset.idx);const tableName=tempJoins[idx]?tempJoins[idx].source_table:'';const currentVal=sel.value||tempJoins[idx]?.source_column||'';if(tableName){const cols=await getCols(tableName);sel.innerHTML='<option value="">-- 选择字段 --</option>'+cols.map(c=>`<option value="${tableName}.${c.name}" ${currentVal===tableName+'.'+c.name?'selected':''}>${c.name}${c.description?' -- '+esc(c.description):''}</option>`).join('');}else{sel.innerHTML='<option value="">-- 请先选择源表 --</option>';}}for(const sel of tgtSelects){const idx=parseInt(sel.dataset.idx);const tableName=tempJoins[idx]?tempJoins[idx].target_table:'';const currentVal=sel.value||tempJoins[idx]?.target_column||'';if(tableName){const cols=await getCols(tableName);sel.innerHTML='<option value="">-- 选择字段 --</option>'+cols.map(c=>`<option value="${tableName}.${c.name}" ${currentVal===tableName+'.'+c.name?'selected':''}>${c.name}${c.description?' -- '+esc(c.description):''}</option>`).join('');}else{sel.innerHTML='<option value="">-- 请先选择目标表 --</option>';}}}
        async function onDimTableChange(pf){const tn=document.getElementById('d-table').value;const fs=document.getElementById('d-field');await popCol(fs,tn,pf||'');}
        function openCreateModal(){openCreateModalForMetric('');}
        function openCreateModalForMetric(mid){editingId=null;document.getElementById('modalTitle').textContent='新建维度';document.getElementById('editId').value='';document.getElementById('d-name').value='';document.getElementById('d-range').value='';document.getElementById('d-bizdef').value='';document.getElementById('d-table').value='';document.getElementById('d-field').innerHTML='<option value="">请先选择维表</option>';tempJoins=[];renderJoins();popDimTableOpts();const ms=document.getElementById('d-metric');ms.innerHTML='<option value="">请选择已配置的指标</option>'+allMetrics.map(m=>`<option value="${m.id}" ${mid===m.id?'selected':''}>${esc(m.name)}</option>`).join('');if(mid){ms.value=mid;}document.getElementById('dimModal').style.display='flex';}
        function editDim(id){const d=allDims.find(x=>x.id===id);if(!d)return;editingId=id;document.getElementById('modalTitle').textContent='编辑维度';document.getElementById('editId').value=d.id;document.getElementById('d-name').value=d.name;document.getElementById('d-range').value=d.value_range||'';document.getElementById('d-bizdef').value=d.business_definition||'';document.getElementById('d-table').value=d.data_source||'';tempJoins=d.joins?JSON.parse(JSON.stringify(d.joins)):[];renderJoins();popDimTableOpts();onDimTableChange(d.field_ref);const ms=document.getElementById('d-metric');ms.innerHTML='<option value="">请选择已配置的指标</option>'+allMetrics.map(m=>`<option value="${m.id}" ${d.metric_id===m.id?'selected':''}>${esc(m.name)}</option>`).join('');ms.value=d.metric_id;document.getElementById('dimModal').style.display='flex';}
        function closeModal(){document.getElementById('dimModal').style.display='none';}
        document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
        async function saveDim(){const mid=document.getElementById('d-metric').value;const name=document.getElementById('d-name').value.trim();const ds=document.getElementById('d-table').value;const field=document.getElementById('d-field').value;if(!mid||!name||!ds||!field){t('请填写所有必填字段','','bg-red-500 text-white');return;}const body={metric_id:mid,name,business_definition:document.getElementById('d-bizdef').value.trim()||null,value_range:document.getElementById('d-range').value.trim()||null,data_source:ds,field_ref:field,joins:tempJoins.filter(j=>j.source_table&&j.target_table),description:null};try{if(editingId){await apiPut('/api/easyq2sql/v1/dimensions/'+encodeURIComponent(editingId),body);t('维度更新成功 ✓','','bg-green-600 text-white');}else{await apiPost('/api/easyq2sql/v1/dimensions',body);t('维度创建成功 ✓（系统将自动生成术语映射）','','bg-green-600 text-white');}closeModal();await loadAll();}catch(e){t('保存失败: '+e.message,'','bg-red-500 text-white');}}
        async function deleteMetricDims(mid){const dims=allDims.filter(d=>d.metric_id===mid);if(!dims.length)return;const mn=metricName(mid);if(!confirm(`确认删除指标「${mn}」下的全部 ${dims.length} 个维度？`))return;for(const d of dims){try{await apiDelete('/api/easyq2sql/v1/dimensions/'+encodeURIComponent(d.id));}catch(e){}}
        t(`已删除 ${dims.length} 个维度`,'','bg-green-600 text-white');await loadAll();}
        async function autoFillRange(){const ds=document.getElementById('d-table').value;const fr=document.getElementById('d-field').value;if(!ds||!fr){t('请先选择数据表和字段','','bg-orange-500 text-white');return;}const btn=event.target;btn.disabled=true;btn.textContent='⏳ 查询中...';try{const r=await apiPost('/api/easyq2sql/v1/dimensions/auto-range',{data_source:ds,field_ref:fr});if(r.too_many){t(`该字段有 ${r.count} 个去重值，超过 20 条，不自动填充。请手动输入取值范围`,'','bg-orange-500 text-white');}else if(r.values&&r.values.length){document.getElementById('d-range').value=r.values.join(';');t(`已自动填入 ${r.values.length} 个取值 ✓`,'','bg-green-600 text-white');}else{t('该字段无数据','','bg-gray-500 text-white');}}catch(e){t('查询失败: '+e.message,'','bg-red-500 text-white');}finally{btn.disabled=false;btn.textContent='⚡ 自动生成';}}
        init();
    </script>"""
    return _admin_page_wrapper("Dimension Management", body, api_base_url)


# =========================================================================
# Terminology Management Page
# =========================================================================

def get_terminology_admin_html(api_base_url: str = "") -> str:
    """Generate the Terminology Management admin page."""
    body = """
    <style>
        .stat-card { transition: box-shadow .2s; }
        .stat-card:hover { box-shadow: 0 6px 16px rgba(0,0,0,.08); }
        .tag-blue { background:#e6f4ff; color:#1677ff; border:1px solid #bae0ff; }
        .tag-green { background:#f6ffed; color:#52c41a; border:1px solid #b7eb8f; }
        .tag-orange { background:#fff7e6; color:#fa8c16; border:1px solid #ffd591; }
        .tag-gray { background:#f5f5f5; color:#8c8c8c; border:1px solid #d9d9d9; }
        .tag-cyan { background:#e6fffb; color:#08979c; border:1px solid #87e8de; }
        .tag { display:inline-flex; align-items:center; padding:1px 8px; border-radius:3px; font-size:12px; line-height:20px; }
        .syn-tag { display:inline-flex; align-items:center; padding:1px 8px; border-radius:3px; font-size:12px; line-height:20px; background:#fafafa; border:1px solid #f0f0f0; color:#595959; }
        .syn-chip { display:inline-flex; align-items:center; gap:4px; padding:2px 10px; border-radius:12px; font-size:12px; line-height:22px; background:#e6f4ff; border:1px solid #bae0ff; color:#1677ff; }
        .tab-btn { padding:10px 20px; font-size:14px; font-weight:500; color:#8c8c8c; cursor:pointer; border-bottom:2px solid transparent; transition:all .2s; margin-bottom:-2px; border:none; background:none; }
        .tab-btn:hover { color:#1677ff; }
        .tab-btn.active { color:#1677ff; border-bottom-color:#1677ff; }
        .modal-overlay { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:1000; display:flex; align-items:flex-start; justify-content:center; padding-top:40px; }
        .toast-msg { position:fixed; top:20px; left:50%; transform:translateX(-50%); z-index:2000; padding:10px 24px; border-radius:8px; font-size:14px; box-shadow:0 4px 12px rgba(0,0,0,.15); }
    </style>
    <!-- Stats Row -->
    <div class="grid grid-cols-4 gap-4 mb-5">
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-blue-50 text-blue-500 flex items-center justify-center text-2xl">🏷️</div><div><div class="text-2xl font-bold text-gray-900" id="statTotal">0</div><div class="text-xs text-gray-500">术语总数</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-orange-50 text-orange-500 flex items-center justify-center text-2xl">✏️</div><div><div class="text-2xl font-bold text-gray-900" id="statManual">0</div><div class="text-xs text-gray-500">手动配置</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg bg-green-50 text-green-500 flex items-center justify-center text-2xl">⚡</div><div><div class="text-2xl font-bold text-gray-900" id="statAuto">0</div><div class="text-xs text-gray-500">自动生成</div></div></div>
        <div class="stat-card bg-white rounded-lg p-5 border border-gray-200 flex items-center gap-4"><div class="w-12 h-12 rounded-lg text-cyan-500 flex items-center justify-center text-2xl" style="background:#e6fffb;">🎯</div><div><div class="text-2xl font-bold text-gray-900" id="statCoverage">0</div><div class="text-xs text-gray-500">覆盖指标/维度</div></div></div>
    </div>
    <!-- Toolbar -->
    <div class="bg-white rounded-lg p-4 border border-gray-200 flex items-center gap-3 flex-wrap mb-0 rounded-b-none border-b-0">
        <input id="searchInput" placeholder="🔍 搜索术语文本 / 同义词..." oninput="renderTable()" class="w-72 h-9 px-3 text-sm border border-gray-300 rounded-md focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal outline-none">
        <select id="targetFilter" onchange="renderTable()" class="h-9 px-3 text-sm border border-gray-300 rounded-md outline-none"><option value="">全部类型</option><option value="metric">→ 指标</option><option value="dimension">→ 维度</option></select>
        <button onclick="resetFilters()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:text-easyq2sql-teal hover:border-easyq2sql-teal transition bg-white">↻ 重置</button>
        <div class="flex-1"></div>
        <button onclick="syncAutoTerms()" class="h-9 px-4 text-sm border border-easyq2sql-orange text-easyq2sql-orange rounded-md hover:bg-easyq2sql-orange hover:text-white transition bg-white font-medium">🔄 同步自动映射</button>
        <button onclick="openCreateModal()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">+ 新建映射</button>
    </div>
    <!-- Table -->
    <div class="bg-white rounded-lg border border-gray-200 overflow-hidden rounded-t-none">
        <div class="px-5 py-3 border-b border-gray-200 flex items-center justify-between">
            <div class="flex gap-0 border-b-0">
                <button class="tab-btn active" onclick="switchTab('all',this)">全部 <span class="text-gray-400 text-xs">0</span></button>
                <button class="tab-btn" onclick="switchTab('manual',this)">手动配置 <span class="text-gray-400 text-xs">0</span></button>
                <button class="tab-btn" onclick="switchTab('auto',this)">自动生成 <span class="text-gray-400 text-xs">0</span></button>
            </div>
            <span class="text-xs text-gray-500">共 <b id="totalCount">0</b> 条</span>
        </div>
        <div class="overflow-x-auto"><table class="w-full text-sm"><thead><tr class="bg-gray-50 text-left text-xs text-gray-500 uppercase"><th class="py-3 px-3 w-36">术语文本</th><th class="py-3 px-3 w-44">映射目标</th><th class="py-3 px-3">业务定义</th><th class="py-3 px-3">同义词</th><th class="py-3 px-3 w-20">来源</th><th class="py-3 px-3 w-36">更新时间</th><th class="py-3 px-3 w-28">操作</th></tr></thead><tbody id="tableBody"></tbody></table></div>
        <div class="px-5 py-3 border-t border-gray-200 text-xs text-gray-500 flex justify-between"><span id="pageInfo"></span></div>
    </div>
    <!-- Modal -->
    <div class="modal-overlay" id="termModal" style="display:none" onclick="if(event.target===this)closeModal()">
        <div class="bg-white rounded-xl shadow-lg w-full max-w-lg max-h-[85vh] flex flex-col">
            <div class="px-6 py-4 border-b border-gray-200 text-base font-semibold flex items-center justify-between"><span id="modalTitle">新建术语映射</span><button onclick="closeModal()" class="text-gray-400 hover:text-gray-800 text-xl leading-none">&times;</button></div>
            <div class="p-6 overflow-y-auto flex-1 space-y-4">
                <input type="hidden" id="editId">
                <div><label class="block text-xs font-medium text-gray-600 mb-1">术语文本 <span class="text-red-500">*</span></label><input id="t-term" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="如：OEE、上月、订单量"><p class="text-xs text-gray-400 mt-1">用户在自然语言中可能使用的业务术语</p></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">映射目标类型 <span class="text-red-500">*</span></label><select id="t-type" onchange="onTypeChange()" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">请选择</option><option value="metric">指标</option><option value="dimension">维度</option></select></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">映射目标 <span class="text-red-500">*</span></label><select id="t-target" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none"><option value="">请先选择映射目标类型</option></select></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">同义词</label><div id="synList" class="flex flex-wrap gap-1.5 mb-2"></div><div class="flex gap-2"><input id="synInput" placeholder="输入同义词后回车添加" onkeydown="if(event.key==='Enter'){event.preventDefault();addSyn()}" class="flex-1 px-3 py-1.5 text-xs border border-gray-300 rounded font-mono outline-none focus:border-easyq2sql-teal"><button onclick="addSyn()" class="px-3 py-1.5 border border-gray-300 rounded text-xs hover:bg-gray-100 bg-white">添加</button></div><p class="text-xs text-gray-400 mt-1">同义词也将参与检索匹配</p></div>
                <div><label class="block text-xs font-medium text-gray-600 mb-1">业务定义</label><textarea id="t-bizdef" rows="2" class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md font-mono outline-none focus:border-easyq2sql-teal focus:ring-1 focus:ring-easyq2sql-teal" placeholder="说明该术语的业务含义"></textarea><p class="text-xs text-gray-400 mt-1">自动生成时从关联的指标/维度继承业务定义</p></div>
                <div id="overrideHint" class="hidden p-3 bg-orange-50 border border-orange-200 rounded text-xs text-orange-500">⚠️ 此操作为手动配置，将覆盖同术语的自动生成映射。</div>
            </div>
            <div class="px-6 py-3 border-t border-gray-200 flex justify-end gap-2"><button onclick="closeModal()" class="h-9 px-4 text-sm border border-gray-300 rounded-md hover:bg-gray-100 bg-white">取消</button><button onclick="saveTerm()" class="h-9 px-5 bg-easyq2sql-teal text-white text-sm font-medium rounded-md hover:bg-easyq2sql-navy transition">✓ 保存</button></div>
        </div>
    </div>
    <!-- Toast -->
    <div class="toast-msg hidden" id="toast"></div>
    <script>
        let allTerms=[],allMetrics=[],allDims=[],editingId=null,tempSyns=[],currentTab='all';
        function esc(s){return(s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
        function t(txt,ms,color){const e=document.getElementById('toast');e.textContent=txt;e.className='toast-msg '+color;e.style.display='block';clearTimeout(e._t);e._t=setTimeout(()=>e.style.display='none',ms||2000);}
        async function init(){try{allMetrics=await apiGet('/api/easyq2sql/v1/metrics');}catch(e){allMetrics=[];}try{allDims=await apiGet('/api/easyq2sql/v1/dimensions');}catch(e){allDims=[];}await loadTerms();}
        async function loadTerms(){try{allTerms=await apiGet('/api/easyq2sql/v1/terminology');}catch(e){allTerms=[];}renderTable();}
        function getFiltered(){let f=[...allTerms];if(currentTab==='manual')f=f.filter(t=>t.source==='manual');if(currentTab==='auto')f=f.filter(t=>t.source==='auto');const s=document.getElementById('searchInput').value.toLowerCase();const tg=document.getElementById('targetFilter').value;return f.filter(t=>(!s||t.term_text.toLowerCase().includes(s)||(t.synonyms||[]).some(sy=>sy.toLowerCase().includes(s)))&&(!tg||t.target_type===tg));}
        function renderTable(){const data=getFiltered();const tb=document.getElementById('tableBody');document.getElementById('totalCount').textContent=data.length;document.getElementById('pageInfo').textContent=`显示 ${data.length} 条`;const manual=allTerms.filter(t=>t.source==='manual').length;const auto=allTerms.filter(t=>t.source==='auto').length;document.getElementById('statTotal').textContent=allTerms.length;document.getElementById('statManual').textContent=manual;document.getElementById('statAuto').textContent=auto;document.getElementById('statCoverage').textContent=new Set(allTerms.map(t=>t.target_id)).size;document.querySelectorAll('.tab-btn span').forEach((s,i)=>{const counts=[allTerms.length,manual,auto];s.textContent=counts[i]||0;});if(!data.length){tb.innerHTML='<tr><td colspan="7" class="text-center py-10 text-gray-400">🏷️ 暂无术语数据</td></tr>';return;}tb.innerHTML=data.map(t=>{const st=t.source==='manual'?'<span class="tag tag-orange">手动</span>':'<span class="tag tag-green">自动</span>';const tt=t.target_type==='metric'?'<span class="tag tag-blue">指标</span>':'<span class="tag tag-cyan">维度</span>';const syns=(t.synonyms||[]).length?(t.synonyms||[]).map(s=>`<span class="syn-tag">${esc(s)}</span>`).join(' '):'<span class="text-gray-400">—</span>';const timeVal=t.created_at||'';return`<tr class="border-b border-gray-100 hover:bg-blue-50/30 transition"><td class="py-2.5 px-3 font-medium text-gray-900">${esc(t.term_text)}</td><td class="py-2.5 px-3">${tt} <span class="text-xs text-gray-600">${esc(t.target_id)}</span></td><td class="py-2.5 px-3 max-w-[160px] truncate text-xs" title="${esc(t.business_definition||'')}">${esc(t.business_definition||'-')}</td><td class="py-2.5 px-3">${syns}</td><td class="py-2.5 px-3">${st}</td><td class="py-2.5 px-3 text-xs text-gray-500">${esc(typeof timeVal==='string'?timeVal.substring(0,16):'')}</td><td class="py-2.5 px-3 whitespace-nowrap"><button onclick="editTerm('${t.id}')" class="text-easyq2sql-teal hover:text-easyq2sql-navy text-xs mr-2">编辑</button><button onclick="deleteTerm('${t.id}')" class="text-red-500 hover:text-red-700 text-xs">删除</button></td></tr>`;}).join('');}
        function switchTab(tab,el){currentTab=tab;document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));el.classList.add('active');renderTable();}
        function resetFilters(){document.getElementById('searchInput').value='';document.getElementById('targetFilter').value='';currentTab='all';document.querySelectorAll('.tab-btn').forEach((b,i)=>i===0?b.classList.add('active'):b.classList.remove('active'));renderTable();}
        function onTypeChange(){const type=document.getElementById('t-type').value;const sel=document.getElementById('t-target');sel.innerHTML='<option value="">请选择</option>';if(type==='metric'){sel.innerHTML+=allMetrics.map(m=>`<option value="${m.id}">${esc(m.name)}</option>`).join('');sel.onchange=function(){const m=allMetrics.find(x=>x.id===sel.value);if(m&&!document.getElementById('t-bizdef').value)document.getElementById('t-bizdef').value=m.business_definition||'';};}else if(type==='dimension'){sel.innerHTML+=allDims.map(d=>{{const mn=(allMetrics.find(m=>m.id===d.metric_id)||{{}}).name||d.metric_id;return`<option value="${{d.id}}">${{esc(d.name)}}</option>`;}}).join('');sel.onchange=function(){const d=allDims.find(x=>x.id===sel.value);if(d&&!document.getElementById('t-bizdef').value)document.getElementById('t-bizdef').value=d.business_definition||'';};}}
        function renderSyns(){const c=document.getElementById('synList');if(!tempSyns.length){c.innerHTML='<span class="text-xs text-gray-400">暂未添加同义词</span>';return;}c.innerHTML=tempSyns.map((s,i)=>`<span class="syn-chip">${esc(s)}<button onclick="tempSyns.splice(${i},1);renderSyns()" class="text-gray-400 hover:text-red-500 leading-none ml-0.5">&times;</button></span>`).join('');}
        function addSyn(){const v=document.getElementById('synInput').value.trim();if(v&&!tempSyns.includes(v)){tempSyns.push(v);document.getElementById('synInput').value='';renderSyns();}}
        function openCreateModal(){editingId=null;document.getElementById('modalTitle').textContent='新建术语映射';document.getElementById('editId').value='';document.getElementById('t-term').value='';document.getElementById('t-type').value='';document.getElementById('t-target').innerHTML='<option value="">请先选择映射目标类型</option>';document.getElementById('t-bizdef').value='';tempSyns=[];renderSyns();document.getElementById('overrideHint').classList.add('hidden');document.getElementById('termModal').style.display='flex';}
        function editTerm(id){const t=allTerms.find(x=>x.id===id);if(!t)return;editingId=id;document.getElementById('modalTitle').textContent=t.source==='auto'?'编辑术语映射（覆盖自动生成）':'编辑术语映射';document.getElementById('editId').value=t.id;document.getElementById('t-term').value=t.term_text;document.getElementById('t-type').value=t.target_type;onTypeChange();document.getElementById('t-target').value=t.target_id;document.getElementById('t-bizdef').value=t.business_definition||'';tempSyns=[...(t.synonyms||[])];renderSyns();document.getElementById('overrideHint').classList.toggle('hidden',t.source!=='auto');document.getElementById('termModal').style.display='flex';}
        function closeModal(){document.getElementById('termModal').style.display='none';}
        document.addEventListener('keydown',function(e){if(e.key==='Escape')closeModal();});
        async function saveTerm(){const termText=document.getElementById('t-term').value.trim();const type=document.getElementById('t-type').value;const targetId=document.getElementById('t-target').value;if(!termText||!type||!targetId){t('请填写所有必填字段','','bg-red-500 text-white');return;}const body={term_text:termText,target_type:type,target_id:targetId,business_definition:document.getElementById('t-bizdef').value.trim()||null,synonyms:tempSyns};try{if(editingId){await apiPut('/api/easyq2sql/v1/terminology/'+encodeURIComponent(editingId),body);t('术语映射更新成功 ✓','','bg-green-600 text-white');}else{await apiPost('/api/easyq2sql/v1/terminology',body);t('术语映射创建成功 ✓','','bg-green-600 text-white');}closeModal();await loadTerms();}catch(e){t('保存失败: '+e.message,'','bg-red-500 text-white');}}
        async function deleteTerm(id){const t=allTerms.find(x=>x.id===id);const label=t&&t.source==='auto'?'此术语为自动生成，删除后可在下次同步时恢复。':'此操作为手动配置，删除后不可恢复。';if(!confirm(`确认删除术语「${t?t.term_text:id}」？\n${label}`))return;try{await apiDelete('/api/easyq2sql/v1/terminology/'+encodeURIComponent(id));t('已删除','','bg-green-600 text-white');await loadTerms();}catch(e){t('删除失败: '+e.message,'','bg-red-500 text-white');}}
        async function syncAutoTerms(){if(!confirm('同步自动映射将根据当前指标和维度重新生成默认术语（不会覆盖手动配置）。确认继续？'))return;try{const r=await apiPost('/api/easyq2sql/v1/terminology/sync',{});t(`同步完成，已更新 ${r.auto_entries_synced} 条映射 ✓`,'','bg-green-600 text-white');await loadTerms();}catch(e){t('同步失败: '+e.message,'','bg-red-500 text-white');}}
        init();
    </script>"""
    return _admin_page_wrapper("Terminology Management", body, api_base_url)
