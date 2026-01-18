// app.js

class App {
    constructor() {
        this.socket = null;
        this.connected = false;

        // State
        this.currentTable = 'articles';
        this.currentPage = 0;
        this.pageSize = 20;
        this.isRunning = false;

        this.init();
    }

    init() {
        this.bindEvents();
        this.connectWebSocket();
        this.loadStatus();
        this.startStatusPolling();

        // Initial Data Load
        this.loadDatabaseData();
    }

    bindEvents() {
        // Navigation
        document.querySelectorAll('.nav-item').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchPage(e.currentTarget));
        });

        // Controls
        document.getElementById('btn-run').addEventListener('click', () => this.runTask('fetch'));
        document.getElementById('btn-digest').addEventListener('click', () => this.runTask('digest'));
        document.getElementById('btn-stop').addEventListener('click', () => this.stopTask());

        // Logs
        document.getElementById('btn-clear-logs').addEventListener('click', () => {
            document.getElementById('terminal-output').innerHTML = '';
        });

        // Database
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.currentTable = e.target.dataset.table;
                this.currentPage = 0;
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                e.target.classList.add('active');
                this.loadDatabaseData();
            });
        });

        document.getElementById('btn-prev-page').addEventListener('click', () => {
            if (this.currentPage > 0) {
                this.currentPage--;
                this.loadDatabaseData();
            }
        });

        document.getElementById('btn-next-page').addEventListener('click', () => {
            this.currentPage++;
            this.loadDatabaseData();
        });

        // Feeds
        document.getElementById('btn-add-feed').addEventListener('click', () => this.addFeed());
    }

    switchPage(targetBtn) {
        // Update Nav
        document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
        targetBtn.classList.add('active');

        // Show View
        const targetId = targetBtn.dataset.target;
        document.querySelectorAll('.view-section').forEach(v => v.classList.remove('active'));
        document.getElementById(`view-${targetId}`).classList.add('active');

        // Update Title
        document.getElementById('page-title').innerText = targetBtn.innerText.trim();

        // Load specific view data
        if (targetId === 'feeds') {
            this.loadFeeds();
        } else if (targetId === 'database') {
            this.loadDatabaseData();
        }
    }

    // --- WebSocket ---

    connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/logs`;

        this.socket = new WebSocket(wsUrl);

        this.socket.onopen = () => {
            console.log('Connected to WebSocket');
            this.connected = true;
            this.logSystem('已连接到实时日志流');
        };

        this.socket.onclose = () => {
            console.log('Disconnected');
            this.connected = false;
            this.logSystem('连接断开，正在重试...');
            setTimeout(() => this.connectWebSocket(), 3000);
        };

        this.socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.type === 'log') {
                    this.appendLog(data);
                }
            } catch (e) {
                console.error('Error parsing msg', e);
            }
        };
    }

    appendLog(log) {
        const terminal = document.getElementById('terminal-output');
        const template = document.getElementById('log-entry-template');
        const clone = template.content.cloneNode(true);

        const el = clone.querySelector('.log-entry');
        el.dataset.level = log.level;

        clone.querySelector('.log-time').textContent = log.timestamp.split('T')[1].split('.')[0];
        clone.querySelector('.log-level').textContent = log.level;
        clone.querySelector('.log-logger').textContent = log.logger || 'root';

        // 构建消息内容，如果有 context data 则附加上
        let msg = log.event;
        if (log.context && Object.keys(log.context).length > 0) {
            msg += ' ' + JSON.stringify(log.context);
        }
        clone.querySelector('.log-message').textContent = msg;

        terminal.appendChild(clone);

        // Auto Scroll
        if (document.getElementById('auto-scroll').checked) {
            terminal.scrollTop = terminal.scrollHeight;
        }

        // Cleanup old logs if too many
        if (terminal.children.length > 1000) {
            terminal.removeChild(terminal.firstChild);
        }
    }

    logSystem(msg) {
        const terminal = document.getElementById('terminal-output');
        if (!terminal) return; // fail safe
        const div = document.createElement('div');
        div.className = 'log-entry system';
        div.textContent = `[SYSTEM] ${msg}`;
        div.style.color = '#888';
        terminal.appendChild(div);

        // Auto Scroll for system logs too
        if (document.getElementById('auto-scroll')?.checked) {
            terminal.scrollTop = terminal.scrollHeight;
        }
    }

    // --- API & State ---

    async runTask(type) {
        if (this.isRunning) return;

        const endpoint = type === 'digest' ? '/api/digest' : '/api/run';
        const body = type === 'fetch' ? { limit: 200 } : {};

        try {
            this.setRunningState(true);
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await res.json();
            if (res.ok) {
                this.logSystem(`任务已启动: ${type}`);
            } else {
                this.logSystem(`启动失败: ${data.detail}`);
                this.setRunningState(false);
            }
        } catch (e) {
            this.logSystem(`请求错误: ${e.message}`);
            this.setRunningState(false);
        }
    }

    async stopTask() {
        try {
            await fetch('/api/stop', { method: 'POST' });
            this.logSystem('发送停止指令...');
        } catch (e) {
            console.error(e);
        }
    }

    setRunningState(running) {
        this.isRunning = running;
        const btnRun = document.getElementById('btn-run');
        const btnDigest = document.getElementById('btn-digest');
        const btnStop = document.getElementById('btn-stop');
        const statusBadge = document.getElementById('system-state');

        if (running) {
            btnRun.disabled = true;
            btnDigest.disabled = true;
            btnStop.disabled = false;
            statusBadge.textContent = 'Running';
            statusBadge.className = 'badge running';
            btnRun.style.opacity = '0.5';
        } else {
            btnRun.disabled = false;
            btnDigest.disabled = false;
            btnStop.disabled = true;
            statusBadge.textContent = 'Idle';
            statusBadge.className = 'badge idle';
            btnRun.style.opacity = '1';
        }
    }

    async loadStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();

            this.setRunningState(data.running);
            document.getElementById('system-mode').textContent = data.mode;

            // Update Stats if available
            if (data.stats) {
                if (data.stats.fetched_count !== undefined)
                    document.getElementById('stat-fetched').textContent = data.stats.fetched_count;
                if (data.stats.analyzed_count !== undefined)
                    document.getElementById('stat-analyzed').textContent = data.stats.analyzed_count;
                // Try to find unsent count if available
                if (data.stats.unsent_count !== undefined)
                    document.getElementById('stat-unsent').textContent = data.stats.unsent_count;
            }

        } catch (e) {
            console.error('Status fetch failed', e);
        }
    }

    startStatusPolling() {
        setInterval(() => this.loadStatus(), 2000);
    }

    // --- Feeds Management ---

    async loadFeeds() {
        const tbody = document.getElementById('feeds-table-body');
        if (!tbody) return;

        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:2rem">Loading...</td></tr>';

        try {
            const res = await fetch('/api/feeds');
            const data = await res.json();

            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:var(--text-muted);padding:2rem">暂无订阅源，请在上方添加</td></tr>';
                return;
            }

            tbody.innerHTML = data.map(feed => `
                <tr class="feed-row">
                    <td>
                        <label class="switch">
                            <input type="checkbox" ${feed.enabled ? 'checked' : ''} onchange="app.toggleFeed('${feed.name}')">
                            <span class="slider"></span>
                        </label>
                    </td>
                    <td class="feed-name" title="${feed.name}">${feed.name}</td>
                    <td><span class="feed-category">${feed.category || '未分类'}</span></td>
                    <td class="feed-url" title="${feed.url}">${feed.url}</td>
                    <td>
                        <button class="btn small danger" style="padding:4px 8px" onclick="app.removeFeed('${feed.name}')" title="删除">🗑️</button>
                    </td>
                </tr>
            `).join('');

        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger);text-align:center">Error: ${e.message}</td></tr>`;
        }
    }

    async addFeed() {
        const urlInput = document.getElementById('feed-url-input');
        const nameInput = document.getElementById('feed-name-input');
        const categoryInput = document.getElementById('feed-category-input');
        const btn = document.getElementById('btn-add-feed');

        const url = urlInput.value.trim();
        const name = nameInput.value.trim();
        const category = categoryInput.value.trim();

        if (!url) {
            this.logSystem('错误: 请输入 RSS URL');
            alert('错误: 请输入 RSS URL');
            return;
        }

        btn.disabled = true;
        const originalText = btn.innerHTML;
        btn.innerHTML = '<span class="icon">⏳</span> 添加中...';

        try {
            const res = await fetch('/api/feeds', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, name, category })
            });
            const data = await res.json();

            if (res.ok) {
                this.logSystem(`✅ 已添加订阅源: ${data.title}`);
                urlInput.value = '';
                nameInput.value = '';
                categoryInput.value = '';
                this.loadFeeds();
            } else {
                this.logSystem(`❌ 添加失败: ${data.detail}`);
                alert(`添加失败: ${data.detail}`);
            }
        } catch (e) {
            this.logSystem(`❌ 请求错误: ${e.message}`);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }

    async toggleFeed(identifier) {
        try {
            const res = await fetch('/api/feeds/toggle', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ identifier })
            });

            if (res.ok) {
                this.logSystem(`订阅源状态已更新: ${identifier}`);
            } else {
                this.loadFeeds(); // Revert UI on failure
                const data = await res.json();
                this.logSystem(`❌ 切换失败: ${data.detail}`);
            }
        } catch (e) {
            console.error(e);
            this.loadFeeds();
        }
    }

    async removeFeed(identifier) {
        if (!confirm(`确定要删除订阅源 "${identifier}" 吗？`)) return;

        try {
            // Encode identifier to handle special characters if any
            const res = await fetch(`/api/feeds/${encodeURIComponent(identifier)}`, {
                method: 'DELETE'
            });

            if (res.ok) {
                this.logSystem(`🗑️ 已删除订阅源: ${identifier}`);
                this.loadFeeds();
            } else {
                const data = await res.json();
                this.logSystem(`❌ 删除失败: ${data.detail}`);
                alert(`删除失败: ${data.detail}`);
            }
        } catch (e) {
            this.logSystem(`❌ 请求错误: ${e.message}`);
        }
    }

    // --- Database View ---

    async loadDatabaseData() {
        const tbody = document.getElementById('db-table-body');
        const thead = document.getElementById('db-table-head');
        tbody.innerHTML = '<tr><td colspan="5">Loading...</td></tr>';

        try {
            const res = await fetch(`/api/db/${this.currentTable}?limit=${this.pageSize}&offset=${this.currentPage * this.pageSize}`);
            const data = await res.json();

            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="5">No data found</td></tr>';
                return;
            }

            // Render Header
            const columns = Object.keys(data[0]);
            thead.innerHTML = '<tr>' + columns.map(c => `<th>${c}</th>`).join('') + '</tr>';

            // Render Body
            const escapeHtml = (unsafe) => {
                return String(unsafe)
                    .replace(/&/g, "&amp;")
                    .replace(/</g, "&lt;")
                    .replace(/>/g, "&gt;")
                    .replace(/"/g, "&quot;")
                    .replace(/'/g, "&#039;");
            }

            tbody.innerHTML = data.map(row => {
                return '<tr>' + columns.map(col => {
                    let val = row[col];
                    if (val === null || val === undefined) val = '';
                    if (typeof val === 'object') val = JSON.stringify(val);

                    let displayVal = String(val);
                    if (displayVal.length > 50) displayVal = displayVal.substring(0, 50) + '...';

                    // Escape HTML to prevent rendering images/scripts
                    return `<td title="${String(val).replace(/"/g, '&quot;')}">${escapeHtml(displayVal)}</td>`;
                }).join('') + '</tr>';
            }).join('');

            document.getElementById('page-info').textContent = `Page ${this.currentPage + 1}`;

        } catch (e) {
            tbody.innerHTML = `<tr><td colspan="5" style="color:var(--danger)">Error: ${e.message}</td></tr>`;
        }
    }
}

// Start App
window.addEventListener('DOMContentLoaded', () => {
    window.app = new App();
});
