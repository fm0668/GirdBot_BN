import asyncio
import time
import logging
import ccxt
from typing import Set, Dict, Any
from config import (
    GRID_SPACING, INITIAL_QUANTITY, ORDER_FIRST_TIME, SYNC_TIME,
    ORDERS_SYNC_COOLDOWN, FAST_SYNC_COOLDOWN,
    PRICE_CHANGE_THRESHOLD, FAST_MARKET_WINDOW,
    API_WEIGHT_LIMIT_PER_MINUTE, FETCH_ORDERS_WEIGHT, SAFETY_MARGIN,
    ENABLE_HEDGE_INITIALIZATION, HEDGE_INIT_DELAY,
    # 动态数量配置 - 已禁用，使用固定数量
    ENABLE_DYNAMIC_QUANTITY
    # ACCOUNT_USAGE_RATIO, SINGLE_ORDER_RATIO,
    # MIN_ORDER_VALUE, MAX_ORDER_VALUE, QUANTITY_CACHE_DURATION,
    # 杠杆优化配置 - 已禁用
    # LEVERAGE_BASED_CALCULATION, LEVERAGE_ORDER_RATIO, USE_TOTAL_EQUITY
)
from risk_manager import RiskManager
# from quantity_calculator import QuantityCalculator  # 已禁用动态数量计算

logger = logging.getLogger(__name__)


