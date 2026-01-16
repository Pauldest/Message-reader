"""RSS 源管理模块"""

import asyncio
from pathlib import Path
from typing import Optional
import yaml
import aiohttp
import feedparser
import structlog

from .config import FeedSource, get_config

logger = structlog.get_logger()


class FeedManager:
    """RSS 源管理器"""
    
    def __init__(self, config_dir: Optional[Path] = None):
        if config_dir is None:
            config_dir = Path(__file__).parent.parent / "config"
        self.config_dir = Path(config_dir)
        self.feeds_path = self.config_dir / "feeds.yaml"
        
        # 如果不存在，从示例文件复制
        if not self.feeds_path.exists():
            example_path = self.config_dir / "feeds.example.yaml"
            if example_path.exists():
                import shutil
                shutil.copy(example_path, self.feeds_path)
    
    def _load_feeds(self) -> list[dict]:
        """加载订阅源列表"""
        if not self.feeds_path.exists():
            return []
        
        with open(self.feeds_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        return data.get("feeds", [])
    
    def _save_feeds(self, feeds: list[dict]):
        """保存订阅源列表"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        with open(self.feeds_path, "w", encoding="utf-8") as f:
            yaml.dump(
                {"feeds": feeds},
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
    
    def list_feeds(self) -> list[FeedSource]:
        """列出所有订阅源"""
        feeds_data = self._load_feeds()
        return [FeedSource(**f) for f in feeds_data]
    
    def add_feed(self, name: str, url: str, category: str = "未分类") -> bool:
        """添加订阅源"""
        feeds = self._load_feeds()
        
        # 检查是否已存在
        for feed in feeds:
            if feed.get("url") == url:
                print(f"❌ 订阅源已存在: {feed.get('name')}")
                return False
        
        # 添加新源
        feeds.append({
            "name": name,
            "url": url,
            "category": category,
            "enabled": True,
        })
        
        self._save_feeds(feeds)
        print(f"✅ 已添加订阅源: {name}")
        return True
    
    def remove_feed(self, identifier: str) -> bool:
        """删除订阅源（按名称或 URL）"""
        feeds = self._load_feeds()
        original_count = len(feeds)
        
        # 按名称或 URL 匹配
        feeds = [
            f for f in feeds
            if f.get("name") != identifier and f.get("url") != identifier
        ]
        
        if len(feeds) == original_count:
            print(f"❌ 未找到订阅源: {identifier}")
            return False
        
        self._save_feeds(feeds)
        print(f"✅ 已删除订阅源: {identifier}")
        return True
    
    def toggle_feed(self, identifier: str) -> bool:
        """启用/禁用订阅源"""
        feeds = self._load_feeds()
        
        for feed in feeds:
            if feed.get("name") == identifier or feed.get("url") == identifier:
                feed["enabled"] = not feed.get("enabled", True)
                self._save_feeds(feeds)
                status = "启用" if feed["enabled"] else "禁用"
                print(f"✅ 已{status}订阅源: {feed.get('name')}")
                return True
        
        print(f"❌ 未找到订阅源: {identifier}")
        return False
    
    async def verify_feed(self, url: str, timeout: int = 10) -> dict:
        """验证订阅源是否有效"""
        result = {
            "url": url,
            "valid": False,
            "title": None,
            "count": 0,
            "error": None,
        }
        
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        result["error"] = f"HTTP {response.status}"
                        return result
                    
                    content = await response.text()
                    parsed = feedparser.parse(content)
                    
                    if parsed.bozo and not parsed.entries:
                        result["error"] = "无效的 RSS/Atom 格式"
                        return result
                    
                    result["valid"] = True
                    result["title"] = parsed.feed.get("title", "未知")
                    result["count"] = len(parsed.entries)
                    
                    return result
        
        except asyncio.TimeoutError:
            result["error"] = "连接超时"
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    async def verify_all_feeds(self) -> list[dict]:
        """验证所有订阅源"""
        feeds = self.list_feeds()
        
        if not feeds:
            print("📭 没有配置任何订阅源")
            return []
        
        print(f"🔍 正在验证 {len(feeds)} 个订阅源...\n")
        
        results = []
        for feed in feeds:
            result = await self.verify_feed(feed.url)
            result["name"] = feed.name
            result["enabled"] = feed.enabled
            results.append(result)
            
            # 显示结果
            if result["valid"]:
                status = "✅" if feed.enabled else "⏸️"
                print(f"{status} {feed.name}: {result['count']} 篇文章")
            else:
                print(f"❌ {feed.name}: {result['error']}")
        
        return results


def print_feeds_table(feeds: list[FeedSource]):
    """打印订阅源表格"""
    if not feeds:
        print("📭 没有配置任何订阅源")
        print("使用 'python -m src.feeds add <名称> <URL>' 添加订阅源")
        return
    
    print(f"\n📰 共 {len(feeds)} 个订阅源:\n")
    print(f"{'状态':<4} {'名称':<20} {'分类':<10} {'URL'}")
    print("-" * 80)
    
    for feed in feeds:
        status = "✅" if feed.enabled else "⏸️"
        name = feed.name[:18] + ".." if len(feed.name) > 20 else feed.name
        category = feed.category[:8] + ".." if len(feed.category) > 10 else feed.category
        url = feed.url[:40] + "..." if len(feed.url) > 43 else feed.url
        print(f"{status:<4} {name:<20} {category:<10} {url}")


def main():
    """RSS 源管理 CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="RSS 源管理工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m src.feeds list                    # 列出所有订阅源
  python -m src.feeds add 少数派 https://sspai.com/feed 科技
                                              # 添加订阅源
  python -m src.feeds remove 少数派           # 删除订阅源
  python -m src.feeds verify                  # 验证所有订阅源
  python -m src.feeds verify https://...      # 验证单个 URL
  python -m src.feeds toggle 少数派           # 启用/禁用订阅源
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # list 命令
    subparsers.add_parser("list", aliases=["ls"], help="列出所有订阅源")
    
    # add 命令
    add_parser = subparsers.add_parser("add", help="添加订阅源")
    add_parser.add_argument("name", help="订阅源名称")
    add_parser.add_argument("url", help="RSS/Atom URL")
    add_parser.add_argument("category", nargs="?", default="未分类", help="分类（可选）")
    
    # remove 命令
    remove_parser = subparsers.add_parser("remove", aliases=["rm", "delete"], help="删除订阅源")
    remove_parser.add_argument("identifier", help="订阅源名称或 URL")
    
    # verify 命令
    verify_parser = subparsers.add_parser("verify", aliases=["check", "test"], help="验证订阅源")
    verify_parser.add_argument("url", nargs="?", help="要验证的 URL（可选，不填则验证全部）")
    
    # toggle 命令
    toggle_parser = subparsers.add_parser("toggle", help="启用/禁用订阅源")
    toggle_parser.add_argument("identifier", help="订阅源名称或 URL")
    
    args = parser.parse_args()
    manager = FeedManager()
    
    if args.command in ("list", "ls", None):
        feeds = manager.list_feeds()
        print_feeds_table(feeds)
    
    elif args.command == "add":
        # 先验证 URL
        print(f"🔍 正在验证 {args.url}...")
        result = asyncio.run(manager.verify_feed(args.url))
        
        if result["valid"]:
            print(f"✅ 有效！发现 {result['count']} 篇文章")
            # 如果没有指定名称，使用 feed 的标题
            name = args.name or result["title"]
            manager.add_feed(name, args.url, args.category)
        else:
            print(f"❌ 验证失败: {result['error']}")
            confirm = input("是否仍要添加？(y/N): ")
            if confirm.lower() == "y":
                manager.add_feed(args.name, args.url, args.category)
    
    elif args.command in ("remove", "rm", "delete"):
        manager.remove_feed(args.identifier)
    
    elif args.command in ("verify", "check", "test"):
        if args.url:
            print(f"🔍 正在验证 {args.url}...")
            result = asyncio.run(manager.verify_feed(args.url))
            
            if result["valid"]:
                print(f"\n✅ 订阅源有效!")
                print(f"   标题: {result['title']}")
                print(f"   文章数: {result['count']}")
            else:
                print(f"\n❌ 验证失败: {result['error']}")
        else:
            asyncio.run(manager.verify_all_feeds())
    
    elif args.command == "toggle":
        manager.toggle_feed(args.identifier)
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
