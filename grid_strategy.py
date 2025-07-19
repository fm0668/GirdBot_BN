import asyncio
import time
import logging
import ccxt
from config import (
    GRID_SPACING, INITIAL_QUANTITY, POSITION_THRESHOLD,
    POSITION_LIMIT, ORDER_FIRST_TIME, SYNC_TIME,
    ORDERS_SYNC_COOLDOWN, FAST_SYNC_COOLDOWN,
    PRICE_CHANGE_THRESHOLD, FAST_MARKET_WINDOW,
    API_WEIGHT_LIMIT_PER_MINUTE, FETCH_ORDERS_WEIGHT, SAFETY_MARGIN,
    ENABLE_HEDGE_INITIALIZATION, HEDGE_INIT_DELAY
)

logger = logging.getLogger(__name__)


class GridStrategy:
    """网格交易策略核心逻辑"""
    
    def __init__(self, exchange_client):
        self.exchange_client = exchange_client
        self.lock = asyncio.Lock()
        
        # 价格相关
        self.latest_price = 0
        self.best_bid_price = None
        self.best_ask_price = None
        
        # 持仓相关
        self.long_position = 0
        self.short_position = 0
        
        # 订单数量相关
        self.long_initial_quantity = 0
        self.short_initial_quantity = 0
        self.buy_long_orders = 0.0
        self.sell_long_orders = 0.0
        self.sell_short_orders = 0.0
        self.buy_short_orders = 0.0
        
        # 网格价格相关
        self.mid_price_long = 0
        self.lower_price_long = 0
        self.upper_price_long = 0
        self.mid_price_short = 0
        self.lower_price_short = 0
        self.upper_price_short = 0
        
        # 时间控制
        self.last_long_order_time = 0
        self.last_short_order_time = 0

        # 对冲初始化控制
        self.hedge_initialization_enabled = ENABLE_HEDGE_INITIALIZATION
        self.hedge_init_delay = HEDGE_INIT_DELAY
        self.pending_hedge_initialization = False

        # API调用频率控制
        self.last_orders_sync_time = 0
        self.orders_sync_cooldown = ORDERS_SYNC_COOLDOWN  # 基础冷却时间
        self.fast_sync_cooldown = FAST_SYNC_COOLDOWN      # 快速同步冷却时间
        self.last_price_change_time = 0
        self.price_change_threshold = PRICE_CHANGE_THRESHOLD  # 价格变化阈值
        self.fast_market_window = FAST_MARKET_WINDOW      # 快速市场检测窗口

        # API使用统计
        self.api_calls_count = 0
        self.api_calls_start_time = time.time()
        self.max_safe_calls_per_minute = int(API_WEIGHT_LIMIT_PER_MINUTE * SAFETY_MARGIN / FETCH_ORDERS_WEIGHT)

    def update_prices(self, latest_price, best_bid_price, best_ask_price):
        """更新价格信息"""
        # 检查价格变化幅度
        if self.latest_price > 0:
            price_change_ratio = abs(latest_price - self.latest_price) / self.latest_price
            if price_change_ratio >= self.price_change_threshold:
                self.last_price_change_time = time.time()

        self.latest_price = latest_price
        self.best_bid_price = best_bid_price
        self.best_ask_price = best_ask_price

    def update_positions(self, long_position, short_position):
        """更新持仓信息"""
        self.long_position = long_position
        self.short_position = short_position

    def get_orders_info(self):
        """获取订单信息字符串"""
        return (f"多头买单 {self.buy_long_orders} 张, 多头卖单 {self.sell_long_orders} 张, "
                f"空头卖单 {self.sell_short_orders} 张, 空头买单 {self.buy_short_orders} 张")

    def check_api_usage(self):
        """检查API使用情况"""
        current_time = time.time()
        time_elapsed = current_time - self.api_calls_start_time

        # 每分钟重置计数器
        if time_elapsed >= 60:
            calls_per_minute = self.api_calls_count / (time_elapsed / 60)
            logger.info(f"API使用统计: {calls_per_minute:.1f}次/分钟 (安全限制: {self.max_safe_calls_per_minute}次/分钟)")
            self.api_calls_count = 0
            self.api_calls_start_time = current_time

        # 检查是否接近限制
        if time_elapsed > 0:
            current_rate = self.api_calls_count / (time_elapsed / 60)
            if current_rate > self.max_safe_calls_per_minute * 0.8:
                logger.warning(f"API调用频率较高: {current_rate:.1f}次/分钟，接近安全限制")

    def should_sync_orders(self):
        """智能检查是否应该同步订单状态（避免高频API调用）"""
        current_time = time.time()

        # 检查API使用情况
        self.check_api_usage()

        # 检查是否在快速波动期间
        is_fast_market = (current_time - self.last_price_change_time) <= self.fast_market_window

        if is_fast_market:
            # 快速市场：使用较短的冷却时间
            cooldown = self.fast_sync_cooldown
            logger.debug("检测到快速波动行情，使用快速同步模式")
        else:
            # 正常市场：使用标准冷却时间
            cooldown = self.orders_sync_cooldown

        # 检查冷却时间
        time_since_last_call = current_time - self.last_orders_sync_time
        can_call = time_since_last_call >= cooldown

        if can_call:
            # 记录API调用
            self.api_calls_count += 1

        return can_call

    def check_orders_status(self):
        """检查当前所有挂单的状态，并更新多头和空头的挂单数量"""
        orders = self.exchange_client.fetch_open_orders()

        # 初始化计数器
        buy_long_orders = 0.0
        sell_long_orders = 0.0
        buy_short_orders = 0.0
        sell_short_orders = 0.0

        for order in orders:
            orig_quantity = abs(float(order.get('info', {}).get('origQty', 0)))
            side = order.get('side')
            position_side = order.get('info', {}).get('positionSide')

            if side == 'buy' and position_side == 'LONG':
                buy_long_orders += orig_quantity
            elif side == 'sell' and position_side == 'LONG':
                sell_long_orders += orig_quantity
            elif side == 'buy' and position_side == 'SHORT':
                buy_short_orders += orig_quantity
            elif side == 'sell' and position_side == 'SHORT':
                sell_short_orders += orig_quantity

        # 更新实例变量
        self.buy_long_orders = buy_long_orders
        self.sell_long_orders = sell_long_orders
        self.buy_short_orders = buy_short_orders
        self.sell_short_orders = sell_short_orders

    async def handle_order_update(self, order):
        """处理订单更新"""
        side = order.get("S")
        position_side = order.get("ps")
        status = order.get("X")
        quantity = float(order.get("q", 0))
        filled = float(order.get("z", 0))
        remaining = quantity - filled

        if status == "NEW":
            if side == "BUY":
                if position_side == "LONG":
                    self.buy_long_orders += remaining
                elif position_side == "SHORT":
                    self.buy_short_orders += remaining
            elif side == "SELL":
                if position_side == "LONG":
                    self.sell_long_orders += remaining
                elif position_side == "SHORT":
                    self.sell_short_orders += remaining
                    
        elif status == "FILLED":
            if side == "BUY":
                if position_side == "LONG":
                    self.long_position += filled
                    self.buy_long_orders = max(0.0, self.buy_long_orders - filled)
                elif position_side == "SHORT":
                    self.short_position = max(0.0, self.short_position - filled)
                    self.buy_short_orders = max(0.0, self.buy_short_orders - filled)
            elif side == "SELL":
                if position_side == "LONG":
                    self.long_position = max(0.0, self.long_position - filled)
                    self.sell_long_orders = max(0.0, self.sell_long_orders - filled)
                elif position_side == "SHORT":
                    self.short_position += filled
                    self.sell_short_orders = max(0.0, self.sell_short_orders - filled)
                    
        elif status == "CANCELED":
            if side == "BUY":
                if position_side == "LONG":
                    self.buy_long_orders = max(0.0, self.buy_long_orders - quantity)
                elif position_side == "SHORT":
                    self.buy_short_orders = max(0.0, self.buy_short_orders - quantity)
            elif side == "SELL":
                if position_side == "LONG":
                    self.sell_long_orders = max(0.0, self.sell_long_orders - quantity)
                elif position_side == "SHORT":
                    self.sell_short_orders = max(0.0, self.sell_short_orders - quantity)

    def get_base_quantity(self, position, side):
        """获取基础交易数量（解耦后）"""
        if side == 'long':
            if position > POSITION_LIMIT:
                return INITIAL_QUANTITY * 2
            else:
                return INITIAL_QUANTITY
        elif side == 'short':
            if position > POSITION_LIMIT:
                return INITIAL_QUANTITY * 2
            else:
                return INITIAL_QUANTITY

    def get_hedge_adjustment_quantity(self, side):
        """获取对冲调整数量（独立的对冲逻辑）"""
        if side == 'long' and self.short_position >= POSITION_THRESHOLD:
            return INITIAL_QUANTITY * 2
        elif side == 'short' and self.long_position >= POSITION_THRESHOLD:
            return INITIAL_QUANTITY * 2
        else:
            return INITIAL_QUANTITY

    def get_final_quantity(self, position, side):
        """获取最终交易数量（组合逻辑）"""
        base_qty = self.get_base_quantity(position, side)
        hedge_qty = self.get_hedge_adjustment_quantity(side)

        # 取较大值作为最终数量
        final_qty = max(base_qty, hedge_qty)

        if side == 'long':
            self.long_initial_quantity = final_qty
        elif side == 'short':
            self.short_initial_quantity = final_qty

        return final_qty

    def get_take_profit_quantity(self, position, side):
        """调整止盈单的交易数量（重构后的方法）"""
        return self.get_final_quantity(position, side)

    def update_mid_price(self, side, price):
        """更新中间价（修复价格精度问题）"""
        if side == 'long':
            self.mid_price_long = price
            self.upper_price_long = round(self.mid_price_long * (1 + GRID_SPACING),
                                        self.exchange_client.price_precision)
            self.lower_price_long = round(self.mid_price_long * (1 - GRID_SPACING),
                                        self.exchange_client.price_precision)
            print("更新 long 中间价")
        elif side == 'short':
            self.mid_price_short = price
            self.upper_price_short = round(self.mid_price_short * (1 + GRID_SPACING),
                                         self.exchange_client.price_precision)
            self.lower_price_short = round(self.mid_price_short * (1 - GRID_SPACING),
                                         self.exchange_client.price_precision)
            print("更新 short 中间价")

    def cancel_orders_for_side(self, position_side):
        """撤销某个方向的所有挂单"""
        orders = self.exchange_client.fetch_open_orders()

        if len(orders) == 0:
            logger.info("没有找到挂单")
        else:
            try:
                for order in orders:
                    side = order.get('side')
                    reduce_only = order.get('reduceOnly', False)
                    position_side_order = order.get('info', {}).get('positionSide', 'BOTH')

                    if position_side == 'long':
                        if (not reduce_only and side == 'buy' and position_side_order == 'LONG') or \
                           (reduce_only and side == 'sell' and position_side_order == 'LONG'):
                            self.exchange_client.cancel_order(order['id'])
                    elif position_side == 'short':
                        if (not reduce_only and side == 'sell' and position_side_order == 'SHORT') or \
                           (reduce_only and side == 'buy' and position_side_order == 'SHORT'):
                            self.exchange_client.cancel_order(order['id'])
            except ccxt.OrderNotFound as e:
                logger.warning(f"订单不存在，无需撤销: {e}")
                self.check_orders_status()
            except Exception as e:
                logger.error(f"撤单失败: {e}")

    def place_take_profit_order(self, side, price, quantity):
        """挂止盈单"""
        # 检查是否已有相同价格的挂单
        orders = self.exchange_client.fetch_open_orders()
        for order in orders:
            if (order['info'].get('positionSide') == side.upper() and
                float(order['price']) == price and
                order['side'] == ('sell' if side == 'long' else 'buy')):
                logger.info(f"已存在相同价格的 {side} 止盈单，跳过挂单")
                return

        try:
            # 检查持仓
            if side == 'long' and self.long_position <= 0:
                logger.warning("没有多头持仓，跳过挂出多头止盈单")
                return
            elif side == 'short' and self.short_position <= 0:
                logger.warning("没有空头持仓，跳过挂出空头止盈单")
                return

            # 修正价格和数量精度
            price = round(price, self.exchange_client.price_precision)
            quantity = round(quantity, self.exchange_client.amount_precision)
            quantity = max(quantity, self.exchange_client.min_order_amount)

            if side == 'long':
                order = self.exchange_client.place_order(
                    'sell', price, quantity, is_reduce_only=True, position_side='LONG'
                )
                logger.info(f"成功挂 long 止盈单: 卖出 {quantity} @ {price}")
            elif side == 'short':
                order = self.exchange_client.place_order(
                    'buy', price, quantity, is_reduce_only=True, position_side='SHORT'
                )
                logger.info(f"成功挂 short 止盈单: 买入 {quantity} @ {price}")
                
        except Exception as e:
            logger.error(f"挂止盈单失败: {e}")

    def check_and_reduce_positions(self):
        """检查持仓并减少库存风险（改进的动态平仓）"""
        local_position_threshold = POSITION_THRESHOLD * 0.8

        if (self.long_position >= local_position_threshold and
            self.short_position >= local_position_threshold):
            logger.info(f"多头和空头持仓均超过阈值 {local_position_threshold}，开始双向平仓，减少库存风险")

            # 动态计算平仓数量，基于实际持仓
            long_reduce_qty = min(self.long_position * 0.2, POSITION_THRESHOLD * 0.1)
            short_reduce_qty = min(self.short_position * 0.2, POSITION_THRESHOLD * 0.1)

            if self.long_position > 0:
                self.exchange_client.place_order(
                    'sell', self.best_ask_price, long_reduce_qty,
                    is_reduce_only=True, position_side='long', order_type='market'
                )
                logger.info(f"市价平仓多头 {long_reduce_qty} 个")

            if self.short_position > 0:
                self.exchange_client.place_order(
                    'buy', self.best_bid_price, short_reduce_qty,
                    is_reduce_only=True, position_side='short', order_type='market'
                )
                logger.info(f"市价平仓空头 {short_reduce_qty} 个")

    async def initialize_long_orders(self):
        """初始化多头订单"""
        current_time = time.time()
        if current_time - self.last_long_order_time < ORDER_FIRST_TIME:
            logger.info(f"距离上次多头挂单时间不足 {ORDER_FIRST_TIME} 秒，跳过本次挂单")
            return

        self.cancel_orders_for_side('long')
        self.exchange_client.place_order('buy', self.best_bid_price, INITIAL_QUANTITY, False, 'long')
        logger.info(f"挂出多头开仓单: 买入 @ {self.latest_price}")

        self.last_long_order_time = time.time()
        logger.info("初始化多头挂单完成")

    async def initialize_short_orders(self):
        """初始化空头订单"""
        current_time = time.time()
        if current_time - self.last_short_order_time < ORDER_FIRST_TIME:
            print(f"距离上次空头挂单时间不足 {ORDER_FIRST_TIME} 秒，跳过本次挂单")
            return

        self.cancel_orders_for_side('short')
        self.exchange_client.place_order('sell', self.best_ask_price, INITIAL_QUANTITY, False, 'short')
        logger.info(f"挂出空头开仓单: 卖出 @ {self.latest_price}")

        self.last_short_order_time = time.time()
        logger.info("初始化空头挂单完成")

    async def initialize_hedge_orders(self):
        """对冲模式：同时初始化多头和空头订单"""
        current_time = time.time()

        # 检查是否可以进行对冲初始化
        long_can_init = (current_time - self.last_long_order_time >= ORDER_FIRST_TIME)
        short_can_init = (current_time - self.last_short_order_time >= ORDER_FIRST_TIME)

        if not (long_can_init and short_can_init):
            logger.info("对冲初始化条件不满足，等待冷却时间")
            return False

        logger.info("🔄 开始对冲初始化：同时挂出多头和空头开仓单")

        try:
            # 同时撤销双向订单
            self.cancel_orders_for_side('long')
            self.cancel_orders_for_side('short')

            # 短暂延迟确保撤单完成
            await asyncio.sleep(self.hedge_init_delay)

            # 同时挂出多头和空头开仓单
            long_order = self.exchange_client.place_order('buy', self.best_bid_price, INITIAL_QUANTITY, False, 'long')
            short_order = self.exchange_client.place_order('sell', self.best_ask_price, INITIAL_QUANTITY, False, 'short')

            # 更新时间戳
            current_time = time.time()
            self.last_long_order_time = current_time
            self.last_short_order_time = current_time

            if long_order and short_order:
                logger.info("✅ 对冲初始化成功：多头和空头开仓单已同时挂出")
                logger.info(f"   多头开仓: 买入 @ {self.best_bid_price}")
                logger.info(f"   空头开仓: 卖出 @ {self.best_ask_price}")
                return True
            else:
                logger.warning("⚠️ 对冲初始化部分失败：部分订单未成功挂出")
                return False

        except Exception as e:
            logger.error(f"❌ 对冲初始化失败: {e}")
            return False

    async def place_long_orders(self, latest_price):
        """挂多头订单（修复止盈价格计算错误）"""
        try:
            self.get_take_profit_quantity(self.long_position, 'long')
            if self.long_position > 0:
                if self.long_position > POSITION_THRESHOLD:
                    print(f"持仓{self.long_position}超过极限阈值 {POSITION_THRESHOLD}，long装死")
                    if self.sell_long_orders <= 0:
                        # 修复：避免除零错误，使用合理的止盈价格
                        if self.short_position > 0:
                            ratio = min(self.long_position / self.short_position, 10)  # 限制最大比例
                            take_profit_price = self.latest_price * (1 + 0.01 * ratio)
                        else:
                            take_profit_price = self.latest_price * 1.05  # 默认5%止盈

                        take_profit_price = round(take_profit_price, self.exchange_client.price_precision)
                        self.place_take_profit_order('long', take_profit_price, self.long_initial_quantity)
                else:
                    self.update_mid_price('long', latest_price)
                    self.cancel_orders_for_side('long')
                    self.place_take_profit_order('long', self.upper_price_long, self.long_initial_quantity)
                    self.exchange_client.place_order('buy', self.lower_price_long, self.long_initial_quantity, False, 'long')
                    logger.info("挂多头止盈，挂多头补仓")
        except Exception as e:
            logger.error(f"挂多头订单失败: {e}")

    async def place_short_orders(self, latest_price):
        """挂空头订单（修复止盈价格计算错误）"""
        try:
            self.get_take_profit_quantity(self.short_position, 'short')
            if self.short_position > 0:
                if self.short_position > POSITION_THRESHOLD:
                    print(f"持仓{self.short_position}超过极限阈值 {POSITION_THRESHOLD}，short 装死")
                    if self.buy_short_orders <= 0:
                        # 修复：避免除零错误，使用合理的止盈价格
                        if self.long_position > 0:
                            ratio = min(self.short_position / self.long_position, 10)  # 限制最大比例
                            take_profit_price = self.latest_price * (1 - 0.01 * ratio)  # 空头止盈应该是低于当前价
                        else:
                            take_profit_price = self.latest_price * 0.95  # 默认5%止盈

                        take_profit_price = round(take_profit_price, self.exchange_client.price_precision)
                        logger.info("发现空头止盈单缺失。。需要补止盈单")
                        self.place_take_profit_order('short', take_profit_price, self.short_initial_quantity)
                else:
                    self.update_mid_price('short', latest_price)
                    self.cancel_orders_for_side('short')
                    self.place_take_profit_order('short', self.lower_price_short, self.short_initial_quantity)
                    self.exchange_client.place_order('sell', self.upper_price_short, self.short_initial_quantity, False, 'short')
                    logger.info("挂空头止盈，挂空头补仓")
        except Exception as e:
            logger.error(f"挂空头订单失败: {e}")

    async def adjust_grid_strategy(self):
        """根据最新价格和持仓调整网格策略（修复高频API调用问题）"""
        # 检查双向仓位库存，如果同时达到，就统一部分平仓减少库存风险
        self.check_and_reduce_positions()

        # 对冲初始化模式：同时检查多头和空头是否需要初始化
        if self.hedge_initialization_enabled and self.long_position == 0 and self.short_position == 0:
            logger.info("🎯 检测到双向无持仓，启动对冲初始化模式")
            hedge_success = await self.initialize_hedge_orders()
            if hedge_success:
                logger.info("✅ 对冲初始化完成，跳过单独初始化")
                return
            else:
                logger.warning("⚠️ 对冲初始化失败，回退到单独初始化模式")

        # 检测多头持仓
        if self.long_position == 0:
            print(f"检测到没有多头持仓{self.long_position}，初始化多头挂单@ ticker")
            await self.initialize_long_orders()
        else:
            orders_valid = (not (0 < self.buy_long_orders <= self.long_initial_quantity) or
                           not (0 < self.sell_long_orders <= self.long_initial_quantity))
            if orders_valid:
                if self.long_position < POSITION_THRESHOLD:
                    # 添加冷却时间检查，避免高频API调用
                    if self.should_sync_orders():
                        print('如果 long 持仓没到阈值，同步后再次确认！')
                        self.check_orders_status()
                        self.last_orders_sync_time = time.time()
                        # 重新检查orders_valid状态
                        orders_valid = (not (0 < self.buy_long_orders <= self.long_initial_quantity) or
                                       not (0 < self.sell_long_orders <= self.long_initial_quantity))

                    if orders_valid:
                        await self.place_long_orders(self.latest_price)
                else:
                    await self.place_long_orders(self.latest_price)

        # 检测空头持仓
        if self.short_position == 0:
            await self.initialize_short_orders()
        else:
            orders_valid = (not (0 < self.sell_short_orders <= self.short_initial_quantity) or
                           not (0 < self.buy_short_orders <= self.short_initial_quantity))
            if orders_valid:
                if self.short_position < POSITION_THRESHOLD:
                    # 添加冷却时间检查，避免高频API调用
                    if self.should_sync_orders():
                        print('如果 short 持仓没到阈值，同步后再次确认！')
                        self.check_orders_status()
                        self.last_orders_sync_time = time.time()
                        # 重新检查orders_valid状态
                        orders_valid = (not (0 < self.sell_short_orders <= self.short_initial_quantity) or
                                       not (0 < self.buy_short_orders <= self.short_initial_quantity))

                    if orders_valid:
                        await self.place_short_orders(self.latest_price)
                else:
                    await self.place_short_orders(self.latest_price)