class GridStrategy:
    """网格交易策略核心逻辑"""
    
    def __init__(self, exchange_client):
        self.exchange_client = exchange_client
        self.lock = asyncio.Lock()

        # 风险管理器
        self.risk_manager = RiskManager(exchange_client, 10)  # 默认10倍杠杆

        # ==================== 事件驱动架构 ====================
        self.pending_updates: Set[str] = set()  # 待处理的事件队列
        self.update_lock = asyncio.Lock()  # 事件队列锁
        self.running = True  # 主循环运行标志

        # 事件处理时间记录
        self.last_update_times: Dict[str, float] = {
            'rebalance_immediately': 0,
            'check_price_drift': 0,
            'long_order_adjustment': 0,  # 新增：多头订单调整时间
            'short_order_adjustment': 0,  # 新增：空头订单调整时间
            'any': 0
        }

        # 分层决策相关
        self.last_grid_update_price = 0  # 上次网格更新时的价格
        self.last_long_price = 0  # 上次多头价格
        self.last_short_price = 0  # 上次空头价格

        # 配置参数
        self.GRID_UPDATE_THRESHOLD = GRID_SPACING * 2.0  # 价格变化阈值 (0.2%)
        self.MIN_UPDATE_INTERVAL = 10  # 最小更新间隔 (秒)
        self.MIN_ORDER_ADJUSTMENT_INTERVAL = 15  # 订单调整最小间隔 (秒) - 从30秒缩短为15秒
        self.QUANTITY_THRESHOLD_RATIO = 0.7  # 订单数量阈值比例

        # 动态数量计算器 - 已禁用，使用固定数量 INITIAL_QUANTITY
        # self.quantity_calculator = QuantityCalculator(
        #     exchange_client=exchange_client,
        #     risk_manager=self.risk_manager,
        #     account_usage_ratio=ACCOUNT_USAGE_RATIO,
        #     single_order_ratio=SINGLE_ORDER_RATIO,
        #     min_order_value=MIN_ORDER_VALUE,
        #     max_order_value=MAX_ORDER_VALUE
        # )

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
        self.hedge_init_completed = False  # 标记对冲初始化是否已完成
        self.last_hedge_init_time = 0      # 上次对冲初始化时间

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
        # 检查是否需要重置对冲初始化状态
        if (self.hedge_init_completed and
            (long_position == 0 and short_position == 0) and
            (self.long_position != 0 or self.short_position != 0)):
            # 从有持仓变为无持仓，重置对冲初始化状态
            self.hedge_init_completed = False
            logger.info("🔄 持仓已清空，重置对冲初始化状态")

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
        """检查当前所有挂单的状态，并更新多头和空头的挂单数量（改进版）"""
        orders = self.exchange_client.fetch_open_orders()

        # 使用字典计数，避免浮点数累加误差
        order_counts = {
            'buy_long': 0,
            'sell_long': 0,
            'buy_short': 0,
            'sell_short': 0
        }

        # 记录有效订单的详细信息
        valid_orders = []

        for order in orders:
            # 使用剩余数量而非原始数量，避免部分成交的影响
            remaining_qty = float(order.get('remaining', 0))
            if remaining_qty <= 0:
                continue  # 跳过已完全成交的订单

            side = order.get('side')
            position_side = order.get('info', {}).get('positionSide')
            order_price = float(order.get('price', 0))

            # 记录有效订单
            valid_orders.append({
                'side': side,
                'position_side': position_side,
                'remaining_qty': remaining_qty,
                'price': order_price
            })

            # 计数有效订单
            if side == 'buy' and position_side == 'LONG':
                order_counts['buy_long'] += 1
            elif side == 'sell' and position_side == 'LONG':
                order_counts['sell_long'] += 1
            elif side == 'buy' and position_side == 'SHORT':
                order_counts['buy_short'] += 1
            elif side == 'sell' and position_side == 'SHORT':
                order_counts['sell_short'] += 1

        # 更新实例变量：订单数量 = 订单个数 × 固定数量
        self.buy_long_orders = order_counts['buy_long'] * INITIAL_QUANTITY
        self.sell_long_orders = order_counts['sell_long'] * INITIAL_QUANTITY
        self.buy_short_orders = order_counts['buy_short'] * INITIAL_QUANTITY
        self.sell_short_orders = order_counts['sell_short'] * INITIAL_QUANTITY

        # 记录有效订单信息供调试使用
        self.valid_orders = valid_orders

        logger.debug(f"订单状态更新: 买多{order_counts['buy_long']}个, 卖多{order_counts['sell_long']}个, "
                    f"卖空{order_counts['sell_short']}个, 买空{order_counts['buy_short']}个")

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
        """获取基础交易数量（已简化为固定数量）"""
        # 直接使用固定数量，不再使用动态计算
        return INITIAL_QUANTITY
        # if ENABLE_DYNAMIC_QUANTITY and self.latest_price > 0:
        #     # 使用动态数量计算
        #     return self.quantity_calculator.get_quantity_for_grid_order(
        #         self.latest_price, position, side
        #     )
        # else:
        #     # 使用固定数量
        #     return INITIAL_QUANTITY

    def get_hedge_adjustment_quantity(self, side):
        """获取对冲调整数量（已简化为固定数量）"""
        # 直接使用固定数量，不再使用动态计算
        return INITIAL_QUANTITY
        # if ENABLE_DYNAMIC_QUANTITY and self.latest_price > 0:
        #     # 对冲初始化使用更保守的数量
        #     return self.quantity_calculator.get_quantity_for_hedge_init(self.latest_price)
        # else:
        #     # 使用固定数量
        #     return INITIAL_QUANTITY

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

    # 删除check_and_reduce_positions函数，因为它依赖于已删除的POSITION_THRESHOLD
    # 如果需要风控，可以在其他地方实现不依赖固定阈值的逻辑

    async def initialize_long_orders(self):
        """初始化多头订单"""
        current_time = time.time()
        if current_time - self.last_long_order_time < ORDER_FIRST_TIME:
            # 降低日志级别，避免冗余输出
            logger.debug(f"距离上次多头挂单时间不足 {ORDER_FIRST_TIME} 秒，跳过本次挂单")
            return

        self.cancel_orders_for_side('long')

        # 使用固定数量，不再使用动态计算
        quantity = INITIAL_QUANTITY
        # if ENABLE_DYNAMIC_QUANTITY:
        #     quantity = self.quantity_calculator.get_quantity_for_hedge_init(self.latest_price)
        # else:
        #     quantity = INITIAL_QUANTITY

        self.exchange_client.place_order('buy', self.best_bid_price, quantity, False, 'long')
        logger.info(f"挂出多头开仓单: 买入 {quantity} 张 @ {self.latest_price}")

        self.last_long_order_time = time.time()
        logger.info("初始化多头挂单完成")

    async def initialize_short_orders(self):
        """初始化空头订单"""
        current_time = time.time()
        if current_time - self.last_short_order_time < ORDER_FIRST_TIME:
            # 降低日志级别，避免冗余输出
            logger.debug(f"距离上次空头挂单时间不足 {ORDER_FIRST_TIME} 秒，跳过本次挂单")
            return

        self.cancel_orders_for_side('short')

        # 使用固定数量，不再使用动态计算
        quantity = INITIAL_QUANTITY
        # if ENABLE_DYNAMIC_QUANTITY:
        #     quantity = self.quantity_calculator.get_quantity_for_hedge_init(self.latest_price)
        # else:
        #     quantity = INITIAL_QUANTITY

        self.exchange_client.place_order('sell', self.best_ask_price, quantity, False, 'short')
        logger.info(f"挂出空头开仓单: 卖出 {quantity} 张 @ {self.latest_price}")

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

            # 使用固定数量，不再使用动态计算
            hedge_quantity = INITIAL_QUANTITY
            # if ENABLE_DYNAMIC_QUANTITY:
            #     hedge_quantity = self.quantity_calculator.get_quantity_for_hedge_init(self.latest_price)
            # else:
            #     hedge_quantity = INITIAL_QUANTITY

            # 同时挂出多头和空头开仓单
            long_order = self.exchange_client.place_order('buy', self.best_bid_price, hedge_quantity, False, 'long')
            short_order = self.exchange_client.place_order('sell', self.best_ask_price, hedge_quantity, False, 'short')

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
        """挂多头订单（支持有持仓和无持仓两种情况）"""
        try:
            # 先撤销现有订单
            self.cancel_orders_for_side('long')

            if self.long_position > 0:
                # 有持仓：挂止盈单 + 补仓单
                self.get_take_profit_quantity(self.long_position, 'long')
                base_quantity = self.get_final_quantity(self.long_position, 'long')

                # 确保订单金额满足最小要求（5 USDC）
                min_notional = 5.0
                min_quantity = min_notional / latest_price * 1.1  # 增加10%缓冲
                safe_quantity = max(base_quantity, min_quantity)

                # 执行正常网格策略
                self.update_mid_price('long', latest_price)
                self.place_take_profit_order('long', self.upper_price_long, safe_quantity)
                self.exchange_client.place_order('buy', self.lower_price_long, safe_quantity, False, 'long')
                logger.info(f"挂多头订单（有持仓），数量: {safe_quantity}")
            else:
                # 无持仓：挂开仓单，为重新建立持仓做准备
                base_quantity = INITIAL_QUANTITY

                # 确保订单金额满足最小要求
                min_notional = 5.0
                min_quantity = min_notional / latest_price * 1.1
                safe_quantity = max(base_quantity, min_quantity)

                # 挂多头开仓单
                buy_price = latest_price * (1 - GRID_SPACING)
                self.exchange_client.place_order('buy', buy_price, safe_quantity, False, 'long')
                logger.info(f"挂多头开仓单（无持仓），数量: {safe_quantity} @ {buy_price:.5f}")

        except Exception as e:
            logger.error(f"挂多头订单失败: {e}")

    async def place_short_orders(self, latest_price):
        """挂空头订单（支持有持仓和无持仓两种情况）"""
        try:
            # 先撤销现有订单
            self.cancel_orders_for_side('short')

            if self.short_position > 0:
                # 有持仓：挂止盈单 + 补仓单
                self.get_take_profit_quantity(self.short_position, 'short')
                base_quantity = self.get_final_quantity(self.short_position, 'short')

                # 确保订单金额满足最小要求（5 USDC）
                min_notional = 5.0
                min_quantity = min_notional / latest_price * 1.1  # 增加10%缓冲
                safe_quantity = max(base_quantity, min_quantity)

                # 执行正常网格策略
                self.update_mid_price('short', latest_price)
                self.place_take_profit_order('short', self.lower_price_short, safe_quantity)
                self.exchange_client.place_order('sell', self.upper_price_short, safe_quantity, False, 'short')
                logger.info(f"挂空头订单（有持仓），数量: {safe_quantity}")
            else:
                # 无持仓：挂开仓单，为重新建立持仓做准备
                base_quantity = INITIAL_QUANTITY

                # 确保订单金额满足最小要求
                min_notional = 5.0
                min_quantity = min_notional / latest_price * 1.1
                safe_quantity = max(base_quantity, min_quantity)

                # 挂空头开仓单
                sell_price = latest_price * (1 + GRID_SPACING)
                self.exchange_client.place_order('sell', sell_price, safe_quantity, False, 'short')
                logger.info(f"挂空头开仓单（无持仓），数量: {safe_quantity} @ {sell_price:.5f}")

        except Exception as e:
            logger.error(f"挂空头订单失败: {e}")

    def log_risk_metrics(self):
        """记录风险指标（简化版）"""
        try:
            # 简化的风险监控，只记录基本持仓信息
            logger.info(f"💰 持仓状态 - 多头: {self.long_position} 张, "
                       f"空头: {self.short_position} 张, "
                       f"当前价格: {self.latest_price:.5f}")
        except Exception as e:
            logger.debug(f"获取风险指标失败: {e}")

    async def adjust_grid_strategy(self):
        """根据最新价格和持仓调整网格策略（集成真实风控决策）"""

        # ==================== 第一步：定期更新风控数据 ====================
        # 风险检查是最高优先级的，必须在做任何开仓决策之前进行
        if self.risk_manager.should_update_account_info():
            self.risk_manager.update_account_info()

        if self.risk_manager.should_update_position_info():
            self.risk_manager.update_position_info(self.exchange_client.ccxt_symbol)

        # ==================== 第二步：多头仓位风险审查与执行 ====================
        if self.long_position > 0:
            # 计算多头仓位的名义价值
            long_notional_value = self.long_position * self.latest_price

            # 获取风控决策
            risk_decision = self.risk_manager.should_reduce_position(
                self.exchange_client.ccxt_symbol, 'long', long_notional_value
            )

            if risk_decision['should_reduce']:
                # 打印明确的警告日志，用于事后复盘
                logger.warning(f"🚨 多头风控触发: {risk_decision['reason']}")
                logger.warning(f"   风险等级: {risk_decision['urgency']}")
                logger.warning(f"   建议减仓比例: {risk_decision['suggested_ratio']:.1%}")

                # 判断紧急程度
                if risk_decision['urgency'] in ['HIGH', 'MEDIUM']:
                    # 计算要减仓的数量
                    reduce_qty = self.long_position * risk_decision['suggested_ratio']
                    reduce_qty = round(reduce_qty, self.exchange_client.amount_precision)
                    reduce_qty = max(reduce_qty, self.exchange_client.min_order_amount)

                    logger.warning(f"🔥 执行紧急减仓: 卖出 {reduce_qty} 张多头仓位")

                    # 下达市价减仓订单
                    order = self.exchange_client.place_order(
                        'sell', None, reduce_qty,
                        is_reduce_only=True, position_side='LONG', order_type='market'
                    )

                    if order:
                        logger.warning(f"✅ 多头减仓订单提交成功: {order.get('id', 'N/A')}")
                    else:
                        logger.error(f"❌ 多头减仓订单提交失败")

                    # 执行减仓后立即返回，跳过本次网格逻辑
                    return

        # ==================== 第三步：空头仓位风险审查与执行 ====================
        if self.short_position > 0:
            # 计算空头仓位的名义价值
            short_notional_value = self.short_position * self.latest_price

            # 获取风控决策
            risk_decision = self.risk_manager.should_reduce_position(
                self.exchange_client.ccxt_symbol, 'short', short_notional_value
            )

            if risk_decision['should_reduce']:
                # 打印明确的警告日志，用于事后复盘
                logger.warning(f"🚨 空头风控触发: {risk_decision['reason']}")
                logger.warning(f"   风险等级: {risk_decision['urgency']}")
                logger.warning(f"   建议减仓比例: {risk_decision['suggested_ratio']:.1%}")

                # 判断紧急程度
                if risk_decision['urgency'] in ['HIGH', 'MEDIUM']:
                    # 计算要减仓的数量
                    reduce_qty = self.short_position * risk_decision['suggested_ratio']
                    reduce_qty = round(reduce_qty, self.exchange_client.amount_precision)
                    reduce_qty = max(reduce_qty, self.exchange_client.min_order_amount)

                    logger.warning(f"🔥 执行紧急减仓: 买入 {reduce_qty} 张空头仓位")

                    # 下达市价减仓订单
                    order = self.exchange_client.place_order(
                        'buy', None, reduce_qty,
                        is_reduce_only=True, position_side='SHORT', order_type='market'
                    )

                    if order:
                        logger.warning(f"✅ 空头减仓订单提交成功: {order.get('id', 'N/A')}")
                    else:
                        logger.error(f"❌ 空头减仓订单提交失败")

                    # 执行减仓后立即返回，跳过本次网格逻辑
                    return

        # ==================== 第四步：执行常规网格逻辑 ====================
        # 如果代码能执行到这里，说明风险审查通过，一切正常
        # 此时，才继续执行后续的对冲初始化、挂多头单、挂空头单等常规的网格交易逻辑

        # 对冲初始化模式：同时检查多头和空头是否需要初始化
        if (self.hedge_initialization_enabled and
            self.long_position == 0 and self.short_position == 0 and
            not self.hedge_init_completed):

            current_time = time.time()
            # 避免频繁尝试对冲初始化
            if current_time - self.last_hedge_init_time >= 5:  # 5秒间隔
                logger.info("🎯 检测到双向无持仓，启动对冲初始化模式")
                hedge_success = await self.initialize_hedge_orders()
                self.last_hedge_init_time = current_time

                if hedge_success:
                    logger.info("✅ 对冲初始化完成，跳过单独初始化")
                    self.hedge_init_completed = True  # 标记已完成
                    return
                else:
                    logger.warning("⚠️ 对冲初始化失败，回退到单独初始化模式")
            else:
                # 避免频繁日志输出
                return

        # 检测多头持仓
        if self.long_position == 0:
            # 如果刚完成对冲初始化，给一些时间让订单成交
            current_time = time.time()
            if self.hedge_init_completed and current_time - self.last_hedge_init_time < 15:
                # 对冲初始化后15秒内，避免冗余的单独初始化尝试
                return

            logger.debug(f"检测到没有多头持仓{self.long_position}，初始化多头挂单@ ticker")
            await self.initialize_long_orders()
        else:
            orders_valid = (not (0 < self.buy_long_orders <= self.long_initial_quantity) or
                           not (0 < self.sell_long_orders <= self.long_initial_quantity))
            if orders_valid:
                # 删除POSITION_THRESHOLD检查，简化逻辑，添加冷却时间检查避免高频API调用
                if self.should_sync_orders():
                    print('如果 long 持仓没到阈值，同步后再次确认！')
                    self.check_orders_status()
                    self.last_orders_sync_time = time.time()
                    # 重新检查orders_valid状态
                    orders_valid = (not (0 < self.buy_long_orders <= self.long_initial_quantity) or
                                   not (0 < self.sell_long_orders <= self.long_initial_quantity))

                if orders_valid:
                    await self.place_long_orders(self.latest_price)

        # 检测空头持仓
        if self.short_position == 0:
            # 如果刚完成对冲初始化，给一些时间让订单成交
            current_time = time.time()
            if self.hedge_init_completed and current_time - self.last_hedge_init_time < 15:
                # 对冲初始化后15秒内，避免冗余的单独初始化尝试
                return

            await self.initialize_short_orders()
        else:
            orders_valid = (not (0 < self.sell_short_orders <= self.short_initial_quantity) or
                           not (0 < self.buy_short_orders <= self.short_initial_quantity))
            if orders_valid:
                # 删除POSITION_THRESHOLD检查，简化逻辑，添加冷却时间检查避免高频API调用
                if self.should_sync_orders():
                    print('如果 short 持仓没到阈值，同步后再次确认！')
                    self.check_orders_status()
                    self.last_orders_sync_time = time.time()
                    # 重新检查orders_valid状态
                    orders_valid = (not (0 < self.sell_short_orders <= self.short_initial_quantity) or
                                   not (0 < self.buy_short_orders <= self.short_initial_quantity))

                if orders_valid:
                    await self.place_short_orders(self.latest_price)

    # ==================== 事件驱动方法 ====================

    async def add_pending_update(self, update_type: str):
        """线程安全地添加待处理事件"""
        async with self.update_lock:
            self.pending_updates.add(update_type)
            logger.debug(f"添加事件: {update_type}, 当前队列: {self.pending_updates}")

    async def on_trade_event(self, trade_data: Dict[str, Any]):
        """处理成交事件 - 高优先级"""
        logger.info(f"收到成交事件: {trade_data}")
        await self.add_pending_update('rebalance_immediately')

    async def on_price_update(self, price: float):
        """处理价格更新事件 - 低优先级"""
        self.latest_price = price
        await self.add_pending_update('check_price_drift')

    async def on_order_update(self, order_data: Dict[str, Any]):
        """处理订单更新事件"""
        logger.debug(f"收到订单更新: {order_data}")
        # 订单更新可能影响持仓，触发重新平衡
        await self.add_pending_update('rebalance_immediately')

    # ==================== 分层决策逻辑 ====================

    def has_price_drift_exceeded_threshold(self) -> bool:
        """第一层检查：价格变化是否超过阈值"""
        if self.last_grid_update_price <= 0:
            self.last_grid_update_price = self.latest_price
            return True  # 首次运行，需要初始化

        # 计算价格变化比例
        price_change = abs(self.latest_price - self.last_grid_update_price) / self.last_grid_update_price

        # 检查是否超过阈值
        threshold_exceeded = price_change > self.GRID_UPDATE_THRESHOLD

        if threshold_exceeded:
            logger.info(f"价格漂移超过阈值: {price_change:.4f} > {self.GRID_UPDATE_THRESHOLD:.4f}, "
                       f"价格从 {self.last_grid_update_price:.5f} 变为 {self.latest_price:.5f}")

        return threshold_exceeded

    def need_order_update(self, side: str, current_price: float) -> bool:
        """第二层检查：智能判断是否需要更新订单（增加时间冷却和紧急检测）"""
        try:
            # 检查订单数量是否明显不足
            quantity_missing = self._check_quantity_missing(side)

            # 检查现有订单价格是否合理
            price_reasonable = self._check_order_prices_reasonable(side, current_price)

            # 紧急情况：订单完全缺失，跳过冷却时间
            if self._is_emergency_missing_orders(side):
                logger.warning(f"{side}方向订单完全缺失，紧急处理，跳过冷却时间")
                need_update = True
            else:
                # 检查时间冷却
                current_time = time.time()
                last_adjustment_key = f'{side}_order_adjustment'
                last_adjustment_time = self.last_update_times.get(last_adjustment_key, 0)

                if current_time - last_adjustment_time < self.MIN_ORDER_ADJUSTMENT_INTERVAL:
                    logger.debug(f"{side}方向订单调整冷却中，距离上次调整 {current_time - last_adjustment_time:.1f}秒")
                    return False

                # 只有数量不足或价格不合理时才需要更新
                need_update = quantity_missing or not price_reasonable

            if need_update:
                reason = []
                if quantity_missing:
                    reason.append("订单数量不足")
                if not price_reasonable:
                    reason.append("订单价格不合理")
                logger.info(f"{side}方向需要更新订单: {', '.join(reason)}")

                # 更新最后调整时间
                current_time = time.time()
                last_adjustment_key = f'{side}_order_adjustment'
                self.last_update_times[last_adjustment_key] = current_time

            return need_update

        except Exception as e:
            logger.error(f"检查订单更新需求时出错: {e}")
            return False  # 出错时保守处理，不更新

    def _check_quantity_missing(self, side: str) -> bool:
        """检查订单数量是否不足"""
        if side == 'long':
            expected_quantity = self.long_initial_quantity
            threshold = expected_quantity * self.QUANTITY_THRESHOLD_RATIO

            buy_missing = self.buy_long_orders < threshold
            sell_missing = self.sell_long_orders < threshold

            if buy_missing or sell_missing:
                logger.debug(f"多头订单数量不足: 买单{self.buy_long_orders}/{expected_quantity}, "
                           f"卖单{self.sell_long_orders}/{expected_quantity}, 阈值{threshold}")
                return True

        else:  # short
            expected_quantity = self.short_initial_quantity
            threshold = expected_quantity * self.QUANTITY_THRESHOLD_RATIO

            sell_missing = self.sell_short_orders < threshold
            buy_missing = self.buy_short_orders < threshold

            if sell_missing or buy_missing:
                logger.debug(f"空头订单数量不足: 卖单{self.sell_short_orders}/{expected_quantity}, "
                           f"买单{self.buy_short_orders}/{expected_quantity}, 阈值{threshold}")
                return True

        return False

    def _check_order_prices_reasonable(self, side: str, current_price: float) -> bool:
        """检查现有订单价格是否合理"""
        if not hasattr(self, 'valid_orders') or not self.valid_orders:
            return False  # 没有有效订单，需要重新挂单

        # 计算期望的订单价格
        expected_buy_price = current_price * (1 - GRID_SPACING)
        expected_sell_price = current_price * (1 + GRID_SPACING)

        # 价格容差（网格间距的100%）- 修复：从30%调整为100%，减少不必要的撤单
        price_tolerance = GRID_SPACING * 1.0

        has_reasonable_buy = False
        has_reasonable_sell = False

        for order in self.valid_orders:
            if order['position_side'] != side.upper():
                continue

            order_price = order['price']

            if order['side'] == 'buy':
                # 检查买单价格是否合理
                price_diff = abs(order_price - expected_buy_price) / expected_buy_price
                if price_diff <= price_tolerance:
                    has_reasonable_buy = True

            elif order['side'] == 'sell':
                # 检查卖单价格是否合理
                price_diff = abs(order_price - expected_sell_price) / expected_sell_price
                if price_diff <= price_tolerance:
                    has_reasonable_sell = True

        # 需要同时有合理的买单和卖单
        reasonable = has_reasonable_buy and has_reasonable_sell

        if not reasonable:
            logger.debug(f"{side}方向订单价格不合理: 买单合理={has_reasonable_buy}, 卖单合理={has_reasonable_sell}")

        return reasonable

    def _is_emergency_missing_orders(self, side: str) -> bool:
        """检查是否为紧急情况：订单完全缺失"""
        if side == 'long':
            # 多头有持仓但没有止盈单（卖单）
            if self.long_position > 0 and self.sell_long_orders == 0:
                logger.warning(f"紧急情况：多头有持仓 {self.long_position} 张但没有止盈单")
                return True
        else:  # short
            # 空头有持仓但没有止盈单（买单）
            if self.short_position > 0 and self.buy_short_orders == 0:
                logger.warning(f"紧急情况：空头有持仓 {self.short_position} 张但没有止盈单")
                return True

        return False

    # ==================== 主循环和事件处理 ====================

    async def main_strategy_loop(self):
        """主策略循环 - 事件驱动架构"""
        logger.info("启动事件驱动主循环")

        while self.running:
            try:
                await asyncio.sleep(1)  # 主循环频率：1秒

                # 检查是否有待处理的事件
                if not self.pending_updates:
                    continue

                # 优先处理高优先级任务：立即重新平衡
                if 'rebalance_immediately' in self.pending_updates:
                    await self._handle_immediate_rebalance()
                    continue  # 处理完高优任务，立即开始下一次循环

                # 处理低优先级任务：价格漂移检查
                if 'check_price_drift' in self.pending_updates:
                    await self._handle_price_drift_check()

            except Exception as e:
                logger.error(f"主循环异常: {e}", exc_info=True)
                await asyncio.sleep(5)  # 异常后暂停5秒

    async def _handle_immediate_rebalance(self):
        """处理立即重新平衡事件"""
        async with self.update_lock:
            self.pending_updates.discard('rebalance_immediately')

        logger.info("执行立即重新平衡...")

        try:
            # 更新持仓和订单状态
            self.check_orders_status()

            # ==================== 风控检查 ====================
            # 风险检查是最高优先级的，必须在做任何开仓决策之前进行
            await self._perform_risk_checks()

            # ==================== 初始化检查 ====================
            # 如果没有持仓，优先进行初始化开仓
            if self.long_position == 0 and self.short_position == 0:
                logger.info("立即重新平衡：检测到无持仓状态，执行初始化开仓")

                # 尝试对冲初始化
                current_time = time.time()
                if current_time - self.last_hedge_init_time >= 5:  # 5秒间隔
                    logger.info("🎯 立即重新平衡：启动对冲初始化模式")
                    hedge_success = await self.initialize_hedge_orders()
                    self.last_hedge_init_time = current_time

                    if hedge_success:
                        logger.info("✅ 立即重新平衡：对冲初始化完成")
                        self.hedge_init_completed = True
                        self.last_grid_update_price = self.latest_price
                        self.last_update_times['rebalance_immediately'] = time.time()
                        return

                # 如果对冲初始化失败，尝试单独初始化
                if self.long_position == 0:
                    logger.info("立即重新平衡：执行多头初始化开仓")
                    await self.initialize_long_orders()

                if self.short_position == 0:
                    logger.info("立即重新平衡：执行空头初始化开仓")
                    await self.initialize_short_orders()

                self.last_grid_update_price = self.latest_price
                self.last_update_times['rebalance_immediately'] = time.time()
                return

            # ==================== 持仓调整检查 ====================
            # 检查多头是否需要调整
            if self.long_position > 0:
                if self.need_order_update('long', self.latest_price):
                    logger.info("多头订单需要调整，执行重新挂单")
                    await self.place_long_orders(self.latest_price)
                    self.last_grid_update_price = self.latest_price
            elif self.long_position == 0:
                # 修复：多头持仓为0时，检查是否需要重新初始化
                logger.info("检测到多头持仓为0，尝试重新初始化多头开仓")
                await self.initialize_long_orders()

            # 检查空头是否需要调整
            if self.short_position > 0:
                if self.need_order_update('short', self.latest_price):
                    logger.info("空头订单需要调整，执行重新挂单")
                    await self.place_short_orders(self.latest_price)
                    self.last_grid_update_price = self.latest_price
            elif self.short_position == 0:
                # 修复：空头持仓为0时，检查是否需要重新初始化
                logger.info("检测到空头持仓为0，尝试重新初始化空头开仓")
                await self.initialize_short_orders()

            # 更新最后处理时间
            self.last_update_times['rebalance_immediately'] = time.time()

        except Exception as e:
            logger.error(f"立即重新平衡时出错: {e}", exc_info=True)

    async def _handle_price_drift_check(self):
        """处理价格漂移检查事件"""
        async with self.update_lock:
            self.pending_updates.discard('check_price_drift')

        # 检查处理频率限制
        current_time = time.time()
        if current_time - self.last_update_times['check_price_drift'] < self.MIN_UPDATE_INTERVAL:
            logger.debug("价格漂移检查冷却中，跳过处理")
            return

        logger.debug("执行价格漂移检查...")

        try:
            # ==================== 风控检查 ====================
            # 风险检查是最高优先级的，必须在做任何开仓决策之前进行
            await self._perform_risk_checks()

            # ==================== 初始化检查 ====================
            # 如果没有持仓，需要先进行初始化开仓
            if self.long_position == 0 and self.short_position == 0:
                logger.info("检测到无持仓状态，执行初始化开仓")

                # 尝试对冲初始化
                current_time = time.time()
                if current_time - self.last_hedge_init_time >= 5:  # 5秒间隔
                    logger.info("🎯 启动对冲初始化模式")
                    hedge_success = await self.initialize_hedge_orders()
                    self.last_hedge_init_time = current_time

                    if hedge_success:
                        logger.info("✅ 对冲初始化完成")
                        self.hedge_init_completed = True
                        self.last_grid_update_price = self.latest_price
                        self.last_update_times['check_price_drift'] = current_time
                        return

                # 如果对冲初始化失败，尝试单独初始化
                if self.long_position == 0:
                    logger.info("执行多头初始化开仓")
                    await self.initialize_long_orders()

                if self.short_position == 0:
                    logger.info("执行空头初始化开仓")
                    await self.initialize_short_orders()

                self.last_grid_update_price = self.latest_price
                self.last_update_times['check_price_drift'] = current_time
                return

            # ==================== 价格漂移检查 ====================
            # 第一层：快速价格变化检查
            if not self.has_price_drift_exceeded_threshold():
                logger.debug("价格变化未超过阈值，跳过订单调整")
                return

            # 第二层：详细订单检查
            need_long_update = False
            need_short_update = False
            need_long_init = False
            need_short_init = False

            if self.long_position > 0:
                need_long_update = self.need_order_update('long', self.latest_price)
            elif self.long_position == 0:
                need_long_init = True

            if self.short_position > 0:
                need_short_update = self.need_order_update('short', self.latest_price)
            elif self.short_position == 0:
                need_short_init = True

            # 执行必要的订单调整
            if need_long_update:
                logger.info("价格漂移触发多头订单调整")
                await self.place_long_orders(self.latest_price)
                self.last_grid_update_price = self.latest_price
            elif need_long_init:
                logger.info("价格漂移触发多头重新初始化")
                await self.initialize_long_orders()

            if need_short_update:
                logger.info("价格漂移触发空头订单调整")
                await self.place_short_orders(self.latest_price)
                self.last_grid_update_price = self.latest_price
            elif need_short_init:
                logger.info("价格漂移触发空头重新初始化")
                await self.initialize_short_orders()

            # 更新最后处理时间
            self.last_update_times['check_price_drift'] = current_time

        except Exception as e:
            logger.error(f"价格漂移检查时出错: {e}", exc_info=True)

    async def shutdown(self):
        """优雅关闭策略"""
        logger.info("开始优雅关闭策略...")
        self.running = False

        # 处理完所有待处理事件
        while self.pending_updates:
            logger.info(f"处理剩余事件: {self.pending_updates}")
            if 'rebalance_immediately' in self.pending_updates:
                await self._handle_immediate_rebalance()
            elif 'check_price_drift' in self.pending_updates:
                await self._handle_price_drift_check()
            else:
                # 清除未知事件
                async with self.update_lock:
                    self.pending_updates.clear()
                break

        logger.info("策略已优雅关闭")

    # ==================== 风控集成方法 ====================

    async def _perform_risk_checks(self):
        """执行风控检查 - 从原 adjust_grid_strategy 方法提取"""
        try:
            # 第一步：定期更新风控数据
            if self.risk_manager.should_update_account_info():
                self.risk_manager.update_account_info()

            if self.risk_manager.should_update_position_info():
                self.risk_manager.update_position_info(self.exchange_client.ccxt_symbol)

            # 第二步：多头仓位风险审查与执行
            if self.long_position > 0:
                # 计算多头仓位的名义价值
                long_notional_value = self.long_position * self.latest_price

                # 获取风控决策
                risk_decision = self.risk_manager.should_reduce_position(
                    self.exchange_client.ccxt_symbol, 'long', long_notional_value
                )

                if risk_decision['should_reduce']:
                    # 打印明确的警告日志，用于事后复盘
                    logger.warning(f"🚨 多头风控触发: {risk_decision['reason']}")
                    logger.warning(f"   风险等级: {risk_decision['urgency']}")
                    logger.warning(f"   建议减仓比例: {risk_decision['suggested_ratio']:.1%}")

                    # 判断紧急程度
                    if risk_decision['urgency'] in ['HIGH', 'MEDIUM']:
                        # 计算要减仓的数量
                        reduce_qty = self.long_position * risk_decision['suggested_ratio']
                        reduce_qty = round(reduce_qty, self.exchange_client.amount_precision)
                        reduce_qty = max(reduce_qty, self.exchange_client.min_order_amount)

                        logger.warning(f"🔥 执行紧急减仓: 卖出 {reduce_qty} 张多头仓位")

                        # 下达市价减仓订单
                        order = self.exchange_client.place_order(
                            'sell', None, reduce_qty,
                            is_reduce_only=True, position_side='LONG', order_type='market'
                        )

                        if order:
                            logger.warning(f"✅ 多头减仓订单提交成功: {order.get('id', 'N/A')}")
                        else:
                            logger.error("❌ 多头减仓订单提交失败")

            # 第三步：空头仓位风险审查与执行
            if self.short_position > 0:
                # 计算空头仓位的名义价值
                short_notional_value = self.short_position * self.latest_price

                # 获取风控决策
                risk_decision = self.risk_manager.should_reduce_position(
                    self.exchange_client.ccxt_symbol, 'short', short_notional_value
                )

                if risk_decision['should_reduce']:
                    # 打印明确的警告日志，用于事后复盘
                    logger.warning(f"🚨 空头风控触发: {risk_decision['reason']}")
                    logger.warning(f"   风险等级: {risk_decision['urgency']}")
                    logger.warning(f"   建议减仓比例: {risk_decision['suggested_ratio']:.1%}")

                    # 判断紧急程度
                    if risk_decision['urgency'] in ['HIGH', 'MEDIUM']:
                        # 计算要减仓的数量
                        reduce_qty = self.short_position * risk_decision['suggested_ratio']
                        reduce_qty = round(reduce_qty, self.exchange_client.amount_precision)
                        reduce_qty = max(reduce_qty, self.exchange_client.min_order_amount)

                        logger.warning(f"🔥 执行紧急减仓: 买入 {reduce_qty} 张空头仓位")

                        # 下达市价减仓订单
                        order = self.exchange_client.place_order(
                            'buy', None, reduce_qty,
                            is_reduce_only=True, position_side='SHORT', order_type='market'
                        )

                        if order:
                            logger.warning(f"✅ 空头减仓订单提交成功: {order.get('id', 'N/A')}")
                        else:
                            logger.error("❌ 空头减仓订单提交失败")

        except Exception as e:
            logger.error(f"风控检查时出错: {e}", exc_info=True)
