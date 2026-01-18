"""邮件发送模块"""

from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape
import structlog

from ..config import EmailConfig
from ..storage.models import DailyDigest

logger = structlog.get_logger()


class EmailSender:
    """邮件发送器"""
    
    def __init__(self, config: EmailConfig):
        self.config = config
        
        # 设置 Jinja2 模板环境
        template_dir = Path(__file__).parent / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
    
    async def send_digest(self, digest: DailyDigest, trend_chart_path: str = None) -> bool:
        """发送每日简报"""
        if not self.config.to_addrs:
            logger.warning("no_recipients_configured")
            return False
        
        try:
            # 渲染邮件内容
            html_content = self._render_digest(digest)
            
            # 构建邮件 - 使用 related 类型以支持内嵌图片
            msg = MIMEMultipart("related")
            msg["Subject"] = f"AI 阅读简报 - {digest.date.strftime('%Y-%m-%d')}"
            msg["From"] = self.config.from_addr
            msg["To"] = ", ".join(self.config.to_addrs)
            
            # 添加 HTML 内容
            msg_alternative = MIMEMultipart("alternative")
            html_part = MIMEText(html_content, "html", "utf-8")
            msg_alternative.attach(html_part)
            msg.attach(msg_alternative)
            
            # 添加趋势图图片作为内嵌附件
            if trend_chart_path:
                try:
                    from email.mime.image import MIMEImage
                    import os
                    
                    if os.path.exists(trend_chart_path):
                        with open(trend_chart_path, 'rb') as f:
                            img_data = f.read()
                        
                        img = MIMEImage(img_data, _subtype="png")
                        img.add_header('Content-ID', '<trend_chart>')
                        img.add_header('Content-Disposition', 'inline', filename='trend_chart.png')
                        msg.attach(img)
                        logger.debug("trend_chart_attached", path=trend_chart_path)
                except Exception as e:
                    logger.warning("trend_chart_attach_failed", error=str(e))
            
            # 发送邮件
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
            
            logger.info("digest_sent",
                       recipients=len(self.config.to_addrs),
                       top_picks=len(digest.top_picks))
            return True
        
        except Exception as e:
            logger.error("email_send_failed", error=str(e))
            return False
    
    def _render_digest(self, digest: DailyDigest) -> str:
        """渲染简报 HTML"""
        try:
            template = self.env.get_template("daily_digest.html")
            return template.render(
                digest=digest,
                date_str=digest.date.strftime("%Y年%m月%d日"),
            )
        except Exception:
            # 如果模板不存在，使用内置模板
            return self._render_fallback_digest(digest)
    
    def _render_fallback_digest(self, digest: DailyDigest) -> str:
        """内置简报模板"""
        date_str = digest.date.strftime("%Y年%m月%d日")
        
        top_picks_html = ""
        for i, article in enumerate(digest.top_picks, 1):
            tags_html = f'<span style="background: rgba(255,255,255,0.15); padding: 2px 8px; border-radius: 4px; font-size: 11px; margin-right: 8px;">🏷️ {article.tags_display}</span>' if article.tags else ''
            top_picks_html += f"""
            <div style="margin-bottom: 24px; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; color: white;">
                <div style="display: flex; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px;">
                    <span style="background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 20px; font-size: 12px;">#{i} 精选</span>
                    <span style="background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 20px; font-size: 12px;">⭐ {article.score:.1f}分</span>
                    {tags_html}
                </div>
                <h3 style="margin: 0 0 10px 0; font-size: 18px;">
                    <a href="{article.url}" style="color: white; text-decoration: none;">{article.title}</a>
                </h3>
                <p style="margin: 0 0 10px 0; font-size: 14px; opacity: 0.9;">{article.summary}</p>
                <div style="font-size: 12px; opacity: 0.8;">
                    📰 {article.source}
                </div>
                {f'<div style="margin-top: 10px; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 8px; font-size: 13px;"><strong>编辑点评：</strong>{article.reasoning}</div>' if article.reasoning else ''}
            </div>
            """
        
        other_articles_html = ""
        for article in digest.other_articles:
            score_color = "#22c55e" if article.score >= 7 else ("#eab308" if article.score >= 5 else "#ef4444")
            tags_text = article.tags_display if article.tags else article.source
            other_articles_html += f"""
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <td style="padding: 12px 0;">
                    <a href="{article.url}" style="color: #1f2937; text-decoration: none; font-weight: 500;">{article.title}</a>
                    <div style="color: #6b7280; font-size: 13px; margin-top: 4px;">{article.summary}</div>
                    <div style="color: #9ca3af; font-size: 11px; margin-top: 2px;">🏷️ {tags_text}</div>
                </td>
                <td style="padding: 12px 0; text-align: center; width: 80px;">
                    <span style="color: {score_color}; font-weight: bold;">{article.score:.1f}</span>
                </td>
                <td style="padding: 12px 0; color: #6b7280; font-size: 13px; width: 100px;">{article.source}</td>
            </tr>
            """
        
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; background: #f9fafb;">
            
            <!-- 头部 -->
            <div style="text-align: center; margin-bottom: 30px;">
                <h1 style="margin: 0; font-size: 28px; color: #1f2937;">📬 AI 阅读简报</h1>
                <p style="color: #6b7280; margin: 10px 0 0 0;">{date_str}</p>
            </div>
            
            <!-- 统计卡片 -->
            <div style="display: flex; justify-content: center; gap: 15px; margin-bottom: 30px; flex-wrap: wrap;">
                <div style="background: white; padding: 15px 25px; border-radius: 10px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <div style="font-size: 24px; font-weight: bold; color: #3b82f6;">{digest.total_fetched}</div>
                    <div style="font-size: 12px; color: #6b7280;">抓取文章</div>
                </div>
                <div style="background: white; padding: 15px 25px; border-radius: 10px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <div style="font-size: 24px; font-weight: bold; color: #10b981;">{digest.total_analyzed}</div>
                    <div style="font-size: 12px; color: #6b7280;">AI 分析</div>
                </div>
                <div style="background: white; padding: 15px 25px; border-radius: 10px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <div style="font-size: 24px; font-weight: bold; color: #8b5cf6;">{len(digest.top_picks)}</div>
                    <div style="font-size: 12px; color: #6b7280;">精选推荐</div>
                </div>
            </div>
            
            <!-- 精选文章 -->
            <div style="margin-bottom: 40px;">
                <h2 style="font-size: 20px; color: #1f2937; margin-bottom: 20px;">🌟 今日精选 · 值得深读</h2>
                {top_picks_html}
            </div>
            
            <!-- 其他文章 -->
            {"<div style='background: white; padding: 20px; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);'><h2 style='font-size: 18px; color: #1f2937; margin: 0 0 15px 0;'>📋 速览列表</h2><table style='width: 100%; border-collapse: collapse;'><thead><tr style='border-bottom: 2px solid #e5e7eb;'><th style='text-align: left; padding: 10px 0; color: #6b7280; font-weight: 500;'>文章</th><th style='text-align: center; padding: 10px 0; color: #6b7280; font-weight: 500;'>评分</th><th style='text-align: left; padding: 10px 0; color: #6b7280; font-weight: 500;'>来源</th></tr></thead><tbody>" + other_articles_html + "</tbody></table></div>" if digest.other_articles else ""}
            
            <!-- 页脚 -->
            <div style="text-align: center; margin-top: 40px; padding: 20px; color: #9ca3af; font-size: 13px;">
                <p>本简报由 AI 阅读助手自动生成</p>
                <p>你是算法的主人，不是算法的奴隶 🚀</p>
            </div>
            
        </body>
        </html>
        """
        
        return html

    async def send_test_email(self) -> bool:
        """发送测试邮件"""
        test_digest = DailyDigest(
            date=datetime.now(),
            top_picks=[],
            other_articles=[],
            total_fetched=100,
            total_analyzed=100,
            total_filtered=5,
        )
        
        # 添加测试数据
        from ..storage.models import DigestArticle
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
