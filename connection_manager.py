import asyncio
import websockets
import json
import logging
import time
from enum import Enum
from typing import Optional, Callable, Any
from config import WEBSOCKET_URL

logger = logging.getLogger(__name__)

class ConnectionState(Enum):
    """WebSocket连接状态枚举"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"

class ConnectionManager:
    """专业的WebSocket连接管理器
    
    特性:
    - 指数退避重连策略
    - 状态机管理
    - 回调机制
    - 心跳与健康检查
    - 自动订阅恢复
    """
    
    def __init__(self, url: str, listen_key: str):
        self.url = url
        self.listen_key = listen_key
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        
        # 连接状态管理
        self.state = ConnectionState.DISCONNECTED
        self.stop_signal = False
        
        # 指数退避重连参数
        self.initial_retry_delay = 5  # 初始重连延迟（秒）
        self.max_retry_delay = 60     # 最大重连延迟（秒）
        self.retry_multiplier = 2     # 延迟倍数
        self.current_retry_delay = self.initial_retry_delay
        self.retry_count = 0
        self.max_retries = 10         # 最大重试次数，超过后进入FAILED状态
        
        # 心跳与健康检查
        self.last_message_time = time.time()
        self.last_heartbeat_time = time.time()
        self.heartbeat_interval = 30  # 心跳间隔（秒）
        self.health_check_timeout = 60  # 健康检查超时（秒）
        
        # 回调函数
        self.on_connected_callback: Optional[Callable] = None
        self.on_reconnected_callback: Optional[Callable] = None
        self.on_message_callback: Optional[Callable] = None
        self.on_disconnected_callback: Optional[Callable] = None
        
        # 统计信息
        self.total_reconnects = 0
        self.connection_start_time = None
        
    def set_callbacks(self, 
                     on_connected: Optional[Callable] = None,
                     on_reconnected: Optional[Callable] = None, 
                     on_message: Optional[Callable] = None,
                     on_disconnected: Optional[Callable] = None):
        """设置回调函数"""
        self.on_connected_callback = on_connected
        self.on_reconnected_callback = on_reconnected
        self.on_message_callback = on_message
        self.on_disconnected_callback = on_disconnected
        
    def set_stop_signal(self):
        """设置停止信号"""
        self.stop_signal = True
        
    async def connect(self):
        """主连接方法 - 带指数退避的智能重连"""
        while not self.stop_signal:
            try:
                await self._attempt_connection()
                
                if self.state == ConnectionState.CONNECTED:
                    # 连接成功，重置重连参数
                    self._reset_retry_params()
                    
                    # 启动消息处理和健康检查
                    await asyncio.gather(
                        self._message_loop(),
                        self._health_check_loop(),
                        return_exceptions=True
                    )
                    
            except Exception as e:
                if not self.stop_signal:
                    logger.error(f"连接异常: {e}")
                    await self._handle_connection_failure()
                else:
                    break
                    
        logger.info("ConnectionManager已停止")
        
    async def _attempt_connection(self):
        """尝试建立连接"""
        if self.retry_count > 0:
            self.state = ConnectionState.RECONNECTING
            logger.info(f"🔄 第{self.retry_count}次重连尝试，延迟{self.current_retry_delay}秒...")
            await asyncio.sleep(self.current_retry_delay)
        else:
            self.state = ConnectionState.CONNECTING
            logger.info("🔗 首次连接尝试...")
            
        # 构建WebSocket URL
        ws_url = f"{self.url}/ws/{self.listen_key}"
        
        # 建立连接
        self.websocket = await websockets.connect(ws_url)
        self.state = ConnectionState.CONNECTED
        self.connection_start_time = time.time()
        self.last_message_time = time.time()
        self.last_heartbeat_time = time.time()
        
        logger.info(f"✅ WebSocket连接成功: {ws_url}")
        
        # 触发回调
        if self.retry_count == 0 and self.on_connected_callback:
            await self.on_connected_callback(self.websocket)
        elif self.retry_count > 0 and self.on_reconnected_callback:
            await self.on_reconnected_callback(self.websocket)
            self.total_reconnects += 1
            
    async def _message_loop(self):
        """消息接收循环"""
        try:
            while not self.stop_signal and self.state == ConnectionState.CONNECTED:
                try:
                    # 设置合理的超时时间
                    message = await asyncio.wait_for(
                        self.websocket.recv(), 
                        timeout=self.heartbeat_interval
                    )
                    
                    # 更新最后消息时间
                    self.last_message_time = time.time()
                    
                    # 处理消息
                    if self.on_message_callback:
                        await self.on_message_callback(message)
                        
                except asyncio.TimeoutError:
                    # 超时是正常的，继续循环
                    continue
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket连接已关闭")
            self.state = ConnectionState.DISCONNECTED
        except Exception as e:
            logger.error(f"消息循环异常: {e}")
            self.state = ConnectionState.DISCONNECTED
            
    async def _health_check_loop(self):
        """健康检查循环 - 检测假死连接"""
        while not self.stop_signal and self.state == ConnectionState.CONNECTED:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                
                current_time = time.time()
                
                # 检查是否超过健康检查超时时间
                if current_time - self.last_message_time > self.health_check_timeout:
                    logger.warning(f"⚠️ 连接假死检测: {self.health_check_timeout}秒内无消息")
                    self.state = ConnectionState.DISCONNECTED
                    if self.websocket:
                        await self.websocket.close()
                    break
                    
                # 发送心跳（如果需要）
                if current_time - self.last_heartbeat_time > self.heartbeat_interval:
                    await self._send_heartbeat()
                    self.last_heartbeat_time = current_time
                    
            except Exception as e:
                logger.error(f"健康检查异常: {e}")
                break
                
    async def _send_heartbeat(self):
        """发送心跳包"""
        try:
            if self.websocket and self.state == ConnectionState.CONNECTED:
                # 发送ping帧
                await self.websocket.ping()
                logger.debug("💓 发送心跳包")
        except Exception as e:
            logger.warning(f"心跳发送失败: {e}")
            
    async def send_message(self, message: str):
        """发送消息"""
        if self.websocket and self.state == ConnectionState.CONNECTED:
            try:
                await self.websocket.send(message)
                self.last_message_time = time.time()
                return True
            except Exception as e:
                logger.error(f"发送消息失败: {e}")
                self.state = ConnectionState.DISCONNECTED
                return False
        else:
            logger.warning("连接未就绪，无法发送消息")
            return False
            
    async def _handle_connection_failure(self):
        """处理连接失败"""
        self.retry_count += 1
        
        if self.retry_count > self.max_retries:
            self.state = ConnectionState.FAILED
            logger.error(f"❌ 连接失败次数超过限制({self.max_retries})，进入FAILED状态")
            return
            
        # 指数退避计算
        self.current_retry_delay = min(
            self.initial_retry_delay * (self.retry_multiplier ** (self.retry_count - 1)),
            self.max_retry_delay
        )
        
        logger.warning(f"⏳ 连接失败，{self.current_retry_delay}秒后重试 (第{self.retry_count}/{self.max_retries}次)")
        
        # 触发断开连接回调
        if self.on_disconnected_callback:
            await self.on_disconnected_callback()
            
    def _reset_retry_params(self):
        """重置重连参数"""
        self.retry_count = 0
        self.current_retry_delay = self.initial_retry_delay
        
    def get_connection_stats(self) -> dict:
        """获取连接统计信息"""
        uptime = time.time() - self.connection_start_time if self.connection_start_time else 0
        return {
            'state': self.state.value,
            'total_reconnects': self.total_reconnects,
            'current_retry_count': self.retry_count,
            'uptime_seconds': uptime,
            'last_message_ago': time.time() - self.last_message_time,
            'is_healthy': self.state == ConnectionState.CONNECTED and 
                         (time.time() - self.last_message_time) < self.health_check_timeout
        }
        
    def update_listen_key(self, new_listen_key: str):
        """更新ListenKey"""
        self.listen_key = new_listen_key
        logger.info(f"ListenKey已更新: {new_listen_key}")
