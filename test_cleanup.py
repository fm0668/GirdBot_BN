#!/usr/bin/env python3
"""
测试清理功能脚本
用于测试启动清理和优雅停止功能
"""

import asyncio
import logging
import os
from config import API_KEY, API_SECRET, COIN_NAME, CONTRACT_TYPE
from exchange_client import ExchangeClient

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),  # 控制台输出
    ],
)
logger = logging.getLogger()


async def test_cleanup_functions():
    """测试清理功能"""
    
    if not API_KEY or not API_SECRET:
        logger.error("请在 config.py 中配置 API_KEY 和 API_SECRET")
        return
    
    try:
        # 创建交易所客户端
        logger.info("初始化交易所客户端...")
        exchange_client = ExchangeClient(API_KEY, API_SECRET, COIN_NAME, CONTRACT_TYPE)
        
        # 显示当前状态
        logger.info("=" * 50)
        logger.info("清理前状态:")
        
        # 获取当前持仓
        long_pos, short_pos = exchange_client.get_position()
        logger.info(f"当前持仓: 多头 {long_pos}, 空头 {short_pos}")
        
        # 获取当前挂单
        orders = exchange_client.fetch_open_orders()
        logger.info(f"当前挂单数量: {len(orders)}")
        for order in orders:
            logger.info(f"  订单: {order['id']} - {order['side']} {order['amount']} @ {order['price']}")
        
        # 执行清理
        logger.info("=" * 50)
        logger.info("开始执行清理...")
        cleanup_success = exchange_client.cleanup_account()
        
        # 显示清理后状态
        logger.info("=" * 50)
        logger.info("清理后状态:")
        
        # 重新获取持仓和挂单
        long_pos, short_pos = exchange_client.get_position()
        logger.info(f"清理后持仓: 多头 {long_pos}, 空头 {short_pos}")
        
        orders = exchange_client.fetch_open_orders()
        logger.info(f"清理后挂单数量: {len(orders)}")
        
        if cleanup_success:
            logger.info("✅ 清理功能测试成功")
        else:
            logger.warning("⚠️ 清理功能测试不完整")
            
    except Exception as e:
        logger.error(f"❌ 测试过程中发生错误: {e}")
        raise


async def test_individual_functions():
    """测试单独的清理功能"""
    
    if not API_KEY or not API_SECRET:
        logger.error("请在 config.py 中配置 API_KEY 和 API_SECRET")
        return
    
    try:
        # 创建交易所客户端
        exchange_client = ExchangeClient(API_KEY, API_SECRET, COIN_NAME, CONTRACT_TYPE)
        
        logger.info("=" * 50)
        logger.info("测试单独的撤单功能...")
        
        # 测试撤单功能
        orders_before = exchange_client.fetch_open_orders()
        logger.info(f"撤单前挂单数量: {len(orders_before)}")
        
        cancel_success = exchange_client.cancel_all_orders()
        
        orders_after = exchange_client.fetch_open_orders()
        logger.info(f"撤单后挂单数量: {len(orders_after)}")
        
        if cancel_success:
            logger.info("✅ 撤单功能测试成功")
        else:
            logger.warning("⚠️ 撤单功能测试不完整")
        
        # 等待一段时间
        await asyncio.sleep(2)
        
        logger.info("=" * 50)
        logger.info("测试单独的平仓功能...")
        
        # 测试平仓功能
        long_before, short_before = exchange_client.get_position()
        logger.info(f"平仓前持仓: 多头 {long_before}, 空头 {short_before}")
        
        close_success = exchange_client.close_all_positions()
        
        # 等待平仓完成
        await asyncio.sleep(3)
        
        long_after, short_after = exchange_client.get_position()
        logger.info(f"平仓后持仓: 多头 {long_after}, 空头 {short_after}")
        
        if close_success:
            logger.info("✅ 平仓功能测试成功")
        else:
            logger.warning("⚠️ 平仓功能测试不完整")
            
    except Exception as e:
        logger.error(f"❌ 测试过程中发生错误: {e}")
        raise


async def main():
    """主函数"""
    logger.info("开始测试清理功能...")
    
    print("\n选择测试模式:")
    print("1. 测试完整清理功能 (cleanup_account)")
    print("2. 测试单独功能 (cancel_all_orders + close_all_positions)")
    print("3. 只查看当前状态")
    
    try:
        choice = input("请输入选择 (1/2/3): ").strip()
        
        if choice == "1":
            await test_cleanup_functions()
        elif choice == "2":
            await test_individual_functions()
        elif choice == "3":
            # 只查看状态
            exchange_client = ExchangeClient(API_KEY, API_SECRET, COIN_NAME, CONTRACT_TYPE)
            
            long_pos, short_pos = exchange_client.get_position()
            logger.info(f"当前持仓: 多头 {long_pos}, 空头 {short_pos}")
            
            orders = exchange_client.fetch_open_orders()
            logger.info(f"当前挂单数量: {len(orders)}")
            for order in orders:
                logger.info(f"  订单: {order['id']} - {order['side']} {order['amount']} @ {order['price']}")
        else:
            logger.error("无效选择")
            
    except KeyboardInterrupt:
        logger.info("测试被用户中断")
    except Exception as e:
        logger.error(f"测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())
