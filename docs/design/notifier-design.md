# Notifier Module Design Document

## Module Overview

**Module Name**: Email Notification System
**Location**: `src/notifier/`
**Purpose**: Send beautifully formatted HTML email digests to users with trend charts and personalized content.

**Key Features**:
- Per-recipient email sending for deliverability
- HTML email templates with Jinja2
- Embedded trend chart images
- Fallback template system
- SMTP with SSL/TLS support
- Retry logic for transient failures
- Beautiful gradient cards for top picks

---

## File Structure

```
src/notifier/
├── __init__.py                   # Package exports
├── email_sender.py               # SMTP email sender (281 lines)
└── templates/
    └── daily_digest.html         # Jinja2 template (optional)
```

**Lines of Code**: ~300 lines (including inline template)
**Complexity**: Medium (handles SMTP, HTML rendering, image embedding)

---

## Class Diagrams

### Email Sender Architecture

```
┌──────────────────────────┐
│     EmailSender          │
│                          │
│  - config: EmailConfig   │
│  - env: Jinja2Environment│
│                          │
│  + send_digest()         │◄───── DailyDigest
│  + send_test_email()     │
│  - _send_to_single_      │
│    recipient()           │
│  - _render_digest()      │
│  - _render_fallback_     │
│    digest()              │
└──────────────────────────┘
         │
         │ uses
         ▼
┌──────────────────────────┐
│    aiosmtplib            │
│                          │
│  + send()                │
└──────────────────────────┘
```

### Email Construction Flow

```
DailyDigest
     │
     ├─► _render_digest()
     │      │
     │      ├─► Jinja2 template (if exists)
     │      └─► _render_fallback_digest() (if template missing)
     │             │
     │             └─► HTML string
     │
     ├─► For each recipient:
     │      │
     │      ├─► Construct MIME message
     │      │      │
     │      │      ├─► HTML part
     │      │      └─► Embedded image (trend chart)
     │      │
     │      └─► _send_to_single_recipient()
     │             │
     │             └─► aiosmtplib.send()
     │
     └─► Return success count
```

---

## Key Components

### 1. EmailSender (email_sender.py)

**SMTP email sender with HTML rendering.**

#### Initialization

```python
class EmailSender:
    """
    Email notification sender.

    Features:
    - Per-recipient sending for better deliverability
    - HTML email with Jinja2 templates
    - Embedded trend chart images
    - Fallback template if Jinja2 template missing
    - SMTP with SSL/TLS support
    """

    def __init__(self, config: EmailConfig):
        """
        Initialize email sender.

        Args:
            config: Email configuration (SMTP, credentials, recipients)
        """
        self.config = config

        # Setup Jinja2 for templates
        template_dir = Path(__file__).parent / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)

        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
```

#### Main Send Method

```python
async def send_digest(
    self,
    digest: DailyDigest,
    trend_chart_path: str = None
) -> bool:
    """
    Send daily digest to all configured recipients.

    Sends individual emails (not BCC) for better deliverability
    and spam filter compatibility.

    Args:
        digest: DailyDigest object with articles
        trend_chart_path: Optional path to trend chart PNG

    Returns:
        True if at least one email sent successfully

    Example:
        >>> sender = EmailSender(config.email)
        >>> digest = DailyDigest(...)
        >>> success = await sender.send_digest(digest, "charts/trend.png")
    """
    if not self.config.to_addrs:
        logger.warning("no_recipients_configured")
        return False

    # Render HTML once (reused for all recipients)
    html_content = self._render_digest(digest)

    # Preload trend chart data
    trend_chart_data = None
    if trend_chart_path:
        try:
            if os.path.exists(trend_chart_path):
                with open(trend_chart_path, 'rb') as f:
                    trend_chart_data = f.read()
                logger.debug("trend_chart_loaded", path=trend_chart_path)
        except Exception as e:
            logger.warning("trend_chart_load_failed", error=str(e))

    # Send to each recipient individually
    success_count = 0
    failed_recipients = []

    for recipient in self.config.to_addrs:
        try:
            success = await self._send_to_single_recipient(
                recipient=recipient,
                digest=digest,
                html_content=html_content,
                trend_chart_data=trend_chart_data
            )
            if success:
                success_count += 1
            else:
                failed_recipients.append(recipient)
        except Exception as e:
            logger.error("email_send_failed_to_recipient",
                       recipient=recipient,
                       error=str(e))
            failed_recipients.append(recipient)

    # Log summary
    logger.info("digest_sent_summary",
               total_recipients=len(self.config.to_addrs),
               success=success_count,
               failed=len(failed_recipients),
               top_picks=len(digest.top_picks))

    if failed_recipients:
        logger.warning("some_emails_failed",
                      failed_recipients=failed_recipients)

    return success_count > 0
```

