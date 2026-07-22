"""
HTML templates for EasyQ2Sql servers.
"""

def get_vanna_component_script(
    static_path: str = "/static",
) -> str:
    """Get the script tag for loading EasyQ2Sql web components."""
    return f'<script type="module" src="{static_path}/easyq2sql-components.js"></script>'


def get_index_html(
    static_path: str = "/static",
    api_base_url: str = "",
) -> str:
    """Generate index HTML with conversation sidebar + chat component.

    Sidebar is server-rendered HTML + vanilla JS (Tailwind + fetch API).
    The <easyq2sql-chat> component handles only the current conversation.
    """
    component_script = get_vanna_component_script(static_path)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>EasyQ2Sql Chat</title>
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
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            background:
                radial-gradient(circle at top left, rgba(21, 168, 168, 0.12), transparent 60%),
                radial-gradient(circle at bottom right, rgba(254, 93, 38, 0.08), transparent 65%);
        }}

        body::after {{
            content: '';
            position: fixed;
            inset: 0;
            pointer-events: none;
            z-index: 0;
            background-image:
                radial-gradient(circle at 2px 2px, rgba(2, 61, 96, 0.3) 1px, transparent 0),
                linear-gradient(rgba(2, 61, 96, 0.1) 1px, transparent 1px),
                linear-gradient(90deg, rgba(2, 61, 96, 0.1) 1px, transparent 1px);
            background-size: 32px 32px, 100px 100px, 100px 100px;
        }}

        body > * {{
            position: relative;
            z-index: 1;
        }}

        easyq2sql-chat {{
            width: 100%;
            display: block;
        }}

        /* Sidebar scrollbar */
        .conv-sidebar::-webkit-scrollbar {{ width: 4px; }}
        .conv-sidebar::-webkit-scrollbar-track {{ background: transparent; }}
        .conv-sidebar::-webkit-scrollbar-thumb {{ background: #cbd5e1; border-radius: 4px; }}

        /* Conversation item transitions */
        .conv-item {{
            transition: all 0.15s ease;
        }}
        .conv-item:hover {{
            background: rgba(21, 168, 168, 0.08);
        }}
        .conv-item.active {{
            background: rgba(21, 168, 168, 0.12);
            border-color: rgba(21, 168, 168, 0.3);
        }}
        .conv-delete-btn {{
            opacity: 0;
            transition: opacity 0.15s ease;
        }}
        .conv-item:hover .conv-delete-btn {{
            opacity: 1;
        }}
        .conv-delete-btn:hover {{
            background: rgba(239, 68, 68, 0.15);
            color: rgb(239, 68, 68);
        }}
    </style>
    {component_script}
</head>
<body>
    <div class="max-w-6xl mx-auto p-5">
        <!-- Header -->
        <div class="text-center mb-8">
            <h1 class="text-4xl font-bold text-easyq2sql-navy mb-2 font-serif">EasyQ2Sql</h1>
            <p class="text-lg font-mono font-bold text-easyq2sql-teal mb-4">DATA-FIRST AGENTS</p>
            <p class="text-slate-600 mb-4">Interactive AI Assistant powered by EasyQ2Sql Framework</p>
            <div class="flex justify-center gap-3 flex-wrap">
                <a href="javascript:window.location='view-source:'+window.location.href" class="inline-flex items-center gap-2 px-4 py-2 bg-easyq2sql-teal text-white text-sm font-medium rounded-lg hover:bg-easyq2sql-navy transition">
                    <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/>
                    </svg>
                    View Page Source
                </a>
                <a href="{api_base_url}/admin/schema" class="inline-flex items-center gap-2 px-4 py-2 bg-easyq2sql-navy text-white text-sm font-medium rounded-lg hover:bg-easyq2sql-teal transition">
                    &#x1f4ca; Schema Admin
                </a>
                <a href="{api_base_url}/admin/metrics" class="inline-flex items-center gap-2 px-4 py-2 bg-easyq2sql-navy text-white text-sm font-medium rounded-lg hover:bg-easyq2sql-teal transition">
                    &#x1f4c8; Metrics Admin
                </a>
            </div>
        </div>

        <!-- Login Form -->
        <div id="loginContainer" class="max-w-md mx-auto mb-10 bg-white p-8 rounded-xl shadow-lg border border-easyq2sql-teal/30">
            <div class="text-center mb-6">
                <h2 class="text-2xl font-semibold text-easyq2sql-navy mb-2 font-serif">Login to Continue</h2>
                <p class="text-sm text-slate-600">Select your email to access the chat</p>
            </div>

            <div class="mb-5">
                <label for="emailInput" class="block mb-2 text-sm font-medium text-easyq2sql-navy">Email Address</label>
                <select
                    id="emailInput"
                    class="w-full px-4 py-3 text-sm border border-easyq2sql-teal/30 rounded-lg focus:outline-none focus:ring-2 focus:ring-easyq2sql-teal focus:border-transparent bg-white"
                >
                    <option value="">Select an email...</option>
                    <option value="admin@example.com">admin@example.com</option>
                    <option value="user@example.com">user@example.com</option>
                </select>
            </div>

            <button id="loginButton" class="w-full px-4 py-3 bg-easyq2sql-teal text-white text-sm font-medium rounded-lg hover:bg-easyq2sql-navy focus:outline-none focus:ring-2 focus:ring-easyq2sql-teal focus:ring-offset-2 transition disabled:bg-gray-400 disabled:cursor-not-allowed">
                Continue
            </button>

            <div class="mt-5 p-3 bg-easyq2sql-teal/10 border-l-4 border-easyq2sql-teal rounded text-xs text-easyq2sql-navy leading-relaxed">
                <strong>Demo Mode:</strong> This is a frontend-only authentication demo.
                Your email will be stored as a cookie and automatically sent with all API requests.
            </div>
        </div>

        <!-- Logged In Status (hidden by default) -->
        <div id="loggedInStatus" class="hidden text-center p-4 bg-easyq2sql-teal/10 border border-easyq2sql-teal/30 rounded-lg mb-5">
            Logged in as <span id="loggedInEmail" class="font-semibold text-easyq2sql-navy"></span>
            <br>
            <button id="logoutButton" class="mt-2 px-3 py-1.5 bg-easyq2sql-navy text-white text-xs rounded hover:bg-easyq2sql-teal transition">
                Logout
            </button>
        </div>

        <!-- Chat Sections (hidden by default until login) -->
        <div id="chatSections" class="hidden">
            <!-- Two-column layout: sidebar + chat -->
            <div class="flex gap-5 h-[650px] max-h-[85vh]">
                <!-- LEFT SIDEBAR: Conversation history -->
                <div class="conv-sidebar w-64 flex-shrink-0 bg-white rounded-xl shadow-lg border border-easyq2sql-teal/30 flex flex-col overflow-hidden">
                    <!-- New Chat button -->
                    <div class="p-4 border-b border-gray-100">
                        <button id="newChatBtn" class="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-easyq2sql-teal text-white text-sm font-semibold rounded-lg hover:bg-easyq2sql-navy transition">
                            <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                                <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
                            </svg>
                            New Chat
                        </button>
                    </div>

                    <!-- Conversation list -->
                    <div class="flex-1 overflow-y-auto p-2" id="convList">
                        <div class="text-xs font-semibold uppercase tracking-wider text-gray-400 px-3 py-2">Recent Conversations</div>
                        <div id="convListContent">
                            <div class="text-xs text-gray-400 text-center py-4">Loading...</div>
                        </div>
                    </div>

                    <!-- API info footer -->
                    <div class="p-3 border-t border-gray-100 text-center">
                        <span id="convCount" class="text-xs text-gray-400">0 conversations</span>
                    </div>
                </div>

                <!-- RIGHT: Chat component -->
                <div class="flex-1 min-w-0 bg-white rounded-xl shadow-lg h-full overflow-hidden border border-easyq2sql-teal/30">
                    <easyq2sql-chat
                        id="easyq2sqlChat"
                        api-base="{api_base_url}"
                        sse-endpoint="{api_base_url}/api/easyq2sql/v1/chat_sse"
                        ws-endpoint="{api_base_url}/api/easyq2sql/v1/chat_websocket"
                        poll-endpoint="{api_base_url}/api/easyq2sql/v1/chat_poll">
                    </easyq2sql-chat>
                </div>
            </div>

            <!-- API Endpoints reference -->
            <div class="mt-8 p-5 bg-white rounded-lg shadow border border-easyq2sql-teal/30">
                <h3 class="text-lg font-semibold text-easyq2sql-navy mb-3 font-serif">API Endpoints</h3>
                <ul class="space-y-2">
                    <li class="p-2 bg-easyq2sql-cream/50 rounded font-mono text-sm">
                        <span class="font-bold text-easyq2sql-teal mr-2">POST</span>{api_base_url}/api/easyq2sql/v1/chat_sse - Server-Sent Events streaming
                    </li>
                    <li class="p-2 bg-easyq2sql-cream/50 rounded font-mono text-sm">
                        <span class="font-bold text-easyq2sql-teal mr-2">WS</span>{api_base_url}/api/easyq2sql/v1/chat_websocket - WebSocket real-time chat
                    </li>
                    <li class="p-2 bg-easyq2sql-cream/50 rounded font-mono text-sm">
                        <span class="font-bold text-easyq2sql-teal mr-2">POST</span>{api_base_url}/api/easyq2sql/v1/chat_poll - Request/response polling
                    </li>
                    <li class="p-2 bg-easyq2sql-cream/50 rounded font-mono text-sm">
                        <span class="font-bold text-easyq2sql-teal mr-2">GET</span>{api_base_url}/api/easyq2sql/v1/conversations - Conversation history
                    </li>
                    <li class="p-2 bg-easyq2sql-cream/50 rounded font-mono text-sm">
                        <span class="font-bold text-easyq2sql-teal mr-2">GET</span>{api_base_url}/health - Health check
                    </li>
                </ul>
            </div>
        </div>
    </div>

    <script>
        // =====================================================================
        // Cookie helpers
        // =====================================================================
        const getCookie = (name) => {{
            const value = `; ${{document.cookie}}`;
            const parts = value.split(`; ${{name}}=`);
            return parts.length === 2 ? parts.pop().split(';').shift() : null;
        }};

        const setCookie = (name, value) => {{
            const expires = new Date(Date.now() + 365 * 864e5).toUTCString();
            document.cookie = `${{name}}=${{value}}; expires=${{expires}}; path=/; SameSite=Lax`;
        }};

        const deleteCookie = (name) => {{
            document.cookie = `${{name}}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
        }};

        // =====================================================================
        // Login / Logout
        // =====================================================================
        document.addEventListener('DOMContentLoaded', () => {{
            const email = getCookie('easyq2sql_email');
            if (email) {{
                loginContainer.classList.add('hidden');
                loggedInStatus.classList.remove('hidden');
                chatSections.classList.remove('hidden');
                loggedInEmail.textContent = email;
                initSidebar();
            }}

            loginButton.addEventListener('click', () => {{
                const email = emailInput.value.trim();
                if (!email) {{ alert('Please select an email address'); return; }}
                setCookie('easyq2sql_email', email);
                loginContainer.classList.add('hidden');
                loggedInStatus.classList.remove('hidden');
                chatSections.classList.remove('hidden');
                loggedInEmail.textContent = email;
                initSidebar();
            }});

            logoutButton.addEventListener('click', () => {{
                deleteCookie('easyq2sql_email');
                loginContainer.classList.remove('hidden');
                loggedInStatus.classList.add('hidden');
                chatSections.classList.add('hidden');
                emailInput.value = '';
            }});

            emailInput.addEventListener('keypress', (e) => {{
                if (e.key === 'Enter') loginButton.click();
            }});
        }});

        // =====================================================================
        // Conversation Sidebar Logic (Vanilla JS + fetch API)
        // =====================================================================
        const API_BASE = '{api_base_url}';
        const CONV_API = API_BASE + '/api/easyq2sql/v1/conversations';
        let currentConversationId = null;

        function getChatComponent() {{
            return document.getElementById('easyq2sqlChat');
        }}

        function formatDate(isoStr) {{
            if (!isoStr) return '';
            try {{
                const date = new Date(isoStr);
                const now = new Date();
                const diffMs = now - date;
                const mins = Math.floor(diffMs / 60000);
                const hours = Math.floor(diffMs / 3600000);
                const days = Math.floor(diffMs / 86400000);
                if (mins < 1) return 'Just now';
                if (mins < 60) return `${{mins}}m ago`;
                if (hours < 24) return `${{hours}}h ago`;
                if (days < 7) return `${{days}}d ago`;
                return date.toLocaleDateString();
            }} catch {{ return ''; }}
        }}

        async function fetchConversations() {{
            try {{
                const resp = await fetch(CONV_API + '?limit=50&offset=0');
                if (!resp.ok) return [];
                return await resp.json();
            }} catch (e) {{
                console.warn('Failed to fetch conversations:', e);
                return [];
            }}
        }}

        async function deleteConversation(convId, event) {{
            event.stopPropagation();
            const item = document.getElementById('conv-' + convId);
            const title = item ? item.querySelector('.conv-title').textContent : convId;
            if (!confirm('Delete conversation "' + title + '"?')) return;
            try {{
                const resp = await fetch(CONV_API + '/' + encodeURIComponent(convId), {{ method: 'DELETE' }});
                if (resp.ok) {{
                    // Remove from DOM
                    if (item) item.remove();
                    updateConvCount();
                    // If deleted current, start new
                    if (convId === currentConversationId) {{
                        startNewChat();
                    }}
                }}
            }} catch (e) {{
                console.error('Delete failed:', e);
                alert('Failed to delete conversation');
            }}
        }}

        async function switchConversation(convId) {{
            if (convId === currentConversationId) return;
            currentConversationId = convId;

            // Update active styling
            document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
            const item = document.getElementById('conv-' + convId);
            if (item) item.classList.add('active');

            // Tell the chat component to load this conversation
            const chat = getChatComponent();
            if (chat && chat.loadConversation) {{
                await chat.loadConversation(convId);
            }}
        }}

        async function startNewChat() {{
            const chat = getChatComponent();
            if (chat && chat.startNewConversation) {{
                await chat.startNewConversation();
            }}
        }}

        function updateConvCount() {{
            const count = document.querySelectorAll('.conv-item').length;
            document.getElementById('convCount').textContent = `${{count}} conversation${{count !== 1 ? 's' : ''}}`;
        }}

        async function renderConversationList() {{
            const container = document.getElementById('convListContent');
            const conversations = await fetchConversations();

            if (!conversations.length) {{
                container.innerHTML = '<div class="text-xs text-gray-400 text-center py-6">No conversations yet</div>';
                updateConvCount();
                return;
            }}

            container.innerHTML = conversations.map(conv => {{
                const title = conv.title || 'Untitled';
                const safeTitle = title.replace(/'/g, "\\'").replace(/"/g, '&quot;');
                const isActive = conv.id === currentConversationId;
                return `
                    <div id="conv-${{conv.id}}"
                         class="conv-item flex items-center gap-2 px-3 py-2.5 rounded-lg cursor-pointer border border-transparent ${{isActive ? 'active' : ''}}"
                         onclick="switchConversation('${{conv.id}}')">
                        <div class="flex-1 min-w-0">
                            <div class="conv-title text-sm font-medium text-gray-800 truncate">${{safeTitle}}</div>
                            <div class="text-xs text-gray-400">${{conv.message_count || 0}} msg &middot; ${{formatDate(conv.updated_at)}}</div>
                        </div>
                        <button class="conv-delete-btn w-7 h-7 rounded border-0 bg-transparent text-gray-400 inline-flex items-center justify-center flex-shrink-0"
                                title="Delete"
                                onclick="deleteConversation('${{conv.id}}', event)">
                            <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
                                <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
                            </svg>
                        </button>
                    </div>
                `;
            }}).join('');
            updateConvCount();
        }}

        function initSidebar() {{
            const chat = getChatComponent();
            if (!chat) {{ setTimeout(initSidebar, 200); return; }}

            // Track current conversation ID from the component
            currentConversationId = chat.conversationId || '';

            // Bind New Chat button
            document.getElementById('newChatBtn').addEventListener('click', startNewChat);

            // Listen for conversation-ready events from the chat component
            chat.addEventListener('conversation-ready', (e) => {{
                if (e.detail && e.detail.conversationId) {{
                    currentConversationId = e.detail.conversationId;
                    renderConversationList();
                }}
            }});

            // Initial load
            renderConversationList();

            // Observe conversation-id attribute changes (for when the component changes it internally)
            const observer = new MutationObserver(() => {{
                const newId = chat.getAttribute('conversation-id');
                if (newId && newId !== currentConversationId) {{
                    currentConversationId = newId;
                    renderConversationList();
                }}
            }});
            observer.observe(chat, {{ attributes: true, attributeFilter: ['conversation-id'] }});
            window._convObserver = observer;
        }}
    </script>

    <script>
        // Artifact demo event listener
        document.addEventListener('DOMContentLoaded', () => {{
            const easyq2sqlChat = document.querySelector('easyq2sql-chat');
            if (easyq2sqlChat) {{
                easyq2sqlChat.addEventListener('artifact-opened', (event) => {{
                    const {{ artifactId, type, title, trigger }} = event.detail;
                    console.log('🎨 Artifact Event:', {{ artifactId, type, title, trigger }});
                    setTimeout(() => {{
                        const newWindow = window.open('', '_blank', 'width=900,height=700');
                        if (newWindow) {{
                            newWindow.document.write(event.detail.getStandaloneHTML());
                            newWindow.document.close();
                            newWindow.document.title = title || 'EasyQ2Sql Artifact';
                            console.log(`📱 Opened ${{title}} in new window`);
                        }}
                    }}, 100);
                    event.detail.preventDefault();
                    console.log('✋ Showing placeholder in chat instead of full artifact');
                }});
                console.log('🎯 Artifact demo mode: All artifacts will open externally');
            }}
        }});

        // Fallback if web component doesn't load
        if (!customElements.get('easyq2sql-chat')) {{
            setTimeout(() => {{
                if (!customElements.get('easyq2sql-chat')) {{
                    document.querySelector('easyq2sql-chat').innerHTML = `
                        <div class="p-10 text-center text-gray-600">
                            <h3 class="text-xl font-semibold mb-2">EasyQ2Sql Chat Component</h3>
                            <p class="mb-2">Web component failed to load. Please check your connection.</p>
                            <p class="text-sm text-gray-400">Loading from: {static_path}/easyq2sql-components.js</p>
                        </div>
                    `;
                }}
            }}, 2000);
        }}
    </script>
</body>
</html>"""


# Backward compatibility - default production HTML
INDEX_HTML = get_index_html()
