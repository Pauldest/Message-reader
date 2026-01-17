"""Agent 基类"""

import time
from abc import ABC, abstractmethod
from typing import Any, Optional
import structlog

from ..services.llm import LLMService
from ..models.agent import AgentContext, AgentOutput, AgentTrace

logger = structlog.get_logger()


class BaseAgent(ABC):
    """
    所有 Agent 的基类
    
    提供：
    - 统一的 LLM 调用接口
    - 自动追踪（Trace）
    - 错误处理
    """
    
    # 子类应该覆盖这些
    AGENT_NAME: str = "BaseAgent"
    SYSTEM_PROMPT: str = ""
    
    def __init__(self, llm_service: LLMService):
        self.llm = llm_service
        self.name = self.AGENT_NAME
    
    @abstractmethod
    async def process(self, input_data: Any, context: AgentContext) -> AgentOutput:
        """
        处理输入数据
        
        Args:
            input_data: 输入数据（具体类型由子类定义）
            context: Agent 上下文
            
        Returns:
            AgentOutput 包含结果和追踪信息
        """
        pass
    
    async def invoke_llm(
        self,
        user_prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        json_mode: bool = False,
    ) -> tuple[Any, dict]:
        """
        调用 LLM
        
        Args:
            user_prompt: 用户提示
            system_prompt: 系统提示（默认使用类的 SYSTEM_PROMPT）
            max_tokens: 最大输出 token
            temperature: 温度
            json_mode: 是否期望 JSON 输出
            
        Returns:
            (response, token_usage)
        """
        # 设置当前 agent 上下文供遥测使用
        try:
            from ..services.telemetry import AITelemetry
            AITelemetry.set_agent(self.name)
        except:
            pass
        
        system = system_prompt or self.SYSTEM_PROMPT
        messages = self.llm.build_messages(system, user_prompt)
        
        if json_mode:
            result, usage = await self.llm.chat_json(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        else:
            result, usage = await self.llm.chat(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        
        return result, usage
    
    def create_trace(
        self,
        input_summary: str,
        output_summary: str,
        duration: float,
        token_usage: dict,
        error: Optional[str] = None,
    ) -> AgentTrace:
        """创建分析追踪"""
        return AgentTrace(
            agent_name=self.name,
            input_summary=input_summary[:500],
            output_summary=output_summary[:500],
            duration_seconds=duration,
            token_usage=token_usage,
            error=error,
        )
    
    async def safe_process(self, input_data: Any, context: AgentContext) -> AgentOutput:
        """
        安全的处理包装器（带错误处理）
        """
        start_time = time.time()
        
        try:
            result = await self.process(input_data, context)
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"{self.name}_failed",
                error=str(e),
                duration=f"{duration:.2f}s",
            )
            return AgentOutput.failure(
                agent_name=self.name,
                error=str(e),
                duration=duration,
            )
    
    def log_start(self, input_summary: str = ""):
        """记录开始处理"""
        logger.info(f"{self.name}_started", input=input_summary[:100])
    
    def log_complete(self, duration: float, output_summary: str = ""):
        """记录处理完成"""
        logger.info(
            f"{self.name}_completed",
            duration=f"{duration:.2f}s",
            output=output_summary[:100],
        )