#### Per-Recipient Sending

```python
async def _send_to_single_recipient(
    self,
    recipient: str,
    digest: DailyDigest,
    html_content: str,
    trend_chart_data: bytes = None
) -> bool:
    """
    Send email to a single recipient.

    Benefits of individual sends:
    - Better deliverability (not flagged as BCC spam)
    - Proper "To:" field for each recipient
    - Individual error tracking

    Args:
        recipient: Single email address
        digest: Daily digest data
        html_content: Rendered HTML
        trend_chart_data: Optional embedded image bytes

    Returns:
        True if sent successfully
    """
    try:
        from email.mime.image import MIMEImage

        # Construct MIME message
        msg = MIMEMultipart("related")
        msg["Subject"] = f"AI 阅读简报 - {digest.date.strftime('%Y-%m-%d')}"
        msg["From"] = self.config.from_addr
        msg["To"] = recipient  # Individual recipient

        # Add HTML content
        msg_alternative = MIMEMultipart("alternative")
        html_part = MIMEText(html_content, "html", "utf-8")
        msg_alternative.attach(html_part)
        msg.attach(msg_alternative)

        # Embed trend chart image
        if trend_chart_data:
            try:
                img = MIMEImage(trend_chart_data, _subtype="png")
                img.add_header('Content-ID', '<trend_chart>')
                img.add_header('Content-Disposition', 'inline',
                             filename='trend_chart.png')
                msg.attach(img)
            except Exception as e:
                logger.warning("trend_chart_attach_failed",
                             recipient=recipient,
                             error=str(e))

        # Send via SMTP
        if self.config.use_ssl:
            await aiosmtplib.send(
                msg,
                hostname=self.config.smtp_host,
                port=self.config.smtp_port,
                username=self.config.username,
                password=self.config.password,
                use_tls=True,
            )
        else:
            await aiosmtplib.send(
                msg,
                hostname=self.config.smtp_host,
                port=self.config.smtp_port,
                username=self.config.username,
                password=self.config.password,
                start_tls=True,
            )

        logger.debug("email_sent_to_recipient", recipient=recipient)
        return True

    except Exception as e:
        logger.error("email_send_failed",
                   recipient=recipient,
                   error=str(e))
        return False
```

#### Template Rendering

```python
def _render_digest(self, digest: DailyDigest) -> str:
    """
    Render digest to HTML.

    Uses Jinja2 template if available, otherwise fallback template.

    Args:
        digest: Daily digest data

    Returns:
        HTML string
    """
    try:
        template = self.env.get_template("daily_digest.html")
        return template.render(
            digest=digest,
            date_str=digest.date.strftime("%Y年%m月%d日"),
        )
    except Exception:
        # Template not found or error - use fallback
        return self._render_fallback_digest(digest)
```

#### Fallback Template

