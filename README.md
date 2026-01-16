# RSS AI Reader Service

智能 RSS 阅读器 - 用 AI 帮你筛选真正值得阅读的内容

## 功能

- 🔄 定时抓取所有 RSS 订阅源
- 🤖 AI 智能筛选，过滤标题党和低质量内容
- 📊 为每篇文章打分并生成一句话摘要
- 📧 每日发送精选简报（5 篇精读 + 其他速览）
- 🐳 Docker 容器化，支持 7×24 小时运行

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制配置模板并填入你的信息：

```bash
cp config/config.example.yaml config/config.yaml
cp config/feeds.example.yaml config/feeds.yaml
```

编辑 `config/config.yaml`：
- 填入 DeepSeek API Key
- 配置邮箱 SMTP 信息
- 设置发送时间

编辑 `config/feeds.yaml`：
- 添加你的 RSS 订阅源

### 3. 运行

```bash
# 直接运行
python -m src.main

# 测试运行（只抓取一次，不发送邮件）
python -m src.main --once --dry-run

# 发送测试邮件
python -m src.main --test-email
```

### 4. Docker 部署

```bash
# 设置环境变量
export DEEPSEEK_API_KEY=your_api_key
export EMAIL_USERNAME=your_email
export EMAIL_PASSWORD=your_password

# 启动服务
docker-compose up -d
```

## 配置说明

### AI 配置

支持 DeepSeek 和 OpenAI 兼容的 API：

```yaml
ai:
  provider: deepseek
  api_key: ${DEEPSEEK_API_KEY}
  model: deepseek-chat
  base_url: https://api.deepseek.com
```

### 邮件配置

```yaml
email:
  smtp_host: smtp.qq.com
  smtp_port: 465
  use_ssl: true
  username: ${EMAIL_USERNAME}
  password: ${EMAIL_PASSWORD}  # QQ邮箱使用授权码
  from_addr: your@qq.com
  to_addrs:
    - recipient@example.com
```

### 调度配置

```yaml
schedule:
  fetch_interval: 2h      # 每 2 小时抓取一次
  digest_time: "07:00"    # 每天早上 7 点发送简报
  timezone: Asia/Shanghai
```

## 目录结构

```
Message-reader/
├── src/                    # 源代码
│   ├── fetcher/           # RSS 抓取模块
│   ├── ai/                # AI 分析模块
│   ├── storage/           # 数据存储
│   └── notifier/          # 邮件通知
├── config/                 # 配置文件
├── data/                   # 数据库文件
├── logs/                   # 日志文件
└── tests/                  # 测试文件
```

## License

MIT
