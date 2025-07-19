import asyncio
import websockets
import json
import logging
import time
from config import WEBSOCKET_URL, SYNC_TIME

logger = logging.getLogger(__name__)

class ConnectionState:
    """WebSocket连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


class WebSocketHandler:
    """WebSocket处理器，负责处理实时数据流"""

    def __init__(self, exchange_client, grid_strategy):
        self.exchange_client = exchange_client
        self.grid_strategy = grid_strategy
        self.coin_name = exchange_client.coin_name
        self.contract_type = exchange_client.contract_type
        self.listenKey = None

        # 价格和时间相关变量
        self.latest_price = 0
        self.best_bid_price = None
        self.best_ask_price = None
        self.last_ticker_update_time = 0
        self.last_position_update_time = 0
        self.last_orders_update_time = 0

        # 停止信号
        self.stop_signal = False

        # 连接状态管理
        self.connection_state = ConnectionState.DISCONNECTED
        self.reconnect_count = 0
        self.max_retries = 5
        self.retry_delay = 5
        self.last_heartbeat = time.time()

        # 错误处理
        self.error_count = 0
        self.max_errors = 10
        self.consecutive_errors = 0
        self.last_successful_message = time.time()


        
    def set_stop_signal(self):
        """设置停止信号"""
        self.stop_signal = True

    async def start(self):
        """启动WebSocket连接"""
        # 获取listenKey
        self.listenKey = self.exchange_client.get_listen_key()

        # 启动 listenKey 更新任务
        asyncio.create_task(self.keep_listen_key_alive())

        while not self.stop_signal:
            try:
                await self.connect_websocket()
                if self.stop_signal:
                    break
            except Exception as e:
                if not self.stop_signal:
                    logger.error(f"WebSocket 连接失败: {e}")
                    await asyncio.sleep(5)
                else:
                    break

        logger.info("WebSocket处理器已停止")

    async def connect_websocket(self):
        """连接 WebSocket 并订阅数据"""
        async with websockets.connect(WEBSOCKET_URL) as websocket:
            # 订阅 ticker 数据
            await self.subscribe_ticker(websocket)
            # 订阅挂单数据
            await self.subscribe_orders(websocket)

            while not self.stop_signal:
                try:
                    # 设置超时，以便能够及时响应停止信号
                    message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    data = json.loads(message)

                    if data.get("e") == "bookTicker":
                        await self.handle_ticker_update(message)
                    elif data.get("e") == "ORDER_TRADE_UPDATE":
                        await self.handle_order_update(message)

                except asyncio.TimeoutError:
                    # 超时是正常的，继续循环检查停止信号
                    continue
                except Exception as e:
                    if not self.stop_signal:
                        logger.error(f"WebSocket 消息处理失败: {e}")
                    break

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
        if not self.listenKey:
            logger.error("listenKey 为空，无法订阅订单更新")
            return

        payload = {
            "method": "SUBSCRIBE",
            "params": [f"{self.listenKey}"],
            "id": 3
        }
        await websocket.send(json.dumps(payload))
        logger.info(f"已发送挂单订阅请求: {payload}")

    async def keep_listen_key_alive(self):
        """定期更新 listenKey"""
        while not self.stop_signal:
            try:
                await asyncio.sleep(1800)  # 每 30 分钟更新一次
                if self.stop_signal:
                    break
                self.exchange_client.update_listen_key()
                self.listenKey = self.exchange_client.get_listen_key()
                logger.info(f"listenKey 已更新: {self.listenKey}")
            except Exception as e:
                if not self.stop_signal:
                    logger.error(f"更新 listenKey 失败: {e}")
                    await asyncio.sleep(60)

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