```python
def _render_fallback_digest(self, digest: DailyDigest) -> str:
    """
    Built-in HTML template (no external dependencies).

    Beautiful gradient card design with:
    - Statistics cards
    - Gradient backgrounds for top picks
    - Clean table layout for other articles
    - Responsive design
    """
    date_str = digest.date.strftime("%Y年%m月%d日")

    # Build top picks section
    top_picks_html = ""
    for i, article in enumerate(digest.top_picks, 1):
        tags_html = f'<span style="...">🏷️ {article.tags_display}</span>' \
                    if article.tags else ''

        top_picks_html += f"""
        <div style="margin-bottom: 24px; padding: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    border-radius: 12px; color: white;">
            <div style="...">
                <span>#{i} 精选</span>
                <span>⭐ {article.score:.1f}分</span>
                {tags_html}
            </div>
            <h3 style="...">
                <a href="{article.url}" style="color: white;">
                    {article.title}
                </a>
            </h3>
            <p>{article.summary}</p>
            <div>📰 {article.source}</div>
            {f'<div>编辑点评: {article.reasoning}</div>'
             if article.reasoning else ''}
        </div>
        """

    # Build other articles table
    other_articles_html = ""
    for article in digest.other_articles:
        score_color = "#22c55e" if article.score >= 7 else \
                     ("#eab308" if article.score >= 5 else "#ef4444")
        tags_text = article.tags_display or article.source

        other_articles_html += f"""
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 12px 0;">
                <a href="{article.url}">{article.title}</a>
                <div style="color: #6b7280;">{article.summary}</div>
                <div style="color: #9ca3af;">🏷️ {tags_text}</div>
            </td>
            <td style="text-align: center;">
                <span style="color: {score_color};">{article.score:.1f}</span>
            </td>
            <td>{article.source}</td>
        </tr>
        """

    # Complete HTML
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: -apple-system, ...; max-width: 700px;
                 margin: 0 auto; padding: 20px; background: #f9fafb;">

        <!-- Header -->
        <div style="text-align: center; margin-bottom: 30px;">
            <h1>📬 AI 阅读简报</h1>
            <p>{date_str}</p>
        </div>

        <!-- Statistics -->
        <div style="display: flex; justify-content: center; gap: 15px;">
            <div style="background: white; padding: 15px 25px; ...">
                <div style="font-size: 24px; color: #3b82f6;">
                    {digest.total_fetched}
                </div>
                <div>抓取文章</div>
            </div>
            <div style="...">
                <div style="font-size: 24px; color: #10b981;">
                    {digest.total_analyzed}
                </div>
                <div>AI 分析</div>
            </div>
            <div style="...">
                <div style="font-size: 24px; color: #8b5cf6;">
                    {len(digest.top_picks)}
                </div>
                <div>精选推荐</div>
            </div>
        </div>

        <!-- Top Picks -->
        <div style="margin-bottom: 40px;">
            <h2>🌟 今日精选 · 值得深读</h2>
            {top_picks_html}
        </div>

        <!-- Other Articles -->
        {f'<div style="background: white; ..."><h2>📋 速览列表</h2><table>...' +
         other_articles_html + '</table></div>' if digest.other_articles else ''}

        <!-- Footer -->
        <div style="text-align: center; margin-top: 40px; ...">
            <p>本简报由 AI 阅读助手自动生成</p>
            <p>你是算法的主人，不是算法的奴隶 🚀</p>
        </div>

    </body>
    </html>
    """

    return html
```

#### Test Email

```python
async def send_test_email(self) -> bool:
    """
    Send a test email to verify configuration.

    Returns:
        True if test email sent successfully

    Example:
        >>> sender = EmailSender(config.email)
        >>> success = await sender.send_test_email()
        >>> if success:
        ...     print("Email configuration is working!")
    """
    from ..storage.models import DigestArticle

    test_digest = DailyDigest(
        date=datetime.now(),
        top_picks=[],
        other_articles=[],
        total_fetched=100,
        total_analyzed=100,
        total_filtered=5,
    )

    # Add test article
    test_digest.top_picks = [
        DigestArticle(
            title="这是一篇测试精选文章",
            url="https://example.com/1",
            source="测试来源",
            category="测试",
            score=9.0,
            summary="这是 AI 生成的一句话摘要，用于测试邮件发送功能是否正常。",
            reasoning="这是编辑点评，说明为什么推荐这篇文章。",
            is_top_pick=True,
            tags=["科技", "人工智能", "大语言模型"],
        )
    ]

    return await self.send_digest(test_digest)
```

