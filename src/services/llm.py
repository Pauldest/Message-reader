"""统一的 LLM 调用服务"""

import json
import re
import time
import uuid
from typing import Optional, Any
from openai import AsyncOpenAI
import structlog

from ..config import AIConfig

logger = structlog.get_logger()

# 延迟导入避免循环依赖
_telemetry = None

def _get_telemetry():
    """延迟获取遥测服务"""
    global _telemetry
    if _telemetry is None:
        try:
            from .telemetry import get_telemetry
            _telemetry = get_telemetry()
        except:
            _telemetry = None
    return _telemetry


class LLMService:
    """
    统一的 LLM 服务层
    
    提供：
    - 统一的调用接口
    - 自动重试
    - Token 使用追踪
    - JSON 解析辅助
    - 遥测记录
    """
    
    def __init__(self, config: AIConfig):
        self.config = config
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self.model = config.model
        self.default_max_tokens = config.max_tokens
        self.default_temperature = config.temperature
    
    async def chat(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
        retry_count: int = 3,
    ) -> tuple[str, dict]:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            max_tokens: 最大输出 token
            temperature: 温度
            json_mode: 是否期望 JSON 输出
            retry_count: 重试次数
            
        Returns:
            (response_text, token_usage)
        """
        max_tokens = max_tokens or self.default_max_tokens
        temperature = temperature if temperature is not None else self.default_temperature
        
        call_id = str(uuid.uuid4())
        start_time = time.time()
        retry_attempts = 0
        last_error = None
        
        for attempt in range(retry_count):
            retry_attempts = attempt
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                
                duration = time.time() - start_time
                duration_ms = int(duration * 1000)
                content = response.choices[0].message.content or ""
                
                token_usage = {
                    "prompt": response.usage.prompt_tokens if response.usage else 0,
                    "completion": response.usage.completion_tokens if response.usage else 0,
                    "total": response.usage.total_tokens if response.usage else 0,
                }
                
                logger.debug(
                    "llm_call_success",
                    model=self.model,
                    duration=f"{duration:.2f}s",
                    tokens=token_usage,
                )
                
                # 记录遥测
                telemetry = _get_telemetry()
                if telemetry:
                    telemetry.record_chat(
                        model=self.model,
                        messages=messages,
                        response=content,
                        token_usage=token_usage,
                        duration_ms=duration_ms,
                        retry_count=retry_attempts,
                        caller="LLMService.chat",
                    )
                
                return content, token_usage
                
            except Exception as e:
                last_error = e
                logger.warning(
                    "llm_call_failed",
                    attempt=attempt + 1,
                    error=str(e),
                )
                if attempt < retry_count - 1:
                    await self._exponential_backoff(attempt)
        
        # 记录失败的遥测
        duration_ms = int((time.time() - start_time) * 1000)
        telemetry = _get_telemetry()
        if telemetry:
            telemetry.record_chat(
                model=self.model,
                messages=messages,
                response="",
                token_usage={"prompt": 0, "completion": 0, "total": 0},
                duration_ms=duration_ms,
                retry_count=retry_attempts,
                error=str(last_error),
                caller="LLMService.chat",
            )
        
        raise last_error
    
    async def chat_json(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        retry_count: int = 3,
    ) -> tuple[Optional[dict], dict]:
        """
        发送聊天请求并解析 JSON 响应
        
        Returns:
            (parsed_json, token_usage) - 如果解析失败，parsed_json 为 None
        """
        start_time = time.time()
        content, token_usage = await self.chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            json_mode=True,
            retry_count=retry_count,
        )
        
        parsed = self.parse_json(content)
        
        # 额外记录 JSON 解析结果
        telemetry = _get_telemetry()
        if telemetry:
            duration_ms = int((time.time() - start_time) * 1000)
            telemetry.record_chat_json(
                model=self.model,
                messages=messages,
                response=content,
                parsed_json=parsed,
                token_usage=token_usage,
                duration_ms=duration_ms,
                caller="LLMService.chat_json",
            )
        
        return parsed, token_usage
    
    @staticmethod
    def parse_json(content: str) -> Optional[dict]:
        """
        解析 AI 返回的 JSON（带容错）
        
        尝试顺序：
        1. 直接解析
        2. 提取 ```json ... ``` 代码块
        3. 提取花括号内容
        """
        if not content:
            return None
            
        # 尝试直接解析
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # 尝试提取 JSON 代码块
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # 尝试提取花括号内容
        brace_match = re.search(r'\{[\s\S]*\}', content)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass
        
        logger.warning("json_parse_failed", content_preview=content[:200])
        return None
    
    async def _exponential_backoff(self, attempt: int):
        """指数退避"""
        import asyncio
        wait_time = min(2 ** attempt, 30)  # 最多等待 30 秒
        await asyncio.sleep(wait_time)
    
    def build_messages(
        self,
        system_prompt: str,
        user_prompt: str,
        examples: Optional[list[dict]] = None,
    ) -> list[dict]:
        """
        构建消息列表
        
        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            examples: few-shot 示例 [{"user": "...", "assistant": "..."}]
        """
        messages = [{"role": "system", "content": system_prompt}]
        
        if examples:
            for example in examples:
                messages.append({"role": "user", "content": example["user"]})
                messages.append({"role": "assistant", "content": example["assistant"]})
        
        messages.append({"role": "user", "content": user_prompt})
        
        return messages
