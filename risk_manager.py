import logging
import time
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class RiskManager:
    """简化版资金和风险管理器"""
    
    def __init__(self, exchange_client, leverage: int, max_position_ratio=0.8, stop_loss_ratio=0.15):
        self.exchange_client = exchange_client
        self.leverage = leverage
        self.max_position_ratio = max_position_ratio
        self.stop_loss_ratio = stop_loss_ratio
        
        # 账户信息缓存
        self.last_balance_check = 0
        self.account_balance = 0
        self.available_balance = 0
        self.margin_ratio = 0
        self.total_unrealized_pnl = 0
        
        # 持仓信息缓存
        self.position_cache = {}
        self.last_position_update = 0
        
    def update_account_info(self):
        """更新账户信息（简化版本，兼容现有ExchangeClient）"""
        try:
            # 使用现有的get_account_balance方法
            if hasattr(self.exchange_client, 'get_account_balance'):
                balance_info = self.exchange_client.get_account_balance()
                self.account_balance = float(balance_info.get('totalWalletBalance', 0))
                self.available_balance = float(balance_info.get('availableBalance', 0))

                # 计算保证金使用率
                used_margin = self.account_balance - self.available_balance
                self.margin_ratio = used_margin / self.account_balance if self.account_balance > 0 else 0

                logger.debug(f"账户余额: {self.account_balance:.2f} USDC, "
                           f"可用余额: {self.available_balance:.2f} USDC, "
                           f"保证金使用率: {self.margin_ratio:.2%}")
                self.last_balance_check = time.time()
            else:
                # 如果没有相应方法，使用默认值
                logger.debug("ExchangeClient不支持账户余额查询，使用默认值")
                self.account_balance = 1000  # 默认值
                self.available_balance = 500  # 默认值
                self.margin_ratio = 0.5

        except Exception as e:
            logger.debug(f"更新账户信息失败，使用默认值: {e}")
            self.account_balance = 1000
            self.available_balance = 500
            self.margin_ratio = 0.5

    def update_position_info(self, symbol: str):
        """更新持仓信息（简化版本，兼容现有ExchangeClient）"""
        try:
            # 使用现有的get_positions方法
            if hasattr(self.exchange_client, 'get_positions'):
                positions = self.exchange_client.get_positions()

                total_unrealized_pnl = 0
                position_data = {}

                for position in positions:
                    if position.get('symbol') == symbol:
                        side = position.get('positionSide', '').lower()
                        if side in ['long', 'short']:
                            unrealized_pnl = float(position.get('unrealizedPnl', 0))
                            position_data[side] = {
                                'size': float(position.get('positionAmt', 0)),
                                'unrealized_pnl': unrealized_pnl,
                                'percentage': float(position.get('percentage', 0)),
                                'entry_price': float(position.get('entryPrice', 0)),
                                'mark_price': float(position.get('markPrice', 0))
                            }
                            total_unrealized_pnl += unrealized_pnl

                self.position_cache[symbol] = position_data
                self.total_unrealized_pnl = total_unrealized_pnl
                self.last_position_update = time.time()

                logger.debug(f"更新持仓信息: {symbol}, 总未实现盈亏: {total_unrealized_pnl:.2f}")
            else:
                logger.debug("ExchangeClient不支持持仓信息查询")

        except Exception as e:
            logger.debug(f"更新持仓信息失败: {e}")
            
    def get_position_pnl(self, symbol: str, side: str) -> float:
        """获取指定持仓的未实现盈亏"""
        if symbol in self.position_cache and side in self.position_cache[symbol]:
            return self.position_cache[symbol][side]['unrealized_pnl']
        return 0.0
        
    def get_position_percentage(self, symbol: str, side: str) -> float:
        """获取持仓盈亏百分比"""
        if symbol in self.position_cache and side in self.position_cache[symbol]:
            return self.position_cache[symbol][side]['percentage']
        return 0.0
        
    def calculate_max_position_size(self, price: float) -> float:
        """计算最大允许仓位大小"""
        if self.account_balance <= 0:
            return 0
            
        # 基于账户余额和杠杆计算最大仓位
        max_notional = self.account_balance * self.leverage * self.max_position_ratio
        max_position = max_notional / price
        
        return max_position
        
    def calculate_safe_order_size(self, current_position: float, price: float,
                                 base_quantity: float) -> float:
        """计算安全的订单大小（确保满足最小订单金额要求）"""
        # 币安要求订单金额不小于5 USDC
        min_notional = 5.0
        min_quantity_for_notional = min_notional / price

        # 确保基础数量满足最小金额要求
        if base_quantity * price < min_notional:
            base_quantity = min_quantity_for_notional * 1.1  # 增加10%缓冲

        max_position = self.calculate_max_position_size(price)

        # 确保不超过最大仓位限制
        safe_quantity = min(base_quantity, max_position - current_position)
        safe_quantity = max(0, safe_quantity)

        # 确保不超过可用余额限制
        required_margin = safe_quantity * price / self.leverage
        if self.available_balance > 0 and required_margin > self.available_balance * 0.9:
            safe_quantity = (self.available_balance * 0.9 * self.leverage) / price

        # 再次检查最小金额要求
        if safe_quantity * price < min_notional:
            safe_quantity = min_quantity_for_notional * 1.1

        # 应用精度限制
        if hasattr(self.exchange_client, 'amount_precision'):
            safe_quantity = round(safe_quantity, self.exchange_client.amount_precision)
        else:
            safe_quantity = round(safe_quantity, 0)  # 默认整数

        if hasattr(self.exchange_client, 'min_order_amount'):
            safe_quantity = max(safe_quantity, self.exchange_client.min_order_amount)
        else:
            safe_quantity = max(safe_quantity, 1.0)  # 默认最小1张

        return safe_quantity
        
    def check_margin_risk(self) -> str:
        """检查保证金风险"""
        if self.margin_ratio > 0.85:
            logger.warning(f"保证金使用率过高: {self.margin_ratio:.2%}")
            return "HIGH_RISK"
        elif self.margin_ratio > 0.7:
            logger.warning(f"保证金使用率较高: {self.margin_ratio:.2%}")
            return "MEDIUM_RISK"
        else:
            return "LOW_RISK"
            
    def should_reduce_position(self, symbol: str, side: str, position_value: float) -> Dict[str, Any]:
        """判断是否应该减仓（简化版）"""
        # 获取真实的未实现盈亏
        unrealized_pnl = self.get_position_pnl(symbol, side)
        pnl_percentage = self.get_position_percentage(symbol, side)
        
        result = {
            'should_reduce': False,
            'reason': '',
            'urgency': 'LOW',
            'suggested_ratio': 0.0
        }
        
        # 检查止损条件
        if unrealized_pnl < 0 and abs(unrealized_pnl) > position_value * self.stop_loss_ratio:
            result.update({
                'should_reduce': True,
                'reason': f'触发止损条件，未实现亏损: {unrealized_pnl:.2f} ({pnl_percentage:.2%})',
                'urgency': 'HIGH',
                'suggested_ratio': 0.5  # 建议减仓50%
            })
            return result
            
        # 检查极端亏损
        if pnl_percentage < -20:  # 亏损超过20%
            result.update({
                'should_reduce': True,
                'reason': f'持仓亏损过大: {pnl_percentage:.2%}',
                'urgency': 'HIGH',
                'suggested_ratio': 0.3
            })
            return result
            
        # 检查保证金风险
        risk_level = self.check_margin_risk()
        if risk_level == "HIGH_RISK":
            result.update({
                'should_reduce': True,
                'reason': f'保证金使用率过高: {self.margin_ratio:.2%}',
                'urgency': 'MEDIUM',
                'suggested_ratio': 0.4
            })
            return result
            
        return result
        
    def get_position_adjustment_ratio(self) -> float:
        """根据风险水平获取仓位调整比例"""
        risk_level = self.check_margin_risk()
        
        if risk_level == "HIGH_RISK":
            return 0.5  # 减半仓位
        elif risk_level == "MEDIUM_RISK":
            return 0.8  # 减少20%仓位
        else:
            return 1.0  # 正常仓位
            
    def get_risk_metrics(self) -> Dict[str, Any]:
        """获取风险指标摘要"""
        return {
            'account_balance': self.account_balance,
            'available_balance': self.available_balance,
            'margin_ratio': self.margin_ratio,
            'total_unrealized_pnl': self.total_unrealized_pnl,
            'risk_level': self.check_margin_risk(),
            'position_adjustment_ratio': self.get_position_adjustment_ratio()
        }
        
    def should_update_account_info(self) -> bool:
        """检查是否需要更新账户信息"""
        return time.time() - self.last_balance_check > 60  # 60秒更新一次
        
    def should_update_position_info(self) -> bool:
        """检查是否需要更新持仓信息"""
        return time.time() - self.last_position_update > 30  # 30秒更新一次