---

## API Documentation

### EmailSender

```python
class EmailSender:
    def __init__(self, config: EmailConfig)

    async def send_digest(
        self,
        digest: DailyDigest,
        trend_chart_path: str = None
    ) -> bool

    async def send_test_email(self) -> bool
```

**Configuration Example**:

```yaml
# config.yaml
email:
  smtp_host: smtp.gmail.com
  smtp_port: 465
  use_ssl: true
  username: your-email@gmail.com
  password: ${EMAIL_PASSWORD}  # From environment
  from_addr: your-email@gmail.com
  from_name: AI Reader
  to_addrs:
    - recipient1@example.com
    - recipient2@example.com
```

**Usage Example**:

```python
from src.notifier import EmailSender
from src.config import get_config
from src.storage.models import DailyDigest, DigestArticle

config = get_config()
sender = EmailSender(config.email)

# Create digest
digest = DailyDigest(
    date=datetime.now(),
    top_picks=[...],
    other_articles=[...],
    total_fetched=150,
    total_analyzed=150,
    total_filtered=20
)

# Send with trend chart
success = await sender.send_digest(
    digest,
    trend_chart_path="data/trend_chart.png"
)

if success:
    print("Digest sent successfully!")
```

---

## Data Flow

### Email Sending Flow

```
DailyDigest
     │
     ├─► Load trend chart image (optional)
     │
     ├─► Render HTML template (once)
     │
     └─► For each recipient:
            │
            ├─► Create MIME message
            │      │
            │      ├─► Set headers (To, From, Subject)
            │      ├─► Attach HTML part
            │      └─► Embed image (Content-ID: <trend_chart>)
            │
            ├─► Connect to SMTP server
            │
            ├─► Authenticate
            │
            └─► Send message
                   │
                   ├─► Success ──► Log + Continue
                   │
                   └─► Failure ──► Log + Add to failed list
```

### Template Rendering Flow

```
_render_digest()
     │
     ├─► Try Jinja2 template
     │      │
     │      ├─► Template exists ──► Render
     │      │
     │      └─► Template missing ──┐
     │                             │
     └─► _render_fallback_digest() ◄┘
            │
            └─► Return built-in HTML
```

---

## Design Patterns

### 1. Template Method Pattern

```python
def _render_digest(self, digest):
    try:
        return self._render_jinja_template(digest)
    except:
        return self._render_fallback_digest(digest)
```

### 2. Builder Pattern (MIME Message)

```python
msg = MIMEMultipart("related")
msg["Subject"] = "..."
msg["From"] = "..."
msg["To"] = "..."

html_part = MIMEText(html, "html", "utf-8")
msg.attach(html_part)

img = MIMEImage(image_data)
img.add_header('Content-ID', '<trend_chart>')
msg.attach(img)
```

### 3. Strategy Pattern (SSL/TLS)

```python
if self.config.use_ssl:
    await aiosmtplib.send(..., use_tls=True)
else:
    await aiosmtplib.send(..., start_tls=True)
```

---

## Error Handling

### Per-Recipient Error Isolation

```python
for recipient in recipients:
    try:
        await self._send_to_single_recipient(recipient, ...)
    except Exception as e:
        logger.error("send_failed", recipient=recipient, error=str(e))
        failed_recipients.append(recipient)
        # Continue to next recipient
```

### Template Fallback

```python
try:
    return jinja_template.render(...)
except:
    return self._render_fallback_digest(...)
```

### Image Embedding Failure

