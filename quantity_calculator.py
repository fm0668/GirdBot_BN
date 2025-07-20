import logging
import time
from typing import Dict, Any

logger = logging.getLogger(__name__)

class QuantityCalculator:
    """动态交易数量计算器
    
    核心目标：基于账户资金、风险偏好和市场条件，计算最优的交易数量
    确保资金利用率最大化的同时控制风险
    """
    
    def __init__(self, exchange_client, risk_manager, 
                 account_usage_ratio=0.6, 
                 single_order_ratio=0.1,
                 min_order_value=5.0,
                 max_order_value=100.0):
        """
        初始化动态数量计算器
        
        :param exchange_client: 交易所客户端
        :param risk_manager: 风险管理器
        :param account_usage_ratio: 账户资金使用比例 (0.6 = 60%)
        :param single_order_ratio: 单笔订单占可用资金比例 (0.1 = 10%)
        :param min_order_value: 最小订单价值 (USDC)
        :param max_order_value: 最大订单价值 (USDC)
        """
        self.exchange_client = exchange_client
        self.risk_manager = risk_manager
        self.account_usage_ratio = account_usage_ratio
        self.single_order_ratio = single_order_ratio
        self.min_order_value = min_order_value
        self.max_order_value = max_order_value
        
        # 缓存机制，避免频繁计算
        self.last_calculation_time = 0
        self.cached_quantity = 50  # 默认值
        self.cache_duration = 30   # 缓存30秒
        
    def calculate_optimal_quantity(self, current_price: float, 
                                 current_position: float = 0,
                                 side: str = 'long') -> float:
        """
        计算最优交易数量
        
        :param current_price: 当前价格
        :param current_position: 当前持仓数量
        :param side: 交易方向 ('long' 或 'short')
        :return: 最优交易数量
        """
        # 检查缓存
        current_time = time.time()
        if current_time - self.last_calculation_time < self.cache_duration:
            return self.cached_quantity
            
        try:
            # 确保风险管理器数据是最新的
            if self.risk_manager.should_update_account_info():
                self.risk_manager.update_account_info()
                
            # 获取账户信息
            available_balance = self.risk_manager.available_balance
            account_balance = self.risk_manager.account_balance
            
            if available_balance <= 0 or account_balance <= 0:
                logger.warning("账户余额不足，使用最小交易数量")
                return self._get_min_quantity(current_price)
                
            # 计算基于资金的最优数量
            optimal_quantity = self._calculate_by_funds(current_price, available_balance)
            
            # 应用风险控制
            safe_quantity = self._apply_risk_controls(
                optimal_quantity, current_price, current_position, side
            )
            
            # 应用交易所限制
            final_quantity = self._apply_exchange_limits(safe_quantity, current_price)
            
            # 更新缓存
            self.cached_quantity = final_quantity
            self.last_calculation_time = current_time
            
            logger.info(f"💡 动态数量计算 - 价格: {current_price:.5f}, "
                       f"可用资金: {available_balance:.2f} USDC, "
                       f"计算数量: {final_quantity:.0f} 张, "
                       f"订单价值: {final_quantity * current_price:.2f} USDC")
            
            return final_quantity
            
        except Exception as e:
            logger.error(f"动态数量计算失败: {e}")
            return self._get_min_quantity(current_price)
            
    def _calculate_by_funds(self, current_price: float, available_balance: float) -> float:
        """基于资金计算最优数量"""
        
        # 方法1：基于单笔订单资金比例
        single_order_value = available_balance * self.single_order_ratio
        quantity_by_ratio = single_order_value / current_price
        
        # 方法2：基于账户总资金使用率
        total_usable_funds = available_balance * self.account_usage_ratio
        # 假设同时有4个订单（多头买卖 + 空头买卖）
        avg_order_value = total_usable_funds / 4
        quantity_by_usage = avg_order_value / current_price
        
        # 取两者的平均值，平衡激进和保守策略
        optimal_quantity = (quantity_by_ratio + quantity_by_usage) / 2
        
        logger.debug(f"资金计算 - 单笔比例法: {quantity_by_ratio:.1f}, "
                    f"总资金法: {quantity_by_usage:.1f}, "
                    f"平均值: {optimal_quantity:.1f}")
        
        return optimal_quantity
        
    def _apply_risk_controls(self, quantity: float, current_price: float,
                           current_position: float, side: str) -> float:
        """应用风险控制"""
        
        # 使用风险管理器的安全计算
        safe_quantity = self.risk_manager.calculate_safe_order_size(
            current_position, current_price, quantity
        )
        
        # 检查保证金风险
        risk_level = self.risk_manager.check_margin_risk()
        if risk_level == "HIGH_RISK":
            safe_quantity *= 0.5  # 高风险时减半
            logger.warning(f"高风险状态，订单数量减半至: {safe_quantity:.1f}")
        elif risk_level == "MEDIUM_RISK":
            safe_quantity *= 0.8  # 中等风险时减少20%
            logger.info(f"中等风险状态，订单数量调整至: {safe_quantity:.1f}")
            
        return safe_quantity
        
    def _apply_exchange_limits(self, quantity: float, current_price: float) -> float:
        """应用交易所限制"""
        
        # 确保订单价值在合理范围内
        order_value = quantity * current_price
        
        if order_value < self.min_order_value:
            # 订单价值太小，调整到最小值
            quantity = self.min_order_value / current_price * 1.1  # 增加10%缓冲
            logger.debug(f"订单价值过小，调整至最小值: {quantity:.1f} 张")
            
        elif order_value > self.max_order_value:
            # 订单价值太大，调整到最大值
            quantity = self.max_order_value / current_price
            logger.debug(f"订单价值过大，调整至最大值: {quantity:.1f} 张")
            
        # 应用交易所精度限制
        if hasattr(self.exchange_client, 'amount_precision'):
            quantity = round(quantity, self.exchange_client.amount_precision)
        else:
            quantity = round(quantity, 0)  # 默认整数
            
        # 确保满足最小交易数量
        if hasattr(self.exchange_client, 'min_order_amount'):
            quantity = max(quantity, self.exchange_client.min_order_amount)
        else:
            quantity = max(quantity, 1.0)  # 默认最小1张
            
        return quantity
        
    def _get_min_quantity(self, current_price: float) -> float:
        """获取最小安全交易数量"""
        min_quantity = self.min_order_value / current_price * 1.2  # 增加20%缓冲
        
        # 应用交易所限制
        if hasattr(self.exchange_client, 'min_order_amount'):
            min_quantity = max(min_quantity, self.exchange_client.min_order_amount)
        else:
            min_quantity = max(min_quantity, 1.0)
            
        return round(min_quantity, 0)
        
    def get_quantity_for_hedge_init(self, current_price: float) -> float:
        """获取对冲初始化的交易数量（通常更保守）"""
        # 对冲初始化使用更保守的参数
        conservative_quantity = self.calculate_optimal_quantity(current_price) * 0.8
        return max(conservative_quantity, self._get_min_quantity(current_price))
        
    def get_quantity_for_grid_order(self, current_price: float, 
                                  current_position: float, side: str) -> float:
        """获取网格订单的交易数量"""
        return self.calculate_optimal_quantity(current_price, current_position, side)
        
    def update_parameters(self, account_usage_ratio: float = None,
                         single_order_ratio: float = None,
                         min_order_value: float = None,
                         max_order_value: float = None):
        """动态更新计算参数"""
        if account_usage_ratio is not None:
            self.account_usage_ratio = account_usage_ratio
        if single_order_ratio is not None:
            self.single_order_ratio = single_order_ratio
        if min_order_value is not None:
            self.min_order_value = min_order_value
        if max_order_value is not None:
            self.max_order_value = max_order_value
            
        # 清除缓存，强制重新计算
        self.last_calculation_time = 0
        logger.info(f"数量计算参数已更新 - 账户使用率: {self.account_usage_ratio:.1%}, "
                   f"单笔订单比例: {self.single_order_ratio:.1%}")
        
    def get_calculation_stats(self) -> Dict[str, Any]:
        """获取计算统计信息"""
        return {
            'account_usage_ratio': self.account_usage_ratio,
            'single_order_ratio': self.single_order_ratio,
            'min_order_value': self.min_order_value,
            'max_order_value': self.max_order_value,
            'cached_quantity': self.cached_quantity,
            'cache_age_seconds': time.time() - self.last_calculation_time
        }
