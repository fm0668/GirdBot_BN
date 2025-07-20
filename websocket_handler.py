import asyncio
import json
import logging
import time
from config import WEBSOCKET_URL, SYNC_TIME
from connection_manager import ConnectionManager

logger = logging.getLogger(__name__)


class WebSocketHandler:
    """WebSocket处理器，负责处理实时数据流（使用ConnectionManager）"""

    def __init__(self, exchange_client, grid_strategy):
        self.exchange_client = exchange_client
        self.grid_strategy = grid_strategy
        self.coin_name = exchange_client.coin_name
        self.contract_type = exchange_client.contract_type

        # 价格和时间相关变量
        self.latest_price = 0
        self.best_bid_price = None
        self.best_ask_price = None
        self.last_ticker_update_time = 0
        self.last_position_update_time = 0
        self.last_orders_update_time = 0

        # 停止信号
        self.stop_signal = False

        # 连接管理器（将在start方法中初始化）
        self.connection_manager: ConnectionManager = None


        
    def set_stop_signal(self):
        """设置停止信号"""
        self.stop_signal = True
        if self.connection_manager:
            self.connection_manager.set_stop_signal()

    async def start(self):
        """启动WebSocket连接（使用ConnectionManager）"""
        # 获取listenKey
        listen_key = self.exchange_client.get_listen_key()

        # 初始化连接管理器
        self.connection_manager = ConnectionManager(WEBSOCKET_URL, listen_key)

        # 设置回调函数
        self.connection_manager.set_callbacks(
            on_connected=self._on_connected,
            on_reconnected=self._on_reconnected,
            on_message=self._on_message,
            on_disconnected=self._on_disconnected
        )

        # 启动 listenKey 更新任务
        asyncio.create_task(self.keep_listen_key_alive())

        # 启动连接管理器（这将处理所有重连逻辑）
        await self.connection_manager.connect()

        logger.info("WebSocket处理器已停止")

    async def _on_connected(self, websocket):
        """首次连接成功回调"""
        logger.info("🎉 WebSocket首次连接成功，开始订阅数据流...")
        await self._subscribe_all_streams(websocket)

    async def _on_reconnected(self, websocket):
        """重连成功回调"""
        logger.info("🔄 WebSocket重连成功，恢复订阅数据流...")
        await self._subscribe_all_streams(websocket)

    async def _on_message(self, message: str):
        """消息接收回调"""
        try:
            data = json.loads(message)

            if data.get("e") == "bookTicker":
                await self.handle_ticker_update(message)
            elif data.get("e") == "ORDER_TRADE_UPDATE":
                await self.handle_order_update(message)
            else:
                logger.debug(f"收到其他消息类型: {data.get('e', 'unknown')}")

        except Exception as e:
            logger.error(f"消息处理失败: {e}")

    async def _on_disconnected(self):
        """连接断开回调"""
        logger.warning("📡 WebSocket连接已断开")

    async def _subscribe_all_streams(self, websocket):
        """订阅所有数据流（统一的订阅逻辑）"""
        try:
            # 订阅 ticker 数据
            await self.subscribe_ticker(websocket)
            # 订阅挂单数据
            await self.subscribe_orders(websocket)
            logger.info("✅ 所有数据流订阅完成")
        except Exception as e:
            logger.error(f"订阅数据流失败: {e}")
            raise

    async def subscribe_ticker(self, websocket):
        """订阅 ticker 数据"""
        payload = {
            "method": "SUBSCRIBE",
            "params": [f"{self.coin_name.lower()}{self.contract_type.lower()}@bookTicker"],
            "id": 1
        }
        await websocket.send(json.dumps(payload))
        logger.info(f"已发送 ticker 订阅请求: {payload}")

    async def subscribe_orders(self, websocket):
        """订阅挂单数据"""
        if not self.connection_manager or not self.connection_manager.listen_key:
            logger.error("listenKey 为空，无法订阅订单更新")
            return

        payload = {
            "method": "SUBSCRIBE",
            "params": [f"{self.connection_manager.listen_key}"],
            "id": 3
        }
        await websocket.send(json.dumps(payload))
        logger.info(f"已发送挂单订阅请求: {payload}")

    async def keep_listen_key_alive(self):
        """定期更新 listenKey（与ConnectionManager协作）"""
        while not self.stop_signal:
            try:
                await asyncio.sleep(1800)  # 每 30 分钟更新一次
                if self.stop_signal:
                    break

                # 更新listenKey
                self.exchange_client.update_listen_key()
                new_listen_key = self.exchange_client.get_listen_key()

                # 同步到ConnectionManager
                if self.connection_manager and new_listen_key:
                    self.connection_manager.update_listen_key(new_listen_key)

                logger.info(f"listenKey 已更新并同步到ConnectionManager: {new_listen_key}")
            except Exception as e:
                if not self.stop_signal:
                    logger.error(f"更新 listenKey 失败: {e}")
                    await asyncio.sleep(60)

    def get_connection_stats(self):
        """获取连接统计信息"""
        if self.connection_manager:
            return self.connection_manager.get_connection_stats()
        else:
            return {'state': 'not_initialized', 'is_healthy': False}

    async def handle_ticker_update(self, message):
        """处理 ticker 更新"""
        current_time = time.time()
        if current_time - self.last_ticker_update_time < 0.5:
            return

        self.last_ticker_update_time = current_time
        data = json.loads(message)
        
        if data.get("e") == "bookTicker":
            best_bid_price = data.get("b")
            best_ask_price = data.get("a")

            if best_bid_price is None or best_ask_price is None:
                logger.warning("bookTicker 消息中缺少最佳买价或最佳卖价")
                return

            try:
                self.best_bid_price = float(best_bid_price)
                self.best_ask_price = float(best_ask_price)
                self.latest_price = (self.best_bid_price + self.best_ask_price) / 2
            except ValueError as e:
                logger.error(f"解析价格失败: {e}")
                return

            # 更新网格策略的价格信息
            self.grid_strategy.update_prices(self.latest_price, self.best_bid_price, self.best_ask_price)

            # 定期同步持仓和订单状态
            await self.sync_positions_and_orders()

            # 执行网格策略
            await self.grid_strategy.adjust_grid_strategy()

    async def sync_positions_and_orders(self):
        """定期同步持仓和订单状态"""
        current_time = time.time()

        # 同步持仓
        if current_time - self.last_position_update_time > SYNC_TIME:
            long_position, short_position = self.exchange_client.get_position()
            self.grid_strategy.update_positions(long_position, short_position)
            self.last_position_update_time = current_time
            logger.info(f"同步 position: 多头 {long_position} 张, 空头 {short_position} 张 @ ticker")

        # 同步订单
        if current_time - self.last_orders_update_time > SYNC_TIME:
            self.grid_strategy.check_orders_status()
            self.last_orders_update_time = current_time
            orders_info = self.grid_strategy.get_orders_info()
            logger.info(f"同步 orders: {orders_info} @ ticker")

    async def handle_order_update(self, message):
        """处理订单更新"""
        async with self.grid_strategy.lock:
            data = json.loads(message)
            
            if data.get("e") == "ORDER_TRADE_UPDATE":
                order = data.get("o", {})
                symbol = order.get("s")
                
                if symbol == f"{self.coin_name}{self.contract_type}":
                    # 将订单更新传递给网格策略处理
                    await self.grid_strategy.handle_order_update(order)