```python
if trend_chart_data:
    try:
        img = MIMEImage(trend_chart_data)
        msg.attach(img)
    except Exception as e:
        logger.warning("chart_attach_failed", error=str(e))
        # Continue without chart
```

---

## Performance Considerations

### 1. Render HTML Once

```python
# Good - render once, reuse
html_content = self._render_digest(digest)
for recipient in recipients:
    await send(recipient, html_content)

# Bad - render for each recipient
for recipient in recipients:
    html_content = self._render_digest(digest)  # Wasteful
    await send(recipient, html_content)
```

### 2. Preload Image Data

```python
# Load image once before loop
with open(chart_path, 'rb') as f:
    image_data = f.read()

for recipient in recipients:
    msg.attach(MIMEImage(image_data))  # Reuse data
```

### 3. Async SMTP

```python
# Use async library for non-blocking
await aiosmtplib.send(...)  # Non-blocking

# Not this
smtplib.SMTP().send(...)  # Blocking
```

---

## Testing Strategy

### Unit Tests

```python
def test_fallback_template():
    sender = EmailSender(config)

    digest = DailyDigest(
        date=datetime.now(),
        top_picks=[test_article],
        other_articles=[]
    )

    html = sender._render_fallback_digest(digest)

    assert "📬 AI 阅读简报" in html
    assert test_article.title in html
    assert str(test_article.score) in html

async def test_send_test_email():
    sender = EmailSender(config)
    success = await sender.send_test_email()
    assert success
```

### Integration Tests

```python
@pytest.mark.asyncio
async def test_full_email_send():
    config = get_test_config()
    sender = EmailSender(config)

    digest = create_test_digest()
    success = await sender.send_digest(digest)

    assert success
    # Verify email received (manual check or test server)
```

---

## Best Practices

### 1. Individual Recipient Sending

```python
# Good - better deliverability
for recipient in recipients:
    await send_to_single_recipient(recipient, ...)

# Bad - may be flagged as spam
msg["Bcc"] = ", ".join(recipients)
```

### 2. Proper MIME Structure

```python
# Good - proper multipart structure
msg = MIMEMultipart("related")
alternative = MIMEMultipart("alternative")
alternative.attach(MIMEText(html, "html"))
msg.attach(alternative)
msg.attach(MIMEImage(image))

# Bad - flat structure may not render properly
```

### 3. Error Logging

```python
# Good - log failures but continue
try:
    await send(recipient)
except Exception as e:
    logger.error("send_failed", recipient=recipient, error=str(e))

# Bad - one failure stops all
await send(recipient)  # May crash entire batch
```

---

## Extension Points

### 1. Multiple Template Themes

```python
class ThemedEmailSender(EmailSender):
    def _render_digest(self, digest, theme="default"):
        template = self.env.get_template(f"digest_{theme}.html")
        return template.render(digest=digest)
```

### 2. Attachment Support

```python
def attach_file(self, msg, file_path):
    with open(file_path, 'rb') as f:
        attachment = MIMEApplication(f.read())
        attachment.add_header('Content-Disposition', 'attachment',
                            filename=os.path.basename(file_path))
        msg.attach(attachment)
```

### 3. Alternative Notification Channels

```python
class MultiChannelNotifier:
    async def send_digest(self, digest):
        await self.email_sender.send_digest(digest)
        await self.slack_sender.send_digest(digest)
        await self.telegram_sender.send_digest(digest)
```

---

## Summary

The Notifier module provides professional email delivery:

**Key Features**:
1. **Per-Recipient Sending**: Better deliverability and tracking
2. **Beautiful HTML**: Gradient cards and responsive design
3. **Template Flexibility**: Jinja2 + fallback system
4. **Image Embedding**: Trend charts inline in email
5. **Error Resilience**: One failure doesn't stop others
6. **Testing Support**: Easy test email functionality

The module ensures users receive visually appealing, informative daily digests reliably.
