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
        const div = document.createElement('div');
        div.className = 'log-entry system';
        div.textContent = `[SYSTEM] ${msg}`;
        div.style.color = '#888';
        terminal.appendChild(div);
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
            }

        } catch (e) {
            console.error('Status fetch failed', e);
        }
    }

    startStatusPolling() {
        setInterval(() => this.loadStatus(), 2000);
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
