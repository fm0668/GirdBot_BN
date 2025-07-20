import ccxt
import math
import logging
import uuid
import time
from config import API_KEY, API_SECRET, LEVERAGE

logger = logging.getLogger(__name__)


class CustomGate(ccxt.binance):
    def fetch(self, url, method='GET', headers=None, body=None):
        if headers is None:
            headers = {}
        # headers['X-Gate-Channel-Id'] = 'laohuoji'
        # headers['Accept'] = 'application/json'
        # headers['Content-Type'] = 'application/json'
        return super().fetch(url, method, headers, body)


class ExchangeClient:
    """交易所客户端，封装所有与交易所相关的API调用"""
    
    def __init__(self, api_key, api_secret, coin_name, contract_type):
        self.api_key = api_key
        self.api_secret = api_secret
        self.coin_name = coin_name
        self.contract_type = contract_type
        self.exchange = self._initialize_exchange()
        self.ccxt_symbol = f"{coin_name}/{contract_type}:{contract_type}"

        # 初始化缓存变量
        self.cached_long_position = 0
        self.cached_short_position = 0

        # 获取交易精度信息
        self._get_price_precision()

        # 设置杠杆
        self.set_initial_leverage()
        
    def _initialize_exchange(self):
        """初始化交易所 API"""
        exchange = CustomGate({
            "apiKey": self.api_key,
            "secret": self.api_secret,
            "options": {
                "defaultType": "future",  # 使用永续合约
            },
        })
        # 加载市场数据
        exchange.load_markets(reload=False)
        return exchange

    def _get_price_precision(self):
        """获取交易对的价格精度、数量精度和最小下单数量"""
        markets = self.exchange.fetch_markets()
        symbol_info = next(market for market in markets if market["symbol"] == self.ccxt_symbol)

        # 获取价格精度
        price_precision = symbol_info["precision"]["price"]
        if isinstance(price_precision, float):
            self.price_precision = int(abs(math.log10(price_precision)))
        elif isinstance(price_precision, int):
            self.price_precision = price_precision
        else:
            raise ValueError(f"未知的价格精度类型: {price_precision}")

        # 获取数量精度
        amount_precision = symbol_info["precision"]["amount"]
        if isinstance(amount_precision, float):
            self.amount_precision = int(abs(math.log10(amount_precision)))
        elif isinstance(amount_precision, int):
            self.amount_precision = amount_precision
        else:
            raise ValueError(f"未知的数量精度类型: {amount_precision}")

        # 获取最小下单数量
        self.min_order_amount = symbol_info["limits"]["amount"]["min"]

        logger.info(
            f"价格精度: {self.price_precision}, 数量精度: {self.amount_precision}, 最小下单数量: {self.min_order_amount}")

    def get_position(self):
        """获取当前持仓（改进的异常处理）"""
        try:
            params = {'type': 'future'}
            positions = self.exchange.fetch_positions(params=params)

            long_position = 0
            short_position = 0

            for position in positions:
                if position['symbol'] == self.ccxt_symbol:
                    contracts = position.get('contracts', 0)
                    side = position.get('side', None)

                    if side == 'long':
                        long_position = contracts
                    elif side == 'short':
                        short_position = abs(contracts)

            # 更新缓存
            self.cached_long_position = long_position
            self.cached_short_position = short_position

            return long_position, short_position

        except ccxt.NetworkError as e:
            logger.warning(f"查询持仓网络错误: {e}")
            # 返回上次缓存的持仓数据
            return self.cached_long_position, self.cached_short_position

        except ccxt.ExchangeError as e:
            logger.error(f"查询持仓失败: {e}")
            return 0, 0

        except Exception as e:
            logger.exception(f"查询持仓时发生未知异常: {e}")
            return 0, 0

    def fetch_open_orders(self):
        """获取当前所有挂单"""
        return self.exchange.fetch_open_orders(self.ccxt_symbol)

    def cancel_order(self, order_id):
        """撤单"""
        try:
            self.exchange.cancel_order(order_id, self.ccxt_symbol)
            logger.info(f"撤销挂单成功, 订单ID: {order_id}")
        except ccxt.BaseError as e:
            logger.error(f"撤单失败: {e}")
            raise e

    def place_order(self, side, price, quantity, is_reduce_only=False, position_side=None, order_type='limit'):
        """挂单函数（修复唯一ID问题和精细化异常处理）"""
        try:
            # 生成唯一的客户端订单ID
            timestamp = int(time.time() * 1000)
            unique_suffix = uuid.uuid4().hex[:8]
            unique_client_id = f"grid-{side}-{timestamp}-{unique_suffix}"

            # 修正价格精度
            if price is not None:
                price = round(price, self.price_precision)

            # 修正数量精度并确保不低于最小下单数量
            quantity = round(quantity, self.amount_precision)
            quantity = max(quantity, self.min_order_amount)

            params = {
                'newClientOrderId': unique_client_id,  # 使用唯一ID
                'reduce_only': is_reduce_only,
            }
            if position_side is not None:
                params['positionSide'] = position_side.upper()

            if order_type == 'market':
                order = self.exchange.create_order(self.ccxt_symbol, 'market', side, quantity, params=params)
            else:
                if price is None:
                    logger.error("限价单必须提供 price 参数")
                    return None
                order = self.exchange.create_order(self.ccxt_symbol, 'limit', side, quantity, price, params)

            logger.info(f"下单成功: {side} {quantity} @ {price}, 订单ID: {unique_client_id}")
            return order

        except ccxt.InsufficientFunds as e:
            logger.critical(f"保证金不足，无法下单: {e}")
            return None

        except ccxt.InvalidOrder as e:
            logger.error(f"订单参数无效: {e}")
            return None

        except ccxt.NetworkError as e:
            logger.warning(f"网络错误，稍后重试: {e}")
            return None

        except ccxt.ExchangeNotAvailable as e:
            if 'maintenance' in str(e).lower():
                logger.warning(f"交易所维护中: {e}")
            else:
                logger.error(f"交易所不可用: {e}")
            return None

        except ccxt.ExchangeError as e:
            error_msg = str(e).lower()
            if 'position side does not match' in error_msg:
                logger.error(f"持仓方向不匹配: {e}")
            elif 'order would immediately match' in error_msg:
                logger.warning(f"订单会立即成交，调整价格: {e}")
            elif 'clientorderid is duplicated' in error_msg:
                logger.error(f"订单ID重复: {e}")
            else:
                logger.error(f"交易所返回错误: {e}")
            return None

        except Exception as e:
            logger.exception(f"下单时发生未知异常: {e}")
            return None

    def get_listen_key(self):
        """获取 listenKey"""
        try:
            response = self.exchange.fapiPrivatePostListenKey()
            listenKey = response.get("listenKey")
            if not listenKey:
                raise ValueError("获取的 listenKey 为空")
            logger.info(f"成功获取 listenKey: {listenKey}")
            return listenKey
        except Exception as e:
            logger.error(f"获取 listenKey 失败: {e}")
            raise e

    def update_listen_key(self):
        """更新 listenKey"""
        self.exchange.fapiPrivatePutListenKey()

    def check_and_enable_hedge_mode(self):
        """检查并启用双向持仓模式"""
        try:
            position_mode = self.exchange.fetch_position_mode(symbol=self.ccxt_symbol)
            if not position_mode['hedged']:
                logger.info("当前不是双向持仓模式，尝试自动启用双向持仓模式...")
                self.enable_hedge_mode()

                position_mode = self.exchange.fetch_position_mode(symbol=self.ccxt_symbol)
                if not position_mode['hedged']:
                    logger.error("启用双向持仓模式失败，请手动启用双向持仓模式后再运行程序。")
                    raise Exception("启用双向持仓模式失败，请手动启用双向持仓模式后再运行程序。")
                else:
                    logger.info("双向持仓模式已成功启用，程序继续运行。")
            else:
                logger.info("当前已是双向持仓模式，程序继续运行。")
        except Exception as e:
            logger.error(f"检查或启用双向持仓模式失败: {e}")
            raise e

    def enable_hedge_mode(self):
        """启用双向持仓模式"""
        try:
            params = {'dualSidePosition': 'true'}
            response = self.exchange.fapiPrivatePostPositionSideDual(params)
            logger.info(f"启用双向持仓模式: {response}")
        except Exception as e:
            logger.error(f"启用双向持仓模式失败: {e}")
            raise e

    def set_initial_leverage(self):
        """设置初始杠杆倍数"""
        try:
            logger.info(f"设置杠杆倍数为: {LEVERAGE}x")
            self.exchange.set_leverage(LEVERAGE, self.ccxt_symbol)
            logger.info(f"杠杆设置成功: {LEVERAGE}x")
        except ccxt.ExchangeError as e:
            if 'leverage not modified' in str(e).lower():
                logger.info(f"杠杆已经是{LEVERAGE}x，无需修改")
            else:
                logger.error(f"设置杠杆失败: {e}")
                raise e
        except Exception as e:
            logger.error(f"设置杠杆时发生异常: {e}")
            raise e

    def verify_leverage(self):
        """验证当前杠杆设置"""
        try:
            # 获取当前杠杆设置
            positions = self.exchange.fetch_positions([self.ccxt_symbol])
            for position in positions:
                if position['symbol'] == self.ccxt_symbol:
                    current_leverage = position.get('leverage', 1)
                    if current_leverage != LEVERAGE:
                        logger.warning(f"当前杠杆{current_leverage}x与配置{LEVERAGE}x不符，重新设置")
                        self.set_initial_leverage()
                    break
        except Exception as e:
            logger.error(f"验证杠杆设置失败: {e}")

    def get_api_rate_limits(self):
        """获取API速率限制信息"""
        try:
            exchange_info = self.exchange.fetch_markets()
            # 尝试获取速率限制信息
            if hasattr(self.exchange, 'describe'):
                api_info = self.exchange.describe()
                rate_limits = api_info.get('rateLimit', {})
                logger.info(f"API速率限制信息: {rate_limits}")
                return rate_limits

            # 如果无法获取详细信息，返回保守估计
            logger.warning("无法获取详细的API限制信息，使用保守设置")
            return {
                'weight_per_minute': 1200,  # 保守估计
                'orders_weight': 1,         # fetch_open_orders单个交易对权重
                'orders_all_weight': 40     # fetch_open_orders所有交易对权重
            }

        except Exception as e:
            logger.error(f"获取API限制信息失败: {e}")
            # 返回最保守的设置
            return {
                'weight_per_minute': 600,   # 更保守的估计
                'orders_weight': 1,
                'orders_all_weight': 40
            }

    def cancel_all_orders(self):
        """撤销所有挂单"""
        try:
            logger.info("开始撤销所有挂单...")
            orders = self.fetch_open_orders()

            if not orders:
                logger.info("没有挂单需要撤销")
                return True

            canceled_count = 0
            failed_count = 0

            for order in orders:
                try:
                    self.cancel_order(order['id'])
                    canceled_count += 1
                    logger.info(f"撤销订单成功: {order['id']}")
                except Exception as e:
                    failed_count += 1
                    logger.error(f"撤销订单失败 {order['id']}: {e}")

            logger.info(f"撤单完成: 成功 {canceled_count} 个, 失败 {failed_count} 个")
            return failed_count == 0

        except Exception as e:
            logger.error(f"撤销所有挂单失败: {e}")
            return False

    def close_all_positions(self):
        """市价平仓所有持仓"""
        try:
            logger.info("开始市价平仓所有持仓...")
            long_position, short_position = self.get_position()

            if long_position == 0 and short_position == 0:
                logger.info("没有持仓需要平仓")
                return True

            success = True

            # 平多头仓位
            if long_position > 0:
                try:
                    logger.info(f"平多头仓位: {long_position}")
                    order = self.place_order(
                        'sell', None, long_position,
                        is_reduce_only=True, position_side='LONG', order_type='market'
                    )
                    if order:
                        logger.info(f"多头平仓订单提交成功: {order.get('id', 'N/A')}")
                    else:
                        logger.error("多头平仓订单提交失败")
                        success = False
                except Exception as e:
                    logger.error(f"平多头仓位失败: {e}")
                    success = False

            # 平空头仓位
            if short_position > 0:
                try:
                    logger.info(f"平空头仓位: {short_position}")
                    order = self.place_order(
                        'buy', None, short_position,
                        is_reduce_only=True, position_side='SHORT', order_type='market'
                    )
                    if order:
                        logger.info(f"空头平仓订单提交成功: {order.get('id', 'N/A')}")
                    else:
                        logger.error("空头平仓订单提交失败")
                        success = False
                except Exception as e:
                    logger.error(f"平空头仓位失败: {e}")
                    success = False

            return success

        except Exception as e:
            logger.error(f"市价平仓所有持仓失败: {e}")
            return False

    def cleanup_account(self):
        """清理账户：撤销所有挂单并平仓所有持仓"""
        logger.info("=" * 50)
        logger.info("开始清理账户...")

        # 第一步：撤销所有挂单
        cancel_success = self.cancel_all_orders()

        # 等待撤单完成
        import time
        time.sleep(2)

        # 第二步：平仓所有持仓
        close_success = self.close_all_positions()

        # 等待平仓完成
        time.sleep(3)

        # 第三步：验证清理结果
        final_orders = self.fetch_open_orders()
        final_long, final_short = self.get_position()

        if len(final_orders) == 0 and final_long == 0 and final_short == 0:
            logger.info("账户清理完成：所有挂单已撤销，所有持仓已平仓")
            logger.info("=" * 50)
            return True
        else:
            logger.warning(f"账户清理不完整：剩余挂单 {len(final_orders)} 个，多头持仓 {final_long}，空头持仓 {final_short}")
            logger.info("=" * 50)
            return False

    def fetch_account_summary(self):
        """获取账户财务数据摘要"""
        try:
            balance_info = self.exchange.fetch_balance()

            # 获取USDC余额信息（合约交易的计价货币）
            usdc_info = balance_info.get('USDC', {})
            if not usdc_info:
                # 如果没有USDC，尝试USDT
                usdc_info = balance_info.get('USDT', {})

            account_summary = {
                'account_balance': float(usdc_info.get('total', 0)),  # 账户总权益
                'available_balance': float(usdc_info.get('free', 0)),  # 可用余额
                'used_balance': float(usdc_info.get('used', 0)),      # 已用保证金
                'currency': 'USDC' if 'USDC' in balance_info else 'USDT'
            }

            logger.debug(f"账户摘要: {account_summary}")
            return account_summary

        except Exception as e:
            logger.error(f"获取账户摘要失败: {e}")
            return {
                'account_balance': 0,
                'available_balance': 0,
                'used_balance': 0,
                'currency': 'USDC'
            }

    def fetch_detailed_positions_for_symbol(self, symbol):
        """获取指定交易对的详细持仓数据"""
        try:
            positions = self.exchange.fetch_positions([symbol])

            detailed_positions = []
            for position in positions:
                if position['symbol'] == symbol and float(position.get('contracts', 0)) != 0:
                    position_detail = {
                        'symbol': position['symbol'],
                        'side': position['side'],  # 'long' or 'short'
                        'size': float(position.get('contracts', 0)),  # 持仓数量
                        'unrealized_pnl': float(position.get('unrealizedPnl', 0)),  # 未实现盈亏
                        'percentage': float(position.get('percentage', 0)),  # 盈亏百分比
                        'entry_price': float(position.get('entryPrice', 0)),  # 开仓均价
                        'mark_price': float(position.get('markPrice', 0)),  # 标记价格
                        'notional': float(position.get('notional', 0)),  # 名义价值
                        'margin': float(position.get('initialMargin', 0))  # 初始保证金
                    }
                    detailed_positions.append(position_detail)

            logger.debug(f"详细持仓数据: {detailed_positions}")
            return detailed_positions

        except Exception as e:
            logger.error(f"获取详细持仓数据失败: {e}")
            return []
